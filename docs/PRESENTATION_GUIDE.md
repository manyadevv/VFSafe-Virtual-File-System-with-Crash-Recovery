# VFSafe – Presentation Guide (Review: Tuesday, 20 October 2026)

## 1. Three-day plan

| Day | Do this |
|---|---|
| **Sat 17 Oct** | Unzip, run `python demo.py`, `python -m unittest -v`, and the demo in README §4. Everyone runs it on their *own* laptop. |
| **Sun 18 Oct** | Each person reads their own modules (section 4 below) and answers the viva questions out loud. Run `python main.py benchmark -n 100` on your laptop and note *your* numbers. Capture the screenshots (README §10). |
| **Mon 19 Oct** | Full rehearsal with a timer (target: 5–6 minutes). Practise one "live change" (section 5). Zip the folder as a backup and keep a copy on a pen drive. |

---

## 2. One-minute explanation for the faculty (about 150 words, ~60 seconds)

> "Our project is **VFSafe**, a small virtual file system in Python with **crash recovery**. The problem: when a program
> updates a file, it must change both the file *and* its details like size. If it stops in the middle, the two
> disagree and the file system is inconsistent.
>
> We solve it with **write-ahead logging**. Before every operation we write a **BEGIN** record to a journal, containing
> everything needed to repeat the operation. Then we apply the change, and finally write a **COMMIT** record.
>
> We can **simulate a crash** at six chosen points. When the program restarts, **recovery runs automatically**: any
> operation with BEGIN but no COMMIT is redone safely, a half-written journal record is discarded, and a
> **consistency checker** verifies metadata against the stored files.
>
> We tested every operation at every crash point with **93 automated tests**, including running recovery repeatedly.
> It is an educational prototype, not a replacement for a real file system."

---

## 3. Suggested review flow (5–6 minutes)

1. *(30 s)* Problem + one-minute explanation. Show `docs/architecture.png`.
2. *(45 s)* **Manya** – basic operations and validation (README §3, screenshots 02–03).
3. *(75 s)* **Hemanya** – journal + crash simulation: `journal`, then `write … --crash-at after_apply`, then
   `--no-recover journal` showing **PENDING**. Show `docs/operation_flow.png`.
4. *(90 s)* **Tanmoy** – recovery: restart → `REDONE`; `rename … --crash-at during_apply` → `--no-recover fsck`
   shows real inconsistency → recovery fixes it; repeated `recover`. Show `docs/recovery_flowchart.png`.
5. *(45 s)* **Tanmoy** – `python -m unittest -v` (`OK`) and `benchmark`.
6. *(30 s)* **All** – limitations (README "Limitations") and conclusion.

---

## 4. Who presents what

This follows the responsibilities in your proposal (§13). **Every member must still be able to explain the whole flow**
– examiners often ask anyone any question.

### Manya – Virtual file system and file operations
**Modules:** `file_manager.py` (operations), `storage.py`, `metadata.py`, `validation.py`, `errors.py`, `main.py` (CLI)
**Presents:** the five-step operation procedure (validate → BEGIN → apply → COMMIT → success), why bad input never reaches the
journal, the storage folder layout (`data/`, `metadata.json`, `journal.log`), safe atomic writes (temp file + rename),
metadata fields, protection of real files (refuses non-VFSafe folders), friendly error messages.
**Live demo:** create / read / write / append / rename / delete / ls / stat; `create "bad name"`; duplicate create; `read missing.txt`.
**Tests she can show:** `test_basic_operations`, `test_errors_and_validation`.

### Hemanya – Journal and crash simulation
**Modules:** `journal.py`, `crash.py` (and the checkpoint calls inside `file_manager._run`)
**Presents:** what write-ahead logging is, the record format (CRC + JSON; BEGIN / COMMIT / CHECKPOINT), why every record is
flushed with `fsync`, what "pending" means (BEGIN without COMMIT), the six crash points and exactly what each leaves on disk,
why the journal stores the *complete* new content, `checkpoint`.
**Live demo:** `journal` before/after; `--crash-at after_journal`; `--crash-at during_journal` (torn record); `--no-recover journal` showing PENDING; open `storage\journal.log` in VS Code.
**Tests she can show:** `test_journal` (CRC detects a one-letter change; torn line detected).

