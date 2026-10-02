"""값을 출력하지 않는 실행 설정. 기본 설정은 모든 외부 동작을 닫는다."""
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path
from typing import Mapping


class ConfigError(ValueError):
    pass


def _flag(env, name):
    value = env.get(name, "false").strip().lower()
    if value in ("false", "off", "0", ""):
        return False
    if value in ("true", "on", "1"):
        return True
    raise ConfigError(f"참/거짓 설정이 잘못되었습니다: {name}")


def _date(env, name):
    value = env.get(name, "").strip()
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise ConfigError(f"날짜 설정이 잘못되었습니다: {name}") from None


def _path(env, name, default):
    path = Path(env.get(name, default))
    root = Path(__file__).resolve().parents[1]
    if not path.is_absolute() or root == path or root in path.resolve().parents:
        raise ConfigError(f"코드 폴더 밖의 절대 경로가 필요합니다: {name}")
    if path.parent == Path("/") or path.name in ("", ".", ".."):
        raise ConfigError(f"전용 폴더 안의 파일 경로가 필요합니다: {name}")
    return str(path)


def _tunnel_path(value):
    # Path 정규화가 '..', 중복 '/', 끝 '/'를 숨기기 전에 원문을 검사한다.
    if (not isinstance(value, str) or not value.startswith("/") or "\0" in value
            or any(part in ("", ".", "..") for part in value.split("/")[1:])):
        raise ConfigError("ERP 터널은 정규화된 전용 UNIX 소켓 절대 경로가 필요합니다")
    try:
        if len(value.encode("utf-8")) > 100:
            raise ConfigError("ERP 터널 소켓 경로가 너무 깁니다")
    except UnicodeEncodeError:
        raise ConfigError("ERP 터널 소켓 경로가 잘못되었습니다") from None
    return _path({"socket": value}, "socket", value)


@dataclass(frozen=True)
class Config:
    db: str = field(repr=False)
    socket: str = field(repr=False)
    sync_enabled: bool = False
    links_enabled: bool = False
    morning_enabled: bool = False
    alerts_enabled: bool = False
    metrics_enabled: bool = False
    inventory_enabled: bool = False
    backup_enabled: bool = False
    web_enabled: bool = False
    issue_alerts_enabled: bool = False
    shadow_start: date | None = None
    issue_alerts_from: date | None = None
    erp_tunnel_socket: str = field(default="/run/naver-erp-tunnel/erp.sock", repr=False)

    @classmethod
    def from_env(cls, env: Mapping[str, str]):
        flags = {name.lower() + "_enabled": _flag(env, f"NAVER_ENGINE_{name}_ENABLED")
                 for name in ("SYNC", "LINKS", "MORNING", "ALERTS", "METRICS", "INVENTORY", "BACKUP", "WEB", "ISSUE_ALERTS")}
        # S16 연결 구현 후에도 기본은 꺼짐. 실제 실행은 전용 교환 키·자체 서명 값이 없으면 시작 전 거절한다.
        if flags["morning_enabled"] and not (flags["sync_enabled"] and flags["links_enabled"]):
            raise ConfigError("아침 점검에는 조직·단계 동기화와 연결 목록 설정이 모두 필요합니다")
        if flags["metrics_enabled"] and not (flags["morning_enabled"] and flags["alerts_enabled"]):
            raise ConfigError("공유 성과 전송에는 아침 점검과 알림·심박 설정이 필요합니다")
        shadow = _date(env, "NAVER_ENGINE_SHADOW_START")
        alerts_from = _date(env, "NAVER_ENGINE_ISSUE_ALERTS_FROM")
        if flags["issue_alerts_enabled"] and (not flags["alerts_enabled"] or shadow is None
                or alerts_from is None or alerts_from < shadow + timedelta(days=14)):
            raise ConfigError("광고주 이슈 알림은 14일 그림자 기간과 알림 설정을 모두 확인해야 합니다")
        db = _path(env, "NAVER_ENGINE_DB", "/var/lib/naver-engine/engine.db")
        sock = _path(env, "NAVER_ENGINE_SOCKET", "/run/naver-engine/engine.sock")
        if Path(db).resolve() == Path(sock).resolve() or Path(db).parent.resolve() == Path(sock).parent.resolve():
            raise ConfigError("저장 폴더와 소켓 폴더는 분리해야 합니다")
        tunnel = _tunnel_path(env.get("NAVER_ENGINE_ERP_TUNNEL_SOCKET", "/run/naver-erp-tunnel/erp.sock"))
        return cls(db, sock, **flags, shadow_start=shadow, issue_alerts_from=alerts_from,
                   erp_tunnel_socket=tunnel)

    def validate_runtime(self, env: Mapping[str, str]):
        """승인된 ERP 다섯 경로만 조립한다. 독립 core 예약 시험의 설정은 바꾸지 않는다."""
        if self.alerts_enabled or self.metrics_enabled or self.issue_alerts_enabled:
            raise ConfigError("제한판 실행은 ERP 알림·심박·성과 전송을 지원하지 않습니다")
        tunnel = Path(_tunnel_path(self.erp_tunnel_socket)).parent.resolve()
        backup = Path(env.get("NAVER_ENGINE_BACKUP_DIR", "/var/backups/naver-engine"))
        if not backup.is_absolute() or backup == Path("/"):
            raise ConfigError("백업 전용 절대 경로가 필요합니다")
        for other in (Path(self.db).parent.resolve(), Path(self.socket).parent.resolve(), backup.resolve()):
            if tunnel == other or tunnel in other.parents or other in tunnel.parents:
                raise ConfigError("ERP 터널 폴더는 저장·웹 소켓·백업 폴더와 겹칠 수 없습니다")

    def switches(self):
        return {name: value for name, value in (
            ("sync", self.sync_enabled), ("links", self.links_enabled),
            ("morning", self.morning_enabled), ("alerts", self.alerts_enabled),
            ("metrics", self.metrics_enabled),
            ("inventory", self.inventory_enabled),
            ("backup", self.backup_enabled), ("web", self.web_enabled),
            ("issue_alerts", self.issue_alerts_enabled))}
