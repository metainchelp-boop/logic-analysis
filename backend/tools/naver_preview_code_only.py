"""Gated, schema-compatible code replacement without controller DB access.

The explicit workflow modes accept only the separate reviewed source/archive/store
transitions sealed below. Their file scopes are not interchangeable.
"""
import json
import os
import pwd
import re

# Reviewed 6198be3 -> e4f64e1 transition. Never derive this approval from request input.
# Tuple: old/new commit, old/new archive SHA256, old/new store SHA256, host baseline.
REVIEWED_TRANSITION = (
    '6198be366344a82923e10ba5e323877026d82f48',
    'e4f64e165ebdf81d4127218d5c91ff6904e75958',
    'b9071a746aa1879d518849bb5a76a8d2259a5d77853e28298fcd26fc7ea0d90e',
    '716d849b68d72cb03489bc16da1cee3d9a0f31cb16612287b407fe244dea84c6',
    '5fa2618f3d74bdfaa10581f6ac759d605544ab0e0e8178eef89f68d8e6840c94',
    '5fa2618f3d74bdfaa10581f6ac759d605544ab0e0e8178eef89f68d8e6840c94',
    '5463ca7b23575f668062e842f551170937239e625fb5a6104655c031c7e31d76',
)
REVIEWED_TRANSITION_V3 = (
    'e4f64e165ebdf81d4127218d5c91ff6904e75958',
    '953c2ccdb1d74a4fd339de013a1bbbbc5f50e3b6',
    '716d849b68d72cb03489bc16da1cee3d9a0f31cb16612287b407fe244dea84c6',
    '461be6b6ae6d09d74108f9f96a5e2bcf68feffdd2728c43f1b5e460be743ac80',
    '5fa2618f3d74bdfaa10581f6ac759d605544ab0e0e8178eef89f68d8e6840c94',
    'f33f8ca29633ae6cda46fd721d9cbf3bdf63969ac69059434a1a159562778862',
    '5463ca7b23575f668062e842f551170937239e625fb5a6104655c031c7e31d76',
)
REVIEWED_TRANSITION_V4 = (
    '953c2ccdb1d74a4fd339de013a1bbbbc5f50e3b6',
    '49c42d645b90732071d0c61b8f9aaf7660e8b765',
    '461be6b6ae6d09d74108f9f96a5e2bcf68feffdd2728c43f1b5e460be743ac80',
    '69b9f79ab243eac6d3d32fe67ce267b96bdd923323997fd2661934bc6a5459d4',
    'f33f8ca29633ae6cda46fd721d9cbf3bdf63969ac69059434a1a159562778862',
    'f33f8ca29633ae6cda46fd721d9cbf3bdf63969ac69059434a1a159562778862',
    '5463ca7b23575f668062e842f551170937239e625fb5a6104655c031c7e31d76',
)
# Reviewed final login/read-budget release: exact Linux3.12 archive and product scope.
REVIEWED_TRANSITION_V5 = (
    '49c42d645b90732071d0c61b8f9aaf7660e8b765',
    '74b79ce6381178abf9b74fff43b0fcb03c5aa60b',
    '69b9f79ab243eac6d3d32fe67ce267b96bdd923323997fd2661934bc6a5459d4',
    '7136119034645500fa31cd1afb85d72b70264144ab62d0181ada6e06ec0484cf',
    'f33f8ca29633ae6cda46fd721d9cbf3bdf63969ac69059434a1a159562778862',
    'f33f8ca29633ae6cda46fd721d9cbf3bdf63969ac69059434a1a159562778862',
    '5463ca7b23575f668062e842f551170937239e625fb5a6104655c031c7e31d76',
)


# Reviewed collection-status reader correction: exact two-file scope, DB unchanged.
REVIEWED_TRANSITION_V6 = (
    '74b79ce6381178abf9b74fff43b0fcb03c5aa60b',
    '383c8511964c13e24e884a4cee561fc9bee64102',
    '7136119034645500fa31cd1afb85d72b70264144ab62d0181ada6e06ec0484cf',
    'a55b8a3a4b87e69b936778298ef95be41241ebdbd322fe5fa467883543b2229e',
    'f33f8ca29633ae6cda46fd721d9cbf3bdf63969ac69059434a1a159562778862',
    'f33f8ca29633ae6cda46fd721d9cbf3bdf63969ac69059434a1a159562778862',
    '5463ca7b23575f668062e842f551170937239e625fb5a6104655c031c7e31d76',
)

# Reviewed observation-only release: normal authenticated timing and actual completed report slices.
REVIEWED_TRANSITION_V7 = (
    '383c8511964c13e24e884a4cee561fc9bee64102',
    '96f10f05b0e92651e04b2076999fa6c6ace7291e',
    'a55b8a3a4b87e69b936778298ef95be41241ebdbd322fe5fa467883543b2229e',
    'a58f46db0367b9b03deb6f141b080b10bbe1d51c7ce91b3265497e9b9c20856f',
    'f33f8ca29633ae6cda46fd721d9cbf3bdf63969ac69059434a1a159562778862',
    'f33f8ca29633ae6cda46fd721d9cbf3bdf63969ac69059434a1a159562778862',
    '5463ca7b23575f668062e842f551170937239e625fb5a6104655c031c7e31d76',
)


