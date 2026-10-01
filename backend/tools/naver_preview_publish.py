"""Narrow, hash-pinned nginx publication. No credential, request or nginx dump output."""
import hashlib
import contextlib
import fcntl
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import tempfile

CONFIG = Path('/etc/nginx/sites-enabled/ad.metainc.co.kr')
NGINX_ROOT = Path('/etc/nginx')
ROOT = Path('/srv/metainc/ad-deploy-staging')
HOSTNAME = 'dashboard.metainc.co.kr'
SSL_INCLUDE = Path('/etc/letsencrypt/options-ssl-nginx.conf')
MARKER = '# metainc-naver-owner-preview-v1'
MAX_CONFIG = 1024 * 1024


def sha(body):
    return hashlib.sha256(body).hexdigest()


def _tokens(text):
    """Small fail-closed nginx lexer, preserving original byte positions for insertion."""
    out, i = [], 0
    while i < len(text):
        if text[i].isspace():
            i += 1
            continue
        if text[i] == '#':
            end = text.find('\n', i)
            i = len(text) if end < 0 else end + 1
            continue
        begin = i
        if text[i] in '{};':
            out.append((text[i], i, i+1))
            i += 1
            continue
        value, quote = '', None
        while i < len(text):
            char = text[i]
            if quote:
                if char == quote:
                    quote = None
                elif char == '\\':
                    i += 1
                    if i >= len(text):
                        raise ValueError('CONFIG_ESCAPE')
                    value += text[i]
                else:
                    value += char
            elif char in '\"\'':
                quote = char
            elif char == '\\':
                i += 1
                if i >= len(text):
                    raise ValueError('CONFIG_ESCAPE')
                value += text[i]
            elif char.isspace() or char in '{};#':
                break
            else:
                value += char
            i += 1
        if quote or not value:
            raise ValueError('CONFIG_TOKEN')
        out.append((value, begin, i))
        if len(out) > 20000:
            raise ValueError('CONFIG_SIZE')
    return out


def _parse(text):
    tokens = _tokens(text)
    def block(pos, depth=0):
        if depth > 12:
            raise ValueError('CONFIG_DEPTH')
        nodes = []
        while pos < len(tokens) and tokens[pos][0] != '}':
            begin, words = tokens[pos][1], []
            while pos < len(tokens) and tokens[pos][0] not in '{};':
                words.append(tokens[pos][0])
                pos += 1
            if not words or pos >= len(tokens):
                raise ValueError('CONFIG_SYNTAX')
            delimiter = tokens[pos]
            if delimiter[0] == ';':
                nodes.append((words, begin, delimiter[2], None))
                pos += 1
            elif delimiter[0] == '{':
                children, pos = block(pos+1, depth+1)
                if pos >= len(tokens) or tokens[pos][0] != '}':
                    raise ValueError('CONFIG_SYNTAX')
                nodes.append((words, begin, tokens[pos][1], children))
                pos += 1
            else:
                raise ValueError('CONFIG_SYNTAX')
        return nodes, pos
    nodes, pos = block(0)
    if pos != len(tokens):
        raise ValueError('CONFIG_SYNTAX')
    return nodes


def _walk(nodes):
    for node in nodes:
        yield node
        if node[3] is not None:
            yield from _walk(node[3])


def _tls_servers(nodes):
    found = []
    for node in _walk(nodes):
        if node[0] != ['server'] or node[3] is None:
            continue
        names = [n[0][1:] for n in node[3] if n[0][0] == 'server_name']
        if not any(HOSTNAME in group for group in names):
            continue
        listeners = [n[0][1:] for n in node[3] if n[0][0] == 'listen']
        if any('ssl' in row and re.search(r'(?:^|:)443$', row[0]) for row in listeners if row):
            if len(names) != 1 or names[0] not in ([HOSTNAME], ['ad.metainc.co.kr', HOSTNAME]):
                raise ValueError('TLS_SERVER_ALIASES')
            found.append(node)
    return found


