"""Completion release: exact pending pins, schema11→21, paired code/DB recovery.

Not routed or deployable until root pins the final source, both full manifests,
CI receipt and UI assets. Existing V26 and its guards are untouched.
"""
import ast
from contextlib import closing, contextmanager
import fcntl
import hashlib
import json
import os
from pathlib import Path
import pwd
import re
import stat
import sqlite3
from types import SimpleNamespace
import uuid
OLD_COMMIT = '737a65952f2ddbc05a235cf2b139a4a11f4e7673'
TARGET_COMMIT = 'e7649acfc71c25d7ae9c981a6ba036b77d97897b'
EXPECTED_BASELINE = '5463ca7b23575f668062e842f551170937239e625fb5a6104655c031c7e31d76'
OLD_SOURCE_SHA256 = '957ed0362ba9e3775a832c78011dc838c39297855d1f8ce901038d4e0c4e4450'
TARGET_SOURCE_SHA256 = '7d02a455ff2b8b2e2bbcd598b71f5e06ffe8e9d2099f08a2e87a8ea10cbae872'
STORE_SHA256 = {'old': 'a78560f42cd3e4ee774135b3b148f0e518ce59a41f1c9d74ae475769aa643856', 'target': 'e63482ff15c5f1fd4f1c26c6119df477aacb708b80751b0617eb9af8ec341b57'}
CODE_PATHS = frozenset()
OLD_MANIFEST = {'.dockerignore': (420, 408, 'ba16cad53840bc35b7c174d5cc143a83e7a56cc63acad2c2d14fab17ab30d1a6'), 'Dockerfile.naver-engine': (420, 1134, 'f838c3da2687e8b800046005ef5bd39b1fc3e3454cecdbe291a233ee00004edc'), 'Dockerfile.naver-engine.dockerignore': (420, 374, '4b3d1a3f35e7f84a6db89382a1b27358ed1a8f2ee9d3b0112c87ded1f468f43d'), 'Dockerfile.naver-relay': (420, 1421, 'c05ec8ced0554c9237718e3c37c265c615d86461d3f5b23df30f23bf113da77d'), 'Dockerfile.naver-relay.dockerignore': (420, 462, 'ae83e68adcc2b2b9cc987dc81e92a3fa42c91542309d9467033a69f59590fb59'), 'backend/app/__init__.py': (420, 0, 'e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855'), 'backend/app/naver_auto/__init__.py': (420, 927, '64020d9148504885f294af924dcea4d2f312df8b6014d646f98b9e5221a4f164'), 'backend/app/naver_auto/checks.py': (420, 16435, '79e61753a0c16f1a8106e7bec2ed89404688eb6ff9a67f8783f47d13409b0b4c'), 'backend/app/naver_auto/issues.py': (420, 14469, 'b47ab19a490c5035cec0e59d19e5720edb03d0c103fe4e1cce3abe2dace9556a'), 'backend/app/naver_auto/matching.py': (420, 27050, '6be28f0bcf2e86ff1a2d799063c3ac5caca81a33ac3572ed7f754aef14bb3eb0'), 'backend/app/naver_auto/org_snapshot.py': (420, 33415, '34da0635ee7d071c3dd02bf4001343f2c42001ebc70d7e5548e692d687920f97'), 'backend/app/naver_auto/scope.py': (420, 35601, 'fd25fae418f27e6bd9b01415489164eb85241a5151a3e5fa1ad085edec7b3cd7'), 'backend/app/naver_auto/thresholds.py': (420, 3789, '6b5259480f85d0c397fac1ee7884a4beb14e0ee60da02669c104b21131498aa7'), 'backend/app/naver_auto/verdict.py': (420, 11797, 'b8ff947d92e9dd0e0ceafd6b1da2e7dc3841875811417e83ae387ba0074809ec'), 'backend/app/naver_entry.py': (420, 457, '21aaf8ace7ca7b650e42cf1a32848cf00696680b68c6624a6ca9cbab7c891c08'), 'backend/app/naver_relay.py': (420, 25944, 'e9d7d38d572a21af77e220199bd34988908d3c636c3a834071fec35bd3065e61'), 'backend/app/routers/__init__.py': (420, 0, 'e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855'), 'backend/app/routers/naver.py': (420, 5619, 'cac5dfc32757f7472f86387447e93cb178de60771cf2bf699aa8ad4cf6bf8069'), 'backend/naver_page/README.md': (420, 824, '6ea9866e718da69999ffc5ce878aaa71e29bb9a6b8f65e4cf53a59c7fb779212'), 'backend/naver_page/app.css': (420, 57115, '82174f6c25649692b68df439bb8f61329a218f6d052e77b8e9b0e9dd1970bee7'), 'backend/naver_page/app.js': (420, 222000, 'f119f80f3fac01de107f7ce45a2ed39f5443dfc4a79db8f8c67ad06678549078'), 'backend/naver_page/automation-ui.js': (420, 22976, '0828746fd2c60d43dd9e6f448782d1c46d543ecf2eb243590df8130ac5f6d2d3'), 'backend/naver_page/favicon.svg': (420, 188, '008a5b8b00e9602ceb35ea244f5ecef6110d8ad0067ac9d993f992a9525c9c5c'), 'backend/naver_page/index.html': (420, 28101, '1651175414b128e136f1553d38cae8e44cd7baf61fd3dad8d001d48b0963dd77'), 'backend/naver_page/learning-ui.js': (420, 23619, '9cae047e4cf163d20e9e597df364da3565c88ed622b4cfe2d6ab651a1274ef7e'), 'backend/naver_page/report-pdf.js': (420, 37921, '454ccb5f20b3a8f125ac9f1e1cc765041a0d23e8a881fa11ccbfea5b5c848964'), 'backend/naver_page/report-ui.js': (420, 89541, '24aba1490a188ab52e6cb22a412030ef42ed1d89da356cdea595f314180e6ead'), 'backend/naver_page/sales-ui.js': (420, 17774, '00553781030990970c88dcd6d86c11730cf9c60cf9ce7a7963f2b091cd5aa2ff'), 'backend/naver_page/sales.css': (420, 5905, 'f27843cb1e1e63a41d85f5f794035f47c62ec72dda5971f95dd9ed58226ba09d'), 'backend/naver_page/sso-bootstrap.js': (420, 4588, 'b32369913287c49fa43fa210db73742f51c203066273b0334b4d6ebbb335b289'), 'backend/naver_page/vendor/report-pdf/Apache-2.0.txt': (420, 11358, 'cfc7749b96f63bd31c3c42b5c471bf756814053e847c10f3eb003417bc523d30'), 'backend/naver_page/vendor/report-pdf/NanumGothic-OFL.txt': (420, 4532, '90f6a909ffb2af7f6422ea20042a26180fe5520cba80bbbf75a5e660320d7924'), 'backend/naver_page/vendor/report-pdf/NanumGothic-Regular.ttf.gz': (420, 697020, '72d1bf88a642ede8ff7da422031106fc697ea4c79b1cfd2994bffc57df4dab07'), 'backend/naver_page/vendor/report-pdf/THIRD-PARTY-NOTICES.txt': (420, 12147, '33588a8c88e8c3f6535dc653bf65840b08dd75b7e7f2beec69d6f5a3542ffa67'), 'backend/naver_page/vendor/report-pdf/fontkit-1.1.1.umd.min.js': (420, 758440, 'd8df561b9fba98e24f2e5130e40948809281bbbc55a20c412359f1a0a5eb35a6'), 'backend/naver_page/vendor/report-pdf/fontkit-LICENSE.txt': (420, 1462, '3b839fbef51e4721ff85ba6c6c79e0d37738f28c28bf90c744d7c4bf9f0eb1a0'), 'backend/naver_page/vendor/report-pdf/js-sha256-LICENSE.txt': (420, 1076, '2153bd2978793748fbe0eb8f838ae2ae19f03f9d4ee5473dd1628a0c0790e4ab'), 'backend/naver_page/vendor/report-pdf/manifest.json': (420, 3008, 'd7b047f71ecf086d422031b4fba80d708a3987fe6635c78e16de82979aa2f3de'), 'backend/naver_page/vendor/report-pdf/pako-LICENSE.txt': (420, 1104, 'a04665b3b2de56c66730c1f720f528175739e4104f79073614aa611da1e85539'), 'backend/naver_page/vendor/report-pdf/pdf-lib-1.17.1.min.js': (420, 525099, '0f9a5cad07941f0826586c94e089d89b918c46e5c17cf2d5a3c6f666e3bc694f'), 'backend/naver_page/vendor/report-pdf/pdf-lib-LICENSE.txt': (420, 1070, 'f2c9fc00fdb66eb99ac156ba52d734af66d8d309f65753ae809ad34ee2883bcb'), 'backend/naver_page/vendor/report-pdf/sha256-1.0.0.min.js': (420, 8156, 'a050d794e170699bd1a69d33908d0942c68901cb88347016064b60b240f0067e'), 'backend/naver_page/vendor/report-pdf/standard-fonts-LICENSE.txt': (420, 1070, '45cc2bb9957ed43f5c7f5eb1912f9f670730394d614079510477cae626194649'), 'backend/naver_page/vendor/report-pdf/upng-LICENSE.txt': (420, 1065, 'c1fb8861eca211bf5aea574358aba7039396c0c1824c2a1477cc126d398efd89'), 'backend/requirements.txt': (420, 144, '0264b07e26f94bc31522b7fcf4801318f21b0d86d74793e6fd9608f8a64ca67c'), 'compose.naver-engine.yml': (420, 2697, '62e33c3d2815579a28031973b956cd36031171f26ead4e21ad2d72adfe2a5ef7'), 'compose.naver-relay.yml': (420, 1514, '00404b84a4377fcb74afc883feff6d2a434b1fca92f0be7b2d399a72ba05da66'), 'deploy/naver-backup-receiver.py': (420, 11383, 'ac324dab4e868477c5c5aceef641e26a2359d45bdde6ac884331de09a208205c'), 'deploy/naver-engine-ad-api.override.yml': (420, 598, '961eddbd2bfe607ac0fe90dc056a7cd09de2a065b942ee0e6c0cc205e1f432fd'), 'deploy/naver-engine-backup.override.yml': (420, 971, 'bfbe6cc3b2a5988071ba067d2b599929deea2ef7d6b8c8644d2aefd236b65a78'), 'deploy/naver-engine-nginx.conf': (420, 2599, 'b26a13f1b7b4f7b5d6ca154333f91b3a92b80348a164544ded2d6e3b8e78e025'), 'deploy/naver-erp-tunnel/OPERATIONS.md': (420, 8186, 'ee50a7dc794d1168b53dff435577595fafb90f11dd2771e77a0e8209aaac37be'), 'deploy/naver-erp-tunnel/ad-ssh.conf': (420, 1385, '1c37f158c26a988973707c36b2f4ccade561c6e1fa93334a12ece8abaf9df0aa'), 'deploy/naver-erp-tunnel/ad-tunnel.service': (420, 1245, 'd6f4698a5aaf53e87bb47e07826503801d4ef49a9a12213d419b1208e33eb35a'), 'deploy/naver-erp-tunnel/authorized_keys.template': (420, 138, '3fab1b741f766435b317325799e50dab985c9f368041b16ca435ed82c1903c3b'), 'deploy/naver-erp-tunnel/be-nginx.conf': (420, 2966, '0c8b4d959203b37892346bcc9796518f95377eaee7e56ff26dee8b01c547d891'), 'deploy/naver-erp-tunnel/be-sshd.conf': (420, 835, '4440431dd03fc52171ee3a8abd9d9ce45500ece0c88e853dfe5537bd30992fc3'), 'deploy/naver-erp-tunnel/test.Dockerfile': (420, 588, '0fa260ab2000c9ea9d7d45330c8256060f7912e3d296bf554c2f4e3fc73b1ee0'), 'deploy/naver-erp-tunnel/test.Dockerfile.dockerignore': (420, 250, '4b7c07b25bf9724ea79620e03d7b40b69ce548dcfe01f478ada8c02c9c2c755a'), 'deploy/naver-erp-tunnel/test_policy.py': (420, 18991, 'e53a165a0a973aacc5a7f8b81c62f6921c88a7f0acabd4992f5521b86c0a7a26'), 'deploy/nginx-ad.metainc.co.kr.conf': (420, 739, '31574f6e1e0dcad25c57fb3f4f183b8f5bfed4b1fb14cd4c7f5f77efac6e89d1'), 'naver_engine/__init__.py': (420, 1077, '83ca0328fd0eb93b016be936321703ae88df5d3410b369df18c5c7290ed6bf74'), 'naver_engine/ad_reasons.py': (420, 5523, '12cb7edc84f8f302036c16677ae51ebbbbc117aa1feba6f58fb32b906501beec'), 'naver_engine/alerts.py': (420, 39621, 'bc4636d8b6f685e02a9305061926299f9fa52f50fbcf6c6e4cb9da8b29d1c35d'), 'naver_engine/approval_documents.py': (420, 6175, 'a50eed929f94debbfc01445ef6a4303c3c749fa1739bad44e942825502691eab'), 'naver_engine/automation_views.py': (420, 4948, '841f9d6e1725842914d73adee1d52e330005f961f038279617449883b51b80dd'), 'naver_engine/backup.py': (420, 16760, '1bc2561ea3d8cc5f528b64ed275da4ca242fe9a5cf166c6bb53aaf6c0ff3a92e'), 'naver_engine/catalog_links.py': (420, 13417, '2984a7582347cad4580be1f25bdee93146e933222f3b783cc2a1bb5ae6478b7b'), 'naver_engine/collection_diagnostics.py': (420, 4116, 'c0c41429d60a4b5c17dc1495e9f36aa65f2502379b41233487e90d42a296f895'), 'naver_engine/credentials.py': (420, 4788, 'f20794c7f89ee29c396fa596ff44c6781bd87872914d08f58b83d15b88df3c84'), 'naver_engine/dashboard.py': (420, 9334, '2c2c86c96f249f133220463f8988b96e07eee795d44dbc844204943370206f15'), 'naver_engine/erp_alert.py': (420, 16095, '55e639ccb747e8e5f34af80e9802e03a0b650c26d06c89531b12ce5b2b8abf92'), 'naver_engine/erp_profile.py': (420, 7315, '108b4ee5d97dfa6174ccca18c5e92e9308976a349c6a648985a7ac45ea75986c'), 'naver_engine/erp_read.py': (420, 21665, 'fc8db800b5fd7cfa9d6e64e621d3513c646b1bcbfaf5c73ab128c6f937092499'), 'naver_engine/fields.py': (420, 3369, 'a92d4182bad903bb3e5c22519ea93dace5041475bc874967024cc34f5e340a6a'), 'naver_engine/handles.py': (420, 16016, 'fa64d8841f352b413ea12fdb8b88ab53c73133eaf0e91a98d8c586a52e8a8e14'), 'naver_engine/inventory.py': (420, 29075, '2a5c4d5f6acb0b431daa9e16be517322a43008aa636cfdf90c49c4a9305ae28e'), 'naver_engine/inventory_reads.py': (420, 9956, '40892186fddd444f2f8868ea31323744e155d8c59eeb42b3ef6deea482a379e1'), 'naver_engine/learning_assets.py': (420, 21080, 'fa3ca40266c69bae43d645685722874d0097918f9813c943d8b3fd8a579b3347'), 'naver_engine/learning_retrieval.py': (420, 5440, '6271dd8af0ba3f435ebeb808dfdcaae9ce645655fb764d17342c0f75d774fd0b'), 'naver_engine/links.py': (420, 24837, 'a97b7f293e32f55ac92a7b53c77884fbc50bb7d481212346f85f7dc8ae2db249'), 'naver_engine/management.py': (420, 5723, '84862507d3831053edf618c6d68e800f1f1a1ec4019bcc88030eacb4d14f37e4'), 'naver_engine/management_store.py': (420, 11391, 'e912f5941d9ce61b57327d7ae7d6307086d06570de72bfea4f9ed0cee389af1d'), 'naver_engine/marketing_strategy.py': (420, 36154, '2b4c5223227890eb7aba253f6ced893a5e19df3b7622556d29aca7b522246b27'), 'naver_engine/metrics.py': (420, 15005, 'f734fa8b2173ff5b59dcd4aeb02e61fbbe77ab23d1cc15ae6ce8441e3548564c'), 'naver_engine/monthly_reads.py': (420, 11994, 'f26214bf881b95be54fca75c941a15cb8f92f667e5af30aa94369e8fda5b7299'), 'naver_engine/morning.py': (420, 48264, 'f6cd9d4c5fd0453dcf77f707313d9c37ff6e01621e1d5f86325423b3adc94ca6'), 'naver_engine/morning_progress.py': (420, 6839, 'c6cb0faf936820a2d93b90985e0aaa1362b1bf3d3a6d98d861212c17366f54b1'), 'naver_engine/naver_read.py': (420, 58166, '07682c649b508eb3b10fd1a0fd62aec0f99bafc6b30c75133e117c7fc6ac49a2'), 'naver_engine/performance_reads.py': (420, 18142, '85a863871288640e0a1a6745a10c618cc2e34e13dbb6de2b6fcf9b9040b3798e'), 'naver_engine/report_enrichment.py': (420, 20237, 'b151e866f561b93661ef52a7f7470f04d3f616d00de14b7e81bc2db6f5c0e1d1'), 'naver_engine/report_notes.py': (420, 9275, 'dadb0b4b1501a87176a4e85dc8c4b74745c39a48888c1c43dda7044048f04408'), 'naver_engine/report_refresh.py': (420, 5882, '1d3e97c43982f855bd6dec93ef0c64173d0c77aec7c0daf25dc56547c2eda3ee'), 'naver_engine/report_views.py': (420, 17055, '0e270227163c7b67fb53fcb3b8eb72eb44e84095a4eded5463b3b807805b1cf5'), 'naver_engine/reporting.py': (420, 25850, '76a7a27ab39f69e9adf4a58547562e00776f6aaa0020df519cb2da8d032bd006'), 'naver_engine/runtime_view.py': (420, 2407, 'a8d78825c16aaa0a3fcc877fdb4a3cfaddc8330154f9331b75eee2cae6c90a4a'), 'naver_engine/sales_views.py': (420, 7905, '885598a9890df6913b54e0d4bf8f2041a18befe5ae319aa0963edb12b5e770f7'), 'naver_engine/session.py': (420, 8455, 'f710ae69062f2ef13c447767fe65ce17c0990aebe65fa6222c4e312129b8e432'), 'naver_engine/setup_checks.py': (420, 15551, 'f7a4f0c0d33fdfa9e3f91c7d219d8185c97bd35d37e4984c04a8eb4bc111a37e'), 'naver_engine/store.py': (420, 433675, 'a78560f42cd3e4ee774135b3b148f0e518ce59a41f1c9d74ae475769aa643856'), 'naver_engine/structure_reads.py': (420, 14811, 'fed780a4903a099b540cc4eb6b9419ee84cbfdbd26056ad1c338a5db23d71c22'), 'naver_engine/sync.py': (420, 24402, '7ddd57ccce8a8edcf13e3d4495d748d122b067e1bba32becfa6326a4dda32dad'), 'naver_engine/view_sync.py': (420, 5380, '57c97bb82d78dc25277cdd7f5ea23c1512be0cfd0279a837e1e64d0b317a4034'), 'naver_engine/views.py': (420, 63931, '5fe46a4e04c271cda518c2cfbac5aecf6848dd8e9815c557421ac34a8231b34a'), 'naver_engine/web.py': (420, 105840, 'a8e9315f458cad04b71f5051865fd08b01b364bc06d1cedcd5d3d080e8b1064c'), 'naver_runtime/__init__.py': (420, 105, '27d28d6ed467edc27f1b22a7a3fedd78253d562938c3cf060ea2573ef38038ec'), 'naver_runtime/__main__.py': (420, 13017, '26185768b4db95d848b74eeb7d37a173501315fd8941427c17b94c3822c14dd7'), 'naver_runtime/backup_transport.py': (420, 5364, 'b14520d0f46429ea93a3158b664ca7f5cb37e378ce146e684cd276265f92db71'), 'naver_runtime/bootstrap.py': (420, 12709, 'dd7f5949eee28e0391608670b3f00a40c30e6b461a3589bf47fcc7b49c5dd504'), 'naver_runtime/claude_provider.py': (420, 14343, 'a20f6f776414aa794f72d0f70c41330fec276e9542708f397ed49c90f17c7706'), 'naver_runtime/collection_requests.py': (420, 6497, '1e7606023cdbd27826b0f0e4e07a3f0f6fa4955d6d00396a1af33e7f62526660'), 'naver_runtime/config.py': (420, 5907, 'a7575256459b99b278bdeb4452bb643944e8983b8cda5f8d007b766a794c7bf5'), 'naver_runtime/erp_tunnel_transport.py': (420, 10072, '59d1c40300c416b40d022ce6d1d91cdc9ac3d4a3b981c260ca3002e919bd3288'), 'naver_runtime/learning_jobs.py': (420, 5822, 'c1f494af99a2eb678907703ceb8372f7943f205a5d67f16bf41071855b04b33a'), 'naver_runtime/learning_provider.py': (420, 4914, '2e1c27a3180ce6ecc032086dad78e27b19eccb6f854a33c26fe6af8a5afb7c6f'), 'naver_runtime/restore_check.py': (420, 5657, '0f7c392155b9fdcb602307b7bd5771c211ca9f6774f5dcfa8106f940bb7905b9'), 'naver_runtime/runtime_status.py': (420, 6149, 'f08633202d21248dde7c62c2d6bdb42a40b981721df958b0124fc7009b4da8eb'), 'naver_runtime/scheduler.py': (420, 26620, '521aeec2132f423c62a62600644189cdb9d423b3a95fefa685de2ad8a2f58110'), 'naver_runtime/server.py': (420, 6425, 'bf17856d256bf672aa4f50d8d9bf4b2557cec9a2aed7f1a0f5f97eee81ca8007'), 'naver_runtime/writer.py': (420, 12150, 'eaa170a7c3a1b0d6f8c7e9340e99d05168a82961b675b7810960aff7b55e5b5a')}
TARGET_MANIFEST = {'.dockerignore': (420, 408, 'ba16cad53840bc35b7c174d5cc143a83e7a56cc63acad2c2d14fab17ab30d1a6'), 'Dockerfile.naver-engine': (420, 1134, 'f838c3da2687e8b800046005ef5bd39b1fc3e3454cecdbe291a233ee00004edc'), 'Dockerfile.naver-engine.dockerignore': (420, 374, '4b3d1a3f35e7f84a6db89382a1b27358ed1a8f2ee9d3b0112c87ded1f468f43d'), 'Dockerfile.naver-relay': (420, 1421, 'c05ec8ced0554c9237718e3c37c265c615d86461d3f5b23df30f23bf113da77d'), 'Dockerfile.naver-relay.dockerignore': (420, 462, 'ae83e68adcc2b2b9cc987dc81e92a3fa42c91542309d9467033a69f59590fb59'), 'backend/app/__init__.py': (420, 0, 'e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855'), 'backend/app/naver_auto/__init__.py': (420, 927, '64020d9148504885f294af924dcea4d2f312df8b6014d646f98b9e5221a4f164'), 'backend/app/naver_auto/checks.py': (420, 16435, '79e61753a0c16f1a8106e7bec2ed89404688eb6ff9a67f8783f47d13409b0b4c'), 'backend/app/naver_auto/issues.py': (420, 14469, 'b47ab19a490c5035cec0e59d19e5720edb03d0c103fe4e1cce3abe2dace9556a'), 'backend/app/naver_auto/matching.py': (420, 27050, '6be28f0bcf2e86ff1a2d799063c3ac5caca81a33ac3572ed7f754aef14bb3eb0'), 'backend/app/naver_auto/org_snapshot.py': (420, 33415, '34da0635ee7d071c3dd02bf4001343f2c42001ebc70d7e5548e692d687920f97'), 'backend/app/naver_auto/scope.py': (420, 35601, 'fd25fae418f27e6bd9b01415489164eb85241a5151a3e5fa1ad085edec7b3cd7'), 'backend/app/naver_auto/thresholds.py': (420, 3789, '6b5259480f85d0c397fac1ee7884a4beb14e0ee60da02669c104b21131498aa7'), 'backend/app/naver_auto/verdict.py': (420, 11797, 'b8ff947d92e9dd0e0ceafd6b1da2e7dc3841875811417e83ae387ba0074809ec'), 'backend/app/naver_entry.py': (420, 457, '21aaf8ace7ca7b650e42cf1a32848cf00696680b68c6624a6ca9cbab7c891c08'), 'backend/app/naver_relay.py': (420, 25944, 'e9d7d38d572a21af77e220199bd34988908d3c636c3a834071fec35bd3065e61'), 'backend/app/routers/__init__.py': (420, 0, 'e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855'), 'backend/app/routers/naver.py': (420, 5619, 'cac5dfc32757f7472f86387447e93cb178de60771cf2bf699aa8ad4cf6bf8069'), 'backend/naver_page/README.md': (420, 824, '6ea9866e718da69999ffc5ce878aaa71e29bb9a6b8f65e4cf53a59c7fb779212'), 'backend/naver_page/app.css': (420, 59087, '296efe6a624ada65affaf2397d2dd55356917bcdc540f6f4f4eddfacee17a5dd'), 'backend/naver_page/app.js': (420, 223505, '8a4daa3a0dbaa9ae61434c8dac223bdb47a3ed0b9106c7c324b4aa8260f25ab3'), 'backend/naver_page/automation-ui.js': (420, 46840, '2997ab9abd54474c913e56189e8c7bbcf0a5a9e6fb8550e331b9dd338bee03f8'), 'backend/naver_page/execution-ui.js': (420, 54585, 'a6febc90e4fda776a1a4f5f666304993484edb540b82f059335221edfeb6a6d1'), 'backend/naver_page/experiments-ui.js': (420, 62774, '043d513b2611ecc620bbfe7143231d4c4951a52a2ddac9150e36b49f3ba69d4e'), 'backend/naver_page/favicon.svg': (420, 188, '008a5b8b00e9602ceb35ea244f5ecef6110d8ad0067ac9d993f992a9525c9c5c'), 'backend/naver_page/index.html': (420, 28388, 'cd24b8f51b94103204bc11ec87cfb488db1a9cb9122f2ac427cb1b81f16dd4f6'), 'backend/naver_page/learning-ui.js': (420, 51105, '28dcb6b7f923048d90ae5ef86e0664c4bfbc7d2b127bc41f2e46ee0a79c0f340'), 'backend/naver_page/operations-ui.js': (420, 12286, '02b756eaa66ec7e5d8a0939473953ec7a639d59e3e23f4dd8c34715b43880008'), 'backend/naver_page/randomized-experiments-ui.js': (420, 36703, 'c3b0096f8e36cc41136f5b9fd0cb21c4b66a19e4b6765c15c92092e81a7b7f1a'), 'backend/naver_page/report-pdf.js': (420, 40388, '03445e5236b80669395d48cc1ebef52dafaf372e84bade035193496c7d6e3867'), 'backend/naver_page/report-schedule-ui.js': (420, 15440, '84beb5cdf5368a706dc85ee20f2666f7108e83724b131c5f7d43bd62ece94b99'), 'backend/naver_page/report-ui.js': (420, 102575, 'f9121aa9fe2d4a82bfcc3d7712d81e0fd043447210ab08ac726a4f2be65cbed8'), 'backend/naver_page/sales-ui.js': (420, 17774, '00553781030990970c88dcd6d86c11730cf9c60cf9ce7a7963f2b091cd5aa2ff'), 'backend/naver_page/sales.css': (420, 5905, 'f27843cb1e1e63a41d85f5f794035f47c62ec72dda5971f95dd9ed58226ba09d'), 'backend/naver_page/sso-bootstrap.js': (420, 4588, 'b32369913287c49fa43fa210db73742f51c203066273b0334b4d6ebbb335b289'), 'backend/naver_page/vendor/report-pdf/Apache-2.0.txt': (420, 11358, 'cfc7749b96f63bd31c3c42b5c471bf756814053e847c10f3eb003417bc523d30'), 'backend/naver_page/vendor/report-pdf/NanumGothic-OFL.txt': (420, 4532, '90f6a909ffb2af7f6422ea20042a26180fe5520cba80bbbf75a5e660320d7924'), 'backend/naver_page/vendor/report-pdf/NanumGothic-Regular.ttf.gz': (420, 697020, '72d1bf88a642ede8ff7da422031106fc697ea4c79b1cfd2994bffc57df4dab07'), 'backend/naver_page/vendor/report-pdf/THIRD-PARTY-NOTICES.txt': (420, 12147, '33588a8c88e8c3f6535dc653bf65840b08dd75b7e7f2beec69d6f5a3542ffa67'), 'backend/naver_page/vendor/report-pdf/fontkit-1.1.1.umd.min.js': (420, 758440, 'd8df561b9fba98e24f2e5130e40948809281bbbc55a20c412359f1a0a5eb35a6'), 'backend/naver_page/vendor/report-pdf/fontkit-LICENSE.txt': (420, 1462, '3b839fbef51e4721ff85ba6c6c79e0d37738f28c28bf90c744d7c4bf9f0eb1a0'), 'backend/naver_page/vendor/report-pdf/js-sha256-LICENSE.txt': (420, 1076, '2153bd2978793748fbe0eb8f838ae2ae19f03f9d4ee5473dd1628a0c0790e4ab'), 'backend/naver_page/vendor/report-pdf/manifest.json': (420, 3008, 'd7b047f71ecf086d422031b4fba80d708a3987fe6635c78e16de82979aa2f3de'), 'backend/naver_page/vendor/report-pdf/pako-LICENSE.txt': (420, 1104, 'a04665b3b2de56c66730c1f720f528175739e4104f79073614aa611da1e85539'), 'backend/naver_page/vendor/report-pdf/pdf-lib-1.17.1.min.js': (420, 525099, '0f9a5cad07941f0826586c94e089d89b918c46e5c17cf2d5a3c6f666e3bc694f'), 'backend/naver_page/vendor/report-pdf/pdf-lib-LICENSE.txt': (420, 1070, 'f2c9fc00fdb66eb99ac156ba52d734af66d8d309f65753ae809ad34ee2883bcb'), 'backend/naver_page/vendor/report-pdf/sha256-1.0.0.min.js': (420, 8156, 'a050d794e170699bd1a69d33908d0942c68901cb88347016064b60b240f0067e'), 'backend/naver_page/vendor/report-pdf/standard-fonts-LICENSE.txt': (420, 1070, '45cc2bb9957ed43f5c7f5eb1912f9f670730394d614079510477cae626194649'), 'backend/naver_page/vendor/report-pdf/upng-LICENSE.txt': (420, 1065, 'c1fb8861eca211bf5aea574358aba7039396c0c1824c2a1477cc126d398efd89'), 'backend/requirements.txt': (420, 144, '0264b07e26f94bc31522b7fcf4801318f21b0d86d74793e6fd9608f8a64ca67c'), 'compose.naver-engine.yml': (420, 2697, '62e33c3d2815579a28031973b956cd36031171f26ead4e21ad2d72adfe2a5ef7'), 'compose.naver-relay.yml': (420, 1514, '00404b84a4377fcb74afc883feff6d2a434b1fca92f0be7b2d399a72ba05da66'), 'deploy/naver-backup-receiver.py': (420, 11383, 'ac324dab4e868477c5c5aceef641e26a2359d45bdde6ac884331de09a208205c'), 'deploy/naver-engine-ad-api.override.yml': (420, 598, '961eddbd2bfe607ac0fe90dc056a7cd09de2a065b942ee0e6c0cc205e1f432fd'), 'deploy/naver-engine-backup.override.yml': (420, 971, 'bfbe6cc3b2a5988071ba067d2b599929deea2ef7d6b8c8644d2aefd236b65a78'), 'deploy/naver-engine-nginx.conf': (420, 2599, 'b26a13f1b7b4f7b5d6ca154333f91b3a92b80348a164544ded2d6e3b8e78e025'), 'deploy/naver-erp-tunnel/OPERATIONS.md': (420, 8186, 'ee50a7dc794d1168b53dff435577595fafb90f11dd2771e77a0e8209aaac37be'), 'deploy/naver-erp-tunnel/ad-ssh.conf': (420, 1385, '1c37f158c26a988973707c36b2f4ccade561c6e1fa93334a12ece8abaf9df0aa'), 'deploy/naver-erp-tunnel/ad-tunnel.service': (420, 1245, 'd6f4698a5aaf53e87bb47e07826503801d4ef49a9a12213d419b1208e33eb35a'), 'deploy/naver-erp-tunnel/authorized_keys.template': (420, 138, '3fab1b741f766435b317325799e50dab985c9f368041b16ca435ed82c1903c3b'), 'deploy/naver-erp-tunnel/be-nginx.conf': (420, 2966, '0c8b4d959203b37892346bcc9796518f95377eaee7e56ff26dee8b01c547d891'), 'deploy/naver-erp-tunnel/be-sshd.conf': (420, 835, '4440431dd03fc52171ee3a8abd9d9ce45500ece0c88e853dfe5537bd30992fc3'), 'deploy/naver-erp-tunnel/test.Dockerfile': (420, 588, '0fa260ab2000c9ea9d7d45330c8256060f7912e3d296bf554c2f4e3fc73b1ee0'), 'deploy/naver-erp-tunnel/test.Dockerfile.dockerignore': (420, 250, '4b7c07b25bf9724ea79620e03d7b40b69ce548dcfe01f478ada8c02c9c2c755a'), 'deploy/naver-erp-tunnel/test_policy.py': (420, 18991, 'e53a165a0a973aacc5a7f8b81c62f6921c88a7f0acabd4992f5521b86c0a7a26'), 'deploy/nginx-ad.metainc.co.kr.conf': (420, 739, '31574f6e1e0dcad25c57fb3f4f183b8f5bfed4b1fb14cd4c7f5f77efac6e89d1'), 'naver_engine/__init__.py': (420, 1077, '83ca0328fd0eb93b016be936321703ae88df5d3410b369df18c5c7290ed6bf74'), 'naver_engine/ad_reasons.py': (420, 5523, '12cb7edc84f8f302036c16677ae51ebbbbc117aa1feba6f58fb32b906501beec'), 'naver_engine/alerts.py': (420, 39621, 'bc4636d8b6f685e02a9305061926299f9fa52f50fbcf6c6e4cb9da8b29d1c35d'), 'naver_engine/approval_documents.py': (420, 7554, '47de41a6c0840710e62b56135593b0c00e99b41053630c3f37b79d2231c17243'), 'naver_engine/automation_views.py': (420, 12728, 'fb1ad696e195123521251deeb9073edee0bab263cc1205df1c4e37940f3223d3'), 'naver_engine/backup.py': (420, 16760, '1bc2561ea3d8cc5f528b64ed275da4ca242fe9a5cf166c6bb53aaf6c0ff3a92e'), 'naver_engine/catalog_links.py': (420, 13417, '2984a7582347cad4580be1f25bdee93146e933222f3b783cc2a1bb5ae6478b7b'), 'naver_engine/collection_diagnostics.py': (420, 4224, '114806cdfb07eeeef2ac365a460e941d2741d6345b165c8428caf4344b2cacd6'), 'naver_engine/credentials.py': (420, 4788, 'f20794c7f89ee29c396fa596ff44c6781bd87872914d08f58b83d15b88df3c84'), 'naver_engine/dashboard.py': (420, 9334, '2c2c86c96f249f133220463f8988b96e07eee795d44dbc844204943370206f15'), 'naver_engine/erp_alert.py': (420, 16095, '55e639ccb747e8e5f34af80e9802e03a0b650c26d06c89531b12ce5b2b8abf92'), 'naver_engine/erp_profile.py': (420, 7315, '108b4ee5d97dfa6174ccca18c5e92e9308976a349c6a648985a7ac45ea75986c'), 'naver_engine/erp_read.py': (420, 22099, '50434c7943a23ab195b2325a74ef977e9d0e0bff02572175b8994536bf7f3cdc'), 'naver_engine/execution_commands.py': (420, 68617, '9def0f8399017376226f3c7ce4477119a9cb19e99a597cbf1f10bbc9066ecc6e'), 'naver_engine/execution_store.py': (420, 76944, '6ab5fd81eb0bab41add10b44bcb630b38e8ebd619fd58a2c5304a69b0c59da44'), 'naver_engine/experiments.py': (420, 41946, 'f99a213727b258aaf88f6769328c2f7a602109466efdbf00a8da33bf7cbad9ff'), 'naver_engine/experiments_reads.py': (420, 29482, '1758861970173d771c805813bc949c77c4559337a0bd7c60416be134513b5ccc'), 'naver_engine/experiments_store.py': (420, 36620, '5e6db883b0ab270a955e90ff5676f61cf0bbc22b4aab348cf968e96a85a6db74'), 'naver_engine/fields.py': (420, 3369, 'a92d4182bad903bb3e5c22519ea93dace5041475bc874967024cc34f5e340a6a'), 'naver_engine/funnel_evidence.py': (420, 13432, '6a25abe8756912cfe130ddb5e99fc26107b34f94ad5c296494e682ebed7f1514'), 'naver_engine/funnel_reads.py': (420, 14000, 'f8959edabea14f723a7c8fa3d40c99a1e0e6740deba31294ca2325e53ed59114'), 'naver_engine/funnel_store.py': (420, 28540, '7df267d9a5d9cb3ee37ea61b6a6b907acc0f2ec9ddc0d7ea070a903778a9fe61'), 'naver_engine/handles.py': (420, 16016, 'fa64d8841f352b413ea12fdb8b88ab53c73133eaf0e91a98d8c586a52e8a8e14'), 'naver_engine/hourly_stats.py': (420, 3181, '287213de98df68c57634e3b6ed454bcb6df6febd12fe22effbb40281f88f2319'), 'naver_engine/inspection_fields.py': (420, 10771, '102028ecb4f35647043b5efc1751e516c92f326252b88c3ab6c983ca7c61ba6a'), 'naver_engine/inspection_reads.py': (420, 23837, '965f5dac65cbf867a6232c5af2d3992a6324b81cc6470e65167e06d674d0e543'), 'naver_engine/inspection_store.py': (420, 29733, '82b368eb9d8122080f24a4fc82007ac38c79f6b7de2c4c42604f02a9c8171cc6'), 'naver_engine/inventory.py': (420, 29075, '2a5c4d5f6acb0b431daa9e16be517322a43008aa636cfdf90c49c4a9305ae28e'), 'naver_engine/inventory_reads.py': (420, 9956, '40892186fddd444f2f8868ea31323744e155d8c59eeb42b3ef6deea482a379e1'), 'naver_engine/learning_assets.py': (420, 40383, '4c3e1d6923eb0396c23e63e18c90c6077623248fc3aa05cb5071684ffde53666'), 'naver_engine/learning_retrieval.py': (420, 9135, 'f4e32d5c458014697d194c077e769ce929f677e98faaf34cc594982f992188ee'), 'naver_engine/learning_source_storage.py': (420, 41649, '144eca9e828c9f73a244b8603bf82758155c351d0586a88b7fcf012126d0935d'), 'naver_engine/links.py': (420, 24837, 'a97b7f293e32f55ac92a7b53c77884fbc50bb7d481212346f85f7dc8ae2db249'), 'naver_engine/management.py': (420, 5723, '84862507d3831053edf618c6d68e800f1f1a1ec4019bcc88030eacb4d14f37e4'), 'naver_engine/management_store.py': (420, 11391, 'e912f5941d9ce61b57327d7ae7d6307086d06570de72bfea4f9ed0cee389af1d'), 'naver_engine/market_evidence.py': (420, 12510, '6ee6ce06477d0c60b798a04e6679beff8ce0e056760e82bef3565764a55075ec'), 'naver_engine/market_store.py': (420, 7284, 'c8d75ab344c5cfb5ba3f034782521a5ae98e75e7083377147eb491c5917570cc'), 'naver_engine/marketing_strategy.py': (420, 84228, '62df719fe988f9c331e82b1324e649a2e481d7817ef32f10efd684cb01e8c12f'), 'naver_engine/metrics.py': (420, 15005, 'f734fa8b2173ff5b59dcd4aeb02e61fbbe77ab23d1cc15ae6ce8441e3548564c'), 'naver_engine/monthly_reads.py': (420, 11994, 'f26214bf881b95be54fca75c941a15cb8f92f667e5af30aa94369e8fda5b7299'), 'naver_engine/morning.py': (420, 48264, 'f6cd9d4c5fd0453dcf77f707313d9c37ff6e01621e1d5f86325423b3adc94ca6'), 'naver_engine/morning_progress.py': (420, 6839, 'c6cb0faf936820a2d93b90985e0aaa1362b1bf3d3a6d98d861212c17366f54b1'), 'naver_engine/naver_read.py': (420, 69880, 'ee1d7412dae83610cbb6c7ba2b812963e69894c706064431606c45d402b96534'), 'naver_engine/naver_write.py': (420, 24439, '68cb76054948950110a85672a05b04818de67bf0cdef8f071324d08b6ad73860'), 'naver_engine/network_observability.py': (420, 1969, '60be59acf1ede301ea93975d6098248f608d738d7178ed8003acb0a326ebe6a5'), 'naver_engine/observation_store.py': (420, 12721, 'af417af3a526f3083a474a4ebbb524bc0abbac13019da5f34fcedb270ce3a5c4'), 'naver_engine/observation_views.py': (420, 3405, 'c0a5f541a97aad0c665b7a4e9cb3ab6fcdedb6eac763320119773d843b359323'), 'naver_engine/observational_inference.py': (420, 15697, 'ff5c9706b4906372f60328c419693fadfee3895cb827bb12c9587323a4b79fb6'), 'naver_engine/operating_criteria.py': (420, 17387, '3bae3f568034d40f76ed65a34bd3b61233e0d0df718ba9db8f9bc9e710fadbe4'), 'naver_engine/performance_reads.py': (420, 18142, '85a863871288640e0a1a6745a10c618cc2e34e13dbb6de2b6fcf9b9040b3798e'), 'naver_engine/product_evidence.py': (420, 13403, '755c97900d34e06ac4a7f46c4ac3aafb3477f5a616cb560bb002f86deac87711'), 'naver_engine/product_store.py': (420, 9723, 'ffc817908ea1ed8a5e05fbc62e4185c7cdd077820199a9f99db15894c9efe303'), 'naver_engine/randomized_execution.py': (420, 11157, 'c3c01e3dbcbafaefb859410a6ecb70c24a81909543b24f48ec0b7bac69d17c86'), 'naver_engine/randomized_experiments.py': (420, 10739, '98a773addae4425cd4e3d7f6c68a3caf6981a76bd465f265cfdf237862e90829'), 'naver_engine/randomized_experiments_reads.py': (420, 8921, '8d5135161638c7a867cec5492c39f6ed4c5261b81a622437836f0b7f4f72122c'), 'naver_engine/randomized_experiments_store.py': (420, 61278, 'a7fbd33eff873d3ac540357c4c3b73b31f096503f7a62efef3b6060dcfc6c547'), 'naver_engine/randomized_inference.py': (420, 18813, '2112f900ae2b9f2188187923deb2f6d6baefcfd6496dc0e5defd4232cbafee58'), 'naver_engine/report_enrichment.py': (420, 20237, 'b151e866f561b93661ef52a7f7470f04d3f616d00de14b7e81bc2db6f5c0e1d1'), 'naver_engine/report_notes.py': (420, 9275, 'dadb0b4b1501a87176a4e85dc8c4b74745c39a48888c1c43dda7044048f04408'), 'naver_engine/report_refresh.py': (420, 7029, '826b8390d7a7b200d1e0449c2c8a1dcaa4e4310bf64bfeab7142998eb111999e'), 'naver_engine/report_schedule.py': (420, 17420, '24a76092fc6420093941fe78f2ce724029fed564c50b3bcce79a8687e0fc58fb'), 'naver_engine/report_schedule_store.py': (420, 24135, 'ae4158824605e129811cd0beefd7ef2cb1cdde4f996c418b70c7de693c9602d0'), 'naver_engine/report_views.py': (420, 17438, '5d6218c1360fee101fb5ec21d036d6047daea11815fc4a1eda66b9e4023c6de2'), 'naver_engine/reporting.py': (420, 25850, '76a7a27ab39f69e9adf4a58547562e00776f6aaa0020df519cb2da8d032bd006'), 'naver_engine/runtime_view.py': (420, 2407, 'a8d78825c16aaa0a3fcc877fdb4a3cfaddc8330154f9331b75eee2cae6c90a4a'), 'naver_engine/sales_views.py': (420, 7905, '885598a9890df6913b54e0d4bf8f2041a18befe5ae319aa0963edb12b5e770f7'), 'naver_engine/session.py': (420, 8455, 'f710ae69062f2ef13c447767fe65ce17c0990aebe65fa6222c4e312129b8e432'), 'naver_engine/setup_checks.py': (420, 34334, '8dc378ab101cc5859c8a05287be5a07d6d59448b9eb913a04627ba7c3e26a7bd'), 'naver_engine/store.py': (420, 445874, 'e63482ff15c5f1fd4f1c26c6119df477aacb708b80751b0617eb9af8ec341b57'), 'naver_engine/structure_reads.py': (420, 14811, 'fed780a4903a099b540cc4eb6b9419ee84cbfdbd26056ad1c338a5db23d71c22'), 'naver_engine/sync.py': (420, 24402, '7ddd57ccce8a8edcf13e3d4495d748d122b067e1bba32becfa6326a4dda32dad'), 'naver_engine/view_sync.py': (420, 5380, '57c97bb82d78dc25277cdd7f5ea23c1512be0cfd0279a837e1e64d0b317a4034'), 'naver_engine/views.py': (420, 64063, 'bfa0f4998153abe01ffeb7d646653db6b4d39b8f4409e09e23002424a60fafb9'), 'naver_engine/web.py': (420, 123506, '348ce74c1d4b7f523fabcf5de9516ed79057a0a1520211753e83fe8e1dcfb149'), 'naver_runtime/__init__.py': (420, 105, '27d28d6ed467edc27f1b22a7a3fedd78253d562938c3cf060ea2573ef38038ec'), 'naver_runtime/__main__.py': (420, 16221, 'de4215ea9b64ca6a2643d1b6ea7abaa11ef63ae130bb2da1ea8e03bab62e3e3d'), 'naver_runtime/backup_transport.py': (420, 5364, 'b14520d0f46429ea93a3158b664ca7f5cb37e378ce146e684cd276265f92db71'), 'naver_runtime/bootstrap.py': (420, 12709, 'dd7f5949eee28e0391608670b3f00a40c30e6b461a3589bf47fcc7b49c5dd504'), 'naver_runtime/claude_provider.py': (420, 45467, '6325f4bf3aa3c95009fb3fe1e2ee4778b8356784aa478091f04166a57c209982'), 'naver_runtime/collection_requests.py': (420, 6497, '1e7606023cdbd27826b0f0e4e07a3f0f6fa4955d6d00396a1af33e7f62526660'), 'naver_runtime/config.py': (420, 6216, 'ee3f1bdd0959ebc7a729de431518200d7eb58dce5f8580936b0ad5ec12bf7fa1'), 'naver_runtime/erp_tunnel_transport.py': (420, 10072, '59d1c40300c416b40d022ce6d1d91cdc9ac3d4a3b981c260ca3002e919bd3288'), 'naver_runtime/learning_jobs.py': (420, 5884, '724b4840a6b33da22d2291e5a8066a80d4a13f15d7d6952ce60735d266028802'), 'naver_runtime/learning_provider.py': (420, 6364, '736d97270bf6a22a916fade9959710c761b09eaea5e8db8fd58bbb60f30849a2'), 'naver_runtime/market_export.py': (420, 2464, '6faef9473ebb38f609a58b7657f86e7c32a3d44d446e2e546392ac8eea3dafb0'), 'naver_runtime/network_observability.py': (420, 2741, 'da1c9f7778ab68142e64e1aaaa21d82514a0852df031deb015dc165f0d48ffbf'), 'naver_runtime/observation_binding.py': (420, 1342, 'f4de2e326ff799c3a7730f71c942011911c14ed4ce9bd051742d7adcf6bbc326'), 'naver_runtime/product_export.py': (420, 2467, 'e22619d2e1030b4e3d3cb6325e636198eeddc3041412dfe1ae937f5c487ee6fa'), 'naver_runtime/provider_observability.py': (420, 16225, '16bcf67ff4c43b71843f6c94ca95982f12c00b76764b94e500070b5f9691f814'), 'naver_runtime/report_schedule_jobs.py': (420, 9356, 'a88ede0467ed6f097f8a9bca818e88eb3107e7c28ddccbddb2a670115349334a'), 'naver_runtime/restore_check.py': (420, 5657, '0f7c392155b9fdcb602307b7bd5771c211ca9f6774f5dcfa8106f940bb7905b9'), 'naver_runtime/runtime_status.py': (420, 6149, 'f08633202d21248dde7c62c2d6bdb42a40b981721df958b0124fc7009b4da8eb'), 'naver_runtime/scheduler.py': (420, 36880, 'f7920b79c0339acf7c619222a46fd9056d73822445cd69966802f261e1e07d41'), 'naver_runtime/server.py': (420, 6425, 'bf17856d256bf672aa4f50d8d9bf4b2557cec9a2aed7f1a0f5f97eee81ca8007'), 'naver_runtime/writer.py': (420, 15964, 'f4825faa816f2001a3902d9828bdf0dc1086467c4a56b89cf7ee4c5425ca5e26')}
CI_PROOF = {'source_commit': 'e7649acfc71c25d7ae9c981a6ba036b77d97897b', 'tooling_head': 'ba4097bb199e83cbdf6e6a0904a777df6bfcc921', 'run_id': '38187950344', 'receipt_sha256': '822daed24e0c7be7d23ceb586316adc73598a514a76407bdff77a42d2c4d39d8'}
OLD_SCHEMA = 11
TARGET_SCHEMA = 21
RANDOMIZED_TABLES = frozenset('''
naver_randomized_experiment naver_randomized_history naver_randomized_receipt
naver_randomized_block naver_randomized_command naver_randomized_switch
naver_randomized_switch_event naver_randomized_probe naver_randomized_job
naver_randomized_observation naver_randomized_result naver_randomized_scan_cursor
'''.split())
DATA = Path('/var/lib/metainc/naver-engine')
ADDED_SOURCE_PATHS = frozenset()
ENGINE_COMPOSE_SHA256 = '62e33c3d2815579a28031973b956cd36031171f26ead4e21ad2d72adfe2a5ef7'
TEST_PATHS = frozenset()
REMOVABLE_SOURCE_PREFIXES = ()
OWNER_ACTION_ROUTES = ('/issues/1/ack', '/issues/1/resolve', '/issues/1/except', '/bell/1/read', '/bell/read-all',
    '/settings/thresholds', *('/holds/'+k+'/confirm' for k in ('org', 'stages', 'accounts')), '/links/revoke')