# Reviewed loading-read release: exact three product files, Store/schema unchanged.
REVIEWED_TRANSITION_V8 = (
    '96f10f05b0e92651e04b2076999fa6c6ace7291e',
    '7985925dcc4ed9d75c28ae43a456964cdc78c63f',
    'a58f46db0367b9b03deb6f141b080b10bbe1d51c7ce91b3265497e9b9c20856f',
    '47632d4d3403c24dd4988b80c1a0ada25cc155fc6048a7f2413fb72d84ea73ff',
    'f33f8ca29633ae6cda46fd721d9cbf3bdf63969ac69059434a1a159562778862',
    'f33f8ca29633ae6cda46fd721d9cbf3bdf63969ac69059434a1a159562778862',
    '5463ca7b23575f668062e842f551170937239e625fb5a6104655c031c7e31d76',
)


# Reviewed V9: exact source, archive, memo scope and resource decision.
REVIEWED_TRANSITION_V9 = (
    '7985925dcc4ed9d75c28ae43a456964cdc78c63f', 'bd08fd07281ae5448bffb3de3d7c405887bfecd9',
    '47632d4d3403c24dd4988b80c1a0ada25cc155fc6048a7f2413fb72d84ea73ff', '6b1618ab9dd47eca6030d1092bdbce1d451d30ce8fdf103e448a96f3ac9da3f1',
    'f33f8ca29633ae6cda46fd721d9cbf3bdf63969ac69059434a1a159562778862', 'f33f8ca29633ae6cda46fd721d9cbf3bdf63969ac69059434a1a159562778862', '5463ca7b23575f668062e842f551170937239e625fb5a6104655c031c7e31d76',
)
REVIEWED_RESOURCE_LIMITS_V9 = True


# Reviewed V10 diagnostics: exact source/archive and one product path only.
REVIEWED_TRANSITION_V10 = (
    'bd08fd07281ae5448bffb3de3d7c405887bfecd9', '3fa096d3d383123fdd3469c5dc68404171a6f076', '6b1618ab9dd47eca6030d1092bdbce1d451d30ce8fdf103e448a96f3ac9da3f1', '1a528165dae3f2e896d98e950f1b92369f997af2ce4e2d823febb7b18c86a6de',
    'f33f8ca29633ae6cda46fd721d9cbf3bdf63969ac69059434a1a159562778862', 'f33f8ca29633ae6cda46fd721d9cbf3bdf63969ac69059434a1a159562778862', '5463ca7b23575f668062e842f551170937239e625fb5a6104655c031c7e31d76',
)

# V11 exact read performance transition: parent target/archive/Store pins are closed placeholders.
REVIEWED_TRANSITION_V11 = (
    '3fa096d3d383123fdd3469c5dc68404171a6f076', '9bfcace1c6ba2a49807c5ec8feb69fde11de73bf', '1a528165dae3f2e896d98e950f1b92369f997af2ce4e2d823febb7b18c86a6de', '1acf8f5d9f54d075655ed263026a77745b75548bbee8fd66a2286aeee404628e',
    'f33f8ca29633ae6cda46fd721d9cbf3bdf63969ac69059434a1a159562778862', 'de9d1fe5886055d07261bc41687666cfe5f800fe582a02057910026ef564ca53', '5463ca7b23575f668062e842f551170937239e625fb5a6104655c031c7e31d76',
)


# V12 manual diagnostics: no authority until all independently reviewed pins exist.
REVIEWED_TRANSITION_V12 = ('9bfcace1c6ba2a49807c5ec8feb69fde11de73bf', '3145da9e3021aed0c06d17f2e51525fc866f8799', '1acf8f5d9f54d075655ed263026a77745b75548bbee8fd66a2286aeee404628e', '14a72af0ee951d54ea05a0c176bb3c2ffdd5e14fdd4380aafd8ba6ad5e31ee7d', 'de9d1fe5886055d07261bc41687666cfe5f800fe582a02057910026ef564ca53', '055106d6811a998b1265b893f4150c2590a3fbaea4b7a48d8fd48d1a78462431', '5463ca7b23575f668062e842f551170937239e625fb5a6104655c031c7e31d76')


# V13 exact history-read release: pending pins do not confer authority.
REVIEWED_TRANSITION_V13 = ('3145da9e3021aed0c06d17f2e51525fc866f8799', 'ecb26ccee4aa8d85b0101e0d59aeafe48de1166b', '14a72af0ee951d54ea05a0c176bb3c2ffdd5e14fdd4380aafd8ba6ad5e31ee7d', '6c0f7382676584a5d2c01fd0d54b169210293a58c654c70e5638e4fad2cbfcad', '055106d6811a998b1265b893f4150c2590a3fbaea4b7a48d8fd48d1a78462431', 'be894a56d4b548700b14c2d8ffd95669ebfac73ead8e6521fb50a5bc9add14af', '5463ca7b23575f668062e842f551170937239e625fb5a6104655c031c7e31d76')


