# VFSafe – Virtual File System with Crash Recovery

**Operating Systems Lab Project** · Team: Manya, Hemanya, Tanmoy · Review: Tuesday, 20 October 2026

VFSafe is a small **virtual file system** written in plain Python (standard library only – nothing to
install). It keeps all its files inside its own `storage/` folder and protects them with a
**write-ahead journal**. You can make the program "crash" at chosen moments; the next time it starts,
**recovery runs automatically**, finishes or discards the unfinished operation, and checks that
everything is consistent.

> This is an educational prototype. Crashes are *simulated inside the program* – it never crashes your
> computer and never touches real system files. See [Limitations](#limitations-what-we-do-not-claim).

---

## Contents
1. [Quick start (Windows PowerShell)](#1-quick-start-windows-powershell)
2. [VS Code setup](#2-vs-code-setup)
3. [Using VFSafe – all commands](#3-using-vfsafe--all-commands)
4. [The crash-recovery demo (do this at the review)](#4-the-crash-recovery-demo)
5. [Running the tests + expected output](#5-running-the-tests)
6. [How crash recovery works (the policy)](#6-how-crash-recovery-works)
7. [Project structure and what each module does](#7-project-structure)
8. [Technical choices in beginner-friendly language](#8-technical-choices-explained)
9. [Performance numbers](#9-performance)
10. [Screenshots to capture](#10-screenshots-to-capture)
11. [Limitations](#limitations-what-we-do-not-claim)
12. [Troubleshooting](#troubleshooting)

Diagrams: `docs/architecture.png`, `docs/recovery_flowchart.png`, `docs/operation_flow.png`
(editable sources: the `.dot` files next to them). Viva questions, the one-minute explanation and the
team split are in **`docs/PRESENTATION_GUIDE.md`**.

---

## 1. Quick start (Windows PowerShell)

**You need:** Python 3.8 or newer. Check in PowerShell:

```powershell
python --version
```

If you see `Python 3.x.x`, you are fine. If you get *"Python was not found"*, either install Python from
<https://www.python.org/downloads/> (**tick "Add python.exe to PATH"** in the installer, then open a *new*
PowerShell) or try `py --version` and use `py` instead of `python` in every command below.

**Unzip the project** (adjust the path if your ZIP is somewhere else):

```powershell
Expand-Archive -Path $HOME\Downloads\VFSafe.zip -DestinationPath $HOME\Desktop
cd $HOME\Desktop\VFSafe
```

**Try it:**

```powershell
python main.py create hello.txt "Hello VFSafe"
python main.py ls
python main.py read hello.txt
```

**See the whole crash-recovery story automatically (10 seconds):**

```powershell
python demo.py
```

**Run all automated tests:**

```powershell
python -m unittest -v
```

No `pip install` is needed – there are no external packages.

---

## 2. VS Code setup

1. Install **Visual Studio Code**: <https://code.visualstudio.com/>
2. Install **Python** (see above) if you have not already.
3. Open VS Code → **Extensions** (`Ctrl+Shift+X`) → search **Python** (publisher: Microsoft) → **Install**.
4. **File → Open Folder…** → choose the `VFSafe` folder (the one that contains `main.py`).
5. Press `Ctrl+Shift+P` → type **Python: Select Interpreter** → pick your Python 3 installation.
6. Open a terminal inside VS Code: **Terminal → New Terminal** (or `` Ctrl+` ``). It opens PowerShell in the
   project folder, so you can run every command in this README directly.
7. *(Optional, nice for the viva)* To step through an operation line by line: open `file_manager.py`, click
   left of the line `self.journal.append(record)` inside `_run` to place a red **breakpoint**, open `main.py`, press
   `F5` → *Python File* … or simply run `python demo.py` and read the output.

If PowerShell refuses to run scripts you do **not** need to change anything: VFSafe only uses
`python …` commands, never `.ps1` scripts.

---

## 3. Using VFSafe – all commands

Run each as `python main.py <command>`. Put text containing spaces in **"double quotes"**.

| Command | What it does |
|---|---|
| `create NAME ["content"]` | Create a new file (error if the name already exists) |
| `read NAME` | Print the file's content |
| `write NAME "content"` | Replace the file's content |
| `append NAME "text"` | Add text to the end of the file |
| `rename OLD NEW` | Rename a file |
| `delete NAME` | Delete a file |
| `ls` | List all files with size and modified time |
| `stat NAME` | Show metadata (size, checksum, created, modified, last operation, last transaction id) |
| `journal` | Show the journal: every transaction as **COMMITTED** or **PENDING** |
| `fsck` | Run the consistency check |
| `recover` | Run recovery now (it also runs by itself at every start-up) |
| `checkpoint` | Empty the journal when nothing is pending |
| `benchmark -n 100` | Measure operation time and recovery time (uses a temporary folder) |
| `reset --yes` | Delete **all** virtual files, metadata and journal (only inside `storage/`) |
| `shell` | Interactive mode (type commands without `python main.py`) |

**Crash options**

* `--crash-at POINT` after a changing command (`create`, `write`, `append`, `rename`, `delete`) makes the program
  crash at that point. Points: `before_journal`, `during_journal`, `after_journal`, `during_apply`,
  `after_apply`, `after_commit`.
* `--no-recover` (put it *before* the command) opens the storage **without** running recovery, so you can *look at*
  the crashed state with `journal`, `fsck`, `ls`, `read`. Changing commands are refused in this mode.

Other options: `--storage PATH` uses a different storage folder (VFSafe refuses a folder that already contains
unrelated files, so your real files can never be touched).

**Exit codes:** `0` success · `1` error (friendly message printed) · `99` simulated crash.

**Interactive shell example**

```powershell
python main.py shell
```
```
vfsafe> create notes.txt "first draft"
vfsafe> crash-at after_apply
vfsafe> write notes.txt "second draft"
[CRASH] Simulated crash at 'after_apply'. ...
```
Start `python main.py shell` again and watch recovery run.

---

## 4. The crash-recovery demo

Do these steps live at the review. Each **bold** line is a command; the text under it is what you should see.
(Timestamps and timings will differ.)

```powershell
python main.py reset --yes
python main.py create notes.txt "version 1"
```
```
[startup] Journal clean, nothing to recover. Consistency OK (0 file(s)).
Created 'notes.txt'.
```

**Crash 1 – after the change is applied but before the COMMIT is written**

```powershell
python main.py write notes.txt "version 2" --crash-at after_apply
```
```
[CRASH] Simulated crash at 'after_apply'.
        The program stopped abruptly - nothing more was written.
```
Look at the crashed disk **before** recovery:
```powershell
python main.py --no-recover journal
```
```
TXID  STATE      OP       DETAILS
1     COMMITTED  create   notes.txt (9 chars)
2     PENDING    write    notes.txt (9 chars)
```
`PENDING` means a BEGIN record exists but no COMMIT – the operation is unfinished.
Now just start the program normally – recovery runs automatically:
```powershell
python main.py read notes.txt
```
```
[startup] storage: ...\VFSafe\storage
[startup] Recovery: unfinished work found - fixing it now.
[startup]   - tx 2 'write' on 'notes.txt': had no COMMIT -> REDONE (rolled forward) and committed
[startup] Consistency check: OK (1 file(s) verified, no problems)
version 2
```

**Crash 2 – in the middle of an operation (the file system is really inconsistent!)**

```powershell
python main.py rename notes.txt report.txt --crash-at during_apply
python main.py --no-recover fsck
```
```
Consistency check: 2 error(s), 1 warning(s) (1 file(s) checked)
  [ERROR] META_WITHOUT_DATA: 'notes.txt' is listed in metadata but its data file is missing
  [ERROR] DATA_WITHOUT_META: 'report.txt' exists in storage but is not listed in metadata (orphan file)
  [WARNING] PENDING_OPERATIONS: 1 operation(s) in the journal have no COMMIT (recovery needed): txid 3
```
```powershell
python main.py ls
```
Recovery completes the rename → `report.txt` is listed, consistency OK.

**Crash 3 – torn journal record (crash while writing the log itself)**

```powershell
python main.py write report.txt "never saved" --crash-at during_journal
python main.py read report.txt
```
Recovery says the incomplete record was **DISCARDED**; the file still contains `version 2`.

**Crash 4 – after COMMIT**

```powershell
python main.py append report.txt " + extra" --crash-at after_commit
python main.py read report.txt
```
Nothing to recover; the content is `version 2 + extra`.

**Repeated recovery is harmless**

```powershell
python main.py recover
python main.py recover
python main.py journal
```
Both say *"journal is clean, nothing to recover"*.

The one-command version of all of this is `python demo.py`.

---

## 5. Running the tests

```powershell
python -m unittest -v
```

Run only one area:

```powershell
python -m unittest tests.test_basic_operations -v
python -m unittest tests.test_errors_and_validation -v
python -m unittest tests.test_journal -v
python -m unittest tests.test_crash_recovery -v
python -m unittest tests.test_consistency -v
python -m unittest tests.test_cli -v
```

**Expected result** (the last lines):

```
----------------------------------------------------------------------
Ran 93 tests in 4.xxxs

OK
```
The time depends on your disk. If you see `FAILED`, read the first failure message – it names the test and what
was different.

**What the tests cover**

| Test file | What it proves |
|---|---|
| `test_basic_operations.py` | create / read / write / append / rename / delete / list, metadata, Unicode, restart |
| `test_errors_and_validation.py` | invalid names (spaces, `/`, `..`, `CON`, too long …), missing files, duplicates, bad content, refusing foreign folders |
| `test_journal.py` | journal format, CRC detects damage, torn lines, checkpoint |
| `test_crash_recovery.py` | **every operation × every crash point**, damage really exists before recovery, repeated recovery, crash *during* recovery, several crashes in a row |
| `test_consistency.py` | the checker detects each kind of inconsistency |
| `test_cli.py` | real separate processes: exit code 99, restart, recovery messages, `benchmark`, `demo.py` |

---

## 6. How crash recovery works

### The five steps of every changing operation

1. **Validate** the input (bad input never reaches the journal).
2. Write a **BEGIN** record to the journal – it contains the *complete* new content – and force it to disk (`fsync`).
3. **Apply** the change: write the data file safely, then update `metadata.json`.
4. Write a **COMMIT** record to the journal (`fsync`).
5. Tell the user it worked (only now).

### Recovery policy: "roll forward, or forget"

At every start-up, `recovery.py`:

1. deletes leftover temporary files;
2. throws away a **torn** last journal line (cut off mid-write);
3. for every BEGIN **without** a COMMIT → **redoes** the operation (safe to repeat) and writes a COMMIT;
4. runs the consistency checker and prints the result.

| When did the crash happen? | State on disk | What recovery does | Final result |
|---|---|---|---|
| `before_journal` – before the operation is applied (nothing logged yet) | unchanged | nothing to do | operation **never happened** |
| `during_journal` – log record half written | torn record at end of journal | **discards** the torn record | operation **never happened** |
| `after_journal` – **before** the change is applied | BEGIN logged, nothing changed | **redo** + COMMIT | operation **completed** |
| `during_apply` – **during** the operation | data and metadata disagree (real inconsistency) | **redo** + COMMIT | operation **completed** |
| `after_apply` – change applied, **no commit record** | everything applied, no COMMIT | redo changes nothing new, + COMMIT | operation **completed** |
| `after_commit` – **after commit** | BEGIN + COMMIT | nothing to do | operation **completed** (stays available) |

**Why is this safe?** Two ideas:

* *Write-ahead*: the BEGIN record (with all information needed) is on disk **before** anything changes, so recovery
  always knows what was intended.
* *Repeatable (idempotent) steps*: "write this exact content to this file", "remove this file if present", "rename
  this file if it is still under the old name" give the same result whether run once or ten times. That is why
  `append` is journaled as the *final* content – redoing it can never append twice.

**What the user is told:** a command prints "success" only after its COMMIT is on disk. If it crashed before that,
the user never saw "success", so either outcome (done or never happened) is a legal answer – the file system is
simply never left half-done.

**Repeated recovery / crash during recovery:** after recovery, nothing is pending, so running it again does nothing.
If the program crashes *while recovering*, the next start-up simply recovers again (tested).

---

## 7. Project structure

```
VFSafe/
├── main.py             Command-line interface + interactive shell
├── file_manager.py     File operations; the 5-step write-ahead procedure; apply()
├── journal.py          Write-ahead log: BEGIN / COMMIT / CHECKPOINT records with CRC
├── recovery.py         Start-up recovery (roll forward or discard) + recovery report
├── consistency.py      fsck: metadata vs data files vs journal
├── metadata.py         metadata.json: size, checksum, times, last operation
├── storage.py          Virtual storage layer: safe (atomic) file writes, storage safety checks
├── crash.py            Crash simulator and the list of crash points
├── validation.py       File-name and content validation
├── errors.py           Custom error types (friendly messages)
├── benchmark.py        Operation-time and recovery-time measurements
├── demo.py             Automatic scripted demonstration
├── storage/            <- the virtual file system lives here (created automatically)
│   ├── data/           virtual files
│   ├── tmp/            scratch space for safe writes
│   ├── metadata.json
│   └── journal.log
├── tests/              93 automated tests (unittest)
└── docs/               diagrams + PRESENTATION_GUIDE.md
```

| Module | In one sentence |
|---|---|
| `main.py` | Reads your commands, runs recovery first, prints friendly output and error messages. |
| `file_manager.py` | Does each operation in the safe order: log → apply → commit. |
| `journal.py` | An append-only diary of what we are about to do and what is finished; every line has a checksum. |
| `recovery.py` | On start-up reads the diary and fixes anything that was not finished. |
| `consistency.py` | Cross-checks the three records of truth and reports every disagreement. |
| `metadata.py` | The "catalogue card" for each file (size, SHA-256, times, last operation). |
| `storage.py` | Writes files so that a reader never sees a half-written file; guards against using the wrong folder. |
| `crash.py` | Lets a test (or you) kill the program at an exact moment. |
| `validation.py` | Rejects bad names/content before anything is logged. |
| `errors.py` | Named error types so the CLI can show a clear message instead of a traceback. |

---

## 8. Technical choices explained

* **Why a journal?** If power dies between "write the file" and "update the catalogue", the two disagree. The
  journal is a note written *first*, so after a restart we can see what was in progress.
* **Why *redo* (roll forward) instead of undo?** The journal stores the complete new content, so finishing an
  operation is easy and always possible. Undo would need the *old* content stored too. Redo is simpler and fully
  repeatable.
* **Why a checksum (CRC) on every journal line?** A crash can leave a half-written line. The CRC lets us notice
  damage instead of trusting it. (Tested: a one-letter change is detected.)
* **Why SHA-256 in the metadata?** Size alone cannot detect silent corruption of the same length; the checksum can.
* **Why write to `tmp/` and then rename?** Renaming a file over another is atomic, so a reader sees the old complete
  file or the new complete file – never half of each.
* **Why `fsync`?** It asks the operating system to really push data to the disk. Without it the "log first" rule
  could be defeated by OS caching.
* **Why does a crash raise an exception instead of killing Python?** It lets the same code run in automated tests.
  The command-line version exits with code 99 straight afterwards, and every state that matters is on disk, so
  starting the program again is a genuine restart. (`test_cli.py` does exactly that with separate processes.)
* **Why are file names case-insensitive?** Windows treats `Notes.txt` and `notes.txt` as the same file. VFSafe
  stores names as typed but compares ignoring case, so two "different" files can never collide on disk.
* **Why only plain text files, no folders?** The goal is crash recovery, not a full file system; a flat namespace
  keeps the focus on journaling.

---

## 9. Performance

`python main.py benchmark -n 100` measures average time per operation and recovery time. Measured in the
development sandbox (Linux, 100 operations) – **your numbers will differ**, so run it on your own laptop and
quote *those*:

| Operation | Average |
|---|---|
| create / write / append / rename / delete | ≈ 3.5 – 4.6 ms |
| read / list | ≈ 0.03 – 0.05 ms |

| Unfinished operations at start-up | Recovery time (incl. consistency check) |
|---|---|
| 0 | ≈ 0.1 ms |
| 10 | ≈ 25 ms |
| 100 | ≈ 450 ms |

Reading is fast; changing is slower because each change deliberately forces several `fsync`s (journal BEGIN, data,
metadata, journal COMMIT). That cost *is* the price of safety. In normal use at most one operation is ever pending.

---

## 10. Screenshots to capture

Use a PowerShell window in VS Code with a readable font size. Suggested file names in brackets.

1. **[01_setup]** `python --version` and the project folder open in VS Code (Explorer showing all modules).
2. **[02_basic_ops]** `create`, `ls`, `read`, `write`, `append`, `rename`, `delete` with their output.
3. **[03_validation]** Friendly errors: `create "bad name"`, `create hello.txt` twice, `read missing.txt`.
4. **[04_journal_normal]** `python main.py journal` showing COMMITTED transactions.
5. **[05_crash_after_apply]** The `--crash-at after_apply` command printing `[CRASH]` (exit code 99).
6. **[06_pending_state]** `python main.py --no-recover journal` showing a **PENDING** entry.
7. **[07_inconsistent]** After `rename … --crash-at during_apply`: `--no-recover fsck` showing the 2 ERRORs.
8. **[08_recovery_output]** The normal restart printing `REDONE (rolled forward)` and `Consistency check: OK`.
9. **[09_torn_journal]** `--crash-at during_journal` followed by the `DISCARDED` message.
10. **[10_repeated_recovery]** `recover` twice → "nothing to recover".
11. **[11_demo_py]** The full `python demo.py` output (take two screenshots if it scrolls).
12. **[12_tests]** `python -m unittest -v` ending with `Ran 93 tests … OK`.
13. **[13_benchmark]** `python main.py benchmark -n 100`.
14. **[14_diagrams]** `docs/architecture.png` and `docs/recovery_flowchart.png` opened in VS Code.
15. **[15_storage_folder]** The `storage/` folder in the Explorer (`data/`, `metadata.json`, `journal.log`) and
    `journal.log` opened in the editor to show the CRC + JSON records.

---

## Limitations (what we do not claim)

* **Simulated crashes only.** The crash simulator stops the program at chosen points in *our* code. It tests our
  recovery *logic*. It does not simulate a power cut, disk damage, or an operating system that ignores `fsync`.
* **No guarantee against every hardware or power failure.** We call `fsync` and use atomic renames, but whether data
  truly reaches the platter/flash is up to the OS and drive.
* **Single user, single process.** There is no locking; running two VFSafe instances on the same folder at once is
  not supported.
* **Prototype scope.** Flat namespace (no folders), text files up to 1 MB, no permissions or encryption.
* **The journal stores whole file contents**, so it is bigger than a metadata-only journal; use `checkpoint` to empty
  it. `metadata.json` is rewritten completely on each change, so very large file counts get slower.
* **`fsck` reports; it does not repair.** Repair happens only through journal recovery. If someone edits files inside
  `storage/` by hand, `fsck` will flag it but not fix it.
* A **damaged journal line in the middle** of the log is skipped and reported (we cannot know what it said), and a
  torn *last* line is discarded; both are shown in the recovery report.

---

## Troubleshooting

| Problem | Fix |
|---|---|
| `python` not recognised | Reinstall Python with *Add to PATH*, or use `py` instead of `python`. |
| `is not empty and is not a VFSafe storage folder` | You passed `--storage` pointing at a folder with other files. Use an empty or new folder. |
| `Recovery needed` / changes blocked | You used `--no-recover`. Run `python main.py recover` (or just any command without `--no-recover`). |
| Start fresh | `python main.py reset --yes` |
| Garbled characters in PowerShell | VFSafe prints plain ASCII; if *your* file content has non-English text, run `chcp 65001` first. |
| Tests fail only on your PC | Run `python -m unittest tests.test_cli -v` separately; antivirus can briefly lock files on Windows – re-run. |