def validate_ssl_include(body):
    if not isinstance(body, bytes) or not 0 < len(body) <= 8192:
        raise ValueError('SSL_INCLUDE_SIZE')
    allowed = {'ssl_session_cache', 'ssl_session_timeout', 'ssl_session_tickets',
               'ssl_protocols', 'ssl_prefer_server_ciphers', 'ssl_ciphers'}
    nodes = _parse(body.decode('utf-8'))
    if not nodes:
        raise ValueError('SSL_INCLUDE_EMPTY')
    for words, _, _, children in nodes:
        if children is not None or words[0] not in allowed or len(words) < 2 or any(
                not re.fullmatch(r'[A-Za-z0-9_:!+@.\-]+', value) for value in words[1:]):
            raise ValueError('SSL_INCLUDE_DIRECTIVE')
    return sha(body)


def build_config(body, *, ssl_include=None):
    if not isinstance(body, bytes) or not 0 < len(body) <= MAX_CONFIG:
        raise ValueError('CONFIG_SIZE')
    text = body.decode('utf-8')
    if MARKER in text:
        raise ValueError('ALREADY_PUBLISHED')
    servers = _tls_servers(_parse(text))
    if len(servers) != 1:
        raise ValueError('TLS_SERVER_NOT_UNIQUE')
    server = servers[0]
    direct = server[3]
    locations = [node for node in direct if node[0][0] == 'location']
    roots = [node for node in locations if node[0] == ['location', '/']]
    if len(roots) != 1 or [n[0] for n in roots[0][3] if n[0][0] == 'proxy_pass'] != [
            ['proxy_pass', 'http://127.0.0.1:5051']]:
        raise ValueError('LEGACY_ROOT_NOT_EXACT')
    for words, _, _, _ in _walk(direct):
        if words[0] == 'include':
            if words != ['include', str(SSL_INCLUDE)]:
                raise ValueError('UNREVIEWED_INCLUDE')
            validate_ssl_include(ssl_include)
        if words[0] == 'location' and (any('naver' in word.lower() for word in words[1:])
                or any(word in ('~', '~*') for word in words[1:])):
            raise ValueError('LOCATION_CONFLICT')
        if words[0] == 'access_log' and words != ['access_log', 'off']:
            raise ValueError('ACCESS_LOG_CONFLICT')
        if words[0] == 'error_log' and words != ['error_log', '/dev/null', 'crit']:
            raise ValueError('ERROR_LOG_CONFLICT')
    if any(node[0][0] in ('return', 'rewrite', 'error_page') for node in direct):
        raise ValueError('SERVER_REWRITE')
    snippet = '\n    '+MARKER+'\n    access_log off;\n    error_log /dev/null crit;\n'
    for route in ('= /naver', '^~ /naver/', '= /api/naver-auto', '^~ /api/naver-auto/'):
        snippet += '''    location %s {
        if ($host != dashboard.metainc.co.kr) { return 404; }
        proxy_pass http://unix:/run/metainc/naver-relay/relay.sock:;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $remote_addr;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header Referer "";
        proxy_hide_header Referrer-Policy;
        proxy_hide_header Cache-Control;
        add_header Referrer-Policy no-referrer always;
        add_header Cache-Control no-store always;
        proxy_intercept_errors off;
        proxy_redirect off;
        client_max_body_size 64k;
        proxy_connect_timeout 3s;
        proxy_read_timeout 35s;
        proxy_send_timeout 35s;
    }
''' % route
    return (text[:server[2]] + snippet + text[server[2]:]).encode('utf-8')


def validate_package(package, *, discovery=False):
    fields = {'baseline', 'source_commit', 'source_tar_gz_sha256', 'nginx_sha256'}
    if not isinstance(package, dict) or (set(package) != fields and not (
            discovery and set(package) == fields-{'nginx_sha256'})):
        raise ValueError('PACKAGE_FIELDS')
    for key, value in package.items():
        if discovery and key == 'nginx_sha256' and value == '':
            continue
        if not isinstance(value, str) or not re.fullmatch('[0-9a-f]{40}' if key == 'source_commit' else '[0-9a-f]{64}', value):
            raise ValueError('PACKAGE_SHAPE')
    return package


