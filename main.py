"""
main.py - the command-line interface (CLI) of VFSafe.

Two ways to use it:

  1) One command at a time:      python main.py create notes.txt "hello"
  2) Interactive shell:          python main.py shell

Run  python main.py --help  to see everything.

Every time the program starts it runs crash recovery FIRST - that is the
"automatic recovery when the application restarts" feature.
"""

import argparse
import shlex
import sys
from pathlib import Path

from benchmark import run_benchmark
from crash import CRASH_POINTS, OPERATION_CRASH_POINTS
from errors import SimulatedCrash, VFSafeError
from file_manager import FileManager
from storage import Storage

DEFAULT_STORAGE = Path(__file__).resolve().parent / "storage"
EXIT_OK, EXIT_ERROR, EXIT_CRASH = 0, 1, 99


# --------------------------------------------------------------------- parser
def build_parser():
    crash_help = "simulate a crash at a chosen point: " + ", ".join(OPERATION_CRASH_POINTS)
    crash_opts = argparse.ArgumentParser(add_help=False)
    crash_opts.add_argument("--crash-at", choices=OPERATION_CRASH_POINTS, metavar="POINT",
                            help=crash_help)

    parser = argparse.ArgumentParser(
        prog="main.py",
        description="VFSafe - a virtual file system with journaling and crash recovery.",
        epilog="Crash points: " + "; ".join("%s = %s" % kv for kv in CRASH_POINTS.items()
                                            if kv[0] != "during_recovery"),
    )
    parser.add_argument("--storage", default=str(DEFAULT_STORAGE),
                        help="storage folder (default: ./storage inside the project)")
    parser.add_argument("--no-recover", action="store_true",
                        help="inspect mode: skip start-up recovery so you can look at a crashed "
                             "state (use with journal / fsck / ls / read)")
    sub = parser.add_subparsers(dest="command", metavar="command")
    sub.required = True

    p = sub.add_parser("create", parents=[crash_opts], help="create a new file")
    p.add_argument("name"); p.add_argument("content", nargs="?", default="")
    p = sub.add_parser("read", help="print a file's content")
    p.add_argument("name")
    p = sub.add_parser("write", parents=[crash_opts], help="replace a file's content")
    p.add_argument("name"); p.add_argument("content")
    p = sub.add_parser("append", parents=[crash_opts], help="add text to the end of a file")
    p.add_argument("name"); p.add_argument("content")
    p = sub.add_parser("rename", parents=[crash_opts], help="rename a file")
    p.add_argument("old_name"); p.add_argument("new_name")
    p = sub.add_parser("delete", parents=[crash_opts], help="delete a file")
    p.add_argument("name")
    sub.add_parser("ls", help="list all files")
    p = sub.add_parser("stat", help="show a file's metadata")
    p.add_argument("name")
    sub.add_parser("fsck", help="run the consistency check")
    sub.add_parser("journal", help="show the journal (transaction log)")
    sub.add_parser("recover", help="run recovery now (it also runs automatically at start-up)")
    sub.add_parser("checkpoint", help="empty the journal (only when nothing is pending)")
    p = sub.add_parser("benchmark", help="measure operation and recovery time")
    p.add_argument("-n", "--ops", type=int, default=100, help="operations per test (default 100)")
    p = sub.add_parser("reset", help="delete ALL virtual files, metadata and journal")
    p.add_argument("--yes", action="store_true", help="confirm the reset")
    sub.add_parser("shell", help="start the interactive shell")
    return parser


# ------------------------------------------------------------------- commands
def show_journal(fm):
    scan = fm.journal.read_all()
    commits = {r["txid"]: r for r in scan.records if r["type"] == "COMMIT"}
    print("%-5s %-10s %-8s %s" % ("TXID", "STATE", "OP", "DETAILS"))
    print("-" * 60)
    if not scan.records:
        print("(journal is empty)")
    for rec in scan.records:
        if rec["type"] == "CHECKPOINT":
            print("%-5s %-10s %-8s %s" % (rec["txid"], "-", "-", "(checkpoint: older records removed)"))
        elif rec["type"] == "BEGIN":
            if rec["op"] == "rename":
                detail = "%s -> %s" % (rec["name"], rec["new_name"])
            elif rec["op"] == "delete":
                detail = rec["name"]
            else:
                detail = "%s (%d chars)" % (rec["name"], len(rec["content"]))
            commit = commits.get(rec["txid"])
            state = "COMMITTED" if commit else "PENDING"
            if commit and commit.get("by") == "recovery":
                detail += "   [committed by recovery]"
            print("%-5s %-10s %-8s %s" % (rec["txid"], state, rec["op"], detail))
    if scan.torn_tail:
        print("!! last journal record is incomplete (%d bytes) - recovery will discard it"
              % scan.torn_bytes)
    for line_no, reason in scan.bad_lines:
        print("!! journal line %d is damaged (%s)" % (line_no, reason))


