"""Bounded, read-only export of saved product observations; no app imports or network.

The JSON is a dedicated source artifact, not a database copy.  recorded_at is the
analysis save time (legacy naive times are KST); original capture time is unknown.
Run this standalone module only from the separately reviewed exporter service.
"""
import argparse
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import json
import math
import os
from pathlib import Path
import re
import sqlite3
import stat
import tempfile
import time
import unicodedata
from urllib.parse import urlparse


KST = timezone(timedelta(hours=9))
HOSTS = frozenset({'smartstore.naver.com', 'brand.naver.com'})
SOURCES = frozenset({'html_meta', 'html_json_ld', 'html_next_data',
                     'review_sample', 'stored_product_info'})
FEATURES = {'delivery_info': 'has_delivery_info', 'return_info': 'has_return_info',
            'gift_info': 'has_gift_info', 'certification': 'has_certification',
            'review_section': 'has_review_section', 'spec_table': 'has_spec_table'}
_SLUG = r'[A-Za-z0-9_-]{1,100}'
_PRODUCT = r'[1-9][0-9]{0,23}'
_PRIVATE = re.compile(r'https?://|www\.|[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}|'
                      r'(?<!\d)\+?\d(?:[ .()-]?\d){8,14}(?!\d)|'
                      r'\b[A-Za-z0-9-]+\.(?:com|net|org|co\.kr|kr|io)\b', re.I)
_READ_COLUMNS = {
    'clients': frozenset({'id', 'naver_store_url', 'role', 'vertical'}),
    'client_analyses': frozenset({'id', 'ROWID', 'client_id', 'product_url',
                                'updated_at', 'analysis_json', 'advertiser_json'}),
}


class ExportInvalid(ValueError):
    """Only fixed, non-sensitive failure codes may reach CLI output."""
    def __init__(self, code):
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class Limits:
    max_clients: int = 10000
    max_rows: int = 100000
    max_json_cell_bytes: int = 2 * 1024 * 1024
    max_input_bytes: int = 32 * 1024 * 1024
    max_output_bytes: int = 5 * 1024 * 1024
    max_seconds: float = 30


class _Budget:
    def __init__(self, limits):
        self.limits, self.started, self.bytes, self.rows = limits, time.monotonic(), 0, 0

    def tick(self, size=0, rows=0):
        self.bytes += size
        self.rows += rows
        if (self.bytes > self.limits.max_input_bytes or self.rows > self.limits.max_rows
                or time.monotonic() - self.started > self.limits.max_seconds):
            raise ExportInvalid('SOURCE_LIMIT')

    def progress(self):
        try:
            self.tick()
            return 0
        except ExportInvalid:
            return 1


def _identity(value):
    if (not isinstance(value, str) or not 1 <= len(value) <= 2048 or value != value.strip()
            or any(ord(c) < 32 or ord(c) == 127 for c in value)):
        return None
    try:
        parsed = urlparse(value if '://' in value else 'https://' + value)
        host = (parsed.hostname or '').lower()
    except ValueError:
        return None
    if (parsed.scheme not in {'http', 'https'} or parsed.netloc.lower() != host
            or parsed.params or host.removeprefix('m.') not in HOSTS):
        return None
    match = re.fullmatch(r'/(' + _SLUG + r')(?:/products/(' + _PRODUCT + r'))?/?', parsed.path)
    return (host.removeprefix('m.'), match[1], match[2]) if match else None


def canonical_store(value):
    identity = _identity(value)
    return '/'.join(identity[:2]) if identity else None


def canonical_product(value):
    identity = _identity(value)
    return '/'.join(identity[:2]) + '/products/' + identity[2] if identity and identity[2] else None


def _moment(value, legacy=False):
    if (not isinstance(value, str) or len(value) > 50
            or re.fullmatch(r'\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|[+-]\d{2}:\d{2})?', value) is None):
        return None
    try:
        at = datetime.fromisoformat(value)
        # Existing source writers use datetime.now()/SQLite localtime under TZ=Asia/Seoul.
        if at.utcoffset() is None:
            if not legacy:
                return None
            at = at.replace(tzinfo=KST)
        return at.astimezone(timezone.utc)
    except (ValueError, OverflowError):
        return None