TARGET_ACTION_ROUTES = ('/reports/notes', '/reports/strategy', '/automation/plans', '/automation/learning')
CLOSED_LINK_ROUTES = ('/links/reject', '/links/preview')
OLD_REPORT_UI = (89541, '24aba1490a188ab52e6cb22a412030ef42ed1d89da356cdea595f314180e6ead', 'text/javascript; charset=utf-8')
OLD_APP = (222000, 'f119f80f3fac01de107f7ce45a2ed39f5443dfc4a79db8f8c67ad06678549078', 'text/javascript; charset=utf-8')
SALES_GET_ROUTES = ('/sales/clients', '/sales/detail', '/sales/report')
OLD_REPORT_ASSETS = {'/naver/sso-bootstrap.js': (4588, 'b32369913287c49fa43fa210db73742f51c203066273b0334b4d6ebbb335b289', 'text/javascript; charset=utf-8'), '/naver/report-ui.js': (89541, '24aba1490a188ab52e6cb22a412030ef42ed1d89da356cdea595f314180e6ead', 'text/javascript; charset=utf-8'), '/naver/report-pdf.js': (37921, '454ccb5f20b3a8f125ac9f1e1cc765041a0d23e8a881fa11ccbfea5b5c848964', 'text/javascript; charset=utf-8'), '/naver/sales-ui.js': (17774, '00553781030990970c88dcd6d86c11730cf9c60cf9ce7a7963f2b091cd5aa2ff', 'text/javascript; charset=utf-8'), '/naver/automation-ui.js': (22976, '0828746fd2c60d43dd9e6f448782d1c46d543ecf2eb243590df8130ac5f6d2d3', 'text/javascript; charset=utf-8'), '/naver/learning-ui.js': (23619, '9cae047e4cf163d20e9e597df364da3565c88ed622b4cfe2d6ab651a1274ef7e', 'text/javascript; charset=utf-8'), '/naver/app.js': (222000, 'f119f80f3fac01de107f7ce45a2ed39f5443dfc4a79db8f8c67ad06678549078', 'text/javascript; charset=utf-8'), '/naver/app.css': (57115, '82174f6c25649692b68df439bb8f61329a218f6d052e77b8e9b0e9dd1970bee7', 'text/css; charset=utf-8'), '/naver/sales.css': (5905, 'f27843cb1e1e63a41d85f5f794035f47c62ec72dda5971f95dd9ed58226ba09d', 'text/css; charset=utf-8'), '/naver/vendor/report-pdf/NanumGothic-Regular.ttf.gz': (697020, '72d1bf88a642ede8ff7da422031106fc697ea4c79b1cfd2994bffc57df4dab07', 'application/gzip'), '/naver/vendor/report-pdf/pdf-lib-1.17.1.min.js': (525099, '0f9a5cad07941f0826586c94e089d89b918c46e5c17cf2d5a3c6f666e3bc694f', 'text/javascript; charset=utf-8'), '/naver/vendor/report-pdf/fontkit-1.1.1.umd.min.js': (758440, 'd8df561b9fba98e24f2e5130e40948809281bbbc55a20c412359f1a0a5eb35a6', 'text/javascript; charset=utf-8'), '/naver/vendor/report-pdf/sha256-1.0.0.min.js': (8156, 'a050d794e170699bd1a69d33908d0942c68901cb88347016064b60b240f0067e', 'text/javascript; charset=utf-8')}
REPORT_ASSETS = {'/naver/app.css': (59087, '296efe6a624ada65affaf2397d2dd55356917bcdc540f6f4f4eddfacee17a5dd', 'text/css; charset=utf-8'), '/naver/app.js': (223505, '8a4daa3a0dbaa9ae61434c8dac223bdb47a3ed0b9106c7c324b4aa8260f25ab3', 'text/javascript; charset=utf-8'), '/naver/automation-ui.js': (46840, '2997ab9abd54474c913e56189e8c7bbcf0a5a9e6fb8550e331b9dd338bee03f8', 'text/javascript; charset=utf-8'), '/naver/execution-ui.js': (54585, 'a6febc90e4fda776a1a4f5f666304993484edb540b82f059335221edfeb6a6d1', 'text/javascript; charset=utf-8'), '/naver/experiments-ui.js': (62774, '043d513b2611ecc620bbfe7143231d4c4951a52a2ddac9150e36b49f3ba69d4e', 'text/javascript; charset=utf-8'), '/naver/learning-ui.js': (51105, '28dcb6b7f923048d90ae5ef86e0664c4bfbc7d2b127bc41f2e46ee0a79c0f340', 'text/javascript; charset=utf-8'), '/naver/operations-ui.js': (12286, '02b756eaa66ec7e5d8a0939473953ec7a639d59e3e23f4dd8c34715b43880008', 'text/javascript; charset=utf-8'), '/naver/randomized-experiments-ui.js': (36703, 'c3b0096f8e36cc41136f5b9fd0cb21c4b66a19e4b6765c15c92092e81a7b7f1a', 'text/javascript; charset=utf-8'), '/naver/report-pdf.js': (40388, '03445e5236b80669395d48cc1ebef52dafaf372e84bade035193496c7d6e3867', 'text/javascript; charset=utf-8'), '/naver/report-schedule-ui.js': (15440, '84beb5cdf5368a706dc85ee20f2666f7108e83724b131c5f7d43bd62ece94b99', 'text/javascript; charset=utf-8'), '/naver/report-ui.js': (102575, 'f9121aa9fe2d4a82bfcc3d7712d81e0fd043447210ab08ac726a4f2be65cbed8', 'text/javascript; charset=utf-8'), '/naver/sales-ui.js': (17774, '00553781030990970c88dcd6d86c11730cf9c60cf9ce7a7963f2b091cd5aa2ff', 'text/javascript; charset=utf-8'), '/naver/sales.css': (5905, 'f27843cb1e1e63a41d85f5f794035f47c62ec72dda5971f95dd9ed58226ba09d', 'text/css; charset=utf-8'), '/naver/sso-bootstrap.js': (4588, 'b32369913287c49fa43fa210db73742f51c203066273b0334b4d6ebbb335b289', 'text/javascript; charset=utf-8'), '/naver/vendor/report-pdf/NanumGothic-Regular.ttf.gz': (697020, '72d1bf88a642ede8ff7da422031106fc697ea4c79b1cfd2994bffc57df4dab07', 'application/gzip'), '/naver/vendor/report-pdf/fontkit-1.1.1.umd.min.js': (758440, 'd8df561b9fba98e24f2e5130e40948809281bbbc55a20c412359f1a0a5eb35a6', 'text/javascript; charset=utf-8'), '/naver/vendor/report-pdf/pdf-lib-1.17.1.min.js': (525099, '0f9a5cad07941f0826586c94e089d89b918c46e5c17cf2d5a3c6f666e3bc694f', 'text/javascript; charset=utf-8'), '/naver/vendor/report-pdf/sha256-1.0.0.min.js': (8156, 'a050d794e170699bd1a69d33908d0942c68901cb88347016064b60b240f0067e', 'text/javascript; charset=utf-8')}
APPROVED_CONFIG_OPERATION_ID = '74c912dddf824fae99012849bc4c19a5'
CONFIG_SOURCE_COMMIT = '9ddb0a30e16e4177e8d419318a6f23eb6c206e2f'
CONFIG_ROLLBACK_COMMIT = '09b216f26509fed97179114ee97cb0d4169ce5f8'
CONFIG_SETTINGS = {'NAVER_CLAUDE_ENABLED': 'true', 'CLAUDE_MODEL': 'claude-sonnet-5-5',
    'NAVER_CLAUDE_MONTHLY_CAP_USD': 'unlimited', 'NAVER_CLAUDE_INPUT_USD_PER_MILLION': '2',
    'NAVER_CLAUDE_OUTPUT_USD_PER_MILLION': '10', 'NAVER_CLAUDE_TIMEOUT_SECONDS': '20'}
