"""Conservative, allowlisted summary of an in-memory ``nginx -T`` dump.

No file/command/network access. Untrusted configuration values never become
error messages or output keys. This is an inventory, not nginx's routing engine.
"""
import fnmatch
import posixpath
import re

HOSTS = frozenset(h + '.metainc.co.kr' for h in ('ad', 'dashboard', 'logic', 'studio'))
LOCATIONS = frozenset(('/naver', '/naver/', '/api/naver-auto', '/studio', '/studio/', '/autobid', '/autobid/', '/'))
UPSTREAMS = frozenset(('naver_relay', 'naver_engine', 'ad_dashboard', 'content_studio', 'logic_analysis', 'autobid'))
SOCKET = '/run/metainc/naver-relay/relay.sock'
STATIC = frozenset(('/root/logic-analysis-deploy/frontend/dist', '/root/content-studio-deploy/frontend/dist',
                    '/root/ad-dashboard-deploy/frontend/dist', '/root/naver-ad-dashboard/frontend/dist'))
BASENAMES = HOSTS | frozenset(('nginx.conf', 'mime.types', 'proxy_params', 'fastcgi_params', 'default',
                             'metainc', 'logic-analysis', 'ad-dashboard', 'content-studio', 'naver',
                             'naver-relay', 'naver-relay.conf', 'ssl-params.conf', 'metainc.conf'))
DIRECTORIES = frozenset(('/etc/nginx', '/etc/nginx/conf.d', '/etc/nginx/sites-enabled',
                         '/etc/nginx/sites-available', '/etc/nginx/snippets'))
MARKER = re.compile(r'^# configuration file (/[^\x00-\x1f]*):\s*$')
CERT = re.compile(r'/etc/letsencrypt/live/((?:ad|dashboard|logic|studio)\.metainc\.co\.kr)(?:-[0-9]{4})?/(?:fullchain|cert|privkey)\.pem\Z')


class _Invalid(Exception):
    pass


def _sections(text):
    files, path, lines, quote, escape = {}, None, [], None, False
    for line in text.splitlines(keepends=True):
        marker = MARKER.fullmatch(line.rstrip('\r\n')) if quote is None else None
        if marker:
            if path is not None:
                if path in files:
                    raise _Invalid('duplicate_file_section')
                files[path] = ''.join(lines)
            path, lines = marker.group(1), []
            continue
        if path is None:
            if line.strip() and not line.lstrip().startswith('#'):
                raise _Invalid('unexpected_preamble')
            continue
        lines.append(line)
        for c in line:
            if escape:
                escape = False
            elif c == '\\':
                escape = True
            elif quote:
                if c == quote:
                    quote = None
            elif c in ('"', "'"):
                quote = c
            elif c == '#':
                break
        if len(files) > 512:
            raise _Invalid('file_limit')
    if path is None:
        raise _Invalid('dump_sections_missing')
    if path in files:
        raise _Invalid('duplicate_file_section')
    files[path] = ''.join(lines)
    if len(files) > 512:
        raise _Invalid('file_limit')
    return files


def _tokens(text):
    result, buf, line, start, quote, after_quote = [], [], 1, 1, None, False
    i = 0
    def emit():
        nonlocal buf, after_quote
        if buf or after_quote:
            result.append((''.join(buf), start, True))
        buf, after_quote = [], False
    while i < len(text):
        c = text[i]
        if c == '\\':
            if after_quote or i + 1 == len(text):
                raise _Invalid('syntax_error')
            if not buf:
                start = line
            i += 1
            c = text[i]
            # nginx preserves the backslash for escapes outside this small set.
            buf.append({'n': '\n', 'r': '\r', 't': '\t', '\\': '\\', '"': '"', "'": "'"}.get(c, '\\' + c))
        elif quote:
            if c == quote:
                quote, after_quote = None, True
            else:
                buf.append(c)
        elif c in ('"', "'"):
            if buf or after_quote:
                raise _Invalid('syntax_error')
            start, quote = line, c
        elif c.isspace():
            emit()
        elif c == '#':
            emit()
            end = text.find('\n', i)
            i = len(text) if end < 0 else end - 1
        elif c in '{};':
            if c == '{' and buf and buf[-1] == '$':
                end = text.find('}', i + 1)
                if end < 0 or not re.fullmatch(r'[A-Za-z0-9_]+', text[i + 1:end]):
                    raise _Invalid('syntax_error')
                buf.extend(text[i:end + 1])
                i = end
            else:
                emit()
                result.append((c, line, False))
        else:
            if after_quote:
                raise _Invalid('syntax_error')
            if not buf:
                start = line
            buf.append(c)
        if c == '\n':
            line += 1
        i += 1
        if len(result) > 50000:
            raise _Invalid('token_limit')
    if quote:
        raise _Invalid('syntax_error')
    emit()
    return result


