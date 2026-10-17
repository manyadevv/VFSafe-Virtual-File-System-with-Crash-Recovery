"""
errors.py - all the custom error types used by VFSafe.

Why custom errors?
  Python's built-in errors (like FileNotFoundError) are about the REAL file
  system. VFSafe has its own *virtual* file system, so we define our own
  errors. This also lets main.py show a friendly message instead of a scary
  Python traceback.
"""


class VFSafeError(Exception):
    """Base class: every 'normal' VFSafe problem is a VFSafeError."""


class InvalidNameError(VFSafeError):
    """The file name is not allowed (empty, has '/', too long, ...)."""


class InvalidContentError(VFSafeError):
    """The file content is not allowed (not text, or too big)."""


class FileMissingError(VFSafeError):
    """The file you asked for does not exist."""


class FileAlreadyExistsError(VFSafeError):
    """You tried to create/rename to a name that is already taken."""


class StorageError(VFSafeError):
    """Something is wrong with the storage folder itself."""


class JournalError(VFSafeError):
    """Something is wrong with the journal (transaction log)."""


class SimulatedCrash(BaseException):
    """
    Raised on purpose by the crash simulator to pretend the program died.

    It inherits from BaseException (not Exception) on purpose: a real crash
    cannot be "caught and handled" by normal error-handling code, so this
    error must not be swallowed by a generic `except Exception:` either.
    """

    def __init__(self, point):
        super().__init__(point)
        self.point = point
