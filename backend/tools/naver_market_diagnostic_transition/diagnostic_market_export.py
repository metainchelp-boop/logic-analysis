"""Export saved, hash-verified search samples without app imports or source writes.

This is a next-plan sample, not market coverage or live ad/competitor performance.
Only the dedicated JSON artifact crosses into the report engine.
"""
import argparse
from datetime import datetime, timedelta, timezone
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import sqlite3
import stat
import sys
import unicodedata
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from uuid import UUID


# Resolve this reviewed sibling by exact path, including standalone python -I.
_SPEC = importlib.util.spec_from_file_location(
    '_naver_market_product_primitives', Path(__file__).resolve().with_name('naver_product_export.py'))
P = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = P
_SPEC.loader.exec_module(P)
ExportInvalid, Limits = P.ExportInvalid, P.Limits
_READ_COLUMNS = {
    'clients': frozenset({'id', 'naver_store_url', 'main_keywords', 'role', 'vertical'}),
    'client_keyword_product': frozenset({'client_id', 'keyword', 'product_url'}),
    'client_keyword_mute': frozenset({'client_id', 'keyword'}),
    'collector_observations': frozenset({'observation_id', 'keyword', 'collected_date', 'status',
        'kind', 'reason', 'payload_hash', 'products_json', 'meta_json', 'received_at'}),
    'collected_serp': frozenset({'keyword', 'collected_date', 'total', 'products_json', 'meta_json'}),
}
_HEX = re.compile(r'[0-9a-f]{64}')
_SOURCES = frozenset({'tap', 'router', 'nextdata'})
_FUTURE = timedelta(minutes=5)
_AGE = timedelta(hours=72)


def _canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)


def result_identity(value):
    """A search-row identity only; this never establishes advertiser ownership."""
    if (not isinstance(value, str) or not 1 <= len(value) <= 4096 or value != value.strip()
            or any(unicodedata.category(c) in {'Cc', 'Cf', 'Cs'} for c in value)
            or '\\' in value):
        return None
    try:
        url = urlsplit(value)
        host = (url.hostname or '').lower()
        port = url.port
    except ValueError:
        return None
    if (url.scheme.lower() not in {'http', 'https'} or url.username is not None or url.password is not None
            or not re.fullmatch(r'[a-z0-9](?:[a-z0-9.-]{0,251}[a-z0-9])?', host)
            or '.' not in host or any(not x or x.startswith('-') or x.endswith('-') for x in host.split('.'))
            or port not in {None, 80 if url.scheme.lower() == 'http' else 443}):
        return None
    normalized = urlunsplit((url.scheme.lower(), host, url.path or '/', url.query, ''))
    product = P.canonical_product(normalized)
    if product is not None:
        return 'https://' + product  # Same exact product with tracking parameters is one identity.
    # Other links identify result items only; query semantics are not product proof.
    return normalized


def _price(value):
    # Producer numeric zero and missing values both become ''; do not revive either.
    if isinstance(value, str) and re.fullmatch(r'[0-9]{1,13}', value):
        number = int(value)
        return number if 1 <= number <= 10**12 else None
    return None


def _int(value, low=0, high=1000):
    return type(value) is int and low <= value <= high


def _authorizer(action, table, column, database, trigger):
    if action == sqlite3.SQLITE_SELECT:
        return sqlite3.SQLITE_OK
    if (action == sqlite3.SQLITE_READ and database == 'main' and table in _READ_COLUMNS
            and column in _READ_COLUMNS[table]):
        return sqlite3.SQLITE_OK
    if action == sqlite3.SQLITE_FUNCTION and column in {'coalesce', 'length'}:
        return sqlite3.SQLITE_OK
    return sqlite3.SQLITE_DENY


def _rows(conn, table, columns, budget, limits, where='', params=()):
    """Measure text before returning it; identifiers are internal constants only."""
    expressions = []
    for name, cap in columns:
        expressions.extend((f'length(CAST({name} AS BLOB))',
            f'CASE WHEN length(CAST({name} AS BLOB))<={cap} THEN {name} END'))
    query = f'SELECT {",".join(expressions)} FROM {table} {where} LIMIT ?'
    for row in conn.execute(query, (*params, limits.max_rows + 1)):
        sizes, values = row[::2], row[1::2]
        budget.tick(rows=1, size=sum(size or 0 for size in sizes))
        if any(size is not None and size > cap for size, (_, cap) in zip(sizes, columns)):
            raise ExportInvalid('SOURCE_LIMIT')
        yield values


def _json(value):
    if not isinstance(value, str):
        return None
    try:
        return json.loads(value, parse_constant=_reject_constant, object_pairs_hook=_unique_object)
    except (ValueError, TypeError, RecursionError):
        return None