def run_command(fm, args):
    """Execute one parsed command. May raise VFSafeError or SimulatedCrash."""
    cmd = args.command
    crash_at = getattr(args, "crash_at", None)
    if crash_at:
        fm.crash.arm(crash_at)
        print("[crash armed] this operation will crash at '%s'" % crash_at)

    if cmd == "create":
        fm.create(args.name, args.content)
        print("Created '%s'." % args.name)
    elif cmd == "read":
        text = fm.read(args.name)
        print(text)
    elif cmd == "write":
        fm.write(args.name, args.content)
        print("Wrote '%s'." % args.name)
    elif cmd == "append":
        fm.append(args.name, args.content)
        print("Appended to '%s'." % args.name)
    elif cmd == "rename":
        fm.rename(args.old_name, args.new_name)
        print("Renamed '%s' to '%s'." % (args.old_name, args.new_name))
    elif cmd == "delete":
        fm.delete(args.name)
        print("Deleted '%s'." % args.name)
    elif cmd == "ls":
        files = fm.list_files()
        if not files:
            print("(no files)")
        else:
            print("%-24s %8s  %s" % ("NAME", "SIZE", "MODIFIED"))
            for f in files:
                print("%-24s %8d  %s" % (f["name"], f["size"], f["modified"]))
            print("%d file(s)" % len(files))
    elif cmd == "stat":
        info = fm.stat(args.name)
        for key in ("name", "size", "sha256", "created", "modified", "last_op", "last_txid"):
            print("%-10s %s" % (key + ":", info[key]))
    elif cmd == "fsck":
        from consistency import ConsistencyChecker
        print("\n".join(ConsistencyChecker(fm).check().summary_lines()))
    elif cmd == "journal":
        show_journal(fm)
    elif cmd == "recover":
        print("\n".join(fm.recover().summary_lines()))
    elif cmd == "checkpoint":
        removed = fm.journal.checkpoint()
        print("Journal emptied (%d record(s) removed)." % removed)
    else:
        raise VFSafeError("Command '%s' is not available here." % cmd)


def crash_message(point):
    return ("\n[CRASH] Simulated crash at '%s'.\n"
            "        The program stopped abruptly - nothing more was written.\n"
            "        Start the program again: recovery will run automatically." % point)


def open_file_manager(storage, recover=True):
    """Open the storage. With recover=True this IS the automatic crash recovery."""
    fm = FileManager(storage, auto_recover=recover)
    report = fm.recovery_report
    if report is None:
        print("[startup] INSPECT MODE (--no-recover): recovery was skipped on purpose.")
        print("[startup] Changing commands are blocked until you run recovery.")
    elif report.nothing_to_do and report.consistency.is_clean and not report.bad_lines:
        print("[startup] Journal clean, nothing to recover. Consistency OK (%d file(s))."
              % report.consistency.files_checked)
    else:
        print("[startup] storage: %s" % fm.storage.root)
        for line in report.summary_lines():
            print("[startup] " + line)
    return fm


# ---------------------------------------------------------------------- shell
SHELL_HELP = """Commands:
  create NAME [CONTENT]      read NAME            write NAME CONTENT
  append NAME CONTENT        rename OLD NEW       delete NAME
  ls                         stat NAME            fsck
  journal                    recover              checkpoint
  crash-at POINT             arm a crash for the NEXT changing operation
  crash-points               list the crash points
  help                       exit
Put text with spaces in "double quotes".  Crash points:
  """ + ", ".join(OPERATION_CRASH_POINTS)


def run_shell(fm, parser):
    print("VFSafe shell. Type 'help' for commands, 'exit' to quit.")
    while True:
        try:
            line = input("vfsafe> ")
        except (EOFError, KeyboardInterrupt):
            print()
            return EXIT_OK
        try:
            words = shlex.split(line)
        except ValueError as exc:
            print("Error: %s" % exc)
            continue
        if not words:
            continue
        head = words[0].lower()
        if head in ("exit", "quit"):
            return EXIT_OK
        if head == "help":
            print(SHELL_HELP)
            continue
        if head == "crash-points":
            for point, text in CRASH_POINTS.items():
                if point != "during_recovery":
                    print("  %-15s %s" % (point, text))
            continue
        if head == "crash-at":
            if len(words) != 2 or words[1] not in OPERATION_CRASH_POINTS:
                print("Usage: crash-at POINT   (one of: %s)" % ", ".join(OPERATION_CRASH_POINTS))
            else:
                fm.crash.arm(words[1])
                print("[crash armed] the next changing operation will crash at '%s'" % words[1])
            continue
        try:
            args = parser.parse_args(words)
        except SystemExit:           # argparse already printed a usage message
            continue
        if args.command in ("shell", "benchmark", "reset"):
            print("That command is not available inside the shell.")
            continue
        try:
            run_command(fm, args)
        except SimulatedCrash as crash:
            print(crash_message(crash.point))
            return EXIT_CRASH
        except VFSafeError as exc:
            print("Error: %s" % exc)


# ----------------------------------------------------------------------- main
def _make_output_safe():
    """Old Windows consoles cannot show every character; print '?' instead of crashing."""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="replace")
        except (AttributeError, ValueError):
            pass


def main(argv=None):
    _make_output_safe()
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        if args.command == "benchmark":
            if args.ops < 1:
                raise VFSafeError("--ops must be at least 1.")
            print("Running benchmark in a temporary folder (your storage is not touched)...")
            run_benchmark(args.ops)
            return EXIT_OK
        if args.command == "reset":
            if not args.yes:
                raise VFSafeError("This deletes ALL virtual files. Add --yes to confirm.")
            storage = Storage(args.storage)
            storage.initialize()    # accepts a new/empty folder; REFUSES a folder with other files
            storage.reset()
            print("Storage reset: all virtual files, metadata and journal deleted.")
            return EXIT_OK

        fm = open_file_manager(args.storage, recover=not args.no_recover)
        if args.command == "shell":
            return run_shell(fm, parser)
        run_command(fm, args)
        return EXIT_OK
    except SimulatedCrash as crash:
        print(crash_message(crash.point))
        return EXIT_CRASH
    except VFSafeError as exc:
        print("Error: %s" % exc)
        return EXIT_ERROR
    except OSError as exc:
        print("Error: operating-system problem: %s" % exc)
        return EXIT_ERROR


if __name__ == "__main__":
    sys.exit(main())