# V14 is closed until target/archive/Store pins are reviewed.
REVIEWED_TRANSITION_V14 = ('ecb26ccee4aa8d85b0101e0d59aeafe48de1166b', '153c9a3a89585b00f2973a694a963ae9227ce19d', '6c0f7382676584a5d2c01fd0d54b169210293a58c654c70e5638e4fad2cbfcad', 'd9be1b9e6225c856d06b8b6e2d5f1e91edfa46a2cb0aa94d4f17497877eceaf8', 'be894a56d4b548700b14c2d8ffd95669ebfac73ead8e6521fb50a5bc9add14af', 'ccb0474dd764d06bb375cd298eb01b333a6503d8db06d3784f2f7599d19afe97', '5463ca7b23575f668062e842f551170937239e625fb5a6104655c031c7e31d76')

# Reviewed V15 page-size transition; only the exact target/archive/Store pins are admitted.
REVIEWED_TRANSITION_V15 = ('153c9a3a89585b00f2973a694a963ae9227ce19d', '702bc6ed3f224638524511a6ef7d43b6dd825343', 'd9be1b9e6225c856d06b8b6e2d5f1e91edfa46a2cb0aa94d4f17497877eceaf8', '5ad8a0e90e37c9025cf2e3e91ccb1c7db9f3fa6b05b17668a4b873ed6983723f', 'ccb0474dd764d06bb375cd298eb01b333a6503d8db06d3784f2f7599d19afe97', 'cc050c8c3d8c0d2a8e4977ec0e8e5b271ff7fc932a8d35a6c0f10dadc11ddb56', '5463ca7b23575f668062e842f551170937239e625fb5a6104655c031c7e31d76')

# V16 exact three-asset transition.
REVIEWED_TRANSITION_V16 = ('702bc6ed3f224638524511a6ef7d43b6dd825343', '6a0c54de9faffbf65ecee2ce57759598794bc005', '5ad8a0e90e37c9025cf2e3e91ccb1c7db9f3fa6b05b17668a4b873ed6983723f', 'f2570d3e1429f9593e7e4a1d559a4aec6665654ea0ed435d162cd8426d1cacc9', 'cc050c8c3d8c0d2a8e4977ec0e8e5b271ff7fc932a8d35a6c0f10dadc11ddb56', 'cc050c8c3d8c0d2a8e4977ec0e8e5b271ff7fc932a8d35a6c0f10dadc11ddb56', '5463ca7b23575f668062e842f551170937239e625fb5a6104655c031c7e31d76')

# V17 exact PDF-filename transition; pending pins grant no authority.
REVIEWED_TRANSITION_V17 = ('6a0c54de9faffbf65ecee2ce57759598794bc005', '7c99e18e29e6cb4d3f32eb41b6983529126d8f3a', 'f2570d3e1429f9593e7e4a1d559a4aec6665654ea0ed435d162cd8426d1cacc9', '874ea72edfef7c5a375f26cf8bdb103aa487779bd06e208aada7b1a5184dcee2', 'cc050c8c3d8c0d2a8e4977ec0e8e5b271ff7fc932a8d35a6c0f10dadc11ddb56', 'cc050c8c3d8c0d2a8e4977ec0e8e5b271ff7fc932a8d35a6c0f10dadc11ddb56', '5463ca7b23575f668062e842f551170937239e625fb5a6104655c031c7e31d76')

REVIEWED_OLD_REPORT_PDF_V17 = (34829, '62bf0c08ca70d5d02bb28ac6e69d1b6f4caa5195ca4ff2478a2e269dad60d539', 'text/javascript; charset=utf-8')

# V18 exact report freshness transition.
REVIEWED_TRANSITION_V18 = ('7c99e18e29e6cb4d3f32eb41b6983529126d8f3a', '7f32d70d97876b806cc5bc44a7cc0f9688caeada', '874ea72edfef7c5a375f26cf8bdb103aa487779bd06e208aada7b1a5184dcee2', 'd6a2d1fe521287c9cedfba1132e5a81164ed2e2745ddea7ea01d74c2beb80a13', 'cc050c8c3d8c0d2a8e4977ec0e8e5b271ff7fc932a8d35a6c0f10dadc11ddb56', 'b01a1e21cc87df1ef5a3935a30cc25d96b0ec3ced0fcc42a2bc9999685ef7d95', '5463ca7b23575f668062e842f551170937239e625fb5a6104655c031c7e31d76')
REVIEWED_OLD_REPORT_UI_V18 = (60450, 'c629f0f2485f9ba5d524b6cbf1329e562958b7099fad5b568c944a03ec855cb8', 'text/javascript; charset=utf-8')

