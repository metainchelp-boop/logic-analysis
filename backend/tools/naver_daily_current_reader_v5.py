"""source4d 전용 현재 수집 원천 읽기 초안. 실제 실행 핀 미확정·운영 조회 미실행."""
import hashlib
import importlib
import json
import re
import sqlite3
import sys
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

SOURCE = '4d5802360c1ba23aa801b1145ca8483db3edd35f'
CANONICAL_SHA256 = 'b1ce7e10044552e9d50427ba15f1e201836d88747fd0d16476a917cf72dab5c8'
EXECUTION_PINS = dict(native_receipt=None, canonical_receipt=None, deployed_prepare=None,
                      deployed_apply=None, controller_transport_identity=None)
ADNO, PID = 1030001, 51952
PERIOD_KEY = 'weekly:2026-10-05:2026-10-11'
PERIOD = dict(kind='weekly', start='2026-10-05', end='2026-10-11')
EVENT_FROM = datetime.fromisoformat('2026-10-13T07:10:00+09:00')
EVENT_UNTIL = datetime.fromisoformat('2026-10-13T07:11:00+09:00')
KST = timezone(timedelta(hours=9))
MAX_ACCOUNTS, MAX_JOBS, MAX_META_ROWS = 4000, 20000, 20000
MAX_BODY, MAX_BODIES = 8*1024*1024, 32*1024*1024
STATUSES = frozenset(('pending reading partial ok retry limited reauth_required source_wait superseded').split())
KINDS = frozenset(('daily weekly manual manual_period').split())
PERFORMANCE_KINDS = KINDS | {'backfill'}
STAGES = frozenset(('진행중 전략관리 사후관리 재계약진행중 홀딩중 환불중 계약만료').split())
ERRORS = frozenset(('KEY_REJECTED RATE SERVER BAD_REQUEST NOT_FOUND NETWORK BAD_RESPONSE MISMATCH OTHER '
    'CHECKPOINT_PENDING CHECKPOINT_INVALID SETTINGS_CHANGED REQUEST_BUDGET REQUEST_DEADLINE REQUEST_CALL_CAP '
    'STATS_INCOMPLETE STATS_SHAPE STATS_SHAPE_UNKNOWN STATS_NUMERIC_INVALID STATS_ROW_ID_INVALID STATS_DATE_INVALID '
    'STATS_PERIOD_OPEN STATS_METRIC_MISSING STATS_METRIC_INVALID STATS_DATE_INCOMPLETE STATS_CYCLE_INVALID '
    'STATS_CYCLE_FUTURE STATS_CAMPAIGNS_INVALID UNEXPECTED RETRY_EXHAUSTED SOURCE_AGGREGATING CAMPAIGNS_CHANGED '
    'RECHECK_COVERED SOURCE_STALE MANUAL_PENDING').split())
BRANCHES = frozenset(('NO_OBSERVATION POLICY_INACTIVE MANUAL_PENDING NO_CURRENT_SCOPE_ROW CYCLE_NOT_CURRENT '
    'CURRENT_ROW_INVALID FUTURE_CHECKED_AT CURRENT_PARTIAL CHECKPOINT_INVALID CURRENT_COMPLETE').split())
PIN_FIELDS = frozenset(EXECUTION_PINS)
JOB_COLUMNS = ('job_key,customer_id,possibility_id,kind,cycle_day,period_start,period_end,snapshot_at,catalog_at,'
    'stage_revision,matching_fingerprint,generation,requested_at,actor,status,checked_at,next_try_at,attempts,error_code,'
    'length(CAST(progress_json AS BLOB)) AS progress_size')