STAGE = 'input'
OPERATION = 'none'
FAILURE_STAGES = frozenset('input code_apply_preflight code_stop_isolated account_database_snapshot '
    'account_sources_warm code_recreate code_replace_units code_start code_verify code_rollback'.split())
FAILURE_OPERATIONS = frozenset('none package current_state target_manifest compatible_source unit_manifest '
    'write_recovery_receipt bootstrap_check snapshot_directory snapshot_identity snapshot_lock snapshot_create '
    'snapshot_schema snapshot_copy snapshot_integrity snapshot_fsync snapshot_digest warm_sources warm_create '
    'warm_wait warm_logs warm_result warm_cleanup_find warm_cleanup_identity warm_cleanup_remove '
    'warm_cleanup_absence warm_config warm_store_open warm_schema warm_org_sync warm_org_contract warm_accounts_sync '
    'warm_catalog_sync warm_summary daemon_reload verify_running post_state write_started_receipt restore_database '
    'old_manifest rollback_schema rollback_state'.split()) | frozenset(prefix+'_'+name for prefix in
        ('stop','stop_check','recreate','replace_unit','start','restore_unit') for name in ('engine','relay'))
FAILURE_KINDS = frozenset('ValueError RuntimeError TimeoutError TimeoutExpired CalledProcessError OSError '
    'PermissionError FileNotFoundError BlockingIOError JSONDecodeError OperationalError IntegrityError '
    'TypeError KeyError AttributeError AssertionError ImportError ModuleNotFoundError ConfigError StoreRefused'.split())
