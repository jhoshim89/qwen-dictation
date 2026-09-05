"""Short-lived private audio files for ASR APIs that require a path."""
from contextlib import contextmanager
import os
import tempfile


@contextmanager
def temporary_wav(prefix="qwen-dictation-"):
    fd, path = tempfile.mkstemp(prefix=prefix, suffix=".wav")
    try:
        os.fchmod(fd, 0o600)
        os.close(fd)
        fd = -1
        yield path
    finally:
        if fd >= 0:
            os.close(fd)
        try:
            os.unlink(path)
        except FileNotFoundError:
            pass