# SOURCE_FILES는 공개 canonical-source의 정확 163경로/바이트/모드/SHA 고정값이다.
SOURCE_FILES = {'.dockerignore': {'bytes': 408, 'mode': 420, 'sha256': 'ba16cad53840bc35b7c174d5cc143a83e7a56cc63acad2c2d14fab17ab30d1a6'}, 'Dockerfile.naver-engine': {'bytes': 1134, 'mode': 420, 'sha256': 'f838c3da2687e8b800046005ef5bd39b1fc3e3454cecdbe291a233ee00004edc'}, 'Dockerfile.naver-engine.dockerignore': {'bytes': 374, 'mode': 420, 'sha256': '4b3d1a3f35e7f84a6db89382a1b27358ed1a8f2ee9d3b0112c87ded1f468f43d'}, 'Dockerfile.naver-relay': {'bytes': 1421, 'mode': 420, 'sha256': 'c05ec8ced0554c9237718e3c37c265c615d86461d3f5b23df30f23bf113da77d'}, 'Dockerfile.naver-relay.dockerignore': {'bytes': 462, 'mode': 420, 'sha256': 'ae83e68adcc2b2b9cc987dc81e92a3fa42c91542309d9467033a69f59590fb59'}, 'backend/app/__init__.py': {'bytes': 0, 'mode': 420, 'sha256': 'e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855'}, 'backend/app/naver_auto/__init__.py': {'bytes': 927, 'mode': 420, 'sha256': '64020d9148504885f294af924dcea4d2f312df8b6014d646f98b9e5221a4f164'}, 'backend/app/naver_auto/checks.py': {'bytes': 16435, 'mode': 420, 'sha256': '79e61753a0c16f1a8106e7bec2ed89404688eb6ff9a67f8783f47d13409b0b4c'}, 'backend/app/naver_auto/issues.py': {'bytes': 14469, 'mode': 420, 'sha256': 'b47ab19a490c5035cec0e59d19e5720edb03d0c103fe4e1cce3abe2dace9556a'}, 'backend/app/naver_auto/matching.py': {'bytes': 27050, 'mode': 420, 'sha256': '6be28f0bcf2e86ff1a2d799063c3ac5caca81a33ac3572ed7f754aef14bb3eb0'}, 'backend/app/naver_auto/org_snapshot.py': {'bytes': 33415, 'mode': 420, 'sha256': '34da0635ee7d071c3dd02bf4001343f2c42001ebc70d7e5548e692d687920f97'}, 'backend/app/naver_auto/scope.py': {'bytes': 35601, 'mode': 420, 'sha256': 'fd25fae418f27e6bd9b01415489164eb85241a5151a3e5fa1ad085edec7b3cd7'}, 'backend/app/naver_auto/thresholds.py': {'bytes': 3789, 'mode': 420, 'sha256': '6b5259480f85d0c397fac1ee7884a4beb14e0ee60da02669c104b21131498aa7'}, 'backend/app/naver_auto/verdict.py': {'bytes': 11797, 'mode': 420, 'sha256': 'b8ff947d92e9dd0e0ceafd6b1da2e7dc3841875811417e83ae387ba0074809ec'}, 'backend/app/naver_entry.py': {'bytes': 457, 'mode': 420, 'sha256': '21aaf8ace7ca7b650e42cf1a32848cf00696680b68c6624a6ca9cbab7c891c08'}, 'backend/app/naver_relay.py': {'bytes': 25944, 'mode': 420, 'sha256': 'e9d7d38d572a21af77e220199bd34988908d3c636c3a834071fec35bd3065e61'}, 'backend/app/routers/__init__.py': {'bytes': 0, 'mode': 420, 'sha256': 'e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855'}, 'backend/app/routers/naver.py': {'bytes': 5619, 'mode': 420, 'sha256': 'cac5dfc32757f7472f86387447e93cb178de60771cf2bf699aa8ad4cf6bf8069'}, 'backend/naver_page/README.md': {'bytes': 824, 'mode': 420, 'sha256': '6ea9866e718da69999ffc5ce878aaa71e29bb9a6b8f65e4cf53a59c7fb779212'}, 'backend/naver_page/app.css': {'bytes': 59087, 'mode': 420, 'sha256': '296efe6a624ada65affaf2397d2dd55356917bcdc540f6f4f4eddfacee17a5dd'}, 'backend/naver_page/app.js': {'bytes': 223505, 'mode': 420, 'sha256': '8a4daa3a0dbaa9ae61434c8dac223bdb47a3ed0b9106c7c324b4aa8260f25ab3'}, 'backend/naver_page/automation-ui.js': {'bytes': 58486, 'mode': 420, 'sha256': 'dc759d6245f87d002bd93a62c1c73ef33204b0708ae1d2357467b2f207cb37a3'}, 'backend/naver_page/execution-ui.js': {'bytes': 54585, 'mode': 420, 'sha256': 'a6febc90e4fda776a1a4f5f666304993484edb540b82f059335221edfeb6a6d1'}, 'backend/naver_page/experiments-ui.js': {'bytes': 62774, 'mode': 420, 'sha256': '043d513b2611ecc620bbfe7143231d4c4951a52a2ddac9150e36b49f3ba69d4e'}, 'backend/naver_page/favicon.svg': {'bytes': 188, 'mode': 420, 'sha256': '008a5b8b00e9602ceb35ea244f5ecef6110d8ad0067ac9d993f992a9525c9c5c'}, 'backend/naver_page/index.html': {'bytes': 28388, 'mode': 420, 'sha256': 'cd24b8f51b94103204bc11ec87cfb488db1a9cb9122f2ac427cb1b81f16dd4f6'}, 'backend/naver_page/learning-ui.js': {'bytes': 51105, 'mode': 420, 'sha256': '28dcb6b7f923048d90ae5ef86e0664c4bfbc7d2b127bc41f2e46ee0a79c0f340'}, 'backend/naver_page/operations-ui.js': {'bytes': 15591, 'mode': 420, 'sha256': 'b6aad703021d6f4006c9dfc3f132e9fc02b9ea9badb8689c8e5c2bac8a78acfd'}, 'backend/naver_page/randomized-experiments-ui.js': {'bytes': 36703, 'mode': 420, 'sha256': 'c3b0096f8e36cc41136f5b9fd0cb21c4b66a19e4b6765c15c92092e81a7b7f1a'}, 'backend/naver_page/report-pdf.js': {'bytes': 40388, 'mode': 420, 'sha256': '03445e5236b80669395d48cc1ebef52dafaf372e84bade035193496c7d6e3867'}, 'backend/naver_page/report-schedule-ui.js': {'bytes': 15440, 'mode': 420, 'sha256': '84beb5cdf5368a706dc85ee20f2666f7108e83724b131c5f7d43bd62ece94b99'}, 'backend/naver_page/report-ui.js': {'bytes': 104777, 'mode': 420, 'sha256': 'a8a4aead101f369cda71fb637b33f57e879e4275aaf45ca16daf480baa9b7896'}, 'backend/naver_page/sales-ui.js': {'bytes': 17774, 'mode': 420, 'sha256': '00553781030990970c88dcd6d86c11730cf9c60cf9ce7a7963f2b091cd5aa2ff'}, 'backend/naver_page/sales.css': {'bytes': 5905, 'mode': 420, 'sha256': 'f27843cb1e1e63a41d85f5f794035f47c62ec72dda5971f95dd9ed58226ba09d'}, 'backend/naver_page/sso-bootstrap.js': {'bytes': 4588, 'mode': 420, 'sha256': 'b32369913287c49fa43fa210db73742f51c203066273b0334b4d6ebbb335b289'}, 'backend/naver_page/vendor/report-pdf/Apache-2.0.txt': {'bytes': 11358, 'mode': 420, 'sha256': 'cfc7749b96f63bd31c3c42b5c471bf756814053e847c10f3eb003417bc523d30'}, 'backend/naver_page/vendor/report-pdf/NanumGothic-OFL.txt': {'bytes': 4532, 'mode': 420, 'sha256': '90f6a909ffb2af7f6422ea20042a26180fe5520cba80bbbf75a5e660320d7924'}, 'backend/naver_page/vendor/report-pdf/NanumGothic-Regular.ttf.gz': {'bytes': 697020, 'mode': 420, 'sha256': '72d1bf88a642ede8ff7da422031106fc697ea4c79b1cfd2994bffc57df4dab07'}, 'backend/naver_page/vendor/report-pdf/THIRD-PARTY-NOTICES.txt': {'bytes': 12147, 'mode': 420, 'sha256': '33588a8c88e8c3f6535dc653bf65840b08dd75b7e7f2beec69d6f5a3542ffa67'}, 'backend/naver_page/vendor/report-pdf/fontkit-1.1.1.umd.min.js': {'bytes': 758440, 'mode': 420, 'sha256': 'd8df561b9fba98e24f2e5130e40948809281bbbc55a20c412359f1a0a5eb35a6'}, 'backend/naver_page/vendor/report-pdf/fontkit-LICENSE.txt': {'bytes': 1462, 'mode': 420, 'sha256': '3b839fbef51e4721ff85ba6c6c79e0d37738f28c28bf90c744d7c4bf9f0eb1a0'}, 'backend/naver_page/vendor/report-pdf/js-sha256-LICENSE.txt': {'bytes': 1076, 'mode': 420, 'sha256': '2153bd2978793748fbe0eb8f838ae2ae19f03f9d4ee5473dd1628a0c0790e4ab'}, 'backend/naver_page/vendor/report-pdf/manifest.json': {'bytes': 3008, 'mode': 420, 'sha256': 'd7b047f71ecf086d422031b4fba80d708a3987fe6635c78e16de82979aa2f3de'}, 'backend/naver_page/vendor/report-pdf/pako-LICENSE.txt': {'bytes': 1104, 'mode': 420, 'sha256': 'a04665b3b2de56c66730c1f720f528175739e4104f79073614aa611da1e85539'}, 'backend/naver_page/vendor/report-pdf/pdf-lib-1.17.1.min.js': {'bytes': 525099, 'mode': 420, 'sha256': '0f9a5cad07941f0826586c94e089d89b918c46e5c17cf2d5a3c6f666e3bc694f'}, 'backend/naver_page/vendor/report-pdf/pdf-lib-LICENSE.txt': {'bytes': 1070, 'mode': 420, 'sha256': 'f2c9fc00fdb66eb99ac156ba52d734af66d8d309f65753ae809ad34ee2883bcb'}, 'backend/naver_page/vendor/report-pdf/sha256-1.0.0.min.js': {'bytes': 8156, 'mode': 420, 'sha256': 'a050d794e170699bd1a69d33908d0942c68901cb88347016064b60b240f0067e'}, 'backend/naver_page/vendor/report-pdf/standard-fonts-LICENSE.txt': {'bytes': 1070, 'mode': 420, 'sha256': '45cc2bb9957ed43f5c7f5eb1912f9f670730394d614079510477cae626194649'}, 'backend/naver_page/vendor/report-pdf/upng-LICENSE.txt': {'bytes': 1065, 'mode': 420, 'sha256': 'c1fb8861eca211bf5aea574358aba7039396c0c1824c2a1477cc126d398efd89'}, 'backend/requirements.txt': {'bytes': 144, 'mode': 420, 'sha256': '0264b07e26f94bc31522b7fcf4801318f21b0d86d74793e6fd9608f8a64ca67c'}, 'compose.naver-engine.yml': {'bytes': 2697, 'mode': 420, 'sha256': '62e33c3d2815579a28031973b956cd36031171f26ead4e21ad2d72adfe2a5ef7'}, 'compose.naver-relay.yml': {'bytes': 1514, 'mode': 420, 'sha256': '00404b84a4377fcb74afc883feff6d2a434b1fca92f0be7b2d399a72ba05da66'}, 'deploy/naver-backup-receiver.py': {'bytes': 11383, 'mode': 420, 'sha256': 'ac324dab4e868477c5c5aceef641e26a2359d45bdde6ac884331de09a208205c'}, 'deploy/naver-engine-ad-api.override.yml': {'bytes': 598, 'mode': 420, 'sha256': '961eddbd2bfe607ac0fe90dc056a7cd09de2a065b942ee0e6c0cc205e1f432fd'}, 'deploy/naver-engine-backup.override.yml': {'bytes': 971, 'mode': 420, 'sha256': 'bfbe6cc3b2a5988071ba067d2b599929deea2ef7d6b8c8644d2aefd236b65a78'}, 'deploy/naver-engine-nginx.conf': {'bytes': 2599, 'mode': 420, 'sha256': 'b26a13f1b7b4f7b5d6ca154333f91b3a92b80348a164544ded2d6e3b8e78e025'}, 'deploy/naver-erp-tunnel/OPERATIONS.md': {'bytes': 8186, 'mode': 420, 'sha256': 'ee50a7dc794d1168b53dff435577595fafb90f11dd2771e77a0e8209aaac37be'}, 'deploy/naver-erp-tunnel/ad-ssh.conf': {'bytes': 1385, 'mode': 420, 'sha256': '1c37f158c26a988973707c36b2f4ccade561c6e1fa93334a12ece8abaf9df0aa'}, 'deploy/naver-erp-tunnel/ad-tunnel.service': {'bytes': 1245, 'mode': 420, 'sha256': 'd6f4698a5aaf53e87bb47e07826503801d4ef49a9a12213d419b1208e33eb35a'}, 'deploy/naver-erp-tunnel/authorized_keys.template': {'bytes': 138, 'mode': 420, 'sha256': '3fab1b741f766435b317325799e50dab985c9f368041b16ca435ed82c1903c3b'}, 'deploy/naver-erp-tunnel/be-nginx.conf': {'bytes': 2966, 'mode': 420, 'sha256': '0c8b4d959203b37892346bcc9796518f95377eaee7e56ff26dee8b01c547d891'}, 'deploy/naver-erp-tunnel/be-sshd.conf': {'bytes': 835, 'mode': 420, 'sha256': '4440431dd03fc52171ee3a8abd9d9ce45500ece0c88e853dfe5537bd30992fc3'}, 'deploy/naver-erp-tunnel/test.Dockerfile': {'bytes': 588, 'mode': 420, 'sha256': '0fa260ab2000c9ea9d7d45330c8256060f7912e3d296bf554c2f4e3fc73b1ee0'}, 'deploy/naver-erp-tunnel/test.Dockerfile.dockerignore': {'bytes': 250, 'mode': 420, 'sha256': '4b7c07b25bf9724ea79620e03d7b40b69ce548dcfe01f478ada8c02c9c2c755a'}, 'deploy/naver-erp-tunnel/test_policy.py': {'bytes': 18991, 'mode': 420, 'sha256': 'e53a165a0a973aacc5a7f8b81c62f6921c88a7f0acabd4992f5521b86c0a7a26'}, 'deploy/nginx-ad.metainc.co.kr.conf': {'bytes': 739, 'mode': 420, 'sha256': '31574f6e1e0dcad25c57fb3f4f183b8f5bfed4b1fb14cd4c7f5f77efac6e89d1'}, 'naver_engine/__init__.py': {'bytes': 1077, 'mode': 420, 'sha256': '83ca0328fd0eb93b016be936321703ae88df5d3410b369df18c5c7290ed6bf74'}, 'naver_engine/ad_reasons.py': {'bytes': 5523, 'mode': 420, 'sha256': '12cb7edc84f8f302036c16677ae51ebbbbc117aa1feba6f58fb32b906501beec'}, 'naver_engine/alerts.py': {'bytes': 39621, 'mode': 420, 'sha256': 'bc4636d8b6f685e02a9305061926299f9fa52f50fbcf6c6e4cb9da8b29d1c35d'}, 'naver_engine/approval_documents.py': {'bytes': 7554, 'mode': 420, 'sha256': '47de41a6c0840710e62b56135593b0c00e99b41053630c3f37b79d2231c17243'}, 'naver_engine/automation_views.py': {'bytes': 12829, 'mode': 420, 'sha256': '7eca7148ce8f8595b861de71bc313b918fffacc25b665f679adc7fa18f6d8ecd'}, 'naver_engine/backup.py': {'bytes': 16760, 'mode': 420, 'sha256': '1bc2561ea3d8cc5f528b64ed275da4ca242fe9a5cf166c6bb53aaf6c0ff3a92e'}, 'naver_engine/catalog_links.py': {'bytes': 13417, 'mode': 420, 'sha256': '2984a7582347cad4580be1f25bdee93146e933222f3b783cc2a1bb5ae6478b7b'}, 'naver_engine/collection_diagnostics.py': {'bytes': 4224, 'mode': 420, 'sha256': '114806cdfb07eeeef2ac365a460e941d2741d6345b165c8428caf4344b2cacd6'}, 'naver_engine/credentials.py': {'bytes': 4788, 'mode': 420, 'sha256': 'f20794c7f89ee29c396fa596ff44c6781bd87872914d08f58b83d15b88df3c84'}, 'naver_engine/dashboard.py': {'bytes': 9334, 'mode': 420, 'sha256': '2c2c86c96f249f133220463f8988b96e07eee795d44dbc844204943370206f15'}, 'naver_engine/erp_alert.py': {'bytes': 16095, 'mode': 420, 'sha256': '55e639ccb747e8e5f34af80e9802e03a0b650c26d06c89531b12ce5b2b8abf92'}, 'naver_engine/erp_profile.py': {'bytes': 7315, 'mode': 420, 'sha256': '108b4ee5d97dfa6174ccca18c5e92e9308976a349c6a648985a7ac45ea75986c'}, 'naver_engine/erp_read.py': {'bytes': 22099, 'mode': 420, 'sha256': '50434c7943a23ab195b2325a74ef977e9d0e0bff02572175b8994536bf7f3cdc'}, 'naver_engine/execution_commands.py': {'bytes': 68617, 'mode': 420, 'sha256': '9def0f8399017376226f3c7ce4477119a9cb19e99a597cbf1f10bbc9066ecc6e'}, 'naver_engine/execution_store.py': {'bytes': 76944, 'mode': 420, 'sha256': '6ab5fd81eb0bab41add10b44bcb630b38e8ebd619fd58a2c5304a69b0c59da44'}, 'naver_engine/experiments.py': {'bytes': 41946, 'mode': 420, 'sha256': 'f99a213727b258aaf88f6769328c2f7a602109466efdbf00a8da33bf7cbad9ff'}, 'naver_engine/experiments_reads.py': {'bytes': 29482, 'mode': 420, 'sha256': '1758861970173d771c805813bc949c77c4559337a0bd7c60416be134513b5ccc'}, 'naver_engine/experiments_store.py': {'bytes': 36620, 'mode': 420, 'sha256': '5e6db883b0ab270a955e90ff5676f61cf0bbc22b4aab348cf968e96a85a6db74'}, 'naver_engine/fields.py': {'bytes': 3369, 'mode': 420, 'sha256': 'a92d4182bad903bb3e5c22519ea93dace5041475bc874967024cc34f5e340a6a'}, 'naver_engine/funnel_evidence.py': {'bytes': 13432, 'mode': 420, 'sha256': '6a25abe8756912cfe130ddb5e99fc26107b34f94ad5c296494e682ebed7f1514'}, 'naver_engine/funnel_reads.py': {'bytes': 14000, 'mode': 420, 'sha256': 'f8959edabea14f723a7c8fa3d40c99a1e0e6740deba31294ca2325e53ed59114'}, 'naver_engine/funnel_store.py': {'bytes': 28540, 'mode': 420, 'sha256': '7df267d9a5d9cb3ee37ea61b6a6b907acc0f2ec9ddc0d7ea070a903778a9fe61'}, 'naver_engine/handles.py': {'bytes': 16016, 'mode': 420, 'sha256': 'fa64d8841f352b413ea12fdb8b88ab53c73133eaf0e91a98d8c586a52e8a8e14'}, 'naver_engine/hourly_stats.py': {'bytes': 3181, 'mode': 420, 'sha256': '287213de98df68c57634e3b6ed454bcb6df6febd12fe22effbb40281f88f2319'}, 'naver_engine/inspection_catalog.py': {'bytes': 10800, 'mode': 420, 'sha256': '3d0652bcb8ef6a5eef6bf16ec85f1e0319b96a078abd68381af070aa3dad46b6'}, 'naver_engine/inspection_fields.py': {'bytes': 10771, 'mode': 420, 'sha256': '102028ecb4f35647043b5efc1751e516c92f326252b88c3ab6c983ca7c61ba6a'}, 'naver_engine/inspection_reads.py': {'bytes': 23837, 'mode': 420, 'sha256': '965f5dac65cbf867a6232c5af2d3992a6324b81cc6470e65167e06d674d0e543'}, 'naver_engine/inspection_store.py': {'bytes': 36698, 'mode': 420, 'sha256': 'aa694ce93b6094d2598f4f3e06eaacfed4a04b1f787e6bc715a22a9f30253799'}, 'naver_engine/inventory.py': {'bytes': 29075, 'mode': 420, 'sha256': '2a5c4d5f6acb0b431daa9e16be517322a43008aa636cfdf90c49c4a9305ae28e'}, 'naver_engine/inventory_reads.py': {'bytes': 9956, 'mode': 420, 'sha256': '40892186fddd444f2f8868ea31323744e155d8c59eeb42b3ef6deea482a379e1'}, 'naver_engine/learning_assets.py': {'bytes': 40383, 'mode': 420, 'sha256': '4c3e1d6923eb0396c23e63e18c90c6077623248fc3aa05cb5071684ffde53666'}, 'naver_engine/learning_retrieval.py': {'bytes': 9135, 'mode': 420, 'sha256': 'f4e32d5c458014697d194c077e769ce929f677e98faaf34cc594982f992188ee'}, 'naver_engine/learning_source_storage.py': {'bytes': 41649, 'mode': 420, 'sha256': '144eca9e828c9f73a244b8603bf82758155c351d0586a88b7fcf012126d0935d'}, 'naver_engine/links.py': {'bytes': 24837, 'mode': 420, 'sha256': 'a97b7f293e32f55ac92a7b53c77884fbc50bb7d481212346f85f7dc8ae2db249'}, 'naver_engine/management.py': {'bytes': 5723, 'mode': 420, 'sha256': '84862507d3831053edf618c6d68e800f1f1a1ec4019bcc88030eacb4d14f37e4'}, 'naver_engine/management_store.py': {'bytes': 11723, 'mode': 420, 'sha256': '13ee58e1d4383acf3ab8da469e7e09b9032640c2629e601809a3991b4c650fc5'}, 'naver_engine/market_evidence.py': {'bytes': 12510, 'mode': 420, 'sha256': '6ee6ce06477d0c60b798a04e6679beff8ce0e056760e82bef3565764a55075ec'}, 'naver_engine/market_store.py': {'bytes': 7284, 'mode': 420, 'sha256': 'c8d75ab344c5cfb5ba3f034782521a5ae98e75e7083377147eb491c5917570cc'}, 'naver_engine/marketing_strategy.py': {'bytes': 87799, 'mode': 420, 'sha256': '750281839cf2b0e186e1d6f0a3c6146134fff82c09495fcda4d4b7ba3e3f2352'}, 'naver_engine/metrics.py': {'bytes': 15005, 'mode': 420, 'sha256': 'f734fa8b2173ff5b59dcd4aeb02e61fbbe77ab23d1cc15ae6ce8441e3548564c'}, 'naver_engine/monthly_reads.py': {'bytes': 11994, 'mode': 420, 'sha256': 'f26214bf881b95be54fca75c941a15cb8f92f667e5af30aa94369e8fda5b7299'}, 'naver_engine/morning.py': {'bytes': 48264, 'mode': 420, 'sha256': 'f6cd9d4c5fd0453dcf77f707313d9c37ff6e01621e1d5f86325423b3adc94ca6'}, 'naver_engine/morning_progress.py': {'bytes': 6839, 'mode': 420, 'sha256': 'c6cb0faf936820a2d93b90985e0aaa1362b1bf3d3a6d98d861212c17366f54b1'}, 'naver_engine/naver_read.py': {'bytes': 69880, 'mode': 420, 'sha256': 'ee1d7412dae83610cbb6c7ba2b812963e69894c706064431606c45d402b96534'}, 'naver_engine/naver_write.py': {'bytes': 24439, 'mode': 420, 'sha256': '68cb76054948950110a85672a05b04818de67bf0cdef8f071324d08b6ad73860'}, 'naver_engine/network_observability.py': {'bytes': 1969, 'mode': 420, 'sha256': '60be59acf1ede301ea93975d6098248f608d738d7178ed8003acb0a326ebe6a5'}, 'naver_engine/observation_store.py': {'bytes': 15048, 'mode': 420, 'sha256': '71eee5b32d1f729f8dea3699c1de43893e7b12766d925fecfaf1e8082e6cad8a'}, 'naver_engine/observation_views.py': {'bytes': 4202, 'mode': 420, 'sha256': '9b95662b7a39a0c36d175b6d28dbfeee4d9057d5f7713943d44bfdd088961de4'}, 'naver_engine/observational_inference.py': {'bytes': 15697, 'mode': 420, 'sha256': 'ff5c9706b4906372f60328c419693fadfee3895cb827bb12c9587323a4b79fb6'}, 'naver_engine/operating_criteria.py': {'bytes': 17387, 'mode': 420, 'sha256': '3bae3f568034d40f76ed65a34bd3b61233e0d0df718ba9db8f9bc9e710fadbe4'}, 'naver_engine/performance_reads.py': {'bytes': 18142, 'mode': 420, 'sha256': '85a863871288640e0a1a6745a10c618cc2e34e13dbb6de2b6fcf9b9040b3798e'}, 'naver_engine/product_evidence.py': {'bytes': 13403, 'mode': 420, 'sha256': '755c97900d34e06ac4a7f46c4ac3aafb3477f5a616cb560bb002f86deac87711'}, 'naver_engine/product_store.py': {'bytes': 9723, 'mode': 420, 'sha256': 'ffc817908ea1ed8a5e05fbc62e4185c7cdd077820199a9f99db15894c9efe303'}, 'naver_engine/randomized_execution.py': {'bytes': 11157, 'mode': 420, 'sha256': 'c3c01e3dbcbafaefb859410a6ecb70c24a81909543b24f48ec0b7bac69d17c86'}, 'naver_engine/randomized_experiments.py': {'bytes': 10739, 'mode': 420, 'sha256': '98a773addae4425cd4e3d7f6c68a3caf6981a76bd465f265cfdf237862e90829'}, 'naver_engine/randomized_experiments_reads.py': {'bytes': 8921, 'mode': 420, 'sha256': '8d5135161638c7a867cec5492c39f6ed4c5261b81a622437836f0b7f4f72122c'}, 'naver_engine/randomized_experiments_store.py': {'bytes': 61278, 'mode': 420, 'sha256': 'a7fbd33eff873d3ac540357c4c3b73b31f096503f7a62efef3b6060dcfc6c547'}, 'naver_engine/randomized_inference.py': {'bytes': 18813, 'mode': 420, 'sha256': '2112f900ae2b9f2188187923deb2f6d6baefcfd6496dc0e5defd4232cbafee58'}, 'naver_engine/report_enrichment.py': {'bytes': 20237, 'mode': 420, 'sha256': 'b151e866f561b93661ef52a7f7470f04d3f616d00de14b7e81bc2db6f5c0e1d1'}, 'naver_engine/report_notes.py': {'bytes': 9275, 'mode': 420, 'sha256': 'dadb0b4b1501a87176a4e85dc8c4b74745c39a48888c1c43dda7044048f04408'}, 'naver_engine/report_refresh.py': {'bytes': 7029, 'mode': 420, 'sha256': '826b8390d7a7b200d1e0449c2c8a1dcaa4e4310bf64bfeab7142998eb111999e'}, 'naver_engine/report_schedule.py': {'bytes': 17420, 'mode': 420, 'sha256': '24a76092fc6420093941fe78f2ce724029fed564c50b3bcce79a8687e0fc58fb'}, 'naver_engine/report_schedule_store.py': {'bytes': 24985, 'mode': 420, 'sha256': '7466cf13bab0b1899b42c2cd34c8e5b1fa0d1a83ee453fff0fa2e8b90489a406'}, 'naver_engine/report_views.py': {'bytes': 17438, 'mode': 420, 'sha256': '5d6218c1360fee101fb5ec21d036d6047daea11815fc4a1eda66b9e4023c6de2'}, 'naver_engine/reporting.py': {'bytes': 25850, 'mode': 420, 'sha256': '76a7a27ab39f69e9adf4a58547562e00776f6aaa0020df519cb2da8d032bd006'}, 'naver_engine/runtime_view.py': {'bytes': 2407, 'mode': 420, 'sha256': 'a8d78825c16aaa0a3fcc877fdb4a3cfaddc8330154f9331b75eee2cae6c90a4a'}, 'naver_engine/sales_views.py': {'bytes': 7905, 'mode': 420, 'sha256': '885598a9890df6913b54e0d4bf8f2041a18befe5ae319aa0963edb12b5e770f7'}, 'naver_engine/session.py': {'bytes': 8455, 'mode': 420, 'sha256': 'f710ae69062f2ef13c447767fe65ce17c0990aebe65fa6222c4e312129b8e432'}, 'naver_engine/setup_checks.py': {'bytes': 39221, 'mode': 420, 'sha256': '849f5ddc1141078988c8fdbec6a6496c2f2cb82aea3af1a9d2070b897e755213'}, 'naver_engine/store.py': {'bytes': 452895, 'mode': 420, 'sha256': '3e36c0391ace66bdb1013cb409756099f8435223c7e8cfbf243774cbc8e66456'}, 'naver_engine/strategy_validation.py': {'bytes': 3271, 'mode': 420, 'sha256': '20e9eecfc86205a50be8e5bf90c4c7024f0a0c1a506758726767042edbba8e9e'}, 'naver_engine/structure_reads.py': {'bytes': 14811, 'mode': 420, 'sha256': 'fed780a4903a099b540cc4eb6b9419ee84cbfdbd26056ad1c338a5db23d71c22'}, 'naver_engine/sync.py': {'bytes': 24402, 'mode': 420, 'sha256': '7ddd57ccce8a8edcf13e3d4495d748d122b067e1bba32becfa6326a4dda32dad'}, 'naver_engine/view_sync.py': {'bytes': 5380, 'mode': 420, 'sha256': '57c97bb82d78dc25277cdd7f5ea23c1512be0cfd0279a837e1e64d0b317a4034'}, 'naver_engine/views.py': {'bytes': 64063, 'mode': 420, 'sha256': 'bfa0f4998153abe01ffeb7d646653db6b4d39b8f4409e09e23002424a60fafb9'}, 'naver_engine/web.py': {'bytes': 127354, 'mode': 420, 'sha256': '4623c4b11a05c6e83c5e5ba7df2b558f1453206de0f4c6ca7304d4e0cb903a89'}, 'naver_runtime/__init__.py': {'bytes': 105, 'mode': 420, 'sha256': '27d28d6ed467edc27f1b22a7a3fedd78253d562938c3cf060ea2573ef38038ec'}, 'naver_runtime/__main__.py': {'bytes': 16221, 'mode': 420, 'sha256': 'de4215ea9b64ca6a2643d1b6ea7abaa11ef63ae130bb2da1ea8e03bab62e3e3d'}, 'naver_runtime/backup_transport.py': {'bytes': 5364, 'mode': 420, 'sha256': 'b14520d0f46429ea93a3158b664ca7f5cb37e378ce146e684cd276265f92db71'}, 'naver_runtime/bootstrap.py': {'bytes': 12709, 'mode': 420, 'sha256': 'dd7f5949eee28e0391608670b3f00a40c30e6b461a3589bf47fcc7b49c5dd504'}, 'naver_runtime/claude_provider.py': {'bytes': 46325, 'mode': 420, 'sha256': '16aa6b6f69c4bc95262a5e165d7295f4b0b5942d75317a8ab9db69c9afd2ebb2'}, 'naver_runtime/collection_requests.py': {'bytes': 6497, 'mode': 420, 'sha256': '1e7606023cdbd27826b0f0e4e07a3f0f6fa4955d6d00396a1af33e7f62526660'}, 'naver_runtime/config.py': {'bytes': 6216, 'mode': 420, 'sha256': 'ee3f1bdd0959ebc7a729de431518200d7eb58dce5f8580936b0ad5ec12bf7fa1'}, 'naver_runtime/erp_tunnel_transport.py': {'bytes': 10072, 'mode': 420, 'sha256': '59d1c40300c416b40d022ce6d1d91cdc9ac3d4a3b981c260ca3002e919bd3288'}, 'naver_runtime/learning_jobs.py': {'bytes': 7028, 'mode': 420, 'sha256': 'b5068fe0b6167726ef83a13b79d99fa2d1b56d97b566eabf4387d73cb70a3a6c'}, 'naver_runtime/learning_provider.py': {'bytes': 6364, 'mode': 420, 'sha256': '736d97270bf6a22a916fade9959710c761b09eaea5e8db8fd58bbb60f30849a2'}, 'naver_runtime/market_export.py': {'bytes': 2464, 'mode': 420, 'sha256': '6faef9473ebb38f609a58b7657f86e7c32a3d44d446e2e546392ac8eea3dafb0'}, 'naver_runtime/network_observability.py': {'bytes': 2741, 'mode': 420, 'sha256': 'da1c9f7778ab68142e64e1aaaa21d82514a0852df031deb015dc165f0d48ffbf'}, 'naver_runtime/observation_binding.py': {'bytes': 3312, 'mode': 420, 'sha256': '8c38a6dc00060526548762da75020e5dc2e3c2118aff35f6ffc8f64c997444e5'}, 'naver_runtime/product_export.py': {'bytes': 2467, 'mode': 420, 'sha256': 'e22619d2e1030b4e3d3cb6325e636198eeddc3041412dfe1ae937f5c487ee6fa'}, 'naver_runtime/provider_observability.py': {'bytes': 16225, 'mode': 420, 'sha256': '16bcf67ff4c43b71843f6c94ca95982f12c00b76764b94e500070b5f9691f814'}, 'naver_runtime/report_schedule_jobs.py': {'bytes': 9854, 'mode': 420, 'sha256': '79e3cb964eae49819d560c27b4a4ef83e876b778c60c22c7e584c6a8f207ab82'}, 'naver_runtime/restore_check.py': {'bytes': 5657, 'mode': 420, 'sha256': '0f7c392155b9fdcb602307b7bd5771c211ca9f6774f5dcfa8106f940bb7905b9'}, 'naver_runtime/runtime_status.py': {'bytes': 6149, 'mode': 420, 'sha256': 'f08633202d21248dde7c62c2d6bdb42a40b981721df958b0124fc7009b4da8eb'}, 'naver_runtime/scheduler.py': {'bytes': 36880, 'mode': 420, 'sha256': 'f7920b79c0339acf7c619222a46fd9056d73822445cd69966802f261e1e07d41'}, 'naver_runtime/server.py': {'bytes': 6425, 'mode': 420, 'sha256': 'bf17856d256bf672aa4f50d8d9bf4b2557cec9a2aed7f1a0f5f97eee81ca8007'}, 'naver_runtime/writer.py': {'bytes': 15964, 'mode': 420, 'sha256': 'f4825faa816f2001a3902d9828bdf0dc1086467c4a56b89cf7ee4c5425ca5e26'}}

