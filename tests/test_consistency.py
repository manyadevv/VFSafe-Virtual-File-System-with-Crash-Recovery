"""Tests for the consistency checker (fsck)."""

from consistency import ConsistencyChecker
from tests.helpers import VFSTestCase


class ConsistencyCheckerTest(VFSTestCase):
    def codes(self):
        return {i.code for i in ConsistencyChecker(self.fm).check().issues}

    def test_clean_file_system_is_clean(self):
        self.fm.create("a.txt", "x")
        self.fm.create("b.txt", "y")
        report = ConsistencyChecker(self.fm).check()
        self.assertTrue(report.is_clean)
        self.assertEqual(report.files_checked, 2)

    def test_empty_file_system_is_clean(self):
        self.assertTrue(ConsistencyChecker(self.fm).check().is_clean)

    def test_detects_missing_data_file(self):
        self.fm.create("a.txt", "x")
        self.fm.storage.file_path("a.txt").unlink()
        self.assertIn("META_WITHOUT_DATA", self.codes())

    def test_detects_orphan_data_file(self):
        self.fm.create("a.txt", "x")
        (self.fm.storage.data_dir / "stray.txt").write_text("who am i")
        self.assertIn("DATA_WITHOUT_META", self.codes())

    def test_detects_size_mismatch(self):
        self.fm.create("a.txt", "12345")
        self.fm.storage.file_path("a.txt").write_text("123")
        self.assertIn("SIZE_MISMATCH", self.codes())

    def test_detects_silent_corruption_with_same_size(self):
        self.fm.create("a.txt", "12345")
        self.fm.storage.file_path("a.txt").write_text("54321")     # same length!
        self.assertIn("CHECKSUM_MISMATCH", self.codes())

    def test_detects_pending_operation(self):
        self.crash(self.fm, "after_journal", self.fm.create, "a.txt", "x")
        fm = self.restart(auto_recover=False)
        self.assertIn("PENDING_OPERATIONS", {i.code for i in ConsistencyChecker(fm).check().issues})

    def test_detects_leftover_temp_file(self):
        (self.fm.storage.tmp_dir / "w-x.tmp").write_text("junk")
        self.assertIn("TEMP_FILES", self.codes())

    def test_warnings_do_not_make_it_inconsistent(self):
        (self.fm.storage.tmp_dir / "w-x.tmp").write_text("junk")
        report = ConsistencyChecker(self.fm).check()
        self.assertTrue(report.is_consistent)
        self.assertFalse(report.is_clean)

    def test_detects_name_in_metadata_that_is_illegal(self):
        self.fm.create("a.txt", "x")
        self.fm.metadata.files["bad name"] = dict(self.fm.metadata.files["a.txt"])
        self.fm.metadata.save()
        self.assertIn("INVALID_NAME", self.codes())

    def test_detects_names_that_differ_only_by_case(self):
        self.fm.create("a.txt", "x")
        self.fm.metadata.files["A.txt"] = dict(self.fm.metadata.files["a.txt"])
        self.fm.metadata.save()
        self.assertIn("CASE_COLLISION", self.codes())

    def test_summary_lines_are_readable(self):
        self.fm.create("a.txt", "x")
        self.fm.storage.file_path("a.txt").unlink()
        text = "\n".join(ConsistencyChecker(self.fm).check().summary_lines())
        self.assertIn("a.txt", text)
        self.assertIn("ERROR", text)
