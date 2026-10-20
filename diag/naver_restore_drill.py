"""네이버 관제 밤 백업 복원 연습 — 엔진 공식 복원 검증 도구(naver_runtime.restore_check)를 실제 백업에 돌린다.

가장 최근 로컬 백업 압축본(암호화 전 사본)을 읽기 전용으로 붙여, 네트워크 없는 일회용 컨테이너 안에서
옛 판(711a245 · 복원 상한 2 GiB)과 새 판(382f143 · 16 GiB) 이미지로 각각 복원 검증을 돌린다.
복원본은 임시 폴더(/var/backups/metainc/restore-drill)에만 쓰고 끝나면 지운다. 운영 DB·백업·엔진은 손대지 않는다.
결과는 판정·표 개수·줄 수 합계만 출력한다(업체명·계정번호 미출력).
진단 전용 갈래(diag/naver-engine-health) — main 에 합치지 않는다.
"""
import json
import os
import re
import shutil
import stat
import subprocess
import time
import zipfile
from datetime import datetime, timedelta, timezone

MODE = 'naver-restore-drill-v1'
LOCAL = '/var/backups/metainc/naver-engine/local'
DRILL = '/var/backups/metainc/restore-drill'
IMAGES = (('old', 'metainc/naver-engine:711a245ea14b590a83eb6746b760ce53275b6602'),
          ('new', 'metainc/naver-engine:382f143ad72a5fb0389d79ba0fac199566016e8b'))
NAME = re.compile(r'naver-(\d{8}T\d{6}Z)-[0-9a-f]{32}\.zip')
KST = timezone(timedelta(hours=9))


def free_gb():
    fs = os.statvfs('/var/backups')
    return round(fs.f_bavail * fs.f_frsize / 1073741824, 2)


def drill(label, image, archive, uid, kst_date):
    out = DRILL + '/out-' + label
    name = 'naver-restore-drill-' + label
    command = ['docker', 'run', '--rm', '--name', name, '--network', 'none', '--read-only', '--user', '%d:%d' % (uid, uid),
               '--cap-drop', 'ALL', '--security-opt', 'no-new-privileges:true', '--pids-limit', '64',
               '--memory', '512m', '--cpus', '1', '--label', 'metainc.naver.restore-drill=1',
               '--tmpfs', '/tmp:rw,noexec,nosuid,nodev,size=64m',
               '-v', archive + ':/in/archive.zip:ro', '-v', DRILL + ':/drill',
               image, 'python', '-m', 'naver_runtime.restore_check',
               '--archive', '/in/archive.zip', '--expected-kst-date', kst_date, '--output-dir', '/drill/out-' + label]
    started = time.monotonic()
    try:
        result = subprocess.run(command, capture_output=True, timeout=900)
    except subprocess.TimeoutExpired:
        # 시간 초과면 컨테이너를 먼저 멈춘 뒤에야 임시 폴더를 지운다(쓰는 중인 폴더를 지우지 않게).
        subprocess.run(['docker', 'rm', '-f', name], capture_output=True, timeout=120)
        raise ValueError('DRILL_TIMEOUT')
    seconds = round(time.monotonic() - started, 1)
    text = result.stdout.decode('utf-8', 'replace').strip().splitlines()
    try:
        report = json.loads(text[-1]) if text else {}
    except ValueError:
        report = {}
    counts = report.get('row_counts') if isinstance(report.get('row_counts'), dict) else {}
    summary = dict(exit=result.returncode, seconds=seconds, docker_failed=result.returncode in (125, 126, 127),
                   status=report.get('status') if report.get('status') in ('verified', 'failed') else 'OTHER',
                   tables=len(counts), rows=sum(v for v in counts.values() if isinstance(v, int)),
                   snapshot_sha_prefix=(report.get('snapshot_sha256') or '')[:12] if re.fullmatch('[0-9a-f]{64}', report.get('snapshot_sha256') or '') else None)
    try:
        summary['restored_bytes'] = os.path.getsize(out + '/snapshot.sqlite')
    except OSError:
        summary['restored_bytes'] = None
    return summary


def main():
    result = dict(mode=MODE, ok=False)
    made = False
    try:
        if os.geteuid() != 0:
            raise ValueError('HOST_IDENTITY')
        now = datetime.now(KST)
        minute = now.hour * 60 + now.minute
        if minute >= 23 * 60 + 30 or minute < 60:
            raise ValueError('BACKUP_WINDOW')
        names = sorted(n for n in os.listdir(LOCAL) if NAME.fullmatch(n))
        if not names:
            raise ValueError('NO_LOCAL_BACKUP')
        archive = os.path.join(LOCAL, names[-1])
        st = os.lstat(archive)
        if not stat.S_ISREG(st.st_mode) or st.st_nlink != 1 or st.st_mode & 0o077:
            raise ValueError('ARCHIVE_UNSAFE')
        # 엔진 검증 도구는 manifest 의 created_at(UTC) 을 KST 날짜로 바꿔 대조한다 — 파일 이름이 아니라 같은 값을 넘긴다.
        with zipfile.ZipFile(archive) as packed:
            if packed.getinfo('manifest.json').file_size > 1024 * 1024:
                raise ValueError('MANIFEST_SIZE')
            created_text = json.loads(packed.read('manifest.json')).get('created_at')
            snapshot_bytes = packed.getinfo('snapshot.sqlite').file_size
        if not isinstance(created_text, str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d{6})?\+00:00', created_text):
            raise ValueError('MANIFEST_CREATED_AT')
        created = datetime.fromisoformat(created_text)
        kst_date = created.astimezone(KST).date().isoformat()
        result['archive'] = dict(created_kst=created.astimezone(KST).strftime('%Y-%m-%d %H:%M'), kst_date=kst_date,
                                 bytes=st.st_size, snapshot_bytes=snapshot_bytes, owner_uid=st.st_uid,
                                 over_old_cap=snapshot_bytes > 2 * 1024 ** 3, under_new_cap=snapshot_bytes <= 16 * 1024 ** 3)
        before = free_gb()
        result['free_gb_before'] = before
        if before < 6:
            raise ValueError('NOT_ENOUGH_SPACE')
        if os.path.lexists(DRILL):
            raise ValueError('DRILL_DIR_EXISTS')
        os.mkdir(DRILL, 0o700)
        made = True
        os.chown(DRILL, st.st_uid, st.st_gid)
        os.chmod(DRILL, 0o700)
        result['runs'] = {}
        for label, image in IMAGES:
            result['runs'][label] = drill(label, image, archive, st.st_uid, kst_date)
            for name in os.listdir(DRILL):
                shutil.rmtree(os.path.join(DRILL, name), ignore_errors=True)
        runs = result['runs']
        result['ok'] = runs['new']['status'] == 'verified' and runs['new']['exit'] == 0
    except Exception as error:
        result['error'] = str(error) if isinstance(error, ValueError) and re.fullmatch(r'[A-Z_]{1,40}', str(error)) else type(error).__name__
    finally:
        if made and os.path.isdir(DRILL) and not os.path.islink(DRILL):
            shutil.rmtree(DRILL, ignore_errors=True)
        result['drill_dir_removed'] = not os.path.lexists(DRILL)
        result['free_gb_after'] = free_gb()
        print('NAVER_RESTORE_DRILL_V1=' + json.dumps(result, sort_keys=True, ensure_ascii=True, separators=(',', ':')))


if __name__ == '__main__':
    main()