# source4d Dockerfile COPY18–21와 전용 dockerignore가 허용한 정확 106경로.
IMAGE_SOURCE_PATHS = (
    'backend/app/__init__.py',
    'backend/app/naver_auto/__init__.py',
    'backend/app/naver_auto/checks.py',
    'backend/app/naver_auto/issues.py',
    'backend/app/naver_auto/matching.py',
    'backend/app/naver_auto/org_snapshot.py',
    'backend/app/naver_auto/scope.py',
    'backend/app/naver_auto/thresholds.py',
    'backend/app/naver_auto/verdict.py',
    'naver_engine/__init__.py',
    'naver_engine/ad_reasons.py',
    'naver_engine/alerts.py',
    'naver_engine/approval_documents.py',
    'naver_engine/automation_views.py',
    'naver_engine/backup.py',
    'naver_engine/catalog_links.py',
    'naver_engine/collection_diagnostics.py',
    'naver_engine/credentials.py',
    'naver_engine/dashboard.py',
    'naver_engine/erp_alert.py',
    'naver_engine/erp_profile.py',
    'naver_engine/erp_read.py',
    'naver_engine/execution_commands.py',
    'naver_engine/execution_store.py',
    'naver_engine/experiments.py',
    'naver_engine/experiments_reads.py',
    'naver_engine/experiments_store.py',
    'naver_engine/fields.py',
    'naver_engine/funnel_evidence.py',
    'naver_engine/funnel_reads.py',
    'naver_engine/funnel_store.py',
    'naver_engine/handles.py',
    'naver_engine/hourly_stats.py',
    'naver_engine/inspection_catalog.py',
    'naver_engine/inspection_fields.py',
    'naver_engine/inspection_reads.py',
    'naver_engine/inspection_store.py',
    'naver_engine/inventory.py',
    'naver_engine/inventory_reads.py',
    'naver_engine/learning_assets.py',
    'naver_engine/learning_retrieval.py',
    'naver_engine/learning_source_storage.py',
    'naver_engine/links.py',
    'naver_engine/management.py',
    'naver_engine/management_store.py',
    'naver_engine/market_evidence.py',
    'naver_engine/market_store.py',
    'naver_engine/marketing_strategy.py',
    'naver_engine/metrics.py',
    'naver_engine/monthly_reads.py',
    'naver_engine/morning.py',
    'naver_engine/morning_progress.py',
    'naver_engine/naver_read.py',
    'naver_engine/naver_write.py',
    'naver_engine/network_observability.py',
    'naver_engine/observation_store.py',
    'naver_engine/observation_views.py',
    'naver_engine/observational_inference.py',
    'naver_engine/operating_criteria.py',
    'naver_engine/performance_reads.py',
    'naver_engine/product_evidence.py',
    'naver_engine/product_store.py',
    'naver_engine/randomized_execution.py',
    'naver_engine/randomized_experiments.py',
    'naver_engine/randomized_experiments_reads.py',
    'naver_engine/randomized_experiments_store.py',
    'naver_engine/randomized_inference.py',
    'naver_engine/report_enrichment.py',
    'naver_engine/report_notes.py',
    'naver_engine/report_refresh.py',
    'naver_engine/report_schedule.py',
    'naver_engine/report_schedule_store.py',
    'naver_engine/report_views.py',
    'naver_engine/reporting.py',
    'naver_engine/runtime_view.py',
    'naver_engine/sales_views.py',
    'naver_engine/session.py',
    'naver_engine/setup_checks.py',
    'naver_engine/store.py',
    'naver_engine/strategy_validation.py',
    'naver_engine/structure_reads.py',
    'naver_engine/sync.py',
    'naver_engine/view_sync.py',
    'naver_engine/views.py',
    'naver_engine/web.py',
    'naver_runtime/__init__.py',
    'naver_runtime/__main__.py',
    'naver_runtime/backup_transport.py',
    'naver_runtime/bootstrap.py',
    'naver_runtime/claude_provider.py',
    'naver_runtime/collection_requests.py',
    'naver_runtime/config.py',
    'naver_runtime/erp_tunnel_transport.py',
    'naver_runtime/learning_jobs.py',
    'naver_runtime/learning_provider.py',
    'naver_runtime/market_export.py',
    'naver_runtime/network_observability.py',
    'naver_runtime/observation_binding.py',
    'naver_runtime/product_export.py',
    'naver_runtime/provider_observability.py',
    'naver_runtime/report_schedule_jobs.py',
    'naver_runtime/restore_check.py',
    'naver_runtime/runtime_status.py',
    'naver_runtime/scheduler.py',
    'naver_runtime/server.py',
    'naver_runtime/writer.py',
)
IMAGE_SOURCE_FILES = {relative: SOURCE_FILES[relative] for relative in IMAGE_SOURCE_PATHS}
IMAGE_SOURCE_MAP_SHA256 = '69d77f2c2ede33f35d8d424665dfd85b4a710fcf3ff5fc88a85b281ce564332f'
READ_STAGE = 'SOURCE'
READ_FAILURE_STAGE = None
READ_FAILURE_REASON = None
READ_STAGES = frozenset(('SOURCE', 'IMPORT', 'DB_OPEN', 'DB_QUERY', 'VALIDATE', 'CLEANUP'))
READ_VALUE_CODES = frozenset(('D3_DATABASE_PATH', 'D3_DEADLINE', 'D3_EXECUTION_PINS_INVALID',
    'D3_EXECUTION_PINS_PENDING', 'D3_MUTATION', 'D3_OUTPUT_SHAPE', 'D3_READER_MODE',
    'D3_READ_BOUND', 'D3_SCHEMA', 'D3_SETUP_SHAPE', 'D3_SHAPE', 'D3_SOURCE_IMPORT',
    'D3_SOURCE_PIN', 'D3_TIME', 'D3_UI_BRANCH_MISMATCH'))
