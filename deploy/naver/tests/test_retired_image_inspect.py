import contextlib
import copy
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location('retired_image_inspect', Path(__file__).parents[1] / 'retired_image_inspect.py')
R = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(R)
CANARY = 'PRIVATE_SYNTHETIC_CANARY'
EXTRA_IMAGE = 'sha256:' + 'e' * 64
CONTAINER = 'c' * 64


def image(image_id, n, **updates):
    result = dict(id=image_id, size=1024 + n, tags=['private/' + CANARY + ':tag' + str(n)],
                  digests=['private/' + CANARY + '@sha256:' + '%064x' % (100 + n)],
                  parent='', rootfs={'Type': 'layers', 'Layers': ['sha256:' + '%064x' % (n + 1)]})
    result.update(updates)
    return result


def fixture():
    images = {image_id: image(image_id, n) for n, (_, image_id) in enumerate(R.CANDIDATES)}
    images[EXTRA_IMAGE] = image(EXTRA_IMAGE, 90)
    return dict(info=dict(id=CANARY, driver='overlay2', driver_status=[['Root', CANARY]],
                          root='/private/' + CANARY, server_version='28.0.0'),
                images=images, containers={}, ancestors={image_id: [] for _, image_id in R.CANDIDATES})


class FakeDocker:
    def __init__(self, first=None, second=None, transform=None):
        self.first = fixture() if first is None else first
        self.second = copy.deepcopy(self.first) if second is None else second
        self.current = None
        self.rounds = 0
        self.commands = []
        self.transform = transform

    def __call__(self, command):
        self.commands.append(command)
        if not R.command_allowed(command):
            raise AssertionError('unexpected command')
        args = command[len(R.DOCKER):]
        if args == ('info', '--format', R.INFO_FORMAT):
            self.current = self.first if self.rounds == 0 else self.second
            self.rounds += 1
            raw = R.canonical(self.current['info']).encode()
        elif args == R.IMAGE_LIST:
            raw = '\n'.join(self.current['images']).encode()
        elif args == R.CONTAINER_LIST:
            raw = '\n'.join(self.current['containers']).encode()
        elif args[:len(R.CONTAINER_LIST)] == R.CONTAINER_LIST:
            target = args[-1].split('=', 1)[1]
            raw = '\n'.join(self.current['ancestors'][target]).encode()
        elif args[:4] == ('image', 'inspect', '--format', R.IMAGE_FORMAT):
            raw = '\n'.join(R.canonical(self.current['images'][key]) for key in args[4:]).encode()
        elif args[:4] == ('container', 'inspect', '--format', R.CONTAINER_FORMAT):
            raw = '\n'.join(R.canonical(self.current['containers'][key]) for key in args[4:]).encode()
        else:
            raise AssertionError('unexpected command')
        return self.transform(args, raw) if self.transform is not None else raw


