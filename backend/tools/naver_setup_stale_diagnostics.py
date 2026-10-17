"""Fixed dc168 schema21 read-only setup source validity diagnosis.

No writer, scheduler tick, collector, provider, environment or raw log reads.
Only setup policy, selected scope and current binding checks leave the reader.
"""
import hashlib
import json
import os
from pathlib import Path
import re

STAGE = 'input'
SOURCE = 'b5e40fa01e6432ab0a62541c330652e1cb4fae2c'
ARCHIVE = '1d3857f19aa8d4eeff573b267cd4a7229df32c58ed1c063e501d3676a64e3a89'
BASELINE = '5463ca7b23575f668062e842f551170937239e625fb5a6104655c031c7e31d76'
SCHEMA = 21
PREPARE_RUN = '38726899460'
APPLY_OPERATION = '9e72159e3ce146a6ba2846396a6ce4b4'
PREVIOUS_SOURCE = '114dde8a45e1753ade0ff871f024c7e5880546c5'
MODE = 'foodin-submit-preflight-b5e-v1'
TARGET_NAMESPACE = 'ad_account_no'
# These are UI advertising-account numbers, never internal customer IDs.
TARGETS = (('gomso', 74789, 2488728), ('foodin', 51952, 1030001))
MAX_OUTPUT = 16384
CODE_PINS = {'backend/app/__init__.py': 'e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855', 'backend/app/naver_auto/__init__.py': '64020d9148504885f294af924dcea4d2f312df8b6014d646f98b9e5221a4f164', 'backend/app/naver_auto/checks.py': '79e61753a0c16f1a8106e7bec2ed89404688eb6ff9a67f8783f47d13409b0b4c', 'backend/app/naver_auto/issues.py': 'b47ab19a490c5035cec0e59d19e5720edb03d0c103fe4e1cce3abe2dace9556a', 'backend/app/naver_auto/matching.py': '6be28f0bcf2e86ff1a2d799063c3ac5caca81a33ac3572ed7f754aef14bb3eb0', 'backend/app/naver_auto/org_snapshot.py': '34da0635ee7d071c3dd02bf4001343f2c42001ebc70d7e5548e692d687920f97', 'backend/app/naver_auto/scope.py': 'fd25fae418f27e6bd9b01415489164eb85241a5151a3e5fa1ad085edec7b3cd7', 'backend/app/naver_auto/thresholds.py': '6b5259480f85d0c397fac1ee7884a4beb14e0ee60da02669c104b21131498aa7', 'backend/app/naver_auto/verdict.py': 'b8ff947d92e9dd0e0ceafd6b1da2e7dc3841875811417e83ae387ba0074809ec', 'naver_engine/__init__.py': '83ca0328fd0eb93b016be936321703ae88df5d3410b369df18c5c7290ed6bf74', 'naver_engine/ad_reasons.py': '12cb7edc84f8f302036c16677ae51ebbbbc117aa1feba6f58fb32b906501beec', 'naver_engine/alerts.py': 'bc4636d8b6f685e02a9305061926299f9fa52f50fbcf6c6e4cb9da8b29d1c35d', 'naver_engine/approval_documents.py': '47de41a6c0840710e62b56135593b0c00e99b41053630c3f37b79d2231c17243', 'naver_engine/automation_views.py': 'fbbb0f4d371d6a6061c60551c3b771a38b13a7ea24c1e79ec479aeb1bd1ab713', 'naver_engine/backup.py': '1bc2561ea3d8cc5f528b64ed275da4ca242fe9a5cf166c6bb53aaf6c0ff3a92e', 'naver_engine/catalog_links.py': '2984a7582347cad4580be1f25bdee93146e933222f3b783cc2a1bb5ae6478b7b', 'naver_engine/collection_diagnostics.py': '114806cdfb07eeeef2ac365a460e941d2741d6345b165c8428caf4344b2cacd6', 'naver_engine/credentials.py': 'f20794c7f89ee29c396fa596ff44c6781bd87872914d08f58b83d15b88df3c84', 'naver_engine/dashboard.py': '2c2c86c96f249f133220463f8988b96e07eee795d44dbc844204943370206f15', 'naver_engine/erp_alert.py': '55e639ccb747e8e5f34af80e9802e03a0b650c26d06c89531b12ce5b2b8abf92', 'naver_engine/erp_profile.py': '108b4ee5d97dfa6174ccca18c5e92e9308976a349c6a648985a7ac45ea75986c', 'naver_engine/erp_read.py': '50434c7943a23ab195b2325a74ef977e9d0e0bff02572175b8994536bf7f3cdc', 'naver_engine/execution_commands.py': '9def0f8399017376226f3c7ce4477119a9cb19e99a597cbf1f10bbc9066ecc6e', 'naver_engine/execution_store.py': 'c4da4337ac0e754b577049f3aaf600542866b9ba90767dbab8c8f86a31ebd650', 'naver_engine/experiments.py': 'f99a213727b258aaf88f6769328c2f7a602109466efdbf00a8da33bf7cbad9ff', 'naver_engine/experiments_reads.py': '1758861970173d771c805813bc949c77c4559337a0bd7c60416be134513b5ccc', 'naver_engine/experiments_store.py': '5e6db883b0ab270a955e90ff5676f61cf0bbc22b4aab348cf968e96a85a6db74', 'naver_engine/fields.py': 'a92d4182bad903bb3e5c22519ea93dace5041475bc874967024cc34f5e340a6a', 'naver_engine/funnel_evidence.py': '6a25abe8756912cfe130ddb5e99fc26107b34f94ad5c296494e682ebed7f1514', 'naver_engine/funnel_reads.py': 'f8959edabea14f723a7c8fa3d40c99a1e0e6740deba31294ca2325e53ed59114', 'naver_engine/funnel_store.py': 'a320b7e2ae58e1be5e7a135cdcb4bdc0edd280db91bce4cd19887c444d0891d8', 'naver_engine/handles.py': 'fa64d8841f352b413ea12fdb8b88ab53c73133eaf0e91a98d8c586a52e8a8e14', 'naver_engine/hourly_stats.py': '287213de98df68c57634e3b6ed454bcb6df6febd12fe22effbb40281f88f2319', 'naver_engine/inspection_catalog.py': '3d0652bcb8ef6a5eef6bf16ec85f1e0319b96a078abd68381af070aa3dad46b6', 'naver_engine/inspection_fields.py': '102028ecb4f35647043b5efc1751e516c92f326252b88c3ab6c983ca7c61ba6a', 'naver_engine/inspection_reads.py': 'c0f4a0b8df790dc8d4814962722fff3f4cc379e443a18b2efe70fcccdf41d462', 'naver_engine/inspection_store.py': '1162d78edb0623fd423fc4cb5e547b16eb6861b877655a0981dc32ef479ab5ca', 'naver_engine/inventory.py': '2a5c4d5f6acb0b431daa9e16be517322a43008aa636cfdf90c49c4a9305ae28e', 'naver_engine/inventory_reads.py': '40892186fddd444f2f8868ea31323744e155d8c59eeb42b3ef6deea482a379e1', 'naver_engine/learning_assets.py': '4c3e1d6923eb0396c23e63e18c90c6077623248fc3aa05cb5071684ffde53666', 'naver_engine/learning_retrieval.py': 'f4e32d5c458014697d194c077e769ce929f677e98faaf34cc594982f992188ee', 'naver_engine/learning_source_storage.py': '144eca9e828c9f73a244b8603bf82758155c351d0586a88b7fcf012126d0935d', 'naver_engine/links.py': 'a97b7f293e32f55ac92a7b53c77884fbc50bb7d481212346f85f7dc8ae2db249', 'naver_engine/management.py': '84862507d3831053edf618c6d68e800f1f1a1ec4019bcc88030eacb4d14f37e4', 'naver_engine/management_store.py': '13ee58e1d4383acf3ab8da469e7e09b9032640c2629e601809a3991b4c650fc5', 'naver_engine/market_evidence.py': '6ee6ce06477d0c60b798a04e6679beff8ce0e056760e82bef3565764a55075ec', 'naver_engine/market_store.py': 'c8d75ab344c5cfb5ba3f034782521a5ae98e75e7083377147eb491c5917570cc', 'naver_engine/marketing_strategy.py': 'd70068f0f14e2a3e36ae56b0f89a4608f43f6e04ed1247bf4927609b739cf49d', 'naver_engine/metrics.py': 'f734fa8b2173ff5b59dcd4aeb02e61fbbe77ab23d1cc15ae6ce8441e3548564c', 'naver_engine/monthly_reads.py': 'f26214bf881b95be54fca75c941a15cb8f92f667e5af30aa94369e8fda5b7299', 'naver_engine/morning.py': 'f6cd9d4c5fd0453dcf77f707313d9c37ff6e01621e1d5f86325423b3adc94ca6', 'naver_engine/morning_progress.py': 'c6cb0faf936820a2d93b90985e0aaa1362b1bf3d3a6d98d861212c17366f54b1', 'naver_engine/naver_read.py': 'c3a8e0d0d0c6f1364ee57f3bb5d796b6b39fe2de07e0980998e2394ef4c84b7a', 'naver_engine/naver_write.py': '427f87ccdc77eb8078bae0e2744aa1d3229c99ab18957d597766e9f854eccd0e', 'naver_engine/network_observability.py': '60be59acf1ede301ea93975d6098248f608d738d7178ed8003acb0a326ebe6a5', 'naver_engine/observation_store.py': '35433ea1c7f9b39ac7793b0fe5957f871964ecbb3756b49f011ee5305b898c72', 'naver_engine/observation_views.py': '9b95662b7a39a0c36d175b6d28dbfeee4d9057d5f7713943d44bfdd088961de4', 'naver_engine/observational_inference.py': 'ff5c9706b4906372f60328c419693fadfee3895cb827bb12c9587323a4b79fb6', 'naver_engine/operating_criteria.py': '3bae3f568034d40f76ed65a34bd3b61233e0d0df718ba9db8f9bc9e710fadbe4', 'naver_engine/performance_reads.py': '85a863871288640e0a1a6745a10c618cc2e34e13dbb6de2b6fcf9b9040b3798e', 'naver_engine/product_evidence.py': '755c97900d34e06ac4a7f46c4ac3aafb3477f5a616cb560bb002f86deac87711', 'naver_engine/product_store.py': 'ffc817908ea1ed8a5e05fbc62e4185c7cdd077820199a9f99db15894c9efe303', 'naver_engine/randomized_execution.py': 'c3c01e3dbcbafaefb859410a6ecb70c24a81909543b24f48ec0b7bac69d17c86', 'naver_engine/randomized_experiments.py': '98a773addae4425cd4e3d7f6c68a3caf6981a76bd465f265cfdf237862e90829', 'naver_engine/randomized_experiments_reads.py': '8d5135161638c7a867cec5492c39f6ed4c5261b81a622437836f0b7f4f72122c', 'naver_engine/randomized_experiments_store.py': 'a7fbd33eff873d3ac540357c4c3b73b31f096503f7a62efef3b6060dcfc6c547', 'naver_engine/randomized_inference.py': '2112f900ae2b9f2188187923deb2f6d6baefcfd6496dc0e5defd4232cbafee58', 'naver_engine/report_enrichment.py': 'b151e866f561b93661ef52a7f7470f04d3f616d00de14b7e81bc2db6f5c0e1d1', 'naver_engine/report_notes.py': 'dadb0b4b1501a87176a4e85dc8c4b74745c39a48888c1c43dda7044048f04408', 'naver_engine/report_refresh.py': '826b8390d7a7b200d1e0449c2c8a1dcaa4e4310bf64bfeab7142998eb111999e', 'naver_engine/report_schedule.py': '24a76092fc6420093941fe78f2ce724029fed564c50b3bcce79a8687e0fc58fb', 'naver_engine/report_schedule_store.py': '7466cf13bab0b1899b42c2cd34c8e5b1fa0d1a83ee453fff0fa2e8b90489a406', 'naver_engine/report_views.py': '5d6218c1360fee101fb5ec21d036d6047daea11815fc4a1eda66b9e4023c6de2', 'naver_engine/reporting.py': '76a7a27ab39f69e9adf4a58547562e00776f6aaa0020df519cb2da8d032bd006', 'naver_engine/runtime_view.py': 'a8d78825c16aaa0a3fcc877fdb4a3cfaddc8330154f9331b75eee2cae6c90a4a', 'naver_engine/sales_views.py': '885598a9890df6913b54e0d4bf8f2041a18befe5ae319aa0963edb12b5e770f7', 'naver_engine/session.py': 'f710ae69062f2ef13c447767fe65ce17c0990aebe65fa6222c4e312129b8e432', 'naver_engine/setup_checks.py': '63f6bc01917b7f82d2f10f2466428f52e9034152ce2d4495708c9fd8988cabf5', 'naver_engine/setup_strategy_evidence.py': '3dde359a43b2a039e01b30b6e97e55e94fe34e59651b97d546c2804ab9c11ef7', 'naver_engine/shared_budget_evidence.py': '3c4fabb77204f103d6fbe7b98f5d8a7ce937fcf0543b4e266982ce71bb99634e', 'naver_engine/store.py': '9359770b96097bf5cfd70242b4902536c08572fc7bca2a76c4be159a4aac4477', 'naver_engine/strategy_validation.py': 'f223cecbb82484673055ca209a853c4b3537f01e8c4a694b71f6c6609f6915ef', 'naver_engine/structure_reads.py': 'fed780a4903a099b540cc4eb6b9419ee84cbfdbd26056ad1c338a5db23d71c22', 'naver_engine/sync.py': '7ddd57ccce8a8edcf13e3d4495d748d122b067e1bba32becfa6326a4dda32dad', 'naver_engine/view_sync.py': '57c97bb82d78dc25277cdd7f5ea23c1512be0cfd0279a837e1e64d0b317a4034', 'naver_engine/views.py': 'bfa0f4998153abe01ffeb7d646653db6b4d39b8f4409e09e23002424a60fafb9', 'naver_engine/web.py': '7535bf1e32f3ceee15d7663bff49bfe006f21ae1d761fb8fe6c473dfee123983', 'naver_runtime/__init__.py': '27d28d6ed467edc27f1b22a7a3fedd78253d562938c3cf060ea2573ef38038ec', 'naver_runtime/__main__.py': 'de4215ea9b64ca6a2643d1b6ea7abaa11ef63ae130bb2da1ea8e03bab62e3e3d', 'naver_runtime/backup_transport.py': 'b14520d0f46429ea93a3158b664ca7f5cb37e378ce146e684cd276265f92db71', 'naver_runtime/bootstrap.py': 'dd7f5949eee28e0391608670b3f00a40c30e6b461a3589bf47fcc7b49c5dd504', 'naver_runtime/claude_provider.py': 'c3fcbebc15561885004451ae181177176bbb8e2af57d363a435fdef25787aee6', 'naver_runtime/collection_requests.py': '1e7606023cdbd27826b0f0e4e07a3f0f6fa4955d6d00396a1af33e7f62526660', 'naver_runtime/config.py': 'ee3f1bdd0959ebc7a729de431518200d7eb58dce5f8580936b0ad5ec12bf7fa1', 'naver_runtime/erp_tunnel_transport.py': '59d1c40300c416b40d022ce6d1d91cdc9ac3d4a3b981c260ca3002e919bd3288', 'naver_runtime/learning_jobs.py': '20e93df06325e56b16f662a22298b45fa5206534c1a35a0342b82eb7e9ddb5cb', 'naver_runtime/learning_provider.py': '736d97270bf6a22a916fade9959710c761b09eaea5e8db8fd58bbb60f30849a2', 'naver_runtime/market_export.py': '6faef9473ebb38f609a58b7657f86e7c32a3d44d446e2e546392ac8eea3dafb0', 'naver_runtime/network_observability.py': 'da1c9f7778ab68142e64e1aaaa21d82514a0852df031deb015dc165f0d48ffbf', 'naver_runtime/observation_binding.py': '8c38a6dc00060526548762da75020e5dc2e3c2118aff35f6ffc8f64c997444e5', 'naver_runtime/product_export.py': 'e22619d2e1030b4e3d3cb6325e636198eeddc3041412dfe1ae937f5c487ee6fa', 'naver_runtime/provider_observability.py': '9344a464a642cfbea41c7e7a14011a466b1d9ebc495a27c36205bd94e45b21cd', 'naver_runtime/report_output_schema.py': '038ee1b9429302f08ccf72c17e195b701f9cf4840cbd389d01035413e900cf62', 'naver_runtime/report_schedule_jobs.py': '2771b0d7bcf37670da386e5e8d18414629aa8f0adafe165f731b9c2d0bc8d386', 'naver_runtime/restore_check.py': '0f7c392155b9fdcb602307b7bd5771c211ca9f6774f5dcfa8106f940bb7905b9', 'naver_runtime/runtime_status.py': 'f08633202d21248dde7c62c2d6bdb42a40b981721df958b0124fc7009b4da8eb', 'naver_runtime/scheduler.py': '58a5884a5ccd38d799dbfa423df5ccc561dec9382d7534bc882a36c722b18f15', 'naver_runtime/server.py': 'bf17856d256bf672aa4f50d8d9bf4b2557cec9a2aed7f1a0f5f97eee81ca8007', 'naver_runtime/writer.py': 'f4825faa816f2001a3902d9828bdf0dc1086467c4a56b89cf7ee4c5425ca5e26'}
READ_FAILURE_CODES = frozenset(('SOURCE_DIAGNOSTICS_READER_FAILED SOURCE_DIAGNOSTICS_READ_FAILED '
    'SOURCE_DIAGNOSTICS_DEADLINE SOURCE_DIAGNOSTICS_TIME SOURCE_DIAGNOSTICS_ROW_LIMIT '
    'SOURCE_DIAGNOSTICS_DATABASE_PATH SOURCE_DIAGNOSTICS_READER_MODE SOURCE_DIAGNOSTICS_TARGETS '
    'SOURCE_DIAGNOSTICS_TARGET_NOT_FOUND SOURCE_DIAGNOSTICS_TARGET_AMBIGUOUS '
    'SOURCE_DIAGNOSTICS_SCHEMA SOURCE_DIAGNOSTICS_ACCOUNT_LIMIT SOURCE_DIAGNOSTICS_DUPLICATE '
    'SOURCE_DIAGNOSTICS_IDENTITY SOURCE_DIAGNOSTICS_NETWORK_FORBIDDEN SOURCE_DIAGNOSTICS_CODE_PIN '
    'SOURCE_DIAGNOSTICS_MUTATION SOURCE_DIAGNOSTICS_OUTPUT_LIMIT SOURCE_DIAGNOSTICS_OUTPUT_FIELDS '
    'SOURCE_DIAGNOSTICS_OUTPUT_SCHEMA SOURCE_DIAGNOSTICS_OUTPUT_TARGETS SOURCE_DIAGNOSTICS_OUTPUT_ENUM '
    'SOURCE_DIAGNOSTICS_OUTPUT_NUMBER SOURCE_DIAGNOSTICS_OUTPUT_COUNTS SOURCE_DIAGNOSTICS_OUTPUT_LIMITS SOURCE_DIAGNOSTICS_PROJECTION_MISMATCH').split())

