"""Tests for normal (no crash) file operations."""

from errors import FileAlreadyExistsError, FileMissingError
from tests.helpers import VFSTestCase


class BasicOperationsTest(VFSTestCase):
    def test_create_and_read(self):
        self.fm.create("a.txt", "hello")
        self.assertEqual(self.fm.read("a.txt"), "hello")

    def test_create_empty_file(self):
        self.fm.create("empty.txt")
        self.assertEqual(self.fm.read("empty.txt"), "")
        self.assertEqual(self.fm.stat("empty.txt")["size"], 0)

    def test_write_replaces_content(self):
        self.fm.create("a.txt", "old")
        self.fm.write("a.txt", "new content")
        self.assertEqual(self.fm.read("a.txt"), "new content")

    def test_append_adds_to_end(self):
        self.fm.create("a.txt", "hello")
        self.fm.append("a.txt", " world")
        self.assertEqual(self.fm.read("a.txt"), "hello world")

    def test_rename_moves_content(self):
        self.fm.create("a.txt", "data")
        self.fm.rename("a.txt", "b.txt")
        self.assertEqual(self.fm.read("b.txt"), "data")
        with self.assertRaises(FileMissingError):
            self.fm.read("a.txt")

    def test_delete_removes_file(self):
        self.fm.create("a.txt", "data")
        self.fm.delete("a.txt")
        self.assertEqual(self.fm.list_files(), [])
        self.assertFalse((self.fm.storage.data_dir / "a.txt").exists())

    def test_list_is_sorted_and_complete(self):
        for name in ("c.txt", "a.txt", "b.txt"):
            self.fm.create(name, name)
        self.assertEqual([f["name"] for f in self.fm.list_files()], ["a.txt", "b.txt", "c.txt"])

    def test_unicode_content_round_trip(self):
        text = "namaste \u0928\u092e\u0938\u094d\u0924\u0947 caf\u00e9 \u4f60\u597d"
        self.fm.create("u.txt", text)
        self.assertEqual(self.fm.read("u.txt"), text)
        self.assertEqual(self.restart().read("u.txt"), text)

    def test_metadata_tracks_size_and_last_operation(self):
        self.fm.create("a.txt", "12345")
        info = self.fm.stat("a.txt")
        self.assertEqual(info["size"], 5)
        self.assertEqual(info["last_op"], "create")
        self.fm.append("a.txt", "67")
        info = self.fm.stat("a.txt")
        self.assertEqual(info["size"], 7)
        self.assertEqual(info["last_op"], "append")

    def test_created_time_kept_when_overwritten(self):
        self.fm.create("a.txt", "1")
        created = self.fm.stat("a.txt")["created"]
        self.fm.write("a.txt", "2")
        self.assertEqual(self.fm.stat("a.txt")["created"], created)

    def test_data_survives_normal_restart(self):
        self.fm.create("a.txt", "keep me")
        self.assertEqual(self.restart().read("a.txt"), "keep me")

    def test_file_names_are_case_insensitive_for_lookup(self):
        self.fm.create("Notes.txt", "x")
        self.assertEqual(self.fm.read("notes.TXT"), "x")
        with self.assertRaises(FileAlreadyExistsError):
            self.fm.create("NOTES.txt", "y")

    def test_every_operation_writes_begin_and_commit(self):
        self.fm.create("a.txt", "1")
        self.fm.write("a.txt", "2")
        records = self.fm.journal.read_all().records
        self.assertEqual([r["type"] for r in records], ["BEGIN", "COMMIT", "BEGIN", "COMMIT"])
        self.assertEqual([r["txid"] for r in records], [1, 1, 2, 2])

    def test_files_live_only_inside_storage_folder(self):
        self.fm.create("a.txt", "x")
        self.assertEqual(self.fm.storage.file_path("a.txt").parent, self.fm.storage.data_dir)
        self.assertTrue(str(self.fm.storage.data_dir).startswith(str(self.root.resolve())))
