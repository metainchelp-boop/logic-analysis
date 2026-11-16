# 승인 명세 구현 계획

2026-10-18 대화창에서 명세 승인과 구현·검증 지시를 받았다. `writing-plans` 스킬은 현재 설치되어 있지 않아 동일 목적의 계획을 이 문서에 기록한다.

1. SEO 전용 읽기 진단: 기존 debug-rank의 SEO 모드만 실행. 비밀값/원문 없이 공급자 오류 분류·보존 시점을 확인한다. 진단 자체를 가짜 Docker 출력으로 먼저 검사한다.
2. 저장 자료 근거: `seo_evidence.py`로 캐시만 읽고 업체 연결 상품을 제공한다. 가짜 DB에서 누락·중복·오래됨·출처 미확인을 검증하고 외부 연결/큐 쓰기 0건을 확인한다.
3. 생성·검수 API: `seo_generate.py`의 구 요청·구 응답 필드를 유지하며 4항목·근거·기준 버전·검수 저장을 추가한다. 공급자 모형으로 오류 재현→분류→회귀와 엄격 출력 검증을 수행한다.
4. 화면: 기존 SEO 진단은 유지. 업체→상품→키워드와 4항목 수정/채택/보류→승인본 저장·복사를 구현한다. 지연 응답과 중복 클릭, 회사 변경, CSV를 실제 React DOM에서 가짜 자료로 확인한다.
5. 기준: 기존 규칙과 이력을 보관하고 개정본 전환을 최고관리자 동작으로 제공한다. 부팅만으로 운영 편집 기준을 덮지 않는다.
6. 통합 검증: 새 API 테스트, 캐시 테스트, 오프라인 브라우저, 기존 고객 피커·권한·훅·분석/진단 관련 회귀 및 구문/빌드 검증, 독립 변경 검토.
7. 인계: 실제 결과/미검증/운영 조치 필요 여부를 `AI_DEV_STATUS.md`에 기록하고 작업 브랜치에 커밋한다. 운영 병합·설정 변경·재시작·배포는 하지 않는다.

구현 계약:

- `GET /api/seo/client/{id}/products`: 접근 허용 업체의 명시 연결 상품만. `data[]` 각 항목 `{product_key,product_url,keyword,product_name,brand,category,features,current_values}`.
- `POST /api/seo/generate`: 구 입력 + 선택 `product_url,current_values`를 받는다. 구 출력 + `generation_id,recommendation,field_reasons,current_values,product_url,rules_version,evidence`를 가산한다.
- `POST /api/seo/save-to-client`: 구 입력은 유지. 새 검수는 `generation_id,reviewed:true,approved_values,decisions,product_url`을 추가한다. 저장된 추천 원본과 요청 업체/상품/키워드를 대조하고 승인본을 별도로 보존한다.
- `GET /api/seo/client/{id}/saved`: 구 목록 필드 + `review`(없으면 null)를 가산한다.
- `GET /api/seo/rules`: 구 rules_text + `version,recommended_rules_text,recommended_version,is_recommended_active`.
- `POST /api/seo/rules/activate-recommended`: 최고관리자가 개정 기준을 활성화하며 기존/개정 기준을 이력으로 보관한다.
- `collect_evidence(db_path,keyword,now=None)`와 `client_products(db_path,client_id)`는 앱 import·DB 생성·외부 연결 없이 동작한다.
- 현재값 키와 승인값 키는 `product_name,tags,page_title,meta_description`; 결정값은 `adopt/edit/hold`이다. 미확인 현재값은 null이며 미확인을 AI로 복원하지 않는다.