def _unique_object(pairs):
    out = {}
    for key, value in pairs:
        if key in out:
            raise ValueError('duplicate JSON key')
        out[key] = value
    return out


def _reject_constant(_value):
    raise ValueError('nonstandard JSON constant')


def _uuid(value):
    try:
        return isinstance(value, str) and str(UUID(value)) == value and len(value) == 36
    except (ValueError, AttributeError):
        return False


def _page(evidence, index, keyword):
    if (not isinstance(evidence, dict) or type(evidence.get('page')) is not int
            or evidence['page'] != index or evidence.get('keyword') != keyword
            or evidence.get('verified') is not True or not isinstance(evidence.get('source'), str)
            or evidence['source'] not in _SOURCES):
        return False
    href = evidence.get('href')
    if not isinstance(href, str) or len(href) > 300 or result_identity(href) is None:
        return False
    url = urlsplit(href)
    if (url.scheme != 'https' or url.hostname != 'search.shopping.naver.com'
            or not (url.path in {'/search/all', '/api/search/all'}
                or re.fullmatch(r'/_next/data/[^/]+/search/all\.json', url.path))):
        return False
    query = parse_qsl(url.query, keep_blank_values=True)
    keys = [key for key, _ in query]
    if len(keys) != len(set(keys)):
        return False
    params = dict(query)
    return (params.get('query') == keyword and params.get('sort', 'rel') == 'rel'
            and params.get('productSet', 'total') == 'total')


def _cohort(header, ledger, serp, product, now):
    oid, keyword, day, status, kind, reason, received_text = header
    digest, products_text, meta_text = ledger
    total, serp_products_text, serp_meta_text = serp
    products, meta = _json(products_text), _json(meta_text)
    serp_products, serp_meta = _json(serp_products_text), _json(serp_meta_text)
    if (status != 'complete' or kind != 'full' or reason != 'COMPLETE' or not _uuid(oid)
            or not isinstance(digest, str) or _HEX.fullmatch(digest) is None
            or not isinstance(products, list) or not 1 <= len(products) <= 1000
            or not isinstance(meta, dict) or products != serp_products or meta != serp_meta
            or not _int(total, 0, 10**12)):
        return None
    try:
        body = _canonical({'keyword': keyword, 'total': total, 'products': products, 'meta': meta})
        if hashlib.sha256(body.encode('utf-8')).hexdigest() != digest:
            return None
    except (ValueError, TypeError, RecursionError, UnicodeError):
        return None
    obs = meta.get('observation')
    if (not isinstance(obs, dict) or type(obs.get('schemaVersion')) is not int
            or obs['schemaVersion'] != 1 or obs.get('observationId') != oid
            or obs.get('keyword') != keyword or obs.get('status') != 'complete'):
        return None
    start, finish = P._moment(obs.get('startedAt')), P._moment(obs.get('finishedAt'))
    received = P._moment(received_text, legacy=True)
    if (start is None or finish is None or received is None or finish < start
            or finish - start > timedelta(hours=24) or finish > now + _FUTURE or received > now + _FUTURE
            or finish < now - _AGE or received < now - _AGE
            or received < finish - _FUTURE or received > finish + timedelta(hours=24)):
        return None
    if any(not _int(obs.get(key)) for key in ('requestedDepth', 'pagesRead', 'organicCount', 'coveredThroughRank')):
        return None
    n, pages = len(products), obs['pagesRead']
    if (not 1 <= pages <= 30 or not 1 <= obs['requestedDepth'] <= 1000
            or n > obs['requestedDepth'] or obs['organicCount'] != n or obs['coveredThroughRank'] != n):
        return None
    evidence, targets = obs.get('pageEvidence'), obs.get('targetIds')
    if (not isinstance(evidence, list) or len(evidence) != pages
            or any(not _page(item, i, keyword) for i, item in enumerate(evidence, 1))
            or not isinstance(targets, list) or len(targets) > 1000
            or any(not isinstance(item, (str, int)) or isinstance(item, bool) for item in targets)
            or len(set(map(str, targets))) != len(targets)):
        return None
    if (meta.get('sort') not in (None, 'rel') or meta.get('productSet') not in (None, 'total')
            or not _int(meta.get('pageSize'), 1, 1000)):
        return None
    for key in ('rawCount', 'adSkipped', 'dupSkipped', 'adHintMissed'):
        if not _int(meta.get(key), 0, 100000):
            return None
    if meta['rawCount'] < n + meta['adSkipped'] + meta['dupSkipped']:
        return None
    samples, identities, previous_page = [], set(), 0
    for index, row in enumerate(products, 1):
        if (not isinstance(row, dict) or type(row.get('rank')) is not int or row['rank'] != index
                or not _int(row.get('sourcePage'), 1, pages) or row['sourcePage'] < previous_page):
            return None
        identity = result_identity(row.get('link'))
        if identity is None or identity in identities:
            return None
        identities.add(identity)
        previous_page = row['sourcePage']
        samples.append({'key': hashlib.sha256(identity.encode('utf-8')).hexdigest(), 'price': _price(row.get('price'))})
    # Empty pages cannot be certified by this producer; every page has a retained sample.
    if set(row['sourcePage'] for row in products) != set(range(1, pages + 1)):
        return None
    return {'product_key': product, 'keyword': keyword, 'recorded_at': received.isoformat(),
        'started_at': start.isoformat(), 'observed_at': finish.isoformat(), 'observation_id': oid,
        'payload_hash': digest, 'surface': 'naver_shopping_search', 'sort': meta.get('sort'),
        'device': None, 'region': None, 'filters': None, 'samples': samples}


