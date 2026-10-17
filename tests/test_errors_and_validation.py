"""Tests for invalid names, missing files, duplicates and bad content."""

from errors import (
    FileAlreadyExistsError,
    FileMissingError,
    InvalidContentError,
    InvalidNameError,
    StorageError,
    VFSafeError,
)
from file_manager import FileManager
from storage import Storage
from tests.helpers import VFSTestCase
from validation import MAX_FILE_BYTES, MAX_NAME_LENGTH, validate_name


class InvalidNamesTest(VFSTestCase):
    BAD_NAMES = [
        "", " ", "has space.txt", "a/b.txt", "a\\b.txt", "..", ".", ".hidden",
        "ends.", "../escape.txt", "C:evil.txt", "q?.txt", "star*.txt",
        "x" * (MAX_NAME_LENGTH + 1), "CON", "nul.txt", "COM1", "lpt9.log",
    ]

    def test_invalid_names_rejected_by_create(self):
        for name in self.BAD_NAMES:
            with self.subTest(name=name):
                with self.assertRaises(InvalidNameError):
                    self.fm.create(name, "x")
        self.assertEqual(self.fm.list_files(), [])

    def test_invalid_names_never_reach_the_journal(self):
        for name in self.BAD_NAMES:
            with self.assertRaises(InvalidNameError):
                self.fm.create(name, "x")
        self.assertEqual(self.fm.journal.read_all().records, [])

    def test_non_text_name_rejected(self):
        for bad in (None, 5, b"a.txt"):
            with self.assertRaises(InvalidNameError):
                validate_name(bad)

    def test_valid_names_accepted(self):
        for name in ("a", "a.txt", "My-File_1.v2.txt", "_x", "9lives", "x" * MAX_NAME_LENGTH):
            with self.subTest(name=name):
                self.assertEqual(validate_name(name), name)

    def test_error_message_is_helpful(self):
        with self.assertRaises(InvalidNameError) as ctx:
            self.fm.create("a/b", "x")
        self.assertIn("folders", str(ctx.exception))


class MissingAndDuplicateTest(VFSTestCase):
    def test_read_missing_file(self):
        with self.assertRaises(FileMissingError):
            self.fm.read("nope.txt")

    def test_write_append_delete_stat_missing_file(self):
        for operation, args in ((self.fm.write, ("nope.txt", "x")),
                                (self.fm.append, ("nope.txt", "x")),
                                (self.fm.delete, ("nope.txt",)),
                                (self.fm.stat, ("nope.txt",))):
            with self.subTest(operation=operation.__name__):
                with self.assertRaises(FileMissingError):
                    operation(*args)

    def test_rename_missing_source(self):
        with self.assertRaises(FileMissingError):
            self.fm.rename("nope.txt", "other.txt")

    def test_duplicate_create(self):
        self.fm.create("a.txt", "first")
        with self.assertRaises(FileAlreadyExistsError):
            self.fm.create("a.txt", "second")
        self.assertEqual(self.fm.read("a.txt"), "first")   # untouched

    def test_rename_onto_existing_file(self):
        self.fm.create("a.txt", "A")
        self.fm.create("b.txt", "B")
        with self.assertRaises(FileAlreadyExistsError):
            self.fm.rename("a.txt", "b.txt")
        self.assertEqual(self.contents(self.fm), {"a.txt": "A", "b.txt": "B"})

    def test_rename_to_same_name(self):
        self.fm.create("a.txt", "A")
        with self.assertRaises(VFSafeError):
            self.fm.rename("a.txt", "A.TXT")

    def test_rename_to_invalid_name(self):
        self.fm.create("a.txt", "A")
        with self.assertRaises(InvalidNameError):
            self.fm.rename("a.txt", "bad name")
        self.assertEqual(self.fm.read("a.txt"), "A")

    def test_failed_operations_write_nothing_to_journal(self):
        self.fm.create("a.txt", "A")
        before = len(self.fm.journal.read_all().records)
        for call in (lambda: self.fm.create("a.txt"), lambda: self.fm.delete("zzz.txt"),
                     lambda: self.fm.rename("a.txt", "a.txt")):
            with self.assertRaises(VFSafeError):
                call()
        self.assertEqual(len(self.fm.journal.read_all().records), before)


class InvalidContentTest(VFSTestCase):
    def test_non_text_content_rejected(self):
        for bad in (None, 123, b"bytes"):
            with self.assertRaises(InvalidContentError):
                self.fm.create("a.txt", bad)

    def test_content_too_large(self):
        with self.assertRaises(InvalidContentError):
            self.fm.create("big.txt", "x" * (MAX_FILE_BYTES + 1))
        self.assertEqual(self.fm.list_files(), [])

    def test_append_cannot_exceed_limit(self):
        self.fm.create("a.txt", "x" * MAX_FILE_BYTES)
        with self.assertRaises(InvalidContentError):
            self.fm.append("a.txt", "y")
        self.assertEqual(len(self.fm.read("a.txt")), MAX_FILE_BYTES)


class StorageSafetyTest(VFSTestCase):
    def test_refuses_to_adopt_a_folder_with_real_files(self):
        foreign = self.root.parent / "my_real_documents"
        foreign.mkdir()
        (foreign / "important.docx").write_text("do not touch")
        with self.assertRaises(StorageError):
            FileManager(foreign)
        self.assertEqual([p.name for p in foreign.iterdir()], ["important.docx"])
        self.assertEqual((foreign / "important.docx").read_text(), "do not touch")

    def test_reset_requires_vfsafe_marker(self):
        foreign = self.root.parent / "other"
        foreign.mkdir()
        (foreign / "keep.txt").write_text("x")
        with self.assertRaises(StorageError):
            Storage(foreign).reset()
        self.assertTrue((foreign / "keep.txt").exists())

    def test_reset_clears_everything(self):
        self.fm.create("a.txt", "x")
        self.fm.storage.reset()
        fresh = self.restart()
        self.assertEqual(fresh.list_files(), [])
        self.assertEqual(fresh.journal.read_all().records, [])