def _text(value):
    if not isinstance(value, str):
        return None
    value = value.strip()
    if (not value or len(value) > 100 or any(c in '<>{}' for c in value)
            or _PRIVATE.search(value) or any(unicodedata.category(c) in {'Cc', 'Cf', 'Cs'} for c in value)):
        return None
    return value


def _number(value, high, integer=False):
    return (type(value) in ((int,) if integer else (int, float))
            and 0 <= value <= high and math.isfinite(value))


def _unknown():
    return {'value': None, 'status': 'unavailable', 'sources': []}


def _metric(quality, name):
    item = quality.get(name) if isinstance(quality, dict) else None
    if (not isinstance(item, dict) or not isinstance(item.get('status'), str)
            or item['status'] not in {'measured', 'cross_verified'}):
        return _unknown()
    sources, value = item.get('sources'), item.get('value')
    high = {'price': 10**12, 'review_count': 10**9, 'rating': 5}[name]
    if (not _number(value, high, name == 'review_count') or not isinstance(sources, list)
            or not 1 <= len(sources) <= len(SOURCES) or any(not isinstance(s, str) or s not in SOURCES for s in sources)):
        return _unknown()
    sources = sorted(set(sources))
    if (item['status'] == 'cross_verified' and len(sources) < 2
            or 'review_sample' in sources and name != 'rating'):
        return _unknown()  # Inconsistent quality tags are unknown, never upgraded or inferred.
    return {'value': value, 'status': item['status'], 'sources': sources}


def _unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ExportInvalid('SOURCE_JSON')
        result[key] = value
    return result


def _json(value, budget):
    if value is None or value == '':
        return {}
    if not isinstance(value, str):
        raise ExportInvalid('SOURCE_JSON')
    try:
        size = len(value.encode('utf-8'))
    except UnicodeError:
        raise ExportInvalid('SOURCE_JSON') from None
    budget.tick(size=size)
    if size > budget.limits.max_json_cell_bytes:
        raise ExportInvalid('SOURCE_LIMIT')
    try:
        result = json.loads(value, object_pairs_hook=_unique,
                            parse_constant=lambda _: (_ for _ in ()).throw(ExportInvalid('SOURCE_JSON')))
    except (ValueError, RecursionError, UnicodeError):
        raise ExportInvalid('SOURCE_JSON') from None
    if not isinstance(result, dict):
        raise ExportInvalid('SOURCE_JSON')
    return result


def _object(value):
    return value if isinstance(value, dict) else {}


def _product(product_key, recorded_at, client_product, analysis, advertiser):
    # Advertiser report contains the exact requested product URL. Unscoped data is not reused.
    scoped = canonical_product(advertiser.get('product_url')) == product_key
    info = _object(advertiser.get('product_info')) if scoped else {}
    quality = _object(advertiser.get('data_quality')) if scoped else {}
    metrics = {key: _metric(quality, key) for key in ('price', 'review_count', 'rating')}
    features = dict.fromkeys(FEATURES)
    category = next((_text(info.get(key)) for key in ('category', 'category2', 'category1') if _text(info.get(key))), None)
    # htmlDetail is derived from client-level saved HTML, so it is usable only for that exact product.
    if client_product == product_key:
        detail = _object(analysis.get('htmlDetail'))
        if detail.get('success') is not False:
            review = _object(detail.get('reviewData'))
            html_quality = _object(review.get('data_quality'))
            for key in metrics:
                observed = _metric(html_quality, key)
                if observed['status'] != 'unavailable':
                    metrics[key] = observed
            raw_features = _object(detail.get('metrics'))
            features = {key: raw_features.get(raw) if type(raw_features.get(raw)) is bool else None
                        for key, raw in FEATURES.items()}
            category = category or _text(review.get('category')) or _text(review.get('category1'))
    return {'product_key': product_key, 'recorded_at': recorded_at.isoformat(), 'observed_at': None,
            'name': _text(info.get('product_name')), 'category': category,
            'metrics': metrics, 'features': features}


def _authorizer(action, table, column, database, trigger):
    if action == sqlite3.SQLITE_SELECT:
        return sqlite3.SQLITE_OK
    if action == sqlite3.SQLITE_READ and database == 'main' and table in _READ_COLUMNS and column in _READ_COLUMNS[table]:
        return sqlite3.SQLITE_OK
    if action == sqlite3.SQLITE_FUNCTION and column in {'coalesce', 'length'}:
        return sqlite3.SQLITE_OK
    return sqlite3.SQLITE_DENY


