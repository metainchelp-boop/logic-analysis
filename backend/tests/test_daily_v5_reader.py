"""Source-only Docker COPY proof and narrow v5 real-Store boundaries.

The already registered source_fixture/frozen assets are authenticated before use.
No operating database, Docker, network, provider, or checkout is used.
"""
import ast
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import socket
import sqlite3
import subprocess
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

import source_fixture as SF


HERE = Path(__file__).resolve().parent
READER = HERE.parent / 'tools' / 'naver_daily_current_reader_v5.py'
SPEC = importlib.util.spec_from_file_location('_daily_v5_reader_test', READER)
D = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(D)
OLD_BODY = SF.frozen_bytes()['reader.py']
OLD = SF.frozen_module('_daily_v3_image_red', OLD_BODY, SF.ASSETS / 'frozen-reader' / 'reader.py')
F = SF.frozen_module('_daily_v5_real_fixture', SF.frozen_bytes()['fixtures.py'], SF.ASSETS / 'frozen-reader' / 'fixtures.py')
MAP_SHA = '69d77f2c2ede33f35d8d424665dfd85b4a710fcf3ff5fc88a85b281ce564332f'
PREFIXES = ('naver_engine/', 'naver_runtime/', 'backend/app/naver_auto/')


def product_module(name):
    return any(name == p or name.startswith(p + '.') for p in ('naver_engine', 'naver_runtime', 'app'))


def denied(*args, **kwargs):
    raise AssertionError('SYNTHETIC_EXTERNAL_IO_DISABLED')


def pins():
    return {k: D.CANONICAL_SHA256 if k == 'canonical_receipt' else 'a' * 64 for k in D.PIN_FIELDS}


def tree_functions(body):
    return {node.name: node for node in ast.parse(body).body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))}


class _RemoveStage(ast.NodeTransformer):
    """Discard only closed stage/reason metadata, retaining all old AST."""
    def visit_Global(self, node):
        if all(name in ('READ_STAGE', 'READ_FAILURE_STAGE', 'READ_FAILURE_REASON') for name in node.names):
            return None
        return node

    def visit_Assign(self, node):
        if all(isinstance(n, ast.Name) and n.id in ('READ_STAGE', 'READ_FAILURE_STAGE', 'READ_FAILURE_REASON') for n in node.targets):
            return None
        return self.generic_visit(node)

    def visit_If(self, node):
        # The new cleanup guards contain only closed failure metadata.
        if (isinstance(node.test, ast.Compare) and isinstance(node.test.left, ast.Name)
                and node.test.left.id == 'failure' and len(node.test.ops) == 1
                and isinstance(node.test.ops[0], ast.Is) and len(node.test.comparators) == 1
                and isinstance(node.test.comparators[0], ast.Constant) and node.test.comparators[0].value is None
                and len(node.body) == 2 and all(isinstance(n, ast.Assign) for n in node.body)
                and [n.targets[0].id if len(n.targets) == 1 and isinstance(n.targets[0], ast.Name) else None
                    for n in node.body] == ['READ_FAILURE_STAGE', 'READ_FAILURE_REASON']
                and not node.orelse):
            return None
        return self.generic_visit(node)

    def visit_ExceptHandler(self, node):
        if isinstance(node.type, ast.Name) and node.type.id == 'Exception' and node.name == 'error':
            node.name = None
        return self.generic_visit(node)

    def visit_Name(self, node):
        if node.id == 'IMAGE_SOURCE_FILES':
            node.id = 'SOURCE_FILES'
        return node


