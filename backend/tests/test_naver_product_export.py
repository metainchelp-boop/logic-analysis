"""Stdlib-only synthetic SQLite/files; no production data, app imports or network."""
from contextlib import redirect_stdout
from datetime import datetime, timezone
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import sqlite3
import stat
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch


SOURCE = Path(__file__).resolve().parents[1] / 'naver_product_export.py'
SPEC = importlib.util.spec_from_file_location('product_export_under_test', SOURCE)
M = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = M
SPEC.loader.exec_module(M)
NOW = datetime(2026, 10, 12, 5, tzinfo=timezone.utc)
URL = 'https://smartstore.naver.com/Synthetic/products/12345'
OTHER = 'https://smartstore.naver.com/Other/products/12345'


def tagged(value, status='measured', sources=None):
    return {'value': value, 'status': status, 'sources': sources or ['html_meta'],
            'confidence': 'medium', 'note': 'PRIVATE_NOTE'}


def analysis(price=13000, review_count=0, rating=4.7):
    return {'htmlDetail': {'success': True,
        'metrics': {'has_delivery_info': True, 'has_return_info': False, 'has_gift_info': None,
                    'has_certification': False, 'has_review_section': True, 'has_spec_table': False},
        'reviewData': {'source': 'html', 'price': price, 'reviewCount': review_count, 'rating': rating,
            'reviews': [{'name': 'PRIVATE_CUSTOMER', 'text': 'PRIVATE_REVIEW 010-1111-2222'}],
            'reviewTextAnalysis': {'summary': 'PRIVATE_AI_CLAIM'},
            'data_quality': {'price': tagged(price, sources=['html_json_ld']),
                             'review_count': tagged(review_count),
                             'rating': tagged(rating, 'cross_verified', ['html_meta', 'review_sample'])}}},
        'scores': {'price': 99}, 'suggestions': ['PRIVATE_STRATEGY'], 'html': '<p>PRIVATE_HTML</p>'}


def advertiser(url=URL, name='합성 상품', category='식품>가공식품'):
    return {'product_url': url, 'product_info': {'product_name': name, 'category': category, 'price': 999999},
            'entry_strategy': {'summary': 'PRIVATE_AI_STRATEGY'}, 'competitor_comparison': {'items': ['PRIVATE_COMPETITOR']}}


