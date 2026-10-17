"""
Tests for interrupted operations, restart and recovery.

The big idea: for EVERY operation and EVERY crash point we
  1. build a known starting state,
  2. crash the operation at the chosen point,
  3. restart (automatic recovery),
  4. check the outcome against the documented recovery policy.
"""

from errors import SimulatedCrash, VFSafeError
from journal import Journal
from tests.helpers import VFSTestCase

# Starting state used by every scenario
START = {"a.txt": "AAA", "b.txt": "BBB"}

# name -> (function that runs the operation, state if it happened, state if it did not)
OPERATIONS = {
    "create": (lambda fm: fm.create("new.txt", "NEW"),
               dict(START, **{"new.txt": "NEW"})),
    "write": (lambda fm: fm.write("a.txt", "CHANGED"),
              dict(START, **{"a.txt": "CHANGED"})),
    "append": (lambda fm: fm.append("a.txt", "+MORE"),
               dict(START, **{"a.txt": "AAA+MORE"})),
    "rename": (lambda fm: fm.rename("a.txt", "z.txt"),
               {"z.txt": "AAA", "b.txt": "BBB"}),
    "delete": (lambda fm: fm.delete("a.txt"),
               {"b.txt": "BBB"}),
}

# Crash points after which the operation is ROLLED FORWARD (completed by recovery)
ROLL_FORWARD = ["after_journal", "during_apply", "after_apply"]
# Crash points after which the operation NEVER HAPPENED
NEVER_HAPPENED = ["before_journal", "during_journal"]


class CrashMatrixTest(VFSTestCase):
    def setUp(self):
        super().setUp()
        for name, text in START.items():
            self.fm.create(name, text)

    def run_scenario(self, op_name, point):
        action, _ = OPERATIONS[op_name]
        fm = self.restart()
        self.crash(fm, point, action, fm)
        return self.restart()          # <-- the "restart": recovery runs automatically

    def test_crash_before_apply_is_rolled_forward(self):
        """Crash AFTER the journal record but BEFORE any change was applied."""
        for op in OPERATIONS:
            with self.subTest(op=op):
                self.reset_storage()
                fm = self.run_scenario(op, "after_journal")
                self.assertEqual(self.contents(fm), OPERATIONS[op][1])
                self.assertEqual(len(fm.recovery_report.redone), 1)

    def test_crash_during_apply_is_rolled_forward(self):
        for op in OPERATIONS:
            with self.subTest(op=op):
                self.reset_storage()
                fm = self.run_scenario(op, "during_apply")
                self.assertEqual(self.contents(fm), OPERATIONS[op][1])
                self.assertEqual(len(fm.recovery_report.redone), 1)

    def test_crash_after_apply_before_commit_is_completed(self):
        for op in OPERATIONS:
            with self.subTest(op=op):
                self.reset_storage()
                fm = self.run_scenario(op, "after_apply")
                self.assertEqual(self.contents(fm), OPERATIONS[op][1])
                self.assertEqual(len(fm.recovery_report.redone), 1)

    def test_crash_after_commit_needs_no_recovery(self):
        for op in OPERATIONS:
            with self.subTest(op=op):
                self.reset_storage()
                fm = self.run_scenario(op, "after_commit")
                self.assertEqual(self.contents(fm), OPERATIONS[op][1])
                self.assertEqual(fm.recovery_report.redone, [])
                self.assertTrue(fm.recovery_report.nothing_to_do)

    def test_crash_before_journal_means_operation_never_happened(self):
        for op in OPERATIONS:
            with self.subTest(op=op):
                self.reset_storage()
                fm = self.run_scenario(op, "before_journal")
                self.assertEqual(self.contents(fm), START)
                self.assertTrue(fm.recovery_report.nothing_to_do)

    def test_torn_journal_record_is_discarded_and_operation_never_happened(self):
        for op in OPERATIONS:
            with self.subTest(op=op):
                self.reset_storage()
                fm = self.run_scenario(op, "during_journal")
                self.assertEqual(self.contents(fm), START)
                self.assertGreater(fm.recovery_report.torn_bytes_discarded, 0)
                self.assertEqual(fm.recovery_report.redone, [])

    def test_state_is_consistent_after_recovery_for_every_scenario(self):
        for op in OPERATIONS:
            for point in ROLL_FORWARD + NEVER_HAPPENED + ["after_commit"]:
                with self.subTest(op=op, point=point):
                    self.reset_storage()
                    fm = self.run_scenario(op, point)
                    report = fm.recovery_report.consistency
                    self.assertTrue(report.is_clean, report.summary_lines())
                    self.assertEqual(Journal.pending_from(fm.journal.read_all().records), [])
                    self.assertFalse(fm.journal.read_all().torn_tail)

    def test_new_operations_work_after_recovery(self):
        for point in ROLL_FORWARD + NEVER_HAPPENED:
            with self.subTest(point=point):
                self.reset_storage()
                fm = self.run_scenario("write", point)
                fm.create("after.txt", "still works")
                fm.write("b.txt", "also works")
                self.assertEqual(self.restart().read("after.txt"), "still works")

    def test_transaction_ids_stay_unique_after_recovery(self):
        fm = self.run_scenario("write", "after_journal")
        fm.create("c.txt", "c")
        ids = [r["txid"] for r in fm.journal.read_all().records if r["type"] == "BEGIN"]
        self.assertEqual(len(ids), len(set(ids)))