def collect(conn, now=None, limits=None):
    """Read one consistent saved snapshot. Never repairs schema or mutates source.

    The caller must provide an idle connection. The read transaction stays open
    until close; no COMMIT/ROLLBACK SQL or app database helpers are called.
    """
    limits = limits or Limits()
    at = now or datetime.now(timezone.utc)
    if not isinstance(at, datetime) or at.utcoffset() is None or conn.in_transaction:
        raise ExportInvalid('SOURCE_STATE')
    budget = _Budget(limits)
    conn.execute('PRAGMA query_only=ON')
    conn.execute('PRAGMA busy_timeout=1000')
    conn.execute('BEGIN')
    conn.set_authorizer(_authorizer)
    conn.set_progress_handler(budget.progress, 1000)
    try:
        clients, stores = {}, {}
        # Size metadata inside SQLite before transferring any possibly huge TEXT to Python.
        # Oversized identities/dates remain invalid; their full byte size still counts.
        rows = conn.execute("SELECT id,length(CAST(naver_store_url AS BLOB)), "
                            "CASE WHEN length(CAST(naver_store_url AS BLOB))<=8192 THEN naver_store_url END "
                            "FROM clients WHERE role='advertiser' "
                            "AND COALESCE(vertical,'store')='store' LIMIT ?", (limits.max_clients + 1,))
        for index, (client_id, url_size, url) in enumerate(rows):
            budget.tick(rows=1, size=url_size or 0)
            if index >= limits.max_clients:
                raise ExportInvalid('SOURCE_LIMIT')
            store = canonical_store(url)
            if store is None:
                continue
            clients[client_id] = (store, canonical_product(url))
            stores.setdefault(store, []).append(client_id)
        latest, invalid_dates = {}, set()
        rows = conn.execute("SELECT a.rowid,a.client_id,length(CAST(a.product_url AS BLOB)), "
                            "length(CAST(a.updated_at AS BLOB)), "
                            "CASE WHEN length(CAST(a.product_url AS BLOB))<=8192 THEN a.product_url END, "
                            "CASE WHEN length(CAST(a.updated_at AS BLOB))<=200 THEN a.updated_at END "
                            "FROM client_analyses a "
                            "JOIN clients c ON c.id=a.client_id WHERE c.role='advertiser' "
                            "AND COALESCE(c.vertical,'store')='store' LIMIT ?", (limits.max_rows + 1,))
        for rowid, client_id, url_size, date_size, url, saved_at in rows:
            budget.tick(rows=1, size=(url_size or 0) + (date_size or 0))
            client = clients.get(client_id)
            if not client or len(stores[client[0]]) != 1:
                continue
            product = canonical_product(url)
            if product is None or canonical_store(url) != client[0]:
                continue
            key, recorded = (client_id, product), _moment(saved_at, legacy=True)
            if recorded is None or recorded > at.astimezone(timezone.utc) + timedelta(minutes=5):
                invalid_dates.add(key)  # Never promote an older dated row behind an undated record.
                continue
            candidate = (recorded, rowid)
            if key not in latest or candidate > latest[key]:
                latest[key] = candidate
        by_client = {}
        for (client_id, product), (stamp, rowid) in latest.items():
            budget.tick()
            if (client_id, product) not in invalid_dates:
                by_client.setdefault(client_id, []).append((product, stamp, rowid))
        result = []
        for store, ids in sorted(stores.items()):
            budget.tick()
            if len(ids) != 1:
                result.append({'store_key': store, 'status': 'ambiguous', 'products': []})
                continue
            client_id, = ids
            candidates = by_client.get(client_id, [])
            candidates.sort(key=lambda row: (row[1], row[2]), reverse=True)
            products = []
            for product, stamp, rowid in candidates[:3]:
                budget.tick()
                sizes = conn.execute('SELECT length(CAST(analysis_json AS BLOB)),length(CAST(advertiser_json AS BLOB)) '
                                     'FROM client_analyses WHERE rowid=? AND client_id=?', (rowid, client_id)).fetchone()
                if sizes is None or any(size is not None and size > limits.max_json_cell_bytes for size in sizes):
                    raise ExportInvalid('SOURCE_LIMIT')
                if budget.bytes + sum(size or 0 for size in sizes) > limits.max_input_bytes:
                    raise ExportInvalid('SOURCE_LIMIT')
                row = conn.execute('SELECT analysis_json,advertiser_json FROM client_analyses '
                                   'WHERE rowid=? AND client_id=?', (rowid, client_id)).fetchone()
                if row is None:
                    raise ExportInvalid('SOURCE_STATE')
                products.append(_product(product, stamp, clients[client_id][1],
                                         _json(row[0], budget), _json(row[1], budget)))
            result.append({'store_key': store, 'status': 'ok' if products else 'no_products', 'products': products})
        bundle = {'schema_version': 1, 'exported_at': at.astimezone(timezone.utc).isoformat(),
                  'complete': True, 'stores': result}
        encode(bundle, limits)
        budget.tick()
        return bundle
    except sqlite3.DatabaseError:
        try:
            budget.tick()
        except ExportInvalid:
            raise
        raise ExportInvalid('SOURCE_READ') from None


