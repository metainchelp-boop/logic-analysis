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

    def test_network_failure_projection_keeps_fixed_kind_phase_step_and_bounded_timings(self):
        messages = [
            'WARNING naver_engine.morning morning_network_failure kind=DNS phase=OPEN '
            'step=CAMPAIGNS request_elapsed_ms=8500 remaining_ms=1500',
            'WARNING naver_engine.read naver_network_failure kind=DEADLINE phase=BODY '
            'step=STATS request_elapsed_ms=20000 remaining_ms=0']
        raw = b'\n'.join(('2026-10-08T01:00:00Z '+message).encode() for message in messages)
        result = M.log_projection(raw, source='docker', unit='engine')
        self.assertEqual(result['unrecognized_entries'], 0)
        self.assertEqual(result['events'], [
            dict(event='network_failure',network_kind='DEADLINE',phase='BODY',step='STATS',count=1,
                 latest_request_elapsed_ms=20000,latest_remaining_ms=0),
            dict(event='network_failure',network_kind='DNS',phase='OPEN',step='CAMPAIGNS',count=1,
                 latest_request_elapsed_ms=8500,latest_remaining_ms=1500)])
        self.assertEqual(result['templates']['categories']['morning_network_failure']['kinds'], {'DNS:OPEN:CAMPAIGNS':1})
        self.assertEqual(result['templates']['categories']['naver_network_failure']['kinds'], {'DEADLINE:BODY:STATS':1})
        for value in ('request_elapsed_ms=', 'remaining_ms='):
            self.assertNotIn(value, json.dumps(result))
        relay = M.log_projection(raw, source='docker', unit='relay')
        self.assertEqual(relay['events'], [])
        self.assertEqual(relay['templates']['categories'], {})

    def test_mutated_network_log_and_suffix_never_pass_full_match(self):
        good = ('WARNING naver_engine.morning morning_network_failure kind=TIMEOUT phase=BODY '
                'step=BIZMONEY request_elapsed_ms=20000 remaining_ms=0')
        invalid = [good+' PRIVATE', good.replace('TIMEOUT','PRIVATE'), good.replace('BODY','PRIVATE'),
                   good.replace('BIZMONEY','PRIVATE'), good.replace('20000','PRIVATE'),
                   good.replace('20000','-1'), good.replace('20000','123456789012345'),
                   good.replace('remaining_ms=0','remaining_ms=PRIVATE')]
        raw = b'\n'.join(('2026-10-08T01:00:00Z '+message).encode() for message in invalid)
        result = M.log_projection(raw, source='docker', unit='engine')
        self.assertEqual(result['events'], [])
        self.assertEqual(result['templates']['categories'], {})
        self.assertEqual(result['templates']['unmatched_entries'], 8)
        self.assertNotIn('PRIVATE', json.dumps(result))

    def test_journal_projection_accepts_the_same_bounded_network_template(self):
        message = ('WARNING naver_engine.morning morning_network_failure kind=UNRECOGNIZED '
                   'phase=UNRECOGNIZED step=UNRECOGNIZED request_elapsed_ms=0 remaining_ms=0')
        raw = json.dumps(dict(MESSAGE=message,__REALTIME_TIMESTAMP='1791421200000000')).encode()
        result = M.log_projection(raw, source='journal', unit='engine')
        self.assertEqual(result['events'], [dict(event='network_failure',network_kind='UNRECOGNIZED',
            phase='UNRECOGNIZED',step='UNRECOGNIZED',count=1,latest_request_elapsed_ms=0,latest_remaining_ms=0)])