READ_REASONS = READ_VALUE_CODES | frozenset(('D3_SQLITE_AUTH', 'D3_SQLITE_BUSY',
    'D3_SQLITE_OTHER', 'D3_UNCLASSIFIED'))


def classify_reader_failure(error):
    # 원문·SQL·경로·예외명은 보존하지 않고 기존 코드와 SQLite 숫자만 분류한다.
    if type(error) is ValueError and len(error.args) == 1:
        code = error.args[0]
        if type(code) is str and code in READ_VALUE_CODES:
            return code
    if isinstance(error, sqlite3.Error):
        try:
            code = getattr(error, 'sqlite_errorcode', None)
        except Exception:
            return 'D3_SQLITE_OTHER'
        if type(code) is int:
            primary = code & 255
            if primary == sqlite3.SQLITE_AUTH:
                return 'D3_SQLITE_AUTH'
            if primary in (sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED):
                return 'D3_SQLITE_BUSY'
        return 'D3_SQLITE_OTHER'
    return 'D3_UNCLASSIFIED'


def require_execution_pins():
    # 경로·호출자·파일·모듈·DB에 접근하기 전 실행 증거부터 닫힌다.
    if set(EXECUTION_PINS) != PIN_FIELDS or any(value is None for value in EXECUTION_PINS.values()):
        raise ValueError('D3_EXECUTION_PINS_PENDING')
    if any(type(v) is not str or re.fullmatch('[0-9a-f]{64}', v) is None for v in EXECUTION_PINS.values()):
        raise ValueError('D3_EXECUTION_PINS_INVALID')
    if EXECUTION_PINS['canonical_receipt'] != CANONICAL_SHA256:
        raise ValueError('D3_EXECUTION_PINS_INVALID')