PROJECTION_SOURCE = '\nKST = timezone(timedelta(hours=9))\nMAX_ACCOUNTS, MAX_JOBS = 4000, 20000\nSTAGES = frozenset((\'진행중\', \'전략관리\', \'사후관리\', \'재계약진행중\', \'홀딩중\', \'환불중\', \'계약만료\'))\nCADENCES = frozenset((\'daily\', \'weekly\', \'blocked\'))\nREASONS = frozenset((\'AUTHORITY_INVALID\', \'SOURCE_STALE\', \'UNMATCHED_ACCOUNT\', \'UNKNOWN_STAGE\', \'MANAGED_STAGE\', \'NONMANAGED_STAGE\'))\nSTATUSES = frozenset((\'reading\', \'partial\', \'ok\', \'retry\', \'limited\', \'reauth_required\', \'source_wait\', \'superseded\'))\nERRORS = frozenset((\'KEY_REJECTED RATE SERVER BAD_REQUEST NOT_FOUND NETWORK BAD_RESPONSE MISMATCH OTHER \'\n    \'CHECKPOINT_PENDING CHECKPOINT_INVALID SETTINGS_CHANGED REQUEST_BUDGET REQUEST_DEADLINE REQUEST_CALL_CAP \'\n    \'STATS_INCOMPLETE STATS_SHAPE STATS_SHAPE_UNKNOWN STATS_NUMERIC_INVALID STATS_ROW_ID_INVALID STATS_DATE_INVALID \'\n    \'STATS_PERIOD_OPEN STATS_METRIC_MISSING STATS_METRIC_INVALID STATS_DATE_INCOMPLETE STATS_CYCLE_INVALID \'\n    \'STATS_CYCLE_FUTURE STATS_CAMPAIGNS_INVALID UNEXPECTED RETRY_EXHAUSTED SOURCE_AGGREGATING CAMPAIGNS_CHANGED \'\n    \'RECHECK_COVERED\').split())\nJOB_COLUMNS = (\'job_key,customer_id,possibility_id,kind,cycle_day,period_start,period_end,snapshot_at,catalog_at,\'\n    "stage_revision,matching_fingerprint,generation,requested_at,actor,status,checked_at,next_try_at,attempts,error_code,"\n    "CASE WHEN progress_json IS NULL THEN NULL ELSE \'\' END AS progress_json,progress_hash")\nMAX_PROGRESS_BYTES, MAX_PROGRESS_TOTAL = 8*1024*1024, 32*1024*1024\n\nREAD_PHASE = \'source-pin\'\nREAD_STAGES = frozenset((\'source-pin\',\'import\',\'open\',\'bounds\',\'policy\',\'source-snapshot\',\'scope\',\n    \'source-validation\',\'setup\',\'proof\',\'output\',\'cleanup\',\'reader-command\'))\nREAD_KINDS = frozenset((\'sqlite-busy\',\'sqlite-interrupted\',\'sqlite-error\',\'shape-invalid\',\'internal\',\'closed-refusal\'))\n\ndef set_read_stage(stage):\n    global READ_PHASE\n    if stage not in READ_STAGES:raise ValueError(\'SOURCE_DIAGNOSTICS_OUTPUT_FIELDS\')\n    READ_PHASE=stage\n\ndef validate_failure_detail(value):\n    if type(value) is not dict or set(value)!={\'stage\',\'kind\'} or type(value[\'stage\']) is not str or value[\'stage\'] not in READ_STAGES or type(value[\'kind\']) is not str or value[\'kind\'] not in READ_KINDS:\n        raise ValueError(\'SOURCE_DIAGNOSTICS_OUTPUT_FIELDS\')\n    return value\n\ndef classify_failure(error,stage=None):\n    stage=READ_PHASE if stage is None else stage\n    code=getattr(error,\'sqlite_errorcode\',None)\n    if isinstance(error,sqlite3.Error):\n        code=code & 255 if type(code) is int else None\n        kind=\'sqlite-busy\' if code in (sqlite3.SQLITE_BUSY,sqlite3.SQLITE_LOCKED) else \'sqlite-interrupted\' if code==sqlite3.SQLITE_INTERRUPT else \'sqlite-error\'\n    elif type(error) is ValueError and len(error.args)==1 and type(error.args[0]) is str and error.args[0] in READ_FAILURE_CODES:\n        kind=\'closed-refusal\'\n    elif isinstance(error,(KeyError,TypeError,AttributeError,ValueError,OverflowError,RecursionError,UnicodeError)):\n        kind=\'shape-invalid\'\n    else:kind=\'internal\'\n    return validate_failure_detail({\'stage\':stage,\'kind\':kind})\n\ndef closed_reader_failure(error):\n    code=error.args[0] if isinstance(error,ValueError) and len(error.args)==1 and type(error.args[0]) is str and error.args[0] in READ_FAILURE_CODES else \'SOURCE_DIAGNOSTICS_READ_FAILED\'\n    return {\'failure\':code,\'failure_detail\':classify_failure(error)}\n\ndef check_deadline(deadline):\n    if time.monotonic() >= deadline:\n        raise ValueError(\'SOURCE_DIAGNOSTICS_DEADLINE\')\n\ndef stamp(value):\n    if value is None:\n        return None\n    if not isinstance(value, str) or len(value) > 48:\n        raise ValueError(\'SOURCE_DIAGNOSTICS_TIME\')\n    try:\n        parsed = datetime.fromisoformat(value)\n        if parsed.tzinfo is None or parsed.utcoffset() is None:\n            raise ValueError()\n        return parsed.astimezone(KST).isoformat()\n    except (TypeError, ValueError):\n        raise ValueError(\'SOURCE_DIAGNOSTICS_TIME\') from None\n\ndef closed(value, allowed):\n    return value if type(value) is str and value in allowed else \'UNRECOGNIZED\'\n\ndef rows(connection, query, parameters, limit, deadline):\n    check_deadline(deadline)\n    cursor = connection.execute(query, parameters)\n    names = [column[0] for column in cursor.description]\n    values = cursor.fetchmany(limit+1)\n    cursor.close()\n    if len(values) > limit:\n        raise ValueError(\'SOURCE_DIAGNOSTICS_ROW_LIMIT\')\n    check_deadline(deadline)\n    return [dict(zip(names, row)) for row in values]\n\ndef readonly_authorizer(action, arg1, arg2, database, source):\n    if action in (sqlite3.SQLITE_SELECT, sqlite3.SQLITE_READ, sqlite3.SQLITE_TRANSACTION,\n                  sqlite3.SQLITE_SAVEPOINT, sqlite3.SQLITE_RECURSIVE):\n        return sqlite3.SQLITE_OK\n    if action == sqlite3.SQLITE_FUNCTION:\n        return sqlite3.SQLITE_DENY if (arg2 or \'\').lower() in (\n            \'load_extension\', \'readfile\', \'writefile\', \'shell\', \'eval\', \'fts3_tokenizer\') else sqlite3.SQLITE_OK\n    if action == sqlite3.SQLITE_PRAGMA and arg2 is None and (arg1 or \'\').lower() in (\'query_only\', \'database_list\'):\n        return sqlite3.SQLITE_OK\n    if action == sqlite3.SQLITE_PRAGMA and (arg1 or \'\').lower() == \'table_info\' and arg2 == \'naver_auto_link_memory\':\n        return sqlite3.SQLITE_OK\n    return sqlite3.SQLITE_DENY\n\ndef connect_reader(path):\n    if path.is_symlink() or path.resolve() != path or not path.is_file():\n        raise ValueError(\'SOURCE_DIAGNOSTICS_DATABASE_PATH\')\n    connection = sqlite3.connect(path.as_uri()+\'?mode=ro\', uri=True, isolation_level=None, timeout=1)\n    try:\n        connection.execute(\'PRAGMA query_only=ON\')\n        connection.execute(\'PRAGMA busy_timeout=1000\')\n        connection.execute(\'PRAGMA trusted_schema=OFF\')\n        connection.set_authorizer(readonly_authorizer)\n        if connection.execute(\'PRAGMA query_only\').fetchone() != (1,):\n            raise ValueError(\'SOURCE_DIAGNOSTICS_READER_MODE\')\n        if connection.execute(\'PRAGMA database_list\').fetchall() != [(0, \'main\', str(path))]:\n            raise ValueError(\'SOURCE_DIAGNOSTICS_DATABASE_PATH\')\n        return connection\n    except Exception:\n        connection.close()\n        raise\n\n\nBRANCHES = frozenset((\'NO_OBSERVATION\',\'POLICY_INACTIVE\',\'MANUAL_PENDING\',\'NO_CURRENT_SCOPE_ROW\',\n    \'CYCLE_NOT_CURRENT\',\'CURRENT_ROW_INVALID\',\'FUTURE_CHECKED_AT\',\'CURRENT_PARTIAL\',\'CHECKPOINT_INVALID\',\'CURRENT_COMPLETE\'))\nOBS_ERRORS = ERRORS | {\'SOURCE_STALE\',\'MANUAL_PENDING\',\'CHECKPOINT_INVALID\'}\nMAX_HISTORY_ROWS = 200\n\ndef optional_match(left,right):\n    return left is not None and right is not None and left==right\n\ndef bounded_bodies(connection,cid,pid,revision,row,deadline,total):\n    # Inspect sizes in SQLite before SELECT * / setup_observation can read bodies.\n    if row is not None:\n        values=rows(connection,\'SELECT length(CAST(progress_json AS BLOB)) AS size FROM naver_auto_inspection_job WHERE job_key=?\',\n            (row[\'job_key\'],),1,deadline)\n        size=values[0][\'size\'] if values else None\n        if size is not None:\n            if type(size) is not int or not 0<=size<=MAX_PROGRESS_BYTES:\n                raise ValueError(\'SOURCE_DIAGNOSTICS_ROW_LIMIT\')\n            total[0]+=size\n    history=rows(connection,\'SELECT length(CAST(body_json AS BLOB)) AS size FROM naver_auto_setting_observation \'\n        \'WHERE customer_id=? AND possibility_id IS ? AND stage_revision=? ORDER BY history_id DESC LIMIT 200\',\n        (cid,pid,revision),MAX_HISTORY_ROWS,deadline)\n    for item in history:\n        size=item[\'size\']\n        if type(size) is not int or not 0<=size<=MAX_PROGRESS_BYTES:\n            raise ValueError(\'SOURCE_DIAGNOSTICS_ROW_LIMIT\')\n        total[0]+=size\n    if total[0]>MAX_PROGRESS_TOTAL:\n        raise ValueError(\'SOURCE_DIAGNOSTICS_ROW_LIMIT\')\n    return len(history)\n\ndef actual_projection(observation):\n    if observation is None:\n        return {\'present\':False,\'status\':None,\'error_code\':None,\'stale\':None,\'complete\':False,\n            \'generation_present\':False,\'checked_at_present\':False}\n    return {\'present\':True,\'status\':closed(observation[\'status\'],STATUSES|{\'pending\'}),\n        \'error_code\':None if observation[\'error_code\'] is None else closed(observation[\'error_code\'],OBS_ERRORS),\n        \'stale\':observation[\'stale\'],\'complete\':observation[\'complete\'],\n        \'generation_present\':observation[\'generation\'] is not None,\'checked_at_present\':observation[\'checked_at\'] is not None}\n\ndef expected_projection(branch,row=None):\n    out={\'present\':True,\'status\':\'pending\',\'error_code\':None,\'stale\':True,\'complete\':False,\n        \'generation_present\':False,\'checked_at_present\':False}\n    if branch==\'NO_OBSERVATION\':return dict(out,present=False,status=None,stale=None)\n    if branch in (\'POLICY_INACTIVE\',\'CURRENT_ROW_INVALID\'):out[\'error_code\']=\'SOURCE_STALE\'\n    elif branch==\'MANUAL_PENDING\':out.update(error_code=\'MANUAL_PENDING\',stale=False,generation_present=True)\n    elif branch in (\'FUTURE_CHECKED_AT\',\'CURRENT_PARTIAL\',\'CHECKPOINT_INVALID\',\'CURRENT_COMPLETE\'):\n        out.update(status=closed(row[\'status\'],STATUSES),error_code=None if row[\'error_code\'] is None else closed(row[\'error_code\'],OBS_ERRORS),\n            stale=False,generation_present=True,checked_at_present=True)\n        if branch==\'FUTURE_CHECKED_AT\':out.update(status=\'pending\',error_code=\'CHECKPOINT_INVALID\',stale=True,checked_at_present=False)\n        elif branch==\'CHECKPOINT_INVALID\':out.update(status=\'limited\',error_code=\'CHECKPOINT_INVALID\')\n        elif branch==\'CURRENT_COMPLETE\':out[\'complete\']=True\n    return out\n\ndef context_binding_matches(proof,row,IC,IS):\n    try:\n        return bool(proof and \'binding\' in proof and IC._dump(proof[\'binding\'])==IC._dump(IC._binding(row,IS._ERROR_CODES)))\n    except (KeyError,TypeError,ValueError,OverflowError,RecursionError):\n        return False\n\ndef target_projection(store,now,deadline,modules,cid,pid,policy,states,catalog,catalog_state,snapshot,fingerprint,org_current,total):\n    S,MS,P,IS,IC= (modules[key] for key in (\'S\',\'MS\',\'P\',\'IS\',\'IC\'))\n    c=store._conn\n    set_read_stage(\'scope\')\n    exists=c.execute(\'SELECT 1 FROM naver_auto_inspection_job WHERE customer_id=? LIMIT 1\',(cid,)).fetchone() is not None\n    requests=rows(c,\'SELECT * FROM naver_auto_manual_read WHERE customer_id=?\',(cid,),1,deadline)\n    request=requests[0] if requests else None\n    active=policy is not None and policy[\'decision\'].cadence!=\'blocked\'\n    current_pid,revision=(policy[\'possibility_id\'],policy[\'stage_revision\']) if policy else (None,None)\n    manual=None\n    if active and request and catalog and snapshot is not None:\n        manual=store._inspection_manual_job(request,policy,snapshot,catalog[\'generated_at\'],fingerprint,now)\n    cadence=policy[\'decision\'].cadence if policy else None\n    cycle=str(P.period_for(cadence,now).cycle_day) if active else None\n    selected=rows(c,\'SELECT \'+JOB_COLUMNS+\' FROM naver_auto_inspection_job WHERE customer_id=? \'\n        \'AND possibility_id IS ? AND stage_revision=? AND ((kind=? AND cycle_day=?) OR (kind=\\\'manual\\\' AND generation=?)) \'\n        \'ORDER BY generation DESC,checked_at DESC,rowid DESC LIMIT 1\',\n        (cid,current_pid,revision,cadence,cycle,manual[\'generation\'] if manual else None),1,deadline) if active else []\n    row=selected[0] if selected else None\n    set_read_stage(\'bounds\')\n    history_count=bounded_bodies(c,cid,current_pid,revision,row,deadline,total) if active and (exists or manual) else 0\n    if row is not None:\n        row=rows(c,\'SELECT * FROM naver_auto_inspection_job WHERE job_key=?\',(row[\'job_key\'],),1,deadline)[0]\n    set_read_stage(\'source-validation\')\n    job=IS._job(row) if row else None\n    current_cycle=bool(row and (row[\'cycle_day\']==cycle if row[\'kind\']!=\'manual\' else\n        row[\'cycle_day\']==str(now.date()) and manual is not None and row[\'generation\']==manual[\'generation\']))\n    core_valid=bool(job and store._inspection_account_valid(job,now))\n    full_valid=bool(job and store.inspection_account_valid(job,now))\n    catalog_proof=store._inspection_catalog_proof(now)\n    proof=store._inspection_read_proof(c,IC.checkpoint_key(row[\'job_key\']),4096) if row else None\n    context=store._inspection_context(c,row,now,catalog_proof) if row else None\n    state=states.get(cid)\n    scope_matches=bool(row and state and IC._scope_matches(row,job,state[\'possibility_id\']))\n    row_binding=bool(row and state and IS._binding(row,job,state[\'possibility_id\']))\n    request_today=bool(request and datetime.fromisoformat(request[\'requested_at\']).astimezone(KST).date()==now.date())\n    newer_manual=bool(job and job[\'kind\']!=\'manual\' and manual and manual[\'generation\']>job[\'generation\'])\n    set_read_stage(\'setup\')\n    observation=store.setup_observation(cid,now)\n    actual=actual_projection(observation)\n    if not exists and not request or not exists and manual is None:branch=\'NO_OBSERVATION\'\n    elif not active:branch=\'POLICY_INACTIVE\'\n    elif manual is not None and (row is None or row[\'generation\']<manual[\'generation\']):branch=\'MANUAL_PENDING\'\n    elif row is None:branch=\'NO_CURRENT_SCOPE_ROW\'\n    elif not current_cycle:branch=\'CYCLE_NOT_CURRENT\'\n    elif not full_valid:branch=\'CURRENT_ROW_INVALID\'\n    elif datetime.fromisoformat(row[\'checked_at\'])>now:branch=\'FUTURE_CHECKED_AT\'\n    elif row[\'status\']!=\'ok\':branch=\'CURRENT_PARTIAL\'\n    elif not actual[\'complete\']:branch=\'CHECKPOINT_INVALID\'\n    else:branch=\'CURRENT_COMPLETE\'\n    expected=expected_projection(branch,row)\n    if actual!=expected:raise ValueError(\'SOURCE_DIAGNOSTICS_PROJECTION_MISMATCH\')\n    set_read_stage(\'proof\')\n    checks=None if row is None else {\n        \'account_snapshot_matches\':snapshot is not None and row[\'snapshot_at\']==S._kst_text(snapshot,\'계정 원천\'),\n        \'catalog_accepted\':catalog_state==\'accepted\',\n        \'catalog_stamp_matches\':catalog is not None and row[\'catalog_at\']==catalog[\'generated_at\'],\n        \'organization_current\':org_current,\n        \'matching_fingerprint_matches\':row[\'matching_fingerprint\']==fingerprint,\n        \'account_present\':c.execute(\'SELECT present FROM naver_auto_account WHERE customer_id=?\',(cid,)).fetchone()==(1,),\n        \'management_revision_matches\':state is not None and row[\'stage_revision\']==state[\'stage_revision\'],\n        \'management_pair_matches\':state is not None and row[\'possibility_id\']==state[\'possibility_id\'],\n        \'row_binding_matches\':row_binding,\'row_scope_matches\':scope_matches,\n        \'current_cycle_matches\':current_cycle,\'core_account_valid\':core_valid,\'full_account_valid\':full_valid,\n        \'catalog_proof_current\':catalog_proof is not None,\'context_proof_present\':proof is not None,\n        \'context_proof_sealed\':bool(proof and IC._sealed(proof,IC._CHECKPOINT_FIELDS)),\n        \'context_binding_matches\':context_binding_matches(proof,row,IC,IS),\n        \'context_catalog_content_matches\':bool(type(proof) is dict and type(catalog_proof) is dict and all(proof.get(k)==catalog_proof[k] for k in (\'content_digest\',\'content_epoch\',\'stable_content_at\'))),\n        \'context_current\':context is not None,\'newer_valid_manual_generation\':newer_manual,\n        \'manual_generation_matches\':bool(manual and row[\'kind\']==\'manual\' and row[\'generation\']==manual[\'generation\'])}\n    reasons=[]\n    if checks is not None:\n        for key in (\'account_present\',\'account_snapshot_matches\',\'catalog_accepted\',\'catalog_stamp_matches\',\'organization_current\',\n            \'matching_fingerprint_matches\',\'management_revision_matches\',\'management_pair_matches\',\'row_binding_matches\',\n            \'row_scope_matches\',\'current_cycle_matches\',\'catalog_proof_current\',\'context_proof_present\',\n            \'context_proof_sealed\',\'context_binding_matches\',\'context_catalog_content_matches\',\'context_current\'):\n            if checks[key] is False:reasons.append(key.upper())\n        if newer_manual:reasons.append(\'NEWER_VALID_MANUAL_GENERATION\')\n        if not core_valid:reasons.append(\'CORE_ACCOUNT_INVALID\')\n        if not full_valid:reasons.append(\'FULL_ACCOUNT_INVALID\')\n    return {\'policy\':{\'present\':policy is not None,\'active\':active,\'cadence\':closed(cadence,CADENCES) if policy else None,\n        \'reason\':closed(policy[\'decision\'].reason,REASONS) if policy else None,\n        \'expected_pair_matches\':bool(policy and policy[\'possibility_id\']==pid and policy[\'matched\'] is True),\n        \'source_current\':bool(policy and policy[\'source_current\'])},\n        \'scope\':{\'any_job_present\':exists,\'current_row_present\':row is not None,\n            \'kind\':closed(row[\'kind\'],frozenset((\'daily\',\'weekly\',\'manual\'))) if row else None,\n            \'status\':closed(row[\'status\'],STATUSES) if row else None,\'history_rows_checked\':history_count},\n        \'manual\':{\'present\':request is not None,\'requested_today\':request_today,\n            \'expected_pair_matches\':bool(request and request[\'possibility_id\']==pid),\'current_valid_request\':manual is not None,\n            \'kind\':closed(request[\'request_kind\'] or \'manual\',frozenset((\'manual\',\'manual_period\'))) if request else None},\n        \'binding_checks\':checks,\'failed_checks\':reasons,\'observation\':dict(actual,branch=branch,projection_matches_actual=True)}\n\ndef collect(store,now,deadline,modules,targets=TARGETS):\n    if targets!=TARGETS:raise ValueError(\'SOURCE_DIAGNOSTICS_TARGETS\')\n    now=now.astimezone(KST);c=store._conn\n    set_read_stage(\'bounds\')\n    if c.execute("SELECT CASE WHEN length(CAST(value AS BLOB))<=2 THEN value END FROM naver_auto_meta WHERE key=\'schema_version\'").fetchone()!=(\'21\',):\n        raise ValueError(\'SOURCE_DIAGNOSTICS_SCHEMA\')\n    if c.execute(\'SELECT COUNT(*) FROM naver_auto_inspection_job\').fetchone()[0]>MAX_JOBS:\n        raise ValueError(\'SOURCE_DIAGNOSTICS_ROW_LIMIT\')\n    accounts=rows(c,\'SELECT customer_id,ad_account_no,present FROM naver_auto_account\',(),MAX_ACCOUNTS,deadline)\n    # Bound all metadata before pinned Store parsers can read catalog/org bodies.\n    sizes=rows(c,\'SELECT length(CAST(value AS BLOB)) AS size FROM naver_auto_meta\',(),20000,deadline)\n    if any(type(x[\'size\']) is not int or x[\'size\']>16*1024*1024 for x in sizes) or sum(x[\'size\'] for x in sizes)>64*1024*1024:\n        raise ValueError(\'SOURCE_DIAGNOSTICS_ROW_LIMIT\')\n    resolved=[]\n    for label,pid,adno in targets:\n        found=[a for a in accounts if a[\'present\']==1 and type(a[\'ad_account_no\']) is int and a[\'ad_account_no\']==adno]\n        if not found:raise ValueError(\'SOURCE_DIAGNOSTICS_TARGET_NOT_FOUND\')\n        if len(found)!=1:raise ValueError(\'SOURCE_DIAGNOSTICS_TARGET_AMBIGUOUS\')\n        cid=found[0][\'customer_id\']\n        if type(cid) is not int or not 0<cid<10**15:raise ValueError(\'SOURCE_DIAGNOSTICS_IDENTITY\')\n        resolved.append((label,pid,cid))\n    S,MS,I,O,Y=(modules[k] for k in (\'S\',\'MS\',\'I\',\'O\',\'Y\'))\n    set_read_stage(\'policy\')\n    states=store.management_states();policies=MS.snapshot(store,now,stage_states=states)\n    set_read_stage(\'source-snapshot\')\n    catalog,state=I.catalog_status(store,now);snapshot=store.inventory_snapshot(now)\n    fingerprint=store.decision_fingerprint();org_current=O.allows_raising(Y.org_freshness(store,now))\n    total=[0];result={}\n    for label,pid,cid in resolved:\n        check_deadline(deadline)\n        result[label]=target_projection(store,now,deadline,modules,cid,pid,policies.get(cid),states,\n            catalog,state,snapshot,fingerprint,org_current,total)\n    return {\'schema_version\':21,\'projection_model\':\'dc168-setup-stale-v1\',\'target_identifier_namespace\':TARGET_NAMESPACE,\n        \'targets\':result,\'limits\':{\'stored_snapshot_only\':True,\'source_guards_unchanged\':True,\'management_not_synchronized\':True,\n            \'collection_completion_not_proven\':True,\'scheduler_budget_unobserved\':True,\'ads_unchanged\':True},\'mutations\':0}\n\n_PREFLIGHT_REPORT_ID = 14055\n_PREFLIGHT_REPORT_REVISION = 6\n_PREFLIGHT_STRATEGY_VERSION = 0\n_PREFLIGHT_ACTOR = 0\n_PREFLIGHT_NARROWED = False\n_PREFLIGHT_TARGET = (\'foodin\', 51952, 1030001)\n_PREFLIGHT_CHECKPOINTS = frozenset((\'none\', \'identity\', \'report_scope\', \'authority\', \'edition\',\n    \'plan\', \'learning\', \'product_market\', \'funnel\', \'setup\', \'prepare_finalize\', \'writer_required\'))\n_PREFLIGHT_KINDS = frozenset((\'none\', \'store_refused\', \'authority_refused\', \'shape_invalid\', \'writer_required\'))\n_PREFLIGHT_FLAGS = (\'authority_passed\', \'report_latest\', \'report_revision_matches\', \'report_dirty\',\n    \'strategy_version_matches\', \'active_job_exists\', \'funnel_current\',\n    \'setup_model_source_passed\', \'prepare_passed\')\n\n\ndef collect_submit_preflight(store, now, deadline, modules):\n    """Call the real fixed report preparation once; never submit or reserve."""\n    from naver_engine import report_views as RV\n    from app.naver_auto import scope as SC\n    c = store._conn\n    check_deadline(deadline)\n    if c.execute("SELECT value FROM naver_auto_meta WHERE key=\'schema_version\'").fetchone() != (\'21\',):\n        raise ValueError(\'SOURCE_DIAGNOSTICS_SCHEMA\')\n    sizes = rows(c, \'SELECT length(CAST(value AS BLOB)) AS size FROM naver_auto_meta\', (), 20000, deadline)\n    if any(type(x[\'size\']) is not int or x[\'size\'] > 16*1024*1024 for x in sizes) or sum(x[\'size\'] for x in sizes) > 64*1024*1024:\n        raise ValueError(\'SOURCE_DIAGNOSTICS_ROW_LIMIT\')\n    accounts = rows(c, \'SELECT customer_id,ad_account_no,present FROM naver_auto_account\', (), MAX_ACCOUNTS, deadline)\n    label, pid, adno = _PREFLIGHT_TARGET\n    found = [row for row in accounts if row[\'present\'] == 1 and type(row[\'ad_account_no\']) is int and row[\'ad_account_no\'] == adno]\n    if not found:\n        raise ValueError(\'SOURCE_DIAGNOSTICS_TARGET_NOT_FOUND\')\n    if len(found) != 1:\n        raise ValueError(\'SOURCE_DIAGNOSTICS_TARGET_AMBIGUOUS\')\n    cid = found[0][\'customer_id\']\n    if type(cid) is not int or not 0 < cid < 10**15:\n        raise ValueError(\'SOURCE_DIAGNOSTICS_IDENTITY\')\n    key = RV.account_key(cid)\n    snapshot = c.execute(\'SELECT possibility_id,period_key,revision_fingerprint,length(CAST(payload_json AS BLOB)) \'\n                         \'FROM naver_auto_report_snapshot WHERE report_id=?\', (_PREFLIGHT_REPORT_ID,)).fetchone()\n    result = dict(schema_version=21, projection_model=\'foodin-submit-preflight-v1\',\n                  target_identifier_namespace=\'ad_account_no\', scope=\'current_preparation_only\',\n                  past_POST_cause_not_proven=True, checks={name: None for name in _PREFLIGHT_FLAGS},\n                  strategy_version=None, failure_checkpoint=\'identity\', failure_kind=\'shape_invalid\',\n                  limits=dict(stored_snapshot_only=True, source_guards_unchanged=True,\n                              reservation_not_called=True, provider_not_called=True,\n                              job_creation_not_called=True, ads_unchanged=True), mutations=0)\n    if snapshot is None or snapshot[0] != pid or type(snapshot[2]) is not str:\n        return result\n    if type(snapshot[3]) is not int or not 0 < snapshot[3] <= 8*1024*1024:\n        raise ValueError(\'SOURCE_DIAGNOSTICS_ROW_LIMIT\')\n    fingerprint, period_key = snapshot[2], snapshot[1]\n    trace = {\'stage\': \'report_scope\', \'writer_required\': False}\n    saved = {}\n    missing = object()\n\n    def hook(name, stage, after=None):\n        original = getattr(store, name)\n        saved[name] = store.__dict__.get(name, missing)\n\n        def observed(*args, **kwargs):\n            if name == \'_approval_head\' and (len(args) < 3 or args[1] != \'report-strategy\' or args[2] != str(_PREFLIGHT_REPORT_ID)+\':\'+key):\n                return original(*args, **kwargs)\n            trace[\'stage\'] = stage\n            value = original(*args, **kwargs)\n            if after is not None:\n                after(value)\n            return value\n        setattr(store, name, observed)\n\n    def authorized(value):\n        result[\'checks\'][\'authority_passed\'] = True\n        trace[\'stage\'] = \'edition\'\n\n    def head(value):\n        result[\'strategy_version\'] = value[\'version\']\n        result[\'checks\'][\'strategy_version_matches\'] = value[\'version\'] == _PREFLIGHT_STRATEGY_VERSION\n\n    def plan(value):\n        trace[\'stage\'] = \'learning\'\n\n    def evidence(value):\n        trace[\'stage\'] = \'funnel\'\n\n    def funnel(value):\n        result[\'checks\'][\'funnel_current\'] = value[\'current\']\n\n    def setup(value):\n        result[\'checks\'][\'setup_model_source_passed\'] = True\n        trace[\'stage\'] = \'prepare_finalize\'\n\n    # Hooks only observe the same instance\'s real calls and return each exact\n    # value unchanged. Restore every instance attribute, including overrides.\n    hook(\'_report_notes_scope\', \'report_scope\')\n    hook(\'_learning_actor\', \'authority\', authorized)\n    hook(\'_approval_head\', \'edition\', head)\n    hook(\'automation_plan\', \'plan\', plan)\n    hook(\'_strategy_evidence\', \'product_market\', evidence)\n    hook(\'funnel_strategy_source\', \'funnel\', funnel)\n    hook(\'_setup_strategy_source\', \'setup\', setup)\n    original_need_writer = store._need_writer\n    saved[\'_need_writer\'] = store.__dict__.get(\'_need_writer\', missing)\n\n    def need_writer():\n        trace.update(stage=\'writer_required\', writer_required=True)\n        return original_need_writer()\n    store._need_writer = need_writer\n    try:\n        try:\n            prepared = store.prepare_learning_strategy(_PREFLIGHT_REPORT_ID, key, fingerprint,\n                _PREFLIGHT_ACTOR, now, _PREFLIGHT_STRATEGY_VERSION, narrowed=_PREFLIGHT_NARROWED)\n            result[\'checks\'][\'prepare_passed\'] = True\n            result.update(failure_checkpoint=\'none\', failure_kind=\'none\')\n            del prepared\n        except SC.ScopeError:\n            result[\'checks\'][\'prepare_passed\'] = False\n            result[\'checks\'][\'authority_passed\'] = False\n            result.update(failure_checkpoint=trace[\'stage\'], failure_kind=\'authority_refused\')\n        except modules[\'S\'].StoreRefused:\n            result[\'checks\'][\'prepare_passed\'] = False\n            if trace[\'stage\'] == \'authority\':\n                result[\'checks\'][\'authority_passed\'] = False\n            if trace[\'stage\'] == \'setup\':\n                result[\'checks\'][\'setup_model_source_passed\'] = False\n            result.update(failure_checkpoint=trace[\'stage\'],\n                          failure_kind=\'writer_required\' if trace[\'writer_required\'] else \'store_refused\')\n        except (KeyError, TypeError, ValueError, OverflowError, RecursionError):\n            result[\'checks\'][\'prepare_passed\'] = False\n            result.update(failure_checkpoint=trace[\'stage\'], failure_kind=\'shape_invalid\')\n    finally:\n        for name, value in saved.items():\n            if value is missing:\n                delattr(store, name)\n            else:\n                setattr(store, name, value)\n    if result[\'checks\'][\'authority_passed\'] is True:\n        latest = c.execute(\'SELECT MAX(report_id) FROM naver_auto_report_snapshot WHERE possibility_id=? AND period_key=?\',\n                           (pid, period_key)).fetchone()[0]\n        revision = store.report_snapshot_detail(_PREFLIGHT_REPORT_ID)[\'revision_no\']\n        dirty = c.execute(\'SELECT pending FROM naver_auto_report_dirty WHERE possibility_id=? AND period_key=?\',\n                          (pid, period_key)).fetchone()\n        result[\'checks\'].update(report_latest=latest == _PREFLIGHT_REPORT_ID,\n            report_revision_matches=revision == _PREFLIGHT_REPORT_REVISION,\n            report_dirty=bool(dirty and dirty[0]),\n            active_job_exists=any(job[\'state\'] in {\'queued\', \'running\'} for job in store.learning_strategy_jobs()))\n    check_deadline(deadline)\n    return result\n\n\ndef validate_submit_preflight_result(value):\n    keys = {\'schema_version\', \'projection_model\', \'target_identifier_namespace\', \'scope\',\n            \'past_POST_cause_not_proven\', \'checks\', \'strategy_version\', \'failure_checkpoint\',\n            \'failure_kind\', \'limits\', \'mutations\'}\n    if type(value) is not dict or set(value) != keys:\n        raise ValueError(\'SOURCE_DIAGNOSTICS_OUTPUT_FIELDS\')\n    if (type(value[\'schema_version\']) is not int or value[\'schema_version\'] != 21\n            or value[\'projection_model\'] != \'foodin-submit-preflight-v1\'\n            or value[\'target_identifier_namespace\'] != \'ad_account_no\'\n            or value[\'scope\'] != \'current_preparation_only\'\n            or value[\'past_POST_cause_not_proven\'] is not True\n            or type(value[\'mutations\']) is not int or value[\'mutations\'] != 0):\n        raise ValueError(\'SOURCE_DIAGNOSTICS_OUTPUT_SCHEMA\')\n    checks = value[\'checks\']\n    if type(checks) is not dict or set(checks) != set(_PREFLIGHT_FLAGS) or any(v is not None and type(v) is not bool for v in checks.values()):\n        raise ValueError(\'SOURCE_DIAGNOSTICS_OUTPUT_FIELDS\')\n    version = value[\'strategy_version\']\n    if version is not None and (type(version) is not int or not 0 <= version <= 2**53-1):\n        raise ValueError(\'SOURCE_DIAGNOSTICS_OUTPUT_NUMBER\')\n    if (type(value[\'failure_checkpoint\']) is not str or value[\'failure_checkpoint\'] not in _PREFLIGHT_CHECKPOINTS\n            or type(value[\'failure_kind\']) is not str or value[\'failure_kind\'] not in _PREFLIGHT_KINDS):\n        raise ValueError(\'SOURCE_DIAGNOSTICS_OUTPUT_ENUM\')\n    if (checks[\'prepare_passed\'] is True) != (value[\'failure_checkpoint\'] == \'none\' and value[\'failure_kind\'] == \'none\'):\n        raise ValueError(\'SOURCE_DIAGNOSTICS_OUTPUT_COUNTS\')\n    if checks[\'prepare_passed\'] is True and any(checks[k] is not True for k in (\'authority_passed\', \'strategy_version_matches\', \'funnel_current\', \'setup_model_source_passed\')):\n        raise ValueError(\'SOURCE_DIAGNOSTICS_OUTPUT_COUNTS\')\n    if checks[\'prepare_passed\'] is True and (checks[\'report_latest\'] is not True or checks[\'report_dirty\'] is not False):\n        raise ValueError(\'SOURCE_DIAGNOSTICS_OUTPUT_COUNTS\')\n    if checks[\'authority_passed\'] is not True and (version is not None or any(checks[k] is not None for k in (\'report_latest\', \'report_revision_matches\', \'report_dirty\', \'strategy_version_matches\', \'active_job_exists\', \'funnel_current\', \'setup_model_source_passed\'))):\n        raise ValueError(\'SOURCE_DIAGNOSTICS_OUTPUT_COUNTS\')\n    expected_limits = {\'stored_snapshot_only\', \'source_guards_unchanged\', \'reservation_not_called\',\n                       \'provider_not_called\', \'job_creation_not_called\', \'ads_unchanged\'}\n    if type(value[\'limits\']) is not dict or set(value[\'limits\']) != expected_limits or any(v is not True for v in value[\'limits\'].values()):\n        raise ValueError(\'SOURCE_DIAGNOSTICS_OUTPUT_LIMITS\')\n    if len(json.dumps(value, allow_nan=False, separators=(\',\', \':\')).encode()) > MAX_OUTPUT:\n        raise ValueError(\'SOURCE_DIAGNOSTICS_OUTPUT_LIMIT\')\n    return value\n'