class CollectionTests(unittest.TestCase):
    def assert_incomplete(self, report, reason):
        self.assertEqual(report['status'], 'INCOMPLETE')
        self.assertEqual(report['reason'], reason)
        self.assertIsNone(report['docker'])
        self.assertTrue(all(c['status'] == 'UNKNOWN' and c['image'] is None and c['references'] is None for c in report['candidates']))
        self.assertIs(R.validate_report(report), report)
        self.assertNotIn(CANARY, R.canonical(report))

    def test_stable_whole_inventory_is_redacted_not_delete_authorized(self):
        runner = FakeDocker()
        report = R.collect_report(runner)
        self.assertEqual(report['status'], 'COMPLETE_STABLE')
        self.assertEqual(report['reason'], 'OK')
        self.assertEqual(report['docker']['image_count'], 6)
        self.assertFalse(report['docker']['parent_relation_complete'])
        self.assertEqual(report['docker']['inventory_scope'], 'ACTIVE_DOCKER_IMAGE_STORE_ONLY')
        self.assertFalse(report['delete_authorized'])
        self.assertFalse(report['backup_currently_verified'])
        self.assertIsNone(report['reclaimable_bytes'])
        self.assertEqual(runner.rounds, 2)
        self.assertTrue(all(c['status'] == 'NO_REFERENCES_OBSERVED' for c in report['candidates']))
        self.assertEqual(report['candidates'][0]['image']['tag_count'], 1)
        self.assertNotIn(CANARY, R.canonical(report))
        self.assertNotIn(EXTRA_IMAGE, R.canonical(report))
        self.assertIs(R.validate_report(report), report)

    def test_exited_unclassified_container_is_a_direct_reference(self):
        value = fixture()
        target = R.CANDIDATES[0][1]
        value['containers'][CONTAINER] = dict(id=CONTAINER, image=target, state='exited')
        value['ancestors'][target] = [CONTAINER]
        report = R.collect_report(FakeDocker(value))
        candidate = report['candidates'][0]
        self.assertEqual(candidate['status'], 'REFERENCES_OBSERVED')
        self.assertEqual(candidate['references']['direct_container_count'], 1)
        self.assertEqual(candidate['references']['ancestor_container_count'], 1)
        self.assertNotIn(CONTAINER, R.canonical(report))

    def test_running_paused_restarting_and_dead_states_remain_references(self):
        for state in R.STATES:
            with self.subTest(state=state):
                value = fixture()
                target = R.CANDIDATES[1][1]
                value['containers'][CONTAINER] = dict(id=CONTAINER, image=target, state=state)
                value['ancestors'][target] = [CONTAINER]
                report = R.collect_report(FakeDocker(value))
                self.assertEqual(report['candidates'][1]['references']['direct_container_count'], 1)

    def test_ancestor_only_container_is_preserved(self):
        value = fixture()
        target = R.CANDIDATES[0][1]
        value['containers'][CONTAINER] = dict(id=CONTAINER, image=EXTRA_IMAGE, state='exited')
        value['ancestors'][target] = [CONTAINER]
        candidate = R.collect_report(FakeDocker(value))['candidates'][0]
        self.assertEqual(candidate['status'], 'REFERENCES_OBSERVED')
        self.assertEqual(candidate['references']['direct_container_count'], 0)
        self.assertEqual(candidate['references']['ancestor_container_count'], 1)

    def test_reference_mismatch_never_turns_into_zero(self):
        for missing_direct in (True, False):
            with self.subTest(missing_direct=missing_direct):
                value = fixture()
                target = R.CANDIDATES[0][1]
                if missing_direct:
                    value['containers'][CONTAINER] = dict(id=CONTAINER, image=target, state='exited')
                else:
                    value['ancestors'][target] = [CONTAINER]
                self.assert_incomplete(R.collect_report(FakeDocker(value)), 'REFERENCE_MISMATCH')

    def test_missing_actual_container_image_refuses_inventory(self):
        value = fixture()
        value['containers'][CONTAINER] = dict(id=CONTAINER, image='sha256:' + 'f' * 64, state='running')
        self.assert_incomplete(R.collect_report(FakeDocker(value)), 'MISSING_CONTAINER_IMAGE')

    def test_absence_is_only_about_active_store(self):
        value = fixture()
        del value['images'][R.CANDIDATES[0][1]]
        runner = FakeDocker(value)
        report = R.collect_report(runner)
        self.assertEqual(report['status'], 'COMPLETE_STABLE')
        self.assertEqual(report['candidates'][0]['status'], 'ABSENT_IN_ACTIVE_STORE')
        self.assertIsNone(report['candidates'][0]['image'])
        self.assertIsNone(report['candidates'][0]['references'])
        self.assertFalse(any(c[-1] == 'ancestor=' + R.CANDIDATES[0][1] for c in runner.commands))

    def test_empty_active_store_is_complete(self):
        value = fixture()
        value['images'] = {}
        report = R.collect_report(FakeDocker(value))
        self.assertEqual(report['status'], 'COMPLETE_STABLE')
        self.assertEqual(report['docker']['image_count'], 0)
        self.assertTrue(all(c['status'] == 'ABSENT_IN_ACTIVE_STORE' for c in report['candidates']))

    def test_parent_prefix_equal_and_shared_are_distinct(self):
        target = R.CANDIDATES[0][1]
        for mode, field, state in (
            ('parent', 'parent_child_image_count', 'REFERENCES_OBSERVED'),
            ('prefix', 'layer_prefix_image_count', 'REFERENCES_OBSERVED'),
            ('equal', 'equal_layers_image_count', 'REFERENCES_OBSERVED'),
            ('shared', 'shared_layers_image_count', 'NO_REFERENCES_OBSERVED'),
        ):
            with self.subTest(mode=mode):
                value = fixture()
                layers = value['images'][target]['rootfs']['Layers']
                if mode == 'parent':
                    value['images'][EXTRA_IMAGE]['parent'] = target
                elif mode == 'prefix':
                    value['images'][EXTRA_IMAGE]['rootfs']['Layers'] = layers + ['sha256:' + 'a' * 64]
                elif mode == 'equal':
                    value['images'][EXTRA_IMAGE]['rootfs']['Layers'] = layers[:]
                else:
                    value['images'][EXTRA_IMAGE]['rootfs']['Layers'] = ['sha256:' + 'a' * 64] + layers
                candidate = R.collect_report(FakeDocker(value))['candidates'][0]
                self.assertEqual(candidate['references'][field], 1)
                self.assertEqual(candidate['status'], state)

    def test_missing_legacy_parent_is_null_not_proven_zero(self):
        value = fixture()
        value['images'][R.CANDIDATES[0][1]]['parent'] = None
        report = R.collect_report(FakeDocker(value))
        self.assertEqual(report['status'], 'COMPLETE_STABLE')
        self.assertIsNone(report['candidates'][0]['image']['parent_present'])
        self.assertTrue(all(c['references']['parent_child_image_count'] is None for c in report['candidates']))
        self.assertFalse(report['docker']['parent_relation_complete'])

    def test_known_positive_parent_survives_other_missing_legacy_fields(self):
        value = fixture()
        target = R.CANDIDATES[0][1]
        value['images'][EXTRA_IMAGE]['parent'] = target
        value['images'][R.CANDIDATES[1][1]]['parent'] = None
        report = R.collect_report(FakeDocker(value))
        candidate = report['candidates'][0]
        self.assertEqual(candidate['status'], 'REFERENCES_OBSERVED')
        self.assertEqual(candidate['references']['parent_child_image_count'], 1)
        self.assertEqual(candidate['references']['layer_prefix_image_count'], 0)
        self.assertEqual(candidate['references']['direct_container_count'], 0)
        self.assertIsNone(report['candidates'][1]['references']['parent_child_image_count'])

    def test_nonlocal_parent_does_not_claim_complete_ancestry(self):
        value = fixture()
        value['images'][R.CANDIDATES[0][1]]['parent'] = 'sha256:' + 'f' * 64
        report = R.collect_report(FakeDocker(value))
        self.assertEqual(report['status'], 'COMPLETE_STABLE')
        self.assertTrue(report['candidates'][0]['image']['parent_present'])
        self.assertFalse(report['docker']['parent_relation_complete'])

    def test_empty_layer_arrays_do_not_match_every_image_as_descendant(self):
        value = fixture()
        target = R.CANDIDATES[0][1]
        value['images'][target]['rootfs']['Layers'] = []
        report = R.collect_report(FakeDocker(value))
        self.assertEqual(report['status'], 'COMPLETE_STABLE')
        candidate = report['candidates'][0]
        self.assertEqual(candidate['image']['layer_count'], 0)
        self.assertEqual(candidate['references']['layer_prefix_image_count'], 0)
        self.assertEqual(candidate['references']['shared_layers_image_count'], 0)
        self.assertEqual(candidate['references']['equal_layers_image_count'], 0)

    def test_missing_layer_metadata_is_unknown_not_zero(self):
        for rootfs in (None, {}, {'Type': 'layers'}, {'Type': 'other', 'Layers': []}):
            with self.subTest(rootfs=rootfs):
                value = fixture()
                value['images'][EXTRA_IMAGE]['rootfs'] = rootfs
                self.assert_incomplete(R.collect_report(FakeDocker(value)), 'INVALID_METADATA')

    def test_null_tags_and_digests_mean_no_named_references(self):
        value = fixture()
        value['images'][R.CANDIDATES[0][1]].update(tags=None, digests=None)
        item = R.collect_report(FakeDocker(value))['candidates'][0]['image']
        self.assertEqual(item['tag_count'], 0)
        self.assertEqual(item['digest_count'], 0)
        self.assertEqual(item['tags_sha256'], R.digest([]))

    def test_second_observation_detects_changes_to_all_relevant_metadata(self):
        cases = ('server', 'driver', 'driver_status', 'root', 'version', 'new_image', 'size',
                 'tag', 'digest', 'parent', 'layer', 'container_state', 'ancestor')
        for change in cases:
            with self.subTest(change=change):
                first = fixture()
                target = R.CANDIDATES[0][1]
                first['containers'][CONTAINER] = dict(id=CONTAINER, image=EXTRA_IMAGE, state='running')
                second = copy.deepcopy(first)
                item = second['images'][target]
                if change == 'server': second['info']['id'] += '-changed'
                elif change == 'driver': second['info']['driver'] = 'overlayfs'
                elif change == 'driver_status': second['info']['driver_status'].append(['driver-type', 'containerd'])
                elif change == 'root': second['info']['root'] += '-changed'
                elif change == 'version': second['info']['server_version'] = '29.0.0'
                elif change == 'new_image': second['images']['sha256:' + 'f' * 64] = image('sha256:' + 'f' * 64, 120)
                elif change == 'size': item['size'] += 1
                elif change == 'tag': item['tags'].append(CANARY + ':different')
                elif change == 'digest': item['digests'].append(CANARY + '@sha256:' + 'f' * 64)
                elif change == 'parent': item['parent'] = EXTRA_IMAGE
                elif change == 'layer': item['rootfs']['Layers'].append('sha256:' + 'a' * 64)
                elif change == 'container_state': second['containers'][CONTAINER]['state'] = 'exited'
                elif change == 'ancestor': second['ancestors'][target] = [CONTAINER]
                report = R.collect_report(FakeDocker(first, second))
                self.assertEqual(report['status'], 'CHANGED')
                self.assertEqual(report['reason'], 'INVENTORY_CHANGED')
                self.assertTrue(all(c['status'] == 'UNKNOWN' for c in report['candidates']))
                self.assertIsNone(report['docker'])
                self.assertNotIn(CANARY, R.canonical(report))

    def test_order_changes_do_not_create_false_inventory_changes(self):
        first = fixture()
        target = R.CANDIDATES[0][1]
        first['images'][target]['tags'].append('private/other:tag')
        first['info']['driver_status'].append(['Type', 'overlay2'])
        second = copy.deepcopy(first)
        second['images'] = dict(reversed(list(second['images'].items())))
        second['images'][target]['tags'].reverse()
        second['info']['driver_status'].reverse()
        self.assertEqual(R.collect_report(FakeDocker(first, second))['status'], 'COMPLETE_STABLE')

    def test_multi_tag_repeated_image_ids_are_normalized(self):
        def transform(args, raw):
            return raw + b'\n' + raw.splitlines()[0] if args == R.IMAGE_LIST else raw
        self.assertEqual(R.collect_report(FakeDocker(transform=transform))['status'], 'COMPLETE_STABLE')

    def test_bad_list_identity_truncation_and_duplicate_container_are_rejected(self):
        cases = [
            (R.IMAGE_LIST, b'sha256:123', 'INVALID_METADATA'),
            (R.IMAGE_LIST, b'\xff', 'INVALID_METADATA'),
            (R.CONTAINER_LIST, (CONTAINER + '\n' + CONTAINER).encode(), 'INVALID_METADATA'),
            (R.CONTAINER_LIST, b'\n', 'INVALID_METADATA'),
        ]
        for command, replacement, reason in cases:
            with self.subTest(replacement=replacement):
                self.assert_incomplete(R.collect_report(FakeDocker(transform=lambda args, raw: replacement if args == command else raw)), reason)

    def test_inspection_identity_mismatch_and_missing_object_fail_closed(self):
        for mode in ('wrong', 'missing', 'duplicate'):
            with self.subTest(mode=mode):
                def transform(args, raw):
                    if args[:2] != ('image', 'inspect'):
                        return raw
                    lines = raw.splitlines()
                    if mode == 'missing':
                        return b'\n'.join(lines[:-1])
                    if mode == 'duplicate':
                        return b'\n'.join([lines[0]] * len(lines))
                    value = json.loads(lines[0])
                    value['id'] = 'sha256:' + 'f' * 64
                    return b'\n'.join([R.canonical(value).encode()] + lines[1:])
                self.assert_incomplete(R.collect_report(FakeDocker(transform=transform)), 'IDENTITY_MISMATCH')

    def test_limits_on_lists_metadata_and_bytes_are_enforced(self):
        for target, maximum, expected in [('MAX_IMAGES', 5, 'ITEM_LIMIT'), ('MAX_REFS', 0, 'ITEM_LIMIT'),
                                          ('MAX_LAYERS', 0, 'ITEM_LIMIT'), ('MAX_COMMAND_BYTES', 32, 'OUTPUT_LIMIT'),
                                          ('MAX_TOTAL_BYTES', 32, 'OUTPUT_LIMIT')]:
            with self.subTest(target=target), patch.object(R, target, maximum):
                self.assert_incomplete(R.collect_report(FakeDocker()), expected)
        value = fixture()
        value['containers'][CONTAINER] = dict(id=CONTAINER, image=EXTRA_IMAGE, state='exited')
        with patch.object(R, 'MAX_CONTAINERS', 0):
            self.assert_incomplete(R.collect_report(FakeDocker(value)), 'ITEM_LIMIT')

    def test_known_unknown_and_private_errors_have_fixed_safe_codes(self):
        for error, expected in [(R.Refused('COMMAND_FAILED'), 'COMMAND_FAILED'),
                                (R.Refused('COMMAND_TIMEOUT'), 'COMMAND_TIMEOUT'),
                                (R.Refused(CANARY), 'INTERNAL_ERROR'),
                                (ValueError(CANARY), 'INTERNAL_ERROR')]:
            with self.subTest(expected=expected):
                def fail(command):
                    raise error
                self.assert_incomplete(R.collect_report(fail), expected)

    def test_batching_covers_every_object_and_never_changes_fixed_endpoint(self):
        runner = FakeDocker()
        with patch.object(R, 'BATCH_SIZE', 2):
            self.assertEqual(R.collect_report(runner)['status'], 'COMPLETE_STABLE')
        inspect_commands = [c for c in runner.commands if c[len(R.DOCKER):len(R.DOCKER) + 2] == ('image', 'inspect')]
        self.assertEqual(len(inspect_commands), 6)
        for command in runner.commands:
            self.assertEqual(command[:len(R.DOCKER)], R.DOCKER)
            self.assertNotIn('rm', command)
            self.assertNotIn('prune', command)


