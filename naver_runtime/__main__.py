"""실행·설정 확인. import/check-config/dry-run은 연결·파일 생성·키 조회를 하지 않는다."""
import argparse
import json
import logging
import os
from pathlib import Path
import platform
import signal
import sys
import threading

from naver_engine import alerts as A, erp_read as E, naver_read as N
from naver_engine import erp_profile as EP, session as SE, store as S, web as WEB
from naver_engine.backup import BackupJob
from naver_engine.credentials import load_manager_credentials
from naver_runtime.backup_transport import OpenSslEncryptor, SshSender
from naver_runtime.config import Config, ConfigError
from naver_runtime.erp_tunnel_transport import ErpTunnelTransport
from naver_runtime.scheduler import Scheduler
from naver_runtime.collection_requests import CollectionClock
from naver_runtime.server import UnixServer, health_app
from naver_runtime.writer import Writer
from naver_runtime import bootstrap as B

log = logging.getLogger("naver_runtime")


class StopRequested(BaseException):
    """외부 조회를 더 시작하지 않고 실행 중 회차의 정리 구문으로 빠진다."""


class InterruptibleClock(N.SystemClock):
    def __init__(self, stop):
        self.stop, self.interrupted = stop, False

    def _check(self):
        if self.stop.is_set() and not self.interrupted:
            self.interrupted = True
            raise StopRequested()

    def now(self):
        self._check()
        return super().now()

    def sleep(self, seconds):
        self.stop.wait(seconds)
        self._check()

    def before_network(self):
        # now()는 중단된 회차의 정리를 위해 한 번만 예외를 내지만, 새 HTTP 송신은
        # 그 뒤에도 계속 막는다. 고정 now를 쓰는 알림 dispatch 내부에도 적용한다.
        if self.stop.is_set():
            self.interrupted = True
            raise StopRequested()


class StopAwareTransport:
    """기존 core HTTP 관문에 위임하며 중지 뒤 새 송신만 차단한다."""
    def __init__(self, clock, transport=None):
        self._clock = clock
        self._transport = transport if transport is not None else N.UrllibTransport()

    def send(self, request, timeout):
        self._clock.before_network()
        if isinstance(self._clock, (MetricsClock, B.BootstrapClock, CollectionClock)):
            timeout = min(timeout, self._clock.remaining())
        return self._transport.send(request, timeout)


class MetricsClock:
    """공유 성과 차례의 재시도·속도제한 대기가 다음 예약 작업을 붙잡지 않게 한다."""
    def __init__(self, base, seconds=45):
        self.base = base
        self.deadline = base.monotonic() + seconds

    def remaining(self):
        self.base.before_network()
        left = self.deadline - self.base.monotonic()
        if left <= 0:
            raise N.RunAbort('metrics-time-budget')
        return left

    def before_network(self):
        self.remaining()

    def now(self):
        self.remaining()
        return self.base.now()

    def epoch_ms(self):
        self.remaining()
        return self.base.epoch_ms()

    def monotonic(self):
        self.remaining()
        return self.base.monotonic()

    def sleep(self, seconds):
        if seconds >= self.remaining():
            raise N.RunAbort('metrics-time-budget')
        self.base.sleep(seconds)
        self.remaining()


def dependencies(config, env, clock):
    """켜진 기능에 필요한 키만 읽는다. 이 함수는 업무 API를 호출하지 않는다."""
    config.validate_runtime(env)
    erp_factory = naver_factory = alert_factory = metrics_factory = backup_job = None
    if config.sync_enabled or config.links_enabled:
        key = E.load_erp_key(env)
        erp_factory = lambda: E.ErpReader(key, clock=clock, transport=StopAwareTransport(
            clock, ErpTunnelTransport(config.erp_tunnel_socket)))
    if config.links_enabled or config.morning_enabled:
        credentials = load_manager_credentials(env)
        naver_factory = lambda: N.NaverReader(credentials, clock=clock, transport=StopAwareTransport(clock))
    if config.backup_enabled:
        names = ("NAVER_BACKUP_CERT", "NAVER_BACKUP_SSH_KEY", "NAVER_BACKUP_KNOWN_HOSTS")
        if any(not env.get(name) for name in names):
            raise ConfigError("백업 공개 인증서·업로드키·호스트키 파일 설정이 필요합니다")
        root = Path(env.get("NAVER_ENGINE_BACKUP_DIR", "/var/backups/naver-engine"))
        code_root = Path(__file__).resolve().parents[1]
        if (not root.is_absolute() or root == Path("/") or code_root == root.resolve()
                or code_root in root.resolve().parents or root.resolve() in (Path(config.db).parent.resolve(),
                                                                            Path(config.socket).parent.resolve())):
            raise ConfigError("코드·저장·소켓 폴더와 다른 백업 전용 절대 경로가 필요합니다")
        encrypt = OpenSslEncryptor(env[names[0]])
        send = SshSender(env[names[1]], env[names[2]])
        backup_job = BackupJob(root, encrypt, send)
    return dict(erp_factory=erp_factory, naver_factory=naver_factory,
                alert_factory=alert_factory, metrics_factory=metrics_factory, backup_job=backup_job)