_HEADER = ('import json,re,sqlite3,time\nfrom datetime import date,datetime,timedelta,timezone\n'
           + 'TARGETS='+repr(TARGETS)+'\nTARGET_NAMESPACE='+repr(TARGET_NAMESPACE)+'\n')
exec(compile(_HEADER+PROJECTION_SOURCE, '<completion-source-diagnostics>', 'exec'))


def validate_package(package):
    expected = {'baseline':BASELINE,'source_commit':SOURCE,'source_tar_gz_sha256':ARCHIVE,'mode':MODE}
    if type(package) is not dict or set(package) != set(expected) or package != expected:
        raise ValueError('SOURCE_DIAGNOSTICS_PACKAGE')


def script():
    prefix = ('import hashlib,json,os,re,socket,sqlite3,sys,time\nfrom pathlib import Path\n'
              'from datetime import date,datetime,timedelta,timezone\nTARGETS='+repr(TARGETS)
              +'\nTARGET_NAMESPACE='+repr(TARGET_NAMESPACE)+'\n')
    body = r'''
pending_failure=None
try:
    if os.geteuid()!=10001:
        raise ValueError('SOURCE_DIAGNOSTICS_IDENTITY')
    os.environ.clear()
    def no_network(*args, **kwargs):
        raise ValueError('SOURCE_DIAGNOSTICS_NETWORK_FORBIDDEN')
    socket.socket.connect=socket.socket.connect_ex=no_network
    for relative,digest in CODE_PINS.items():
        path=Path('/opt/naver-engine')/relative
        if path.is_symlink() or path.resolve()!=path or not path.is_file() or path.stat().st_size>1048576 or hashlib.sha256(path.read_bytes()).hexdigest()!=digest:
            raise ValueError('SOURCE_DIAGNOSTICS_CODE_PIN')
    set_read_stage('import')
    sys.path[:0]=['/opt/naver-engine','/opt/naver-engine/backend']
    from naver_engine import store as S,management_store as MS,inventory as I,management as P,inspection_store as IS,inspection_reads as IR,inspection_catalog as IC,sync as Y,product_evidence as PE
    from app.naver_auto import org_snapshot as O
    modules=dict(S=S,MS=MS,I=I,P=P,IS=IS,IR=IR,IC=IC,O=O,Y=Y,PE=PE)
    deadline=time.monotonic()+20
    set_read_stage('open')
    connection=connect_reader(Path('/var/lib/naver-engine/engine.db'))
    reader=S.Store(connection,'/var/lib/naver-engine/engine.db',None,writer=False)
    try:
        connection.set_progress_handler(lambda:time.monotonic()>=deadline,1000)
        connection.execute('BEGIN')
        result=collect(reader,datetime.now(KST),deadline,modules)
        if connection.total_changes!=0:
            raise ValueError('SOURCE_DIAGNOSTICS_MUTATION')
    except Exception as error:
        pending_failure=closed_reader_failure(error)
        raise
    finally:
        set_read_stage('cleanup')
        try:
            if connection.in_transaction:
                connection.execute('ROLLBACK')
        finally:
            reader.close()
    set_read_stage('output')
    check_deadline(deadline)
    encoded=json.dumps(result,sort_keys=True,allow_nan=False,separators=(',',':'))
    if len(encoded.encode())>16384:
        raise ValueError('SOURCE_DIAGNOSTICS_OUTPUT_LIMIT')
    print(encoded)
except Exception as error:
    print(json.dumps(pending_failure if pending_failure is not None else closed_reader_failure(error)))
'''
    return (prefix+'CODE_PINS='+repr(CODE_PINS)+'\nREAD_FAILURE_CODES='+repr(READ_FAILURE_CODES)+'\n'+PROJECTION_SOURCE+body).encode()