class ParserAndSchemaTests(unittest.TestCase):
    def setUp(self):
        self.report = R.collect_report(FakeDocker())

    def test_strict_json_rejects_duplicate_keys_nonfinite_floats_and_huge_integers(self):
        for raw in (b'{"a":1,"a":2}', b'{"a":NaN}', b'{"a":Infinity}', b'{"a":1.0}',
                    b'{"a":123456789012345678901}', b'{} garbage', b'\xff'):
            with self.subTest(raw=raw), self.assertRaises(R.Refused):
                R.strict_json(raw)
        self.assertEqual(R.strict_json(b'{"a":1}'), {'a': 1})

    def test_closed_schema_rejects_extra_keys_at_every_object_level(self):
        for path in ((), ('docker',), ('candidates', 0), ('candidates', 0, 'image'), ('candidates', 0, 'references')):
            with self.subTest(path=path):
                value = copy.deepcopy(self.report)
                current = value
                for key in path:
                    current = current[key]
                current[CANARY] = CANARY
                with self.assertRaises(R.Refused):
                    R.validate_report(value)

    def test_fixed_identifiers_statuses_and_safety_assertions_cannot_be_forged(self):
        mutations = [
            (('schema_version',), True), (('scope',), CANARY),
            (('delete_authorized',), True), (('backup_currently_verified',), True),
            (('reclaimable_bytes',), 1), (('status',), 'eligible'), (('reason',), CANARY),
            (('docker', 'container_count'), True), (('docker', 'image_count'), -1),
            (('docker', 'parent_relation_complete'), True), (('docker', 'inventory_scope'), CANARY),
            (('docker', 'driver_sha256'), CANARY), (('candidates', 0, 'name'), CANARY),
            (('candidates', 0, 'image_id'), EXTRA_IMAGE), (('candidates', 0, 'status'), 'REFERENCES_OBSERVED'),
            (('candidates', 0, 'image', 'size_bytes'), True),
            (('candidates', 0, 'image', 'tag_count'), -1),
            (('candidates', 0, 'image', 'parent_present'), 0),
            (('candidates', 0, 'image', 'tags_sha256'), CANARY),
            (('candidates', 0, 'references', 'ancestor_container_count'), 1),
        ]
        for path, replacement in mutations:
            with self.subTest(path=path):
                value = copy.deepcopy(self.report)
                current = value
                for key in path[:-1]:
                    current = current[key]
                current[path[-1]] = replacement
                with self.assertRaises(R.Refused):
                    R.validate_report(value)

    def test_missing_complete_and_partial_fields_are_not_interchangeable(self):
        for status, reason in [('INCOMPLETE', 'COMMAND_FAILED'), ('CHANGED', 'INVENTORY_CHANGED')]:
            value = R.empty_report(reason, status == 'CHANGED')
            self.assertIs(R.validate_report(value), value)
            value['candidates'][0]['references'] = self.report['candidates'][0]['references']
            with self.assertRaises(R.Refused):
                R.validate_report(value)
        value = R.empty_report('OK')
        with self.assertRaises(R.Refused):
            R.validate_report(value)
        value = R.empty_report('INVENTORY_CHANGED')
        with self.assertRaises(R.Refused):
            R.validate_report(value)

    def test_input_metadata_unknown_fields_cannot_escape(self):
        for kind in ('info', 'image', 'container'):
            with self.subTest(kind=kind):
                value = fixture()
                if kind == 'info': value['info'][CANARY] = CANARY
                elif kind == 'image': value['images'][EXTRA_IMAGE][CANARY] = CANARY
                else: value['containers'][CONTAINER] = dict(id=CONTAINER, image=EXTRA_IMAGE, state='exited', env=CANARY)
                report = R.collect_report(FakeDocker(value))
                self.assertEqual(report['reason'], 'INVALID_METADATA')
                self.assertNotIn(CANARY, R.canonical(report))

    def test_direct_reference_total_cannot_exceed_container_inventory(self):
        value = copy.deepcopy(self.report)
        value['docker']['container_count'] = 1
        first = value['candidates'][0]
        first['status'] = 'REFERENCES_OBSERVED'
        first['references']['direct_container_count'] = 1
        first['references']['ancestor_container_count'] = 1
        second = copy.deepcopy(first)
        second['name'], second['image_id'] = R.CANDIDATES[1]
        value['candidates'][1] = second
        value['docker']['image_count'] = max(2, value['docker']['image_count'])
        with self.assertRaises(R.Refused):
            R.validate_report(value)

    def test_layer_relationship_counts_must_be_consistent(self):
        for relation in ('layer_prefix_image_count', 'equal_layers_image_count'):
            with self.subTest(relation=relation):
                value = copy.deepcopy(self.report)
                item = value['candidates'][0]
                item['status'] = 'REFERENCES_OBSERVED'
                item['image']['layer_count'] = 1
                item['references'][relation] = 1
                item['references']['shared_layers_image_count'] = 0
                with self.assertRaises(R.Refused):
                    R.validate_report(value)
        value = copy.deepcopy(self.report)
        value['candidates'][0]['image']['layer_count'] = 0
        value['candidates'][0]['references']['shared_layers_image_count'] = 1
        with self.assertRaises(R.Refused):
            R.validate_report(value)


