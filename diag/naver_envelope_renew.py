"""네이버 관제 배포 봉투 인증서 갱신 — 서버 전용 열쇠쌍을 새로 만들고 옛 쌍은 같은 보호로 보관한다.

배포 봉투 = 다음 판 소스와 운영 설정을 서버만 열 수 있게 잠그는 자물쇠. 공개 인증서(recipient.pem)로 잠그고
서버에만 있는 개인키(private.pem)로 연다. 인증서 유효 기간이 지나면 봉인 도구가 잠그기를 거절해 새 판을 낼 수 없다.

미리보기(READ_ONLY_NAVER_ENVELOPE_PREVIEW): 지금 폴더·파일 권한, 인증서 지문·만료일, 배포 작업 동시 실행 여부만 본다.
실행(APPLY_NAVER_ENVELOPE_RENEW): 새 폴더에 RSA 4096 · 365일 인증서를 만들고, 봉인 도구와 같은 방식으로 잠근 뒤
서버 배포 도구와 같은 명령으로 열어 보는 왕복 시험을 통과해야만 자리를 바꾼다. 옛 폴더는 이름만 바꿔
(naver-deploy-envelope.retired-<시각>) 같은 권한으로 남긴다 — 되돌리기는 이름을 되돌리면 된다.
개인키는 출력·복사·전송하지 않는다. 공개 인증서 본문·지문·기간만 출력한다.
진단 전용 갈래(diag/naver-engine-health) — main 에 합치지 않는다.
"""
import hashlib
import json
import os
import re
import stat
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

MODE = 'naver-envelope-renew-v1'
APPLY = os.environ.get('CLEANUP_APPLY') == '1'
PARENT = Path('/etc/metainc')
FOLDER = PARENT / 'naver-deploy-envelope'
BACKUP_CERT = Path('/etc/metainc/naver-engine/backup-recipient.pem')
DAYS = 365
SUBJECT = '/CN=metainc-naver-deploy-envelope'
KST = timezone(timedelta(hours=9))
# 봉인 도구(AD tools/naver-preview-seal.py)의 암호화 명령과 서버 배포 도구의 복호화 명령을 그대로 쓴다.
SEAL_ENV = {'PATH': '/usr/bin:/bin', 'LANG': 'C', 'OPENSSL_CONF': '/dev/null'}
ENCRYPT = ['openssl', 'cms', '-encrypt', '-binary', '-aes-256-gcm', '-stream', '-outform', 'DER', '-recip', None,
           '-keyopt', 'rsa_padding_mode:oaep', '-keyopt', 'rsa_oaep_md:sha256', '-keyopt', 'rsa_mgf1_md:sha256']
DECRYPT = ['openssl', 'cms', '-decrypt', '-binary', '-inform', 'DER', '-inkey', None]
VERBS = ('build', 'buildx', 'builder', 'image', 'pull', 'load', 'rmi', 'tag', 'push', 'save', 'commit',
         'system', 'create', 'down', 'rm', 'prune', 'import')


def run(args, data=None, env=None, timeout=60):
    result = subprocess.run(args, input=data, capture_output=True, timeout=timeout, env=env)
    if result.returncode != 0:
        raise ValueError('CMD_FAILED')
    return result.stdout


def ancestors():
    out, pid = set(), os.getpid()
    while pid > 1 and pid not in out:
        out.add(pid)
        with open('/proc/%d/stat' % pid) as f:
            pid = int(f.read().rsplit(')', 1)[1].split()[1])
    return out


def deploy_busy():
    """배포 도구(python3 -I -B - / exec(compile( 실행)나 이미지를 만드는 docker 명령이 돌고 있는지 센다."""
    mine, deploy, docker = ancestors(), 0, 0
    for pid in os.listdir('/proc'):
        if not pid.isdigit() or int(pid) in mine:
            continue
        try:
            with open('/proc/' + pid + '/cmdline', 'rb') as f:
                raw = f.read()
        except OSError:
            continue
        argv = [t for t in raw.split(b'\0') if t]
        if not argv:
            continue
        base = os.path.basename(argv[0].decode('utf-8', 'replace'))
        if base in ('docker', 'docker-compose', 'docker-buildx'):
            if any(t.decode('utf-8', 'replace') in VERBS for t in argv[1:]):
                docker += 1
        elif (base.startswith('python') and argv[1:] == [b'-I', b'-B', b'-']) or b'exec(compile(' in raw:
            deploy += 1
    return dict(deploy_tools=deploy, image_commands=docker)