def verify_host_source(root):
    root = Path(root)
    if root.is_symlink() or root.resolve() != root or len(SOURCE_FILES) != 163:
        raise ValueError('D3_SOURCE_PIN')
    for relative, expected in SOURCE_FILES.items():
        p = Path(relative)
        if p.is_absolute() or '..' in p.parts or p.name in ('store 2.py', 'HANDOVER.md') or p.name.startswith('.env'):
            raise ValueError('D3_SOURCE_PIN')
        target = root / p
        if target.is_symlink() or target.resolve() != target or not target.is_file():
            raise ValueError('D3_SOURCE_PIN')
        stat = target.stat()
        if stat.st_size != expected['bytes'] or stat.st_mode & 0o777 != expected['mode']:
            raise ValueError('D3_SOURCE_PIN')
        if hashlib.sha256(target.read_bytes()).hexdigest() != expected['sha256']:
            raise ValueError('D3_SOURCE_PIN')
    return root


def verify_source(root):
    root = Path(root)
    if root.is_symlink() or root.resolve() != root or len(IMAGE_SOURCE_FILES) != 106:
        raise ValueError('D3_SOURCE_PIN')
    if (tuple(IMAGE_SOURCE_FILES) != IMAGE_SOURCE_PATHS
            or any(SOURCE_FILES.get(name) != row for name, row in IMAGE_SOURCE_FILES.items())
            or hashlib.sha256(json.dumps(IMAGE_SOURCE_FILES, sort_keys=True, separators=(',', ':')).encode()).hexdigest() != IMAGE_SOURCE_MAP_SHA256):
        raise ValueError('D3_SOURCE_PIN')
    for relative, expected in IMAGE_SOURCE_FILES.items():
        p = Path(relative)
        if p.is_absolute() or '..' in p.parts or p.name in ('store 2.py', 'HANDOVER.md') or p.name.startswith('.env'):
            raise ValueError('D3_SOURCE_PIN')
        target = root / p
        if target.is_symlink() or target.resolve() != target or not target.is_file():
            raise ValueError('D3_SOURCE_PIN')
        stat = target.stat()
        if stat.st_size != expected['bytes'] or stat.st_mode & 0o777 != expected['mode']:
            raise ValueError('D3_SOURCE_PIN')
        if hashlib.sha256(target.read_bytes()).hexdigest() != expected['sha256']:
            raise ValueError('D3_SOURCE_PIN')
    return root