FAILURE_KINDS |= frozenset({'ExportInstallInvalid', 'FileExistsError'})
SQL_ERRORS={n:'SQLITE_'+s for n,s in zip((1,5,6,8,10,11,14,15,26),'ERROR BUSY LOCKED READONLY IOERR CORRUPT CANTOPEN PROTOCOL NOTADB'.split())}
M_PHASES=frozenset('rows_before apply_first apply_repeat schema_after rows_after integrity'.split())
M_KINDS=FAILURE_KINDS|{'StoreError','DatabaseError','OtherError'}
M_SQL={number:'SQLITE_'+name for number,name in enumerate(
    'ERROR INTERNAL PERM ABORT BUSY LOCKED NOMEM READONLY INTERRUPT IOERR CORRUPT NOTFOUND FULL CANTOPEN '
    'PROTOCOL EMPTY SCHEMA TOOBIG CONSTRAINT MISMATCH MISUSE NOLFS AUTH FORMAT RANGE NOTADB NOTICE WARNING'.split(),1)}
M_CODES=frozenset('DB_OLD_SCHEMA DB_TARGET_SCHEMA DB_ROWS_CHANGED DB_SCHEMA_OBJECT DB_ROW_BOUND DB_SNAPSHOT_INTEGRITY'.split())
FAILURE_OPERATIONS |= M_PHASES
FAILURE_KINDS = M_KINDS
FAILURE_CODES = frozenset(SQL_ERRORS.values()) | frozenset('CODE_TARGET_NOT_PINNED CODE_PACKAGE CODE_TARGET CODE_BASELINE CODE_APPLY_FIELDS '
    'CODE_OPERATION_ID CODE_ALREADY_ATTEMPTED CODE_POST_STATE CODE_TARGET_SOURCE_CHANGED CODE_FAILED_ROLLED_BACK_DB_PRESERVED '
    'CODE_ROLLBACK_FAILED HOST_BASELINE OLD_BASELINE OLD_SOURCE_CHANGED OLD_UNIT_CHANGED OLD_UNIT_NOT_ENABLED '
    'DEPENDENCY_NOT_ACTIVE BOOTSTRAP_REQUEST BOOTSTRAP_NOT_FINISHED BOOTSTRAP_CHANGED TMPFILES_CHANGED '
    'CODE_INFRASTRUCTURE_CHANGED CODE_SCHEMA_CHANGED CODE_STORE_CHANGED CODE_OVERRIDE_CHANGED CODE_SOURCE_PATH CODE_SOURCE_MODE_CHANGED '
    'CODE_SOURCE_REMOVED CODE_SCOPE_CHANGED SCHEMA_CONTRACT_MISSING CODE_PROBE_SOURCE CODE_ROUTE_STATUS '
    'CODE_SERVICE_NOT_ACTIVE CODE_SERVICE_NOT_ENABLED VERIFIED_WRITE_AUTH_NOT_REQUIRED '
    'ACCOUNT_WRITER_NOT_STOPPED DB_IDENTITY DB_OLD_SCHEMA DB_TARGET_SCHEMA DB_SNAPSHOT_INTEGRITY DB_SNAPSHOT_CHANGED '
    'WARM_CONTAINER_ID WARM_CONTAINER_REMAINS WARM_CREATE_UNCONFIRMED WARM_CLEANUP_FAILED SOURCE_WARM_FAILED '
    'ORG_NOT_ACCEPTED MANAGEMENT_FIELD_MISSING ACCOUNTS_NOT_ACCEPTED CATALOG_NOT_ACCEPTED '
    'COMMAND_FAILED DIRECTORY_POLICY FILE_PATH FILE_POLICY PREPARED_MANIFEST PREPARED_DIGEST '
    'PREPARED_FILE_CHANGED PREPARED_IMAGE PREPARED_IMAGE_CHANGED SOURCE_NOT_READY UNIT_CHANGED ENGINE_NOT_READY '
    'PAGE_NOT_READY REPORT_ASSET_NOT_READY UNAUTHENTICATED_READ_NOT_DENIED BUSINESS_WRITE_NOT_DENIED SERVICES_NOT_READY'.split())
FAILURE_CODES |= frozenset(M_SQL.values())
FAILURE_CODES |= frozenset({'CODE_ONLY_REQUIRED', 'PROBE_RESPONSE_SIZE'})
FAILURE_CODES |= frozenset({'RUNTIME_SECRET_CHANGED', 'CONFIG_PRESERVE_NOT_APPROVED', 'CONFIG_PRESERVE_PROOF', 'CONFIG_PRESERVE_DRIFT'})
FAILURE_STAGES |= frozenset({'code_prepare_runtime_config', 'code_prepare_runtime_postflight'})
FAILURE_STAGES |= frozenset({'code_prepare_preflight', 'code_build_engine', 'code_build_relay',
    'code_config_engine', 'code_config_relay', 'code_check_config', 'code_prepare_postflight'})
FAILURE_CODES |= frozenset({'EXECUTION_ENABLED', 'RUNTIME_CONFIG_PROOF', 'RUNTIME_CONFIG_DRIFT'})
FAILURE_OPERATIONS |= frozenset({'runtime_config_preflight', 'runtime_old_config', 'runtime_stopped_config', 'runtime_target_config'})
# Keep this reviewed set exact; an EXPORT_ prefix never makes an error public.
EXPORT_FAILURE_CODES = frozenset('EXPORT_ALREADY_ATTEMPTED EXPORT_BUNDLE_INVALID EXPORT_BUNDLE_STALE '
    'EXPORT_COMMAND_FAILED EXPORT_DATABASE_NAME EXPORT_DIRECTORY_POLICY EXPORT_FILE_CHANGED EXPORT_FILE_POLICY '
    'EXPORT_IDENTITY EXPORT_IDENTITY_CHANGED EXPORT_INSTALLED_CHANGED EXPORT_INSTALL_CONFLICT EXPORT_JOURNAL '
    'EXPORT_OPERATION EXPORT_OUTPUT_CONFLICT EXPORT_PATH EXPORT_PIN EXPORT_PREPARED_CHANGED EXPORT_PROFILE '
    'EXPORT_PYTHON EXPORT_RECEIPT EXPORT_ROLLBACK_DRIFT EXPORT_ROOT_REQUIRED EXPORT_RUN_NOT_VERIFIED '
    'EXPORT_SOURCE_CHANGED EXPORT_SOURCE_PATH EXPORT_SOURCE_SCOPE EXPORT_SOURCE_SYMLINK EXPORT_SYMLINK EXPORT_TIME'.split())
FAILURE_CODES |= EXPORT_FAILURE_CODES
FAILURE_STAGES |= frozenset({'saved_exports_binding', 'saved_exports_prepare', 'saved_exports_install'})
EXPORT_COMMAND_STAGES = frozenset('unit_verify daemon_reload product_start market_start product_enable '
    'market_enable product_show market_show product_enabled market_enabled product_active market_active '
    'product_disable market_disable product_stop market_stop unknown'.split())
EXPORT_COMMAND_ISSUES = frozenset('permission_denied missing_file disk_full unit_syntax namespace readonly '
    'sqlite_open python_import command_timeout command_failed unknown'.split())

CONFIG_SWITCHES = frozenset('sync links morning alerts metrics inventory execution backup web issue_alerts'.split())
CHECK_CONFIG_FIELDS = frozenset('command configuration switches network_performed storage_opened credentials_verified web_available deployment_ready'.split())
ENV_FLAGS_SCRIPT = '''import json,os
def flag(name):
 value=os.environ.get(name,'false').strip().lower()
 if value in ('false','off','0',''):return False
 if value in ('true','on','1'):return True
 raise SystemExit(2)
print(json.dumps({'inventory_enabled':flag('NAVER_ENGINE_INVENTORY_ENABLED'),'execution_enabled':flag('NAVER_ENGINE_EXECUTION_ENABLED')},separators=(',',':')))
'''


def runtime_flags(raw, *, environment=False):
    """Accept only a bounded, closed boolean proof; never return raw config."""
    def unique(pairs):
        value = {}
        for key, item in pairs:
            if key in value:
                raise ValueError('RUNTIME_CONFIG_PROOF')
            value[key] = item
        return value
    def invalid_constant(_):
        raise ValueError('RUNTIME_CONFIG_PROOF')
    if type(raw) is not bytes or not 1 <= len(raw) <= 4096:
        raise ValueError('RUNTIME_CONFIG_PROOF')
    try:
        value = json.loads(raw, object_pairs_hook=unique, parse_constant=invalid_constant)
    except (ValueError, TypeError, UnicodeError, RecursionError):
        raise ValueError('RUNTIME_CONFIG_PROOF') from None
    if environment:
        if (type(value) is not dict or set(value) != {'inventory_enabled', 'execution_enabled'}
                or any(type(v) is not bool for v in value.values())):
            raise ValueError('RUNTIME_CONFIG_PROOF')
        result = value
    else:
        if (type(value) is not dict or set(value) != CHECK_CONFIG_FIELDS
                or value['command'] != 'check-config' or value['configuration'] != 'valid'
                or any(value[k] is not False for k in CHECK_CONFIG_FIELDS-{'command','configuration','switches'})
                or type(value['switches']) is not dict or set(value['switches']) != CONFIG_SWITCHES
                or any(type(v) is not bool for v in value['switches'].values())):
            raise ValueError('RUNTIME_CONFIG_PROOF')
        result = {'inventory_enabled':value['switches']['inventory'], 'execution_enabled':value['switches']['execution']}
    if result['execution_enabled'] is not False:
        raise ValueError('EXECUTION_ENABLED')
    return dict(result)


def target_runtime_flags(path, release, identity, *, override=None):
    """Same target compose/env, with networking disabled and no runtime startup."""
    check = release.compose(path, 'engine')
    check[check.index('--project-name')+1] = 'naver-check-'+TARGET_COMMIT+'-'+uuid.uuid4().hex
    created = override is None
    if created:
        override = release.ROOT/'receipts'/('completion-config-'+identity+'-'+uuid.uuid4().hex+'.override.yml')
        release.write_new(override, b'services:\n  naver-engine:\n    network_mode: none\n')
    try:
        raw = release.command(check+['-f',str(override),'run','--rm','--no-deps','--pull','never',
            'naver-engine','python','-B','-m','naver_runtime','check-config'], timeout=60)
        return runtime_flags(raw)
    finally:
        if created:
            override.unlink()


def container_environment_flags(raw):
    """Reduce private immutable Docker Env in memory to the two safe flags only."""
    if type(raw) is not bytes or not 1 <= len(raw) <= 65536:
        raise ValueError('RUNTIME_CONFIG_PROOF')
    try:
        values = json.loads(raw)
        if type(values) is not list or len(values) > 256:
            raise ValueError('RUNTIME_CONFIG_PROOF')
        selected = {}
        names = {'NAVER_ENGINE_INVENTORY_ENABLED':'inventory_enabled',
            'NAVER_ENGINE_EXECUTION_ENABLED':'execution_enabled'}
        for item in values:
            if type(item) is not str or '\x00' in item:
                raise ValueError('RUNTIME_CONFIG_PROOF')
            name, separator, value = item.partition('=')
            if name not in names:
                continue
            if not separator or name in selected:
                raise ValueError('RUNTIME_CONFIG_PROOF')
            lowered = value.strip().lower()
            if lowered not in ('false','off','0','','true','on','1'):
                raise ValueError('RUNTIME_CONFIG_PROOF')
            selected[name] = lowered in ('true','on','1')
        flags = {public:selected.get(name,False) for name,public in names.items()}
    except (ValueError, TypeError, UnicodeError, RecursionError):
        raise ValueError('RUNTIME_CONFIG_PROOF') from None
    return runtime_flags(json.dumps(flags,separators=(',',':')).encode(),environment=True)


def target_engine_snapshot(path, receipt, release, lifecycle, *, stopped):
    """Bound one actual target container without inspecting or returning secrets."""
    if (path.name != 'naver-'+TARGET_COMMIT or receipt.get('source_commit') != TARGET_COMMIT
            or not isinstance(receipt.get('images'),dict)
            or not isinstance(receipt['images'].get('engine'),str)
            or re.fullmatch('sha256:[0-9a-f]{64}',receipt['images']['engine']) is None):
        raise ValueError('RUNTIME_CONFIG_PROOF')
    if stopped and (lifecycle._state(release,lifecycle.UNITS[0],'ActiveState') not in ('inactive','failed')
            or lifecycle._state(release,lifecycle.UNITS[0],'SubState') not in ('dead','failed')
            or lifecycle._state(release,lifecycle.UNITS[0],'MainPID') != '0'):
        raise ValueError('ACCOUNT_WRITER_NOT_STOPPED')
    raw = release.command(release.compose(path,'engine')+['ps','--all','--quiet'],timeout=30)
    if type(raw) is not bytes or len(raw) > 256:
        raise ValueError('RUNTIME_CONFIG_PROOF')
    try:
        identities = raw.decode('ascii').strip().splitlines()
    except UnicodeError:
        raise ValueError('RUNTIME_CONFIG_PROOF') from None
    if len(identities) != 1 or re.fullmatch('[0-9a-f]{64}',identities[0]) is None:
        raise ValueError('RUNTIME_CONFIG_PROOF')
    fields = {'id':'.Id','image':'.Image','running':'.State.Running',
        'restarting':'.State.Restarting','pid':'.State.Pid',
        'source':'(index .Config.Labels "metainc.naver.preview.source")',
        'project':'(index .Config.Labels "com.docker.compose.project")',
        'service':'(index .Config.Labels "com.docker.compose.service")'}
    fmt = '{'+','.join(json.dumps(k)+':{{json '+v+'}}' for k,v in fields.items())+'}'
    raw = release.command(['docker','inspect','--format',fmt,identities[0]],timeout=30)
    if type(raw) is not bytes or not 1 <= len(raw) <= 4096:
        raise ValueError('RUNTIME_CONFIG_PROOF')
    try:
        row = json.loads(raw)
    except (ValueError, TypeError, UnicodeError, RecursionError):
        raise ValueError('RUNTIME_CONFIG_PROOF') from None
    if (type(row) is not dict or set(row) != set(fields) or row['id'] != identities[0]
            or row['image'] != receipt['images']['engine'] or row['source'] != TARGET_COMMIT
            or row['project'] != 'naver-engine' or row['service'] != 'naver-engine'
            or row['running'] is not (not stopped) or row['restarting'] is not False
            or type(row['pid']) is not int or (row['pid'] != 0 if stopped else row['pid'] <= 0)):
        raise ValueError('RUNTIME_CONFIG_DRIFT')
    return row


def stopped_container_runtime_flags(path, receipt, release, lifecycle):
    before = target_engine_snapshot(path,receipt,release,lifecycle,stopped=True)
    # Docker Env may contain secrets. It stays transient server memory: never hash,
    # log, persist, or include it in any receipt or returned proof.
    flags = container_environment_flags(release.command(
        ['docker','inspect','--format','{{json .Config.Env}}',before['id']],timeout=30))
    if target_engine_snapshot(path,receipt,release,lifecycle,stopped=True) != before:
        raise ValueError('RUNTIME_CONFIG_DRIFT')
    return flags,before


def container_runtime_flags(path, receipt, release, lifecycle, *, target=False, expected=None):
    """Inspect only the already-verified exact engine container's safe flags."""
    before = lifecycle._snapshot(release, path, receipt['images'])
    identity = before.get('engine',{}).get('id')
    if not isinstance(identity,str) or re.fullmatch('[0-9a-f]{64}',identity) is None:
        raise ValueError('RUNTIME_CONFIG_PROOF')
    if expected is not None:
        actual = target_engine_snapshot(path,receipt,release,lifecycle,stopped=False)
        identity_fields = ('id','image','source','project','service')
        if (not target or actual['id'] != identity or type(expected) is not dict
                or any(actual[key] != expected.get(key) for key in identity_fields)):
            raise ValueError('RUNTIME_CONFIG_DRIFT')
    command = (['python','-B','-m','naver_runtime','check-config'] if target else
        ['python','-I','-B','-c',ENV_FLAGS_SCRIPT])
    flags = runtime_flags(release.command(['docker','exec',identity]+command, timeout=60), environment=not target)
    if lifecycle._snapshot(release, path, receipt['images']) != before:
        raise ValueError('RUNTIME_CONFIG_DRIFT')
    if expected is not None and target_engine_snapshot(path,receipt,release,lifecycle,stopped=False) != actual:
        raise ValueError('RUNTIME_CONFIG_DRIFT')
    return flags


CONFIG_PREDECESSOR_COMMIT = OLD_COMMIT
CONFIG_PREDECESSOR_ARCHIVE = OLD_SOURCE_SHA256
CONFIG_PREDECESSOR_PREPARE_RUN = '38128651317'
CONFIG_PRESERVATION_CHAIN = (
    ('10a46ddce2116e274e27fabaf73c7a94be6cda62', '6a2a1075b1b2c31f47d45d8afdd080e8da786e49c3fdf173e82e51c0a3e3705c', '38122455056', CONFIG_SOURCE_COMMIT),
    ('da8e1c071f848898b8857221ac3d618786b5d0b7', 'bbf90eaf2b9377e58739bfa8038f3d43478c0150786e0d2c4745354eebc64e6f', '38126684468', '10a46ddce2116e274e27fabaf73c7a94be6cda62'),
    (CONFIG_PREDECESSOR_COMMIT, CONFIG_PREDECESSOR_ARCHIVE, CONFIG_PREDECESSOR_PREPARE_RUN, 'da8e1c071f848898b8857221ac3d618786b5d0b7'),
)

