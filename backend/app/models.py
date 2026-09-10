"""데이터 모델 — 직원(User)→팀(Team)→광고주(Client)→채널키(ChannelCredential)."""
from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey
from sqlalchemy.sql import func

from .database import Base


class Team(Base):
    __tablename__ = "teams"
    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)


class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True)
    email = Column(String, unique=True, index=True, nullable=False)
    name = Column(String, nullable=False)
    password_hash = Column(String, nullable=False)
    role = Column(String, nullable=False, default="staff")  # staff | lead | admin
    team_id = Column(Integer, ForeignKey("teams.id"))


class Client(Base):
    __tablename__ = "clients"
    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)
    category = Column(String)
    # active | paused | ended | delete_requested(삭제요청, 대표 승인 대기) | archived(보관소, 기능 일시정지·데이터는 학습용 보존)
    status = Column(String, default="active")
    delete_requested_by = Column(Integer, ForeignKey("users.id"))
    delete_requested_at = Column(String)
    owner_id = Column(Integer, ForeignKey("users.id"))
    team_id = Column(Integer, ForeignKey("teams.id"))
    contact = Column(String)
    contract_start = Column(String)
    contract_end = Column(String)          # 계약 종료일(전산 계약 종료일 동기화)
    biz_reg_name = Column(String)          # 사업자 등록 상호명(전산 보조 매칭)
    erp_possibility_id = Column(Integer, index=True)  # 전산 가망 PK(안정 매칭)
    sales_manager = Column(String)         # 전산 영업 담당자
    db_grade = Column(String)              # 전산 DB 등급(S/A/B/C)
    memo = Column(Text)
    created_at = Column(DateTime, server_default=func.now())


class ChannelMetric(Base):
    """정기 수집된 채널 성과 스냅샷 — 1행 = 광고주×채널×수집시각."""
    __tablename__ = "channel_metrics"
    id = Column(Integer, primary_key=True)
    client_id = Column(Integer, ForeignKey("clients.id"), index=True)
    channel = Column(String, nullable=False, index=True)
    payload_json = Column(Text, default="{}")  # fetch_performance 결과 그대로
    collected_at = Column(DateTime, server_default=func.now())


class Report(Base):
    """AI 결과보고서 — 기간 지정 생성, 피드백 4단계(진단·개선·방향성·전략) 포함."""
    __tablename__ = "reports"
    id = Column(Integer, primary_key=True)
    client_id = Column(Integer, ForeignKey("clients.id"), index=True)
    date_from = Column(String, nullable=False)
    date_to = Column(String, nullable=False)
    data_json = Column(Text, default="{}")     # 기간 성과 원본(캠페인·합계)
    report_json = Column(Text, default="{}")   # AI 산출(결론·피드백 4단계)
    created_by = Column(Integer, ForeignKey("users.id"))
    created_at = Column(DateTime, server_default=func.now())


class ConnectLink(Base):
    """광고주 자가 키 입력 링크 — 마케터가 생성해 광고주에게 발송, 광고주가 로그인 없이 키만 입력.

    토큰 기반·만료식. 특정 광고주 1명에게만 유효하며, 입력 키는 암호화 저장된다.
    """
    __tablename__ = "connect_links"
    id = Column(Integer, primary_key=True)
    client_id = Column(Integer, ForeignKey("clients.id"), index=True)
    token = Column(String, unique=True, index=True, nullable=False)
    channels_json = Column(Text, default="[]")  # 요청 채널 키 목록
    created_by = Column(Integer, ForeignKey("users.id"))
    created_at = Column(DateTime, server_default=func.now())
    expires_at = Column(String)   # ISO(KST)
    used_at = Column(String)      # 마지막 제출 시각
    submit_count = Column(Integer, default=0)


