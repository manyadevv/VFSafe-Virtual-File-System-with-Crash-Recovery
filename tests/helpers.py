"""Shared helpers for the VFSafe tests."""

import shutil
import tempfile
import unittest
from pathlib import Path

from errors import SimulatedCrash
from file_manager import FileManager


class VFSTestCase(unittest.TestCase):
    """Gives every test its own empty temporary storage folder."""

    def setUp(self):
        self._tmp = tempfile.mkdtemp(prefix="vfsafe_test_")
        self.root = Path(self._tmp) / "storage"
        self.fm = self.restart()

    def tearDown(self):
        shutil.rmtree(self._tmp, ignore_errors=True)

    def reset_storage(self):
        """Throw away the storage and start a brand-new scenario (used inside loops)."""
        shutil.rmtree(self._tmp, ignore_errors=True)
        self.setUp()

    def restart(self, auto_recover=True):
        """Simulate 'closing the program and starting it again'."""
        return FileManager(self.root, auto_recover=auto_recover)

    def crash(self, fm, point, operation, *args):
        """Arm `point`, run the operation, and assert that it 'crashed'."""
        fm.crash.arm(point)
        with self.assertRaises(SimulatedCrash) as ctx:
            operation(*args)
        self.assertEqual(ctx.exception.point, point)

    def snapshot(self, fm):
        """{name: (content, metadata-entry)} - everything a user could observe."""
        return {f["name"]: (fm.read(f["name"]), dict(f)) for f in fm.list_files()}

    def contents(self, fm):
        return {f["name"]: fm.read(f["name"]) for f in fm.list_files()}
