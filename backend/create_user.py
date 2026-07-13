"""실제 직원 계정 생성 도구.

사용법 (backend 폴더에서, 가상환경 활성화 후):
    python create_user.py <이메일> <이름> <역할> <비밀번호> [팀ID]

역할(role):
    admin   대표·관리자 (전체)
    lead    팀장 (팀 전체)
    staff   광고팀 담당자 (본인 담당)
    viewer  읽기 전용 (전 직원)

예:
    python create_user.py ad1@metainc.co.kr 박광고 staff Pw!2026
"""
import sys
from app.database import SessionLocal, Base, engine
from app import models, security

Base.metadata.create_all(bind=engine)

ROLES = {"admin", "lead", "staff", "viewer"}


def main():
    if len(sys.argv) < 5 or sys.argv[3] not in ROLES:
        print(__doc__)
        sys.exit(1)
    email, name, role, password = sys.argv[1:5]
    team_id = int(sys.argv[5]) if len(sys.argv) > 5 else None

    db = SessionLocal()
    try:
        if db.query(models.User).filter(models.User.email == email).first():
            print(f"⚠️ 이미 존재하는 이메일입니다: {email}")
            sys.exit(1)
        db.add(models.User(
            email=email, name=name, role=role,
            password_hash=security.hash_password(password),
            team_id=team_id,
        ))
        db.commit()
        print(f"✅ 계정 생성 완료: {name} <{email}> · 역할={role}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
