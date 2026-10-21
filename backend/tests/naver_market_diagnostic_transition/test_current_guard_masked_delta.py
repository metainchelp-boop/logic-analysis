import unittest
import test_current_guard as fixtures
import transition as T


class MaskedInvocationTests(unittest.TestCase):
    def test_masked_different_nonzero_invocation_rejects_without_old_journal_read(self):
        f = fixtures.CurrentGuardTests();f.setUp();self.addCleanup(f.doCleanups)
        f.guard.capture();f.calls.clear()
        f.reader.update(LoadState='masked', UnitFileState='masked-runtime', FragmentPath=fixtures.S.MASK_ROOT + '/' + T.OLD_READER,
            InvocationID='8' * 32, Result='success', ExecMainStatus='0')
        with self.assertRaisesRegex(T.Invalid, 'CURRENT_FAILURE_CHANGED'):
            f.guard(require_failure=True)
        self.assertFalse(any(v[0] == '/usr/bin/journalctl' for v in f.calls))

    def test_bound_or_cleared_mask_cache_retains_same_original_proof(self):
        f = fixtures.CurrentGuardTests();f.setUp();self.addCleanup(f.doCleanups)
        proof = f.guard.capture()
        for invocation in ('f' * 32, '', '0' * 32):
            f.reader.update(LoadState='masked', UnitFileState='masked-runtime', FragmentPath=fixtures.S.MASK_ROOT + '/' + T.OLD_READER,
                InvocationID=invocation)
            self.assertTrue(f.guard(require_failure=True)['source_limit_invocation_verified'])
            self.assertEqual(f.guard.proof, proof)


if __name__ == '__main__': unittest.main()
