"""
metadata.py - the Metadata Manager.

Metadata is "data about the files": name, size, checksum, timestamps and which
operation touched the file last. It is kept in storage/metadata.json:

    {"version": 1,
     "files": {"notes.txt": {"size": 11, "sha256": "...", "created": "...",
                             "modified": "...", "last_op": "write",
                             "last_txid": 7}}}

Every method here is REPEATABLE (idempotent): doing it twice gives the same
result as doing it once. Recovery relies on that property.
"""

import json

from errors import StorageError
from storage import content_info


class MetadataManager:
    def __init__(self, storage):
        self.storage = storage
        self.files = {}
        self.load()

    # ------------------------------------------------------------------ disk
    def load(self):
        path = self.storage.meta_path
        if not path.exists():
            self.files = {}
            return
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
            self.files = dict(doc["files"])
        except (ValueError, KeyError, TypeError) as exc:
            raise StorageError(
                "metadata.json is corrupted (%s). Restore it or reset the storage." % exc
            )

    def save(self):
        self.storage.write_json_atomic(
            self.storage.meta_path, {"version": 1, "files": self.files}
        )

    # --------------------------------------------------------------- queries
    def names(self):
        return sorted(self.files)

    def get(self, name):
        return self.files.get(name)

    def find_ci(self, name):
        """Find a stored name ignoring upper/lower case (Windows is case-blind)."""
        wanted = name.lower()
        for stored in self.files:
            if stored.lower() == wanted:
                return stored
        return None

    # --------------------------------------------------------------- updates
    def put(self, name, content, txid, op, ts):
        """Create or overwrite the entry for `name` (repeatable)."""
        size, digest = content_info(content)
        old = self.files.get(name)
        self.files[name] = {
            "size": size,
            "sha256": digest,
            "created": old["created"] if old else ts,
            "modified": ts,
            "last_op": op,
            "last_txid": txid,
        }
        self.save()

    def remove(self, name):
        """Remove the entry (repeatable: does nothing if already gone)."""
        if name in self.files:
            del self.files[name]
            self.save()

    def rename(self, old, new, txid, ts):
        """Move the entry (repeatable: does nothing if `old` is already gone)."""
        if old in self.files:
            entry = self.files.pop(old)
            entry.update({"modified": ts, "last_op": "rename", "last_txid": txid})
            self.files[new] = entry
            self.save()
