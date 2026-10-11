"""Synthetic SQLite/file regression only; no app, network, or real source data."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import hashlib
import importlib.util
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


SOURCE = Path(__file__).resolve().parents[1] / 'naver_market_export.py'
SPEC = importlib.util.spec_from_file_location('market_export_under_test', SOURCE)
M = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = M
SPEC.loader.exec_module(M)
NOW = datetime(2026, 10, 12, 5, tzinfo=timezone.utc)
URL = 'https://smartstore.naver.com/Synthetic/products/12345'
STORE = 'smartstore.naver.com/Synthetic'
KEYWORD = '합성 과자'
OID = '923180e2-8522-4e61-b431-6c502de92101'


def payload(keyword=KEYWORD, oid=OID, stamp=NOW - timedelta(hours=1), prices=('1000', '2000', '')):
    products = [{'rank': i, 'sourcePage': 1, 'productId': str(i), 'nvMid': str(i),
        'link': f'https://example.com/products/{i}', 'price': price,
        'title': 'PRIVATE_PRODUCT', 'mallName': 'PRIVATE_COMPETITOR', 'reviewCount': '99999'}
        for i, price in enumerate(prices, 1)]
    return {'keyword': keyword, 'total': 9999, 'products': products, 'meta': {
        'sort': 'rel', 'productSet': 'total', 'pageSize': 40,
        'rawCount': len(products), 'adSkipped': 0, 'dupSkipped': 0, 'adHintMissed': 0,
        'collectorVersion': 'synthetic', 'rankPolicy': 'organic-v3(ad:legacy-or-adId+adType+adcrUrl@ader)',
        'PRIVATE_RAW': 'PRIVATE_CONTACT 010-1111-2222',
        'observation': {'schemaVersion': 1, 'observationId': oid, 'workerId': 'PRIVATE_WORKER',
            'keyword': keyword, 'status': 'complete', 'stopReason': 'SHORT_PAGE',
            'startedAt': (stamp - timedelta(minutes=5)).isoformat(), 'finishedAt': stamp.isoformat(),
            'requestedDepth': 300, 'pagesRead': 1, 'organicCount': len(products),
            'coveredThroughRank': len(products), 'targetIds': [], 'pageEvidence': [{
                'page': 1, 'keyword': keyword, 'verified': True, 'source': 'tap',
                'href': 'https://search.shopping.naver.com/search/all?' + M.urlencode({'query': keyword})}]}}}


class MarketExportTests(unittest.TestCase):
    def fixture(self, base=URL, main=KEYWORD, mapping=None, muted=(), extra_clients=()):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        root = Path(directory.name)
        database, output = root / 'synthetic.sqlite3', root / 'bundle.json'
        conn = sqlite3.connect(database)
        conn.executescript('''
            CREATE TABLE clients(id INTEGER PRIMARY KEY,naver_store_url TEXT,main_keywords TEXT,role TEXT,vertical TEXT,notes TEXT);
            CREATE TABLE client_keyword_product(client_id INTEGER,keyword TEXT,product_url TEXT);
            CREATE TABLE client_keyword_mute(client_id INTEGER,keyword TEXT);
            CREATE TABLE collector_observations(observation_id TEXT PRIMARY KEY,keyword TEXT,collected_date TEXT,
                status TEXT,kind TEXT,reason TEXT,payload_hash TEXT,products_json TEXT,meta_json TEXT,received_at TEXT);
            CREATE TABLE collected_serp(keyword TEXT,collected_date TEXT,total INTEGER,products_json TEXT,meta_json TEXT,
                UNIQUE(keyword,collected_date));
        ''')
        conn.execute('INSERT INTO clients VALUES(1,?,?,\'advertiser\',\'store\',\'PRIVATE_NOTES\')', (base, main))
        for row in extra_clients:
            conn.execute('INSERT INTO clients VALUES(?,?,?,?,?,?)', row)
        if mapping is not None:
            conn.executemany('INSERT INTO client_keyword_product VALUES(1,?,?)', mapping)
        conn.executemany('INSERT INTO client_keyword_mute VALUES(1,?)', [(k,) for k in muted])
        conn.commit()
        conn.close()
        return database, output

    def add(self, database, item=None, received=None, day='2026-10-12', status='complete', kind='full',
            reason='COMPLETE', digest=None, save_serp=True):
        item = deepcopy(item or payload())
        received = received or (NOW - timedelta(minutes=55)).isoformat()
        conn = sqlite3.connect(database)
        digest = digest or hashlib.sha256(M._canonical(item).encode()).hexdigest()
        conn.execute('INSERT INTO collector_observations VALUES(?,?,?,?,?,?,?,?,?,?)',
            (item['meta']['observation']['observationId'], item['keyword'], day, status, kind, reason,
             digest, M._canonical(item['products']), M._canonical(item['meta']), received))
        if save_serp:
            conn.execute('INSERT OR REPLACE INTO collected_serp VALUES(?,?,?,?,?)',
                (item['keyword'], day, item['total'], M._canonical(item['products']), M._canonical(item['meta'])))
        conn.commit()
        conn.close()

    def export(self, database, output, **kwargs):
        M.export_database(database, output, now=NOW, **kwargs)
        return json.loads(output.read_text())

    def cohort(self, bundle):
        return bundle['stores'][0]['cohorts'][0]

    def assert_unavailable(self, item, **add_options):
        database, output = self.fixture()
        self.add(database, item, **add_options)
        store = self.export(database, output)['stores'][0]
        self.assertEqual('no_observations', store['status'])
        self.assertEqual([], store['cohorts'])

    def test_closed_bundle_readonly_and_no_private_content(self):
        database, output = self.fixture()
        self.add(database)
        before = (database.read_bytes(), database.stat().st_mtime_ns)
        bundle = self.export(database, output)
        cohort = self.cohort(bundle)
        self.assertEqual({'schema_version', 'exported_at', 'complete', 'stores'}, set(bundle))
        self.assertEqual(STORE, bundle['stores'][0]['store_key'])
        self.assertEqual([1000, 2000, None], [s['price'] for s in cohort['samples']])
        self.assertEqual(URL.removeprefix('https://'), cohort['product_key'])
        self.assertEqual({'key', 'price'}, set(cohort['samples'][0]))
        self.assertEqual(hashlib.sha256(b'https://example.com/products/1').hexdigest(), cohort['samples'][0]['key'])
        for key in ('device', 'region', 'filters'):
            self.assertIsNone(cohort[key])
        self.assertEqual(before, (database.read_bytes(), database.stat().st_mtime_ns))
        self.assertEqual(0o640, stat.S_IMODE(output.stat().st_mode))
        text = output.read_text()
        for forbidden in ('PRIVATE_', '010-1111', 'reviewCount', 'nvMid', 'example.com', 'rawCount', 'rankPolicy'):
            self.assertNotIn(forbidden, text)

    def test_current_main_keyword_and_mute_only(self):
        for main, muted in [('different', ()), (KEYWORD, (KEYWORD,))]:
            with self.subTest(main=main, muted=muted):
                database, output = self.fixture(main=main, muted=muted)
                self.add(database)
                self.assertEqual('no_observations', self.export(database, output)['stores'][0]['status'])

    def test_base_home_requires_explicit_exact_product_mapping(self):
        for mapping, expected in [(None, 'no_observations'), ([(KEYWORD, URL)], 'ok'),
                ([(KEYWORD, 'https://smartstore.naver.com/Other/products/12345')], 'no_observations'),
                ([(KEYWORD, '')], 'no_observations')]:
            with self.subTest(mapping=mapping):
                database, output = self.fixture(base='https://smartstore.naver.com/Synthetic', mapping=mapping)
                self.add(database)
                self.assertEqual(expected, self.export(database, output)['stores'][0]['status'])

    def test_present_invalid_assignment_never_falls_back_to_base(self):
        for assigned in ('bad', 'https://smartstore.naver.com/Other/products/12345', 'https://smartstore.naver.com/Synthetic'):
            with self.subTest(assigned=assigned):
                database, output = self.fixture(mapping=[(KEYWORD, assigned)])
                self.add(database)
                self.assertEqual('no_observations', self.export(database, output)['stores'][0]['status'])

    def test_duplicate_store_and_contradictory_mapping_ambiguous(self):
        for options in [dict(extra_clients=[(2, URL, KEYWORD, 'advertiser', 'store', '')]),
                dict(mapping=[(KEYWORD, URL), (KEYWORD, URL.replace('12345', '999'))])]:
            with self.subTest(options=options):
                database, output = self.fixture(**options)
                self.add(database)
                self.assertEqual('ambiguous', self.export(database, output)['stores'][0]['status'])

    def test_non_advertiser_and_place_do_not_create_fake_duplicates(self):
        database, output = self.fixture(extra_clients=[(2, URL, KEYWORD, 'competitor', 'store', ''),
            (3, URL, KEYWORD, 'advertiser', 'place', '')])
        self.add(database)
        self.assertEqual('ok', self.export(database, output)['stores'][0]['status'])

    def test_newest_partial_failed_legacy_blocks_older_complete(self):
        for status, kind, reason in [('partial', 'positive', 'BLOCKED'), ('failed', 'evidence_only', 'READ_FAILED'),
                ('legacy', 'full', 'LEGACY'), ('target_complete', 'full_positive', 'TARGETS_FOUND')]:
            with self.subTest(status=status):
                database, output = self.fixture()
                self.add(database)
                newest = payload(oid=OID[:-1] + '2', stamp=NOW - timedelta(minutes=15))
                newest['meta']['observation']['status'] = status
                self.add(database, newest, received=(NOW - timedelta(minutes=10)).isoformat(),
                    status=status, kind=kind, reason=reason, save_serp=False)
                self.assertEqual('no_observations', self.export(database, output)['stores'][0]['status'])

    def test_newest_invalid_and_unorderable_never_fall_back(self):
        for options in [dict(digest='0' * 64), dict(received='not a time')]:
            with self.subTest(options=options):
                database, output = self.fixture()
                self.add(database)
                newest = payload(oid=OID[:-1] + '2', stamp=NOW - timedelta(minutes=15))
                self.add(database, newest, received=options.pop('received', (NOW - timedelta(minutes=10)).isoformat()), **options)
                self.assertEqual('no_observations', self.export(database, output)['stores'][0]['status'])

    def test_different_current_keyword_can_supply_latest_valid_sample(self):
        database, output = self.fixture(main=KEYWORD + ', 다른 과자')
        self.add(database)
        self.add(database, payload(keyword='다른 과자', oid=OID[:-1] + '2', stamp=NOW - timedelta(minutes=15)),
            received=(NOW - timedelta(minutes=10)).isoformat())
        self.assertEqual('다른 과자', self.cohort(self.export(database, output))['keyword'])
        self.assertEqual(1, len(self.export(database, output)['stores'][0]['cohorts']))

    def test_original_pair_hash_total_and_same_observation_required(self):
        for mutation in ('missing', 'total', 'meta', 'products', 'observation'):
            with self.subTest(mutation=mutation):
                database, output = self.fixture()
                self.add(database)
                conn = sqlite3.connect(database)
                if mutation == 'missing':
                    conn.execute('DELETE FROM collected_serp')
                elif mutation == 'total':
                    conn.execute('UPDATE collected_serp SET total=5')
                else:
                    item = payload()
                    if mutation == 'products':
                        item['products'][0]['price'] = '999'
                        conn.execute('UPDATE collected_serp SET products_json=?', (M._canonical(item['products']),))
                    else:
                        if mutation == 'observation':
                            item['meta']['observation']['observationId'] = OID[:-1] + '2'
                        else:
                            item['meta']['pageSize'] = 80
                        conn.execute('UPDATE collected_serp SET meta_json=?', (M._canonical(item['meta']),))
                conn.commit()
                conn.close()
                self.assertEqual('no_observations', self.export(database, output)['stores'][0]['status'])

    def test_rank_page_link_dedup_and_count_corruption(self):
        cases = []
        for field, value in [('rank', 2), ('rank', True), ('sourcePage', 0), ('sourcePage', 2),
                ('link', 'javascript:alert(1)'), ('link', 'https://example.com/products/2')]:
            item = payload()
            item['products'][0][field] = value
            cases.append(item)
        for field, value in [('organicCount', 2), ('coveredThroughRank', 2), ('pagesRead', 2), ('requestedDepth', 2)]:
            item = payload()
            item['meta']['observation'][field] = value
            cases.append(item)
        item = payload()
        item['meta']['rawCount'] = 2
        cases.append(item)
        for index, item in enumerate(cases):
            with self.subTest(index=index):
                self.assert_unavailable(item)

    def test_envelope_keyword_uuid_source_and_url_conditions(self):
        cases = []
        for field, value in [('schemaVersion', True), ('keyword', 'wrong'), ('status', 'partial')]:
            item = payload()
            item['meta']['observation'][field] = value
            cases.append(item)
        for field, value in [('verified', False), ('source', 'unknown'), ('keyword', 'wrong'),
                ('href', 'https://example.com/search/all?query=x'),
                ('href', 'https://search.shopping.naver.com/search/all?query=wrong')]:
            item = payload()
            item['meta']['observation']['pageEvidence'][0][field] = value
            cases.append(item)
        item = payload(oid='not-a-uuid')
        cases.append(item)
        for index, item in enumerate(cases):
            with self.subTest(index=index):
                self.assert_unavailable(item)

    def test_time_freshness_duration_receive_and_naive_boundaries(self):
        cases = []
        for field, value in [('startedAt', NOW.isoformat()), ('startedAt', (NOW - timedelta(days=2)).isoformat()),
                ('finishedAt', (NOW + timedelta(minutes=6)).isoformat()), ('finishedAt', '2026-10-12 04:00:00')]:
            item = payload()
            item['meta']['observation'][field] = value
            cases.append((item, {}))
        cases.extend([(payload(stamp=NOW - timedelta(hours=73)), {'received': (NOW - timedelta(hours=72)).isoformat()}),
            (payload(), {'received': (NOW - timedelta(hours=2)).isoformat()}),
            (payload(stamp=NOW - timedelta(hours=26)), {'received': NOW.isoformat()}),
            (payload(), {'received': (NOW + timedelta(minutes=6)).isoformat()})])
        for index, (item, options) in enumerate(cases):
            with self.subTest(index=index):
                self.assert_unavailable(item, **options)
        database, output = self.fixture()
        self.add(database, received='2026-10-12 13:05:00')
        self.assertEqual('2026-10-12T04:05:00+00:00', self.cohort(self.export(database, output))['recorded_at'])

    def test_price_missing_zero_estimated_and_invalid_are_null(self):
        values = ('0', '', '1200원', '약 1000', '1,200', '-1', '1.2', '1000000000001', None, '1', '1000000000000')
        database, output = self.fixture()
        self.add(database, payload(prices=values))
        self.assertEqual([None] * 9 + [1, 10**12], [s['price'] for s in self.cohort(self.export(database, output))['samples']])

    def test_result_identity_normalization_and_invalid_url(self):
        self.assertEqual('https://example.com/a?b=1', M.result_identity('HTTPS://EXAMPLE.COM:443/a?b=1#x'))
        for url in ('https://user:pass@example.com/a', 'https://example.com:444/a', 'http://localhost/a',
                'https://example.com/\nprivate', 'https://example.com\\@other.com/a', 'javascript:alert(1)'):
            self.assertIsNone(M.result_identity(url))
        item = payload()
        item['products'][1]['link'] = 'https://EXAMPLE.com:443/products/1#x'
        self.assert_unavailable(item)

    def test_same_exact_product_tracking_urls_are_duplicates(self):
        item = payload()
        item['products'][0]['link'] = URL + '?track=one'
        item['products'][1]['link'] = URL + '?track=two#fragment'
        self.assertEqual(URL, M.result_identity(item['products'][1]['link']))
        self.assert_unavailable(item)

    def test_non_text_current_keywords_stay_unknown(self):
        database, output = self.fixture(main=123)
        self.add(database)
        self.assertEqual('no_observations', self.export(database, output)['stores'][0]['status'])

    def test_keyword_private_markup_and_unicode_control_not_exported(self):
        for keyword in ('https://example.com', '010-1111-2222', '<b>과자</b>', '과자\u202e'):
            database, output = self.fixture(main=keyword)
            self.add(database, payload(keyword=keyword))
            self.assertEqual('no_observations', self.export(database, output)['stores'][0]['status'])

    def test_limits_and_failed_export_preserve_prior_complete_file(self):
        database, output = self.fixture()
        self.add(database)
        output.write_text('PRIOR_COMPLETE')
        for limits in (M.Limits(max_json_cell_bytes=20), M.Limits(max_input_bytes=50),
                M.Limits(max_output_bytes=50), M.Limits(max_rows=1), M.Limits(max_seconds=-1)):
            with self.subTest(limits=limits), self.assertRaises(M.ExportInvalid):
                M.export_database(database, output, now=NOW, limits=limits)
            self.assertEqual('PRIOR_COMPLETE', output.read_text())

    def test_client_limit_counts_invalid_candidates_too(self):
        database, output = self.fixture(base='invalid', extra_clients=[(2, URL, KEYWORD, 'advertiser', 'store', '')])
        with self.assertRaises(M.ExportInvalid):
            M.export_database(database, output, now=NOW, limits=M.Limits(max_clients=1))

    def test_authorizer_blocks_private_columns_and_source_writes(self):
        database, output = self.fixture()
        self.add(database)
        conn = sqlite3.connect(database, isolation_level=None)
        self.addCleanup(conn.close)
        M.collect(conn, now=NOW)
        for statement in ('SELECT notes FROM clients', "UPDATE clients SET notes='changed'", 'PRAGMA user_version=20'):
            with self.subTest(statement=statement), self.assertRaises(sqlite3.DatabaseError):
                conn.execute(statement)

    def test_invalid_json_and_duplicate_json_keys_do_not_promote_source(self):
        for text in ('{', '{"observation":{},"observation":{}}', '[' * 2000):
            database, output = self.fixture()
            self.add(database)
            conn = sqlite3.connect(database)
            conn.execute('UPDATE collector_observations SET meta_json=?', (text,))
            conn.commit()
            conn.close()
            self.assertEqual('no_observations', self.export(database, output)['stores'][0]['status'])

    def test_nonstandard_json_constants_cannot_impersonate_original_null_hash(self):
        for constant in ('NaN', 'Infinity', '-Infinity'):
            with self.subTest(constant=constant):
                database, output = self.fixture()
                item = payload(prices=(None, '2000', ''))
                self.add(database, item)
                altered = M._canonical(item['products']).replace('"price":null', '"price":' + constant)
                conn = sqlite3.connect(database)
                conn.execute('UPDATE collector_observations SET products_json=?', (altered,))
                conn.execute('UPDATE collected_serp SET products_json=?', (altered,))
                conn.commit()
                conn.close()
                self.assertEqual('no_observations', self.export(database, output)['stores'][0]['status'])

    def test_postreplace_fsync_warning_reports_published_complete_file(self):
        database, output = self.fixture()
        self.add(database)
        output.write_text('PRIOR_COMPLETE')
        actual = M.P.os.fsync
        calls = []
        def fail_directory(fd):
            calls.append(fd)
            if len(calls) == 2:
                raise OSError('PRIVATE_FAILURE')
            return actual(fd)
        with patch.object(M.P.os, 'fsync', side_effect=fail_directory):
            result = M.export_database(database, output, now=NOW)
        self.assertEqual('ok', result['status'])
        self.assertEqual('EXPORT_DURABILITY_UNCONFIRMED', result['warning'])
        self.assertTrue(json.loads(output.read_text())['complete'])

    def test_standalone_isolated_cli_and_fixed_failure_output(self):
        database, output = self.fixture()
        self.add(database, payload(stamp=datetime.now(timezone.utc) - timedelta(hours=1)),
            received=(datetime.now(timezone.utc) - timedelta(minutes=55)).isoformat())
        result = subprocess.run([sys.executable, '-I', str(SOURCE), '--database', str(database), '--output', str(output)],
            capture_output=True, text=True, timeout=5)
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual('ok', json.loads(result.stdout)['status'])
        self.assertEqual('', result.stderr)
        result = subprocess.run([sys.executable, '-I', str(SOURCE), '--database', str(database) + '.missing', '--output', str(output)],
            capture_output=True, text=True, timeout=5)
        self.assertEqual(1, result.returncode)
        self.assertEqual({'status': 'failed', 'code': 'SOURCE_PATH'}, json.loads(result.stdout))
        self.assertEqual('', result.stderr)


if __name__ == '__main__':
    unittest.main()
