"""S0 점검 도구 — 값은 하나도 찍지 않고 상태(출처 · 사유 이름 · 개수)만 찍는다.

돌리는 법(운영 컨테이너 안): ``docker exec ad-api python -m tools.check_secrets``
로컬: backend 폴더에서 ``python -m tools.check_secrets``
찍는 것: 로그인 서명 값의 출처(env · derived)와 환경 값을 안 쓴 까닭 · 암호화 키 파일 권한 · 공개 데모 비밀번호 그대로인
계정 수 · 쓸 수 있는 관리자 수 · CORS 로 열어 둔 주소 수 · 최근 10분 로그인 실패 줄 수. 이메일·비밀번호·키 값은 0.
"""
from __future__ import annotations

import os
import stat
import sys


def main() -> int:
    from app import cors_policy, login_guard, models, security
    from app.database import SessionLocal

    print(f"로그인 서명 값 — 출처: {security.JWT_SOURCE}(env = 환경 값 · derived = 서버가 만든 값) · "
          f"환경 값을 안 쓴 까닭: {security.JWT_REASON}")
    f = security._KEY_FILE
    if f.exists():
        mode = stat.S_IMODE(f.stat().st_mode)
        print(f"암호화 키 파일 — 있음 · 권한 {mode:o}{' (600 이 아님 — chmod 600 으로 좁히세요)' if mode & 0o077 else ''}")
    else:
        print("암호화 키 파일 — 없음(앱이 아직 한 번도 안 떴음)")
    origins, dropped = cors_policy.allowed_origins(os.environ.get("CORS_ALLOW_ORIGINS"))
    print(f"CORS — 열어 둔 주소 {len(origins)}개 · 모양이 틀려 버린 값 {dropped}개")
    db = SessionLocal()
    try:
        n, a = login_guard.demo_status(db)
        admins = db.query(models.User).filter(models.User.role == "admin").all()
        usable = sum(1 for u in admins if not login_guard.still_on_demo_password(u))
        print(f"데모 계정 — 공개 비밀번호 그대로 {n}개(그중 관리자 {a}개) · 쓸 수 있는 관리자 {usable}명")
        if a and not usable:
            print("  ⚠ 쓸 수 있는 다른 관리자가 없어 데모 관리자는 막지 않고 경고만 남깁니다 — python -m tools.set_password <이메일> 로 비밀번호를 바꾸거나 전산 SSO 계정을 관리자로 지정하세요")
        try:
            print(f"로그인 실패 — 최근 10분 {login_guard.recent_count()}줄")
        except Exception as e:
            print(f"로그인 실패 — 표를 읽지 못함({type(e).__name__})")
    finally:
        db.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
