"""
demo.py - a scripted, automatic demonstration of crash recovery.

Run:   python demo.py

It uses a temporary folder (deleted at the end), so it never touches your
own storage. For each crash point it shows:
    BEFORE restart  -> what the disk looks like right after the crash
    AFTER restart   -> what automatic recovery did
"""

import tempfile
from pathlib import Path

from consistency import ConsistencyChecker
from errors import SimulatedCrash
from file_manager import FileManager
from main import show_journal


def banner(text):
    print("\n" + "=" * 70)
    print(text)
    print("=" * 70)


def crash_and_restart(root, point, label, action, check):
    """Crash an operation at `point`, show the damage, restart, show the repair."""
    banner("SCENARIO: crash at '%s'  (%s)" % (point, label))
    fm = FileManager(root)
    fm.crash.arm(point)
    print(">>> %s   [crash armed at %s]" % (label, point))
    try:
        action(fm)
    except SimulatedCrash:
        print("[CRASH] the program died here.\n")

    print("--- Disk state right after the crash (recovery NOT run yet) ---")
    inspect = FileManager(root, auto_recover=False)
    show_journal(inspect)
    print("\n".join(ConsistencyChecker(inspect).check().summary_lines()))

    print("\n--- Restarting the program (automatic recovery) ---")
    restarted = FileManager(root)
    print("\n".join(restarted.recovery_report.summary_lines()))
    print("Result: %s" % check(restarted))
    return restarted


def files_of(fm):
    return {f["name"]: fm.read(f["name"]) for f in fm.list_files()}


def main():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / "demo_storage"
        fm = FileManager(root)
        fm.create("notes.txt", "version 1")
        fm.create("todo.txt", "buy milk")
        banner("SETUP: two committed files")
        print(files_of(fm))

        crash_and_restart(root, "before_journal", "write notes.txt 'version 2'",
                          lambda f: f.write("notes.txt", "version 2"),
                          lambda f: "notes.txt = %r (old content: the operation never started)"
                          % f.read("notes.txt"))

        crash_and_restart(root, "during_journal", "write notes.txt 'version 2'",
                          lambda f: f.write("notes.txt", "version 2"),
                          lambda f: "notes.txt = %r (torn record discarded: operation never happened)"
                          % f.read("notes.txt"))

        crash_and_restart(root, "after_journal", "write notes.txt 'version 2'",
                          lambda f: f.write("notes.txt", "version 2"),
                          lambda f: "notes.txt = %r (rolled forward by recovery)"
                          % f.read("notes.txt"))

        crash_and_restart(root, "during_apply", "rename todo.txt -> tasks.txt",
                          lambda f: f.rename("todo.txt", "tasks.txt"),
                          lambda f: "files = %s (rename completed by recovery)"
                          % sorted(files_of(f)))

        crash_and_restart(root, "after_apply", "delete notes.txt",
                          lambda f: f.delete("notes.txt"),
                          lambda f: "files = %s (change was applied; recovery only wrote the COMMIT)"
                          % sorted(files_of(f)))

        crash_and_restart(root, "after_commit", "create report.txt",
                          lambda f: f.create("report.txt", "final"),
                          lambda f: "files = %s (already committed: nothing to recover)"
                          % sorted(files_of(f)))

        banner("REPEATED RECOVERY: run recovery two more times - nothing should change")
        fm = FileManager(root)
        before = files_of(fm)
        for run in (1, 2):
            report = fm.recover()
            print("run %d: redone=%d, consistent=%s"
                  % (run, len(report.redone), report.consistency.is_consistent))
        print("Files unchanged:", before == files_of(fm))

        banner("FINAL JOURNAL")
        show_journal(fm)
    print("\nDemo finished. (The temporary demo storage was deleted.)")


if __name__ == "__main__":
    main()