def _parse(text, source):
    tokens, i = _tokens(text), 0
    def block(depth, nested):
        nonlocal i
        if depth > 64:
            raise _Invalid('nesting_limit')
        nodes, args, start = [], [], 0
        while i < len(tokens):
            value, line, word = tokens[i]
            i += 1
            if word:
                if not args:
                    start = line
                args.append(value)
            elif value == '}':
                if args or not nested:
                    raise _Invalid('syntax_error')
                return nodes
            else:
                if not args:
                    raise _Invalid('syntax_error')
                children = block(depth + 1, True) if value == '{' else None
                nodes.append((args, children, source, start))
                args = []
        if args or nested:
            raise _Invalid('syntax_error')
        return nodes
    return block(0, False)


def _endpoint(value):
    match = re.fullmatch(r'(127\.0\.0\.1|localhost|\[::1\]):([0-9]{1,5})', value)
    if match and 1 <= int(match[2]) <= 65535:
        return {'host': match[1], 'port': int(match[2])}
    if value == 'unix:' + SOCKET:
        return {'socket': SOCKET}
    return None


def _policies(nodes):
    checks = {
        'real_ip_overwrite': lambda a: a == ['proxy_set_header', 'X-Real-IP', '$remote_addr'],
        'access_log_suppressed': lambda a: a == ['access_log', 'off'],
        'error_log_suppressed': lambda a: len(a) >= 2 and a[:2] == ['error_log', '/dev/null'],
        'cache_disabled': lambda a: a[:2] in (['proxy_no_cache', '1'], ['proxy_cache_bypass', '1']) or
            (len(a) >= 3 and a[0:2] == ['add_header', 'Cache-Control'] and 'no-store' in a[2].split(',')),
        'referrer_suppressed': lambda a: len(a) >= 3 and a[:3] == ['add_header', 'Referrer-Policy', 'no-referrer'],
        'proxy_buffering_disabled': lambda a: a == ['proxy_buffering', 'off'],
        'proxy_request_buffering_disabled': lambda a: a == ['proxy_request_buffering', 'off'],
        'timeout_present': lambda a: len(a) == 2 and a[0] in ('proxy_read_timeout', 'proxy_send_timeout', 'proxy_connect_timeout') and bool(re.fullmatch(r'[0-9]+[smh]?', a[1])),
        'body_limit_present': lambda a: len(a) == 2 and a[0] == 'client_max_body_size' and bool(re.fullmatch(r'[0-9]+[kKmMgG]?', a[1])),
    }
    return {name: any(test(a) for a, children, _, _ in nodes if children is None) for name, test in checks.items()}


