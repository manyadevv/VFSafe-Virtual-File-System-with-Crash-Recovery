"""
storage.py - the Virtual Storage Layer.

Everything VFSafe saves lives inside ONE folder (default: ./storage):

    storage/
      .vfsafe_storage   <- marker file: "this folder belongs to VFSafe"
      data/             <- the virtual files (file content)
      tmp/              <- scratch space used while writing safely
      metadata.json     <- list of files + size/checksum/etc.
      journal.log       <- the write-ahead log (transaction log)

SAFE WRITING (important idea!)
  If we wrote straight into the real file and crashed half-way, the file would
  be half old / half new. Instead we:
     1. write the new content into a temporary file in tmp/
     2. force it onto the disk (fsync)
     3. rename the temp file over the real one (os.replace)
  The rename is "atomic": other programs see either the complete old file or
  the complete new file, never a mix.
"""

import hashlib
import json
import os
import tempfile
from pathlib import Path

from errors import StorageError

MARKER_NAME = ".vfsafe_storage"


def bytes_info(data):
    """Return (size_in_bytes, sha256_hex) for a bytes object."""
    return len(data), hashlib.sha256(data).hexdigest()


def content_info(text):
    """Same as bytes_info, but for a text string (stored as UTF-8)."""
    return bytes_info(text.encode("utf-8"))


def _fsync_dir(path):
    """Ask the OS to persist a directory entry (not supported on Windows)."""
    if os.name == "nt":
        return
    try:
        fd = os.open(str(path), os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
    except OSError:
        pass


class Storage:
    def __init__(self, root):
        self.root = Path(root).resolve()
        self.data_dir = self.root / "data"
        self.tmp_dir = self.root / "tmp"
        self.meta_path = self.root / "metadata.json"
        self.journal_path = self.root / "journal.log"
        self.marker_path = self.root / MARKER_NAME

    # ------------------------------------------------------------------ setup
    def initialize(self):
        """Create the folder layout. Refuses to adopt a folder that is not ours."""
        if self.root.exists():
            if not self.root.is_dir():
                raise StorageError("'%s' exists but is not a folder." % self.root)
            leftovers = [p for p in self.root.iterdir() if p.name != ".gitkeep"]
            if leftovers and not self.marker_path.exists():
                raise StorageError(
                    "'%s' is not empty and is not a VFSafe storage folder. "
                    "Refusing to use it so your real files are never touched." % self.root
                )
        try:
            self.data_dir.mkdir(parents=True, exist_ok=True)
            self.tmp_dir.mkdir(parents=True, exist_ok=True)
            if not self.marker_path.exists():
                self.marker_path.write_text("VFSafe storage folder\n", encoding="utf-8")
        except OSError as exc:
            raise StorageError("Cannot create storage folder '%s': %s" % (self.root, exc))

    def reset(self):
        """Delete all virtual files, metadata and journal (keeps the folder)."""
        if not self.marker_path.exists():
            raise StorageError("Refusing to reset: '%s' is not a VFSafe storage folder." % self.root)
        for folder in (self.data_dir, self.tmp_dir):
            if folder.exists():
                for item in folder.iterdir():
                    if item.is_file():
                        item.unlink()
        for path in (self.meta_path, self.journal_path):
            if path.exists():
                path.unlink()
        self.initialize()

    # ------------------------------------------------------------ data files
    def file_path(self, name):
        """Real path of a virtual file. `name` must already be validated."""
        path = self.data_dir / name
        if path.parent != self.data_dir:  # defensive: never escape data/
            raise StorageError("Unsafe file name '%s'." % name)
        return path

    def file_exists(self, name):
        return self.file_path(name).is_file()

    def list_data_files(self):
        if not self.data_dir.exists():
            return []
        return sorted(p.name for p in self.data_dir.iterdir() if p.is_file())

    def read_file(self, name):
        try:
            return self.file_path(name).read_bytes().decode("utf-8")
        except FileNotFoundError:
            raise StorageError("The data for '%s' is missing from storage. Run 'fsck'." % name)
        except UnicodeDecodeError:
            raise StorageError("The data for '%s' is not valid text. Run 'fsck'." % name)

    def write_file(self, name, content):
        """Safely (atomically) write a virtual file. Safe to repeat."""
        self._atomic_write_bytes(self.file_path(name), content.encode("utf-8"))

    def delete_file(self, name):
        """Delete a virtual file. Does nothing if it is already gone (repeatable)."""
        path = self.file_path(name)
        if path.exists():
            path.unlink()
            _fsync_dir(self.data_dir)

    def rename_file(self, old, new):
        """Rename a virtual file. Does nothing if `old` is already gone (repeatable)."""
        src, dst = self.file_path(old), self.file_path(new)
        if src.exists():
            os.replace(str(src), str(dst))
            _fsync_dir(self.data_dir)

    # --------------------------------------------------------- tmp + metadata
    def clean_tmp(self):
        """Remove leftover temp files (from an interrupted write). Returns count."""
        count = 0
        if self.tmp_dir.exists():
            for item in self.tmp_dir.iterdir():
                if item.is_file():
                    item.unlink()
                    count += 1
        return count

    def list_tmp_files(self):
        if not self.tmp_dir.exists():
            return []
        return sorted(p.name for p in self.tmp_dir.iterdir() if p.is_file())

    def write_json_atomic(self, path, obj):
        text = json.dumps(obj, indent=2, sort_keys=True)
        self._atomic_write_bytes(Path(path), text.encode("utf-8"))

    # --------------------------------------------------------------- internals
    def _atomic_write_bytes(self, target, data):
        self.tmp_dir.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(dir=str(self.tmp_dir), prefix="w-", suffix=".tmp")
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp_name, str(target))
        except Exception:
            if os.path.exists(tmp_name):
                os.unlink(tmp_name)
            raise
        _fsync_dir(target.parent)