def load_modules(root):
    global READ_STAGE
    root = verify_source(root)
    READ_STAGE = 'IMPORT'
    for name, module in tuple(sys.modules.items()):
        if name in ('naver_engine','naver_runtime','app','app.naver_auto') or name.startswith(('naver_engine.', 'naver_runtime.', 'app.naver_auto.')):
            path = getattr(module, '__file__', None)
            if path is not None and not Path(path).resolve().is_relative_to(root):
                raise ValueError('D3_SOURCE_IMPORT')
    sys.path[:0] = [str(root), str(root/'backend')]
    names = {'S':'naver_engine.store', 'MS':'naver_engine.management_store', 'IS':'naver_engine.inspection_store',
             'IR':'naver_engine.inspection_reads', 'IC':'naver_engine.inspection_catalog',
             'P':'naver_engine.management', 'I':'naver_engine.inventory', 'Y':'naver_engine.sync',
             'O':'app.naver_auto.org_snapshot', 'SC':'app.naver_auto.scope', 'RV':'naver_engine.report_views',
             'J':'naver_runtime.learning_jobs', 'C':'naver_engine.setup_checks'}
    result = {key:importlib.import_module(name) for key,name in names.items()}
    for name, module in tuple(sys.modules.items()):
        if name.startswith(('naver_engine.', 'naver_runtime.', 'app.naver_auto.')):
            path = getattr(module, '__file__', None)
            if path is not None:
                resolved = Path(path).resolve()
                if not resolved.is_relative_to(root) or resolved.relative_to(root).as_posix() not in IMAGE_SOURCE_FILES:
                    raise ValueError('D3_SOURCE_IMPORT')
    return result


def private_json(raw, maximum):
    if type(raw) is not str or len(raw.encode('utf8')) > maximum:
        raise ValueError('D3_SHAPE')
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError('D3_SHAPE')
            result[key] = value
        return result
    def no_constant(_):
        raise ValueError('D3_SHAPE')
    return json.loads(raw, object_pairs_hook=unique, parse_constant=no_constant)


def at(value):
    if type(value) is not str or not 20 <= len(value) <= 40:
        raise ValueError('D3_TIME')
    parsed = datetime.fromisoformat(value)
    if parsed.utcoffset() is None:
        raise ValueError('D3_TIME')
    return parsed.astimezone(KST)


def stamp(value):
    return None if value is None else at(value).isoformat()


def closed(value, allowed):
    return value if type(value) is str and value in allowed else 'UNRECOGNIZED'


def rows(connection, query, parameters, limit, deadline):
    if time.monotonic() >= deadline:
        raise ValueError('D3_DEADLINE')
    cursor = connection.execute(query, parameters)
    names = [column[0] for column in cursor.description]
    values = cursor.fetchmany(limit+1)
    cursor.close()
    if len(values) > limit or time.monotonic() >= deadline:
        raise ValueError('D3_READ_BOUND')
    return [dict(zip(names, row)) for row in values]


def readonly_authorizer(action, arg1, arg2, database, source):
    if action in (sqlite3.SQLITE_SELECT, sqlite3.SQLITE_READ):
        return sqlite3.SQLITE_OK
    if action == sqlite3.SQLITE_TRANSACTION and arg1 in ('BEGIN', 'ROLLBACK'):
        return sqlite3.SQLITE_OK
    if action == sqlite3.SQLITE_FUNCTION and (arg2 or '').lower() in ('count','length','sum','max','min','coalesce','substr'):
        return sqlite3.SQLITE_OK
    if action == sqlite3.SQLITE_PRAGMA and arg2 is None and (arg1 or '').lower() in ('query_only','database_list'):
        return sqlite3.SQLITE_OK
    if action == sqlite3.SQLITE_PRAGMA and arg1 == 'table_info' and arg2 == 'naver_auto_link_memory':
        return sqlite3.SQLITE_OK
    return sqlite3.SQLITE_DENY


def connect_reader(path):
    if not isinstance(path, Path) or path.is_symlink() or path.resolve() != path or not path.is_file():
        raise ValueError('D3_DATABASE_PATH')
    connection = sqlite3.connect(path.as_uri()+'?mode=ro', uri=True, isolation_level=None, timeout=1)
    try:
        connection.execute('PRAGMA query_only=ON')
        connection.execute('PRAGMA busy_timeout=1000')
        connection.execute('PRAGMA trusted_schema=OFF')
        connection.set_authorizer(readonly_authorizer)
        if connection.execute('PRAGMA query_only').fetchone() != (1,) or connection.execute('PRAGMA database_list').fetchall() != [(0,'main',str(path))]:
            raise ValueError('D3_READER_MODE')
        return connection
    except BaseException:
        connection.close()
        raise


def bounds(store, deadline):
    c = store._conn
    if c.execute("SELECT CASE WHEN length(CAST(value AS BLOB))<=2 THEN value END FROM naver_auto_meta WHERE key='schema_version'").fetchone() != ('21',):
        raise ValueError('D3_SCHEMA')
    for table in ('naver_auto_inspection_job', 'naver_auto_performance_job'):
        if c.execute('SELECT count(*) FROM '+table).fetchone()[0] > MAX_JOBS:
            raise ValueError('D3_READ_BOUND')
    metadata = rows(c,'SELECT length(CAST(value AS BLOB)) AS size FROM naver_auto_meta',(),MAX_META_ROWS,deadline)
    if any(type(x['size']) is not int or not 0 <= x['size'] <= 16*1024*1024 for x in metadata) or sum(x['size'] for x in metadata) > 64*1024*1024:
        raise ValueError('D3_READ_BOUND')
    accounts = rows(c,'SELECT customer_id,ad_account_no,present FROM naver_auto_account',(),MAX_ACCOUNTS,deadline)
    found = [a for a in accounts if type(a['present']) is int and a['present'] == 1 and type(a['ad_account_no']) is int and a['ad_account_no'] == ADNO]
    if len(found) != 1 or type(found[0]['customer_id']) is not int or not 0 < found[0]['customer_id'] < 10**15:
        return None
    return found[0]['customer_id']


def event_owner(store, now, deadline, modules, cid, policy):
    """고정된 실제 07:10 수동 이벤트의 소유자 발견; 현재 로그인 UID를 추정하지 않는다."""
    if not policy or policy['possibility_id'] != PID or policy['matched'] is not True or policy['source_current'] is not True:
        return False
    c, J = store._conn, modules['J']
    key = modules['RV'].account_key(cid)
    saved = rows(c,'SELECT report_id,revision_fingerprint,CASE WHEN length(CAST(payload_json AS BLOB))<=8388608 THEN payload_json END AS payload FROM naver_auto_report_snapshot WHERE possibility_id=? AND period_key=? ORDER BY report_id DESC LIMIT 1',(PID,PERIOD_KEY),1,deadline)
    if len(saved) != 1:
        return False
    report = saved[0]
    rid, fingerprint = report['report_id'], report['revision_fingerprint']
    if type(rid) is not int or rid <= 0 or type(fingerprint) is not str or not re.fullmatch('[0-9a-f]{64}',fingerprint):
        return False
    payload = private_json(report['payload'],MAX_BODY)
    account = payload.get('_account_reports',{}).get(str(cid)) if type(payload) is dict else None
    if (type(payload) is not dict or payload.get('revision_fingerprint') != fingerprint or payload.get('period_key') != PERIOD_KEY
            or type(payload.get('period')) is not dict or any(payload['period'].get(k) != v for k,v in PERIOD.items()) or type(payload.get('revision_no')) is not int or payload['revision_no'] != 4
            or type(account) is not dict or account.get('period') != payload['period'] or account.get('period_key') != PERIOD_KEY
            or type(account.get('revision_no')) is not int or account['revision_no'] != 4):
        return False
    if '_expected_customers' in account and (type(account['_expected_customers']) is not list or len(account['_expected_customers']) != 1 or type(account['_expected_customers'][0]) is not int or account['_expected_customers'] != [cid]):
        return False
    dirty = c.execute('SELECT pending FROM naver_auto_report_dirty WHERE possibility_id=? AND period_key=?',(PID,PERIOD_KEY)).fetchone()
    if dirty is not None and (type(dirty[0]) is not int or dirty[0] != 0):
        return False
    if c.execute('SELECT 1 FROM naver_auto_meta WHERE key=?',('report-strategy-head:'+str(rid)+':'+key,)).fetchone():
        return False
    matches = []
    for record in rows(c,'SELECT key,CASE WHEN length(CAST(value AS BLOB))<=4096 THEN value END AS value FROM naver_auto_meta WHERE key>=? AND key<? ORDER BY key LIMIT 101',(J.PREFIX,J.PREFIX+'\uffff'),100,deadline):
        job = J.clean(private_json(record['value'],4096))
        identity = J.identity(job['actor'],job['narrowed'],job['report_id'],job['account_key'],job['revision_fingerprint'],job['expected_version'])
        if record['key'] != J.PREFIX+identity:
            return False
        if (job['report_id'],job['account_key'],job['revision_fingerprint'],job['expected_version']) != (rid,key,fingerprint,0):
            continue
        reservations = rows(c,'SELECT CASE WHEN length(CAST(value AS BLOB))<=2048 THEN value END AS value FROM naver_auto_meta WHERE key=?',('learning-call:'+job['job_id'],),1,deadline)
        if len(reservations) != 1:
            continue
        reserved = private_json(reservations[0]['value'],2048)
        expected = dict(actor=job['actor'],proof_hash=job['proof_hash'],report_id=rid,account_key=key,possibility_id=PID)
        if (type(reserved) is not dict or set(reserved) != set(expected)|{'at','reserved_microusd'}
                or any(type(reserved[k]) is not type(v) or reserved[k] != v for k,v in expected.items())
                or type(reserved['reserved_microusd']) is not int or not 0 < reserved['reserved_microusd'] <= 10**12):
            return False
        reserved_at = at(reserved['at'])
        if not EVENT_FROM <= reserved_at < EVENT_UNTIL:
            continue
        if job['state'] not in ('failed','interrupted') or not at(job['created_at']) <= reserved_at <= at(job['updated_at']) < at(job['expires_at']) or at(job['updated_at']) > now:
            return False
        bindings = rows(c,'SELECT trace_id,job_id,actor,possibility_id,account_key,report_id,origin,created_at,reserved_microusd,proof_hash FROM naver_auto_provider_binding WHERE job_id=?',(job['job_id'],),2,deadline)
        if len(bindings) != 1:
            return False
        binding = bindings[0]
        binding_expected = dict(job_id=job['job_id'],actor=job['actor'],possibility_id=PID,account_key=key,report_id=rid,
                                origin='manual_async',created_at=reserved['at'],reserved_microusd=reserved['reserved_microusd'],proof_hash=job['proof_hash'])
        if any(type(binding[k]) is not type(v) or binding[k] != v for k,v in binding_expected.items()) or type(binding['trace_id']) is not str or not re.fullmatch('[0-9a-f]{32}',binding['trace_id']):
            return False
        matches.append(job)
    if len(matches) != 1:
        return False
    job = matches[0]
    try:
        store._learning_actor(PID,key,job['actor'],now,narrowed=job['narrowed'])
        scope_pid, scope_period, _ = store._report_notes_scope(c,rid,key,fingerprint)
        if scope_pid != PID or scope_period != PERIOD_KEY:
            return False
    except (modules['S'].StoreRefused,modules['SC'].ScopeError,modules['RV'].QueryInvalid,modules['RV'].SourceUnavailable):
        return False
    return True


