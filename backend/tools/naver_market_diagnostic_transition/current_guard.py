"""Fixed, read-only current deployment and exact original failure guard.

Uses the existing lifecycle snapshot's image/project/service identity checks,
without calling upgrade.manifest/current_state (which read runtime secrets).
Only selected Docker metadata and closed exporter journal results enter RAM.
No container exec, DB, environment, bundle, service mutation or raw log output.
This establishes deployment identity, not an original export success.
"""
import re
from pathlib import Path
import preflight as B
import systemd_boundary as S
import transition as T

ROOT = Path('/srv/metainc/ad-deploy-staging')
ARCHIVE = '4aaa36508961e88f2c02df193bb869f9fb89cac32bd3d44bee8dfac072f2023c'
CIPHER = '92fd9b4479014c80fe3968b906225f79d02c4e7f53c01c2cf6477c3c56d6be6f'
BASELINE = '5463ca7b23575f668062e842f551170937239e625fb5a6104655c031c7e31d76'
RUN = '38850467092'
FIELDS = {'id': '.Id', 'image': '.Image', 'running': '.State.Running',
    'started': '.State.StartedAt', 'restarts': '.RestartCount', 'user': '.Config.User',
    'readonly': '.HostConfig.ReadonlyRootfs',
    'project': '(index .Config.Labels "com.docker.compose.project")',
    'service': '(index .Config.Labels "com.docker.compose.service")',
    'source': '(index .Config.Labels "metainc.naver.preview.source")'}
IMAGE_FIELDS = {'id': '.Id', 'user': '.Config.User',
    'source': '(index .Config.Labels "metainc.naver.preview.source")'}
PROOF_KEYS = {'version', 'operating_source', 'operating_operation',
    'prepared_sha256', 'started_sha256', 'containers_sha256', 'invocation_id'}


def fmt(fields):
    return '{' + ','.join('"' + k + '":{{json ' + v + '}}' for k, v in fields.items()) + '}'


def validate_proof(value, previous):
    if (type(value) is not dict or set(value) != PROOF_KEYS
            or type(value['version']) is not int or value['version'] != 1
            or value['operating_source'] != T.OPERATING_SOURCE
            or value['operating_operation'] != T.OPERATING_OPERATION):
        T.fail('CURRENT_PROOF')
    for key in ('prepared_sha256', 'started_sha256', 'containers_sha256'):
        T.digest(value[key])
    T.operation(value['invocation_id'])
    if value['started_sha256'] != previous['operating_receipt_sha256']:
        T.fail('CURRENT_PROOF')
    if len(T.canonical(value)) > 4096: T.fail('CURRENT_PROOF')
    return S.decode(T.canonical(value))


