"""
validation.py - input validation for file names and file content.

All user input passes through these functions BEFORE anything is written to
the journal, so bad input can never reach the storage.
"""

import re

from errors import InvalidContentError, InvalidNameError

MAX_NAME_LENGTH = 64
MAX_FILE_BYTES = 1_000_000  # 1 MB per virtual file keeps the journal small

# Letters, digits, dot, underscore, dash. Must start with a letter/digit/underscore.
_NAME_PATTERN = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9._-]*$")

# Names Windows refuses to use for real files (we store files on the real disk).
_WINDOWS_RESERVED = {"CON", "PRN", "AUX", "NUL"}
_WINDOWS_RESERVED.update("COM%d" % i for i in range(1, 10))
_WINDOWS_RESERVED.update("LPT%d" % i for i in range(1, 10))


def validate_name(name):
    """Return the name if it is valid, otherwise raise InvalidNameError."""
    if not isinstance(name, str):
        raise InvalidNameError("File name must be text.")
    if name == "":
        raise InvalidNameError("File name cannot be empty.")
    if len(name) > MAX_NAME_LENGTH:
        raise InvalidNameError(
            "File name is too long (%d characters; the maximum is %d)."
            % (len(name), MAX_NAME_LENGTH)
        )
    if "/" in name or "\\" in name:
        raise InvalidNameError(
            "File name '%s' cannot contain '/' or '\\' - VFSafe has no folders." % name
        )
    if name in (".", ".."):
        raise InvalidNameError("'%s' is not a valid file name." % name)
    if name.startswith("."):
        raise InvalidNameError("File name '%s' cannot start with a dot." % name)
    if name.endswith("."):
        raise InvalidNameError("File name '%s' cannot end with a dot." % name)
    if not _NAME_PATTERN.match(name):
        raise InvalidNameError(
            "File name '%s' has illegal characters. Use only letters, digits, "
            "'.', '_' and '-' (no spaces)." % name
        )
    if name.split(".")[0].upper() in _WINDOWS_RESERVED:
        raise InvalidNameError(
            "'%s' is a reserved name on Windows. Please choose another." % name
        )
    return name


def validate_content(content):
    """Return the content if it is valid text of acceptable size."""
    if not isinstance(content, str):
        raise InvalidContentError("File content must be text.")
    try:
        data = content.encode("utf-8")
    except UnicodeEncodeError:
        raise InvalidContentError("File content contains characters that cannot be stored.")
    if len(data) > MAX_FILE_BYTES:
        raise InvalidContentError(
            "File content is too large (%d bytes; the maximum is %d)."
            % (len(data), MAX_FILE_BYTES)
        )
    return content