def collect(conn, now=None, limits=None):
    """Read one transaction only. No migrations, app imports, PRAGMA repairs or writes."""
    limits = limits or Limits()
    at = now or datetime.now(timezone.utc)
    if not isinstance(at, datetime) or at.utcoffset() is None or conn.in_transaction:
        raise ExportInvalid('SOURCE_STATE')
    at = at.astimezone(timezone.utc)
    budget = P._Budget(limits)
    conn.execute('PRAGMA query_only=ON')
    conn.execute('PRAGMA busy_timeout=1000')
    conn.execute('BEGIN')
    conn.set_authorizer(_authorizer)
    conn.set_progress_handler(budget.progress, 1000)
    try:
        clients, stores = {}, {}
        for index, (cid, url, keywords) in enumerate(_rows(conn, 'clients', [('id', 30), ('naver_store_url', 8192),
                ('main_keywords', 8192)], budget, limits,
                "WHERE role='advertiser' AND COALESCE(vertical,'store')='store'")):
            if index >= limits.max_clients:
                raise ExportInvalid('SOURCE_LIMIT')
            store = P.canonical_store(url)
            if store is None:
                continue
            current = keywords if isinstance(keywords, str) else ''
            clients[cid] = (store, P.canonical_product(url),
                set(k.strip() for k in current.split(',') if P._text(k) is not None))
            stores.setdefault(store, []).append(cid)
        mapped, contradictory, muted = {}, set(), {}
        for cid, keyword, url in _rows(conn, 'client_keyword_product', [('client_id', 30),
                ('keyword', 8192), ('product_url', 8192)], budget, limits):
            if cid not in clients or not isinstance(keyword, str):
                continue
            key = (cid, keyword.strip())
            product = P.canonical_product(url)
            if P.canonical_store(url) != clients[cid][0]:
                product = None
            if key in mapped and mapped[key] != product:
                contradictory.add(cid)
            mapped[key] = product  # Presence, even invalid, forbids base fallback.
        for cid, keyword in _rows(conn, 'client_keyword_mute', [('client_id', 30), ('keyword', 8192)], budget, limits):
            if cid in clients and isinstance(keyword, str):
                muted.setdefault(cid, set()).add(keyword.strip())
        assigned, wanted = {}, set()
        for cid, (store, base, keywords) in clients.items():
            if len(stores[store]) != 1 or cid in contradictory:
                continue
            for keyword in sorted(keywords - muted.get(cid, set())):
                product = mapped.get((cid, keyword)) if (cid, keyword) in mapped else base
                if product is not None:
                    assigned.setdefault(cid, []).append((keyword, product))
                    wanted.add(keyword)
        latest, unorderable = {}, set()
        columns = [('observation_id', 100), ('keyword', 8192), ('collected_date', 100),
            ('status', 100), ('kind', 100), ('reason', 300), ('received_at', 200)]
        for header in _rows(conn, 'collector_observations', columns, budget, limits):
            oid, keyword, day, status, kind, reason, received_text = header
            if keyword not in wanted:
                continue
            received = P._moment(received_text, legacy=True)
            if received is None or not isinstance(oid, str):
                unorderable.add(keyword)
                continue
            order = (received, oid)
            if keyword not in latest or order > latest[keyword][0]:
                latest[keyword] = (order, header)
        verified = {}
        for keyword, (_, header) in latest.items():
            if keyword in unorderable:
                continue
            oid, _, day, status, kind, reason, _ = header
            if status != 'complete' or kind != 'full' or reason != 'COMPLETE':
                continue  # Never fall back to an older complete same-keyword row.
            ledger = list(_rows(conn, 'collector_observations', [('payload_hash', 100),
                ('products_json', limits.max_json_cell_bytes), ('meta_json', limits.max_json_cell_bytes)],
                budget, limits, 'WHERE observation_id=?', (oid,)))
            serp = list(_rows(conn, 'collected_serp', [('total', 100),
                ('products_json', limits.max_json_cell_bytes), ('meta_json', limits.max_json_cell_bytes)],
                budget, limits, 'WHERE keyword=? AND collected_date=?', (keyword, day)))
            if len(ledger) == len(serp) == 1:
                verified[keyword] = (header, ledger[0], serp[0])
        result = []
        for store, ids in sorted(stores.items()):
            budget.tick()
            if len(ids) != 1 or ids[0] in contradictory:
                result.append({'store_key': store, 'status': 'ambiguous', 'cohorts': []})
                continue
            cohorts = []
            for keyword, product in assigned.get(ids[0], []):
                if keyword in verified:
                    cohort = _cohort(*verified[keyword], product, at)
                    if cohort is not None:
                        cohorts.append(cohort)
            cohorts.sort(key=lambda c: (c['recorded_at'], c['observed_at'], c['keyword'], c['observation_id']), reverse=True)
            result.append({'store_key': store, 'status': 'ok' if cohorts else 'no_observations', 'cohorts': cohorts[:1]})
        bundle = {'schema_version': 1, 'exported_at': at.isoformat(), 'complete': True, 'stores': result}
        P.encode(bundle, limits)
        budget.tick()
        return bundle
    except sqlite3.DatabaseError as error:
        budget.tick()
        raise ExportInvalid('SOURCE_READ', source_issue=P._sqlite_issue(error)) from None