def note_orphaned(store, now):
    if store.orphaned_runs:
        A.record_system_alert(store, now, "morning", ["RUN_ORPHANED"])


def combine_web(status, web):
    """내부 건강 확인을 보존하고, 켜진 경우에만 관제 경로를 넘긴다."""
    health = health_app(status)
    def app(environ, start_response):
        if web is not None and (environ.get('PATH_INFO') or '').startswith(WEB.PREFIX + '/'):
            return web(environ, start_response)
        return health(environ, start_response)
    return app


def run(config, env, *, stop=None):
    stop = stop if stop is not None else threading.Event()
    clock = InterruptibleClock(stop)
    options = dependencies(config, env, clock)
    profiles = signer = None
    if config.web_enabled:
        profiles = EP.ErpProfileReader(env=env, transport=StopAwareTransport(
            clock, ErpTunnelTransport(config.erp_tunnel_socket)))
        profiles.require_configured()
        signer = SE.TokenSigner(SE.load_token_secret(env))
    state = {"state": "starting", "switches": config.switches(), "last_tick": None}
    state_lock = threading.Lock()

    def status():
        with state_lock:
            return dict(state)

    # 저장소의 정리용 시계는 중지 신호로 중단하지 않는다.
    with Writer(config.db, clock=N.SystemClock().now) as writer:
        writer.call(lambda st: note_orphaned(st, N.SystemClock().now()))
        def collection_factory():
            bounded = CollectionClock(clock, seconds=600)
            deps = dependencies(config, env, bounded)
            return dict(clock=bounded, erp_factory=deps["erp_factory"], naver_factory=deps["naver_factory"])
        scheduler = Scheduler(config, writer.proxy, clock=clock.now,
                              collection_factory=collection_factory, **options)
        # 읽기 연결은 요청 스레드에서 열고 닫으며, 쓰기는 기존 단일 소유자 큐만 지난다.
        web = WEB.App(open_read=lambda: S.open_reader(config.db), write=writer.call,
                      signer=signer, profiles=profiles, owner_verification=True, verified_linking=True,
                      request_collection=scheduler.request_collection,
                      collection_status=scheduler.collection_status) if config.web_enabled else None
        with UnixServer(config.socket, combine_web(status, web)):
            # WEB는 이미 별도 스레드에서 열린 상태. 관리 단발 작업을 예약 회차보다 먼저 실행한다.
            # 환경값이 없으면 bootstrap 파일/영수증/스냅샷 경로를 전혀 조회하지 않는다.
            if env.get("NAVER_ENGINE_BOOTSTRAP_REQUEST"):
                try:
                    bootstrap = B.execute(config, env, writer, clock,
                                          lambda bounded: dependencies(config, env, bounded))
                    with state_lock:
                        state["bootstrap"] = bootstrap
                except StopRequested:
                    return 0
            while not stop.is_set():
                with state_lock:
                    state.update(state="running")
                try:
                    result = scheduler.tick()
                except StopRequested:
                    break
                except Exception as exc:
                    log.error("예약 회차 실패: %s", type(exc).__name__)
                    result = {"state": "failed", "errors": ["scheduler"]}
                with state_lock:
                    state.update(result, last_tick=N.SystemClock().now().isoformat())
                    backup = options.get("backup_job")
                    if backup is not None:
                        state["backup"] = backup.status()
                stop.wait(60)
    return 0


def main(argv=None, *, env=None):
    parser = argparse.ArgumentParser(description="네이버 읽기 전용 관제 실행 장치 (배포 명령 아님)")
    parser.add_argument("command", choices=("check-config", "dry-run", "run"))
    args = parser.parse_args(argv)
    env = os.environ if env is None else env
    try:
        config = Config.from_env(env)
        config.validate_runtime(env)
        if args.command != "run":
            print(json.dumps({"command": args.command, "configuration": "valid", "switches": config.switches(),
                              "network_performed": False, "storage_opened": False,
                              "credentials_verified": False, "web_available": False,
                              "deployment_ready": False}, ensure_ascii=False))
            return 0
        if platform.system() != "Linux":
            raise ConfigError("실행은 Linux 전용입니다. 다른 환경에서는 설정 확인·무통신 시험만 사용합니다")
        stop = threading.Event()
        prior = {sig: signal.signal(sig, lambda *_: stop.set()) for sig in (signal.SIGTERM, signal.SIGINT)}
        try:
            return run(config, env, stop=stop)
        finally:
            for sig, handler in prior.items():
                signal.signal(sig, handler)
    except Exception as exc:
        # 예외 메시지에 키·경로·업체 정보가 있어도 출력하지 않는다.
        print(json.dumps({"error": "startup-refused", "kind": type(exc).__name__}), file=sys.stderr)
        return 2


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    raise SystemExit(main())