def validate_result(value):
    if type(value) is not dict or set(value)!={'schema_version','projection_model','target_identifier_namespace','targets','limits','mutations'}:
        raise ValueError('SOURCE_DIAGNOSTICS_OUTPUT_FIELDS')
    if type(value['schema_version']) is not int or value['schema_version']!=21 or type(value['mutations']) is not int or value['mutations']!=0:
        raise ValueError('SOURCE_DIAGNOSTICS_OUTPUT_SCHEMA')
    if value['projection_model']!='dc168-setup-stale-v1' or value['target_identifier_namespace']!=TARGET_NAMESPACE or type(value['targets']) is not dict or set(value['targets'])!={x[0] for x in TARGETS}:
        raise ValueError('SOURCE_DIAGNOSTICS_OUTPUT_TARGETS')
    def exact(row,keys):
        if type(row) is not dict or set(row)!=set(keys):raise ValueError('SOURCE_DIAGNOSTICS_OUTPUT_FIELDS')
    def boolean(row,keys):
        if any(type(row[k]) is not bool for k in keys):raise ValueError('SOURCE_DIAGNOSTICS_OUTPUT_FIELDS')
    check_keys={'account_present','account_snapshot_matches','catalog_accepted','catalog_stamp_matches','organization_current',
        'matching_fingerprint_matches','management_revision_matches','management_pair_matches','row_binding_matches',
        'row_scope_matches','current_cycle_matches','core_account_valid','full_account_valid','catalog_proof_current',
        'context_proof_present','context_proof_sealed','context_binding_matches','context_catalog_content_matches',
        'context_current','newer_valid_manual_generation','manual_generation_matches'}
    failed_keys=(check_keys-{'core_account_valid','full_account_valid','newer_valid_manual_generation','manual_generation_matches'})
    for row in value['targets'].values():
        exact(row,('policy','scope','manual','binding_checks','failed_checks','observation'))
        p=row['policy'];exact(p,('present','active','cadence','reason','expected_pair_matches','source_current'))
        boolean(p,('present','active','expected_pair_matches','source_current'))
        if p['cadence'] not in (None,'daily','weekly','blocked','UNRECOGNIZED') or p['reason'] not in REASONS|{None,'UNRECOGNIZED'}:
            raise ValueError('SOURCE_DIAGNOSTICS_OUTPUT_ENUM')
        if p['active']!=(p['present'] and p['cadence']!='blocked') or (not p['present'] and (p['cadence'] is not None or p['reason'] is not None or p['expected_pair_matches'] or p['source_current'])):
            raise ValueError('SOURCE_DIAGNOSTICS_OUTPUT_COUNTS')
        s=row['scope'];exact(s,('any_job_present','current_row_present','kind','status','history_rows_checked'))
        boolean(s,('any_job_present','current_row_present'))
        if type(s['history_rows_checked']) is not int or not 0<=s['history_rows_checked']<=200:
            raise ValueError('SOURCE_DIAGNOSTICS_OUTPUT_NUMBER')
        if s['kind'] not in (None,'daily','weekly','manual','UNRECOGNIZED') or s['status'] not in STATUSES|{None,'UNRECOGNIZED'}:
            raise ValueError('SOURCE_DIAGNOSTICS_OUTPUT_ENUM')
        if s['current_row_present']!=(s['kind'] is not None and s['status'] is not None) or s['current_row_present'] and not s['any_job_present']:
            raise ValueError('SOURCE_DIAGNOSTICS_OUTPUT_COUNTS')
        m=row['manual'];exact(m,('present','requested_today','expected_pair_matches','current_valid_request','kind'))
        boolean(m,('present','requested_today','expected_pair_matches','current_valid_request'))
        if m['kind'] not in (None,'manual','manual_period','UNRECOGNIZED') or m['present']!=(m['kind'] is not None) or (not m['present'] and any(m[k] for k in ('requested_today','expected_pair_matches','current_valid_request'))) or m['current_valid_request'] and (not m['requested_today'] or m['kind']!='manual'):
            raise ValueError('SOURCE_DIAGNOSTICS_OUTPUT_COUNTS')
        c=row['binding_checks'];f=row['failed_checks']
        if s['current_row_present']!=(c is not None):raise ValueError('SOURCE_DIAGNOSTICS_OUTPUT_COUNTS')
        expected_failures=[]
        if c is not None:
            exact(c,check_keys);boolean(c,check_keys)
            expected_failures=[k.upper() for k in failed_keys if c[k] is False]
            if c['newer_valid_manual_generation']:expected_failures.append('NEWER_VALID_MANUAL_GENERATION')
            if not c['core_account_valid']:expected_failures.append('CORE_ACCOUNT_INVALID')
            if not c['full_account_valid']:expected_failures.append('FULL_ACCOUNT_INVALID')
            if c['full_account_valid'] and (not c['core_account_valid'] or not all(c[k] for k in failed_keys)):
                raise ValueError('SOURCE_DIAGNOSTICS_OUTPUT_COUNTS')
        if type(f) is not list or any(type(x) is not str for x in f) or len(set(f))!=len(f) or set(f)!=set(expected_failures):
            raise ValueError('SOURCE_DIAGNOSTICS_OUTPUT_COUNTS')
        o=row['observation'];exact(o,('present','status','error_code','stale','complete','generation_present','checked_at_present','branch','projection_matches_actual'))
        boolean(o,('present','complete','generation_present','checked_at_present','projection_matches_actual'))
        if o['stale'] is not None and type(o['stale']) is not bool or o['branch'] not in BRANCHES or o['status'] not in STATUSES|{None,'pending','UNRECOGNIZED'} or o['error_code'] not in OBS_ERRORS|{None,'UNRECOGNIZED'}:
            raise ValueError('SOURCE_DIAGNOSTICS_OUTPUT_ENUM')
        if o['projection_matches_actual'] is not True or o['complete']!=(o['branch']=='CURRENT_COMPLETE'):
            raise ValueError('SOURCE_DIAGNOSTICS_OUTPUT_COUNTS')
        if o['branch']=='NO_OBSERVATION':
            if any(o[k] for k in ('present','complete','generation_present','checked_at_present')) or o['status'] is not None or o['error_code'] is not None or o['stale'] is not None:
                raise ValueError('SOURCE_DIAGNOSTICS_OUTPUT_COUNTS')
        elif not o['present'] or o['stale'] is None:raise ValueError('SOURCE_DIAGNOSTICS_OUTPUT_COUNTS')
        if o['error_code']=='SOURCE_STALE' and (o['branch'] not in ('POLICY_INACTIVE','CURRENT_ROW_INVALID') or o['generation_present'] or o['checked_at_present'] or o['stale'] is not True):
            raise ValueError('SOURCE_DIAGNOSTICS_OUTPUT_COUNTS')
        if o['branch']=='POLICY_INACTIVE' and (p['active'] or o['error_code']!='SOURCE_STALE'):
            raise ValueError('SOURCE_DIAGNOSTICS_OUTPUT_COUNTS')
        if o['branch']=='CURRENT_ROW_INVALID' and (c is None or c['full_account_valid'] or not p['active'] or o['error_code']!='SOURCE_STALE'):
            raise ValueError('SOURCE_DIAGNOSTICS_OUTPUT_COUNTS')
        if o['branch']=='MANUAL_PENDING' and (not m['current_valid_request'] or o['stale'] or not o['generation_present'] or o['checked_at_present'] or o['error_code']!='MANUAL_PENDING'):
            raise ValueError('SOURCE_DIAGNOSTICS_OUTPUT_COUNTS')
        if o['branch']=='CURRENT_PARTIAL' and (c is None or not c['full_account_valid'] or s['status']=='ok' or o['stale'] or not o['generation_present'] or not o['checked_at_present'] or o['status']!=s['status']):
            raise ValueError('SOURCE_DIAGNOSTICS_OUTPUT_COUNTS')
        if o['branch']=='NO_CURRENT_SCOPE_ROW' and (s['current_row_present'] or not p['active'] or o['error_code'] is not None or not o['stale']):
            raise ValueError('SOURCE_DIAGNOSTICS_OUTPUT_COUNTS')
        if o['complete'] and (c is None or not c['full_account_valid'] or not c['context_current'] or s['status']!='ok' or o['status']!='ok' or o['stale'] or not o['generation_present'] or not o['checked_at_present']):
            raise ValueError('SOURCE_DIAGNOSTICS_OUTPUT_COUNTS')
    exact(value['limits'],('stored_snapshot_only','source_guards_unchanged','management_not_synchronized','collection_completion_not_proven','scheduler_budget_unobserved','ads_unchanged'))
    if any(x is not True for x in value['limits'].values()):raise ValueError('SOURCE_DIAGNOSTICS_OUTPUT_LIMITS')
    if len(json.dumps(value,allow_nan=False,separators=(',',':')).encode())>MAX_OUTPUT:raise ValueError('SOURCE_DIAGNOSTICS_OUTPUT_LIMIT')
    return value


