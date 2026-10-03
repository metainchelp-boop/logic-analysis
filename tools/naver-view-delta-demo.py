#!/usr/bin/env python3
"""변경분 갱신·이관 분류·상향 접기 화면의 loopback 합성 시연.

제품 엔진·중계·화면을 그대로 사용하며, 상향 대기 항목 두 건도 시험 자료다.

실행: PYTHONDONTWRITEBYTECODE=1 NODE_PATH=<기존 Playwright 경로> python3 tools/naver-view-delta-demo.py
표준 출력에 나온 /naver/ 주소만 연다. 실제 계정·네이버·운영 DB·자격을 읽지 않는다.
로컬 파일 잠금 환경과 분리한 메모리 SQLite fixture이며 운영 WAL 검증이 아니다.
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from naver_engine.tests.test_view_sections_screen import ViewSectionsScreenTest  # noqa: E402
from naver_engine.tests import test_web as TW  # noqa: E402


CONTROLS = r"""'use strict';
(function () {
  const panel = document.createElement('section');
  panel.setAttribute('aria-label', '합성 시험 제어');
  const label = document.createElement('strong');
  label.textContent = '시험 자료만 변경: ';
  panel.appendChild(label);
  const status = document.createElement('p');
  status.id = 'deltaDemoStatus'; status.setAttribute('role', 'status');
  [ ['add', '광고주 추가'], ['correct', '관제 금액 정정'], ['remove', '추가 광고주 제외'],
    ['inventory-correct', '이관 잔액 정정'], ['report-correct', '보고서 정정'],
    ['reports-shrink', '보고 마지막 페이지 소실'], ['org-stale', '조직 자료 낡음'],
    ['org-fresh', '조직 자료 복구'] ].forEach(function (item) {
    const button = document.createElement('button');
    button.type = 'button'; button.className = 'btn sm'; button.id = 'deltaDemo-' + item[0];
    button.textContent = item[1];
    button.addEventListener('click', async function () {
      button.disabled = true; status.textContent = '합성 저장 자료 변경 중';
      try {
        const response = await fetch('/__view_delta_test__/' + item[0], {method: 'POST', credentials: 'omit'});
        if (!response.ok) throw new Error('합성 자료 변경 실패');
        status.textContent = item[1] + ' 완료. 제품 화면의 변경 확인 단추를 눌러 비교하십시오. 네이버 요청은 없습니다.';
      } catch (_) { status.textContent = '합성 자료를 변경하지 못했습니다.'; }
      finally { button.disabled = false; }
    });
    panel.appendChild(button);
  });
  panel.appendChild(status);
  document.getElementById('syntheticNotice').after(panel);
})();
"""


class Demo(ViewSectionsScreenTest):
    def _handler(self):
        parent = super()._handler()
        class Handler(parent):
            def _send(self, status, headers, body):
                if status == 200 and b'id="syntheticNotice"' in body:
                    body = body.replace(b'</body>',
                        b'<script src="/__view_delta_demo_controls.js" defer></script></body>')
                return super()._send(status, headers, body)

            def _any(self):
                if self.path == '/__view_delta_demo_controls.js' and self.command == 'GET':
                    return self._send(200, (('Content-Type', 'application/javascript'),
                        ('Cache-Control', 'no-store')), CONTROLS.encode())
                return super()._any()
            do_GET = do_POST = do_HEAD = _any
        return Handler


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--staff', action='store_true', help='대표 대신 합성 직원으로 진입한다')
    parser.add_argument('--seconds', type=int, default=1800, help='1~3600초 뒤 자동 종료(기본 1800)')
    args = parser.parse_args()
    if not 1 <= args.seconds <= 3600:
        parser.error('--seconds는 1~3600이어야 합니다')
    os.environ['NAVER_VIEW_DELTA_MEMORY'] = '1'
    os.environ.pop('NAVER_VIEW_DELTA_BASELINE', None)
    test = Demo()
    try:
        test.setUp()
        test.entry_code = TW.tok(3 if args.staff else 1)
        print(json.dumps({'url': test.base + '/naver/', 'data': '시험 자료', 'store': 'memory-sqlite',
            'role': '합성 직원' if args.staff else '합성 대표', 'external_requests': 0,
            'expires_in_seconds': args.seconds}, ensure_ascii=False), flush=True)
        deadline = time.monotonic() + args.seconds
        while time.monotonic() < deadline:
            test.drain_controls()
            test.engine.handle_request()
    except KeyboardInterrupt:
        pass
    finally:
        test.doCleanups()
        if hasattr(test, 'dir'):
            test.tearDown()


if __name__ == '__main__':
    main()
