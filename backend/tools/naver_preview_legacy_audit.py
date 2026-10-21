"""Fixed, aggregate-only legacy ad-api SQLite audit. No app imports or decryption."""
import json
import os
import re

STAGE = 'input'
PROJECTION_SOURCE = r'''
import sqlite3

FIELDS = ('credential_rows', 'unique_clients', 'customer_id_ciphertext_present',
          'three_fields_present', 'erp_linked_rows', 'three_fields_with_erp_link',
          'connected_rows', 'active_client_rows', 'invalid_json_rows',
          'mode_delegated_rows', 'mode_direct_rows', 'mode_upload_rows', 'mode_other_rows')
SQL = """
WITH n AS (
  SELECT cc.client_id, cc.mode, cc.status, c.status AS client_status,
    c.erp_possibility_id,
    CASE WHEN json_valid(cc.fields_json) THEN
      CASE WHEN json_type(cc.fields_json)='object' THEN cc.fields_json ELSE '{}' END
      ELSE '{}' END AS payload,
    CASE WHEN json_valid(cc.fields_json) THEN
      CASE WHEN json_type(cc.fields_json)='object' THEN 0 ELSE 1 END ELSE 1 END AS bad_json
  FROM channel_credentials cc LEFT JOIN clients c ON c.id=cc.client_id
  WHERE cc.channel='naver_searchad'
), p AS (
  SELECT *,
    typeof(json_extract(payload,'$.customer_id'))='text'
      AND length(json_extract(payload,'$.customer_id'))>0 AS has_id,
    typeof(json_extract(payload,'$.api_license'))='text'
      AND length(json_extract(payload,'$.api_license'))>0 AS has_key,
    typeof(json_extract(payload,'$.secret_key'))='text'
      AND length(json_extract(payload,'$.secret_key'))>0 AS has_secret,
    typeof(erp_possibility_id)='integer' AND erp_possibility_id>0 AS has_erp
  FROM n
)
SELECT COUNT(*), COUNT(DISTINCT client_id),
  COUNT(CASE WHEN has_id THEN 1 END),
  COUNT(CASE WHEN has_id AND has_key AND has_secret THEN 1 END),
  COUNT(CASE WHEN has_erp THEN 1 END),
  COUNT(CASE WHEN has_id AND has_key AND has_secret AND has_erp THEN 1 END),
  COUNT(CASE WHEN status='connected' THEN 1 END),
  COUNT(CASE WHEN client_status='active' THEN 1 END),
  COUNT(CASE WHEN bad_json=1 THEN 1 END),
  COUNT(CASE WHEN mode='delegated' THEN 1 END),
  COUNT(CASE WHEN mode='direct' THEN 1 END),
  COUNT(CASE WHEN mode='upload' THEN 1 END),
  COUNT(CASE WHEN mode IS NULL OR mode NOT IN ('delegated','direct','upload') THEN 1 END)
FROM p
"""


def authorizer(action, arg1, arg2, database, trigger):
    if action == sqlite3.SQLITE_SELECT:
        return sqlite3.SQLITE_OK
    if action == sqlite3.SQLITE_TRANSACTION and arg1 in ('BEGIN', 'ROLLBACK'):
        return sqlite3.SQLITE_OK
    if action == sqlite3.SQLITE_FUNCTION and arg2 in (
            'count', 'json_valid', 'json_type', 'json_extract', 'typeof', 'length'):
        return sqlite3.SQLITE_OK
    columns = {'channel_credentials': {'client_id', 'channel', 'mode', 'status', 'fields_json'},
               'clients': {'id', 'status', 'erp_possibility_id'}}
    if (action == sqlite3.SQLITE_READ and database == 'main' and trigger in (None, 'n', 'p')
            and arg1 in columns and arg2 in columns[arg1]):
        return sqlite3.SQLITE_OK
    return sqlite3.SQLITE_DENY


def validate_result(value):
    if type(value) is not dict or set(value) != set(FIELDS):
        raise ValueError('LEGACY_AUDIT_FIELDS')
    if any(type(n) is not int or not 0 <= n < 2**31 for n in value.values()):
        raise ValueError('LEGACY_AUDIT_COUNTS')
    total = value['credential_rows']
    if (any(n > total for n in value.values())
            or sum(value['mode_'+mode+'_rows'] for mode in ('delegated','direct','upload','other')) != total
            or value['three_fields_present'] > value['customer_id_ciphertext_present']
            or value['three_fields_with_erp_link'] > min(value['three_fields_present'], value['erp_linked_rows'])):
        raise ValueError('LEGACY_AUDIT_RANGE')
    return value


def collect(conn):
    conn.execute('PRAGMA query_only=ON')
    conn.set_authorizer(authorizer)
    conn.execute('BEGIN')
    try:
        return validate_result(dict(zip(FIELDS, conn.execute(SQL).fetchone())))
    finally:
        conn.execute('ROLLBACK')
'''
exec(compile(PROJECTION_SOURCE, '<legacy-audit-projection>', 'exec'))


