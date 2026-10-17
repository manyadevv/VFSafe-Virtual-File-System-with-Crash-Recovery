"""
consistency.py - the Consistency Checker (a tiny "fsck").

It compares three things that must agree with each other:
    1. metadata.json  (what we THINK exists)
    2. storage/data/  (what REALLY exists)
    3. journal.log    (is any operation unfinished?)

It only REPORTS problems. Fixing is the job of recovery.py.
"""

from collections import defaultdict
from dataclasses import dataclass, field
from typing import List

from errors import InvalidNameError
from storage import bytes_info
from validation import validate_name


@dataclass
class Issue:
    severity: str   # "ERROR" (file system is inconsistent) or "WARNING"
    code: str
    message: str


@dataclass
class ConsistencyReport:
    files_checked: int = 0
    issues: List[Issue] = field(default_factory=list)

    @property
    def errors(self):
        return [i for i in self.issues if i.severity == "ERROR"]

    @property
    def warnings(self):
        return [i for i in self.issues if i.severity == "WARNING"]

    @property
    def is_consistent(self):
        """True when there are no ERRORs (warnings are allowed)."""
        return not self.errors

    @property
    def is_clean(self):
        """True when there are no problems at all."""
        return not self.issues

    def summary_lines(self):
        if self.is_clean:
            return ["Consistency check: OK (%d file(s) verified, no problems)" % self.files_checked]
        lines = [
            "Consistency check: %d error(s), %d warning(s) (%d file(s) checked)"
            % (len(self.errors), len(self.warnings), self.files_checked)
        ]
        for issue in self.issues:
            lines.append("  [%s] %s: %s" % (issue.severity, issue.code, issue.message))
        return lines


class ConsistencyChecker:
    def __init__(self, file_manager):
        self.fm = file_manager

    def check(self):
        fm = self.fm
        report = ConsistencyReport()
        fm.metadata.load()                       # always compare with what is on disk
        meta = fm.metadata.files
        data_names = set(fm.storage.list_data_files())
        report.files_checked = len(meta)

        def add(severity, code, message):
            report.issues.append(Issue(severity, code, message))

        # 1. every metadata entry must have a matching, intact data file
        for name in sorted(meta):
            entry = meta[name]
            try:
                validate_name(name)
            except InvalidNameError as exc:
                add("ERROR", "INVALID_NAME", "metadata has an illegal name: %s" % exc)
                continue
            if name not in data_names:
                add("ERROR", "META_WITHOUT_DATA",
                    "'%s' is listed in metadata but its data file is missing" % name)
                continue
            size, digest = bytes_info(fm.storage.file_path(name).read_bytes())
            if size != entry.get("size"):
                add("ERROR", "SIZE_MISMATCH",
                    "'%s': metadata says %s bytes, file has %d bytes"
                    % (name, entry.get("size"), size))
            elif digest != entry.get("sha256"):
                add("ERROR", "CHECKSUM_MISMATCH",
                    "'%s': content does not match the recorded checksum" % name)

        # 2. every data file must be listed in metadata
        for name in sorted(data_names - set(meta)):
            add("ERROR", "DATA_WITHOUT_META",
                "'%s' exists in storage but is not listed in metadata (orphan file)" % name)

        # 3. two names that differ only by upper/lower case would clash on Windows
        groups = defaultdict(list)
        for name in meta:
            groups[name.lower()].append(name)
        for names in groups.values():
            if len(names) > 1:
                add("ERROR", "CASE_COLLISION", "names differ only by case: %s" % ", ".join(sorted(names)))

        # 4. leftovers of an interrupted safe-write
        tmp_files = fm.storage.list_tmp_files()
        if tmp_files:
            add("WARNING", "TEMP_FILES", "%d leftover temp file(s) in tmp/" % len(tmp_files))

        # 5. journal health
        scan = fm.journal.read_all()
        pending = fm.journal.pending_from(scan.records)
        if pending:
            add("WARNING", "PENDING_OPERATIONS",
                "%d operation(s) in the journal have no COMMIT (recovery needed): txid %s"
                % (len(pending), ", ".join(str(r["txid"]) for r in pending)))
        if scan.torn_tail:
            add("WARNING", "TORN_JOURNAL_TAIL",
                "the last journal record is incomplete (%d bytes)" % scan.torn_bytes)
        for line_no, reason in scan.bad_lines:
            add("WARNING", "BAD_JOURNAL_RECORD", "journal line %d is damaged (%s)" % (line_no, reason))

        return report
