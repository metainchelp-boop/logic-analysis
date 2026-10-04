"""읽기 전용 검증판 안내 문구의 닫힌 경계. DB·운영 계정·외부 네트워크 없음."""
from pathlib import Path
import unittest

PAGE = Path(__file__).resolve().parents[2] / 'backend/naver_page'


class OwnerScreenCopyTest(unittest.TestCase):
    def test_first_input_and_unchecked_empty_states_do_not_claim_completion(self):
        source = (PAGE / 'app.js').read_text()
        html = (PAGE / 'index.html').read_text()
        self.assertIn("b.stage_state === 'held'", source)
        self.assertIn('계약 단계 목록을 확인 중이라 아직 광고주를 표시하지 않았습니다', source)
        self.assertIn('아직 점검 결과가 충분하지 않아 문제 여부를 판단할 수 없습니다', source)
        self.assertNotIn('오늘은 들어가 볼 광고주가 없습니다', source)
        self.assertNotIn('모든 광고주의 네이버 광고 계정을 대신 점검했습니다', html)
        self.assertNotIn('오늘 아침 점검', source)

    def test_login_help_uses_separate_naver_menu(self):
        source = (PAGE / 'app.js').read_text()
        self.assertNotIn('「광고 센터」', source)
        self.assertIn('「광고 스튜디오 › 네이버 관제(읽기 전용)」', source)

    def test_read_only_copy_distinguishes_scheduled_checks_and_disabled_alerts(self):
        source = (PAGE / 'app.js').read_text()
        self.assertIn('전일 실적은 한국시간 00:01부터 수집합니다', source)
        self.assertIn('10:00은 출근용 집계 목표', source)
        self.assertIn('미완료 계정은 이후에도 계속 수집합니다', source)
        self.assertIn('기존 이상 점검의 06:30~', source)
        self.assertIn('별도 경로입니다', source)
        self.assertIn('모든 계정의 10시 완료를 보장하지 않습니다', source)
        self.assertIn('읽기 전용 검증판에서는 점검 기준을 변경할 수 없습니다', source)
        self.assertIn('알림 전송·자동입찰은 꺼져 있습니다', source)
        self.assertIn("readOnly() ?", source)
        notice = (PAGE / 'index.html').read_text()
        self.assertIn('현황·이상 감지·모니터링 화면입니다', notice)
        self.assertIn('기존 담당 권한 범위의 네이버 원천 수치만 보이며', notice)
        self.assertIn('실적일과 수집 시각은 다릅니다', notice)
        self.assertIn('자료 미확인은 0이나 정상으로 표시하지 않습니다', notice)
        self.assertIn('광고 변경·자동입찰·외부 전송·업무 처리 기능은 열지 않습니다', notice)
        self.assertIn('여기서 승인·게시·전송하지 않습니다', notice)
        self.assertNotIn('대표 전용 읽기 검증판', notice)

    def test_legacy_stage_block_does_not_claim_stage_still_excludes_linking(self):
        source = (PAGE / 'app.js').read_text()
        self.assertNotIn('현재 진행 단계는 연결 확정 대상이 아닙니다', source)
        self.assertIn('전산 업무 단계만으로 연결을 제외하지 않습니다', source)

    def test_current_collection_and_report_copy_does_not_reintroduce_legacy_gates(self):
        source = (PAGE / 'app.js').read_text()
        html = (PAGE / 'index.html').read_text()
        for old in ('확인 전에는 자동화·광고주 보고서가 켜지지 않습니다', '그 외·수동 제외 계정',
                    '자동화·광고주 보고서가 켜질 수 있습니다', '계약 종료 후 14일이 지나 연결을 확정할 수 없습니다'):
            self.assertFalse(old in source + html, old)
        self.assertIn('현재 관리 중인 확정 업체의 보고서는 자동 생성', html)
        self.assertIn('현재 이관 계정의 비관리 주간 관찰은 별도', html)
        self.assertIn('그 외 이관 계정은', html)
        self.assertIn('이전 수동 제외 기록', source)


if __name__ == '__main__':
    unittest.main()