def preserve_approved_config(files, operation_id, active, release, upgrade):
    """Resolve one historical env against its committed server-local transaction.

    No environment, manifest, envelope, or journal is written. The authenticated
    ciphertext and six-field package retain their original identity. Only the
    verified runtime.env comparison value changes in memory; three other secrets
    keep the ordinary byte comparison. All proof bytes remain server-local.
    """
    if operation_id != APPROVED_CONFIG_OPERATION_ID or OLD_COMMIT != CONFIG_PREDECESSOR_COMMIT:
        raise ValueError('CONFIG_PRESERVE_NOT_APPROVED')
    root = release.ROOT / 'claude-config'
    folder = root / APPROVED_CONFIG_OPERATION_ID
    for parent in (root, folder):
        if parent.resolve() != parent:
            raise ValueError('CONFIG_PRESERVE_PROOF')
        release.trusted_dir(parent, mode=0o700)
    read = lambda path: upgrade.read_file(path, mode=0o600, maximum=32768)
    journal_body = read(folder / 'journal.json')
    journal = json.loads(journal_body, object_pairs_hook=release.unique)
    paths = [release.SECRET_ROOT / 'runtime.env'] + [release.ROOT / 'receipts' / ('preview-' + source + '.json')
        for source in (CONFIG_SOURCE_COMMIT, CONFIG_ROLLBACK_COMMIT)]
    if (not isinstance(journal, dict) or set(journal) != {'schema', 'operation_id', 'source_commit',
            'rollback_commit', 'baseline', 'state', 'files', 'images', 'before'} or type(journal['schema']) is not int
            or journal['schema'] != 1 or journal['operation_id'] != APPROVED_CONFIG_OPERATION_ID
            or journal['source_commit'] != CONFIG_SOURCE_COMMIT or journal['rollback_commit'] != CONFIG_ROLLBACK_COMMIT
            or journal['baseline'] != EXPECTED_BASELINE or journal['state'] != 'committed'
            or not isinstance(journal['images'], dict)
            or set(journal['images']) != {'engine', 'relay'} or not isinstance(journal['before'], dict)
            or set(journal['before']) != {'engine', 'relay'} or not isinstance(journal['files'], list)
            or len(journal['files']) != 3):
        raise ValueError('CONFIG_PRESERVE_PROOF')
    for name, image in journal['images'].items():
        before = journal['before'][name]
        if (not isinstance(image, str) or not re.fullmatch('sha256:[0-9a-f]{64}', image)
                or not isinstance(before, dict) or set(before) != {'id', 'image', 'running', 'started', 'restarts', 'project', 'service'}
                or not isinstance(before['id'], str) or not re.fullmatch('[0-9a-f]{64}', before['id'])
                or before['image'] != image or before['running'] is not True or type(before['restarts']) is not int
                or before['restarts'] != 0 or not isinstance(before['started'], str) or not before['started']
                or before['project'] != 'naver-' + name or before['service'] != 'naver-' + name):
            raise ValueError('CONFIG_PRESERVE_PROOF')
    historical_path, historical = upgrade.manifest(release, CONFIG_SOURCE_COMMIT, started=True)
    if journal['images'] != historical['images']:
        raise ValueError('CONFIG_PRESERVE_PROOF')
    old, new = [], []
    for index, (row, path) in enumerate(zip(journal['files'], paths)):
        if (not isinstance(row, dict) or set(row) != {'path', 'old', 'new'} or row['path'] != str(path)
                or any(not isinstance(row[key], str) or not re.fullmatch('[0-9a-f]{64}', row[key]) for key in ('old', 'new'))):
            raise ValueError('CONFIG_PRESERVE_PROOF')
        old.append(read(folder / ('old-' + str(index))))
        new.append(read(folder / ('new-' + str(index))))
        if hashlib.sha256(old[-1]).hexdigest() != row['old'] or hashlib.sha256(new[-1]).hexdigest() != row['new']:
            raise ValueError('CONFIG_PRESERVE_PROOF')
        if read(path) != new[-1]:
            raise ValueError('CONFIG_PRESERVE_DRIFT')
    allowed = {key.encode() for key in CONFIG_SETTINGS} | {b'ANTHROPIC_API_KEY'}
    unrelated = lambda body: b''.join(line for line in body.splitlines(keepends=True) if line.split(b'=', 1)[0] not in allowed)
    if (b'\x00' in old[0] or b'\x00' in new[0] or not old[0].endswith(b'\n') or not new[0].endswith(b'\n')
            or unrelated(old[0]) != unrelated(new[0])):
        raise ValueError('CONFIG_PRESERVE_PROOF')
    configured = {}
    for line in new[0].splitlines():
        name, separator, value = line.partition(b'=')
        if name in allowed:
            if not separator or name in configured:
                raise ValueError('CONFIG_PRESERVE_PROOF')
            configured[name] = value
    if (set(configured) != allowed or any(configured[key.encode()] != value.encode() for key, value in CONFIG_SETTINGS.items())
            or not re.fullmatch(rb'[\x21-\x7e]{1,4096}', configured[b'ANTHROPIC_API_KEY'])):
        raise ValueError('CONFIG_PRESERVE_PROOF')
    for index, source in enumerate((CONFIG_SOURCE_COMMIT, CONFIG_ROLLBACK_COMMIT), 1):
        before = json.loads(old[index], object_pairs_hook=release.unique)
        after = json.loads(new[index], object_pairs_hook=release.unique)
        if (not isinstance(before, dict) or before.get('ok') is not True or before.get('stage') != 'prepared'
                or before.get('source_commit') != source or not isinstance(before.get('files'), dict)
                or before['files'].get(str(paths[0])) != journal['files'][0]['old']):
            raise ValueError('CONFIG_PRESERVE_PROOF')
        before['files'][str(paths[0])] = journal['files'][0]['new']
        if before != after:
            raise ValueError('CONFIG_PRESERVE_PROOF')
    # Both historical manifests must still validate against the current live files.
    upgrade.manifest(release, CONFIG_SOURCE_COMMIT, started=True)
    upgrade.manifest(release, CONFIG_ROLLBACK_COMMIT, started=True)
    chain_bodies = []
    for index, (source, archive, run_id, previous) in enumerate(CONFIG_PRESERVATION_CHAIN):
        _, bridge = upgrade.manifest(release, source, started=True)
        bridge_file = release.ROOT / 'receipts' / ('preview-' + source + '.json')
        bridge_body = read(bridge_file)
        started_body = read(bridge_file.with_name('preview-start-' + source + '.json'))
        started = json.loads(started_body, object_pairs_hook=release.unique)
        if ((index == len(CONFIG_PRESERVATION_CHAIN) - 1 and bridge != active)
                or json.loads(bridge_body, object_pairs_hook=release.unique) != bridge
                or bridge.get('runtime_environment_preserved') is not True
                or bridge.get('config_operation_id') != APPROVED_CONFIG_OPERATION_ID
                or bridge.get('source_commit') != source
                or bridge.get('package', {}).get('source_commit') != source
                or bridge['package'].get('source_tar_gz_sha256') != archive
                or bridge['package'].get('baseline') != EXPECTED_BASELINE
                or bridge['package'].get('run_id') != run_id
                or bridge.get('files', {}).get(str(paths[0])) != journal['files'][0]['new']
                or started.get('ok') is not True or started.get('stage') != 'internal_ready'
                or started.get('source_commit') != source
                or started.get('previous_commit') != previous
                or started.get('database_policy') != 'preserve-in-place'
                or started.get('database_opened_by_controller') is not False):
            raise ValueError('CONFIG_PRESERVE_PROOF')
        chain_bodies.extend((bridge_body, started_body))
    candidates = [item for item in files if item['path'] == str(paths[0])]
    if len(candidates) != 1 or candidates[0]['content'].encode() != old[0]:
        raise ValueError('RUNTIME_SECRET_CHANGED')
    resolved = [dict(item, content=new[0].decode()) if item is candidates[0] else dict(item) for item in files]
    return resolved, (journal_body, tuple(old), tuple(new), tuple(chain_bodies))
def _error_labels(error):
    kind = type(error).__name__
    code = error.args[0] if len(error.args) == 1 and isinstance(error.args[0], str) else None
    if isinstance(error,sqlite3.Error):
        fallback=dict(zip(('database is locked|database table is locked|attempt to write a readonly database|'
        'unable to open database file|database disk image is malformed|file is not a database|disk I/O error|'
        'locking protocol').split('|'),(5,6,8,14,11,26,10,15)))
        code=SQL_ERRORS.get(getattr(error,'sqlite_errorcode',fallback.get(code,0))&255)
    return {'error_kind':kind if kind in FAILURE_KINDS else 'OtherError',
        'error_code':code if code in FAILURE_CODES else 'UNRECOGNIZED'}
def _migration_details(r):
    if type(r) is not dict or set(r)!={'ok','step','code','error_kind'} or r['ok'] is not False:return {}
    p,c,k=(r[k] for k in ('step','code','error_kind'))
    if (type(p) is type(c) is type(k) is str and p in M_PHASES
        and c in M_CODES|set(M_SQL.values())|{'UNRECOGNIZED'}
        and k in M_KINDS):return dict(operation=p,error_kind=k,error_code=c)
    return {}
def _capture_failure(error, prefix='failed'):
    details = {'stage':STAGE if STAGE in FAILURE_STAGES else 'unknown',
        'operation':OPERATION if OPERATION in FAILURE_OPERATIONS else 'unknown', **_error_labels(error)}
    details.update(_migration_details(getattr(error,'migration_failure',None)))
    return {prefix+'_'+key:value for key,value in details.items()}
def failure_report(error):
    result = {'stage':STAGE if STAGE in FAILURE_STAGES else 'unknown', **_error_labels(error)}
    choices = {'stage':FAILURE_STAGES|{'unknown'}, 'operation':FAILURE_OPERATIONS|{'unknown'},
        'error_kind':FAILURE_KINDS|{'OtherError'}, 'error_code':FAILURE_CODES|{'UNRECOGNIZED'}}
    details = getattr(error, 'failure_details', {})
    if isinstance(details, dict):
        for prefix in ('failed', 'cleanup', 'rollback'):
            for suffix, allowed in choices.items():
                key = prefix+'_'+suffix
                value = details.get(key)
                if isinstance(value, str) and value in allowed:
                    result[key] = value
        for key, allowed in (('export_command_stage', EXPORT_COMMAND_STAGES),
                             ('export_command_issue', EXPORT_COMMAND_ISSUES)):
            value = details.get(key)
            if isinstance(value, str) and value in allowed:
                result[key] = value
        status = details.get('export_command_status')
        if type(status) is int and 0 <= status <= 255:
            result['export_command_status'] = status
    return result
def require_pins():
    if (type(TARGET_COMMIT) is not str or re.fullmatch('[0-9a-f]{40}', TARGET_COMMIT) is None
        or TARGET_COMMIT == OLD_COMMIT or type(TARGET_SOURCE_SHA256) is not str
        or re.fullmatch('[0-9a-f]{64}', TARGET_SOURCE_SHA256) is None
        or type(STORE_SHA256) is not dict or set(STORE_SHA256)!={'old','target'}
        or STORE_SHA256.get('old')!='a78560f42cd3e4ee774135b3b148f0e518ce59a41f1c9d74ae475769aa643856'
        or type(STORE_SHA256.get('target')) is not str
        or re.fullmatch('[0-9a-f]{64}', STORE_SHA256['target']) is None):
        raise ValueError('CODE_TARGET_NOT_PINNED')
    for manifest in (OLD_MANIFEST, TARGET_MANIFEST):
        if type(manifest) is not dict or not manifest or len(manifest) > 512:
            raise ValueError('CODE_TARGET_NOT_PINNED')
        for name, row in manifest.items():
            if (not safe_source_path(name) or type(row) is not tuple or len(row) != 3
                or row[0] not in (0o644, 0o755) or type(row[1]) is not int or not 0 <= row[1] <= 1024*1024
                or type(row[2]) is not str or re.fullmatch('[0-9a-f]{64}', row[2]) is None):
                raise ValueError('CODE_TARGET_NOT_PINNED')
    if (type(CI_PROOF) is not dict or set(CI_PROOF) != {'source_commit','tooling_head','run_id','receipt_sha256'}
        or CI_PROOF['source_commit'] != TARGET_COMMIT
        or type(CI_PROOF['tooling_head']) is not str or re.fullmatch('[0-9a-f]{40}',CI_PROOF['tooling_head']) is None
        or type(CI_PROOF['run_id']) is not str or re.fullmatch('[0-9]{6,20}',CI_PROOF['run_id']) is None
        or type(CI_PROOF['receipt_sha256']) is not str or re.fullmatch('[0-9a-f]{64}',CI_PROOF['receipt_sha256']) is None):
        raise ValueError('CODE_TARGET_NOT_PINNED')
    if type(SCHEMA_SHA256) is not dict or set(SCHEMA_SHA256)!={'old','target'} or any(type(SCHEMA_SHA256.get(role)) is not str or re.fullmatch('[0-9a-f]{64}',SCHEMA_SHA256[role]) is None for role in ('old','target')):
        raise ValueError('CODE_TARGET_NOT_PINNED')
    if type(REPORT_ASSETS) is not dict or not set(OLD_REPORT_ASSETS) <= set(REPORT_ASSETS):
        raise ValueError('CODE_TARGET_NOT_PINNED')
    for route, row in REPORT_ASSETS.items():
        if (type(route) is not str or not route.startswith('/naver/')
            or type(row) is not tuple or len(row)!=3 or type(row[0]) is not int or not 0 < row[0] <= 1024*1024
            or type(row[1]) is not str or re.fullmatch('[0-9a-f]{64}',row[1]) is None
            or row[2] not in ('text/javascript; charset=utf-8','text/css; charset=utf-8','application/gzip')):
            raise ValueError('CODE_TARGET_NOT_PINNED')
        path='backend/naver_page/'+route.removeprefix('/naver/')
        if TARGET_MANIFEST.get(path, (None,None,None))[1:] != row[:2]:
            raise ValueError('CODE_TARGET_NOT_PINNED')
    if (OLD_MANIFEST.get('naver_engine/store.py',(None,None,None))[2] != STORE_SHA256['old']
        or TARGET_MANIFEST.get('naver_engine/store.py',(None,None,None))[2] != STORE_SHA256['target']):
        raise ValueError('CODE_TARGET_NOT_PINNED')


def safe_source_path(name):
    return (type(name) is str and 0 < len(name) <= 300 and not name.startswith('/')
        and all(part not in ('','..','.') for part in name.split('/'))
        and name not in ('HANDOVER.md',) and not any(part in ('store 2.py','.git','tests','__pycache__') for part in name.split('/'))
        and not name.endswith(('.env','.pyc','.pem','.key')) and '.env.' not in name
        and (name.startswith(('naver_engine/','naver_runtime/','backend/app/naver_auto/','backend/naver_page/','deploy/'))
             or name in {'backend/requirements.txt','backend/app/__init__.py','backend/app/naver_relay.py',
                 'backend/app/routers/__init__.py','backend/app/routers/naver.py','backend/app/naver_entry.py',
                 '.dockerignore','Dockerfile.naver-engine','Dockerfile.naver-engine.dockerignore',
                 'Dockerfile.naver-relay','Dockerfile.naver-relay.dockerignore','compose.naver-engine.yml','compose.naver-relay.yml'}))


def validate_package(package, release):
    require_pins()  # refuse before host, file, DB, credentials or subprocess access
    if type(package) is not dict or package.get('operation') != 'code-prepare':
        raise ValueError('CODE_PACKAGE')
    release.validate_package(dict(package, operation='upgrade-prepare'))
    if package['source_commit'] != TARGET_COMMIT: raise ValueError('CODE_TARGET')
    if package['source_tar_gz_sha256'] != TARGET_SOURCE_SHA256: raise ValueError('CODE_TARGET_SOURCE_CHANGED')
    if package['baseline'] != EXPECTED_BASELINE: raise ValueError('CODE_BASELINE')
    return package
def bootstrap_state(release, upgrade):
    request = upgrade.REQUEST
    if not os.path.lexists(request):
        return None
    release.trusted_dir(request.parent, uid=10001, gid=10001, mode=0o750)
    raw = upgrade.read_file(request, uid=0, gid=10001, mode=0o440, maximum=4096)
    data = json.loads(raw, object_pairs_hook=release.unique)
    identity = data.get('request_id')
    if not isinstance(identity, str) or not re.fullmatch('[0-9a-f]{32}', identity):
        raise ValueError('BOOTSTRAP_REQUEST')
    folder = request.parent/'bootstrap'
    release.trusted_dir(folder, uid=10001, gid=10001, mode=0o700)
    snapshot = {'request': raw}
    for suffix in ('.json', '.result.json'):
        body = upgrade.read_file(folder/('bootstrap-'+identity+suffix), uid=10001, gid=10001,
        mode=0o600, maximum=32768)
        value = json.loads(body, object_pairs_hook=release.unique)
        if value.get('request_id') != identity or value.get('status') not in (
        ('started',) if suffix == '.json' else ('completed', 'partial', 'failed_partial')):
            raise ValueError('BOOTSTRAP_NOT_FINISHED')
        snapshot[suffix] = body
    return snapshot
def current_state(package, host, release, lifecycle, upgrade):
    if os.geteuid() != 0 or host.baseline() != package['baseline']:
        raise ValueError('HOST_BASELINE')
    path, receipt = upgrade.manifest(release, OLD_COMMIT, started=True)
    if receipt['package'].get('baseline') != package['baseline']:
        raise ValueError('OLD_BASELINE')
    if receipt['package'].get('source_tar_gz_sha256') != OLD_SOURCE_SHA256:
        raise ValueError('OLD_SOURCE_CHANGED')
    files = lifecycle.unit_files(path, pwd.getpwnam('www-data').pw_gid, release)
    for parent in (lifecycle.UNIT_DIR, lifecycle.TMPFILES.parent):
        release.trusted_dir(parent)
    for filename, body in files.items():
        if upgrade.read_file(filename, mode=0o644, maximum=32768) != body:
            raise ValueError('OLD_UNIT_CHANGED')
    for unit in ('docker.service', lifecycle.TUNNEL, *lifecycle.UNITS):
        if lifecycle._state(release, unit, 'ActiveState') != 'active':
            raise ValueError('DEPENDENCY_NOT_ACTIVE')
    for unit in lifecycle.UNITS:
        if lifecycle._state(release, unit, 'UnitFileState') != 'enabled':
            raise ValueError('OLD_UNIT_NOT_ENABLED')
    return path, receipt, files, lifecycle._snapshot(release, path, receipt['images']), bootstrap_state(release, upgrade)
def schema_contract(body):
    tree = ast.parse(body)
    selected = {}
    for node in ast.walk(tree):
        if isinstance(node,ast.Assign):
            for target in node.targets:
                if isinstance(target,ast.Name) and target.id in ('SCHEMA_VERSION','_SCHEMA','_REVISION_COLUMNS'):
                    selected[target.id]=selected.get(target.id,'')+ast.dump(node,include_attributes=False)
        elif isinstance(node,ast.AugAssign) and isinstance(node.target,ast.Name) and node.target.id=='_SCHEMA':
            selected['_SCHEMA']=selected.get('_SCHEMA','')+ast.dump(node,include_attributes=False)
        elif isinstance(node,ast.FunctionDef) and node.name=='_migrate':
            selected[node.name]=ast.dump(node,include_attributes=False)
    if set(selected)!={'SCHEMA_VERSION','_SCHEMA','_REVISION_COLUMNS','_migrate'}:
        raise ValueError('SCHEMA_CONTRACT_MISSING')
    return selected
