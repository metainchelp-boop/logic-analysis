"""실제 파일 DB의 읽기 스냅숏 시험. 잠금 오류를 건너뛰거나 우회하지 않는다."""
from copy import deepcopy

from naver_engine.tests import test_web as TW


class ViewSyncStorageTest(TW.WebBase):
    def test_live_file_reader_keeps_one_snapshot_while_writer_publishes(self):
        with TW.S.open_reader(self.path) as reader:
            with reader.read_snapshot():
                original = reader.org_current()
                self.fc.advance(1)
                body = deepcopy(original["body"])
                body["generated_at"] = self.fc.now().isoformat()
                body["employees"][0]["name"] = "합성 변경 대표"
                self.st.record_org(body, self.fc.now())
                self.assertEqual(reader.org_current(), original)
            self.assertNotEqual(reader.org_current(), original)

    def test_board_opt_in_uses_file_snapshot_and_preserves_legacy_response(self):
        original = self.get("/board", 0)[1]
        status, first = self.get("/board", 0, query="view_sync=1")
        self.assertEqual(status, 200)
        self.assertEqual(first["data"], original)
        status, second = self.get("/board", 0, query="view_sync=1&view_cursor=" + first["cursor"])
        self.assertEqual(status, 200)
        self.assertEqual(second["mode"], "unchanged")