def code_module_name(source_commit):
    if type(source_commit) is str and source_commit == REVIEWED_TRANSITION[1]:
        return 'naver_preview_code_upgrade'
    if type(source_commit) is str and source_commit == REVIEWED_TRANSITION_V3[1]:
        return 'naver_preview_code_upgrade_v3'
    if type(source_commit) is str and source_commit == REVIEWED_TRANSITION_V4[1]:
        return 'naver_preview_code_upgrade_v4'
    if type(source_commit) is str and source_commit == REVIEWED_TRANSITION_V5[1]:
        return 'naver_preview_code_upgrade_v5'
    if type(source_commit) is str and source_commit == REVIEWED_TRANSITION_V6[1]:
        return 'naver_preview_code_upgrade_v6'
    if type(source_commit) is str and source_commit == REVIEWED_TRANSITION_V7[1]:
        return 'naver_preview_code_upgrade_v7'
    if type(source_commit) is str and source_commit == REVIEWED_TRANSITION_V8[1]:
        return 'naver_preview_code_upgrade_v8'
    if (type(source_commit) is str and type(REVIEWED_TRANSITION_V9[1]) is str
            and source_commit == REVIEWED_TRANSITION_V9[1]
            and re.fullmatch('[0-9a-f]{40}', REVIEWED_TRANSITION_V9[1])
            and type(REVIEWED_TRANSITION_V9[3]) is str
            and re.fullmatch('[0-9a-f]{64}', REVIEWED_TRANSITION_V9[3])
            and type(REVIEWED_RESOURCE_LIMITS_V9) is bool):
        return 'naver_preview_code_upgrade_v9'
    if (type(source_commit) is str and type(REVIEWED_TRANSITION_V10[1]) is str
            and source_commit == REVIEWED_TRANSITION_V10[1]
            and re.fullmatch('[0-9a-f]{40}', REVIEWED_TRANSITION_V10[1])
            and type(REVIEWED_TRANSITION_V10[3]) is str
            and re.fullmatch('[0-9a-f]{64}', REVIEWED_TRANSITION_V10[3])):
        return 'naver_preview_code_upgrade_v10'
    if (type(source_commit) is str and type(REVIEWED_TRANSITION_V11[1]) is str
            and source_commit == REVIEWED_TRANSITION_V11[1]
            and re.fullmatch('[0-9a-f]{40}', REVIEWED_TRANSITION_V11[1])
            and all(type(REVIEWED_TRANSITION_V11[index]) is str
                and re.fullmatch('[0-9a-f]{64}', REVIEWED_TRANSITION_V11[index]) for index in (3, 4, 5))):
        return 'naver_preview_code_upgrade_v11'
    if (type(source_commit) is str and type(REVIEWED_TRANSITION_V12[1]) is str
            and source_commit == REVIEWED_TRANSITION_V12[1]
            and re.fullmatch('[0-9a-f]{40}', REVIEWED_TRANSITION_V12[1])
            and all(type(REVIEWED_TRANSITION_V12[index]) is str
                and re.fullmatch('[0-9a-f]{64}', REVIEWED_TRANSITION_V12[index]) for index in (3, 4, 5))):
        return 'naver_preview_code_upgrade_v12'
    if (type(source_commit) is str and type(REVIEWED_TRANSITION_V13[1]) is str
            and source_commit == REVIEWED_TRANSITION_V13[1]
            and re.fullmatch('[0-9a-f]{40}', REVIEWED_TRANSITION_V13[1])
            and all(type(REVIEWED_TRANSITION_V13[index]) is str
                and re.fullmatch('[0-9a-f]{64}', REVIEWED_TRANSITION_V13[index]) for index in (3, 4, 5))):
        return 'naver_preview_code_upgrade_v13'
    if (type(source_commit) is str and type(REVIEWED_TRANSITION_V14[1]) is str
            and source_commit == REVIEWED_TRANSITION_V14[1]
            and re.fullmatch('[0-9a-f]{40}', REVIEWED_TRANSITION_V14[1])
            and all(type(REVIEWED_TRANSITION_V14[index]) is str
                and re.fullmatch('[0-9a-f]{64}', REVIEWED_TRANSITION_V14[index]) for index in (3, 4, 5))):
        return 'naver_preview_code_upgrade_v14'
    if (type(source_commit) is str and type(REVIEWED_TRANSITION_V15[1]) is str
            and source_commit == REVIEWED_TRANSITION_V15[1]
            and re.fullmatch('[0-9a-f]{40}', REVIEWED_TRANSITION_V15[1])
            and all(type(REVIEWED_TRANSITION_V15[index]) is str
                and re.fullmatch('[0-9a-f]{64}', REVIEWED_TRANSITION_V15[index]) for index in (3, 4, 5))):
        return 'naver_preview_code_upgrade_v15'
    if (type(source_commit) is str and type(REVIEWED_TRANSITION_V16[1]) is str
            and source_commit == REVIEWED_TRANSITION_V16[1]
            and re.fullmatch('[0-9a-f]{40}', REVIEWED_TRANSITION_V16[1])
            and all(type(REVIEWED_TRANSITION_V16[index]) is str
                and re.fullmatch('[0-9a-f]{64}', REVIEWED_TRANSITION_V16[index]) for index in (3, 4, 5))):
        return 'naver_preview_code_upgrade_v16'
    if (type(source_commit) is str and type(REVIEWED_TRANSITION_V17[1]) is str
            and source_commit == REVIEWED_TRANSITION_V17[1]
            and re.fullmatch('[0-9a-f]{40}', REVIEWED_TRANSITION_V17[1])
            and all(type(REVIEWED_TRANSITION_V17[index]) is str
                and re.fullmatch('[0-9a-f]{64}', REVIEWED_TRANSITION_V17[index]) for index in (3, 4, 5))):
        return 'naver_preview_code_upgrade_v17'
    if (type(source_commit) is str and type(REVIEWED_TRANSITION_V18[1]) is str
            and source_commit == REVIEWED_TRANSITION_V18[1]
            and re.fullmatch('[0-9a-f]{40}', REVIEWED_TRANSITION_V18[1])
            and all(type(REVIEWED_TRANSITION_V18[index]) is str
                and re.fullmatch('[0-9a-f]{64}', REVIEWED_TRANSITION_V18[index]) for index in (3, 4, 5))):
        return 'naver_preview_code_upgrade_v18'
    raise ValueError('CODE_ONLY_RELEASE_NOT_REVIEWED')