def actual_setup(observation):
    if observation is None:
        return dict(present=False,status=None,error_code=None,stale=None,complete=False,generation_present=False,checked_at_present=False)
    if type(observation) is not dict or any(type(observation[k]) is not bool for k in ('stale','complete')):
        raise ValueError('D3_SETUP_SHAPE')
    return dict(present=True,status=closed(observation['status'],STATUSES),
                error_code=None if observation['error_code'] is None else closed(observation['error_code'],ERRORS),
                stale=observation['stale'],complete=observation['complete'],generation_present=observation['generation'] is not None,
                checked_at_present=observation['checked_at'] is not None)


def expected_setup(branch,row):
    out = dict(present=True,status='pending',error_code=None,stale=True,complete=False,generation_present=False,checked_at_present=False)
    if branch == 'NO_OBSERVATION':
        return dict(out,present=False,status=None,stale=None)
    if branch in ('POLICY_INACTIVE','CURRENT_ROW_INVALID'):
        out['error_code'] = 'SOURCE_STALE'
    elif branch == 'MANUAL_PENDING':
        out.update(error_code='MANUAL_PENDING',stale=False,generation_present=True)
    elif branch in ('FUTURE_CHECKED_AT','CURRENT_PARTIAL','CHECKPOINT_INVALID','CURRENT_COMPLETE'):
        out.update(status=closed(row['status'],STATUSES),error_code=None if row['error_code'] is None else closed(row['error_code'],ERRORS),stale=False,generation_present=True,checked_at_present=True)
        if branch == 'FUTURE_CHECKED_AT':
            out.update(status='pending',error_code='CHECKPOINT_INVALID',stale=True,checked_at_present=False)
        elif branch == 'CHECKPOINT_INVALID':
            out.update(status='limited',error_code='CHECKPOINT_INVALID')
        elif branch == 'CURRENT_COMPLETE':
            out['complete'] = True
    return out


def inspection_projection(store,now,deadline,modules,cid,policy,states,catalog,snapshot,fingerprint):
    c, S, IS, P = store._conn,modules['S'],modules['IS'],modules['P']
    active = policy['decision'].cadence != 'blocked'
    revision = policy['stage_revision']
    exists = c.execute('SELECT 1 FROM naver_auto_inspection_job WHERE customer_id=? LIMIT 1',(cid,)).fetchone() is not None
    requests = rows(c,'SELECT * FROM naver_auto_manual_read WHERE customer_id=?',(cid,),1,deadline)
    request = requests[0] if requests else None
    manual = store._inspection_manual_job(request,policy,snapshot,catalog['generated_at'],fingerprint,now) if active and request and catalog and snapshot is not None else None
    cadence = policy['decision'].cadence
    cycle = str(P.period_for(cadence,now).cycle_day) if active else None
    selected = rows(c,"SELECT "+JOB_COLUMNS+" FROM naver_auto_inspection_job WHERE customer_id=? AND possibility_id IS ? AND stage_revision=? AND ((kind=? AND cycle_day=?) OR (kind='manual' AND generation=?)) ORDER BY generation DESC,checked_at DESC,rowid DESC LIMIT 1",(cid,PID,revision,cadence,cycle,manual['generation'] if manual else None),1,deadline) if active else []
    row = selected[0] if selected else None
    # 이 제한 검사 뒤에만 기존 Store가 progress/history 본문을 읽는다.
    sizes = rows(c,'SELECT length(CAST(body_json AS BLOB)) AS size FROM naver_auto_setting_observation WHERE customer_id=? AND possibility_id IS ? AND stage_revision=? ORDER BY history_id DESC LIMIT 200',(cid,PID,revision),200,deadline)
    if row and row['progress_size'] is not None:
        sizes.append({'size':row['progress_size']})
    if any(type(v['size']) is not int or not 0 <= v['size'] <= MAX_BODY for v in sizes) or sum(v['size'] for v in sizes) > MAX_BODIES:
        raise ValueError('D3_READ_BOUND')
    if row is not None:
        row = rows(c,'SELECT * FROM naver_auto_inspection_job WHERE job_key=?',(row['job_key'],),1,deadline)[0]
    job = IS._job(row) if row else None
    current_cycle = bool(row and (row['cycle_day'] == cycle if row['kind'] != 'manual' else row['cycle_day'] == str(now.date()) and manual is not None and row['generation'] == manual['generation']))
    valid = bool(job and store.inspection_account_valid(job,now))
    context_valid = bool(row and store._inspection_context(c,row,now,store._inspection_catalog_proof(now)) is not None)
    progress = None
    shape_valid = False
    if job:
        try:
            progress = store.inspection_progress(job)
            shape_valid = progress is not None
        except (modules['IR'].CheckpointInvalid,TypeError,ValueError):
            pass
    confirmed = bool(progress and progress['confirmed'] is True)
    queue_count, next_index = (len(progress['queue']),progress['next_index']) if progress else (None,None)
    time_valid = bool(progress and all(at(t) <= now for t in IS._observed_times(progress)) and at(row['generation']) <= now)
    observation = store.setup_observation(cid,now)
    if (not exists and not request) or (not exists and manual is None):
        branch = 'NO_OBSERVATION'
    elif not active:
        branch = 'POLICY_INACTIVE'
    elif manual is not None and (row is None or row['generation'] < manual['generation']):
        branch = 'MANUAL_PENDING'
    elif row is None:
        branch = 'NO_CURRENT_SCOPE_ROW'
    elif not current_cycle:
        branch = 'CYCLE_NOT_CURRENT'
    elif not valid:
        branch = 'CURRENT_ROW_INVALID'
    elif at(row['checked_at']) > now:
        branch = 'FUTURE_CHECKED_AT'
    elif row['status'] != 'ok':
        branch = 'CURRENT_PARTIAL'
    elif not (shape_valid and confirmed and next_index == queue_count and time_valid):
        branch = 'CHECKPOINT_INVALID'
    else:
        branch = 'CURRENT_COMPLETE'
    agrees = actual_setup(observation) == expected_setup(branch,row)
    ui = modules['C'].project_setup(now=now,observation=observation)
    meta = ui['source']['structure']
    # UI usable는 설정 전체 승인과 다르다. 완결 checkpoint+시간 최신성만 대조한다.
    expected_meta = modules['C']._meta(observation,now) if observation is not None else modules['C']._meta(None,now,structure=True)
    agrees = agrees and all(meta[k] == expected_meta[k] for k in ('status','checked_at','complete','freshness'))
    agrees = agrees and ui['source']['kind'] == ('shared_setup_observation' if observation is not None else 'stored_observations')
    if branch != 'CURRENT_COMPLETE':
        agrees = agrees and meta['usable'] is False
    if not agrees:
        raise ValueError('D3_UI_BRANCH_MISMATCH')
    req_at = at(request['requested_at']) if request else None
    if req_at is not None and req_at > now:
        raise ValueError('D3_TIME')
    actor_pid_valid = False
    if request and request['possibility_id'] == PID and type(request['actor']) is int:
        try:
            modules['MS'].require_action(store,now,request['actor'],cid,possibility_id=PID,allow_unmatched=True)
            actor_pid_valid = True
        except (modules['S'].StoreRefused,modules['SC'].ScopeError):
            pass
    manual_out = dict(present=request is not None,request_kind=closed(request.get('request_kind') or 'manual',KINDS) if request else None,
        requested_today=req_at.date() == now.date() if req_at else False,consumed=bool(request and request['consumed_at'] is not None),
        actor_pid_valid=actor_pid_valid,one_hour_wait=bool(req_at and req_at <= now < req_at+timedelta(hours=1)),requested_at=stamp(request['requested_at']) if request else None)
    return dict(scope_row_exists=row is not None,kind=closed(row['kind'],KINDS) if row else None,
        status=closed(row['status'],STATUSES) if row else None,cycle_day=str(date.fromisoformat(row['cycle_day'])) if row else None,
        checked_at=stamp(row['checked_at']) if row else None,error_code=None if not row or row['error_code'] is None else closed(row['error_code'],ERRORS),
        current_valid=valid,progress_shape_valid=shape_valid,progress_context_valid=context_valid,confirmed=confirmed,
        queue_count=queue_count,next_index=next_index,retry_due=bool(row and store._collection_retry_ready(row,S._kst_text(now,'현재'))),
        ui_branch=branch,ui_setup_branch_agreement=agrees), manual_out


def overlap_projection(store,now,deadline,modules,cid,cadence):
    end = now.date()-timedelta(days=1)
    start = end if cadence == 'daily' else end-timedelta(days=6)
    candidates = rows(store._conn,"SELECT kind,status,error_code,next_try_at,checked_at,attempts FROM naver_auto_performance_job WHERE customer_id=? AND possibility_id=? AND period_start<=? AND period_end>=? AND status IN ('reading','retry','partial','source_wait')",(cid,PID,str(end),str(start)),1000,deadline)
    groups = {}
    for row in candidates:
        kind,status = closed(row['kind'],PERFORMANCE_KINDS),closed(row['status'],STATUSES)
        error = None if row['error_code'] is None else closed(row['error_code'],ERRORS)
        due = bool(store._collection_retry_ready(row,modules['S']._kst_text(now,'현재')))
        group = (kind,status,error,due)
        groups[group] = groups.get(group,0)+1
    return dict(overlap_count=len(candidates),closed_groups=[dict(kind=k,status=s,error_code=e,retry_due=d,count=n) for (k,s,e,d),n in sorted(groups.items(),key=lambda x:repr(x[0]))])