def folder_policy(folder):
    """서버 배포 도구가 요구하는 그대로: 폴더 root:root 0700, 개인키 root:root 0600 · 링크 1, 인증서 일반 파일."""
    info = folder.lstat()
    out = dict(folder=stat.S_ISDIR(info.st_mode) and (info.st_uid, info.st_gid, stat.S_IMODE(info.st_mode)) == (0, 0, 0o700))
    key = (folder / 'private.pem').lstat()
    out['private_key'] = (stat.S_ISREG(key.st_mode)
                          and (key.st_uid, key.st_gid, stat.S_IMODE(key.st_mode), key.st_nlink) == (0, 0, 0o600, 1))
    cert = (folder / 'recipient.pem').lstat()
    out['certificate'] = stat.S_ISREG(cert.st_mode) and cert.st_nlink == 1 and cert.st_uid == 0
    out['entries'] = sorted(os.listdir(folder)) == ['private.pem', 'recipient.pem']
    return out


def certificate(path):
    body = path.read_bytes()
    if not body.startswith(b'-----BEGIN CERTIFICATE-----\n') or len(body) > 4096 or b'PRIVATE' in body:
        raise ValueError('CERT_SHAPE')
    text = run(['openssl', 'x509', '-noout', '-startdate', '-enddate', '-subject', '-text'], data=body).decode('ascii', 'replace')
    fields = dict(line.split('=', 1) for line in text.splitlines() if re.fullmatch(r'(notBefore|notAfter|subject)=[ -~]{1,120}', line))
    bits = re.search(r'Public-Key: \((\d{3,5}) bit\)', text)
    out = dict(sha256=hashlib.sha256(body).hexdigest(), subject=fields.get('subject'), bits=int(bits[1]) if bits else None)
    for name in ('notBefore', 'notAfter'):
        value = fields.get(name)
        try:
            out[name] = datetime.strptime(value, '%b %d %H:%M:%S %Y GMT').replace(tzinfo=timezone.utc).astimezone(KST).strftime('%Y-%m-%d %H:%M') if value else None
        except ValueError:
            out[name] = 'OTHER'
    return out, body


def roundtrip(folder):
    """봉인 도구처럼 잠그고 서버 배포 도구처럼 연다. 같은 바이트가 나와야 한다."""
    secret = os.urandom(64)
    encrypt = list(ENCRYPT)
    encrypt[encrypt.index(None)] = str(folder / 'recipient.pem')
    sealed = run(encrypt, data=secret, env=SEAL_ENV)
    decrypt = list(DECRYPT)
    decrypt[decrypt.index(None)] = str(folder / 'private.pem')
    return run(decrypt, data=sealed) == secret, sealed


def create(folder):
    """코덱스 create_envelope 와 같은 방식(배타적 mkdir · umask 077 · RSA 4096 · 같은 CN), 기간만 365일."""
    folder.mkdir(mode=0o700)
    os.chown(folder, 0, 0)
    previous = os.umask(0o077)
    try:
        result = subprocess.run(['openssl', 'req', '-new', '-x509', '-newkey', 'rsa:4096', '-nodes', '-days', str(DAYS),
                                 '-subj', SUBJECT, '-keyout', str(folder / 'private.pem'), '-out', str(folder / 'recipient.pem')],
                                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=120)
        if result.returncode:
            raise ValueError('ENVELOPE_GENERATION_FAILED')
    finally:
        os.umask(previous)
    for name in ('private.pem', 'recipient.pem'):
        os.chown(folder / name, 0, 0)
        os.chmod(folder / name, 0o600)