### Tanmoy – Recovery, consistency checks and testing
**Modules:** `recovery.py`, `consistency.py`, `tests/`, `benchmark.py`, `demo.py`
**Presents:** the recovery policy ("roll forward, or forget"), the table of crash points → outcomes, why redo is
repeatable (idempotent), repeated recovery and crash-during-recovery, the kinds of inconsistency `fsck` detects (missing data, orphan files, size and checksum mismatch, bad names, case clashes, temp leftovers, pending/damaged journal),
the test strategy (every operation × every crash point), and the performance numbers.
**Live demo:** restart after a crash (REDONE message), `--no-recover fsck` showing errors then recovery fixing them,
`recover` twice, `python -m unittest -v`, `benchmark -n 100`.
**Tests he can show:** `test_crash_recovery`, `test_consistency`.

---

## 5. Be ready for a "change it live" request

Faculty sometimes ask for a small modification. Practise these:

* **Add a new crash point** → add an entry in `crash.py` (`CRASH_POINTS`, `OPERATION_CRASH_POINTS`) and a
  `crash.checkpoint("your_point")` call in `file_manager._run`.
* **Change the maximum file size** → `MAX_FILE_BYTES` in `validation.py`.
* **Allow spaces in names** → the regex `_NAME_PATTERN` in `validation.py` (explain the Windows risk first).
* **Make recovery print more detail** → `RecoveryReport.summary_lines()` in `recovery.py`.
* **Show what the journal looks like on disk** → open `storage\journal.log`: each line is `crc json`.

---

## 6. Likely viva questions and answers

**Q1. What problem does your project solve?**
When an update needs several changes (the file *and* its metadata) and the program stops in the middle, only some changes
are saved and the file system becomes inconsistent. VFSafe records each operation first, so after a restart it can finish
or discard unfinished work.

**Q2. What is a journal / write-ahead log?**
An append-only log. Before changing anything we write down what we are about to do and make sure it is on disk; after the
change we write that it is done. "Write-ahead" = the note is written *ahead of* the change.

**Q3. What are BEGIN and COMMIT records?**
BEGIN contains the operation, the file name(s) and the full new content. COMMIT means "operation N finished completely".
A BEGIN without a COMMIT = an incomplete (pending) operation.

**Q4. Explain your recovery policy.**
"Roll forward, or forget." If the BEGIN record is intact and has no COMMIT, recovery **redoes** the operation and writes a
COMMIT. If the last journal line is cut off, it is **discarded** – the operation never became official. Then the consistency
checker runs.

**Q5. What happens if it crashes before the operation is applied?**
Two sub-cases. Before the journal write (`before_journal`) nothing was logged, so the operation never happened. After the
journal write (`after_journal`) recovery sees BEGIN without COMMIT and redoes it – the operation completes.

**Q6. What if it crashes during the operation?**
The data file and the metadata may disagree (we show this with `--no-recover fsck`). Recovery redoes the whole operation;
because each step is repeatable, finishing the missing step and repeating the finished one is safe.

**Q7. What if it crashes after applying but before the commit record?**
Everything is already applied but there is no COMMIT. Recovery redoes it (no visible change) and writes the COMMIT. The
state stays the same and the transaction is closed.

**Q8. What if it crashes after commit?**
Nothing to do – the operation is complete and stays available after restart.

**Q9. What does "idempotent" mean and why does it matter?**
Doing it twice has the same effect as once. "Write this exact content to this file", "delete if present" and "rename if
still under the old name" are idempotent. That is why recovery can safely repeat an operation, and why running recovery many
times is harmless. It is also why `append` is journaled as the *final* content: replaying "append X" could add X twice.