def summarize_nginx(text):
    """Return safe metadata; failures carry fixed codes, never raw values."""
    report = {'status': 'error', 'resolution_complete': False, 'errors': [], 'files': [],
              'includes': [], 'servers': [], 'redacted_server_count': 0,
              'policy_semantics': 'local_directive_presence_not_effective_inheritance',
              'routing_semantics': 'configuration_structure_only_not_request_matching'}
    errors = set()
    def issue(code):
        errors.add(code)
    try:
        if not isinstance(text, str) or len(text) > 2 * 1024 * 1024 or '\x00' in text:
            raise _Invalid('input_invalid_or_limit')
        files = _sections(text)
        ids = {path: 'file-' + str(n + 1) for n, path in enumerate(files)}
        for path, ident in ids.items():
            safe = posixpath.dirname(path) in DIRECTORIES and posixpath.basename(path) in BASENAMES
            report['files'].append({'id': ident, 'path': path if safe else None, 'redacted': not safe})
        parsed = {path: _parse(body, ids[path]) for path, body in files.items()}
        if '/etc/nginx/nginx.conf' not in parsed:
            raise _Invalid('main_section_missing')
        expanded_count, visited = 0, {'/etc/nginx/nginx.conf'}
        def expand(nodes, stack):
            nonlocal expanded_count
            if len(stack) > 32:
                issue('include_depth_limit')
                return []
            result = []
            for args, children, source, line in nodes:
                expanded_count += 1
                if expanded_count > 50000:
                    raise _Invalid('expansion_limit')
                if args[0] == 'include':
                    row = {'source': source, 'line': line, 'targets': [], 'status': 'unresolved'}
                    report['includes'].append(row)
                    if len(args) != 2 or children is not None or '$' in args[1]:
                        issue('include_unresolved')
                        continue
                    target = posixpath.normpath(posixpath.join('/etc/nginx', args[1]))
                    parts = target.split('/')
                    matches = sorted(p for p in files if len(p.split('/')) == len(parts) and
                                     all(fnmatch.fnmatchcase(v, pattern) for v, pattern in zip(p.split('/'), parts)))
                    if not matches:
                        issue('include_unresolved')
                    else:
                        row['targets'], row['status'] = [ids[p] for p in matches], 'expanded'
                    for path in matches:
                        if path in stack:
                            row['status'] = 'cycle'
                            issue('include_cycle')
                        else:
                            visited.add(path)
                            result.extend(expand(parsed[path], stack + [path]))
                else:
                    result.append((args, expand(children, stack) if children is not None else None, source, line))
            return result
        tree = expand(parsed['/etc/nginx/nginx.conf'], ['/etc/nginx/nginx.conf'])
        if set(files) != visited:
            issue('unreferenced_file_sections')
        upstreams, candidates = {}, []
        for args, children, _, _ in tree:
            if args == ['http'] and children is not None:
                if any(c is None and a[0] in ('root', 'alias', 'proxy_pass', 'rewrite', 'try_files', 'return', 'error_page')
                       for a, c, _, _ in children):
                    issue('http_inherited_routing_unverified')
                for node in children:
                    a, content, _, _ = node
                    if a[0] == 'server' and content is not None:
                        candidates.append(node)
                    elif a[0] == 'upstream' and len(a) == 2 and content is not None:
                        endpoints = [_endpoint(x[0][1]) for x in content if x[0][0] == 'server' and len(x[0]) >= 2 and x[1] is None]
                        if a[1] in upstreams:
                            upstreams[a[1]] = None
                            issue('duplicate_upstream')
                        else:
                            upstreams[a[1]] = endpoints if endpoints and all(endpoints) else None
            elif args[0] == 'server':
                issue('server_context_invalid')
        def proxy(value, unresolved):
            match = re.fullmatch(r'(https?)://(.+)', value)
            result = {'redacted': True}
            if match and '$' not in value:
                dest = match[2]
                if dest.startswith('unix:' + SOCKET + ':'):
                    result = {'scheme': match[1], 'socket': SOCKET, 'uri_present': bool(dest[len(SOCKET) + 6:])}
                else:
                    address, slash, _ = dest.partition('/')
                    endpoint = _endpoint(address)
                    if endpoint:
                        result = dict(endpoint, scheme=match[1], uri_present=bool(slash))
                    elif address in UPSTREAMS and upstreams.get(address):
                        result = {'scheme': match[1], 'upstream': address, 'endpoints': upstreams[address], 'uri_present': bool(slash)}
            if result.get('redacted'):
                unresolved.add('proxy_unresolved')
            if result.get('uri_present'):
                unresolved.add('proxy_uri_redacted')
            return result
        for _, content, source, line in candidates:
            names = [v for a, c, _, _ in content if a[0] == 'server_name' and c is None for v in a[1:]]
            known = sorted(set(names) & HOSTS)
            if not known:
                report['redacted_server_count'] += 1
                issue('redacted_server_context_unverified')
                continue
            row = {'id': 'server-' + str(len(report['servers']) + 1), 'source': source, 'line': line,
                   'server_names': known, 'other_names_present': bool(set(names) - HOSTS), 'listen': [],
                   'certificates': [], 'locations': [], 'policies': _policies(content), 'unresolved': []}
            report['servers'].append(row)
            unresolved = set()
            def metadata(nodes, target):
                for a, c, src, ln in nodes:
                    if c is not None:
                        continue
                    if a[0] == 'proxy_pass':
                        target.setdefault('proxy_pass', []).append(proxy(a[1], unresolved) if len(a) == 2 else {'redacted': True})
                        if len(a) != 2:
                            unresolved.add('proxy_unresolved')
                    elif a[0] in ('root', 'alias'):
                        safe = len(a) == 2 and a[1].rstrip('/') in STATIC
                        target.setdefault('static_paths', []).append({'directive': a[0], 'path': a[1] if safe else None, 'redacted': not safe})
                        if not safe:
                            unresolved.add('static_path_redacted')
                    elif a[0] in ('rewrite', 'try_files', 'return', 'error_page'):
                        unresolved.add('routing_directive_present')
                    elif a[0] in ('fastcgi_pass', 'uwsgi_pass', 'grpc_pass', 'scgi_pass', 'memcached_pass',
                                  'auth_request', 'proxy_redirect', 'index', 'internal', 'limit_except'):
                        unresolved.add('routing_directive_present')
                    elif a[0] not in ('listen', 'server_name', 'ssl_certificate', 'ssl_certificate_key',
                                      'proxy_set_header', 'add_header', 'access_log', 'error_log',
                                      'proxy_no_cache', 'proxy_cache_bypass', 'proxy_buffering',
                                      'proxy_request_buffering', 'proxy_read_timeout', 'proxy_send_timeout',
                                      'proxy_connect_timeout', 'client_max_body_size', 'ssl_protocols',
                                      'ssl_ciphers', 'ssl_prefer_server_ciphers', 'include'):
                        unresolved.add('directive_unresolved')
            metadata(content, row)
            for a, c, _, _ in content:
                if c is not None:
                    continue
                if a[0] == 'listen':
                    match = re.fullmatch(r'(?:(127\.0\.0\.1|0\.0\.0\.0|\[::\]|\[::1\]|\*):)?([0-9]{1,5})', a[1]) if len(a) >= 2 else None
                    safe = bool(match and 1 <= int(match[2]) <= 65535)
                    row['listen'].append({'address': (match[1] or '*') if safe else None, 'port': int(match[2]) if safe else None,
                                          'default_server': 'default_server' in a[2:], 'ssl': 'ssl' in a[2:], 'redacted': not safe})
                    if not safe or any(v not in ('ssl', 'http2', 'default_server', 'reuseport', 'quic') for v in a[2:]):
                        unresolved.add('listen_unresolved')
                elif a[0] in ('ssl_certificate', 'ssl_certificate_key'):
                    safe = len(a) == 2 and bool(CERT.fullmatch(a[1]))
                    row['certificates'].append({'directive': a[0], 'path': a[1] if safe else None, 'redacted': not safe})
                    if not safe:
                        unresolved.add('certificate_redacted')
            def locations(nodes, parent=None, context_known=True):
                for a, c, src, ln in nodes:
                    if c is None:
                        continue
                    if a[0] != 'location':
                        unresolved.add('nested_context_unresolved')
                        continue
                    modifier = a[1] if len(a) == 3 and a[1] in ('=', '^~', '~', '~*') else ''
                    path = a[-1] if len(a) == 2 or modifier else None
                    safe = path in LOCATIONS and len(a) in (2, 3)
                    ident = 'location-' + str(locations.counter)
                    locations.counter += 1
                    if modifier in ('~', '~*'):
                        unresolved.add('regex_location_present')
                    if safe:
                        location = {'id': ident, 'source': src, 'line': ln, 'path': path, 'modifier': modifier,
                                    'parent_location': parent, 'context_known': context_known, 'policies': _policies(c)}
                        row['locations'].append(location)
                        metadata(c, location)
                    else:
                        unresolved.add('other_location_present')
                    locations(c, ident, context_known and safe)
            locations.counter = 1
            locations(content)
            if not row['listen']:
                unresolved.add('listen_unspecified')
            for target in [row] + row['locations']:
                if len(target.get('proxy_pass', [])) > 1:
                    unresolved.add('multiple_proxy_pass')
            row['unresolved'] = sorted(unresolved)
            if unresolved:
                issue('server_resolution_incomplete')
        seen = set()
        for server in report['servers']:
            for host in server['server_names']:
                for listener in server['listen']:
                    key = (host, listener['address'], listener['port'])
                    if key in seen:
                        issue('duplicate_server_mapping')
                    seen.add(key)
        report['status'] = 'incomplete' if errors else 'ok'
        report['resolution_complete'] = not errors
    except _Invalid as exc:
        issue(str(exc))
    except (ValueError, TypeError, IndexError, RecursionError):
        issue('parse_failure')
    report['errors'] = sorted(errors)
    return report