class RunnerAndMainTests(unittest.TestCase):
    def test_command_allowlist_rejects_mutation_user_input_and_other_endpoints(self):
        invalid = [('/usr/bin/docker', 'image', 'rm', R.CANDIDATES[0][1]),
                   R.DOCKER + ('image', 'rm', R.CANDIDATES[0][1]),
                   R.DOCKER + ('system', 'prune'),
                   R.DOCKER + ('info',),
                   R.DOCKER + ('image', 'inspect', '--format', R.IMAGE_FORMAT, 'sha256:bad'),
                   R.DOCKER + R.CONTAINER_LIST + ('--filter', 'ancestor=' + EXTRA_IMAGE),
                   ('/usr/bin/docker', '--host=tcp://remote') + R.IMAGE_LIST,
                   list(R.DOCKER + R.IMAGE_LIST)]
        with patch.object(R.subprocess, 'Popen') as launch:
            for command in invalid:
                with self.subTest(command=command), self.assertRaises(R.Refused):
                    R.Runner()(command)
            launch.assert_not_called()

    def launch_python(self, script):
        real_popen = subprocess.Popen
        captured = []
        def launch(command, **kwargs):
            captured.append((command, kwargs))
            return real_popen((sys.executable, '-c', script), **kwargs)
        return captured, launch

    def test_process_runner_drains_stderr_without_leaking_or_inheriting_environment(self):
        captured, launch = self.launch_python("import os; os.write(1, b'[]'); os.write(2, b'PRIVATE_SYNTHETIC_CANARY')")
        with patch.dict(os.environ, {'DOCKER_CONTEXT': CANARY, 'DOCKER_HOST': CANARY}), patch.object(R.subprocess, 'Popen', side_effect=launch):
            self.assertEqual(R.Runner()(R.DOCKER + R.IMAGE_LIST), b'[]')
        self.assertEqual(captured[0][0], R.DOCKER + R.IMAGE_LIST)
        self.assertEqual(captured[0][1]['env'], R.ENV)
        self.assertNotIn('DOCKER_CONTEXT', captured[0][1]['env'])
        self.assertNotIn('DOCKER_HOST', captured[0][1]['env'])
        self.assertEqual(captured[0][1]['stdin'], subprocess.DEVNULL)
        self.assertEqual(captured[0][1]['cwd'], '/')

    def test_combined_stdout_stderr_limit_and_nonzero_exit(self):
        for script, reason in [("import os; os.write(1, b'a'*2048); os.write(2, b'b'*2049)", 'OUTPUT_LIMIT'),
                               ("import sys; sys.stderr.write('PRIVATE_SYNTHETIC_CANARY'); sys.exit(3)", 'COMMAND_FAILED')]:
            with self.subTest(reason=reason):
                _, launch = self.launch_python(script)
                with patch.object(R, 'MAX_COMMAND_BYTES', 4096), patch.object(R.subprocess, 'Popen', side_effect=launch):
                    with self.assertRaisesRegex(R.Refused, '^' + reason + '$'):
                        R.Runner()(R.DOCKER + R.IMAGE_LIST)

    def test_process_timeout_and_total_pipe_budget(self):
        _, launch = self.launch_python('import time; time.sleep(2)')
        with patch.object(R, 'COMMAND_SECONDS', 0.05), patch.object(R.subprocess, 'Popen', side_effect=launch):
            with self.assertRaisesRegex(R.Refused, '^COMMAND_TIMEOUT$'):
                R.Runner()(R.DOCKER + R.IMAGE_LIST)
        _, launch = self.launch_python("import os; os.write(1,b'a'*3000)")
        with patch.object(R, 'MAX_TOTAL_BYTES', 5000), patch.object(R.subprocess, 'Popen', side_effect=launch):
            runner = R.Runner()
            self.assertEqual(len(runner(R.DOCKER + R.IMAGE_LIST)), 3000)
            with self.assertRaisesRegex(R.Refused, '^OUTPUT_LIMIT$'):
                runner(R.DOCKER + R.IMAGE_LIST)

    def test_main_guards_platform_root_and_arguments_without_collecting(self):
        for platform, uid, argv, reason in [('darwin', 0, [], 'UNSUPPORTED_PLATFORM'),
                                           ('linux', 1000, [], 'NOT_ROOT'),
                                           ('linux', 0, ['--delete'], 'INPUT_REFUSED')]:
            with self.subTest(reason=reason), patch.object(R.sys, 'platform', platform), patch.object(R.os, 'geteuid', return_value=uid), patch.object(R, 'collect_report') as collect:
                output, error = io.StringIO(), io.StringIO()
                with contextlib.redirect_stdout(output), contextlib.redirect_stderr(error):
                    self.assertEqual(R.main(argv), 2)
                collect.assert_not_called()
                self.assertEqual(error.getvalue(), '')
                self.assertEqual(output.getvalue().count('\n'), 1)
                self.assertEqual(R.strict_json(output.getvalue())['reason'], reason)

    def test_main_returns_matching_exit_status_and_closed_one_line_json(self):
        for report, expected in [(R.collect_report(FakeDocker()), 0),
                                 (R.empty_report('COMMAND_FAILED'), 2),
                                 (R.empty_report('INVENTORY_CHANGED', True), 2),
                                 ({'private': CANARY}, 2)]:
            with self.subTest(expected=expected), patch.object(R.sys, 'platform', 'linux'), patch.object(R.os, 'geteuid', return_value=0), patch.object(R, 'collect_report', return_value=report):
                output, error = io.StringIO(), io.StringIO()
                with contextlib.redirect_stdout(output), contextlib.redirect_stderr(error):
                    self.assertEqual(R.main([]), expected)
                self.assertEqual(error.getvalue(), '')
                self.assertEqual(output.getvalue().count('\n'), 1)
                self.assertLessEqual(len(output.getvalue().encode()), R.MAX_REPORT_BYTES)
                R.validate_report(R.strict_json(output.getvalue()))
                self.assertNotIn(CANARY, output.getvalue())


if __name__ == '__main__':
    unittest.main()
