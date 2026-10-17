"""
recovery.py - the Recovery Manager.

RECOVERY POLICY ("roll forward, or forget")
------------------------------------------
Because every BEGIN record contains the COMPLETE new content, the journal has
everything needed to finish an operation. So on every start-up we do:

  1. Delete leftover temp files.
  2. Read the journal. If its last line is cut off (torn), throw that line away.
     That operation never became "official", so it simply never happened.
  3. For every BEGIN that has NO COMMIT:  REDO it (apply it again), then write
     a COMMIT. Redo is safe even if the operation was already fully applied,
     because every apply step is repeatable (idempotent).
  4. Run the consistency checker and report the result.

What happens for each crash point?
  before_journal  -> nothing was logged           -> operation never happened
  during_journal  -> BEGIN is cut off (bad CRC)   -> discarded, never happened
  after_journal   -> BEGIN complete, nothing done -> REDONE (rolled forward)
  during_apply    -> BEGIN complete, half done    -> REDONE (rolled forward)
  after_apply     -> BEGIN complete, all done     -> REDONE (harmless repeat) + COMMIT
  after_commit    -> COMMIT exists                -> nothing to do

Running recovery twice (or after a crash INSIDE recovery) is safe: the second
run finds nothing pending.

This module never imports file_manager.py; it just uses the object it is given.
"""

import time
from dataclasses import dataclass, field
from typing import List

from consistency import ConsistencyChecker
from journal import Journal


@dataclass
class RecoveryReport:
    records_scanned: int = 0
    committed_count: int = 0
    redone: List[dict] = field(default_factory=list)       # [{"txid", "op", "name"}]
    torn_bytes_discarded: int = 0
    bad_lines: list = field(default_factory=list)
    temp_files_removed: int = 0
    duration_ms: float = 0.0
    consistency: object = None

    @property
    def nothing_to_do(self):
        return not (self.redone or self.torn_bytes_discarded or self.temp_files_removed)

    def summary_lines(self):
        lines = []
        if self.nothing_to_do:
            lines.append("Recovery: journal is clean, nothing to recover.")
        else:
            lines.append("Recovery: unfinished work found - fixing it now.")
            for item in self.redone:
                lines.append(
                    "  - tx %d '%s' on '%s': had no COMMIT -> REDONE (rolled forward) and committed"
                    % (item["txid"], item["op"], item["name"])
                )
            if self.torn_bytes_discarded:
                lines.append(
                    "  - incomplete journal record (%d bytes) -> DISCARDED "
                    "(that operation never became official, so it did not happen)"
                    % self.torn_bytes_discarded
                )
            if self.temp_files_removed:
                lines.append("  - removed %d leftover temp file(s)" % self.temp_files_removed)
        for line_no, reason in self.bad_lines:
            lines.append("  ! journal line %d is damaged (%s) and was skipped" % (line_no, reason))
        if self.consistency is not None:
            lines.extend(self.consistency.summary_lines())
        lines.append("Recovery time: %.2f ms" % self.duration_ms)
        return lines


class RecoveryManager:
    def __init__(self, file_manager):
        self.fm = file_manager

    def recover(self):
        fm = self.fm
        started = time.perf_counter()
        report = RecoveryReport()

        fm.metadata.load()                                   # trust the disk, not memory
        report.temp_files_removed = fm.storage.clean_tmp()

        scan = fm.journal.read_all()
        if scan.torn_tail:
            report.torn_bytes_discarded = fm.journal.repair_tail(scan)
            scan = fm.journal.read_all()
        report.bad_lines = list(scan.bad_lines)
        report.records_scanned = len(scan.records)
        report.committed_count = sum(1 for r in scan.records if r["type"] == "COMMIT")

        for record in Journal.pending_from(scan.records):
            fm.apply(record)                                 # REDO (repeatable)
            fm.crash.checkpoint("during_recovery")           # tests can crash here
            fm.journal.append(
                {"type": "COMMIT", "txid": record["txid"], "by": "recovery", "ts": _now()}
            )
            report.redone.append(
                {"txid": record["txid"], "op": record["op"], "name": record["name"]}
            )

        fm.journal.reset_cache()
        report.consistency = ConsistencyChecker(fm).check()
        report.duration_ms = (time.perf_counter() - started) * 1000.0
        return report


def _now():
    return time.strftime("%Y-%m-%d %H:%M:%S")