class DamageBeforeRecoveryTest(VFSTestCase):
    """Prove the crash REALLY leaves the disk inconsistent (so recovery is real)."""

    def setUp(self):
        super().setUp()
        self.fm.create("a.txt", "AAA")

    def crashed_but_not_recovered(self, action):
        self.crash(self.fm, "during_apply", action)
        return self.restart(auto_recover=False)

    def codes(self, fm):
        from consistency import ConsistencyChecker
        return {i.code for i in ConsistencyChecker(fm).check().issues}

    def test_create_crash_leaves_orphan_data_file(self):
        fm = self.crashed_but_not_recovered(lambda: self.fm.create("n.txt", "N"))
        self.assertIn("DATA_WITHOUT_META", self.codes(fm))

    def test_write_crash_leaves_metadata_out_of_date(self):
        fm = self.crashed_but_not_recovered(lambda: self.fm.write("a.txt", "much longer"))
        self.assertIn("SIZE_MISMATCH", self.codes(fm))

    def test_delete_crash_leaves_metadata_without_data(self):
        fm = self.crashed_but_not_recovered(lambda: self.fm.delete("a.txt"))
        self.assertIn("META_WITHOUT_DATA", self.codes(fm))

    def test_rename_crash_leaves_both_problems(self):
        fm = self.crashed_but_not_recovered(lambda: self.fm.rename("a.txt", "b.txt"))
        self.assertTrue({"META_WITHOUT_DATA", "DATA_WITHOUT_META"} <= self.codes(fm))

    def test_recovery_then_repairs_each_of_them(self):
        self.crash(self.fm, "during_apply", self.fm.delete, "a.txt")
        fm = self.restart()
        self.assertTrue(fm.recovery_report.consistency.is_clean)
        self.assertEqual(fm.list_files(), [])


class RecoveryNotRunTest(VFSTestCase):
    def test_changes_are_blocked_until_recovery_has_run(self):
        self.crash(self.fm, "after_journal", self.fm.create, "a.txt", "x")
        inspect = self.restart(auto_recover=False)
        with self.assertRaises(VFSafeError):
            inspect.create("b.txt", "y")
        inspect.recover()
        inspect.create("b.txt", "y")                     # allowed now
        self.assertEqual(self.contents(inspect), {"a.txt": "x", "b.txt": "y"})

    def test_instance_that_crashed_refuses_further_work(self):
        self.crash(self.fm, "after_apply", self.fm.create, "a.txt", "x")
        with self.assertRaises(VFSafeError):
            self.fm.create("b.txt", "y")


