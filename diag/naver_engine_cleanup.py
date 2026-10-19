"""네이버 관제 서버 저장 공간 정리 — 대표 지시 「원인 확인 먼저 하고 정리는 네가 해」(2026-10-19).

지우는 것은 두 가지뿐이다.
  ① 도커 빌드 임시 저장분(build cache) 중 최근 48시간 안에 쓰이지 않은 것.
  ② 배포 도구(로직분석 backend/tools · .github, codex 갈래 전체)가 더는 참조하지 않는
     옛 엔진·중계 이미지 12개 판. 컨테이너가 쓰는 이미지는 지우지 않는다(docker image rm, -f 없음).
엔진 DB · 백업 · 배포 기록(receipts) · 릴리스 폴더 · 지금 판(711a245)·직전 판(b00d6bf) 이미지 ·
배포 도구가 참조하는 판의 이미지는 손대지 않는다.

CLEANUP_APPLY=1 이 아니면 미리보기만 한다(삭제 0). 사전 조건이 하나라도 어긋나면 아무것도 지우지 않는다.
업체명·계정번호 미출력 — 크기·개수·판 번호 앞 7자리만 출력한다.
진단 전용 갈래(diag/naver-engine-health) — main 에 합치지 않는다.
"""
import json
import os
import re
import subprocess

MODE = 'naver-engine-cleanup-v1'
CURRENT = '711a245ea14b590a83eb6746b760ce53275b6602'
PREVIOUS = 'b00d6bf805b43b282c04dd95970ae9ccb7d8247d'
TARGETS = (
    '7422fac362dc6cafcfe6ffface4d00d0f2820665', 'f7eb2e58aafad81e27978f175d83cca0eb5c5733',
    'abf24060eaf907416439bf3e57d83242bb1b7bb5', '317dac8b145669dd9d78f1c35f9bf5ba6ae85418',
    'f8daabe19ee4bdd4d6e79159f431a5dfd49058e6', 'd6542c37d1b247801f3f10259b2098d14e7b6dc8',
    '367a03dcae3a4a3b9da6e6c56918a439b995a40e', '73b9fe39c36284e266eea874902608a4127b00bf',
    '657d98d12b7d84c1e34b6fc61c5fad830e5c0377', '847be08ad8c306b7fce3fb427d1cc3168014493f',
    'b83e908d04223b9e004122ae2ddfc1fc452a5255', 'e132a4b6ebba40ca58fb4de3cd3a66a3c910b218',
)
NAMES = ('engine', 'relay')
REPOS = tuple('metainc/naver-' + n for n in NAMES)
STAGING = '/srv/metainc/ad-deploy-staging'
CACHE_KEEP = 'until=48h'


def run(args, timeout=120):
    result = subprocess.run(args, capture_output=True, timeout=timeout)
    if result.returncode != 0:
        raise ValueError('CMD_FAILED:' + args[1] if len(args) > 1 else 'CMD_FAILED')
    return result.stdout.decode('utf-8', 'replace')


def size_mb(text):
    m = re.match(r'\s*([0-9.]+)\s*([kKMGT]?B)', text or '')
    if not m:
        return None
    unit = {'B': 1 / 1048576, 'kB': 1 / 1024, 'KB': 1 / 1024, 'MB': 1, 'GB': 1024, 'TB': 1048576}[m.group(2)]
    return round(float(m.group(1)) * unit, 1)


def free_gb():
    out = {}
    for path in ('/', '/var/lib/docker'):
        fs = os.statvfs(path)
        out[path] = round(fs.f_bavail * fs.f_frsize / 1073741824, 2)
    return out


def docker_df():
    rows = [json.loads(line) for line in run(['docker', 'system', 'df', '--format', '{{json .}}']).splitlines() if line.strip()]
    return {(r.get('Type') or 'OTHER').replace(' ', '_'): dict(size_mb=size_mb(r.get('Size')), reclaimable_mb=size_mb(r.get('Reclaimable')))
            for r in rows if re.fullmatch('[A-Za-z ]{1,20}', r.get('Type') or '')}


