# 전산(ERP) ↔ 광고센터 계약 연동 API 명세

> # ⚠️ 이 문서는 초안(구버전)입니다 — 기준 문서 아님 (2026-07-10)
>
> **권위 문서 = 전산 리포(`metainc-web-backend`) 루트의 `ERP_CONTRACT_SYNC_API.md`** (섹션 B가 실제 구현 기준으로 작성).
> 이 초안은 실제 구현과 아래 3군데가 달라 **그대로 믿으면 안 됩니다**:
>
> 1. **응답 래핑** — 아래 본문은 최상위 `{total,page,size,items[]}` 로 적혀 있으나,
>    실제는 **`{"status":200,"result":{"total":N,"items":[...]}}`** (`result` 언랩 필요).
> 2. **`ad_center_registered`** — 본문에 없으나, 실제로는 **광고주 자동생성 게이트**로 쓰이는 계약 필드.
> 3. **페이징** — 본문의 `page`/`size` 는 **미구현**. 실제는 **전량 반환(무페이징)** 이 계약.
>    (전산이 페이징 도입 시 사전 통지 확약 → 그때 광고센터에 페이징 구현할 것.)
>
> 이력용으로만 남겨둡니다. 수정·참조는 전산 리포 문서로.

> 목적: 전산 "가망 관리"에서 **계약 상품이 등록되고 업무 단계가 "진행중"으로 전환**되면,
> 그 광고주의 **계약기간(계약일·종료일)·담당자·기본정보**를 광고센터(dashboard.metainc.co.kr)가
> 자동으로 받아 광고주 정보에 반영한다. 계약 데이터는 여러 화면에서 재사용되므로 범용 구조로 설계.

- 전산 호스트: `http://api.metainc.co.kr` (백엔드, Spring)
- 광고센터 호스트: `https://dashboard.metainc.co.kr` (FastAPI)
- **매칭 키: 상호명(company_name) = 광고센터 광고주명(client.name).**
  - 보조 키: 사업자 등록 상호명(biz_reg_name), 그리고 전산 내부 식별자 `possibility_id`(가망 PK).
  - 권장: 최초 1회 상호명으로 매칭한 뒤 `possibility_id`를 광고센터에 저장해 이후엔 ID로 안정 매칭.

---

## 방식 개요 (둘 다 권장: 조회 + 푸시)

| 방식 | 방향 | 용도 |
|---|---|---|
| **① 조회 API (Pull)** | 광고센터 → 전산 호출 | 정기 동기화·과거분 일괄 보정·단건 조회. 기본·필수 |
| **② Webhook (Push)** | 전산 → 광고센터 호출 | "진행중 전환" 즉시 실시간 반영. 권장(선택) |

먼저 **① 조회 API**만 있어도 동작합니다(광고센터가 매일/등록 시 호출). ②는 실시간이 필요할 때 추가.

---

## ① 조회 API — 전산이 제공 (광고센터가 호출)

### `GET /api/ad-sync/contracts`

**인증:** 광고센터 전용 서비스 키. 헤더 `X-Api-Key: <발급키>` (또는 서비스계정 JWT — 제안서 연동과 동일 패턴).

**Query 파라미터 (모두 선택):**

| 파라미터 | 예 | 설명 |
|---|---|---|
| `stage` | `진행중` | 업무 단계 필터. 기본값 `진행중`. (전체는 `all`) |
| `has_contract` | `true` | 계약 상품이 1건 이상 등록된 건만. 기본 `true` |
| `updated_since` | `2026-06-01T00:00:00+09:00` | 이 시각 이후 **변경된 건만**(증분 동기화용) |
| `name` | `옥수주조` | 상호명 단건 조회 |
| `page` / `size` | `1` / `100` | 페이징 |

**응답 (200):**

```json
{
  "total": 152,
  "page": 1,
  "size": 100,
  "items": [
    {
      "possibility_id": 83071,
      "company_name": "옥수주조",
      "biz_reg_name": "옥수주조",
      "store_url": "https://smartstore.naver.com/oksujujo",
      "category": "스마트스토어",
      "owner_name": "김진영",
      "phone": "010-2055-3943",
      "address": "서울특별시 성동구 한림말5길 23 1층",
      "email": "oksujujo@naver.com",
      "db_grade": "C",
      "sales_manager": "최진혁",
      "stage": "진행중",
      "stage_changed_at": "2026-05-13T10:40:08+09:00",
      "contracts": [
        {
          "round": 1,
          "product": "정규300",
          "start_date": "2026-06-11",
          "end_date": "2026-06-17",
          "amount": 3000000,
          "type": "일반",
          "is_upsell": false
        }
      ],
      "updated_at": "2026-06-13T10:40:08+09:00"
    }
  ]
}
```