def export_database(database, output, now=None, limits=None):
    limits = limits or Limits()
    source = Path(database).absolute()
    if not source.is_file() or not stat.S_ISREG(source.stat().st_mode):
        raise ExportInvalid('SOURCE_PATH')
    try:
        conn = sqlite3.connect(source.as_uri() + '?mode=ro', uri=True, timeout=1, isolation_level=None)
        try:
            bundle = collect(conn, now=now, limits=limits)
            content = P.encode(bundle, limits)
        finally:
            conn.close()
        durable = P.write_atomic(output, content, source=source)
    except sqlite3.DatabaseError as error:
        raise ExportInvalid('SOURCE_READ', source_issue=P._sqlite_issue(error)) from None
    result = {'status': 'ok', 'stores': len(bundle['stores']),
        'cohorts': sum(len(store['cohorts']) for store in bundle['stores']), 'bytes': len(content)}
    if not durable:
        result['warning'] = 'EXPORT_DURABILITY_UNCONFIRMED'
    return result


def _limit_issue(error):
    """Classify the existing rejection; never read source values or a new clock."""
    if type(error) is not ExportInvalid or error.code != 'SOURCE_LIMIT':
        return 'unknown'
    tb = error.__traceback__
    for _ in range(32):
        if tb is None:
            return 'unknown'
        if tb.tb_next is None:
            break
        tb = tb.tb_next
    else:
        return 'unknown'
    frame = tb.tb_frame
    if frame.f_code is _rows.__code__ and frame.f_globals is globals():
        return 'cell'
    if frame.f_code is collect.__code__ and frame.f_globals is globals():
        return 'clients'
    if frame.f_code is P._Budget.tick.__code__ and frame.f_globals is P.__dict__:
        budget = frame.f_locals.get('self')
        if type(budget) is not P._Budget or type(budget.limits) is not Limits:
            return 'unknown'
        values = (budget.bytes, budget.rows, budget.limits.max_input_bytes, budget.limits.max_rows)
        if any(type(value) is not int or value < 0 for value in values):
            return 'unknown'
        if budget.bytes > budget.limits.max_input_bytes:
            return 'input_bytes'
        if budget.rows > budget.limits.max_rows:
            return 'rows'
        # This exact original tick raised after both preceding OR tests were false.
        return 'time'
    return 'unknown'


def _failure_result(error):
    result = P._failure_result(error)
    if result.get('code') == 'SOURCE_LIMIT':
        result['limit_issue'] = _limit_issue(error)
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description='Export bounded saved search samples; no collection or source writes.')
    parser.add_argument('--database', required=True)
    parser.add_argument('--output', required=True)
    args = parser.parse_args(argv)
    try:
        result = export_database(args.database, args.output)
    except (ExportInvalid, OSError, OverflowError, ValueError, TypeError, RecursionError, UnicodeError) as error:
        print(json.dumps(_failure_result(error)))
        return 1
    print(json.dumps(result))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
