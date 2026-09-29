"""초기 데모 데이터 — 팀/직원/샘플 광고주. (사용자가 없을 때만 1회 생성)"""
import json
from .database import SessionLocal
from . import models, security

# 처음 설치 때 만드는 데모 계정의 비밀번호 — 예전 화면(app.js)과 문서에 공개됐다(S0).
# 이 비밀번호 그대로인 계정은 비밀번호 로그인이 막힌다(login_guard · 관리자 길을 끊지 않는 경우만 예외).
# 이 값을 로그·화면·문서에 옮겨 적지 않는다.
DEMO_PASSWORDS = {
    "admin@metainc.co.kr": "admin1234",
    "lead@metainc.co.kr": "lead1234",
    "kim@metainc.co.kr": "kim1234",
    "viewer@metainc.co.kr": "viewer1234",
}


def run():
    db = SessionLocal()
    try:
        if db.query(models.User).first():
            return  # 운영 전환: 계정이 하나라도 있으면 데모 시드 안 함(재생성 금지)

        team1 = models.Team(name="1팀")
        team2 = models.Team(name="2팀")
        db.add_all([team1, team2])
        db.flush()

        admin = models.User(
            email="admin@metainc.co.kr", name="대표",
            password_hash=security.hash_password(DEMO_PASSWORDS["admin@metainc.co.kr"]),
            role="admin", team_id=team1.id,
        )
        lead = models.User(
            email="lead@metainc.co.kr", name="이팀장",
            password_hash=security.hash_password(DEMO_PASSWORDS["lead@metainc.co.kr"]),
            role="lead", team_id=team1.id,
        )
        kim = models.User(
            email="kim@metainc.co.kr", name="김마케터",
            password_hash=security.hash_password(DEMO_PASSWORDS["kim@metainc.co.kr"]),
            role="staff", team_id=team1.id,
        )
        viewer = models.User(
            email="viewer@metainc.co.kr", name="정직원(읽기전용)",
            password_hash=security.hash_password(DEMO_PASSWORDS["viewer@metainc.co.kr"]),
            role="viewer", team_id=team2.id,
        )
        db.add_all([admin, lead, kim, viewer])
        db.flush()

        c1 = models.Client(
            name="건강한밥상", category="식품 · 건강식품", status="active",
            owner_id=kim.id, team_id=team1.id, contact="010-1234-5678",
            contract_start="2026-01-15",
        )
        c2 = models.Client(
            name="아이루 펫푸드", category="반려동물", status="active",
            owner_id=kim.id, team_id=team1.id, contract_start="2026-03-02",
        )
        db.add_all([c1, c2])
        db.flush()

        # 샘플 채널 키 (암호화 저장)
        db.add(models.ChannelCredential(
            client_id=c1.id, channel="naver_commerce", mode="direct", status="connected",
            fields_json=json.dumps({
                "app_id": security.encrypt("DEMO_APP_3f7a"),
                "app_secret": security.encrypt("DEMO_SECRET_9921"),
            }),
        ))
        db.add(models.ChannelCredential(
            client_id=c1.id, channel="naver_searchad", mode="delegated", status="connected",
            fields_json=json.dumps({"customer_id": security.encrypt("1234567")}),
        ))
        db.commit()
        print("✅ 데모 데이터 생성 완료(데모 계정 4개 — 공개된 비밀번호 그대로면 로그인이 막힙니다 · S0)")
    finally:
        db.close()


def _ensure_viewer(db):
    """읽기 전용 데모 계정이 없으면 추가 (기존 데이터는 건드리지 않음)."""
    if db.query(models.User).filter(models.User.email == "viewer@metainc.co.kr").first():
        return
    team = db.query(models.Team).first()
    db.add(models.User(
        email="viewer@metainc.co.kr", name="정직원(읽기전용)",
        password_hash=security.hash_password(DEMO_PASSWORDS["viewer@metainc.co.kr"]),
        role="viewer", team_id=team.id if team else None,
    ))
    db.commit()
    print("✅ 읽기전용 데모 계정 추가(공개된 비밀번호 그대로면 로그인이 막힙니다 · S0)")