class CurrentGuard:
    def __init__(self, previous, *, proof=None, command=S.bounded):
        if type(previous) is not dict or set(previous) != T.PROOF_KEYS:
            T.fail('CURRENT_PREVIOUS')
        for v in previous.values(): T.digest(v)
        self.previous = S.decode(T.canonical(previous))
        self.proof = None if proof is None else validate_proof(proof, previous)
        # Injection is only for isolated tests. Production entrypoint never
        # accepts a command/callback from a request or a saved receipt.
        self.command = command

    def _run(self, argv, *, limit=4096):
        code, raw = self.command(argv, limit=limit, timeout=8)
        if type(code) is not int or code != 0 or type(raw) is not bytes or len(raw) > limit:
            T.fail('CURRENT_COMMAND')
        return raw

    def _receipts(self):
        for p in (ROOT, ROOT / 'receipts'): B.trusted_dir(p)
        prepared_path = ROOT / 'receipts' / ('preview-' + T.OPERATING_SOURCE + '.json')
        started_path = ROOT / 'receipts' / ('preview-start-' + T.OPERATING_SOURCE + '.json')
        prepared_raw, _ = B.snapshot(prepared_path)
        started_raw, _ = B.snapshot(started_path)
        prepared, started = B.decode(prepared_raw), B.decode(started_raw)
        package = dict(baseline=BASELINE, source_commit=T.OPERATING_SOURCE,
            source_tar_gz_sha256=ARCHIVE, ciphertext_sha256=CIPHER, run_id=RUN)
        if (type(prepared) is not dict or prepared.get('ok') is not True
                or prepared.get('stage') != 'prepared'
                or prepared.get('source_commit') != T.OPERATING_SOURCE
                or type(prepared.get('package')) is not dict
                or any(not T.same(prepared['package'].get(k), v) for k, v in package.items())
                or type(prepared.get('images')) is not dict
                or set(prepared['images']) != {'engine', 'relay'}):
            T.fail('CURRENT_PREPARED')
        for v in prepared['images'].values():
            if type(v) is not str or re.fullmatch('sha256:[0-9a-f]{64}', v) is None:
                T.fail('CURRENT_IMAGE')
        expected = dict(ok=True, stage='internal_ready', source_commit=T.OPERATING_SOURCE,
            previous_commit='513e52eaee4d1bb722461961639cd588df9080cd',
            operation_id=T.OPERATING_OPERATION, database_policy='preserve-in-place',
            execution_enabled=False)
        if (type(started) is not dict
                or any(not T.same(started.get(k), v) for k, v in expected.items())
                or T.sha(started_raw) != self.previous['operating_receipt_sha256']):
            T.fail('CURRENT_STARTED')
        return (T.sha(prepared_raw), T.sha(started_raw)), prepared['images']

    def _deployment(self):
        hashes, images = self._receipts()
        rows = {}
        for name in ('engine', 'relay'):
            label = 'naver-' + name
            # Avoid docker compose: its configuration processing can read env
            # files. Select the unique existing pair via the same lifecycle
            # project/service labels and inspect only the closed safe fields.
            raw = self._run(['/usr/bin/docker', 'ps', '--all', '--no-trunc',
                '--filter', 'label=com.docker.compose.project=' + label,
                '--filter', 'label=com.docker.compose.service=' + label,
                '--format', '{{.ID}}'])
            try: ids = raw.decode('ascii').splitlines()
            except UnicodeError: T.fail('CURRENT_CONTAINER')
            if len(ids) != 1 or re.fullmatch('[0-9a-f]{64}', ids[0]) is None:
                T.fail('CURRENT_CONTAINER')
            row = S.decode(self._run(['/usr/bin/docker', 'inspect', '--format', fmt(FIELDS), ids[0]]))
            expected = dict(id=ids[0], image=images[name], running=True, restarts=0,
                user='10001:10001', readonly=True, project=label, service=label,
                source=T.OPERATING_SOURCE)
            if (type(row) is not dict or set(row) != set(FIELDS)
                    or any(not T.same(row.get(k), v) for k, v in expected.items())
                    or type(row['started']) is not str
                    or re.fullmatch(r'[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(?:\.[0-9]{1,9})?Z', row['started']) is None
                    or row['started'].startswith('0001-')):
                T.fail('CURRENT_CONTAINER')
            image = S.decode(self._run(['/usr/bin/docker', 'image', 'inspect', '--format',
                fmt(IMAGE_FIELDS), images[name]]))
            if not T.same(image, dict(id=images[name], user='10001:10001', source=T.OPERATING_SOURCE)):
                T.fail('CURRENT_IMAGE')
            rows[name] = row
        if self._receipts() != (hashes, images): T.fail('CURRENT_CHANGED')
        return dict(prepared_sha256=hashes[0], started_sha256=hashes[1],
                    containers_sha256=T.sha(T.canonical(rows)))

    def _reader(self):
        return S.snapshot(self._run(['/usr/bin/systemctl', 'show', T.OLD_READER] +
            ['--property=' + p for p in S.PROPERTIES]))

    def _failure(self, invocation=None):
        before = self._reader()
        if before['DropInPaths'] or not S.idle(before): T.fail('CURRENT_FAILURE_UNIT')
        if before['LoadState'] == 'loaded':
            if (before['FragmentPath'] != T.UNIT_ROOT + '/' + T.OLD_READER
                    or before['UnitFileState'] not in ('static', 'disabled')
                    or before['Result'] != 'exit-code' or before['ExecMainStatus'] != '1'):
                T.fail('CURRENT_FAILURE_UNIT')
            latest = T.operation(before['InvocationID'])
            if invocation is not None and invocation != latest: T.fail('CURRENT_FAILURE_CHANGED')
            invocation = latest
        elif (invocation is None or before['LoadState'] != 'masked'
                or before['FragmentPath'] != S.MASK_ROOT + '/' + T.OLD_READER
                or before['UnitFileState'] != 'masked-runtime'):
            T.fail('CURRENT_FAILURE_UNIT')
        elif before['InvocationID'] not in ('', '0' * 32, invocation):
            T.fail('CURRENT_FAILURE_CHANGED')
        # Once owned masks are installed, systemd may clear cached InvocationID.
        # Keep the immutable pre-mask ID; HostPort additionally proves owned
        # masks, both idle original units and unchanged original source files.
        raw = self._run(['/usr/bin/journalctl', '--output=json', '--no-pager', '-n', '32',
            '_SYSTEMD_UNIT=' + T.OLD_READER, '_SYSTEMD_INVOCATION_ID=' + invocation], limit=32768)
        if S.exact_failure(raw, unit=T.OLD_READER, invocation=invocation) != 'unknown':
            T.fail('CURRENT_FAILURE_RESULT')
        # Original pinned exporter has exactly two fields. Never accept a new
        # diagnostic result as the original failure prerequisite.
        for line in raw.splitlines():
            message = S.decode(line)['MESSAGE']
            if not message.lstrip().startswith('{'): continue
            value = S.decode(message)
            if type(value) is dict and ('status' in value or 'code' in value):
                if not T.same(value, {'status': 'failed', 'code': 'SOURCE_LIMIT'}):
                    T.fail('CURRENT_FAILURE_RESULT')
        if not T.same(before, self._reader()): T.fail('CURRENT_FAILURE_CHANGED')
        return invocation

    def capture(self):
        if self.proof is not None: T.fail('CURRENT_ALREADY_BOUND')
        before = self._deployment()
        invocation = self._failure()
        if not T.same(before, self._deployment()): T.fail('CURRENT_CHANGED')
        self.proof = validate_proof(dict(version=1, operating_source=T.OPERATING_SOURCE,
            operating_operation=T.OPERATING_OPERATION, invocation_id=invocation, **before), self.previous)
        return S.decode(T.canonical(self.proof))

    def __call__(self, *, require_failure):
        if type(require_failure) is not bool or self.proof is None: T.fail('CURRENT_PROOF')
        proof = validate_proof(self.proof, self.previous)
        before = self._deployment()
        if not T.same(before, {k: proof[k] for k in before}): T.fail('CURRENT_CHANGED')
        if require_failure: self._failure(proof['invocation_id'])
        if not T.same(before, self._deployment()): T.fail('CURRENT_CHANGED')
        return dict(operating_source=T.OPERATING_SOURCE,
            operating_operation=T.OPERATING_OPERATION, current_source_verified=True,
            source_limit_invocation_verified=require_failure)