def run(package, host, release):
    """Same registered-read controller boundary, with an exact new closed profile.

    Only the separately registered dc168 profile can invoke this controller.
    """
    global STAGE
    STAGE='preflight'
    validate_package(package)
    if os.geteuid()!=0 or host.baseline()!=BASELINE:
        raise ValueError('HOST_BASELINE')
    path,prepared_path=release.prepared_paths(SOURCE)
    started_path=prepared_path.with_name('preview-start-'+SOURCE+'.json')
    for item in (prepared_path,started_path):
        release.trusted_private_file(item)
        if item.stat().st_size>32768:
            raise ValueError('RECEIPT_SIZE')
    prepared=json.loads(prepared_path.read_bytes(),object_pairs_hook=release.unique)
    started=json.loads(started_path.read_bytes(),object_pairs_hook=release.unique)
    if (prepared.get('ok') is not True or prepared.get('stage')!='prepared' or prepared.get('source_commit')!=SOURCE
            or any(prepared.get('package',{}).get(key)!=package[key] for key in ('baseline','source_commit','source_tar_gz_sha256'))
            or prepared.get('package',{}).get('run_id')!=PREPARE_RUN
            # P5 stores config/source/image proof here. The three policy fields
            # are in its returned prepare projection, not this persisted file.
            # The persisted started receipt below must still prove all three.
            or prepared.get('config_operation_id')!='74c912dddf824fae99012849bc4c19a5'
            or prepared.get('runtime_environment_preserved') is not True
            or prepared.get('inventory_enabled') is not True or prepared.get('execution_enabled') is not False
            or prepared.get('runtime_flags_verified') is not True or started.get('ok') is not True
            or started.get('previous_commit')!=PREVIOUS_SOURCE or started.get('operation_id')!=APPLY_OPERATION
            or started.get('database_policy')!='preserve-in-place' or started.get('database_opened_by_controller') is not False
            or started.get('source_warmup_performed') is not False or started.get('database_snapshot_verified') is not False
            or started.get('rollback_requires_matching_database') is not False or started.get('saved_export_companion_preserved') is not True
            or started.get('stage')!='internal_ready' or started.get('source_commit')!=SOURCE
            or type(started.get('database_schema')) is not int or started['database_schema']!=21
            or started.get('execution_enabled') is not False or started.get('runtime_flags_verified') is not True):
        raise ValueError('SOURCE_NOT_READY')
    for item in (path/'compose.naver-engine.yml',path/'preview-engine.override.yml',path/'deploy/naver-engine-backup.override.yml'):
        if item.resolve()!=item or release.sha(item.read_bytes())!=prepared.get('files',{}).get(str(item)):
            raise ValueError('COMPOSE_CHANGED')
    image_id=prepared.get('images',{}).get('engine')
    if type(image_id) is not str or re.fullmatch('sha256:[0-9a-f]{64}',image_id) is None:
        raise ValueError('PREPARED_IMAGE')
    image_format='{"id":{{json .Id}},"user":{{json .Config.User}},"source":{{json (index .Config.Labels "metainc.naver.preview.source")}}}'
    image=json.loads(release.command(['docker','image','inspect','--format',image_format,'metainc/naver-engine:'+SOURCE]))
    if image!={'id':image_id,'user':'10001:10001','source':SOURCE}:
        raise ValueError('PREPARED_IMAGE_CHANGED')
    identity=release.command(release.compose(path,'engine')+['ps','--all','--quiet']).decode().strip()
    if re.fullmatch('[0-9a-f]{64}',identity) is None:
        raise ValueError('PREVIEW_CONTAINER_ID')
    fmt='{"id":{{json .Id}},"image":{{json .Image}},"running":{{json .State.Running}},"user":{{json .Config.User}},"project":{{json (index .Config.Labels "com.docker.compose.project")}},"service":{{json (index .Config.Labels "com.docker.compose.service")}},"started":{{json .State.StartedAt}},"restarts":{{json .RestartCount}},"readonly":{{json .HostConfig.ReadonlyRootfs}},"data":[{{range .Mounts}}{{if eq .Destination "/var/lib/naver-engine"}}{{json .}}{{end}}{{end}}]}'
    def container():
        return json.loads(release.command(['docker','inspect','--format',fmt,identity]))
    before=container()
    if any(before.get(key)!=value for key,value in {'id':identity,'image':image_id,'running':True,'user':'10001:10001',
            'project':'naver-engine','service':'naver-engine','readonly':True}.items()):
        raise ValueError('PREVIEW_CONTAINER_CHANGED')
    mounts=before.get('data')
    if type(mounts) is not list or len(mounts)!=1 or type(mounts[0]) is not dict or any(mounts[0].get(key)!=value
            for key,value in {'Type':'bind','Destination':'/var/lib/naver-engine','Source':'/var/lib/metainc/naver-engine'}.items()):
        raise ValueError('PREVIEW_DATA_MOUNT')
    STAGE='read_only_source_diagnostics'
    primary=None
    failure_detail=None
    value=None
    try:
        try:
            raw=release.command(['docker','exec','-i','--user','10001:10001',identity,'python','-I','-B','-'],data=script(),timeout=30)
        except Exception as error:
            failure_detail=classify_failure(error,'reader-command')
            raise ValueError('SOURCE_DIAGNOSTICS_READER_FAILED') from None
        if len(raw)>MAX_OUTPUT:
            raise ValueError('SOURCE_DIAGNOSTICS_OUTPUT_LIMIT')
        value=json.loads(raw,object_pairs_hook=release.unique)
        if type(value) is dict and set(value) in ({'failure'},{'failure','failure_detail'}):
            if 'failure_detail' in value:failure_detail=validate_failure_detail(value['failure_detail'])
            code=value['failure']
            raise ValueError(code if type(code) is str and code in READ_FAILURE_CODES else 'SOURCE_DIAGNOSTICS_READ_FAILED')
        validate_result(value)
    except Exception as error:
        primary=error.args[0] if isinstance(error,ValueError) and len(error.args)==1 and type(error.args[0]) is str and error.args[0] in READ_FAILURE_CODES else 'SOURCE_DIAGNOSTICS_READ_FAILED'
        # Legacy one-field failures keep their original basic ABI. Locally
        # malformed output gains only a closed classification, never its text.
        if failure_detail is None and not (type(value) is dict and set(value)=={'failure'}):
            failure_detail=classify_failure(error,'output')
    STAGE='postflight'
    post_engine=post_legacy=None
    try:
        if container()!=before:
            post_engine='POST_ENGINE_CHANGED'
    except Exception:
        post_engine='POST_ENGINE_UNVERIFIED'
    try:
        if host.baseline()!=BASELINE:
            post_legacy='POST_LEGACY_BASELINE_CHANGED'
    except Exception:
        post_legacy='POST_LEGACY_BASELINE_UNVERIFIED'
    if primary is not None or post_engine is not None or post_legacy is not None:
        # Never overwrite an original closed reader failure with a postflight
        # failure, or expose a partial response as a successful diagnostic.
        failure={'ok':False,'mode':MODE,'source_commit':SOURCE,'mutations':0,
            'collection_completion_verified':False,'failure':{'primary_code':primary,
                'post_engine_code':post_engine,'post_legacy_baseline_code':post_legacy}}
        if primary is not None and failure_detail is not None:failure['failure_detail']=failure_detail
        return failure
    return {'ok':True,'mode':MODE,'source_commit':SOURCE,'reader_mode':'sqlite-mode-ro-query-only-authorizer',
        'database_opened_by_controller':False,'mutations':0,'existing_app_baseline_unchanged':True,
        'collection_completion_verified':False,'diagnostics':value}