def _unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('DUPLICATE_FIELD')
        result[key] = value
    return result


def _json(body):
    return json.loads(body, object_pairs_hook=_unique)


def _trusted_directory(path, *, private=False):
    path = Path(path)
    for parent in reversed((path, *path.parents)):
        st = parent.lstat()
        if not stat.S_ISDIR(st.st_mode) or st.st_uid != 0 or st.st_mode & 0o022:
            raise ValueError('UNSAFE_DIRECTORY')
    if private and (path.stat().st_gid != 0 or stat.S_IMODE(path.stat().st_mode) != 0o700):
        raise ValueError('PRIVATE_DIRECTORY_POLICY')


def _read_regular(path, *, private=False):
    path = Path(path)
    _trusted_directory(path.parent, private=private)
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(fd, 'rb') as stream:
        st = os.fstat(stream.fileno())
        if (not stat.S_ISREG(st.st_mode) or st.st_uid != 0 or st.st_gid != 0 or st.st_nlink != 1
                or st.st_mode & 0o022 or not 0 < st.st_size <= MAX_CONFIG
                or (private and stat.S_IMODE(st.st_mode) != 0o600)):
            raise ValueError('FILE_POLICY')
        body = stream.read(MAX_CONFIG+1)
    if len(body) > MAX_CONFIG:
        raise ValueError('FILE_SIZE')
    return body, st