def naver_tags():
    tags = {}
    for line in run(['docker', 'images', '--no-trunc', '--format', '{{.Repository}}:{{.Tag}} {{.ID}}']).splitlines():
        ref, _, image = line.strip().partition(' ')
        if ref.split(':')[0] in REPOS:
            tags[ref] = image
    return tags


def used_images():
    ids = run(['docker', 'ps', '-a', '-q', '--no-trunc']).split()
    if not ids:
        return set()
    return {line.strip() for line in run(['docker', 'inspect', '--format', '{{.Image}}'] + ids).splitlines() if line.strip()}


def services():
    out = {}
    for name in NAMES:
        project = 'naver-engine' if name == 'engine' else 'naver-relay'
        ids = run(['docker', 'ps', '--no-trunc', '--filter', 'label=com.docker.compose.project=' + project,
                   '--filter', 'label=com.docker.compose.service=' + project, '--format', '{{.ID}}']).split()
        if len(ids) != 1:
            out[name] = dict(found=len(ids))
            continue
        row = json.loads(run(['docker', 'inspect', '--format',
                              '{"image":{{json .Image}},"started":{{json .State.StartedAt}},"running":{{json .State.Running}},'
                              '"restarts":{{json .RestartCount}},"source":{{json (index .Config.Labels "metainc.naver.preview.source")}}}',
                              ids[0]]))
        row['id'] = ids[0]
        out[name] = row
    return out


VERBS = ('compose', 'up', 'run', 'exec', 'logs', 'events', 'stats', 'ps', 'inspect', 'start', 'stop', 'restart', 'wait',
         'attach', 'version', 'info', 'cp', 'build', 'buildx', 'builder', 'image', 'images', 'pull', 'load', 'rmi', 'tag',
         'push', 'save', 'commit', 'system', 'create', 'down', 'rm', 'prune', 'import')
# 이미지·빌드 캐시를 만들거나 지우는 동작만 정리와 겹친다. 서비스를 띄워 두는 compose up 등은 늘 떠 있으므로 막지 않는다.
MUTATING = frozenset(('build', 'buildx', 'builder', 'image', 'pull', 'load', 'rmi', 'tag', 'push', 'save', 'commit',
                      'system', 'create', 'down', 'rm', 'prune', 'import'))


def ancestors():
    out, pid = set(), os.getpid()
    while pid > 1 and pid not in out:
        out.add(pid)
        with open('/proc/%d/stat' % pid) as f:
            pid = int(f.read().rsplit(')', 1)[1].split()[1])
    return out


def other_docker_clients():
    mine = ancestors()
    verbs, busy, deploy = {}, 0, 0
    for pid in os.listdir('/proc'):
        if not pid.isdigit() or int(pid) in mine:
            continue
        try:
            with open('/proc/' + pid + '/cmdline', 'rb') as f:
                raw = f.read()
        except OSError:
            continue
        argv = raw.split(b'\0')
        if b'exec(compile(' in raw or b'ad-deploy-staging' in raw:
            deploy += 1
        if argv and os.path.basename(argv[0].decode('utf-8', 'replace')) in ('docker', 'docker-compose', 'docker-buildx'):
            words = [t.decode('utf-8', 'replace') for t in argv[1:]]
            found = [w for w in words if w in VERBS]
            key = '+'.join(found[:2]) or 'OTHER'
            verbs[key] = verbs.get(key, 0) + 1
            if MUTATING.intersection(found) or os.path.basename(argv[0].decode('utf-8', 'replace')) == 'docker-buildx':
                busy += 1
    return dict(verbs=verbs, busy=busy, deploy_tool=deploy)


def unique_sizes():
    sizes = {}
    try:
        text = run(['docker', 'system', 'df', '-v'], timeout=180)
    except Exception:
        return sizes
    for line in text.splitlines():
        parts = line.split()
        if len(parts) >= 8 and parts[0] in REPOS:
            sizes[parts[0] + ':' + parts[1]] = size_mb(parts[-2])
    return sizes


def count_dir(path):
    try:
        return len(os.listdir(path))
    except OSError:
        return None


def state():
    return dict(free_gb=free_gb(), docker=docker_df(), services=services(), tags=naver_tags(), used=used_images(),
                receipts=count_dir(STAGING + '/receipts'), releases=count_dir(STAGING + '/releases'))


