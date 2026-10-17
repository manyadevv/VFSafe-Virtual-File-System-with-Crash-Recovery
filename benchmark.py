"""
benchmark.py - basic performance measurements (proposal objective #8).

Measures, in a throw-away temporary folder:
  * average time of each file operation
  * time to recover N unfinished operations

NOTE: every operation calls fsync (forces data onto the disk) twice for the
journal and again for data/metadata. That is what makes the log trustworthy,
and it is also why operations take milliseconds rather than microseconds.
"""

import tempfile
import time
from pathlib import Path

from file_manager import FileManager
from journal import Journal


def _avg_ms(func, items):
    start = time.perf_counter()
    for item in items:
        func(item)
    return (time.perf_counter() - start) * 1000.0 / len(items)


def run_benchmark(n=100, out=print):
    names = ["bench%d.txt" % i for i in range(n)]
    results = []

    with tempfile.TemporaryDirectory() as tmp:
        fm = FileManager(Path(tmp) / "bench")
        results.append(("create", _avg_ms(lambda x: fm.create(x, "x" * 100), names)))
        results.append(("read", _avg_ms(fm.read, names)))
        results.append(("write", _avg_ms(lambda x: fm.write(x, "y" * 100), names)))
        results.append(("append", _avg_ms(lambda x: fm.append(x, "z"), names)))
        results.append(("list (all files)", _avg_ms(lambda _: fm.list_files(), [0] * n)))
        results.append(("rename", _avg_ms(lambda x: fm.rename(x, "r_" + x), names)))
        results.append(("delete", _avg_ms(lambda x: fm.delete("r_" + x), names)))

    recovery_rows = []
    for pending in (0, max(1, n // 10), n):
        with tempfile.TemporaryDirectory() as tmp:
            fm = FileManager(Path(tmp) / "bench", auto_recover=False)
            # Fake `pending` unfinished operations: BEGIN records with no COMMIT.
            for i in range(pending):
                fm.journal.append({
                    "type": "BEGIN", "txid": i + 1, "op": "create",
                    "name": "p%d.txt" % i, "content": "data", "ts": "2026-01-01 00:00:00",
                })
            report = fm.recover()
            recovery_rows.append((pending, report.duration_ms, len(report.redone)))

    out("")
    out("Average time per operation (%d operations each):" % n)
    for name, ms in results:
        out("  %-18s %8.3f ms" % (name, ms))
    out("")
    out("Recovery time (includes the consistency check):")
    out("  %-22s %12s %10s" % ("unfinished operations", "recovery ms", "redone"))
    for pending, ms, redone in recovery_rows:
        out("  %-22d %12.2f %10d" % (pending, ms, redone))
    out("")
    return results, recovery_rows