def require_review(code):
    transition = (code.OLD_COMMIT, code.TARGET_COMMIT, code.OLD_SOURCE_SHA256,
                  code.TARGET_SOURCE_SHA256, code.STORE_SHA256.get('old'),
                  code.STORE_SHA256.get('target'), code.EXPECTED_BASELINE)
    expected_paths = ({'naver_engine/catalog_links.py', 'naver_engine/dashboard.py', 'naver_engine/inventory.py'}
        if transition == REVIEWED_TRANSITION else
        {'naver_engine/inventory.py', 'naver_engine/store.py', 'naver_engine/naver_read.py', 'naver_engine/morning.py'}
        if transition == REVIEWED_TRANSITION_V3 else
        {'backend/naver_page/app.js', 'backend/naver_page/index.html', 'naver_engine/naver_read.py'}
        if transition == REVIEWED_TRANSITION_V4 else
        {'backend/app/naver_auto/matching.py', 'naver_engine/inventory.py',
         'naver_engine/naver_read.py', 'naver_runtime/scheduler.py',
         'naver_engine/management_store.py', 'naver_runtime/writer.py', 'naver_engine/web.py'}
        if transition == REVIEWED_TRANSITION_V5 else
        {'naver_engine/web.py', 'naver_runtime/scheduler.py'}
        if transition == REVIEWED_TRANSITION_V6 else
        {'naver_engine/web.py', 'naver_runtime/scheduler.py', 'naver_runtime/runtime_status.py'}
        if transition == REVIEWED_TRANSITION_V7 else
        {'backend/naver_page/app.js', 'naver_engine/views.py', 'naver_engine/web.py'}
        if transition == REVIEWED_TRANSITION_V8 else
        {'naver_engine/inventory.py', 'naver_engine/management_store.py'} |
        ({'compose.naver-engine.yml'} if REVIEWED_RESOURCE_LIMITS_V9 is True else set())
        if (transition == REVIEWED_TRANSITION_V9
            and type(REVIEWED_RESOURCE_LIMITS_V9) is bool
            and getattr(code, 'RESOURCE_LIMITS_APPROVED', None) is REVIEWED_RESOURCE_LIMITS_V9
            and type(transition[1]) is str and re.fullmatch('[0-9a-f]{40}', transition[1])
            and type(transition[3]) is str and re.fullmatch('[0-9a-f]{64}', transition[3])) else
        {'naver_engine/web.py'}
        if (transition == REVIEWED_TRANSITION_V10
            and type(transition[1]) is str and re.fullmatch('[0-9a-f]{40}', transition[1])
            and type(transition[3]) is str and re.fullmatch('[0-9a-f]{64}', transition[3])) else
        {'naver_engine/store.py', 'naver_engine/inventory.py', 'naver_engine/dashboard.py', 'naver_engine/web.py'}
        if (transition == REVIEWED_TRANSITION_V11
            and type(transition[1]) is str and re.fullmatch('[0-9a-f]{40}', transition[1])
            and all(type(transition[index]) is str and re.fullmatch('[0-9a-f]{64}', transition[index])
                for index in (3, 4, 5))) else {'naver_engine/store.py', 'naver_engine/web.py', 'naver_engine/views.py', 'backend/naver_page/app.js', 'naver_runtime/writer.py', 'naver_runtime/__main__.py', 'naver_engine/collection_diagnostics.py'}
        if (transition == REVIEWED_TRANSITION_V12
            and type(transition[1]) is str and re.fullmatch('[0-9a-f]{40}', transition[1])
            and all(type(transition[index]) is str and re.fullmatch('[0-9a-f]{64}', transition[index])
                for index in (3, 4, 5))) else {'naver_engine/store.py', 'naver_engine/inventory.py', 'naver_engine/web.py'}
        if (transition == REVIEWED_TRANSITION_V13
            and type(transition[1]) is str and re.fullmatch('[0-9a-f]{40}', transition[1])
            and all(type(transition[index]) is str and re.fullmatch('[0-9a-f]{64}', transition[index])
                for index in (3, 4, 5))) else {'naver_engine/reporting.py', 'naver_engine/report_views.py', 'naver_engine/store.py', 'naver_engine/web.py', 'backend/naver_page/report-ui.js', 'backend/naver_page/report-pdf.js', 'backend/naver_page/app.css', 'backend/naver_page/app.js', 'naver_engine/report_enrichment.py', 'naver_engine/report_notes.py'}
        if (transition == REVIEWED_TRANSITION_V14
            and type(transition[1]) is str and re.fullmatch('[0-9a-f]{40}', transition[1])
            and all(type(transition[index]) is str and re.fullmatch('[0-9a-f]{64}', transition[index])
                for index in (3, 4, 5))) else {'naver_engine/report_views.py', 'naver_engine/store.py'}
        if (transition == REVIEWED_TRANSITION_V15
            and type(transition[1]) is str and re.fullmatch('[0-9a-f]{40}', transition[1])
            and all(type(transition[index]) is str and re.fullmatch('[0-9a-f]{64}', transition[index])
                for index in (3, 4, 5))) else {'backend/naver_page/report-ui.js', 'backend/naver_page/report-pdf.js', 'backend/naver_page/app.css'}
        if (transition == REVIEWED_TRANSITION_V16
            and type(transition[1]) is str and re.fullmatch('[0-9a-f]{40}', transition[1])
            and all(type(transition[index]) is str and re.fullmatch('[0-9a-f]{64}', transition[index])
                for index in (3, 4, 5))) else {'backend/naver_page/report-pdf.js'}
        if (transition == REVIEWED_TRANSITION_V17
            and type(transition[1]) is str and re.fullmatch('[0-9a-f]{40}', transition[1])
            and all(type(transition[index]) is str and re.fullmatch('[0-9a-f]{64}', transition[index])
                for index in (3, 4, 5))) else {'naver_engine/report_refresh.py', 'naver_engine/report_views.py', 'naver_engine/store.py', 'backend/naver_page/report-ui.js'}
        if (transition == REVIEWED_TRANSITION_V18
            and type(transition[1]) is str and re.fullmatch('[0-9a-f]{40}', transition[1])
            and all(type(transition[index]) is str and re.fullmatch('[0-9a-f]{64}', transition[index])
                for index in (3, 4, 5))) else None)
    if transition == REVIEWED_TRANSITION_V14 and (
            getattr(code, 'ADDED_SOURCE_PATHS', None) != frozenset({'naver_engine/report_enrichment.py', 'naver_engine/report_notes.py'})
            or getattr(code, 'TARGET_ACTION_ROUTES', None) != ('/reports/notes',)):
        raise ValueError('CODE_ONLY_RELEASE_NOT_REVIEWED')
    if transition in (REVIEWED_TRANSITION_V15, REVIEWED_TRANSITION_V16, REVIEWED_TRANSITION_V17) and (
            getattr(code, 'ADDED_SOURCE_PATHS', None) != frozenset()
            or getattr(code, 'TARGET_ACTION_ROUTES', None) != ('/reports/notes',)
            or getattr(code, 'OWNER_ACTION_ROUTES', None) != (
                '/issues/1/ack', '/issues/1/resolve', '/issues/1/except', '/bell/1/read', '/bell/read-all',
                '/settings/thresholds', '/holds/org/confirm', '/holds/stages/confirm', '/holds/accounts/confirm', '/links/revoke')
            or getattr(code, 'CLOSED_LINK_ROUTES', None) != ('/links/reject', '/links/preview')):
        raise ValueError('CODE_ONLY_RELEASE_NOT_REVIEWED')
    if transition == REVIEWED_TRANSITION_V17 and getattr(code, 'OLD_REPORT_PDF', None) != REVIEWED_OLD_REPORT_PDF_V17:
        raise ValueError('CODE_ONLY_RELEASE_NOT_REVIEWED')
    if transition == REVIEWED_TRANSITION_V18 and (
            getattr(code, 'ADDED_SOURCE_PATHS', None) != frozenset({'naver_engine/report_refresh.py'})
            or getattr(code, 'TARGET_ACTION_ROUTES', None) != ('/reports/notes',)
            or getattr(code, 'OWNER_ACTION_ROUTES', None) != (
                '/issues/1/ack', '/issues/1/resolve', '/issues/1/except', '/bell/1/read', '/bell/read-all',
                '/settings/thresholds', '/holds/org/confirm', '/holds/stages/confirm', '/holds/accounts/confirm', '/links/revoke')
            or getattr(code, 'CLOSED_LINK_ROUTES', None) != ('/links/reject', '/links/preview')
            or getattr(code, 'OLD_REPORT_UI', None) != REVIEWED_OLD_REPORT_UI_V18):
        raise ValueError('CODE_ONLY_RELEASE_NOT_REVIEWED')
    if expected_paths is None or code.CODE_PATHS != expected_paths or code.TEST_PATHS != frozenset():
        raise ValueError('CODE_ONLY_RELEASE_NOT_REVIEWED')