def main():
    apply = os.environ.get('CLEANUP_APPLY') == '1'
    result = dict(mode=MODE, apply=apply, ok=False, removed_images=0, cache_reclaimed_mb=0.0)
    try:
        if os.geteuid() != 0:
            raise ValueError('HOST_IDENTITY')
        before = state()
        result['before'] = dict(free_gb=before['free_gb'], docker=before['docker'], naver_tags=len(before['tags']),
                                receipts=before['receipts'], releases=before['releases'])
        svc = before['services']
        for name in NAMES:
            row = svc.get(name, {})
            if row.get('running') is not True or row.get('source') != CURRENT:
                raise ValueError('SERVICE_NOT_CURRENT')
        protected = {}
        for commit in (CURRENT, PREVIOUS):
            for repo in REPOS:
                ref = repo + ':' + commit
                if ref not in before['tags']:
                    raise ValueError('PROTECTED_IMAGE_MISSING')
                protected[ref] = before['tags'][ref]
        clients = other_docker_clients()
        result['other_docker_clients'] = clients
        if clients['busy']:
            raise ValueError('DOCKER_CLIENT_BUSY')
        if clients['deploy_tool']:
            raise ValueError('DEPLOY_TOOL_RUNNING')
        sizes = unique_sizes()
        plan, skipped = [], {}
        for commit in TARGETS:
            for repo in REPOS:
                ref = repo + ':' + commit
                image = before['tags'].get(ref)
                if image is None:
                    skipped['missing'] = skipped.get('missing', 0) + 1
                elif image in before['used']:
                    skipped['in_use'] = skipped.get('in_use', 0) + 1
                elif image in protected.values():
                    skipped['same_as_protected'] = skipped.get('same_as_protected', 0) + 1
                else:
                    plan.append(ref)
        result['plan'] = dict(images=len(plan), commits=sorted({ref.split(':')[1][:7] for ref in plan}),
                              unique_mb=round(sum(sizes.get(ref) or 0 for ref in plan), 1), skipped=skipped,
                              cache_filter=CACHE_KEEP)
        if not apply:
            result['ok'] = True
            return
        failed = 0
        for ref in plan:
            try:
                run(['docker', 'image', 'rm', ref], timeout=120)
                result['removed_images'] += 1
            except Exception:
                failed += 1
        result['remove_failed'] = failed
        again = other_docker_clients()
        if again['busy'] or again['deploy_tool']:
            result['cache_skipped'] = 'BUSY'
        else:
            text = run(['docker', 'builder', 'prune', '-f', '--filter', CACHE_KEEP], timeout=300)
            m = re.search(r'Total(?: reclaimed space)?:\s*([0-9.]+\s*[kKMGT]?B)', text)
            result['cache_reclaimed_mb'] = size_mb(m.group(1)) if m else None
        after = state()
        result['after'] = dict(free_gb=after['free_gb'], docker=after['docker'], naver_tags=len(after['tags']),
                               receipts=after['receipts'], releases=after['releases'])
        removed = set(plan) - set(after['tags'])
        checks = dict(
            services_unchanged=all(after['services'].get(n) == svc.get(n) for n in NAMES),
            protected_present=all(after['tags'].get(ref) == image for ref, image in protected.items()),
            other_tags_unchanged={ref: image for ref, image in before['tags'].items() if ref not in plan}
            == {ref: image for ref, image in after['tags'].items() if ref not in plan},
            removed_match=len(removed) == result['removed_images'],
            receipts_unchanged=after['receipts'] == before['receipts'],
            releases_unchanged=after['releases'] == before['releases'],
        )
        result['checks'] = checks
        result['ok'] = all(checks.values()) and failed == 0
    except Exception as error:
        result['error'] = str(error) if isinstance(error, ValueError) and re.fullmatch(r'[A-Z_]{1,40}(:[a-z]{1,20})?', str(error)) else type(error).__name__
    finally:
        print('NAVER_ENGINE_CLEANUP_V1=' + json.dumps(result, sort_keys=True, ensure_ascii=True, separators=(',', ':')))


if __name__ == '__main__':
    main()