**Q10. Why redo (roll forward) rather than undo (roll back)?**
Our journal contains the complete new content, so finishing is always possible and simple. Undo logging would have to store
the old content as well. (When the journal record itself is torn, we effectively roll back, because the operation never
became official.)

**Q11. How do you detect a half-written journal record?**
Every line starts with a CRC-32 checksum of its JSON. A cut-off last line has no newline at the end, so it is treated as torn
and removed. A complete line whose checksum does not match is skipped and reported. A test changes one letter and the CRC notices.

**Q12. Why do you call `fsync`?**
`fsync` asks the OS to flush data to the disk. Without it the BEGIN record could still be only in memory when the crash
happens, which would defeat "log first".

**Q13. Why do you write to a temp file and then rename?**
Renaming over an existing file is atomic, so a reader sees the old complete file or the new complete file, never a half-written one.

**Q14. How is your crash simulation implemented? Is it a real crash?**
`crash.checkpoint("point")` calls are placed between the steps. If the point is armed, it raises `SimulatedCrash`, which stops
the program at exactly that moment, leaving the disk as it was. From the command line the process then exits with code 99
and we start a *new* process – so no memory survives, only the files. It is a simulation of our own program stopping, not a
hardware failure.

**Q15. What does the consistency checker check?**
Metadata entries without a data file; data files without metadata (orphans); size mismatch; checksum mismatch (SHA-256);
illegal names; names differing only by case; leftover temp files; pending or damaged journal records.

**Q16. Does the checker repair problems?**
No, it reports. Repair happens through journal recovery. This is stated in our limitations.

**Q17. What is metadata in your system?**
Per file: size, SHA-256 checksum, created and modified time, last operation and last transaction id, stored in `metadata.json`.

**Q18. Is your system safe against power failure or disk damage?**
We do not claim that. We use `fsync` and atomic renames, which help against power loss on a well-behaved system, but our tests
simulate the program stopping at chosen points, not hardware failure. Disk damage is out of scope (proposal §4, §15).

**Q19. How do you make sure real system files are never touched?**
Everything is under the project's `storage/` folder. File names cannot contain `/`, `\` or `..`. VFSafe refuses to use a
folder that already contains other files, and `reset` only works on a VFSafe storage folder.

**Q20. Why are the operations slower than reads?**
Each change does several `fsync`s (journal BEGIN, data, metadata, journal COMMIT) – that is the cost of durability. Reads
are just file reads. Our benchmark shows a few milliseconds for changes vs. well under a millisecond for reads.

**Q21. What happens if recovery itself crashes?**
Nothing special – the COMMIT is written only after the redo finishes, so the next start-up simply recovers again. This is
tested (`during_recovery` crash point).

**Q22. How is this different from a real journaling file system such as ext3/ext4 or NTFS?**
Real systems journal at block or metadata level, handle concurrency, and deal with hardware caches, barriers and large
volumes. Ours demonstrates the *principle* (log first, commit, replay) on whole files in a single-user prototype.

**Q23. Why does the journal store whole file contents? Is that a problem?**
It makes redo trivial but makes the journal larger. `checkpoint` empties it once everything is committed. A production system
would journal metadata or blocks instead.

**Q24. What happens if two programs use it at once?**
Not supported – there is no locking (stated in the limitations).

**Q25. How did you test it?**
93 automated tests: all operations; invalid names and missing files; duplicates; every operation at every crash point;
restart and recovery; repeated recovery; a crash inside recovery; several crashes in a row; consistency checks; and real
separate-process runs. We also confirmed the tests can fail by deliberately breaking recovery and checking that tests catch it.

**Q26. What would you improve next?**
Folders; file locking; journaling only metadata plus data checksums; a compact journal format; a real disk-image file instead of
a folder; and a GUI.