class ProductExportTests(unittest.TestCase):
    def fixture(self, clients=None, rows=None):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        root = Path(directory.name)
        database, output = root / 'synthetic.sqlite3', root / 'bundle.json'
        conn = sqlite3.connect(database)
        conn.executescript('''CREATE TABLE clients(id INTEGER PRIMARY KEY, naver_store_url TEXT,
            role TEXT, vertical TEXT, name TEXT, contact_phone TEXT, notes TEXT, detail_html TEXT);
            CREATE TABLE client_analyses(id INTEGER PRIMARY KEY, client_id INTEGER,
            product_url TEXT, updated_at TEXT, analysis_json TEXT, advertiser_json TEXT,
            report_html TEXT, keyword TEXT);''')
        clients = clients if clients is not None else [(1, URL, 'advertiser', 'store')]
        for client in clients:
            conn.execute('INSERT INTO clients VALUES (?,?,?,?,?,?,?,?)',
                         (*client, 'PRIVATE_CLIENT', '010-1111-2222', 'PRIVATE_STAFF_NOTE', '<p>PRIVATE_HTML</p>'))
        rows = rows if rows is not None else [(1, 1, URL, '2026-10-11 18:00:00', analysis(), advertiser())]
        for rowid, cid, url, at, result, adv in rows:
            conn.execute('INSERT INTO client_analyses VALUES (?,?,?,?,?,?,?,?)',
                         (rowid, cid, url, at, result if isinstance(result, str) else json.dumps(result),
                          adv if isinstance(adv, str) else json.dumps(adv), '<p>PRIVATE_REPORT_HTML</p>', 'PRIVATE_KEYWORD'))
        conn.commit()
        conn.close()
        return database, output

    def read(self, database, limits=None):
        conn = sqlite3.connect(database.as_uri() + '?mode=ro', uri=True, isolation_level=None)
        self.addCleanup(conn.close)
        return M.collect(conn, now=NOW, limits=limits)

    def product(self, bundle):
        return bundle['stores'][0]['products'][0]

    def test_exact_keys_zero_null_kst_and_no_private_or_inferred_fields(self):
        database, _ = self.fixture()
        bundle = self.read(database)
        self.assertEqual(set(bundle), {'schema_version', 'exported_at', 'complete', 'stores'})
        self.assertIs(bundle['complete'], True)
        store = bundle['stores'][0]
        self.assertEqual(store['store_key'], 'smartstore.naver.com/Synthetic')
        product = self.product(bundle)
        self.assertEqual(set(product), {'product_key', 'recorded_at', 'observed_at', 'name', 'category', 'metrics', 'features'})
        self.assertEqual(product['recorded_at'], '2026-10-11T09:00:00+00:00')
        self.assertIsNone(product['observed_at'])
        self.assertEqual(product['metrics']['review_count'], {'value': 0, 'status': 'measured', 'sources': ['html_meta']})
        self.assertEqual(product['metrics']['price']['value'], 13000)
        self.assertIs(product['features']['delivery_info'], True)
        self.assertIs(product['features']['return_info'], False)
        self.assertIsNone(product['features']['gift_info'])
        self.assertEqual(set(product['features']), set(M.FEATURES))
        self.assertEqual(product['name'], '합성 상품')
        self.assertNotIn('PRIVATE', json.dumps(bundle, ensure_ascii=False))
        self.assertNotIn('999999', json.dumps(bundle))

    def test_exact_canonical_identity_rejects_prefix_userinfo_port_catalog_and_encoded_paths(self):
        self.assertEqual(M.canonical_product(URL + '?tracking=private#x'), 'smartstore.naver.com/Synthetic/products/12345')
        self.assertEqual(M.canonical_product(URL.replace('smartstore.', 'm.smartstore.')), M.canonical_product(URL))
        self.assertEqual(M.canonical_store('BRAND.naver.com/Store'), 'brand.naver.com/Store')
        self.assertIsNone(M.canonical_product('smartstore.naver.com/Synthetic'))
        self.assertNotEqual(M.canonical_store(URL), M.canonical_store(URL.replace('Synthetic', 'synthetic')))
        bad = [URL.replace('https://', 'ftp://'), URL.replace('https://', 'https://user@'),
               URL.replace('naver.com/', 'naver.com:443/'), URL.replace('naver.com/', 'naver.com.evil/'),
               URL + '/reviews', URL + ';params', URL.replace('12345', '0'), URL.replace('12345', '01'),
               URL.replace('12345', '1' * 25), URL.replace('Synthetic', '%53ynthetic'),
               'https://search.shopping.naver.com/catalog/12345', URL + '\n', ' ' + URL]
        for value in bad:
            with self.subTest(value=value):
                self.assertIsNone(M.canonical_product(value))

    def test_only_exact_store_and_unique_advertiser_client_are_candidates(self):
        clients = [(1, URL, 'advertiser', 'store'), (2, URL + '?other=1', 'advertiser', 'store'),
                   (3, OTHER, 'advertiser', 'store'), (4, OTHER, 'competitor', 'store'),
                   (5, 'https://brand.naver.com/Place', 'advertiser', 'place')]
        rows = [(1, 1, URL, '2026-10-11 18:00:00', analysis(), advertiser()),
                (2, 3, OTHER, '2026-10-11 18:00:00', analysis(), advertiser(OTHER)),
                (3, 3, URL, '2026-10-12 10:00:00', analysis(), advertiser())]
        database, _ = self.fixture(clients, rows)
        stores = {store['store_key']: store for store in self.read(database)['stores']}
        self.assertEqual(len(stores), 2)
        self.assertEqual(stores['smartstore.naver.com/Synthetic'], {'store_key': 'smartstore.naver.com/Synthetic', 'status': 'ambiguous', 'products': []})
        self.assertEqual(stores['smartstore.naver.com/Other']['products'][0]['product_key'], 'smartstore.naver.com/Other/products/12345')

    def test_client_home_and_different_keyword_product_never_inherit_client_level_html(self):
        for client_url in ['https://smartstore.naver.com/Synthetic', URL.replace('12345', '98765')]:
            with self.subTest(client_url=client_url):
                database, _ = self.fixture(clients=[(1, client_url, 'advertiser', 'store')])
                product = self.product(self.read(database))
                self.assertEqual(product['name'], '합성 상품')  # Exact advertiser product report is separately scoped.
                self.assertTrue(all(metric['status'] == 'unavailable' for metric in product['metrics'].values()))
                self.assertTrue(all(value is None for value in product['features'].values()))

    def test_missing_quality_estimates_bad_values_and_inconsistent_sources_stay_unknown(self):
        changes = [('price', tagged(5000, 'estimated')), ('review_count', tagged(5, sources=['rank_based'])),
                   ('rating', tagged(4.5, 'cross_verified', ['html_meta'])), ('rating', tagged(float('inf'))),
                   ('price', tagged(True)), ('price', tagged(10**1000)), ('price', tagged(-1)),
                   ('review_count', tagged(0.5)), ('review_count', tagged(1, sources=['review_sample']))]
        for key, value in changes:
            with self.subTest(key=key, value=str(value)[:100]):
                result = analysis()
                result['htmlDetail']['reviewData']['data_quality'][key] = value
                if value.get('value') == float('inf'):
                    # JSON non-finite is a source parse failure, preserving old export, never a measured value.
                    database, _ = self.fixture(rows=[(1, 1, URL, '2026-10-11 18:00:00', result, advertiser())])
                    with self.assertRaises(M.ExportInvalid): self.read(database)
                    continue
                database, _ = self.fixture(rows=[(1, 1, URL, '2026-10-11 18:00:00', result, advertiser())])
                self.assertEqual(self.product(self.read(database))['metrics'][key], M._unknown())
        result = analysis()
        result['htmlDetail']['reviewData'].pop('data_quality')
        database, _ = self.fixture(rows=[(1, 1, URL, '2026-10-11 18:00:00', result, advertiser())])
        self.assertTrue(all(metric['value'] is None for metric in self.product(self.read(database))['metrics'].values()))

    def test_quality_status_wrong_types_are_unknown_without_crashing_export(self):
        for status in [{}, [], None, False, 1]:
            with self.subTest(status=status):
                result = analysis()
                result['htmlDetail']['reviewData']['data_quality']['price']['status'] = status
                adv = advertiser()
                adv['data_quality'] = {'price': tagged(40000, status=status, sources=['stored_product_info'])}
                database, _ = self.fixture(rows=[(1, 1, URL, '2026-10-11 18:00:00', result, adv)])
                self.assertEqual(self.product(self.read(database))['metrics']['price'], M._unknown())

    def test_rating_sample_retains_sample_source_and_tagged_stored_product_info_is_exact_scoped(self):
        result, adv = analysis(), advertiser()
        result['htmlDetail']['reviewData']['data_quality']['rating'] = tagged(4.2, sources=['review_sample'])
        adv['data_quality'] = {'price': tagged(25000, sources=['stored_product_info'])}
        database, _ = self.fixture(clients=[(1, 'https://smartstore.naver.com/Synthetic', 'advertiser', 'store')],
                                  rows=[(1, 1, URL, '2026-10-11 18:00:00', result, adv)])
        product = self.product(self.read(database))
        self.assertEqual(product['metrics']['price']['value'], 25000)
        self.assertIsNone(product['metrics']['rating']['value'])
        database, _ = self.fixture(rows=[(1, 1, URL, '2026-10-11 18:00:00', result, adv)])
        self.assertEqual(self.product(self.read(database))['metrics']['rating']['sources'], ['review_sample'])
        adv['product_url'] = OTHER
        database, _ = self.fixture(clients=[(1, 'https://smartstore.naver.com/Synthetic', 'advertiser', 'store')],
                                  rows=[(1, 1, URL, '2026-10-11 18:00:00', result, adv)])
        product = self.product(self.read(database))
        self.assertIsNone(product['name'])
        self.assertTrue(all(metric['value'] is None for metric in product['metrics'].values()))

    def test_names_categories_contacts_injections_controls_surrogates_are_null_not_claims(self):
        for value in ['<img onerror=x>', '{{product:1.price}}', '010-1234-5678', 'name@example.com',
                      'https://example.com', 'www.example.com', 'text\x00x', '\u202eevil', '\ud800', 'a' * 101]:
            with self.subTest(value=repr(value)):
                database, _ = self.fixture(rows=[(1, 1, URL, '2026-10-11 18:00:00', {}, advertiser(name=value, category=value))])
                product = self.product(self.read(database))
                self.assertIsNone(product['name']); self.assertIsNone(product['category'])

    def test_latest_exact_product_uses_normalized_save_time_then_rowid_and_limits_to_three(self):
        rows = []
        for n in range(1, 6):
            url = URL.replace('12345', str(1000 + n))
            rows.append((n, 1, url, f'2026-10-{n+1:02} 10:00:00', {}, advertiser(url, name=f'상품 {n}')))
        url = URL.replace('12345', '1005')
        rows += [(10, 1, url + '?tracking=old', '2026-10-06T01:00:00+00:00', {}, advertiser(url, name='동시각 뒤 행')),
                 (11, 1, url, '2026-10-05T23:00:00+00:00', {}, advertiser(url, name='행번호 크지만 이전 시각'))]
        database, _ = self.fixture(rows=rows)
        products = self.read(database)['stores'][0]['products']
        self.assertEqual(len(products), 3)
        self.assertEqual(products[0]['name'], '동시각 뒤 행')
        self.assertEqual([p['product_key'].rsplit('/', 1)[-1] for p in products], ['1005', '1004', '1003'])

    def test_unselected_historical_json_is_not_loaded_and_metadata_is_byte_bounded(self):
        rows = [(1, 1, URL, '2026-10-10 18:00:00', '{malformed-old-json', 'x' * 4096),
                (2, 1, URL, '2026-10-11 18:00:00', analysis(), advertiser())]
        database, _ = self.fixture(rows=rows)
        self.assertEqual(self.product(self.read(database, M.Limits(max_json_cell_bytes=2048)))['name'], '합성 상품')
        # Large metadata is counted even though its full TEXT never crosses into Python.
        database, _ = self.fixture(clients=[(1, URL + '?q=' + 'x' * 9000, 'advertiser', 'store')], rows=[])
        with self.assertRaises(M.ExportInvalid) as caught:
            self.read(database, M.Limits(max_input_bytes=8192))
        self.assertEqual(caught.exception.code, 'SOURCE_LIMIT')
        database, _ = self.fixture(rows=[(1, 1, URL, 'x' * 201, analysis(), advertiser())])
        self.assertEqual(self.read(database)['stores'][0]['status'], 'no_products')

    def test_unknown_or_future_save_time_is_not_promoted_and_stale_records_keep_their_real_age(self):
        for date in ['not-a-date', '2026-10-11', '2026-99-40 10:00:00', '2026-10-12T05:05:01+00:00']:
            rows = [(1, 1, URL, '2026-10-11 18:00:00', analysis(), advertiser()), (2, 1, URL, date, analysis(), advertiser())]
            database, _ = self.fixture(rows=rows)
            self.assertEqual(self.read(database)['stores'][0]['status'], 'no_products')
        database, _ = self.fixture(rows=[(1, 1, URL, '2025-01-01 10:00:00', analysis(), advertiser())])
        self.assertEqual(self.product(self.read(database))['recorded_at'], '2025-01-01T01:00:00+00:00')

    def test_read_transaction_denies_mutations_other_tables_private_columns_and_extensions(self):
        database, _ = self.fixture()
        conn = sqlite3.connect(database.as_uri() + '?mode=ro', uri=True, isolation_level=None)
        self.addCleanup(conn.close)
        M.collect(conn, now=NOW)
        self.assertTrue(conn.in_transaction)
        for sql in ['DELETE FROM clients', 'UPDATE clients SET role="advertiser"', 'CREATE TABLE leak(x)',
                    'PRAGMA query_only=OFF', "ATTACH ':memory:' AS other", "SELECT load_extension('bad')",
                    'SELECT contact_phone FROM clients', 'SELECT report_html FROM client_analyses', 'COMMIT']:
            with self.subTest(sql=sql), self.assertRaises(sqlite3.DatabaseError): conn.execute(sql)

    def test_export_is_atomic_0640_and_does_not_modify_source_database(self):
        database, output = self.fixture()
        before, mtime = hashlib.sha256(database.read_bytes()).hexdigest(), database.stat().st_mtime_ns
        result = M.export_database(database, output, now=NOW)
        self.assertEqual(result['status'], 'ok')
        self.assertEqual(stat.S_IMODE(output.stat().st_mode), 0o640)
        self.assertEqual(hashlib.sha256(database.read_bytes()).hexdigest(), before)
        self.assertEqual(database.stat().st_mtime_ns, mtime)
        self.assertEqual(json.loads(output.read_text())['stores'][0]['status'], 'ok')
        self.assertEqual(list(output.parent.glob('.naver-product-*.tmp')), [])

    def test_precommit_fsync_failure_preserves_previous_but_postcommit_is_durability_warning(self):
        database, output = self.fixture()
        previous = b'PREVIOUS_COMPLETE_BUNDLE\n'
        output.write_bytes(previous)
        with patch.object(M.os, 'fsync', side_effect=OSError('PRIVATE_SYNC_ERROR')):
            with self.assertRaises(M.ExportInvalid) as caught:
                M.export_database(database, output, now=NOW)
        self.assertEqual(caught.exception.code, 'OUTPUT_WRITE')
        self.assertEqual(output.read_bytes(), previous)
        self.assertEqual(list(output.parent.glob('.naver-product-*.tmp')), [])
        real_fsync = M.os.fsync

        def fail_directory_only(fd):
            if stat.S_ISDIR(os.fstat(fd).st_mode):
                raise OSError('PRIVATE_DIRECTORY_SYNC_ERROR')
            return real_fsync(fd)

        with patch.object(M.os, 'fsync', side_effect=fail_directory_only):
            result = M.export_database(database, output, now=NOW)
        self.assertEqual(result['status'], 'ok')
        self.assertEqual(result['warning'], 'EXPORT_DURABILITY_UNCONFIRMED')
        bundle = json.loads(output.read_bytes())
        self.assertIs(bundle['complete'], True)
        self.assertEqual(bundle['stores'][0]['products'][0]['metrics']['price']['value'], 13000)
        self.assertEqual(list(output.parent.glob('.naver-product-*.tmp')), [])
        self.assertNotIn('PRIVATE', json.dumps(result))

    def test_limits_parse_errors_missing_schema_and_write_failure_preserve_previous_bundle(self):
        database, output = self.fixture()
        previous = b'PREVIOUS_COMPLETE_BUNDLE\n'
        limits = [(M.Limits(max_clients=0), 'SOURCE_LIMIT'), (M.Limits(max_rows=1), 'SOURCE_LIMIT'),
                  (M.Limits(max_input_bytes=20), 'SOURCE_LIMIT'), (M.Limits(max_json_cell_bytes=10), 'SOURCE_LIMIT'),
                  (M.Limits(max_output_bytes=20), 'EXPORT_LIMIT'), (M.Limits(max_seconds=-1), 'SOURCE_LIMIT')]
        for limit, code in limits:
            output.write_bytes(previous)
            with self.subTest(limit=limit), self.assertRaises(M.ExportInvalid) as caught:
                M.export_database(database, output, now=NOW, limits=limit)
            self.assertEqual(caught.exception.code, code)
            self.assertEqual(output.read_bytes(), previous)
        for value in ['{bad-json', '{"duplicate":1,"duplicate":2}', '{"value":NaN}', '[]']:
            bad_db, bad_output = self.fixture(rows=[(1, 1, URL, '2026-10-11 18:00:00', value, advertiser())])
            bad_output.write_bytes(previous)
            with self.subTest(value=value), self.assertRaises(M.ExportInvalid) as caught:
                M.export_database(bad_db, bad_output, now=NOW)
            self.assertEqual(caught.exception.code, 'SOURCE_JSON')
            self.assertEqual(bad_output.read_bytes(), previous)
        output.write_bytes(previous)
        with patch.object(M.os, 'replace', side_effect=OSError('PRIVATE_WRITE_ERROR')):
            with self.assertRaises(M.ExportInvalid): M.export_database(database, output, now=NOW)
        self.assertEqual(output.read_bytes(), previous)
        self.assertEqual(list(output.parent.glob('.naver-product-*.tmp')), [])
        missing = database.parent / 'missing.sqlite3'
        with self.assertRaises(M.ExportInvalid): M.export_database(missing, output, now=NOW)
        self.assertFalse(missing.exists())
        schema = database.parent / 'schema.sqlite3'; sqlite3.connect(schema).close()
        with self.assertRaises(M.ExportInvalid): M.export_database(schema, output, now=NOW)
        self.assertEqual(output.read_bytes(), previous)

    def test_output_cannot_replace_database_hardlinks_symlinks_or_non_json_paths(self):
        database, output = self.fixture()
        for target in [database, database.parent / 'other.bin']:
            with self.subTest(target=target), self.assertRaises(M.ExportInvalid): M.export_database(database, target, now=NOW)
        hardlink = database.parent / 'hardlink.json'; os.link(database, hardlink)
        with self.assertRaises(M.ExportInvalid): M.export_database(database, hardlink, now=NOW)
        output.symlink_to(database)
        with self.assertRaises(M.ExportInvalid): M.export_database(database, output, now=NOW)

    def test_cli_failure_prints_fixed_code_and_success_has_only_bounded_counts(self):
        database, output = self.fixture()
        stream = io.StringIO()
        with redirect_stdout(stream): result = M.main(['--database', str(database), '--output', str(output)])
        self.assertEqual(result, 0)
        self.assertEqual(set(json.loads(stream.getvalue())), {'status', 'stores', 'products', 'bytes'})
        stream = io.StringIO()
        with redirect_stdout(stream): result = M.main(['--database', str(database.parent / 'PRIVATE_MISSING'), '--output', str(output)])
        self.assertEqual(result, 1)
        self.assertEqual(json.loads(stream.getvalue()), {'status': 'failed', 'code': 'SOURCE_PATH'})
        self.assertNotIn('PRIVATE', stream.getvalue())

    def test_standalone_cli_works_with_only_stdlib_and_synthetic_source(self):
        database, output = self.fixture()
        completed = subprocess.run([sys.executable, '-I', str(SOURCE), '--database', str(database), '--output', str(output)],
                                   capture_output=True, text=True, timeout=5)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(json.loads(completed.stdout)['status'], 'ok')
        self.assertNotIn('PRIVATE', completed.stdout + completed.stderr)


if __name__ == '__main__':
    unittest.main()
