"""End-to-end tests that run main.py as a REAL separate process.

This is the closest thing to a real crash: the process exits with code 99
right after the simulated crash, so no in-memory state can survive.
"""

import subprocess
import sys
from pathlib import Path

from tests.helpers import VFSTestCase

MAIN = str(Path(__file__).resolve().parent.parent / "main.py")


class CliTest(VFSTestCase):
    def cli(self, *args):
        result = subprocess.run(
            [sys.executable, MAIN, "--storage", str(self.root)] + list(args),
            capture_output=True, text=True, timeout=60,
        )
        return result.returncode, result.stdout + result.stderr

    def test_create_and_read(self):
        self.assertEqual(self.cli("create", "a.txt", "hello CLI")[0], 0)
        code, out = self.cli("read", "a.txt")
        self.assertEqual(code, 0)
        self.assertIn("hello CLI", out)

    def test_error_gives_friendly_message_and_exit_code_1(self):
        code, out = self.cli("read", "missing.txt")
        self.assertEqual(code, 1)
        self.assertIn("does not exist", out)
        self.assertNotIn("Traceback", out)

    def test_invalid_name_message(self):
        code, out = self.cli("create", "bad name.txt", "x")
        self.assertEqual(code, 1)
        self.assertIn("illegal characters", out)

    def test_crash_exits_with_99_and_next_start_recovers(self):
        self.cli("create", "a.txt", "old")
        code, out = self.cli("write", "a.txt", "new", "--crash-at", "after_journal")
        self.assertEqual(code, 99)
        self.assertIn("[CRASH]", out)

        code, out = self.cli("--no-recover", "journal")        # inspect the crashed state
        self.assertIn("PENDING", out)

        code, out = self.cli("read", "a.txt")                  # normal start => recovery
        self.assertEqual(code, 0)
        self.assertIn("REDONE", out)
        self.assertIn("new", out)

        code, out = self.cli("journal")
        self.assertNotIn("PENDING", out)
        self.assertIn("committed by recovery", out)

    def test_torn_journal_crash_via_cli(self):
        self.cli("create", "a.txt", "keep")
        self.assertEqual(self.cli("write", "a.txt", "lost", "--crash-at", "during_journal")[0], 99)
        code, out = self.cli("read", "a.txt")
        self.assertIn("DISCARDED", out)
        self.assertIn("keep", out)
        self.assertNotIn("lost", out.replace("DISCARDED", ""))

    def test_fsck_reports_ok_after_recovery(self):
        self.cli("create", "a.txt", "x")
        self.cli("rename", "a.txt", "b.txt", "--crash-at", "during_apply")
        code, out = self.cli("fsck")
        self.assertEqual(code, 0)
        self.assertIn("Consistency check: OK", out)

    def test_reset_needs_confirmation(self):
        self.cli("create", "a.txt", "x")
        code, out = self.cli("reset")
        self.assertEqual(code, 1)
        self.assertEqual(self.cli("reset", "--yes")[0], 0)
        self.assertIn("(no files)", self.cli("ls")[1])

    def test_reset_works_on_a_brand_new_storage_folder(self):
        code, out = self.cli("reset", "--yes")           # nothing exists yet
        self.assertEqual(code, 0, out)

    def test_reset_refuses_a_folder_with_foreign_files(self):
        foreign = self.root.parent / "precious"
        foreign.mkdir()
        (foreign / "thesis.docx").write_text("irreplaceable")
        result = subprocess.run([sys.executable, MAIN, "--storage", str(foreign), "reset", "--yes"],
                                capture_output=True, text=True, timeout=60)
        self.assertEqual(result.returncode, 1)
        self.assertEqual((foreign / "thesis.docx").read_text(), "irreplaceable")
        self.assertEqual([p.name for p in foreign.iterdir()], ["thesis.docx"])

    def test_reading_unicode_never_crashes_even_on_an_ascii_only_console(self):
        import os
        text = "caf\u00e9 \u0928\u092e\u0938\u094d\u0924\u0947"
        self.assertEqual(self.cli("create", "u.txt", text)[0], 0)
        env = dict(os.environ, PYTHONIOENCODING="ascii")        # like an old Windows console
        result = subprocess.run([sys.executable, MAIN, "--storage", str(self.root), "read", "u.txt"],
                                capture_output=True, text=True, timeout=60, env=env)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("Traceback", result.stderr)

    def test_benchmark_runs(self):
        code, out = self.cli("benchmark", "-n", "5")
        self.assertEqual(code, 0)
        self.assertIn("Average time per operation", out)
        self.assertIn("Recovery time", out)

    def test_demo_script_runs(self):
        demo = str(Path(MAIN).parent / "demo.py")
        result = subprocess.run([sys.executable, demo], capture_output=True, text=True, timeout=120)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Files unchanged: True", result.stdout)