class ReaderV5Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.old_path = list(sys.path)
        cls.old_modules = {n: m for n, m in sys.modules.copy().items() if product_module(n)}
        for name in cls.old_modules:
            del sys.modules[name]
        cls.blocks = []
        for obj, name in ((socket.socket, 'connect'), (socket.socket, 'connect_ex'),
                (socket, 'create_connection'), (subprocess, 'run'), (subprocess, 'Popen')):
            block = patch.object(obj, name, side_effect=denied)
            block.start()
            cls.blocks.append(block)
        cls.temp = tempfile.TemporaryDirectory(prefix='d3-v5-reader-')
        cls.host = SF.extract_source(Path(cls.temp.name).resolve() / 'host')
        cls.canonical, cls.bodies = SF.read_bundle()
        cls.image = Path(cls.temp.name).resolve() / 'image'
        cls.image.mkdir(mode=0o700)
        for name, row in cls.canonical['files'].items():
            if name.startswith(PREFIXES) or name == 'backend/app/__init__.py':
                target = cls.image / name
                target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
                target.write_bytes(cls.bodies[name])
                target.chmod(row['mode'])
        cls.modules = D.load_modules(cls.image)

    @classmethod
    def tearDownClass(cls):
        for name in tuple(sys.modules):
            if product_module(name):
                del sys.modules[name]
        sys.modules.update(cls.old_modules)
        sys.path[:] = cls.old_path
        cls.temp.cleanup()
        for block in reversed(cls.blocks):
            block.stop()

    def test_old_full_host_guard_red_on_docker_copy_before_database(self):
        self.assertEqual(OLD.verify_source(self.host), self.host)
        self.assertFalse((self.image / '.dockerignore').exists())
        with self.assertRaisesRegex(ValueError, '^D3_SOURCE_PIN$'):
            OLD.verify_source(self.image)
        with patch.object(OLD, 'EXECUTION_PINS', pins()), patch.object(OLD, 'connect_reader', side_effect=denied) as db:
            with self.assertRaisesRegex(ValueError, '^D3_READ_FAILED$'):
                OLD.read_database('/synthetic/not-opened.db', self.image)
            db.assert_not_called()

    def test_image_map_exact_docker_copy_ignore_and_full_canonical(self):
        dockerfile = self.bodies['Dockerfile.naver-engine'].decode()
        self.assertEqual([line for line in dockerfile.splitlines() if line.startswith('COPY ')], [
            'COPY naver_engine/ ./naver_engine/', 'COPY naver_runtime/ ./naver_runtime/',
            'COPY backend/app/__init__.py ./backend/app/__init__.py',
            'COPY backend/app/naver_auto/ ./backend/app/naver_auto/'])
        ignore = self.bodies['Dockerfile.naver-engine.dockerignore'].decode().splitlines()
        self.assertEqual(ignore[1:], ['**', '!Dockerfile.naver-engine', '!naver_engine/', '!naver_engine/**',
            '!naver_runtime/', '!naver_runtime/**', '!backend/', '!backend/app/', '!backend/app/__init__.py',
            '!backend/app/naver_auto/', '!backend/app/naver_auto/**', '**/tests/', '**/__pycache__/',
            '**/*.pyc', '**/*.db*', '**/.env*', '**/*.pem', '**/*.key*'])
        expected = {n: row for n, row in self.canonical['files'].items()
            if n.startswith(PREFIXES) or n == 'backend/app/__init__.py'}
        self.assertEqual(len(expected), 106)
        self.assertEqual(D.IMAGE_SOURCE_FILES, expected)
        self.assertEqual(D.SOURCE_FILES, self.canonical['files'])
        self.assertEqual(len(D.SOURCE_FILES), 163)
        self.assertEqual(hashlib.sha256(json.dumps(expected, sort_keys=True, separators=(',', ':')).encode()).hexdigest(), MAP_SHA)
        self.assertEqual(D.IMAGE_SOURCE_MAP_SHA256, MAP_SHA)
        self.assertTrue(all('/tests/' not in n and '/__pycache__/' not in n
            and not n.endswith('.pyc') and not Path(n).name.startswith('.env')
            and not any(s in Path(n).name for s in ('.db', '.pem', '.key')) for n in expected))

    def test_v5_image_and_full_host_guards_have_separate_required_scopes(self):
        self.assertEqual(D.verify_source(self.image), self.image)
        self.assertEqual(D.verify_host_source(self.host), self.host)
        with self.assertRaisesRegex(ValueError, '^D3_SOURCE_PIN$'):
            D.verify_host_source(self.image)
        name = '.dockerignore'
        original = (self.host / name).read_bytes()
        (self.host / name).unlink()
        try:
            with self.assertRaisesRegex(ValueError, '^D3_SOURCE_PIN$'):
                D.verify_host_source(self.host)
            self.assertEqual(D.verify_source(self.image), self.image)
        finally:
            (self.host / name).write_bytes(original)
            (self.host / name).chmod(self.canonical['files'][name]['mode'])

    def test_old_sql_authority_time_projection_and_cleanup_ast_preserved(self):
        old = tree_functions(OLD_BODY.decode())
        new = tree_functions(READER.read_text())
        self.assertEqual(set(new), set(old) | {'verify_host_source', 'classify_reader_failure'})
        original = copy.deepcopy(old['verify_source'])
        original.name = 'verify_host_source'
        self.assertEqual(ast.dump(original, include_attributes=False), ast.dump(new['verify_host_source'], include_attributes=False))
        for name, node in old.items():
            if name == 'verify_source':
                continue
            with self.subTest(function=name):
                transformed = _RemoveStage().visit(copy.deepcopy(new[name])) if name in ('load_modules', 'read_database') else new[name]
                self.assertEqual(ast.dump(node, include_attributes=False), ast.dump(transformed, include_attributes=False))

    def test_missing_expected_image_file_is_never_ignored(self):
        target = self.image / 'naver_runtime/config.py'
        original = target.read_bytes()
        target.unlink()
        try:
            with self.assertRaisesRegex(ValueError, '^D3_SOURCE_PIN$'):
                D.verify_source(self.image)
        finally:
            target.write_bytes(original)
            target.chmod(0o644)

    def test_image_bytes_mode_symlink_and_empty_init_guards(self):
        target = self.image / 'backend/app/__init__.py'
        self.assertEqual(target.stat().st_size, 0)
        self.assertEqual(D.verify_source(self.image), self.image)
        for mutant in ('bytes', 'mode', 'symlink'):
            with self.subTest(mutant=mutant):
                try:
                    if mutant == 'bytes':
                        target.write_bytes(b'# invalid nonempty\n')
                    elif mutant == 'mode':
                        target.chmod(0o664)
                    else:
                        target.unlink()
                        target.symlink_to(self.host / 'backend/app/__init__.py')
                    with self.assertRaisesRegex(ValueError, '^D3_SOURCE_PIN$'):
                        D.verify_source(self.image)
                finally:
                    target.unlink()
                    target.write_bytes(b'')
                    target.chmod(0o644)

    def test_image_manifest_tampering_count_hash_and_fullmap_binding_refused(self):
        for mutation in ('delete', 'wrong_hash', 'wrong_mode', 'unapproved_path'):
            manifest = copy.deepcopy(D.IMAGE_SOURCE_FILES)
            first = next(iter(manifest))
            if mutation == 'delete':
                del manifest[first]
            elif mutation == 'wrong_hash':
                manifest[first]['sha256'] = '0' * 64
            elif mutation == 'wrong_mode':
                manifest[first]['mode'] = 0o664
            else:
                manifest['.dockerignore'] = copy.deepcopy(D.SOURCE_FILES['.dockerignore'])
            with self.subTest(mutation=mutation), patch.object(D, 'IMAGE_SOURCE_FILES', manifest):
                with self.assertRaisesRegex(ValueError, '^D3_SOURCE_PIN$'):
                    D.verify_source(self.image)

    def test_foreign_cached_product_import_and_unlisted_inroot_module_refused(self):
        for path in (self.host / 'naver_engine/store.py', self.image / 'naver_engine/unapproved.py'):
            fake = types.ModuleType('naver_engine.synthetic_guard_probe')
            fake.__file__ = str(path)
            with self.subTest(path_is_inside_image=path.is_relative_to(self.image)), \
                    patch.dict(sys.modules, {'naver_engine.synthetic_guard_probe': fake}):
                with self.assertRaisesRegex(ValueError, '^D3_SOURCE_IMPORT$'):
                    D.load_modules(self.image)

    def test_pending_execution_pins_stop_before_any_path_or_source_io(self):
        class Trap:
            def __fspath__(self):
                raise AssertionError('PENDING_PIN_PATH_IO')
        self.assertTrue(all(value is None for value in D.EXECUTION_PINS.values()))
        with patch.object(D, 'load_modules', side_effect=denied) as source, patch.object(D, 'connect_reader', side_effect=denied) as db:
            with self.assertRaisesRegex(ValueError, '^D3_EXECUTION_PINS_PENDING$'):
                D.read_database(Trap(), Trap())
            source.assert_not_called()
            db.assert_not_called()
        self.assertIsNone(D.READ_FAILURE_STAGE)
        self.assertIsNone(D.READ_FAILURE_REASON)

    def real_collect(self, scenario, revoked=False):
        st, modules, now = F.seed(self.modules, scenario)
        try:
            st._conn.set_authorizer(None)  # Synthetic preparation, before the read boundary.
            if revoked:
                st.writer = True
                organization = F._organization(now)
                organization['owners'][0]['manage_emp_idx'] = 1
                st.record_org(organization, now)
                st.writer = False
            c = st._conn
            c.set_authorizer(None)
            c.execute('PRAGMA query_only=ON')
            c.set_authorizer(D.readonly_authorizer)
            before = c.total_changes
            c.execute('BEGIN')
            with patch.object(st, 'synchronize_management', side_effect=denied), \
                    patch.object(st, 'inspection_work', side_effect=denied), \
                    patch.object(st, 'performance_work', side_effect=denied), patch.object(st, '_tx', side_effect=denied):
                result = D.validate_result(D.collect(st, now, modules))
            self.assertEqual(c.total_changes, before)
            c.execute('ROLLBACK')
            return result
        finally:
            st.close()

    def test_image_actual_store_past_event_current_authority_and_ui_branches(self):
        self.assertLess(F.EXPIRES, F.NOW)
        for scenario, branch in (('nojob', 'NO_OBSERVATION'), ('partial', 'CURRENT_PARTIAL'), ('ok', 'CURRENT_COMPLETE')):
            with self.subTest(scenario=scenario):
                result = self.real_collect(scenario)
                self.assertEqual(result['authorization'], 'OBSERVED_EVENT_OWNER_CURRENTLY_AUTHORIZED')
                self.assertEqual(result['inspection']['ui_branch'], branch)
                self.assertTrue(result['identity']['canonical_ad_account_namespace_resolved'])

    def test_image_actual_store_current_authority_refusal_remains_unknown(self):
        result = self.real_collect('partial', revoked=True)
        self.assertEqual(result['authorization'], 'UNKNOWN')
        self.assertTrue(all(result[key] is None for key in ('identity', 'inspection', 'manual', 'same_pid_performance')))

    def test_image_actual_uri_reader_single_snapshot_no_db_mutation(self):
        st, _, now = F.seed(self.modules, 'partial')
        try:
            path = Path(self.temp.name).resolve() / 'synthetic-reader.db'
            connection = sqlite3.connect(path)
            st._conn.backup(connection)
            connection.close()
            before = hashlib.sha256(path.read_bytes()).hexdigest()
            statements = []
            original = D.connect_reader
            def capture(value):
                result = original(value)
                result.set_trace_callback(lambda sql: statements.append(sql) if sql in ('BEGIN', 'ROLLBACK') else None)
                return result
            with patch.object(D, 'EXECUTION_PINS', pins()), patch.object(D, 'connect_reader', side_effect=capture):
                result = D.read_database(path, self.image, now=now)
            self.assertEqual(result['inspection']['ui_branch'], 'CURRENT_PARTIAL')
            self.assertEqual(statements, ['BEGIN', 'ROLLBACK'])
            self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), before)
            self.assertIsNone(D.READ_FAILURE_STAGE)
            self.assertIsNone(D.READ_FAILURE_REASON)
        finally:
            st.close()

    def test_stage_source_and_import_failures_are_closed_before_database(self):
        for stage, source_target in (('SOURCE', 'verify_source'), ('IMPORT', 'import_module')):
            target = D if source_target == 'verify_source' else D.importlib
            with self.subTest(stage=stage), patch.object(D, 'EXECUTION_PINS', pins()), \
                    patch.object(target, source_target, side_effect=RuntimeError('PRIVATE_RAW_MUST_NOT_ESCAPE')), \
                    patch.object(D, 'connect_reader', side_effect=denied) as db:
                with self.assertRaisesRegex(ValueError, '^D3_READ_FAILED$'):
                    D.read_database('/synthetic/not-opened.db', self.image)
                self.assertEqual(D.READ_FAILURE_STAGE, stage)
                self.assertEqual(D.READ_FAILURE_REASON, 'D3_UNCLASSIFIED')
                db.assert_not_called()

    def test_stage_db_open_failure_is_closed_without_query(self):
        with patch.object(D, 'EXECUTION_PINS', pins()), patch.object(D, 'load_modules', return_value=self.modules), \
                patch.object(D, 'connect_reader', side_effect=RuntimeError('PRIVATE_RAW')):
            with self.assertRaisesRegex(ValueError, '^D3_READ_FAILED$'):
                D.read_database('/synthetic/not-opened.db', self.image)
        self.assertEqual(D.READ_FAILURE_STAGE, 'DB_OPEN')
        self.assertEqual(D.READ_FAILURE_REASON, 'D3_UNCLASSIFIED')

    def test_stage_db_query_and_validation_preserve_first_failure_over_cleanup(self):
        for stage in ('DB_QUERY', 'VALIDATE'):
            st, _, now = F.seed(self.modules, 'partial')
            connection = st._conn
            connection.set_authorizer(None)
            connection.execute('PRAGMA query_only=ON')
            connection.set_authorizer(D.readonly_authorizer)
            try:
                with self.subTest(stage=stage), patch.object(D, 'EXECUTION_PINS', pins()), \
                        patch.object(D, 'load_modules', return_value=self.modules), \
                        patch.object(D, 'connect_reader', return_value=connection), \
                        patch.object(self.modules['S'], 'Store', return_value=st), \
                        patch.object(st, 'close', side_effect=RuntimeError('PRIVATE_CLEANUP')), \
                        patch.object(D, 'collect', return_value={}, side_effect=RuntimeError('PRIVATE_QUERY') if stage == 'DB_QUERY' else None) as query, \
                        patch.object(D, 'validate_result', side_effect=RuntimeError('PRIVATE_VALIDATION')) as validation:
                    with self.assertRaisesRegex(ValueError, '^D3_READ_FAILED$'):
                        D.read_database('/synthetic/not-opened.db', self.image, now=now)
                    self.assertEqual(D.READ_FAILURE_STAGE, stage)
                    self.assertEqual(D.READ_FAILURE_REASON, 'D3_UNCLASSIFIED')
                    self.assertTrue(query.called)
                    self.assertEqual(validation.called, stage == 'VALIDATE')
            finally:
                st.close()

    def test_stage_cleanup_failure_does_not_return_success_or_raw(self):
        st, _, now = F.seed(self.modules, 'partial')
        connection = st._conn
        connection.set_authorizer(None)
        connection.execute('PRAGMA query_only=ON')
        connection.set_authorizer(D.readonly_authorizer)
        try:
            with patch.object(D, 'EXECUTION_PINS', pins()), patch.object(D, 'load_modules', return_value=self.modules), \
                    patch.object(D, 'connect_reader', return_value=connection), \
                    patch.object(self.modules['S'], 'Store', return_value=st), \
                    patch.object(st, 'close', side_effect=RuntimeError('PRIVATE_CLEANUP')):
                with self.assertRaisesRegex(ValueError, '^D3_CLEANUP_FAILED$'):
                    D.read_database('/synthetic/not-opened.db', self.image, now=now)
                self.assertEqual(D.READ_FAILURE_STAGE, 'CLEANUP')
                self.assertEqual(D.READ_FAILURE_REASON, 'D3_UNCLASSIFIED')
        finally:
            st.close()

    def test_reason_exact_valueerror_codes_only_without_raw_or_unhashable_args(self):
        known = frozenset(('D3_DATABASE_PATH', 'D3_DEADLINE', 'D3_EXECUTION_PINS_INVALID',
            'D3_EXECUTION_PINS_PENDING', 'D3_MUTATION', 'D3_OUTPUT_SHAPE', 'D3_READER_MODE',
            'D3_READ_BOUND', 'D3_SCHEMA', 'D3_SETUP_SHAPE', 'D3_SHAPE', 'D3_SOURCE_IMPORT',
            'D3_SOURCE_PIN', 'D3_TIME', 'D3_UI_BRANCH_MISMATCH'))
        self.assertEqual(D.READ_VALUE_CODES, known)
        self.assertEqual(D.READ_REASONS, known | {'D3_SQLITE_AUTH', 'D3_SQLITE_BUSY', 'D3_SQLITE_OTHER', 'D3_UNCLASSIFIED'})
        self.assertEqual(type(D.READ_REASONS), frozenset)
        self.assertEqual(len(D.READ_REASONS), 19)
        for code in known:
            with self.subTest(code=code):
                self.assertEqual(D.classify_reader_failure(ValueError(code)), code)
        class ValueErrorSubclass(ValueError):
            def __str__(self):
                raise AssertionError('EXCEPTION_TEXT_READ')
        class UnknownError(RuntimeError):
            def __getattribute__(self, name):
                if name == 'args':
                    raise AssertionError('UNKNOWN_ARGS_READ')
                return super().__getattribute__(name)
            def __str__(self):
                raise AssertionError('EXCEPTION_TEXT_READ')
        errors = [ValueError(), ValueError('SYNTHETIC_PRIVATE_DETAIL'), ValueError('D3_SOURCE_PIN', 'extra'),
            ValueError(['SYNTHETIC_PRIVATE_DETAIL']), ValueError({'private': 'synthetic'}), ValueError(set()),
            ValueError(None), ValueError(True), ValueError(b'D3_SOURCE_PIN'), ValueError('D3_SQLITE_AUTH'),
            RuntimeError('D3_SOURCE_PIN'), ValueErrorSubclass('D3_SOURCE_PIN'), UnknownError('SYNTHETIC_PRIVATE_DETAIL')]
        for index, error in enumerate(errors):
            with self.subTest(case=index):
                self.assertEqual(D.classify_reader_failure(error), 'D3_UNCLASSIFIED')

    def test_reason_sqlite_primary_numeric_codes_only_including_real_auth(self):
        connection = sqlite3.connect(':memory:')
        try:
            connection.set_authorizer(lambda *args: sqlite3.SQLITE_DENY)
            try:
                connection.execute('SELECT 1')
            except sqlite3.Error as error:
                self.assertEqual(type(error.sqlite_errorcode), int)
                self.assertEqual(D.classify_reader_failure(error), 'D3_SQLITE_AUTH')
            else:
                self.fail('SYNTHETIC_AUTH_DENIAL_MISSING')
        finally:
            connection.close()
        class SQLiteNoText(sqlite3.OperationalError):
            def __str__(self):
                raise AssertionError('SQLITE_TEXT_READ')
        for code, expected in ((sqlite3.SQLITE_AUTH | 256, 'D3_SQLITE_AUTH'),
                (sqlite3.SQLITE_BUSY, 'D3_SQLITE_BUSY'), (sqlite3.SQLITE_LOCKED, 'D3_SQLITE_BUSY'),
                (sqlite3.SQLITE_BUSY | 512, 'D3_SQLITE_BUSY'), (sqlite3.SQLITE_LOCKED | 256, 'D3_SQLITE_BUSY'),
                (sqlite3.SQLITE_ERROR, 'D3_SQLITE_OTHER'), (None, 'D3_SQLITE_OTHER'),
                (True, 'D3_SQLITE_OTHER'), ('5', 'D3_SQLITE_OTHER'), ([], 'D3_SQLITE_OTHER')):
            error = SQLiteNoText('SYNTHETIC_PRIVATE_SQL')
            error.sqlite_errorcode = code
            with self.subTest(code_type=type(code).__name__, expected=expected):
                self.assertEqual(D.classify_reader_failure(error), expected)
        class SQLiteUnreadableCode(sqlite3.Error):
            @property
            def sqlite_errorcode(self):
                raise RuntimeError('SYNTHETIC_PRIVATE_ATTRIBUTE')
        self.assertEqual(D.classify_reader_failure(SQLiteUnreadableCode()), 'D3_SQLITE_OTHER')
        self.assertEqual(D.classify_reader_failure(sqlite3.Error('SYNTHETIC_PRIVATE_SQL')), 'D3_SQLITE_OTHER')

    def cleanup_reason_case(self, primary):
        st, _, now = F.seed(self.modules, 'partial')
        connection = st._conn
        connection.set_authorizer(None)
        connection.execute('PRAGMA query_only=ON')
        connection.set_authorizer(D.readonly_authorizer)
        rollback_error = sqlite3.OperationalError('SYNTHETIC_PRIVATE_ROLLBACK')
        rollback_error.sqlite_errorcode = sqlite3.SQLITE_AUTH
        close_error = sqlite3.OperationalError('SYNTHETIC_PRIVATE_CLOSE')
        close_error.sqlite_errorcode = sqlite3.SQLITE_BUSY
        class RollbackDenied:
            def __getattr__(self, name):
                return getattr(connection, name)
            def execute(self, sql):
                if sql == 'ROLLBACK':
                    raise rollback_error
                return connection.execute(sql)
        try:
            with patch.object(D, 'EXECUTION_PINS', pins()), patch.object(D, 'load_modules', return_value=self.modules), \
                    patch.object(D, 'connect_reader', return_value=RollbackDenied()), \
                    patch.object(self.modules['S'], 'Store', return_value=st), \
                    patch.object(st, 'close', side_effect=close_error) as close, \
                    patch.object(D, 'collect', return_value={}, side_effect=ValueError(primary) if primary else None), \
                    patch.object(D, 'validate_result', return_value={}):
                expected_code = 'D3_READ_FAILED' if primary else 'D3_CLEANUP_FAILED'
                with self.assertRaisesRegex(ValueError, '^' + expected_code + '$'):
                    D.read_database('/synthetic/not-opened.db', self.image, now=now)
                close.assert_called_once()
                return D.READ_FAILURE_STAGE, D.READ_FAILURE_REASON
        finally:
            st.close()

    def test_reason_primary_survives_rollback_and_close_different_failures(self):
        self.assertEqual(self.cleanup_reason_case('D3_DEADLINE'), ('DB_QUERY', 'D3_DEADLINE'))

    def test_reason_first_cleanup_failure_survives_later_close_failure(self):
        self.assertEqual(self.cleanup_reason_case(None), ('CLEANUP', 'D3_SQLITE_AUTH'))

    def test_reason_known_source_failure_is_closed_and_next_success_resets_reason(self):
        with patch.object(D, 'EXECUTION_PINS', pins()), \
                patch.object(D, 'verify_source', side_effect=ValueError('D3_SOURCE_PIN')), \
                patch.object(D, 'connect_reader', side_effect=denied) as db:
            with self.assertRaisesRegex(ValueError, '^D3_READ_FAILED$'):
                D.read_database('/synthetic/not-opened.db', self.image)
            self.assertEqual((D.READ_FAILURE_STAGE, D.READ_FAILURE_REASON), ('SOURCE', 'D3_SOURCE_PIN'))
            db.assert_not_called()
        # Existing real URI test verifies success retains the exact result and clears both metadata fields.
        self.test_image_actual_uri_reader_single_snapshot_no_db_mutation()
        self.assertIsNone(D.READ_FAILURE_STAGE)
        self.assertIsNone(D.READ_FAILURE_REASON)


if __name__ == '__main__':
    unittest.main()
