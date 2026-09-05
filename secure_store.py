"""Private, crash-safe writes for Qwen Dictation user data."""
import json
import os
import tempfile


PRIVATE_FILE_MODE = 0o600


def ensure_private_file(path):
    """Tighten an existing regular file to owner read/write only."""
    try:
        if os.path.isfile(path) and not os.path.islink(path):
            os.chmod(path, PRIVATE_FILE_MODE)
    except OSError:
        pass


def atomic_write_text(path, text):
    """Write text beside the destination, fsync it, then atomically replace."""
    parent = os.path.dirname(os.path.abspath(path))
    os.makedirs(parent, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=f".{os.path.basename(path)}.", dir=parent)
    try:
        os.fchmod(fd, PRIVATE_FILE_MODE)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            fd = -1
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
        os.chmod(path, PRIVATE_FILE_MODE)
    finally:
        if fd >= 0:
            os.close(fd)
        try:
            os.unlink(tmp)
        except FileNotFoundError:
            pass


def atomic_write_json(path, data):
    atomic_write_text(path, json.dumps(data, ensure_ascii=False, indent=2))


def append_private_text(path, text):
    """Append to a 0600 file without following a pre-existing symlink."""
    parent = os.path.dirname(os.path.abspath(path))
    os.makedirs(parent, exist_ok=True)
    flags = os.O_WRONLY | os.O_CREAT | os.O_APPEND
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    fd = os.open(path, flags, PRIVATE_FILE_MODE)
    try:
        os.fchmod(fd, PRIVATE_FILE_MODE)
        with os.fdopen(fd, "a", encoding="utf-8") as handle:
            fd = -1
            handle.write(text)
            handle.flush()
    finally:
        if fd >= 0:
            os.close(fd)
