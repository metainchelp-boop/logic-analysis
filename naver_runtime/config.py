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


@dataclass(frozen=True)
class Config:
    db: str = field(repr=False)
    socket: str = field(repr=False)
    sync_enabled: bool = False
    links_enabled: bool = False
    morning_enabled: bool = False
    alerts_enabled: bool = False
    metrics_enabled: bool = False
    backup_enabled: bool = False
    web_enabled: bool = False
    issue_alerts_enabled: bool = False
    shadow_start: date | None = None
    issue_alerts_from: date | None = None

    @classmethod
    def from_env(cls, env: Mapping[str, str]):
        flags = {name.lower() + "_enabled": _flag(env, f"NAVER_ENGINE_{name}_ENABLED")
                 for name in ("SYNC", "LINKS", "MORNING", "ALERTS", "METRICS", "BACKUP", "WEB", "ISSUE_ALERTS")}
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
        return cls(db, sock, **flags, shadow_start=shadow, issue_alerts_from=alerts_from)

    def switches(self):
        return {name: value for name, value in (
            ("sync", self.sync_enabled), ("links", self.links_enabled),
            ("morning", self.morning_enabled), ("alerts", self.alerts_enabled),
            ("metrics", self.metrics_enabled),
            ("backup", self.backup_enabled), ("web", self.web_enabled),
            ("issue_alerts", self.issue_alerts_enabled))}