def store_contract(body, role):
    if role not in ('old', 'target') or hashlib.sha256(body).hexdigest() != STORE_SHA256.get(role):
        raise ValueError('CODE_STORE_CHANGED')
    tree = ast.parse(body)
    versions = [node for node in tree.body if isinstance(node,ast.Assign)
        and any(isinstance(target,ast.Name) and target.id=='SCHEMA_VERSION' for target in node.targets)]
    if (len(versions) != 1 or len(versions[0].targets) != 1
        or not isinstance(versions[0].value, ast.Constant)
        or type(versions[0].value.value) is not int or versions[0].value.value != (OLD_SCHEMA if role == 'old' else TARGET_SCHEMA)):
        raise ValueError('CODE_SCHEMA_CHANGED')
    return schema_contract(body)
def compatible_engine_compose(before, after):
    if (type(before) is not bytes or type(after) is not bytes
            or before != after
            or hashlib.sha256(before).hexdigest() != ENGINE_COMPOSE_SHA256):
        raise ValueError('CODE_INFRASTRUCTURE_CHANGED')

def compatible_source(old, new, upgrade):
    read = lambda path: upgrade.read_file(path, mode=0o644, maximum=1024*1024, minimum=0)
    compatible_engine_compose(read(old/'compose.naver-engine.yml'), read(new/'compose.naver-engine.yml'))
    for name in ('compose.naver-relay.yml',
        'deploy/naver-engine-backup.override.yml', 'Dockerfile.naver-engine',
        'Dockerfile.naver-relay', 'backend/requirements.txt', 'naver_runtime/bootstrap.py'):
        if read(old/name) != read(new/name):
            raise ValueError('CODE_INFRASTRUCTURE_CHANGED')
    before, after = read(old/'naver_engine/store.py'), read(new/'naver_engine/store.py')
    migration_contract(before, after)
    for name in ('engine', 'relay'):
        before = upgrade.read_file(old/('preview-'+name+'.override.yml'), mode=0o600)
        after = upgrade.read_file(new/('preview-'+name+'.override.yml'), mode=0o600)
        if after != target_override(before, name):
            raise ValueError('CODE_OVERRIDE_CHANGED')
    compatible_code_scope(old, new, upgrade)
def migration_contract(before, after):
    store_contract(before, 'old')
    store_contract(after, 'target')
    # No schema-equality normalization: exact files bind actual additive migration.
def target_override(before, name):
    return before.replace(OLD_COMMIT.encode(), TARGET_COMMIT.encode())
def stopped_writer(release, lifecycle, path, images, unit):
    if (unit not in lifecycle.UNITS or path.name not in ('naver-'+OLD_COMMIT,'naver-'+TARGET_COMMIT)
        or not isinstance(images,dict) or not images or set(images)-{OLD_COMMIT,TARGET_COMMIT}):
        raise ValueError('ACCOUNT_WRITER_NOT_STOPPED')
    name='engine' if unit==lifecycle.UNITS[0] else 'relay'
    allowed={source:value.get(name) for source,value in images.items() if isinstance(value,dict)}
    if len(allowed)!=len(images) or any(not isinstance(v,str) or not re.fullmatch('sha256:[0-9a-f]{64}',v)
        for v in allowed.values()):
        raise ValueError('ACCOUNT_WRITER_NOT_STOPPED')
    if (lifecycle._state(release,unit,'ActiveState') not in ('inactive','failed')
        or lifecycle._state(release,unit,'SubState') not in ('dead','failed')
        or lifecycle._state(release,unit,'MainPID')!='0'):
        raise ValueError('ACCOUNT_WRITER_NOT_STOPPED')
    ids=release.command(['docker','ps','--all','--no-trunc','--filter',
        'label=com.docker.compose.project=naver-'+name,'--format','{{.ID}}']).decode().strip().splitlines()
    if len(ids)>1 or any(not re.fullmatch('[0-9a-f]{64}',identity) for identity in ids):
        raise ValueError('ACCOUNT_WRITER_NOT_STOPPED')
    if not ids:
        return
    fields={'id':'.Id','image':'.Image','running':'.State.Running','restarting':'.State.Restarting','pid':'.State.Pid',
        'source':'(index .Config.Labels "metainc.naver.preview.source")',
        'project':'(index .Config.Labels "com.docker.compose.project")',
        'service':'(index .Config.Labels "com.docker.compose.service")'}
    fmt='{'+','.join(json.dumps(k)+':{{json '+v+'}}' for k,v in fields.items())+'}'
    row=json.loads(release.command(['docker','inspect','--format',fmt,ids[0]]))
    if (not isinstance(row,dict) or not isinstance(row.get('source'),str) or row['source'] not in allowed
        or row.get('id')!=ids[0] or row.get('image')!=allowed[row['source']]
        or row.get('project')!='naver-'+name or row.get('service')!='naver-'+name
        or row.get('running') is not False or row.get('restarting') is not False
        or type(row.get('pid')) is not int or row['pid']!=0):
        raise ValueError('ACCOUNT_WRITER_NOT_STOPPED')
def compatible_code_scope(old, new, upgrade, *, inverse=False):
    require_pins()
    def inventory(root, wanted):
        actual={}
        for path in root.rglob('*'):
            if path.is_symlink() or path.resolve()!=path: raise ValueError('CODE_SOURCE_PATH')
            if path.is_dir(): continue
            name=path.relative_to(root).as_posix()
            if name in ('preview-engine.override.yml','preview-relay.override.yml'): continue
            if name=='deploy/naver-engine.env.example' and wanted is OLD_MANIFEST: continue
            # Check path before reading or hashing any forbidden object.
            if not safe_source_path(name) or name not in wanted: raise ValueError('CODE_SCOPE_CHANGED')
            mode=stat.S_IMODE(path.stat().st_mode)
            body=upgrade.read_file(path,mode=mode,maximum=1024*1024,minimum=0)
            actual[name]=(mode,len(body),hashlib.sha256(body).hexdigest())
        if actual!=wanted: raise ValueError('CODE_SCOPE_CHANGED')
    inventory(old, TARGET_MANIFEST if inverse else OLD_MANIFEST)
    inventory(new, OLD_MANIFEST if inverse else TARGET_MANIFEST)


def compatible_inverse_source(target, old, upgrade):
    compatible_source(old,target,upgrade)
    compatible_code_scope(target,old,upgrade,inverse=True)
def probe(release, source_commit, upgrade):
    management_target = source_commit in (OLD_COMMIT, TARGET_COMMIT)
    old_source = source_commit == OLD_COMMIT
    if source_commit == OLD_COMMIT:
        source_commit = TARGET_COMMIT
    if (not isinstance(TARGET_COMMIT, str) or not re.fullmatch('[0-9a-f]{40}', TARGET_COMMIT)
        or source_commit != TARGET_COMMIT):
        raise ValueError('CODE_PROBE_SOURCE')
    def request(path, route, method='GET'):
        status, headers, body = release.unix_request(path, route, method)
        key = route.removeprefix('/api/naver-auto')
        opened = key in OWNER_ACTION_ROUTES or key in TARGET_ACTION_ROUTES
        if method == 'POST' and (route == '/api/naver-auto/links/confirm' or opened):
            if status != 401:
                raise ValueError('VERIFIED_WRITE_AUTH_NOT_REQUIRED')
            return 403, headers, body
        return status, headers, body
    upgrade.probe(SimpleNamespace(unix_request=request))
    relay = '/run/metainc/naver-relay/relay.sock'
    if release.unix_request(relay, '/api/naver-auto/dashboard', 'GET')[0] != 401:
        raise ValueError('CODE_ROUTE_STATUS')
    status, headers, body = release.unix_request(relay, '/naver/dashboard', 'GET')
    headers = {key.lower():value for key,value in headers.items()}
    if (status != 200 or b'id="s-dashboard"' not in body or headers.get('referrer-policy') != 'no-referrer'
            or headers.get('cache-control') != 'no-store'):
        raise ValueError('PAGE_NOT_READY')
    if management_target:
        for route, method in (('/reports', 'GET'),
        ('/reports/history?possibility_id=1&limit=20', 'GET'),
        ('/accounts/reasons?ad_account_no=1&page=0&selection=all', 'GET'),
        ('/management/update', 'POST'),
        ('/management/collect', 'POST'), ('/reports/review', 'POST')):
            if release.unix_request(relay, '/api/naver-auto'+route, method)[0] != 401:
                raise ValueError('CODE_ROUTE_STATUS')
    if release.unix_request(relay, '/api/naver-auto/reports/strategy/jobs?job_id=' + '0' * 32, 'GET')[0] != 401:
        raise ValueError('CODE_ROUTE_STATUS')
    for route, method, expected in (
            ('/collection/status', 'GET', 401), ('/collection/request', 'POST', 401),
            *((r, 'POST', 401) for r in OWNER_ACTION_ROUTES),
            *((r, 'POST', 401) for r in TARGET_ACTION_ROUTES),
            *((r, 'POST', 403) for r in CLOSED_LINK_ROUTES)):
        if release.unix_request(relay, '/api/naver-auto' + route, method)[0] != expected:
            raise ValueError('CODE_ROUTE_STATUS')
    if management_target:
        for route in ('/reports/accounts?selection=all&kind=weekly&page=0',
                      '/reports/detail?report_id=1&account_key=company'):
            if release.unix_request(relay, '/api/naver-auto'+route, 'GET')[0] != 401:
                raise ValueError('CODE_ROUTE_STATUS')
        assets = dict(OLD_REPORT_ASSETS if old_source else REPORT_ASSETS)
        account_query='?possibility_id=1&account_key='+'0'*64
        new_reads=('/experiments'+account_query,'/execution'+account_query,
            '/automation/learning/source'+account_query+'&asset_id=auto-exec-'+'0'*32,
            '/reports/schedule'+account_query,'/operations'+account_query)
        for route in SALES_GET_ROUTES + (() if old_source else new_reads):
            if release.unix_request(relay, '/api/naver-auto'+route, 'GET')[0] != 401:
                raise ValueError('CODE_ROUTE_STATUS')
        if not old_source:
            for route in ('/experiments','/execution','/automation/learning/source','/reports/schedule'):
                if release.unix_request(relay,'/api/naver-auto'+route,'POST')[0]!=401:
                    raise ValueError('CODE_ROUTE_STATUS')
        if release.unix_request(relay, '/api/naver-auto/automation?possibility_id=1&account_key=customer-1', 'GET')[0] != 401:
            raise ValueError('CODE_ROUTE_STATUS')
        for route,(size,digest,mime) in assets.items():
            status,headers,body = release.unix_request(relay, route, 'GET')
            headers = {key.lower():value for key,value in headers.items()}
            if (status != 200 or len(body) != size or hashlib.sha256(body).hexdigest() != digest
                    or headers.get('content-type') != mime or headers.get('cache-control') != 'no-store'
                    or headers.get('x-content-type-options') != 'nosniff'
                    or headers.get('referrer-policy') != 'no-referrer' or headers.get('content-encoding')):
                raise ValueError('REPORT_ASSET_NOT_READY')
def prepare(package, host, release, lifecycle, upgrade, *, approved_config_operation_id=None, prepare_exports=None):
    global STAGE
    STAGE = 'code_prepare_preflight'
    validate_package(package, release)
    if approved_config_operation_id != APPROVED_CONFIG_OPERATION_ID: raise ValueError('CONFIG_PRESERVE_NOT_APPROVED')
    old = current_state(package, host, release, lifecycle, upgrade)
    destination = release.ROOT/'releases'/('naver-'+TARGET_COMMIT)
    receipt_path = release.ROOT/'receipts'/('preview-'+TARGET_COMMIT+'.json')
    if os.path.lexists(receipt_path):
        raise ValueError('PREEXISTING_RELEASE')
    for folder in (release.ROOT, release.ROOT/'incoming', release.ROOT/'releases', release.ROOT/'receipts',
                   release.ROOT/'incoming'/package['run_id']):
        if folder.resolve() != folder:
            raise ValueError('SYMLINKED_PARENT')
        release.trusted_dir(folder, mode=0o700)
    ciphertext = release.received_ciphertext(release.ROOT/'incoming'/package['run_id']/'runtime-secrets.cms', package['ciphertext_sha256'])
    key = upgrade.ENVELOPE_KEY
    if key.parent.resolve() != key.parent:
        raise ValueError('SYMLINKED_ENVELOPE_PARENT')
    release.trusted_dir(key.parent, mode=0o700)
    release.trusted_private_file(key)
    plain = release.command(['openssl','cms','-decrypt','-binary','-inform','DER','-inkey',str(key)], data=ciphertext)
    if len(plain) > 4*1024*1024:
        raise ValueError('PLAINTEXT_SIZE')
    source, files = release.decode_payload(plain, TARGET_COMMIT, package['source_tar_gz_sha256'])
    release.source_members(source)[0].close()
    original_files = files
    config_proof = None
    if approved_config_operation_id is not None:
        STAGE = 'code_prepare_runtime_config'
        files, config_proof = preserve_approved_config(files, approved_config_operation_id, old[1], release, upgrade)
    for item in files:
        if upgrade.read_file(item['path'], uid=item['uid'], gid=item['gid'], mode=0o600) != item['content'].encode():
            raise ValueError('RUNTIME_SECRET_CHANGED')
    overrides = {name: target_override(upgrade.read_file(old[0]/('preview-'+name+'.override.yml'), mode=0o600), name).decode()
                 for name in ('engine', 'relay')}
    if os.path.lexists(destination):
        upgrade.verify_interrupted_source(source, destination, overrides, release)
    else:
        release.extract_source(source, destination)
        for name, body in overrides.items():
            release.write_new(destination/('preview-'+name+'.override.yml'), body.encode())
    compatible_source(old[0], destination, upgrade)
    if prepare_exports is not None:
        prepare_exports()
    for name in ('engine', 'relay'):
        STAGE = 'code_build_'+name
        release.command(['docker','build','--label','metainc.naver.preview.source='+TARGET_COMMIT,
                         '-t','metainc/naver-'+name+':'+TARGET_COMMIT,'-f',str(destination/('Dockerfile.naver-'+name)),str(destination)], timeout=600)
        STAGE = 'code_config_'+name
        release.command(release.compose(destination, name)+['config','--quiet'])
    STAGE = 'code_check_config'
    check_override = release.ROOT/'incoming'/package['run_id']/'check-config.override.yml'
    release.write_new(check_override, b'services:\n  naver-engine:\n    network_mode: none\n')
    flags = target_runtime_flags(destination, release, package['run_id'], override=check_override)
    STAGE = 'code_prepare_postflight'
    if current_state(package, host, release, lifecycle, upgrade) != old:
        raise ValueError('OLD_STATE_CHANGED')
    if config_proof is not None:
        STAGE = 'code_prepare_runtime_postflight'
        current_files, current_proof = preserve_approved_config(original_files, approved_config_operation_id, old[1], release, upgrade)
        if current_files != files or current_proof != config_proof:
            raise ValueError('CONFIG_PRESERVE_DRIFT')
        for item in files:
            if upgrade.read_file(item['path'], uid=item['uid'], gid=item['gid'], mode=0o600) != item['content'].encode():
                raise ValueError('RUNTIME_SECRET_CHANGED')
    images = {name: json.loads(release.command(['docker','image','inspect','--format','{{json .Id}}','metainc/naver-'+name+':'+TARGET_COMMIT])) for name in ('engine','relay')}
    paths = {str(destination/'deploy/naver-engine-backup.override.yml')}
    paths.update(str(destination/(prefix+name+suffix)) for name in ('engine','relay')
                 for prefix, suffix in (('compose.naver-', '.yml'), ('preview-', '.override.yml')))
    paths.update(item['path'] for item in files)
    receipt = {'ok':True, 'stage':'prepared', 'source_commit':TARGET_COMMIT,
               'package':{k:v for k,v in package.items() if k!='operation'}, 'images':images,
               'files':{path:release.sha(Path(path).read_bytes()) for path in sorted(paths)}}
    receipt.update(flags, runtime_flags_verified=True)
    if config_proof is not None:
        receipt.update(runtime_environment_preserved=True, config_operation_id=approved_config_operation_id)
    release.write_new(receipt_path, json.dumps(receipt, sort_keys=True).encode())
    upgrade.manifest(release, TARGET_COMMIT, package)
    result = {'ok':True,'stage':'prepared','source_commit':TARGET_COMMIT,'previous_commit':OLD_COMMIT,
              'services_started':False,'nginx_changed':False,'bootstrap_unchanged':True}
    result.update(flags, runtime_flags_verified=True)
    if config_proof is not None:
        result.update(runtime_environment_preserved=True, config_operation_id=approved_config_operation_id)
    return result

SCHEMA_SHA256 = {'old': '6339215c290f599984f114eeeaf1cd12ed378b1fc5e45c7896e2f442f379fd6c', 'target': 'f7a5d1a05dca07e4eeed737155cb4bc5031e492ba07ce948b0b13d773cdcb8e5'}


def schema_digest(connection):
    rows=connection.execute("SELECT type,name,tbl_name,sql FROM sqlite_master WHERE name NOT LIKE 'sqlite_%' ORDER BY type,name").fetchall()
    normalized=[]
    for kind,name,table,sql in rows:
        if not re.fullmatch('[a-z][a-z0-9_]{0,100}',name): raise ValueError('DB_SCHEMA_OBJECT')
        normalized.append((kind,name,table,re.sub(r'\s+',' ',sql or '').strip()))
    return hashlib.sha256(json.dumps(normalized,separators=(',',':')).encode()).hexdigest()


def database_contract(connection, source):
    if source not in (OLD_COMMIT,TARGET_COMMIT): raise ValueError('CODE_PROBE_SOURCE')
    role='old' if source==OLD_COMMIT else 'target'
    version=OLD_SCHEMA if role=='old' else TARGET_SCHEMA
    if (connection.execute("SELECT value FROM naver_auto_meta WHERE key='schema_version'").fetchone()!=(str(version),)
        or schema_digest(connection)!=SCHEMA_SHA256[role]):
        raise ValueError('DB_OLD_SCHEMA' if role=='old' else 'DB_TARGET_SCHEMA')
    if role=='target' and {r[0] for r in connection.execute("SELECT name FROM sqlite_master WHERE type='table' AND name GLOB 'naver_randomized_*'")}!=RANDOMIZED_TABLES:
        raise ValueError('DB_TARGET_SCHEMA')


DATABASE_MAX_BYTES = 2 * 1024**3
DATABASE_CHUNK_BYTES = 1024**2
DATABASE_RESERVE_BYTES = 64 * 1024**2
FAILURE_CODES |= frozenset({'DB_SPACE'})


def _database_metadata(path, fd, *, uid=0, gid=0, minimum=1):
    """Validate a held no-follow file; never read its body for policy checks."""
    info=os.fstat(fd);named=path.lstat()
    if (path.resolve()!=path or not stat.S_ISREG(info.st_mode) or info.st_nlink!=1
        or (info.st_uid,info.st_gid,stat.S_IMODE(info.st_mode))!=(uid,gid,0o600)
        or not minimum<=info.st_size<=DATABASE_MAX_BYTES
        or not stat.S_ISREG(named.st_mode) or (info.st_dev,info.st_ino)!=(named.st_dev,named.st_ino)):
        raise ValueError('DB_IDENTITY')
    return (info.st_dev,info.st_ino,info.st_size,info.st_mtime_ns,info.st_ctime_ns)