**필드 의미 (가망 업체 수정 화면 대응):**

| 응답 필드 | 전산 화면 | 비고 |
|---|---|---|
| `possibility_id` | URL `possibilityCompanyModify/{id}` | 가망 PK(안정 매칭용) |
| `company_name` | 상호명 | **매칭 키** |
| `biz_reg_name` | 사업자 등록 상호명 | 보조 매칭 |
| `store_url` | 업체 링크 | |
| `owner_name` | 대표 이름 | |
| `sales_manager` | 영업 담당자 | |
| `db_grade` | DB 등급(S/A/B/C) | |
| `stage` | 업무 진행 단계 | 아래 매핑 참고 |
| `contracts[].start_date` | 계약 상품 · 계약일 | **계약 시작일** |
| `contracts[].end_date` | 계약 상품 · 종료일 | **계약 종료일** |
| `contracts[].amount` | 계약 상품 · 계약금액 | |
| `contracts[].round` | 1차 / 2차 업셀링 | `is_upsell`로 2차 구분 |

> 계약기간 = `contracts` 중 활성 차수의 `start_date` ~ `end_date`.
> 여러 차수면 광고센터가 **min(start) ~ max(end)** 로 합산하거나 1차 기준 사용(광고센터에서 처리).

---

## ② Webhook (선택) — 전산이 광고센터로 푸시

**트리거:** 가망 업체의 **업무 단계가 "진행중"으로 전환**되거나, **계약 상품이 등록/수정**될 때.
(전산 화면 안내문 "인수인계 전달 시 업무 단계가 자동으로 진행중으로 전환됩니다"의 그 시점)

### `POST https://dashboard.metainc.co.kr/api/erp/contract-webhook`

**인증:** 헤더 `X-Webhook-Secret: <공유 비밀키>` (광고센터·전산만 아는 값).

**Body:** ① 응답의 `items[]` 한 건과 동일한 형태 + 이벤트 타입.

```json
{
  "event": "stage_changed_to_active",   // 또는 "contract_updated"
  "occurred_at": "2026-06-13T10:40:08+09:00",
  "company": { /* ① items[] 한 건과 동일 구조 */ }
}
```

**광고센터 동작:** `company_name`(또는 `possibility_id`)으로 광고주를 찾아 계약기간·담당자·기본정보 upsert.
일치 광고주가 없으면 "전산 신규 계약" 알림으로 보류(자동 생성은 옵션).

---

## 업무 단계 ↔ 광고센터 상태 매핑

| 전산 업무 단계 | 광고센터 status | 비고 |
|---|---|---|
| 진행중 | `active` (진행중) | 계약 활성 |
| 홀딩중 | `paused` (일시정지) | |
| 환불중 | `paused` (일시정지) | |
| 계약 만료 | `ended` (종료) | |
| 사후 관리 | `archived` (사후관리/보관) | ← 광고센터 "사후관리"와 일치 |
| 블랙 리스트 | (동기화 제외) | |
| 전략 관리 | `active` (진행중) 유지 | |

---

## 광고센터(수신) 측 준비 — 함께 구현 필요

- Client 모델 필드 추가: `contract_end`(종료일), `biz_reg_name`, `erp_possibility_id`(전산 PK), `sales_manager`(영업담당), `db_grade`.
- 동기화 엔드포인트: `POST /api/erp/contract-webhook`(수신) + 정기 배치(매일 06시 수집기와 함께 ① 조회 API 호출).
- 매칭: `company_name`==`client.name` → 계약기간 채움. 단계 매핑으로 status 반영(옵션, 대표 승인 후).

---

## 보안

- 조회 API 키 / Webhook 시크릿은 양측 서버 환경변수에만 보관(코드·화면 노출 금지).
- 광고센터는 **회원 개인정보(소비자)는 받지 않음** — 광고주(업체) 정보·계약만.
- HTTPS 전송. Webhook은 시크릿 헤더 불일치 시 401.

---

## 도입 순서(권장)

1. 전산: `GET /api/ad-sync/contracts` 조회 API 구현 + 서비스 키 발급.
2. 광고센터: Client에 계약 필드 추가 + 매일 조회 동기화(상호명 매칭) → 계약기간 자동 채움.
3. (실시간 필요 시) 전산: 진행중 전환 Webhook 추가 → 광고센터 수신 엔드포인트 연동.