def submit_preflight_script():
    raw = script()
    old = b'result=collect(reader,datetime.now(KST),deadline,modules)'
    if raw.count(old) != 1:
        raise ValueError('SOURCE_DIAGNOSTICS_CODE_PIN')
    return raw.replace(old, b'result=collect_submit_preflight(reader,datetime.now(KST),deadline,modules)', 1)


def run_submit_preflight(package, host, release):
    """Same registered-read controller boundary, with an exact new closed profile.

    Only the separately registered dc168 profile can invoke this controller.
    """
    global STAGE
    STAGE='preflight'
    validate_package(package)
    if os.geteuid()!=0 or host.baseline()!=BASELINE:
        raise ValueError('HOST_BASELINE')
    path,prepared_path=release.prepared_paths(SOURCE)
    started_path=prepared_path.with_name('preview-start-'+SOURCE+'.json')
    for item in (prepared_path,started_path):
        release.trusted_private_file(item)
        if item.stat().st_size>32768:
            raise ValueError('RECEIPT_SIZE')
    prepared=json.loads(prepared_path.read_bytes(),object_pairs_hook=release.unique)
    started=json.loads(started_path.read_bytes(),object_pairs_hook=release.unique)
    if (prepared.get('ok') is not True or prepared.get('stage')!='prepared' or prepared.get('source_commit')!=SOURCE
            or any(prepared.get('package',{}).get(key)!=package[key] for key in ('baseline','source_commit','source_tar_gz_sha256'))
            or prepared.get('package',{}).get('run_id')!=PREPARE_RUN
            # P5 stores config/source/image proof here. The three policy fields
            # are in its returned prepare projection, not this persisted file.
            # The persisted started receipt below must still prove all three.
            or prepared.get('config_operation_id')!='74c912dddf824fae99012849bc4c19a5'
            or prepared.get('runtime_environment_preserved') is not True
            or prepared.get('inventory_enabled') is not True or prepared.get('execution_enabled') is not False
            or prepared.get('runtime_flags_verified') is not True or started.get('ok') is not True
            or started.get('previous_commit')!=PREVIOUS_SOURCE or started.get('operation_id')!=APPLY_OPERATION
            or started.get('database_policy')!='preserve-in-place' or started.get('database_opened_by_controller') is not False
            or started.get('source_warmup_performed') is not False or started.get('database_snapshot_verified') is not False
            or started.get('rollback_requires_matching_database') is not False or started.get('saved_export_companion_preserved') is not True
            or started.get('stage')!='internal_ready' or started.get('source_commit')!=SOURCE
            or type(started.get('database_schema')) is not int or started['database_schema']!=21
            or started.get('execution_enabled') is not False or started.get('runtime_flags_verified') is not True):
        raise ValueError('SOURCE_NOT_READY')
    for item in (path/'compose.naver-engine.yml',path/'preview-engine.override.yml',path/'deploy/naver-engine-backup.override.yml'):
        if item.resolve()!=item or release.sha(item.read_bytes())!=prepared.get('files',{}).get(str(item)):
            raise ValueError('COMPOSE_CHANGED')
    image_id=prepared.get('images',{}).get('engine')
    if type(image_id) is not str or re.fullmatch('sha256:[0-9a-f]{64}',image_id) is None:
        raise ValueError('PREPARED_IMAGE')
    image_format='{"id":{{json .Id}},"user":{{json .Config.User}},"source":{{json (index .Config.Labels "metainc.naver.preview.source")}}}'
    image=json.loads(release.command(['docker','image','inspect','--format',image_format,'metainc/naver-engine:'+SOURCE]))
    if image!={'id':image_id,'user':'10001:10001','source':SOURCE}:
        raise ValueError('PREPARED_IMAGE_CHANGED')
    identity=release.command(release.compose(path,'engine')+['ps','--all','--quiet']).decode().strip()
    if re.fullmatch('[0-9a-f]{64}',identity) is None:
        raise ValueError('PREVIEW_CONTAINER_ID')
    fmt='{"id":{{json .Id}},"image":{{json .Image}},"running":{{json .State.Running}},"user":{{json .Config.User}},"project":{{json (index .Config.Labels "com.docker.compose.project")}},"service":{{json (index .Config.Labels "com.docker.compose.service")}},"started":{{json .State.StartedAt}},"restarts":{{json .RestartCount}},"readonly":{{json .HostConfig.ReadonlyRootfs}},"data":[{{range .Mounts}}{{if eq .Destination "/var/lib/naver-engine"}}{{json .}}{{end}}{{end}}]}'
    def container():
        return json.loads(release.command(['docker','inspect','--format',fmt,identity]))
    before=container()
    if any(before.get(key)!=value for key,value in {'id':identity,'image':image_id,'running':True,'user':'10001:10001',
            'project':'naver-engine','service':'naver-engine','readonly':True}.items()):
        raise ValueError('PREVIEW_CONTAINER_CHANGED')
    mounts=before.get('data')
    if type(mounts) is not list or len(mounts)!=1 or type(mounts[0]) is not dict or any(mounts[0].get(key)!=value
            for key,value in {'Type':'bind','Destination':'/var/lib/naver-engine','Source':'/var/lib/metainc/naver-engine'}.items()):
        raise ValueError('PREVIEW_DATA_MOUNT')
    STAGE='read_only_source_diagnostics'
    primary=None
    failure_detail=None
    value=None
    try:
        try:
            raw=release.command(['docker','exec','-i','--user','10001:10001',identity,'python','-I','-B','-'],data=submit_preflight_script(),timeout=30)
        except Exception as error:
            failure_detail=classify_failure(error,'reader-command')
            raise ValueError('SOURCE_DIAGNOSTICS_READER_FAILED') from None
        if len(raw)>MAX_OUTPUT:
            raise ValueError('SOURCE_DIAGNOSTICS_OUTPUT_LIMIT')
        value=json.loads(raw,object_pairs_hook=release.unique)
        if type(value) is dict and set(value) in ({'failure'},{'failure','failure_detail'}):
            if 'failure_detail' in value:failure_detail=validate_failure_detail(value['failure_detail'])
            code=value['failure']
            raise ValueError(code if type(code) is str and code in READ_FAILURE_CODES else 'SOURCE_DIAGNOSTICS_READ_FAILED')
        validate_submit_preflight_result(value)
    except Exception as error:
        primary=error.args[0] if isinstance(error,ValueError) and len(error.args)==1 and type(error.args[0]) is str and error.args[0] in READ_FAILURE_CODES else 'SOURCE_DIAGNOSTICS_READ_FAILED'
        # Legacy one-field failures keep their original basic ABI. Locally
        # malformed output gains only a closed classification, never its text.
        if failure_detail is None and not (type(value) is dict and set(value)=={'failure'}):
            failure_detail=classify_failure(error,'output')
    STAGE='postflight'
    post_engine=post_legacy=None
    try:
        if container()!=before:
            post_engine='POST_ENGINE_CHANGED'
    except Exception:
        post_engine='POST_ENGINE_UNVERIFIED'
    try:
        if host.baseline()!=BASELINE:
            post_legacy='POST_LEGACY_BASELINE_CHANGED'
    except Exception:
        post_legacy='POST_LEGACY_BASELINE_UNVERIFIED'
    if primary is not None or post_engine is not None or post_legacy is not None:
        # Never overwrite an original closed reader failure with a postflight
        # failure, or expose a partial response as a successful diagnostic.
        failure={'ok':False,'mode':MODE,'source_commit':SOURCE,'mutations':0,
            'collection_completion_verified':False,'failure':{'primary_code':primary,
                'post_engine_code':post_engine,'post_legacy_baseline_code':post_legacy}}
        if primary is not None and failure_detail is not None:failure['failure_detail']=failure_detail
        return failure
    return {'ok':True,'mode':MODE,'source_commit':SOURCE,'reader_mode':'sqlite-mode-ro-query-only-authorizer',
        'database_opened_by_controller':False,'mutations':0,'existing_app_baseline_unchanged':True,
        'collection_completion_verified':False,'diagnostics':value}