def fsync_dir(path):
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def main():
    result = dict(mode=MODE, apply=APPLY, ok=False)
    try:
        if os.geteuid() != 0:
            raise ValueError('HOST_IDENTITY')
        if FOLDER.resolve() != FOLDER or PARENT.resolve() != PARENT:
            raise ValueError('SYMLINKED_ENVELOPE')
        result['openssl'] = re.sub(r'[^ -~]', '', run(['openssl', 'version']).decode('ascii', 'replace'))[:40]
        result['policy'] = folder_policy(FOLDER)
        if not all(result['policy'].values()):
            raise ValueError('ENVELOPE_POLICY')
        result['current'], _ = certificate(FOLDER / 'recipient.pem')
        try:
            result['backup_recipient'], _ = certificate(BACKUP_CERT)
            result['backup_recipient'].pop('sha256', None)
        except Exception as error:
            result['backup_recipient'] = dict(available=False, error=type(error).__name__)
        result['retired_folders'] = sorted(n for n in os.listdir(PARENT) if re.fullmatch(r'naver-deploy-envelope\.retired-\d{8}T\d{6}Z', n))
        busy = deploy_busy()
        result['busy'] = busy
        ok_now, _ = roundtrip(FOLDER)
        result['current_roundtrip'] = ok_now
        if not APPLY:
            result['ok'] = ok_now
            return
        if busy['deploy_tools'] or busy['image_commands']:
            raise ValueError('DEPLOY_BUSY')
        stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
        staged = PARENT / ('naver-deploy-envelope.new-' + stamp)
        retired = PARENT / ('naver-deploy-envelope.retired-' + stamp)
        if os.path.lexists(staged) or os.path.lexists(retired):
            raise ValueError('STAGING_EXISTS')
        result['stage'] = 'create'
        try:
            create(staged)
            if not all(folder_policy(staged).values()):
                raise ValueError('NEW_POLICY')
            fresh, body = certificate(staged / 'recipient.pem')
            if fresh['bits'] != 4096 or fresh['subject'] is None or 'metainc-naver-deploy-envelope' not in fresh['subject']:
                raise ValueError('NEW_CERT_SHAPE')
            result['stage'] = 'roundtrip'
            ok_new, sealed_new = roundtrip(staged)
            if not ok_new:
                raise ValueError('NEW_ROUNDTRIP')
            # 옛 개인키로는 새 봉투가 열리지 않아야 한다(정말 다른 열쇠쌍인지).
            decrypt = list(DECRYPT)
            decrypt[decrypt.index(None)] = str(FOLDER / 'private.pem')
            try:
                run(decrypt, data=sealed_new)
                raise ValueError('NEW_KEY_NOT_DISTINCT')
            except ValueError as error:
                if str(error) != 'CMD_FAILED':
                    raise
        except Exception:
            if staged.is_dir() and not staged.is_symlink():
                for name in os.listdir(staged):
                    os.unlink(staged / name)
                staged.rmdir()
            raise
        result['stage'] = 'swap'
        os.rename(FOLDER, retired)
        try:
            os.rename(staged, FOLDER)
        except Exception:
            os.rename(retired, FOLDER)
            raise
        fsync_dir(PARENT)
        result['stage'] = 'verify'
        result['policy_after'] = folder_policy(FOLDER)
        result['retired_policy'] = folder_policy(retired)
        after, body_after = certificate(FOLDER / 'recipient.pem')
        ok_after, _ = roundtrip(FOLDER)
        if not all(result['policy_after'].values()) or after['sha256'] != fresh['sha256'] or not ok_after:
            raise ValueError('POST_SWAP_CHECK')
        result.update(renewed=after, retired_folder=retired.name, roundtrip_after=ok_after,
                      certificate_pem=body_after.decode('ascii'), ok=True)
        result['stage'] = 'done'
    except Exception as error:
        result['error'] = str(error) if isinstance(error, ValueError) and re.fullmatch(r'[A-Z_]{1,40}', str(error)) else type(error).__name__
    finally:
        print('NAVER_ENVELOPE_RENEW_V1=' + json.dumps(result, sort_keys=True, ensure_ascii=True, separators=(',', ':')))


if __name__ == '__main__':
    main()