def prepare(package, host, release, lifecycle, upgrade, code):
    code.STAGE, code.OPERATION = 'code_prepare_preflight', 'package'
    require_review(code)
    result = code.prepare(package, host, release, lifecycle, upgrade)
    return dict(result, database_policy='preserve-in-place', database_opened_by_controller=False)


def apply(package, host, release, lifecycle, upgrade, code):
    code.STAGE, code.OPERATION = 'code_apply_preflight', 'package'
    require_review(code)
    if not isinstance(package, dict) or set(package) != {'release', 'operation_id'}:
        raise ValueError('CODE_APPLY_FIELDS')
    identity = package['operation_id']
    if not isinstance(identity, str) or not re.fullmatch('[0-9a-f]{32}', identity):
        raise ValueError('CODE_OPERATION_ID')
    prepared = code.validate_package(package['release'], release)
    code.OPERATION = 'current_state'
    old_path, old_receipt, old_files, _, bootstrap = code.current_state(prepared, host, release, lifecycle, upgrade)
    code.OPERATION = 'target_manifest'
    path, receipt = upgrade.manifest(release, code.TARGET_COMMIT, prepared)
    code.OPERATION = 'compatible_source'
    code.compatible_source(old_path, path, upgrade)
    code.OPERATION = 'unit_manifest'
    new_files = lifecycle.unit_files(path, pwd.getpwnam('www-data').pw_gid, release)
    if new_files[lifecycle.TMPFILES] != old_files[lifecycle.TMPFILES]:
        raise ValueError('TMPFILES_CHANGED')
    started = release.ROOT/'receipts'/('preview-start-'+code.TARGET_COMMIT+'.json')
    recovery = release.ROOT/'receipts'/('code-upgrade-'+identity+'.json')
    if any(os.path.lexists(p) for p in (started, recovery)):
        raise ValueError('CODE_ALREADY_ATTEMPTED')
    code.OPERATION = 'write_recovery_receipt'
    release.write_new(recovery, json.dumps({
        'source_commit':code.OLD_COMMIT, 'target_commit':code.TARGET_COMMIT,
        'database_policy':'preserve-in-place', 'images':old_receipt['images'],
        'units':{str(p):b.decode() for p,b in old_files.items() if p != lifecycle.TMPFILES}},
        sort_keys=True).encode())
    replaced = []

    def unchanged_state():
        require_review(code)
        if host.baseline() != prepared['baseline'] or code.bootstrap_state(release, upgrade) != bootstrap:
            raise ValueError('CODE_POST_STATE')

    def name(unit):
        return 'engine' if unit == lifecycle.UNITS[0] else 'relay'

    try:
        code.STAGE = 'code_stop_isolated'
        for unit in reversed(lifecycle.UNITS):
            code.OPERATION = 'stop_'+name(unit)
            release.command(['/usr/bin/systemctl', 'stop', unit], timeout=90)
            code.OPERATION = 'stop_check_'+name(unit)
            code.stopped_writer(release, lifecycle, old_path, {code.OLD_COMMIT:old_receipt['images']}, unit)
        code.OPERATION = 'bootstrap_check'
        unchanged_state()
        code.STAGE = 'code_recreate'
        for service in ('engine', 'relay'):
            code.OPERATION = 'recreate_'+service
            release.command(release.compose(path, service)+['up', '--no-start', '--no-build', '--force-recreate'], timeout=90)
        code.STAGE = 'code_replace_units'
        for unit in lifecycle.UNITS:
            code.OPERATION = 'replace_unit_'+name(unit)
            target = lifecycle.UNIT_DIR/unit
            replaced.append(target)
            upgrade.replace_unit(target, old_files[target], new_files[target], identity, release)
        code.OPERATION = 'daemon_reload'
        release.command(['/usr/bin/systemctl', 'daemon-reload'])
        code.STAGE = 'code_start'
        for unit in lifecycle.UNITS:
            code.OPERATION = 'start_'+name(unit)
            release.command(['/usr/bin/systemctl', 'start', unit], timeout=90)
        code.STAGE, code.OPERATION = 'code_verify', 'verify_running'
        verify_running(path, receipt, release, lifecycle, upgrade, code)
        code.OPERATION = 'post_state'
        unchanged_state()
        result = dict(ok=True, stage='internal_ready', source_commit=code.TARGET_COMMIT,
                      previous_commit=code.OLD_COMMIT, operation_id=identity, nginx_changed=False,
                      legacy_containers_unchanged=True, bootstrap_unchanged=True,
                      unauthenticated_read_status=401, business_post_status=403,
                      database_policy='preserve-in-place', database_opened_by_controller=False,
                      database_snapshot_verified=False, source_warmup_performed=False,
                      rollback_requires_matching_database=False, collection_completion_verified=False)
        code.OPERATION = 'write_started_receipt'
        release.write_new(started, json.dumps(result, sort_keys=True).encode())
        return result
    except Exception as error:
        details = code._capture_failure(error)
        code.STAGE = 'code_rollback'
        failed = False

        def attempt(function, *args, **kwargs):
            nonlocal failed
            try:
                function(*args, **kwargs)
                return True
            except Exception as rollback_error:
                if 'rollback_stage' not in details:
                    details.update(code._capture_failure(rollback_error, 'rollback'))
                failed = True
                return False

        def restore_unit(target):
            if upgrade.read_file(target, mode=0o644, maximum=32768) != old_files[target]:
                upgrade.replace_unit(target, new_files[target], old_files[target], identity+'-rollback', release)

        for unit in reversed(lifecycle.UNITS):
            code.OPERATION = 'stop_'+name(unit)
            attempt(release.command, ['/usr/bin/systemctl', 'stop', unit], timeout=90)
        for unit in lifecycle.UNITS:
            code.OPERATION = 'stop_check_'+name(unit)
            attempt(code.stopped_writer, release, lifecycle, old_path,
                    {code.OLD_COMMIT:old_receipt['images'], code.TARGET_COMMIT:receipt['images']}, unit)
        if not failed:
            code.OPERATION = 'rollback_state'
            attempt(unchanged_state)
        if not failed:
            code.OPERATION = 'compatible_source'
            attempt(code.compatible_source, old_path, path, upgrade)
        if not failed:
            code.OPERATION = 'old_manifest'
            attempt(upgrade.manifest, release, code.OLD_COMMIT, started=True)
        if not failed:
            for target in reversed(replaced):
                code.OPERATION = 'restore_unit_'+name(target.name)
                if not attempt(restore_unit, target):
                    break
        if not failed:
            for service in ('engine', 'relay'):
                code.OPERATION = 'recreate_'+service
                if not attempt(release.command, release.compose(old_path, service)+
                               ['up', '--no-start', '--no-build', '--force-recreate'], timeout=90):
                    break
        if not failed:
            code.OPERATION = 'daemon_reload'
            attempt(release.command, ['/usr/bin/systemctl', 'daemon-reload'])
        if not failed:
            for unit in lifecycle.UNITS:
                code.OPERATION = 'start_'+name(unit)
                if not attempt(release.command, ['/usr/bin/systemctl', 'start', unit], timeout=90):
                    break
            if not failed:
                code.OPERATION = 'verify_running'
                attempt(verify_running, old_path, old_receipt, release, lifecycle, upgrade, code)
        code.OPERATION = 'rollback_state'
        attempt(unchanged_state)
        if failed:
            for unit in reversed(lifecycle.UNITS):
                code.OPERATION = 'stop_'+name(unit)
                attempt(release.command, ['/usr/bin/systemctl', 'stop', unit], timeout=90)
        refused = RuntimeError('CODE_ROLLBACK_FAILED' if failed else 'CODE_ONLY_FAILED_ROLLED_BACK')
        refused.failure_details = details
        raise refused from None


def verify_running(path, receipt, release, lifecycle, upgrade, code):
    # No direct DB reader, docker exec, warmup, or integrity assertion here.
    source = receipt.get('source_commit')
    if source not in (code.OLD_COMMIT, code.TARGET_COMMIT) or path.name != 'naver-'+source:
        raise ValueError('CODE_PROBE_SOURCE')
    code.probe(release, source, upgrade)
    lifecycle._snapshot(release, path, receipt['images'])
    for unit in (lifecycle.TUNNEL, *lifecycle.UNITS):
        if lifecycle._state(release, unit, 'ActiveState') != 'active':
            raise ValueError('CODE_SERVICE_NOT_ACTIVE')
    for unit in lifecycle.UNITS:
        if lifecycle._state(release, unit, 'UnitFileState') != 'enabled':
            raise ValueError('CODE_SERVICE_NOT_ENABLED')


def failure_report(error, code):
    result = code.failure_report(error)
    if type(error) in (ValueError, RuntimeError) and error.args in (
            ('CODE_ONLY_RELEASE_NOT_REVIEWED',), ('CODE_ONLY_FAILED_ROLLED_BACK',)):
        result['error_code'] = error.args[0]
    return result