@contextmanager
def _database_file(path, *, uid=0, gid=0, minimum=1, writable=False, lockable=False, stable=True):
    # Keep the original O_RDWR flock handle; it never writes. SQLite uses a
    # separate mode=ro connection, and ordinary metadata handles are O_RDONLY.
    fd=os.open(path,(os.O_RDWR if writable or lockable else os.O_RDONLY)|os.O_NOFOLLOW|os.O_NONBLOCK)
    try:
        before=_database_metadata(path,fd,uid=uid,gid=gid,minimum=minimum)
        yield fd,before
        after=_database_metadata(path,fd,uid=uid,gid=gid,minimum=minimum)
        if after[:2]!=before[:2] or (stable and not writable and after!=before):raise ValueError('DB_IDENTITY')
    finally:os.close(fd)


def database_preflight(release, *, space=True):
    """Metadata-only while old services run; repeat after proving them stopped."""
    release.trusted_dir(DATA,uid=10001,gid=10001,mode=0o750)
    with _database_file(DATA/'engine.db',uid=10001,gid=10001,stable=False) as (_,identity):size=identity[2]
    if space:
        # A committed WAL can contain pages absent from the main file. Reserve
        # its full byte length too, both before STOP and again after STOP.
        present={suffix for suffix in ('-wal','-shm','-journal') if os.path.lexists(str(DATA/'engine.db')+suffix)}
        if present and present!={'-wal','-shm'}:raise ValueError('DB_IDENTITY')
        for suffix in present:
            with _database_file(Path(str(DATA/'engine.db')+suffix),uid=10001,gid=10001,minimum=0,stable=False) as (_,found):
                if suffix=='-wal':size+=found[2]
        receipts=release.ROOT/'receipts';release.trusted_dir(receipts,mode=0o700)
        same=DATA.stat().st_dev==receipts.stat().st_dev
        # The roundtrip copy is removed durably before migration. Snapshot plus
        # verification, or snapshot plus a restore temp, therefore peak at 2x.
        required=[(receipts,2*size+DATABASE_RESERVE_BYTES)] if same else [
            (receipts,2*size+DATABASE_RESERVE_BYTES),(DATA,size+DATABASE_RESERVE_BYTES)]
        for path,need in required:
            capacity=os.statvfs(path)
            if capacity.f_bavail*capacity.f_frsize<need:raise ValueError('DB_SPACE')


@contextmanager
def _database_reader(path, fd, *, uid=0, gid=0):
    # Callers have proved operating writers stopped (private backup files have
    # no writers). Immutable is used only when every sidecar is absent. This
    # prevents a root mode=ro reader from creating root-owned WAL/SHM files.
    before=_database_metadata(path,fd,uid=uid,gid=gid)
    present={suffix for suffix in ('-wal','-shm','-journal') if os.path.lexists(str(path)+suffix)}
    if present and present!={'-wal','-shm'}:raise ValueError('DB_IDENTITY')
    for suffix in present:
        with _database_file(Path(str(path)+suffix),uid=uid,gid=gid,minimum=0):pass
    uri=path.as_uri()+'?mode=ro'+('' if present else '&immutable=1')
    with closing(sqlite3.connect(uri,uri=True,timeout=1)) as connection:
        connection.execute('PRAGMA query_only=ON');connection.execute('PRAGMA trusted_schema=OFF')
        yield connection
    if _database_metadata(path,fd,uid=uid,gid=gid)!=before:raise ValueError('DB_IDENTITY')
    if not present and any(os.path.lexists(str(path)+s) for s in ('-wal','-shm','-journal')):
        raise ValueError('DB_IDENTITY')


def _database_digest(path, *, uid=0, gid=0):
    with _database_file(path,uid=uid,gid=gid) as (fd,identity):
        digest=hashlib.sha256();size=0
        while True:
            chunk=os.read(fd,DATABASE_CHUNK_BYTES)
            if not chunk:break
            size+=len(chunk)
            if size>DATABASE_MAX_BYTES:raise ValueError('DB_IDENTITY')
            digest.update(chunk)
        if size!=identity[2]:raise ValueError('DB_IDENTITY')
        return digest.hexdigest()


def _database_copy(path, temporary, digest, release):
    """Create an exact private restore copy in bounded chunks before quarantine."""
    release.write_new(temporary,b'',uid=10001,gid=10001,mode=0o600)
    with _database_file(path) as (source,identity), _database_file(
            temporary,uid=10001,gid=10001,minimum=0,writable=True) as (target,_):
        found=hashlib.sha256();size=0
        while True:
            chunk=os.read(source,DATABASE_CHUNK_BYTES)
            if not chunk:break
            size+=len(chunk)
            if size>DATABASE_MAX_BYTES:raise ValueError('DB_IDENTITY')
            found.update(chunk);view=memoryview(chunk)
            while view:
                written=os.write(target,view)
                if written<=0:raise OSError('DB_COPY_FAILED')
                view=view[written:]
        os.fsync(target)
        if size!=identity[2] or found.hexdigest()!=digest:raise ValueError('DB_SNAPSHOT_CHANGED')
        copied=_database_metadata(temporary,target,uid=10001,gid=10001)
    return copied


