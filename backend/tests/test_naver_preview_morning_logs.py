"""상세 점검의 고정 원인 코드만 집계하며 자유 텍스트는 반환하지 않는다."""
import importlib.util
import json
from pathlib import Path
import unittest

SPEC = importlib.util.spec_from_file_location('morning_status', Path(__file__).parents[1]/'tools/naver_preview_collection_status.py')
M = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(M)


class MorningLogsTest(unittest.TestCase):
    def test_fixed_abort_causes_and_timestamps_only(self):
        stamp = '2026-10-08T01:00:00+00:00'
        entries = [(stamp, 'WARNING naver_engine.morning morning_abort code=REQUEST_DEADLINE '
                    f'cause={cause} calls=3 elapsed_ms=28500') for cause in ('SERVER','NETWORK','RATE')]
        result = M.log_categories(entries, 'engine')
        row = result['categories']['morning_abort']
        self.assertEqual(row['count'], 3)
        self.assertEqual(row['kinds'], {f'REQUEST_DEADLINE:{cause}':1 for cause in ('SERVER','NETWORK','RATE')})
        self.assertEqual(row['last_at'], stamp)
        self.assertNotIn('28500', json.dumps(result))

    def test_private_text_and_mutated_numeric_fields_are_never_returned(self):
        good = 'WARNING naver_engine.morning morning_abort code=REQUEST_DEADLINE cause=SERVER calls=3 elapsed_ms=28500'
        invalid = [good+' PRIVATE',good.replace('SERVER','PRIVATE'),good.replace('calls=3','calls=PRIVATE'),
                   good.replace('28500','-1')]
        result = M.log_categories([(None, message) for message in invalid], 'engine')
        self.assertEqual(result['categories'], {})
        self.assertEqual(result['unmatched_entries'], 4)
        self.assertNotIn('PRIVATE', json.dumps(result))
