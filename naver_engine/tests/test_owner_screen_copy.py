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
        self.assertIn('현재 시간대에는 아직 수집·점검 전일 수 있습니다', source)
        self.assertIn('읽기 전용 검증판에서는 점검 기준을 변경할 수 없습니다', source)
        self.assertIn('알림 전송·자동입찰은 꺼져 있습니다', source)
        self.assertIn("readOnly() ?", source)
        notice = (PAGE / 'index.html').read_text()
        self.assertIn('읽기 전용 검증판입니다. 기존 권한 범위 안의 자료만 보이며', notice)
        self.assertNotIn('대표 전용 읽기 검증판', notice)


if __name__ == '__main__':
    unittest.main()