class RepeatedRecoveryTest(VFSTestCase):
    def setUp(self):
        super().setUp()
        self.fm.create("a.txt", "AAA")

    def test_running_recovery_many_times_changes_nothing(self):
        for point in ROLL_FORWARD + NEVER_HAPPENED:
            with self.subTest(point=point):
                self.reset_storage()
                self.crash(self.fm, point, self.fm.write, "a.txt", "NEW")
                fm = self.restart()                       # recovery run #1 (at start-up)
                state = self.snapshot(fm)
                journal_bytes = fm.storage.journal_path.read_bytes()
                for run in (2, 3, 4):
                    report = fm.recover()
                    self.assertEqual(report.redone, [], "run %d redid something" % run)
                    self.assertEqual(self.snapshot(fm), state)
                    self.assertEqual(fm.storage.journal_path.read_bytes(), journal_bytes)

    def test_each_operation_is_written_to_journal_committed_exactly_once(self):
        self.crash(self.fm, "after_apply", self.fm.write, "a.txt", "NEW")
        fm = self.restart()
        fm.recover()
        fm.recover()
        commits = [r for r in fm.journal.read_all().records
                   if r["type"] == "COMMIT" and r["txid"] == 2]
        self.assertEqual(len(commits), 1)
        self.assertEqual(commits[0]["by"], "recovery")

    def test_redo_of_an_already_applied_operation_is_harmless(self):
        """after_apply: the change is ALREADY on disk; recovery redoes it anyway."""
        self.crash(self.fm, "after_apply", self.fm.append, "a.txt", "+X")
        fm = self.restart()
        self.assertEqual(fm.read("a.txt"), "AAA+X")      # not "AAA+X+X"
        self.assertEqual(fm.stat("a.txt")["size"], 5)

    def test_crash_during_recovery_then_recover_again(self):
        self.crash(self.fm, "after_journal", self.fm.write, "a.txt", "NEW")
        fm = self.restart(auto_recover=False)
        fm.crash.arm("during_recovery")                  # recovery dies after redo, before COMMIT
        with self.assertRaises(SimulatedCrash):
            fm.recover()
        fm2 = self.restart()                             # the next start-up finishes the job
        self.assertEqual(fm2.read("a.txt"), "NEW")
        self.assertEqual(len(fm2.recovery_report.redone), 1)
        self.assertTrue(fm2.recovery_report.consistency.is_clean)
        self.assertEqual(self.restart().recovery_report.redone, [])

    def test_crash_in_the_middle_of_recovery_apply_then_recover_again(self):
        self.crash(self.fm, "after_journal", self.fm.rename, "a.txt", "c.txt")
        fm = self.restart(auto_recover=False)
        fm.crash.arm("during_apply")                     # dies between data step and metadata step
        with self.assertRaises(SimulatedCrash):
            fm.recover()
        fm2 = self.restart()
        self.assertEqual(self.contents(fm2), {"c.txt": "AAA"})
        self.assertTrue(fm2.recovery_report.consistency.is_clean)

    def test_several_crashes_in_a_row(self):
        fm = self.fm
        self.crash(fm, "after_apply", fm.write, "a.txt", "ONE")
        fm = self.restart()
        self.crash(fm, "during_apply", fm.write, "a.txt", "TWO")
        fm = self.restart()
        self.crash(fm, "during_journal", fm.write, "a.txt", "THREE")
        fm = self.restart()
        self.assertEqual(fm.read("a.txt"), "TWO")        # THREE never became official
        self.assertTrue(fm.recovery_report.consistency.is_clean)

    def test_multiple_pending_operations_are_redone_in_order(self):
        fm = self.restart(auto_recover=False)
        for txid, text in ((10, "first"), (11, "second"), (12, "third")):
            fm.journal.append({"type": "BEGIN", "txid": txid, "op": "write", "name": "a.txt",
                               "content": text, "ts": "2026-01-01 00:00:00"})
        report = fm.recover()
        self.assertEqual([r["txid"] for r in report.redone], [10, 11, 12])
        self.assertEqual(fm.read("a.txt"), "third")

    def test_leftover_temp_files_are_cleaned(self):
        (self.fm.storage.tmp_dir / "w-leftover.tmp").write_text("junk")
        fm = self.restart()
        self.assertEqual(fm.recovery_report.temp_files_removed, 1)
        self.assertEqual(fm.storage.list_tmp_files(), [])