def collect(store,now,modules,*,deadline=None):
    if store.writer is not False or not store._conn.in_transaction or store._conn.execute('PRAGMA query_only').fetchone() != (1,):
        raise ValueError('D3_READER_MODE')
    if not isinstance(now,datetime) or now.utcoffset() is None:
        raise ValueError('D3_TIME')
    now = now.astimezone(KST)
    deadline = time.monotonic()+20 if deadline is None else deadline
    c, before = store._conn,store._conn.total_changes
    empty = dict(source_commit=SOURCE,schema=21,authorization='UNKNOWN',identity=None,inspection=None,manual=None,same_pid_performance=None,mutations=0)
    cid = bounds(store,deadline)
    if cid is None:
        return empty
    S, MS, I, O, Y = (modules[k] for k in ('S','MS','I','O','Y'))
    states = store.management_states()
    policies = MS.snapshot(store,now,stage_states=states)
    policy = policies.get(cid)
    try:
        if not event_owner(store,now,deadline,modules,cid,policy):
            return empty
    except (ValueError,TypeError,KeyError,OverflowError,RecursionError,UnicodeError,sqlite3.Error):
        return empty
    catalog,catalog_state = I.catalog_status(store,now)
    snapshot = store.inventory_snapshot(now)
    identity = dict(current_mapping=bool(policy and policy['possibility_id'] == PID and policy['matched'] is True),
        policy_source_current=policy['source_current'] is True,org_current=O.allows_raising(Y.org_freshness(store,now)),
        catalog_accepted=catalog_state == 'accepted',inventory_current=snapshot is not None,authority_valid=True,pid=PID,
        stage=closed(policy['stage_key'],STAGES),cadence=closed(policy['decision'].cadence,{'daily','weekly','blocked'}),canonical_ad_account_namespace_resolved=True)
    inspection,manual = inspection_projection(store,now,deadline,modules,cid,policy,states,catalog,snapshot,store.decision_fingerprint())
    overlap = overlap_projection(store,now,deadline,modules,cid,policy['decision'].cadence)
    if c.total_changes != before:
        raise ValueError('D3_MUTATION')
    result = dict(empty,authorization='OBSERVED_EVENT_OWNER_CURRENTLY_AUTHORIZED',identity=identity,inspection=inspection,manual=manual,same_pid_performance=overlap)
    validate_result(result)
    return result


def validate_result(result):
    names = {'source_commit','schema','authorization','identity','inspection','manual','same_pid_performance','mutations'}
    if type(result) is not dict or set(result) != names or result['source_commit'] != SOURCE or type(result['schema']) is not int or result['schema'] != 21 or type(result['mutations']) is not int or result['mutations'] != 0:
        raise ValueError('D3_OUTPUT_SHAPE')
    if result['authorization'] == 'UNKNOWN':
        if any(result[k] is not None for k in ('identity','inspection','manual','same_pid_performance')):
            raise ValueError('D3_OUTPUT_SHAPE')
        return result
    if result['authorization'] != 'OBSERVED_EVENT_OWNER_CURRENTLY_AUTHORIZED':
        raise ValueError('D3_OUTPUT_SHAPE')
    identity,inspection,manual,overlap = (result[k] for k in ('identity','inspection','manual','same_pid_performance'))
    fields = {'current_mapping','policy_source_current','org_current','catalog_accepted','inventory_current','authority_valid','pid','stage','cadence','canonical_ad_account_namespace_resolved'}
    if type(identity) is not dict or set(identity) != fields or type(identity['pid']) is not int or identity['pid'] != PID or identity['stage'] not in STAGES|{'UNRECOGNIZED'} or identity['cadence'] not in {'daily','weekly','blocked','UNRECOGNIZED'}:
        raise ValueError('D3_OUTPUT_SHAPE')
    if any(type(identity[k]) is not bool for k in fields-{'pid','stage','cadence'}):
        raise ValueError('D3_OUTPUT_SHAPE')
    if type(inspection) is not dict or set(inspection) != set('scope_row_exists kind status cycle_day checked_at error_code current_valid progress_shape_valid progress_context_valid confirmed queue_count next_index retry_due ui_branch ui_setup_branch_agreement'.split()):
        raise ValueError('D3_OUTPUT_SHAPE')
    if any(type(inspection[k]) is not bool for k in ('scope_row_exists','current_valid','progress_shape_valid','progress_context_valid','confirmed','retry_due','ui_setup_branch_agreement')) or inspection['ui_branch'] not in BRANCHES:
        raise ValueError('D3_OUTPUT_SHAPE')
    for key, allowed in (('kind',KINDS),('status',STATUSES),('error_code',ERRORS)):
        if inspection[key] is not None and inspection[key] not in allowed|{'UNRECOGNIZED'}:
            raise ValueError('D3_OUTPUT_SHAPE')
    for key in ('queue_count','next_index'):
        if inspection[key] is not None and (type(inspection[key]) is not int or not 0 <= inspection[key] <= 32768):
            raise ValueError('D3_OUTPUT_SHAPE')
    if (inspection['queue_count'] is None) != (inspection['next_index'] is None):
        raise ValueError('D3_OUTPUT_SHAPE')
    if inspection['queue_count'] is not None and inspection['next_index'] > inspection['queue_count']:
        raise ValueError('D3_OUTPUT_SHAPE')
    if inspection['ui_branch'] == 'CURRENT_COMPLETE' and (not all(inspection[k] is True for k in ('scope_row_exists','current_valid','progress_shape_valid','progress_context_valid','confirmed','ui_setup_branch_agreement')) or inspection['queue_count'] is None or inspection['next_index'] != inspection['queue_count'] or inspection['status'] != 'ok'):
        raise ValueError('D3_OUTPUT_SHAPE')
    if inspection['cycle_day'] is not None:
        date.fromisoformat(inspection['cycle_day'])
    if inspection['checked_at'] is not None:
        at(inspection['checked_at'])
    if type(manual) is not dict or set(manual) != set('present request_kind requested_today consumed actor_pid_valid one_hour_wait requested_at'.split()) or any(type(manual[k]) is not bool for k in ('present','requested_today','consumed','actor_pid_valid','one_hour_wait')):
        raise ValueError('D3_OUTPUT_SHAPE')
    if manual['request_kind'] is not None and manual['request_kind'] not in KINDS|{'UNRECOGNIZED'}:
        raise ValueError('D3_OUTPUT_SHAPE')
    if manual['requested_at'] is not None:
        at(manual['requested_at'])
    if type(overlap) is not dict or set(overlap) != {'overlap_count','closed_groups'} or type(overlap['overlap_count']) is not int or not 0 <= overlap['overlap_count'] <= 1000 or type(overlap['closed_groups']) is not list or len(overlap['closed_groups']) > 1000:
        raise ValueError('D3_OUTPUT_SHAPE')
    for group in overlap['closed_groups']:
        if type(group) is not dict or set(group) != {'kind','status','error_code','retry_due','count'} or group['kind'] not in PERFORMANCE_KINDS|{'UNRECOGNIZED'} or group['status'] not in {'reading','retry','partial','source_wait','UNRECOGNIZED'} or (group['error_code'] is not None and group['error_code'] not in ERRORS|{'UNRECOGNIZED'}) or type(group['retry_due']) is not bool or type(group['count']) is not int or not 1 <= group['count'] <= 1000:
            raise ValueError('D3_OUTPUT_SHAPE')
    if sum(g['count'] for g in overlap['closed_groups']) != overlap['overlap_count']:
        raise ValueError('D3_OUTPUT_SHAPE')
    if len(json.dumps(result,sort_keys=True,separators=(',',':'),allow_nan=False).encode()) > 16384:
        raise ValueError('D3_OUTPUT_SHAPE')
    return result


def read_database(database_path,product_root,*,now=None):
    global READ_STAGE, READ_FAILURE_STAGE, READ_FAILURE_REASON
    READ_STAGE = 'SOURCE'
    READ_FAILURE_STAGE = None
    READ_FAILURE_REASON = None
    require_execution_pins()
    reader = None
    c = None
    failure = None
    result = None
    try:
        modules = load_modules(product_root)
        READ_STAGE = 'DB_OPEN'
        c = connect_reader(Path(database_path))
        READ_STAGE = 'DB_QUERY'
        reader = modules['S'].Store(c,str(database_path),None,writer=False)
        deadline = time.monotonic()+20
        before = c.total_changes
        c.set_progress_handler(lambda:time.monotonic() >= deadline,1000)
        c.execute('BEGIN')
        result = collect(reader,datetime.now(KST) if now is None else now,modules,deadline=deadline)
        if c.total_changes != before:
            raise ValueError('D3_MUTATION')
        READ_STAGE = 'VALIDATE'
        validate_result(result)
    except Exception as error:
        # DB/OS/Store 예외의 원문·경로·SQL·행·값은 호출자에게 전달하지 않는다.
        failure = 'D3_READ_FAILED'
        READ_FAILURE_STAGE = READ_STAGE
        READ_FAILURE_REASON = classify_reader_failure(error)
    finally:
        READ_STAGE = 'CLEANUP'
        try:
            if c is not None and c.in_transaction:
                c.execute('ROLLBACK')
        except Exception as error:
            if failure is None:
                READ_FAILURE_STAGE = 'CLEANUP'
                READ_FAILURE_REASON = classify_reader_failure(error)
            failure = failure or 'D3_CLEANUP_FAILED'
        finally:
            try:
                if reader is not None:
                    reader.close()
                elif c is not None:
                    c.close()
            except Exception as error:
                if failure is None:
                    READ_FAILURE_STAGE = 'CLEANUP'
                    READ_FAILURE_REASON = classify_reader_failure(error)
                failure = failure or 'D3_CLEANUP_FAILED'
    if failure is not None:
        raise ValueError(failure) from None
    return result
