"""Tests for the journal: encoding, damage detection, checkpoint."""

from errors import JournalError
from journal import Journal, decode_line, encode_record
from tests.helpers import VFSTestCase


class JournalFormatTest(VFSTestCase):
    def test_encode_decode_round_trip(self):
        rec = {"type": "BEGIN", "txid": 3, "op": "write", "name": "a.txt",
               "content": "line1\nline2 \u00e9 \"quoted\"", "ts": "now"}
        line = encode_record(rec)
        self.assertTrue(line.endswith("\n"))
        self.assertEqual(line.count("\n"), 1)         # newlines inside content are escaped
        self.assertEqual(decode_line(line.rstrip("\n")), rec)

    def test_damaged_line_is_detected(self):
        line = encode_record({"type": "COMMIT", "txid": 1}).rstrip("\n")
        with self.assertRaises(ValueError):
            decode_line(line[:-3] + "xyz")

    def test_checksum_catches_damage_that_still_looks_like_valid_json(self):
        """Flip one letter inside the content: the JSON is still valid, only the CRC notices."""
        line = encode_record({"type": "BEGIN", "txid": 1, "op": "write", "name": "a.txt",
                              "content": "secret", "ts": "t"}).rstrip("\n")
        tampered = line.replace("secret", "Secret")
        self.assertNotEqual(line, tampered)
        with self.assertRaises(ValueError) as ctx:
            decode_line(tampered)
        self.assertIn("checksum", str(ctx.exception))

    def test_tampered_record_in_file_is_never_applied_by_recovery(self):
        self.crash(self.fm, "after_journal", self.fm.create, "a.txt", "original")
        path = self.fm.storage.journal_path
        path.write_bytes(path.read_bytes().replace(b"original", b"0riginal"))
        fm = self.restart()
        self.assertEqual(fm.list_files(), [])                 # damaged BEGIN was not trusted
        self.assertEqual(len(fm.recovery_report.bad_lines), 1)

    def test_begin_is_written_before_commit(self):
        self.fm.create("a.txt", "x")
        types = [r["type"] for r in self.fm.journal.read_all().records]
        self.assertEqual(types, ["BEGIN", "COMMIT"])

    def test_begin_record_contains_everything_needed_to_redo(self):
        self.fm.create("a.txt", "payload")
        begin = self.fm.journal.read_all().records[0]
        self.assertEqual((begin["op"], begin["name"], begin["content"]),
                         ("create", "a.txt", "payload"))


class JournalDamageTest(VFSTestCase):
    def test_torn_last_line_is_detected(self):
        self.fm.create("a.txt", "x")
        with open(self.fm.storage.journal_path, "ab") as f:
            f.write(b"deadbeef {\"type\":\"BEG")        # cut off, no newline
        scan = self.fm.journal.read_all()
        self.assertTrue(scan.torn_tail)
        self.assertEqual(len(scan.records), 2)

    def test_damaged_middle_line_is_skipped_not_fatal(self):
        self.fm.create("a.txt", "x")
        self.fm.create("b.txt", "y")
        raw = self.fm.storage.journal_path.read_bytes().split(b"\n")
        raw[2] = b"00000000 garbage"                     # destroy the 3rd record
        self.fm.storage.journal_path.write_bytes(b"\n".join(raw))
        scan = self.fm.journal.read_all()
        self.assertEqual(len(scan.bad_lines), 1)
        self.assertEqual(len(scan.records), 3)
        restarted = self.restart()                       # recovery must not crash
        self.assertEqual(len(restarted.recovery_report.bad_lines), 1)

    def test_append_never_glues_onto_a_torn_line(self):
        self.fm.create("a.txt", "x")
        with open(self.fm.storage.journal_path, "ab") as f:
            f.write(b"half a record")
        self.fm.journal.append({"type": "COMMIT", "txid": 99})
        self.assertEqual(self.fm.journal.read_all().records[-1]["txid"], 99)


class JournalCheckpointTest(VFSTestCase):
    def test_checkpoint_empties_journal_but_keeps_txid_counter(self):
        self.fm.create("a.txt", "x")
        self.fm.create("b.txt", "y")
        self.assertEqual(self.fm.journal.checkpoint(), 4)
        self.assertEqual([r["type"] for r in self.fm.journal.read_all().records], ["CHECKPOINT"])
        self.fm.create("c.txt", "z")
        self.assertEqual(self.fm.journal.read_all().records[1]["txid"], 3)
        self.assertEqual(self.contents(self.restart()),
                         {"a.txt": "x", "b.txt": "y", "c.txt": "z"})

    def test_checkpoint_refused_while_operation_pending(self):
        self.crash(self.fm, "after_journal", self.fm.create, "a.txt", "x")
        fm = self.restart(auto_recover=False)
        with self.assertRaises(JournalError):
            fm.journal.checkpoint()

    def test_pending_from_ignores_committed(self):
        recs = [{"type": "BEGIN", "txid": 1}, {"type": "COMMIT", "txid": 1},
                {"type": "BEGIN", "txid": 2}]
        self.assertEqual([r["txid"] for r in Journal.pending_from(recs)], [2])
