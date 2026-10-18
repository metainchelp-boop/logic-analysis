"""One new interrupted ownership durability boundary; temporary files only."""
from pathlib import Path
import unittest
from unittest.mock import patch
import publication as P
import test_publication as publication_fixture


class OwnershipDurability(unittest.TestCase):
    def test_recovered_ownership_is_fsynced_before_public_link_and_failure_blocks_link(self):
        for fail_sync in (False, True):
            fixture = publication_fixture.PublicationTests()
            fixture.setUp()
            try:
                pub = fixture.pub
                original_link, original_sync = P.os.link, pub._sync

                def interrupt_commit(source, target, **kwargs):
                    original_link(source, target, **kwargs)
                    if Path(target).name == 'ownership.json':
                        raise KeyboardInterrupt('synthetic ownership commit boundary')

                with patch.object(P.os, 'link', side_effect=interrupt_commit):
                    with self.assertRaises(KeyboardInterrupt): pub.prepare()
                self.assertTrue((pub.root / 'ownership.pending').exists())
                events = []

                def sync(path):
                    events.append(('sync', Path(path)))
                    if fail_sync and Path(path) == pub.root:
                        raise OSError('synthetic receipt fsync boundary')
                    original_sync(path)

                def link(source, target, **kwargs):
                    events.append(('link', Path(target)))
                    original_link(source, target, **kwargs)

                with patch.object(pub, '_sync', side_effect=sync), patch.object(P.os, 'link', side_effect=link):
                    if fail_sync:
                        with self.assertRaises(OSError): pub.publish('mask')
                    else: pub.publish('mask')
                self.assertEqual(events[0], ('sync', pub.root))
                links = [event for event in events if event[0] == 'link']
                self.assertEqual(len(links), 0 if fail_sync else 2)
                if fail_sync:
                    self.assertTrue(all(not Path(target).exists() and not Path(target).is_symlink()
                                        for target in pub.expected))
                else:
                    pub.remove('mask')
                pub.validate()
            finally:
                fixture.doCleanups()


if __name__ == '__main__': unittest.main()