def _database_move(source, destination, identity):
    held=os.open(source,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
    try:
        if _database_metadata(source,held,uid=10001,gid=10001,minimum=0)!=identity:raise ValueError('DB_IDENTITY')
        if os.path.lexists(destination):raise ValueError('DB_IDENTITY')
        os.replace(source,destination)
        if _database_metadata(destination,held,uid=10001,gid=10001,minimum=0)[:4]!=identity[:4]:raise ValueError('DB_IDENTITY')
    finally:os.close(held)


def _database_fsync_directory(path):
    fd=os.open(path,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
    try:os.fsync(fd)
    finally:os.close(fd)


def _database_unlink_verify(path, fd, created, completed):
    # Only the just-created roundtrip copy is disposable. A replaced path,
    # changed file, original snapshot, or operating DB is never removed.
    if (re.fullmatch(r'completion-db-[0-9a-f]{32}\.verify\.sqlite',path.name) is None
        or created[:2]!=completed[:2] or _database_metadata(path,fd)!=completed):
        raise ValueError('DB_IDENTITY')
    os.unlink(path)


def verify_database_schema(source, release, upgrade):
    database_preflight(release,space=False)
    db=DATA/'engine.db'
    with _database_file(db,uid=10001,gid=10001) as (fd,_), _database_reader(db,fd,uid=10001,gid=10001) as connection:
        database_contract(connection,source)


def db_snapshot(identity, release, upgrade):
    global OPERATION
    OPERATION='snapshot_directory'
    database_preflight(release)
    db=DATA/'engine.db'
    destination=release.ROOT/'receipts'/('completion-db-'+identity+'.sqlite')
    release.trusted_dir(release.ROOT/'receipts',mode=0o700)
    with _database_file(db,uid=10001,gid=10001,lockable=True) as (fd,_):
        OPERATION='snapshot_lock';fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
        release.write_new(destination,b'')
        with _database_reader(db,fd,uid=10001,gid=10001) as source, closing(sqlite3.connect(destination)) as target:
            database_contract(source,OLD_COMMIT)
            source.backup(target,pages=256,sleep=0.01)
            if target.execute('PRAGMA integrity_check').fetchall()!=[('ok',)]:raise ValueError('DB_SNAPSHOT_INTEGRITY')
            database_contract(target,OLD_COMMIT)
        durable=os.open(destination,os.O_RDONLY|os.O_NOFOLLOW)
        try:os.fsync(durable)
        finally:os.close(durable)
        digest=_database_digest(destination)
        # Roundtrip in a second server-local DB; no operating row leaves the server.
        verify=destination.with_suffix('.verify.sqlite')
        verified=os.open(verify,os.O_CREAT|os.O_EXCL|os.O_RDWR|os.O_NOFOLLOW|os.O_NONBLOCK,0o600)
        try:
            created=_database_metadata(verify,verified,minimum=0)
            with _database_file(destination) as (saved,_), _database_reader(destination,saved) as source,closing(sqlite3.connect(verify)) as target:
                source.backup(target,pages=256,sleep=0.01)
                database_contract(target,OLD_COMMIT)
                if target.execute('PRAGMA integrity_check').fetchall()!=[('ok',)]:raise ValueError('DB_SNAPSHOT_INTEGRITY')
            completed=_database_metadata(verify,verified)
            if completed[:2]!=created[:2]:raise ValueError('DB_IDENTITY')
            os.fsync(verified)
            proof=release.ROOT/'receipts'/('completion-snapshot-'+identity+'.json')
            release.write_new(proof,json.dumps({
                'source_commit':OLD_COMMIT,'target_commit':TARGET_COMMIT,'operation_id':identity,
                'database_sha256':digest,'schema':OLD_SCHEMA,'snapshot_restore_verified':True},sort_keys=True).encode())
            with _database_file(proof) as (receipt,_):os.fsync(receipt)
            _database_fsync_directory(destination.parent)
            _database_unlink_verify(verify,verified,created,completed)
            _database_fsync_directory(destination.parent)
        finally:os.close(verified)
        return destination,digest


def restore_db(snapshot, identity, release, upgrade):
    path,digest=snapshot
    expected=release.ROOT/'receipts'/('completion-db-'+identity+'.sqlite')
    if path!=expected:raise ValueError('DB_SNAPSHOT_CHANGED')
    release.trusted_dir(release.ROOT/'receipts',mode=0o700)
    if _database_digest(path)!=digest:raise ValueError('DB_SNAPSHOT_CHANGED')
    with _database_file(path) as (fd,_), _database_reader(path,fd) as source:
        database_contract(source,OLD_COMMIT)
        if source.execute('PRAGMA integrity_check').fetchall()!=[('ok',)]:raise ValueError('DB_SNAPSHOT_INTEGRITY')
    release.trusted_dir(DATA,uid=10001,gid=10001,mode=0o750)
    temporary=DATA/('completion-restore-'+identity+'.sqlite')
    copied=_database_copy(path,temporary,digest,release)
    sources=[]
    for suffix in ('','-wal','-shm','-journal'):
        source=DATA/('engine.db'+suffix)
        if os.path.lexists(source):
            with _database_file(source,uid=10001,gid=10001,minimum=0) as (_,found):sources.append((source,found))
    quarantine=DATA/('.completion-failed-db-'+identity)
    release.trusted_dir(quarantine,mode=0o700,new=True)
    for source,found in sources:
        _database_move(source,quarantine/source.name,found)
    _database_move(temporary,DATA/'engine.db',copied)
    _database_fsync_directory(quarantine);_database_fsync_directory(DATA)
    verify_database_schema(OLD_COMMIT,release,upgrade)


MIGRATION_SCRIPT = ('RANDOMIZED_TABLES='+repr(sorted(RANDOMIZED_TABLES))+'\n'
    +'M_KINDS='+repr(sorted(M_KINDS))+'\n'
    +'M_SQL='+repr(M_SQL)+'\n'
    +'M_CODES='+repr(sorted(M_CODES))+'\n')+r'''
import hashlib,json,re,sqlite3,sys
sys.path[:0]=['/opt/naver-engine','/opt/naver-engine/backend']
step='rows_before'
def migration_failure(e):
 k=type(e).__name__;a=e.args
 k=k if k in M_KINDS else 'OtherError'
 c=a[0] if len(a)==1 and isinstance(a[0],str) and a[0] in M_CODES else 'UNRECOGNIZED'
 seen=set();sql=None
 for _ in range(4):
  if not isinstance(e,BaseException) or id(e) in seen:break
  seen.add(id(e))
  if isinstance(e,sqlite3.Error):
   n=getattr(e,'sqlite_errorcode',None)
   if type(n) is int and 0<n<=2147483647:sql=M_SQL.get(n&255)
   if sql is not None:break
  e=e.__cause__ if isinstance(e.__cause__,BaseException) else e.__context__
 return {'ok':False,'step':step,'code':c if c!='UNRECOGNIZED' else sql or c,'error_kind':k}
try:
 from naver_engine import store as S
 def shape(c):
  r=c.execute("SELECT type,name,tbl_name,sql FROM sqlite_master WHERE name NOT LIKE 'sqlite_%' ORDER BY type,name").fetchall()
  return hashlib.sha256(json.dumps([(k,n,t,re.sub(r'\s+',' ',s or '').strip()) for k,n,t,s in r],separators=(',',':')).encode()).hexdigest()
 c=sqlite3.connect('/var/lib/naver-engine/engine.db',isolation_level=None)
 if S.SCHEMA_VERSION!=21 or c.execute("SELECT value FROM naver_auto_meta WHERE key='schema_version'").fetchone()!=('11',) or shape(c)!=PINS['old']:raise ValueError('DB_OLD_SCHEMA')
 tables={}
 for (t,) in c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"):
  if re.fullmatch('[a-z][a-z0-9_]{0,100}',t) is None:raise ValueError('DB_SCHEMA_OBJECT')
  tables[t]=[r[1] for r in c.execute('PRAGMA table_info('+t+')')]
 def rows():
  out={};total=0
  for t,columns in tables.items():
   query='SELECT '+','.join(columns)+' FROM '+t
   if t=='naver_auto_meta':query+=" WHERE key != 'schema_version'"
   query+=' ORDER BY rowid'
   h=hashlib.sha256();count=0
   for row in c.execute(query):
    count+=1;total+=1
    if total>10000000:raise ValueError('DB_ROW_BOUND')
    h.update(json.dumps(list(row),ensure_ascii=True,separators=(',',':'),allow_nan=False).encode()+b'\n')
   out[t]=(count,h.hexdigest())
  return out
 before=rows();step='apply_first'
 st=object.__new__(S.Store);st._conn=c;st._migrate();step='apply_repeat';st._migrate();c.set_authorizer(None)
 step='schema_after'
 if c.execute("SELECT value FROM naver_auto_meta WHERE key='schema_version'").fetchone()!=('21',) or shape(c)!=PINS['target']:raise ValueError('DB_TARGET_SCHEMA')
 if {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name GLOB 'naver_randomized_*'")}!=set(RANDOMIZED_TABLES):raise ValueError('DB_TARGET_SCHEMA')
 if any(c.execute('SELECT count(*) FROM '+t).fetchone()!=(0,) for t in RANDOMIZED_TABLES):raise ValueError('DB_TARGET_SCHEMA')
 step='rows_after'
 if rows()!=before:raise ValueError('DB_ROWS_CHANGED')
 step='integrity'
 if c.execute('PRAGMA integrity_check').fetchall()!=[('ok',)]:raise ValueError('DB_SNAPSHOT_INTEGRITY')
 print(json.dumps({'ok':True,'schema':21,'old_schema':11,'old_tables':len(tables),'old_rows':sum(r[0] for r in before.values()),'preserved_rows':True,'migration_repeatable':True,'network_calls':0,'randomized_tables':RANDOMIZED_TABLES,'randomized_tables_empty':True}))
 c.close()
except Exception as error:
 print(json.dumps(migration_failure(error)));sys.exit(1)
'''


def migrate_database(path, release):
    global STAGE, OPERATION
    STAGE = 'account_sources_warm'
    check = release.compose(path, 'engine')
    override=release.ROOT/'receipts'/('migration-network-'+uuid.uuid4().hex+'.yml')
    release.write_new(override,b'services:\n  naver-engine:\n    network_mode: none\n')
    check+=['-f',str(override)]
    script='PINS='+repr(SCHEMA_SHA256)+'\n'+MIGRATION_SCRIPT
    name = 'naver-migration-'+TARGET_COMMIT+'-'+uuid.uuid4().hex
    identity = None
    failure = None
    try:
        OPERATION = 'warm_create'
        identity = release.command(check+['run', '--detach', '--no-deps', '--pull', 'never',
        '--name', name, '--label', 'metainc.naver.warm.source='+TARGET_COMMIT,
        '--entrypoint', 'python', 'naver-engine', '-I', '-B', '-c', script], timeout=60).decode().strip()
        if not re.fullmatch('[0-9a-f]{64}', identity):
            raise ValueError('WARM_CONTAINER_ID')
        OPERATION = 'warm_wait'
        status = release.command(['docker', 'wait', identity], timeout=180).strip()
        OPERATION = 'warm_logs'
        raw=release.command(['docker','logs',identity],timeout=30)
        if len(raw)>4096:raise ValueError('SOURCE_WARM_FAILED')
        result=json.loads(raw)
        OPERATION = 'warm_result'
        if status != b'0':
            diagnostic=_migration_details(result)
            if diagnostic:
                code=diagnostic['error_code']
                error=ValueError(code if code!='UNRECOGNIZED' else 'SOURCE_WARM_FAILED')
                error.migration_failure=result
                raise error
            if (type(result) is dict and set(result)=={'ok','step','code'} and result['ok'] is False
                and result['step'] in ('migration_start','migration_apply')
                and result['code'] in M_CODES):
                OPERATION=result['step']
                raise ValueError(result['code'])
            raise ValueError('SOURCE_WARM_FAILED')
        if (type(result) is not dict or set(result)!={'ok','schema','old_schema','old_tables','old_rows','preserved_rows','migration_repeatable','network_calls','randomized_tables','randomized_tables_empty'}
            or result['ok'] is not True or type(result['schema']) is not int or result['schema']!=TARGET_SCHEMA
            or type(result['old_schema']) is not int or result['old_schema']!=OLD_SCHEMA
            or type(result['old_tables']) is not int or not 1<=result['old_tables']<=512
            or type(result['old_rows']) is not int or not 0<=result['old_rows']<=10000000
            or result['preserved_rows'] is not True or result['migration_repeatable'] is not True
            or type(result['randomized_tables']) is not list or result['randomized_tables']!=sorted(RANDOMIZED_TABLES)
            or result['randomized_tables_empty'] is not True
            or type(result['network_calls']) is not int or result['network_calls']!=0):
            raise ValueError('SOURCE_WARM_FAILED')
        return result
    except Exception as error:
        error.failure_details = _capture_failure(error)
        failure = error.failure_details
        raise
    finally:
        # Prove cleanup after CLI timeout.
        try:
            OPERATION = 'warm_cleanup_find'
            found = release.command(['docker', 'ps', '--all', '--no-trunc', '--filter',
                'name=^/'+name+'$', '--format', '{{.ID}}'], timeout=30).decode().strip()
            if found:
                OPERATION = 'warm_cleanup_identity'
                if not re.fullmatch('[0-9a-f]{64}', found):
                    raise ValueError('WARM_CONTAINER_ID')
                fmt = '{"source":{{json (index .Config.Labels "metainc.naver.warm.source")}},"project":{{json (index .Config.Labels "com.docker.compose.project")}},"user":{{json .Config.User}}}'
                meta = json.loads(release.command(['docker', 'inspect', '--format', fmt, found]))
                if meta != {'source':TARGET_COMMIT, 'project':'naver-engine', 'user':'10001:10001'}:
                    raise ValueError('WARM_CONTAINER_ID')
                OPERATION = 'warm_cleanup_remove'
                release.command(['docker', 'rm', '--force', found], timeout=45)
            elif identity is None:
        # Late create after timeout.
                raise ValueError('WARM_CREATE_UNCONFIRMED')
            OPERATION = 'warm_cleanup_absence'
            if release.command(['docker', 'ps', '--all', '--no-trunc', '--filter',
                    'name=^/'+name+'$', '--format', '{{.ID}}'], timeout=30).strip():
                raise ValueError('WARM_CONTAINER_REMAINS')
        except Exception as error:
            refused = RuntimeError('WARM_CLEANUP_FAILED')
            refused.failure_details = {**(failure or _capture_failure(error)), **_capture_failure(error,'cleanup')}
            raise refused from None


def verify_running(path,receipt,release,lifecycle,upgrade):
    source=receipt.get('source_commit')
    if source not in (OLD_COMMIT,TARGET_COMMIT) or path.name!='naver-'+source:raise ValueError('CODE_PROBE_SOURCE')
    probe(release,source,upgrade)
    lifecycle._snapshot(release,path,receipt['images'])
    for unit in (lifecycle.TUNNEL,*lifecycle.UNITS):
        if lifecycle._state(release,unit,'ActiveState')!='active':raise ValueError('CODE_SERVICE_NOT_ACTIVE')
    for unit in lifecycle.UNITS:
        if lifecycle._state(release,unit,'UnitFileState')!='enabled':raise ValueError('CODE_SERVICE_NOT_ENABLED')
def apply(package, host, release, lifecycle, upgrade):
    global STAGE, OPERATION
    require_pins()
    STAGE = 'code_apply_preflight'
    OPERATION = 'package'
    if not isinstance(package, dict) or set(package) != {'release', 'operation_id'}:
        raise ValueError('CODE_APPLY_FIELDS')
    identity = package['operation_id']
    if not isinstance(identity, str) or not re.fullmatch('[0-9a-f]{32}', identity):
        raise ValueError('CODE_OPERATION_ID')
    prepared = validate_package(package['release'], release)
    OPERATION = 'current_state'
    old_path, old_receipt, old_files, _, bootstrap = current_state(prepared, host, release, lifecycle, upgrade)
    OPERATION = 'target_manifest'
    path, receipt = upgrade.manifest(release, TARGET_COMMIT, prepared)
    OPERATION = 'compatible_source'
    compatible_source(old_path, path, upgrade)
    OPERATION = 'unit_manifest'
    new_files = lifecycle.unit_files(path, pwd.getpwnam('www-data').pw_gid, release)
    if new_files[lifecycle.TMPFILES] != old_files[lifecycle.TMPFILES]:
        raise ValueError('TMPFILES_CHANGED')
    started = release.ROOT/'receipts'/('preview-start-'+TARGET_COMMIT+'.json')
    backup = release.ROOT/'receipts'/('code-upgrade-'+identity+'.json')
    if any(os.path.lexists(p) for p in (started, backup)):
        raise ValueError('CODE_ALREADY_ATTEMPTED')
    OPERATION = 'runtime_config_preflight'
    flags = target_runtime_flags(path, release, identity)
    OPERATION = 'runtime_old_config'
    if container_runtime_flags(old_path, old_receipt, release, lifecycle) != flags:
        raise ValueError('RUNTIME_CONFIG_DRIFT')
    OPERATION = 'database_preflight'
    database_preflight(release)
    OPERATION = 'write_recovery_receipt'
    release.write_new(backup, json.dumps({'source_commit':OLD_COMMIT,'target_commit':TARGET_COMMIT,
        'images':old_receipt['images'],'units':{str(p):b.decode() for p,b in old_files.items() if p!=lifecycle.TMPFILES}}, sort_keys=True).encode())
    replaced = []
    snapshot = None
    source_status = None
    try:
        STAGE = 'code_stop_isolated'
        for unit in reversed(lifecycle.UNITS):
            name = 'engine' if unit == lifecycle.UNITS[0] else 'relay'
            OPERATION = 'stop_'+name
            release.command(['/usr/bin/systemctl','stop',unit], timeout=90)
            OPERATION = 'stop_check_'+name
            stopped_writer(release, lifecycle, old_path, {OLD_COMMIT:old_receipt['images']}, unit)
        OPERATION = 'bootstrap_check'
        if bootstrap_state(release, upgrade) != bootstrap:
            raise ValueError('BOOTSTRAP_CHANGED')
        STAGE = 'account_database_snapshot'
        OPERATION = 'snapshot_create'
        snapshot = db_snapshot(identity, release, upgrade)
        STAGE = 'account_sources_warm'
        OPERATION = 'warm_sources'
        source_status = migrate_database(path, release)
        verify_database_schema(TARGET_COMMIT,release,upgrade)
        STAGE = 'code_recreate'
        for name in ('engine','relay'):
            OPERATION = 'recreate_'+name
            release.command(release.compose(path,name)+['up','--no-start','--no-build','--force-recreate'], timeout=90)
        STAGE = 'code_replace_units'
        for unit in lifecycle.UNITS:
            OPERATION = 'replace_unit_'+('engine' if unit == lifecycle.UNITS[0] else 'relay')
            target = lifecycle.UNIT_DIR/unit
            replaced.append(target)
            upgrade.replace_unit(target, old_files[target], new_files[target], identity, release)
        OPERATION = 'daemon_reload'
        release.command(['/usr/bin/systemctl','daemon-reload'])
        OPERATION = 'runtime_stopped_config'
        stopped_flags, stopped_container = stopped_container_runtime_flags(path,receipt,release,lifecycle)
        if stopped_flags != flags:
            raise ValueError('RUNTIME_CONFIG_DRIFT')
        STAGE = 'code_start'
        for unit in lifecycle.UNITS:
            OPERATION = 'start_'+('engine' if unit == lifecycle.UNITS[0] else 'relay')
            release.command(['/usr/bin/systemctl','start',unit], timeout=90)
        STAGE = 'code_verify'
        OPERATION = 'verify_running'
        verify_running(path, receipt, release, lifecycle, upgrade)
        OPERATION = 'runtime_target_config'
        if container_runtime_flags(path, receipt, release, lifecycle, target=True, expected=stopped_container) != flags:
            raise ValueError('RUNTIME_CONFIG_DRIFT')
        OPERATION = 'post_state'
        if host.baseline() != prepared['baseline'] or bootstrap_state(release, upgrade) != bootstrap:
            raise ValueError('CODE_POST_STATE')
        result = {'ok':True,'stage':'internal_ready','source_commit':TARGET_COMMIT,'previous_commit':OLD_COMMIT,
                  'nginx_changed':False,'legacy_containers_unchanged':True,'bootstrap_unchanged':True,
                  'operation_id':identity,'unauthenticated_read_status':401,'business_post_status':403}
        result.update(database_policy='paired-snapshot',database_opened_by_controller=True,
        collection_completion_verified=False,source_warmup_performed=False,
        result_gate='internal_only_actual_SSO_reads_Claude_PDF_pending',
        database_snapshot_verified=True, database_schema=TARGET_SCHEMA,
        source_status=source_status, rollback_requires_matching_database=True)
        result.update(flags, runtime_flags_verified=True)
        OPERATION = 'write_started_receipt'
        release.write_new(started, json.dumps(result, sort_keys=True).encode())
        return result
    except Exception as error:
        details = {key:value for key,value in failure_report(error).items()
                   if key.startswith(('failed_', 'cleanup_'))} or _capture_failure(error)
        STAGE = 'code_rollback'
        failed = str(error) == 'WARM_CLEANUP_FAILED'
        def attempt(function, *args, **kwargs):
            nonlocal failed
            try:
                function(*args, **kwargs)
                return True
            except Exception as rollback_error:
                if 'rollback_stage' not in details:
                    details.update(_capture_failure(rollback_error, 'rollback'))
                failed = True
                return False
        def restore(target):
            if upgrade.read_file(target, mode=0o644, maximum=32768) != old_files[target]:
                upgrade.replace_unit(target, new_files[target], old_files[target], identity+'-rollback', release)
        for unit in reversed(lifecycle.UNITS):
            OPERATION = 'stop_'+('engine' if unit == lifecycle.UNITS[0] else 'relay')
            attempt(release.command, ['/usr/bin/systemctl','stop',unit], timeout=90)
        for unit in lifecycle.UNITS:
            OPERATION = 'stop_check_'+('engine' if unit == lifecycle.UNITS[0] else 'relay')
            attempt(stopped_writer, release, lifecycle, old_path,
                    {OLD_COMMIT:old_receipt['images'], TARGET_COMMIT:receipt['images']}, unit)
        if not failed:
            for target in reversed(replaced):
                OPERATION = 'restore_unit_'+('engine' if target.name == lifecycle.UNITS[0] else 'relay')
                attempt(restore, target)
        if snapshot is not None and not failed:
            OPERATION = 'restore_database'
            attempt(restore_db, snapshot, identity, release, upgrade)
        OPERATION = 'old_manifest'
        if not failed and attempt(upgrade.manifest, release, OLD_COMMIT, started=True):
            for name in ('engine','relay'):
                OPERATION = 'recreate_'+name
                attempt(release.command, release.compose(old_path,name)+['up','--no-start','--no-build','--force-recreate'], timeout=90)
        if not failed:
            OPERATION = 'daemon_reload'
            attempt(release.command, ['/usr/bin/systemctl','daemon-reload'])
        if not failed:
            # Writers proven stopped: the rollback's only DB read.
            OPERATION = 'rollback_schema'
            attempt(verify_database_schema, OLD_COMMIT, release, upgrade)
        if not failed:
            for unit in lifecycle.UNITS:
                OPERATION = 'start_'+('engine' if unit == lifecycle.UNITS[0] else 'relay')
                if not attempt(release.command, ['/usr/bin/systemctl','start',unit], timeout=90):
                    break
            OPERATION = 'verify_running'
            attempt(verify_running, old_path, old_receipt, release, lifecycle, upgrade)
        try:
            OPERATION = 'rollback_state'
            if host.baseline() != prepared['baseline'] or bootstrap_state(release, upgrade) != bootstrap:
                failed = True
        except Exception:
            failed = True
        if failed:
            for unit in reversed(lifecycle.UNITS):
                attempt(release.command, ['/usr/bin/systemctl','stop',unit], timeout=90)
            refused = RuntimeError('CODE_ROLLBACK_FAILED')
        else:
            refused = RuntimeError('CODE_FAILED_ROLLED_BACK_DB_PRESERVED')
        refused.failure_details = details
        raise refused from None

FAILURE_CODES |= frozenset({'DB_SCHEMA_OBJECT','DB_ROW_BOUND','DB_ROWS_CHANGED','OLD_STATE_CHANGED','PREEXISTING_RELEASE'})


def rollback(package, host, release, lifecycle, upgrade):
    """Explicit post-success rollback to the *same apply's* code and DB snapshot.

    All post-upgrade DB files remain in private quarantine. Failure leaves both
    writers stopped; it never starts old code against a schema21 database.
    """
    global STAGE, OPERATION
    require_pins()
    STAGE,OPERATION='completion_rollback_preflight','package'
    if type(package) is not dict or set(package)!={'release','apply_operation_id','operation_id'}:
        raise ValueError('CODE_ROLLBACK_FIELDS')
    original,identity=package['apply_operation_id'],package['operation_id']
    if (any(type(value) is not str or re.fullmatch('[0-9a-f]{32}',value) is None for value in (original,identity)) or original==identity):
        raise ValueError('CODE_ROLLBACK_OPERATION_ID')
    prepared=validate_package(package['release'],release)
    if os.geteuid()!=0 or host.baseline()!=prepared['baseline']:raise ValueError('HOST_BASELINE')
    old,old_receipt=upgrade.manifest(release,OLD_COMMIT,started=True)
    target,receipt=upgrade.manifest(release,TARGET_COMMIT,prepared,started=True)
    for row,digest in ((old_receipt,OLD_SOURCE_SHA256),(receipt,TARGET_SOURCE_SHA256)):
        if row['package'].get('baseline')!=prepared['baseline'] or row['package'].get('source_tar_gz_sha256')!=digest:
            raise ValueError('CODE_ROLLBACK_SOURCE')
    compatible_inverse_source(target,old,upgrade)
    files=lifecycle.unit_files(target,pwd.getpwnam('www-data').pw_gid,release)
    old_files=lifecycle.unit_files(old,pwd.getpwnam('www-data').pw_gid,release)
    if files[lifecycle.TMPFILES]!=old_files[lifecycle.TMPFILES]:raise ValueError('TMPFILES_CHANGED')
    for parent in (lifecycle.UNIT_DIR,lifecycle.TMPFILES.parent,release.ROOT/'receipts'):release.trusted_dir(parent)
    for filename,body in files.items():
        if upgrade.read_file(filename,mode=0o644,maximum=32768)!=body:raise ValueError('CODE_ROLLBACK_UNIT')
    # A broken target HTTP/UI is a reason to roll back, not a refusal condition.
    # The exact files/images/units above plus stopped_writer below bind identity.
    if lifecycle._state(release,'docker.service','ActiveState')!='active':raise ValueError('DEPENDENCY_NOT_ACTIVE')
    paths={name:release.ROOT/'receipts'/filename for name,filename in (
        ('saved','code-upgrade-'+original+'.json'),('started','preview-start-'+TARGET_COMMIT+'.json'),
        ('snapshot','completion-snapshot-'+original+'.json'))}
    read=lambda filename:upgrade.read_file(filename,mode=0o600,maximum=32768)
    raw={name:read(path) for name,path in paths.items()}
    docs={name:json.loads(body,object_pairs_hook=release.unique) for name,body in raw.items()}
    expected_saved={'source_commit':OLD_COMMIT,'target_commit':TARGET_COMMIT,'images':old_receipt['images'],
        'units':{str(p):b.decode() for p,b in old_files.items() if p!=lifecycle.TMPFILES}}
    if docs['saved']!=expected_saved:raise ValueError('CODE_ROLLBACK_RECOVERY')
    started=docs['started']
    if (type(started) is not dict or started.get('ok') is not True or started.get('stage')!='internal_ready'
        or started.get('source_commit')!=TARGET_COMMIT or started.get('previous_commit')!=OLD_COMMIT
        or started.get('operation_id')!=original or started.get('database_policy')!='paired-snapshot'
        or started.get('database_snapshot_verified') is not True or started.get('database_schema')!=TARGET_SCHEMA):
        raise ValueError('CODE_ROLLBACK_STARTED')
    snap=docs['snapshot']
    if (type(snap) is not dict or set(snap)!={'source_commit','target_commit','operation_id','database_sha256','schema','snapshot_restore_verified'}
        or snap['source_commit']!=OLD_COMMIT or snap['target_commit']!=TARGET_COMMIT or snap['operation_id']!=original
        or type(snap['database_sha256']) is not str or re.fullmatch('[0-9a-f]{64}',snap['database_sha256']) is None
        or type(snap['schema']) is not int or snap['schema']!=OLD_SCHEMA or snap['snapshot_restore_verified'] is not True):
        raise ValueError('CODE_ROLLBACK_RECOVERY')
    snapshot=(release.ROOT/'receipts'/('completion-db-'+original+'.sqlite'),snap['database_sha256'])
    bootstrap=bootstrap_state(release,upgrade)
    attempt=release.ROOT/'receipts'/('completion-post-rollback-'+identity+'.json')
    result_path=attempt.with_name('completion-post-rollback-'+identity+'.result.json')
    if any(os.path.lexists(path) for path in (attempt,result_path)):raise ValueError('CODE_ROLLBACK_ALREADY_ATTEMPTED')
    release.write_new(attempt,json.dumps({'source_commit':TARGET_COMMIT,'target_commit':OLD_COMMIT,
        'apply_operation_id':original,'operation_id':identity,'database_policy':'matching-apply-snapshot'},sort_keys=True).encode())
    def unchanged():
        require_pins()
        if (host.baseline()!=prepared['baseline'] or bootstrap_state(release,upgrade)!=bootstrap
            or any(read(paths[name])!=body for name,body in raw.items())):raise ValueError('CODE_ROLLBACK_STATE')
        if (upgrade.manifest(release,OLD_COMMIT,started=True)!=(old,old_receipt)
            or upgrade.manifest(release,TARGET_COMMIT,prepared,started=True)!=(target,receipt)):
            raise ValueError('CODE_ROLLBACK_SOURCE')
        compatible_inverse_source(target,old,upgrade)
    try:
        STAGE='completion_rollback_stop'
        for unit in reversed(lifecycle.UNITS):release.command(['/usr/bin/systemctl','stop',unit],timeout=90)
        for unit in lifecycle.UNITS:stopped_writer(release,lifecycle,target,{TARGET_COMMIT:receipt['images']},unit)
        unchanged()
        OPERATION='rollback_schema';verify_database_schema(TARGET_COMMIT,release,upgrade)
        STAGE='completion_rollback_restore';OPERATION='restore_database'
        restore_db(snapshot,original,release,upgrade)
        for name in ('engine','relay'):
            release.command(release.compose(old,name)+['up','--no-start','--no-build','--force-recreate'],timeout=90)
        for unit in reversed(lifecycle.UNITS):
            filename=lifecycle.UNIT_DIR/unit
            upgrade.replace_unit(filename,files[filename],old_files[filename],identity,release)
        release.command(['/usr/bin/systemctl','daemon-reload'])
        unchanged();verify_database_schema(OLD_COMMIT,release,upgrade)
        STAGE='completion_rollback_start'
        for unit in lifecycle.UNITS:release.command(['/usr/bin/systemctl','start',unit],timeout=90)
        STAGE='completion_rollback_verify';verify_running(old,old_receipt,release,lifecycle,upgrade)
        for filename,body in old_files.items():
            if upgrade.read_file(filename,mode=0o644,maximum=32768)!=body:raise ValueError('CODE_ROLLBACK_UNIT')
        unchanged()
        result={'ok':True,'stage':'internal_ready','operation':'completion-rollback','source_commit':OLD_COMMIT,
            'previous_commit':TARGET_COMMIT,'operation_id':identity,'apply_operation_id':original,
            'database_policy':'matching-apply-snapshot','database_schema':OLD_SCHEMA,
            'database_opened_by_controller':True,'new_database_quarantined':True,'source_warmup_performed':False,'nginx_changed':False}
        release.write_new(result_path,json.dumps(result,sort_keys=True).encode())
        return result
    except Exception as error:
        details=_capture_failure(error)
        STAGE='completion_rollback_failed_stop';verified=True
        for unit in reversed(lifecycle.UNITS):
            try:release.command(['/usr/bin/systemctl','stop',unit],timeout=90)
            except Exception:verified=False
        for unit in lifecycle.UNITS:
            try:stopped_writer(release,lifecycle,target,{OLD_COMMIT:old_receipt['images'],TARGET_COMMIT:receipt['images']},unit)
            except Exception:verified=False
        refused=RuntimeError('CODE_POST_ROLLBACK_FAILED');refused.failure_details={**details,'isolated_stop_verified':verified}
        raise refused from None


FAILURE_STAGES |= frozenset({'completion_rollback_preflight','completion_rollback_stop','completion_rollback_restore',
    'completion_rollback_start','completion_rollback_verify','completion_rollback_failed_stop'})
FAILURE_CODES |= frozenset({'CODE_ROLLBACK_FIELDS','CODE_ROLLBACK_OPERATION_ID','CODE_ROLLBACK_SOURCE','CODE_ROLLBACK_UNIT',
    'CODE_ROLLBACK_RECOVERY','CODE_ROLLBACK_STARTED','CODE_ROLLBACK_ALREADY_ATTEMPTED','CODE_ROLLBACK_STATE','CODE_POST_ROLLBACK_FAILED'})
FAILURE_OPERATIONS |= frozenset({'migration_start','migration_apply'})
FAILURE_OPERATIONS |= frozenset({'database_preflight'})
