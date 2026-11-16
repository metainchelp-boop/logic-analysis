"""Synthetic metadata contracts: observation never grants archive eligibility."""
import copy
import importlib.util
import os
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch


SPEC = importlib.util.spec_from_file_location(
    'backup_metadata_fixture', Path(__file__).with_name('test_backup_status.py'))
T = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(T)
B = T.B


class MetadataContractTest(T.Fixture):
    def building(self, folder='local', suffix='abcdefgh', mode=0o700):
        result = self.root / folder / ('.building-' + suffix)
        result.mkdir(mode=mode)
        result.chmod(mode)
        return result

    def child(self, parent, name='snapshot.sqlite', data=b'synthetic'):
        result = parent / name
        result.write_bytes(data)
        result.chmod(0o600)
        return result

    def assert_unknown(self, result, reason):
        self.assertEqual((result['status'], result['reason']), ('incomplete', reason))
        for key in ('file_count', 'logical_bytes', 'allocated_bytes',
                    'oldest_filename_kst_day', 'newest_filename_kst_day'):
            self.assertIsNone(result[key])
        metadata = result['metadata']
        self.assertEqual((metadata['status'], metadata['reason']), ('incomplete', reason))
        self.assertTrue(all(value is None for key, value in metadata.items()
                            if key not in ('status', 'reason')))
        B.validate_metadata(metadata)

    def test_mixed_entries_are_closed_metadata_without_contents_or_recursive_open(self):
        archive = self.file(data=T.CANARY.encode())
        building = self.building()
        for name in ('snapshot.sqlite', 'packed.zip', 'encrypted.cms', T.CANARY):
            self.child(building, name, T.CANARY.encode())
        nested = building / 'nested-private'
        nested.mkdir(mode=0o700)
        self.child(nested, data=T.CANARY.encode())
        (building / 'child-link').symlink_to(archive)
        unrelated = self.root / 'local' / 'unrelated-private'
        unrelated.mkdir(mode=0o700)
        self.child(unrelated, data=T.CANARY.encode())
        self.child(self.root / 'local', T.CANARY)
        (self.root / 'local' / 'root-link').symlink_to(unrelated)
        os.mkfifo(self.root / 'local' / 'fifo-private', 0o600)
        os.utime(building, ns=(1762214400123456789, 1762214400123456789))
        original_open = os.open
        opened = []

        def directories_only(path, flags, *args, **kwargs):
            self.assertTrue(flags & os.O_DIRECTORY)
            if path != '/':
                self.assertTrue(flags & os.O_NOFOLLOW)
            opened.append(path)
            return original_open(path, flags, *args, **kwargs)

        with patch.object(B.os, 'open', side_effect=directories_only), \
                patch('builtins.open', side_effect=AssertionError('content opened')):
            result = B.summarize_folder('local', 'zip')
        self.assertEqual(result['reason'], 'UNEXPECTED_ENTRY')
        self.assertIsNone(result['file_count'])
        metadata = B.validate_metadata(result['metadata'])
        self.assertEqual(metadata['status'], 'observed')
        self.assertEqual((metadata['root_entries'], metadata['child_entries']), (6, 6))
        self.assertEqual(metadata['building_directories_scanned'], 1)
        self.assertEqual(metadata['unscanned_directory_count'], 2)
        self.assertIsNone(metadata['unscanned_subtree_bytes'])
        self.assertEqual(metadata['building_oldest_mtime_utc'], '2025-11-04T00:00:00.123456+00:00')
        self.assertEqual(metadata['building_newest_mtime_utc'], metadata['building_oldest_mtime_utc'])
        for name in ('unrelated-private', 'nested-private', 'root-link', 'child-link'):
            self.assertNotIn(name, opened)
        encoded = B.canonical(result)
        for private in (T.CANARY, str(self.root), '.building-', archive.name,
                        'snapshot.sqlite', 'packed.zip', 'encrypted.cms', 'unrelated-private'):
            self.assertNotIn(private, encoded)

    def test_one_entry_budget_counts_children_and_both_folders(self):
        building = self.building()
        self.child(building)
        self.child(building, 'packed.zip')
        self.file(folder='outgoing', extension='cms')
        budget = B.MetadataBudget()
        with patch.object(B, 'MAX_ENTRIES', 3):
            local = B.summarize_folder('local', 'zip', budget=budget)
            outgoing = B.summarize_folder('outgoing', 'cms', budget=budget)
        self.assertEqual(local['metadata']['status'], 'observed')
        self.assertEqual((local['metadata']['root_entries'], local['metadata']['child_entries']), (1, 2))
        self.assert_unknown(outgoing, 'ENTRY_LIMIT')
        self.assertEqual(budget.entries, 3)

    def test_building_limit_is_shared_and_seventeenth_directory_is_not_opened(self):
        for number in range(17):
            self.building('local' if number < 8 else 'outgoing', '%08d' % number)
        original_open = os.open
        opened = []

        def track(path, *args, **kwargs):
            if str(path).startswith('.building-'):
                opened.append(path)
            return original_open(path, *args, **kwargs)

        budget = B.MetadataBudget()
        with patch.object(B.os, 'open', side_effect=track):
            local = B.summarize_folder('local', 'zip', budget=budget)
            outgoing = B.summarize_folder('outgoing', 'cms', budget=budget)
        self.assertEqual(local['metadata']['building_directories_scanned'], 8)
        self.assert_unknown(outgoing, 'BUILDING_LIMIT')
        self.assertEqual(budget.buildings, 16)
        self.assertEqual(len(opened), 16)
        self.assertNotIn('.building-00000016', opened)

    def test_nonproducer_directory_mode_owner_and_names_are_never_opened(self):
        wrong_mode = self.building(suffix='mode0000', mode=0o755)
        wrong_owner = self.building(suffix='owner000')
        invalid_names = ('.building-ABCDEFGH', '.building-short', '.building-abcdefghi')
        for name in invalid_names:
            (self.root / 'local' / name).mkdir(mode=0o700)
        for directory in (wrong_mode, wrong_owner):
            self.child(directory, data=T.CANARY.encode())
        original_stat, original_open = os.stat, os.open
        opened = []

        def owner_changed(path, *args, **kwargs):
            info = original_stat(path, *args, **kwargs)
            if path == wrong_owner.name:
                info = SimpleNamespace(**{key: getattr(info, key) for key in dir(info)
                                          if key.startswith('st_')})
                info.st_uid = B.ENGINE_UID + 1
            return info

        def track(path, *args, **kwargs):
            opened.append(path)
            return original_open(path, *args, **kwargs)

        with patch.object(B.os, 'stat', side_effect=owner_changed), \
                patch.object(B.os, 'open', side_effect=track):
            result = B.summarize_folder('local', 'zip')
        metadata = B.validate_metadata(result['metadata'])
        self.assertEqual(metadata['building_directories_scanned'], 0)
        self.assertEqual(metadata['child_entries'], 0)
        self.assertEqual(metadata['unscanned_directory_count'], 5)
        self.assertIsNone(metadata['unscanned_subtree_bytes'])
        for name in (*invalid_names, wrong_mode.name, wrong_owner.name):
            self.assertNotIn(name, opened)

    def test_shared_deadline_does_not_restart_for_an_empty_second_folder(self):
        clock = [0]
        budget = B.MetadataBudget(monotonic=lambda: clock[0])
        self.assertEqual(B.summarize_folder('local', 'zip', budget=budget)['status'], 'observed')
        clock[0] = B.METADATA_SECONDS
        self.assert_unknown(B.summarize_folder('outgoing', 'cms', budget=budget), 'TIME_LIMIT')

    def test_late_child_addition_invalidates_entire_metadata_observation(self):
        building = self.building()
        child = self.child(building)
        original_stat = os.stat
        calls = 0

        def add_after_child_recheck(path, *args, **kwargs):
            nonlocal calls
            info = original_stat(path, *args, **kwargs)
            if path == child.name:
                calls += 1
                if calls == 2:
                    self.child(building, 'packed.zip')
                    # Make the directory change deterministic on coarse filesystems.
                    os.utime(building, ns=(info.st_mtime_ns + 2000000000,
                                          info.st_mtime_ns + 2000000000))
            return info

        with patch.object(B.os, 'stat', side_effect=add_after_child_recheck):
            result = B.summarize_folder('local', 'zip')
        self.assertEqual(calls, 2)
        self.assert_unknown(result, 'CHANGED')

    def test_building_replacement_between_stat_and_open_is_unknown(self):
        building = self.building()
        self.child(building)
        original_open = os.open
        replaced = False

        def replace(path, *args, **kwargs):
            nonlocal replaced
            if path == building.name and not replaced:
                replaced = True
                building.rename(self.base / 'saved-original')
                building.mkdir(mode=0o700)
            return original_open(path, *args, **kwargs)

        with patch.object(B.os, 'open', side_effect=replace):
            result = B.summarize_folder('local', 'zip')
        self.assertTrue(replaced)
        self.assert_unknown(result, 'CHANGED')

    def test_deadline_during_recheck_discards_partial_counters(self):
        building = self.building()
        child = self.child(building)
        clock = [0]
        budget = B.MetadataBudget(monotonic=lambda: clock[0])
        original_stat = os.stat
        calls = 0

        def expire(path, *args, **kwargs):
            nonlocal calls
            info = original_stat(path, *args, **kwargs)
            if path == child.name:
                calls += 1
                if calls == 2:
                    clock[0] = B.METADATA_SECONDS
            return info

        with patch.object(B.os, 'stat', side_effect=expire):
            result = B.summarize_folder('local', 'zip', budget=budget)
        self.assert_unknown(result, 'TIME_LIMIT')

    def test_hardlinks_count_entries_but_attribute_inode_bytes_once(self):
        building = self.building()
        first = self.child(self.root / 'local', 'unknown-regular', b'123456789')
        os.link(first, building / 'snapshot.sqlite')
        os.link(first, building / 'packed.zip')
        result = B.summarize_folder('local', 'zip')
        metadata = B.validate_metadata(result['metadata'])
        self.assertIsNone(result['logical_bytes'])
        self.assertEqual((metadata['root_entries'], metadata['child_entries']), (2, 2))
        self.assertEqual(metadata['duplicate_inode_count'], 2)
        rows = [row for name in ('root_buckets', 'child_buckets') for row in metadata[name].values()]
        self.assertEqual(sum(row['regular_logical_bytes'] for row in rows), 9)
        self.assertEqual(sum(row['inode_allocated_bytes'] for row in rows),
                         (first.stat().st_blocks + building.stat().st_blocks) * 512)
        self.assertEqual(metadata['root_buckets']['other_regular']['regular_logical_bytes'], 9)
        self.assertEqual(metadata['child_buckets']['snapshot_regular']['regular_logical_bytes'], 0)
        self.assertEqual(metadata['child_buckets']['packed_regular']['regular_logical_bytes'], 0)

    def test_date_and_extension_violations_never_make_archive_totals_known(self):
        self.file(day='20261302T160000Z')
        result = B.summarize_folder('local', 'zip')
        self.assertEqual(result['reason'], 'UNAVAILABLE')
        self.assertIsNone(result['file_count'])
        self.assertEqual(B.validate_metadata(result['metadata'])['archive_violations']['date'], 1)
        self.file(folder='outgoing', extension='zip')
        outgoing = B.summarize_folder('outgoing', 'cms')
        self.assertEqual(outgoing['reason'], 'UNEXPECTED_ENTRY')
        self.assertIsNone(outgoing['logical_bytes'])
        self.assertEqual(outgoing['metadata']['archive_violations']['extension'], 1)

    def test_closed_validator_rejects_types_counts_times_and_cross_bucket_overflow(self):
        building = self.building()
        self.child(building)
        self.child(self.root / 'local', 'unknown-regular')
        metadata = B.summarize_folder('local', 'zip')['metadata']
        B.validate_metadata(metadata)
        edits = (
            lambda value: value.update(root_entries=True),
            lambda value: value.update(extra=T.CANARY),
            lambda value: value['root_buckets'].update(extra={}),
            lambda value: value['child_buckets']['snapshot_regular'].update(entries=2),
            lambda value: value['archive_violations'].update(name=True),
            lambda value: value.update(unscanned_subtree_bytes=None),
            lambda value: value.update(building_oldest_mtime_utc='2026-01-01T00:00:00+09:00'),
            lambda value: value.update(building_oldest_mtime_utc='2099-01-01T00:00:00+00:00'),
            lambda value: value['root_buckets']['other_regular'].update(regular_logical_bytes=-1),
            lambda value: value['root_buckets']['other_regular'].update(regular_logical_bytes=2 ** 63),
        )
        for number, edit in enumerate(edits):
            with self.subTest(case=number):
                value = copy.deepcopy(metadata)
                edit(value)
                with self.assertRaises((B.Refused, ValueError, TypeError)):
                    B.validate_metadata(value)
        for field in ('regular_logical_bytes', 'inode_allocated_bytes'):
            value = copy.deepcopy(metadata)
            value['root_buckets']['other_regular'][field] = 2 ** 62
            value['child_buckets']['snapshot_regular'][field] = 2 ** 62
            with self.subTest(overflow=field), self.assertRaises(B.Refused):
                B.validate_metadata(value)
        value = B.empty_metadata('CHANGED')
        value['root_entries'] = 0
        with self.assertRaises(B.Refused):
            B.validate_metadata(value)

    def test_report_cannot_promote_diagnostic_or_reset_global_entry_limit(self):
        for folder in ('local', 'outgoing'):
            building = self.building(folder)
            self.child(building)
        report = B.receipt()
        for folder, extension in (('local', 'zip'), ('outgoing', 'cms')):
            report[folder] = B.summarize_folder(folder, extension)
        B.validate_report(report)
        with patch.object(B, 'MAX_ENTRIES', 3), self.assertRaises(B.Refused):
            B.validate_report(report)
        promoted = copy.deepcopy(report)
        promoted['local'].update(status='observed', reason='OK', file_count=0,
                                 logical_bytes=0, allocated_bytes=0)
        with self.assertRaises(B.Refused):
            B.validate_report(promoted)


if __name__ == '__main__':
    unittest.main()
