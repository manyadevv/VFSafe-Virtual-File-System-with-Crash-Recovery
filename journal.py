"""
journal.py - the Journal Manager (write-ahead log).

WRITE-AHEAD LOGGING in one sentence:
    "Write down what you are ABOUT to do, make sure that note is safely on
     disk, only then do it - and finally write down that it is DONE."

The journal is a text file, one record per line:

    <crc32 in hex> <json>

Record types
    BEGIN       the full description of an operation (op, names, NEW content)
    COMMIT      "operation <txid> finished completely"
    CHECKPOINT  written when the journal is emptied; remembers the last txid

Why a CRC (checksum) on every line?
    If the program dies while a line is being written, the line is cut off.
    The CRC lets us notice "this line is damaged" and ignore it, instead of
    trusting half a record.

A BEGIN without a matching COMMIT = an INCOMPLETE (pending) operation.
"""

import json
import os
import zlib
from dataclasses import dataclass, field
from typing import List, Tuple

from errors import JournalError

RECORD_TYPES = ("BEGIN", "COMMIT", "CHECKPOINT")


@dataclass
class JournalScan:
    """Result of reading the whole journal file."""

    records: List[dict] = field(default_factory=list)       # all valid records, in order
    bad_lines: List[Tuple[int, str]] = field(default_factory=list)  # (line no, reason)
    torn_tail: bool = False      # last line was cut off (no newline at the end)
    torn_bytes: int = 0          # how many bytes that cut-off line has
    valid_length: int = 0        # file size up to the end of the last complete line


def encode_record(record):
    """dict -> one journal line (with CRC and trailing newline)."""
    payload = json.dumps(record, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    crc = zlib.crc32(payload.encode("ascii")) & 0xFFFFFFFF
    return "%08x %s\n" % (crc, payload)


def decode_line(text):
    """One journal line (without newline) -> dict. Raises ValueError if damaged."""
    crc_hex, sep, payload = text.partition(" ")
    if not sep or len(crc_hex) != 8:
        raise ValueError("malformed line")
    try:
        expected = int(crc_hex, 16)
    except ValueError:
        raise ValueError("malformed checksum")
    if (zlib.crc32(payload.encode("ascii")) & 0xFFFFFFFF) != expected:
        raise ValueError("checksum mismatch")
    record = json.loads(payload)
    if not isinstance(record, dict) or record.get("type") not in RECORD_TYPES:
        raise ValueError("unknown record type")
    if not isinstance(record.get("txid"), int):
        raise ValueError("missing txid")
    return record


class Journal:
    def __init__(self, path, crash=None):
        self.path = path
        self.crash = crash          # CrashSimulator (optional)
        self._last_txid = None      # cache; filled on first use

    # ---------------------------------------------------------------- writing
    def append(self, record):
        """Append one record and force it to disk (fsync) before returning."""
        line = encode_record(record)
        prefix = b""
        if self.path.exists() and self.path.stat().st_size > 0:
            with open(self.path, "rb") as probe:
                probe.seek(-1, os.SEEK_END)
                if probe.read(1) != b"\n":      # never glue onto a torn line
                    prefix = b"\n"
        with open(self.path, "ab") as handle:
            if (
                self.crash is not None
                and record["type"] == "BEGIN"
                and self.crash.is_armed("during_journal")
            ):
                half = line[: len(line) // 2].encode("ascii")   # torn write!
                handle.write(prefix + half)
                handle.flush()
                os.fsync(handle.fileno())
                self.crash.checkpoint("during_journal")         # raises SimulatedCrash
            handle.write(prefix + line.encode("ascii"))
            handle.flush()
            os.fsync(handle.fileno())
        if self._last_txid is None or record["txid"] > self._last_txid:
            self._last_txid = record["txid"]

    def next_txid(self):
        """Transaction ids go 1, 2, 3, ... (and keep counting after a checkpoint)."""
        if self._last_txid is None:
            ids = [r["txid"] for r in self.read_all().records]
            self._last_txid = max(ids) if ids else 0
        return self._last_txid + 1

    def reset_cache(self):
        self._last_txid = None

    # ---------------------------------------------------------------- reading
    def read_all(self):
        scan = JournalScan()
        if not self.path.exists():
            return scan
        data = self.path.read_bytes()
        pos, line_no = 0, 0
        while pos < len(data):
            newline = data.find(b"\n", pos)
            if newline == -1:                      # last line has no newline: torn
                scan.torn_tail = True
                scan.torn_bytes = len(data) - pos
                break
            raw = data[pos:newline]
            pos = newline + 1
            line_no += 1
            scan.valid_length = pos
            try:
                scan.records.append(decode_line(raw.decode("ascii")))
            except (UnicodeDecodeError, ValueError) as exc:
                scan.bad_lines.append((line_no, str(exc)))
        return scan

    @staticmethod
    def pending_from(records):
        """BEGIN records that never got a COMMIT, in journal order."""
        open_tx = {}
        for rec in records:
            if rec["type"] == "BEGIN":
                open_tx[rec["txid"]] = rec
            elif rec["type"] == "COMMIT":
                open_tx.pop(rec["txid"], None)
        return list(open_tx.values())

    # ------------------------------------------------------------ maintenance
    def repair_tail(self, scan=None):
        """Cut off a torn last line. Returns the number of bytes removed."""
        scan = scan or self.read_all()
        if not scan.torn_tail:
            return 0
        with open(self.path, "r+b") as handle:
            handle.truncate(scan.valid_length)
            handle.flush()
            os.fsync(handle.fileno())
        self.reset_cache()
        return scan.torn_bytes

    def checkpoint(self):
        """
        Empty the journal once every operation is committed, so it does not
        grow forever. Leaves one CHECKPOINT record to remember the txid count.
        Returns how many records were removed.
        """
        scan = self.read_all()
        if scan.torn_tail or self.pending_from(scan.records):
            raise JournalError(
                "Cannot checkpoint: there are unfinished operations. Run recovery first."
            )
        last = max([r["txid"] for r in scan.records], default=0)
        with open(self.path, "wb") as handle:
            handle.write(encode_record({"type": "CHECKPOINT", "txid": last}).encode("ascii"))
            handle.flush()
            os.fsync(handle.fileno())
        self._last_txid = last
        return len(scan.records)