def encode(bundle, limits=None):
    limits = limits or Limits()
    try:
        content = (json.dumps(bundle, ensure_ascii=False, allow_nan=False, separators=(',', ':')) + '\n').encode('utf-8')
    except (ValueError, TypeError, UnicodeError):
        raise ExportInvalid('EXPORT_INVALID') from None
    if len(content) > limits.max_output_bytes:
        raise ExportInvalid('EXPORT_LIMIT')
    return content


def write_atomic(output, content, source=None):
    """Publish a complete bundle; return whether post-replace durability was confirmed.

    Replace is the commit point. Before it, errors preserve the previous file.
    After it, a directory fsync failure is a warning about crash durability, not
    a claim that the already-published complete bundle was rolled back.
    """
    output = Path(output).absolute()
    parent = output.parent
    if (output.suffix != '.json' or not parent.is_dir() or parent.is_symlink() or output.is_symlink()
            or output.exists() and not output.is_file()
            or source is not None and (output.resolve() == Path(source).resolve()
                or output.exists() and os.path.samefile(output, source))):
        raise ExportInvalid('OUTPUT_PATH')
    temporary, directory, published, durable = None, None, False, True
    try:
        fd, temporary = tempfile.mkstemp(prefix='.naver-product-', suffix='.tmp', dir=parent)
        with os.fdopen(fd, 'wb') as stream:
            os.fchmod(stream.fileno(), 0o640)
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        directory = os.open(parent, os.O_RDONLY | getattr(os, 'O_DIRECTORY', 0))
        os.replace(temporary, output)
        published = True
        temporary = None
        os.fsync(directory)
    except OSError:
        if not published:
            raise ExportInvalid('OUTPUT_WRITE') from None
        durable = False
    finally:
        if directory is not None:
            try:
                os.close(directory)
            except OSError:
                durable = False
        if temporary is not None:
            try:
                os.unlink(temporary)
            except FileNotFoundError:
                pass
    return durable


def export_database(database, output, now=None, limits=None):
    limits = limits or Limits()
    source = Path(database).absolute()
    if not source.is_file() or not stat.S_ISREG(source.stat().st_mode):
        raise ExportInvalid('SOURCE_PATH')
    try:
        conn = sqlite3.connect(source.as_uri() + '?mode=ro', uri=True, timeout=1, isolation_level=None)
        try:
            bundle = collect(conn, now=now, limits=limits)
            content = encode(bundle, limits)
        finally:
            conn.close()
        durable = write_atomic(output, content, source=source)
    except sqlite3.DatabaseError:
        raise ExportInvalid('SOURCE_READ') from None
    result = {'status': 'ok', 'stores': len(bundle['stores']),
              'products': sum(len(store['products']) for store in bundle['stores']), 'bytes': len(content)}
    if not durable:
        result['warning'] = 'EXPORT_DURABILITY_UNCONFIRMED'
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description='Export bounded saved product observations; source database is read-only.')
    parser.add_argument('--database', required=True)
    parser.add_argument('--output', required=True)
    args = parser.parse_args(argv)
    try:
        result = export_database(args.database, args.output)
    except (ExportInvalid, OSError, OverflowError) as error:
        print(json.dumps({'status': 'failed', 'code': error.code if isinstance(error, ExportInvalid) else 'EXPORT_FAILED'}))
        return 1
    print(json.dumps(result))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
