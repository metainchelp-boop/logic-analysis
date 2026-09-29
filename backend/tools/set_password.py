"""계정 비밀번호 바꾸기(서버에서만) — 공개된 데모 비밀번호 그대로라 로그인이 막힌 계정을 되살리는 길(S0).

돌리는 법(운영 컨테이너 안): ``docker exec -it ad-api python -m tools.set_password <이메일>``
- 새 비밀번호는 **화면에 보이지 않게 두 번** 묻는다(명령 줄·기록에 남지 않게 인자로 받지 않는다).
  터미널이 아니면(``-i`` 만) 표준 입력 첫 줄을 읽는다.
- 12자 이상 · 공개된 데모 비밀번호는 거절 · 찍는 것은 계정 번호와 결과뿐(이메일·비밀번호 0).
"""
from __future__ import annotations

import getpass
import sys

MIN_LEN = 12


def _ask() -> str:
    if sys.stdin.isatty():
        a = getpass.getpass("새 비밀번호: ")
        b = getpass.getpass("한 번 더: ")
        if a != b:
            raise SystemExit("두 번 넣은 값이 다릅니다 — 바꾸지 않았습니다")
        return a
    return sys.stdin.readline().rstrip("\n")


def main(argv) -> int:
    if len(argv) != 2:
        print(__doc__)
        return 1
    from app import login_guard, models, security
    from app.database import SessionLocal
    email = argv[1].strip()
    db = SessionLocal()
    try:
        user = db.query(models.User).filter(models.User.email == email).first()
        if user is None:
            print("그 이메일의 계정이 없습니다 — 바꾸지 않았습니다")
            return 1
        pw = _ask()
        if len(pw.strip()) < MIN_LEN:
            print(f"새 비밀번호는 {MIN_LEN}자 이상이어야 합니다 — 바꾸지 않았습니다")
            return 1
        if login_guard.is_any_published_demo(pw):
            print("처음 설치 때 공개된 비밀번호는 쓸 수 없습니다 — 바꾸지 않았습니다")
            return 1
        user.password_hash = security.hash_password(pw)
        db.commit()
        print(f"바꿨습니다 — 계정 번호 {user.id}")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main(sys.argv))