class ActivityLog(Base):
    """광고주 진행 이력 — 등록 시점부터 모든 작업을 시간순 기록(이력 추적·운영 내역서용).

    type 예: client_created, client_updated, channel_connected, report_created,
             upload, manual_entry, status_changed, metric_collected
    """
    __tablename__ = "activity_logs"
    id = Column(Integer, primary_key=True)
    client_id = Column(Integer, ForeignKey("clients.id"), index=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    user_name = Column(String)  # 기록 당시 담당자 이름(사용자 변경돼도 이력 보존)
    type = Column(String, nullable=False)
    message = Column(String, nullable=False)
    meta_json = Column(Text, default="{}")
    created_at = Column(DateTime, server_default=func.now())


class CampaignProposal(Base):
    """AI 캠페인 제안 — 실제 광고주 데이터로 AI가 설계한 다음 기간 캠페인안.

    제안 생성(draft)은 광고팀(editor)이, 실제 검색광고 적용(applied)은 대표(admin)만.
    실제 적용은 항상 ① 미리보기(dry-run) → ② 명시 확인 → ③ '일시중지' 상태로 생성 순서.
    """
    __tablename__ = "campaign_proposals"
    id = Column(Integer, primary_key=True)
    client_id = Column(Integer, ForeignKey("clients.id"), index=True)
    objective = Column(String)              # 목표(매출 성장·전환·노출 등, 자유 입력)
    monthly_budget = Column(Integer)        # 월 광고 예산(원)
    proposal_json = Column(Text, default="{}")       # AI 산출 캠페인안(채널믹스·검색광고 세팅·예상성과)
    status = Column(String, default="draft")          # draft | applied | discarded
    apply_result_json = Column(Text, default="{}")    # 실제 적용 결과(또는 마지막 dry-run 미리보기)
    created_by = Column(Integer, ForeignKey("users.id"))
    created_at = Column(DateTime, server_default=func.now())
    applied_by = Column(Integer, ForeignKey("users.id"))
    applied_at = Column(String)             # ISO(KST) 실제 적용 시각


class SetupProposal(Base):
    """네이버 검색광고 AI 세팅 제안 — 제안(draft) → 담당자 선택·승인 → 실계정 적용(applied).

    items_json 의 각 항목이 하나의 변경(입찰가·키워드 중지·키워드 추가·예산)이며,
    담당자가 체크한 것만 적용된다. 적용 결과는 항목별 성공/실패로 result_json 에 남는다.
    ★적용은 항상 confirm=True 를 명시해야 하고, 변경폭은 어댑터가 ±50% 로 잘라낸다.
    """
    __tablename__ = "setup_proposals"
    id = Column(Integer, primary_key=True)
    client_id = Column(Integer, ForeignKey("clients.id"), index=True)
    summary = Column(String)                        # 제안 전체 요약 한 줄
    diagnosis_json = Column(Text, default="{}")     # 같이 생성된 AI 진단
    items_json = Column(Text, default="[]")         # 변경 제안 목록
    status = Column(String, default="draft")        # draft | applied | discarded
    result_json = Column(Text, default="{}")        # 항목별 적용 결과
    created_by = Column(Integer, ForeignKey("users.id"))
    created_at = Column(DateTime, server_default=func.now())
    applied_by = Column(Integer, ForeignKey("users.id"))
    applied_at = Column(String)                     # ISO(KST)


class ClientSetting(Base):
    """광고주별 설정 키-값 저장 — 오토파일럿 규칙·리포트 예약 등 확장용.

    (client_id, key) 유일. value_json에 JSON 직렬화된 설정을 보관.
    """
    __tablename__ = "client_settings"
    id = Column(Integer, primary_key=True)
    client_id = Column(Integer, ForeignKey("clients.id"), index=True)
    key = Column(String, nullable=False, index=True)   # autopilot | report_schedule
    value_json = Column(Text, default="{}")
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())


class ChannelCredential(Base):
    __tablename__ = "channel_credentials"
    id = Column(Integer, primary_key=True)
    client_id = Column(Integer, ForeignKey("clients.id"))
    # naver_commerce | naver_searchad | kakao | youtube | meta_chehum | daangn
    channel = Column(String, nullable=False)
    mode = Column(String, default="direct")  # delegated | direct | upload
    status = Column(String, default="disconnected")  # connected | disconnected
    fields_json = Column(Text, default="{}")  # {field: encrypted_value}
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())


class MonthlyRecord(Base):
    """월별 소진 '확정 기록' — 1일~말일 마감값을 영구 보관.

    스펜딩 소진현황(실시간·월초~현재 누적·덮어쓰기식)과 분리. 월 마감 시 스냅샷을 떠
    저장하므로 다음 달 업로드가 지난달 기록을 건드리지 않는다. (month, client)당 1행.
    """
    __tablename__ = "monthly_records"
    id = Column(Integer, primary_key=True)
    month = Column(String, nullable=False, index=True)   # "YYYY-MM"
    client_id = Column(Integer, ForeignKey("clients.id"), index=True)
    client_name = Column(String)                          # 기록 시점 광고주명 스냅샷
    total_spend = Column(Integer, default=0)
    channels_json = Column(Text, default="[]")            # [{channel,label,spend}]
    recorded_at = Column(DateTime, server_default=func.now())
    recorded_by = Column(Integer, ForeignKey("users.id"))
    recorded_by_name = Column(String)
