"""
file_manager.py - the File Operation Manager (the heart of VFSafe).

Every changing operation (create / write / append / rename / delete) follows
the SAME 5 steps:

    1. validate the input                    (bad input never touches the journal)
    2. write BEGIN to the journal  (+fsync)  <- "write-ahead": note first ...
    3. apply the change to data + metadata   <- ... then do the work
    4. write COMMIT to the journal (+fsync)  <- "it is done"
    5. report success to the user            (only after COMMIT)

Between the steps there are crash checkpoints (see crash.py). If the program
dies at any of them, recovery.py repairs the state at the next start-up.
"""

import time

from crash import CrashSimulator
from errors import (
    FileAlreadyExistsError,
    FileMissingError,
    SimulatedCrash,
    VFSafeError,
)
from journal import Journal
from metadata import MetadataManager
from recovery import RecoveryManager
from storage import Storage
from validation import validate_content, validate_name


def now_string():
    return time.strftime("%Y-%m-%d %H:%M:%S")


class FileManager:
    def __init__(self, storage_root, auto_recover=True, crash=None):
        """
        storage_root : folder that holds the whole virtual file system
        auto_recover : run crash recovery right now (this is what "restart" does)
        crash        : optional CrashSimulator (a new one is created if omitted)
        """
        self.storage = Storage(storage_root)
        self.storage.initialize()
        self.crash = crash if crash is not None else CrashSimulator()
        self.metadata = MetadataManager(self.storage)
        self.journal = Journal(self.storage.journal_path, crash=self.crash)
        self.recovery_report = None
        self._blocked_reason = None

        if auto_recover:
            self.recovery_report = self.recover()
        else:
            scan = self.journal.read_all()
            if scan.torn_tail or Journal.pending_from(scan.records):
                self._blocked_reason = (
                    "The journal contains unfinished work. Run recovery before new operations."
                )

    # =========================================================== public: recovery
    def recover(self):
        """Run crash recovery now. Safe to call as often as you like."""
        try:
            report = RecoveryManager(self).recover()
        except SimulatedCrash:
            self._blocked_reason = "This FileManager 'crashed'. Create a new one to restart."
            raise
        self._blocked_reason = None
        return report

    # ========================================================= public: operations
    def create(self, name, content=""):
        self._check_not_blocked()
        name = validate_name(name)
        content = validate_content(content)
        if self.metadata.find_ci(name) is not None:
            raise FileAlreadyExistsError("File '%s' already exists." % name)
        return self._run("create", name=name, content=content)

    def write(self, name, content):
        self._check_not_blocked()
        actual = self._resolve(name)
        content = validate_content(content)
        return self._run("write", name=actual, content=content)

    def append(self, name, text):
        self._check_not_blocked()
        actual = self._resolve(name)
        new_content = validate_content(self.storage.read_file(actual) + validate_content(text))
        # The journal stores the FINAL content, so redoing it twice is harmless.
        return self._run("append", name=actual, content=new_content)

    def rename(self, old_name, new_name):
        self._check_not_blocked()
        old_actual = self._resolve(old_name)
        new_name = validate_name(new_name)
        if old_actual.lower() == new_name.lower():
            raise VFSafeError("The new name is the same as the old name.")
        if self.metadata.find_ci(new_name) is not None:
            raise FileAlreadyExistsError("Cannot rename: '%s' already exists." % new_name)
        return self._run("rename", name=old_actual, new_name=new_name)

    def delete(self, name):
        self._check_not_blocked()
        actual = self._resolve(name)
        return self._run("delete", name=actual)

    # ============================================================ public: queries
    def read(self, name):
        return self.storage.read_file(self._resolve(name))

    def stat(self, name):
        actual = self._resolve(name)
        info = dict(self.metadata.get(actual))
        info["name"] = actual
        return info

    def list_files(self):
        result = []
        for name in self.metadata.names():
            info = dict(self.metadata.get(name))
            info["name"] = name
            result.append(info)
        return result

    # ======================================================== the apply step (REDO)
    def apply(self, record):
        """
        Perform the change described by a BEGIN record.

        Used by normal operations AND by recovery. Every branch is REPEATABLE
        (idempotent): running it again after it already finished changes nothing.
        The crash checkpoint sits between the data step and the metadata step,
        which is exactly where an unlucky crash leaves the two out of sync.
        """
        op, name = record["op"], record["name"]
        txid, ts = record["txid"], record.get("ts", now_string())

        if op in ("create", "write", "append"):
            content = record["content"]
            self.storage.write_file(name, content)                 # step 1: data
            self.crash.checkpoint("during_apply")
            self.metadata.put(name, content, txid, op, ts)         # step 2: metadata
        elif op == "delete":
            self.storage.delete_file(name)
            self.crash.checkpoint("during_apply")
            self.metadata.remove(name)
        elif op == "rename":
            new_name = record["new_name"]
            self.storage.rename_file(name, new_name)
            self.crash.checkpoint("during_apply")
            self.metadata.rename(name, new_name, txid, ts)
        else:
            raise VFSafeError("Unknown operation '%s' in journal." % op)

    # ================================================================== internals
    def _resolve(self, name):
        """Validate `name` and return the stored spelling of it (case-insensitive)."""
        name = validate_name(name)
        actual = self.metadata.find_ci(name)
        if actual is None:
            raise FileMissingError("File '%s' does not exist." % name)
        return actual

    def _check_not_blocked(self):
        if self._blocked_reason:
            raise VFSafeError(self._blocked_reason)

    def _run(self, op, **fields):
        self._check_not_blocked()
        crash = self.crash
        try:
            crash.checkpoint("before_journal")
            txid = self.journal.next_txid()
            record = {"type": "BEGIN", "txid": txid, "op": op, "ts": now_string()}
            record.update(fields)
            self.journal.append(record)               # (2) write-ahead: BEGIN
            crash.checkpoint("after_journal")
            self.apply(record)                        # (3) apply (has during_apply inside)
            crash.checkpoint("after_apply")
            self.journal.append(                      # (4) COMMIT
                {"type": "COMMIT", "txid": txid, "by": "normal", "ts": now_string()}
            )
            crash.checkpoint("after_commit")
            return txid                               # (5) success
        except SimulatedCrash:
            self._blocked_reason = "This FileManager 'crashed'. Create a new one to restart."
            raise