def fixed_script():
    # Never import app.security: that module can create missing key files on import.
    return ('import json,os,sys\n'+PROJECTION_SOURCE+'''
try:
    os.environ.clear()
    conn=sqlite3.connect('file:/app/data/app.db?mode=ro',uri=True,timeout=5)
    try:
        result=collect(conn)
    finally:
        conn.close()
    print(json.dumps(result,sort_keys=True))
except Exception:
    sys.exit(1)
''').encode()


def validate_package(package):
    if type(package) is not dict or set(package) != {'baseline', 'source_commit', 'source_tar_gz_sha256'}:
        raise ValueError('PACKAGE_FIELDS')
    for key, value in package.items():
        if type(value) is not str or not re.fullmatch('[0-9a-f]{40}' if key == 'source_commit' else '[0-9a-f]{64}', value):
            raise ValueError('PACKAGE_SHAPE')


def run(package, host, release):
    global STAGE
    STAGE = 'preflight'
    validate_package(package)
    if os.geteuid() != 0 or host.baseline() != package['baseline']:
        raise ValueError('HOST_BASELINE')
    # AD docker-compose.yml fixes container_name=ad-api and service=ad-api.
    fmt = '{"id":{{json .Id}},"name":{{json .Name}},"image":{{json .Image}},"running":{{json .State.Running}},"user":{{json .Config.User}},"service":{{json (index .Config.Labels "com.docker.compose.service")}},"started":{{json .State.StartedAt}},"restarts":{{json .RestartCount}}}'
    def container(target):
        raw = release.command(['docker', 'inspect', '--format', fmt, target], timeout=15)
        if len(raw) > 4096:
            raise ValueError('CONTAINER_SIZE')
        return json.loads(raw, object_pairs_hook=release.unique)
    before = container('ad-api')
    if (type(before) is not dict or set(before) != {'id','name','image','running','user','service','started','restarts'}
            or before['name'] != '/ad-api' or before['service'] != 'ad-api' or before['running'] is not True
            or type(before['id']) is not str or not re.fullmatch('[0-9a-f]{64}', before['id'])):
        raise ValueError('LEGACY_CONTAINER_IDENTITY')
    STAGE = 'read_only_legacy_audit'
    try:
        # No --user override, install, app import, API invocation or database write.
        raw = release.command(['docker', 'exec', '-i', before['id'], 'python', '-I', '-B', '-'],
                              data=fixed_script(), timeout=30)
        if len(raw) > 4096:
            raise ValueError('LEGACY_AUDIT_SIZE')
        result = validate_result(json.loads(raw, object_pairs_hook=release.unique))
    finally:
        STAGE = 'postflight'
        if container('ad-api') != before or host.baseline() != package['baseline']:
            raise ValueError('POST_BASELINE')
    return {'ok': True, 'mode': 'legacy-audit', 'source_commit': package['source_commit'], 'audit': result,
            'reader_mode': 'sqlite-mode-ro-query-only-authorizer', 'mutations': 0, 'external_calls': 0,
            'decryption_performed': False, 'existing_app_baseline_unchanged': True}