class NativeSystem:
    """Host filesystem/process adapter. Returned values never contain nginx command output."""
    def root(self):
        return os.geteuid() == 0

    def config(self):
        _trusted_directory(CONFIG.parent)
        link = CONFIG.lstat()
        if link.st_uid != 0 or not (stat.S_ISLNK(link.st_mode) or stat.S_ISREG(link.st_mode)):
            raise ValueError('CONFIG_LINK_POLICY')
        target = CONFIG.resolve(strict=True)
        if not target.is_relative_to(NGINX_ROOT) or target == NGINX_ROOT:
            raise ValueError('CONFIG_TARGET_SCOPE')
        body, _ = _read_regular(target)
        return str(target), body

    def read_private(self, path):
        return _read_regular(path, private=True)[0]

    def ssl_include(self):
        body = _read_regular(SSL_INCLUDE)[0]
        validate_ssl_include(body)
        return body

    def new_private(self, path, body):
        path = Path(path)
        _trusted_directory(path.parent, private=True)
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, 'wb') as stream:
            os.fchown(stream.fileno(), 0, 0)
            os.fchmod(stream.fileno(), 0o600)
            stream.write(body)
            stream.flush()
            os.fsync(stream.fileno())

    @contextlib.contextmanager
    def locked(self):
        _trusted_directory(ROOT, private=True)
        folder = ROOT/'publish'
        try:
            folder.mkdir(mode=0o700)
        except FileExistsError:
            pass
        _trusted_directory(folder, private=True)
        fd = os.open(folder/'.lock', os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
        try:
            st = os.fstat(fd)
            if (not stat.S_ISREG(st.st_mode) or (st.st_uid, st.st_gid, st.st_nlink,
                    stat.S_IMODE(st.st_mode)) != (0, 0, 1, 0o600)):
                raise ValueError('LOCK_POLICY')
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            yield
        finally:
            os.close(fd)

    def replace_config(self, target, expected, body):
        current_target, current = self.config()
        if current_target != target or sha(current) != expected:
            raise ValueError('CONFIG_CHANGED')
        _, metadata = _read_regular(target)
        fd, temporary = tempfile.mkstemp(prefix='.naver-preview-', dir=Path(target).parent)
        try:
            with os.fdopen(fd, 'wb') as stream:
                os.fchown(stream.fileno(), metadata.st_uid, metadata.st_gid)
                os.fchmod(stream.fileno(), stat.S_IMODE(metadata.st_mode))
                stream.write(body)
                stream.flush()
                os.fsync(stream.fileno())
            # Do not replace a newly edited file or a repointed sites-enabled symlink.
            if self.config() != (target, current):
                raise ValueError('CONFIG_CHANGED')
            os.replace(temporary, target)
            directory = os.open(Path(target).parent, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

    def command(self, args):
        if args not in (['nginx', '-T'], ['nginx', '-t'], ['nginx', '-s', 'reload']):
            raise ValueError('COMMAND_SCOPE')
        result = subprocess.run(args, capture_output=True, timeout=30,
                                env={'PATH': '/usr/sbin:/usr/bin:/sbin:/bin', 'LANG': 'C'})
        if result.returncode or len(result.stdout) > 2*MAX_CONFIG:
            raise RuntimeError('NGINX_COMMAND_FAILED')
        return result.stdout


def _check_identity(package, host, system, *, discovery=False):
    validate_package(package, discovery=discovery)
    if not system.root() or host.baseline() != package['baseline']:
        raise ValueError('HOST_BASELINE')


def _preflight(package, host, system, *, discovery=False):
    _check_identity(package, host, system, discovery=discovery)
    commit = package['source_commit']
    prepared = _json(system.read_private(ROOT/'receipts'/('preview-'+commit+'.json')))
    started = _json(system.read_private(ROOT/'receipts'/('preview-start-'+commit+'.json')))
    if (prepared.get('ok') is not True or prepared.get('stage') != 'prepared'
            or prepared.get('source_commit') != commit or started.get('ok') is not True
            or started.get('stage') != 'internal_ready' or started.get('source_commit') != commit
            or any(prepared.get('package', {}).get(key) != package[key]
                   for key in ('baseline', 'source_commit', 'source_tar_gz_sha256'))):
        raise ValueError('SOURCE_NOT_READY')
    target, original = system.config()
    if package.get('nginx_sha256') and sha(original) != package['nginx_sha256']:
        raise ValueError('CONFIG_CHANGED')
    ssl_include = system.ssl_include() if str(SSL_INCLUDE).encode() in original else None
    candidate = build_config(original, ssl_include=ssl_include)
    effective = system.command(['nginx', '-T']).decode('utf-8')
    sections = re.split(r'(?m)^# configuration file ([^\n]+):\n', effective)
    loaded = [sections[i+1] for i in range(1, len(sections), 2)
              if sections[i] in (str(CONFIG), target)]
    if len(loaded) != 1 or loaded[0].rstrip('\n') != original.decode('utf-8').rstrip('\n'):
        raise ValueError('CONFIG_NOT_LOADED')
    effective_nodes = _parse(effective)
    if len(_tls_servers(effective_nodes)) != 1:
        raise ValueError('GLOBAL_TLS_SERVER_NOT_UNIQUE')
    if any(node[0] == ['http'] and any(child[0][0] == 'error_page' for child in node[3])
           for node in _walk(effective_nodes)):
        raise ValueError('INHERITED_ERROR_PAGE')
    summary = {'ok': True, 'mode': 'plan', 'mutations': 0, 'source_commit': commit,
               'target': target, 'original_sha256': sha(original), 'candidate_sha256': sha(candidate),
               'routes': ['/naver', '/naver/', '/api/naver-auto', '/api/naver-auto/'],
               'legacy_root_unchanged': True, 'request_logs_disabled': True,
               'public_access_verified': False}
    if ssl_include is not None:
        summary['ssl_include_sha256'] = sha(ssl_include)
    return summary, original, candidate


def plan(package, host, *, system=None):
    return _preflight(package, host, system or NativeSystem(), discovery=True)[0]


def inspect(package, host, *, system=None):
    system = system or NativeSystem()
    if (not isinstance(package, dict) or set(package) != {'baseline'}
            or not re.fullmatch('[0-9a-f]{64}', package['baseline'])
            or not system.root() or host.baseline() != package['baseline']):
        raise ValueError('HOST_BASELINE')
    target, original = system.config()
    details=[]
    for node in _walk(_parse(original.decode())):
        if node[0] != ['server'] or node[3] is None:
            continue
        names=[n[0][1:] for n in node[3] if n[0][0]=='server_name']
        if not any(HOSTNAME in group for group in names):
            continue
        details.append({key:[n[0][1:] for n in _walk(node[3]) if n[0][0]==key]
                        for key in ('server_name','listen','include','access_log','error_log','location','proxy_pass')})
    try:
        ssl_include = system.ssl_include() if str(SSL_INCLUDE).encode() in original else None
        candidate=build_config(original, ssl_include=ssl_include);error=None;digest=sha(candidate)
    except ValueError as failure:
        error=str(failure);digest=None
    return {'ok':True,'mode':'inspect','mutations':0,'target':target,'original_sha256':sha(original),
            'servers':details,'candidate_sha256':digest,'candidate_error':error}


def _backup_paths(commit):
    return ROOT/'publish'/('nginx-'+commit+'.before'), ROOT/'publish'/('nginx-'+commit+'.json')


def _restore(system, target, expected, original):
    system.replace_config(target, expected, original)
    system.command(['nginx', '-t'])
    system.command(['nginx', '-s', 'reload'])


def apply(package, host, *, system=None):
    system = system or NativeSystem()
    # This first read-only gate runs before creating even the private lock folder.
    _preflight(package, host, system)
    with system.locked():
        summary, original, candidate = _preflight(package, host, system)
        before_path, manifest_path = _backup_paths(package['source_commit'])
        manifest = {'package': dict(package), 'target': summary['target'],
                    'before_sha256': sha(original), 'candidate_sha256': sha(candidate)}
        system.new_private(before_path, original)
        system.new_private(manifest_path, json.dumps(manifest, sort_keys=True).encode())
        try:
            system.replace_config(summary['target'], sha(original), candidate)
            system.command(['nginx', '-t'])
            if host.baseline() != package['baseline']:
                raise ValueError('POST_BASELINE')
            system.command(['nginx', '-s', 'reload'])
        except Exception:
            target, current = system.config()
            if target != summary['target'] or sha(current) not in (sha(original), sha(candidate)):
                raise RuntimeError('PUBLISH_ROLLBACK_CONFLICT') from None
            try:
                # Even reload errors can leave the candidate loaded; always reload the original.
                _restore(system, target, sha(current), original)
            except Exception:
                raise RuntimeError('PUBLISH_ROLLBACK_FAILED') from None
            raise RuntimeError('PUBLISH_FAILED_ROLLED_BACK') from None
        return {'ok': True, 'mode': 'apply', 'source_commit': package['source_commit'],
                'candidate_sha256': sha(candidate), 'reload_requested': True,
                'public_access_verified': False, 'legacy_root_unchanged': True}


def rollback(package, host, *, system=None):
    system = system or NativeSystem()
    _check_identity(package, host, system)
    with system.locked():
        before_path, manifest_path = _backup_paths(package['source_commit'])
        manifest = _json(system.read_private(manifest_path))
        original = system.read_private(before_path)
        if (manifest.get('package') != package or manifest.get('before_sha256') != sha(original)
                or sha(original) != package['nginx_sha256']
                or manifest.get('candidate_sha256') != sha(build_config(original,
                    ssl_include=system.ssl_include() if str(SSL_INCLUDE).encode() in original else None))):
            raise ValueError('ROLLBACK_PROVENANCE')
        _restore(system, manifest['target'], manifest['candidate_sha256'], original)
        return {'ok': True, 'mode': 'rollback', 'source_commit': package['source_commit'],
                'rolled_back': True, 'reload_requested': True, 'original_sha256': sha(original)}
