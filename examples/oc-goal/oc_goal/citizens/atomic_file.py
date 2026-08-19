"""Atomic file writes plus a cross-process advisory lock.

Use it for any write whose truth source is still a file (declaration-layer
materialization, exported artifacts). Do not use it for entities already in
`oc.db`: their atomicity belongs to SQLite transactions, and a file lock on top
is pure overhead.

flock is advisory: it constrains only processes that also take this lock. Code
calling `open(path, "w")` directly is unconstrained, so the discipline is "every
write to such a file goes through this module", not "the lock makes it safe".
"""
import contextlib
import os
import tempfile
import threading

_THREAD_LOCKS = {}
_THREAD_LOCKS_GUARD = threading.Lock()


def _thread_lock(path):
    with _THREAD_LOCKS_GUARD:
        return _THREAD_LOCKS.setdefault(os.path.abspath(path), threading.RLock())


@contextlib.contextmanager
def file_lock(path):
    """Cross-process advisory lock plus an in-process thread lock. `path` is the lock
    file itself, usually `<dir>/.lock`."""
    local = _thread_lock(path)
    with local:
        directory = os.path.dirname(path)
        if directory:
            os.makedirs(directory, exist_ok=True)
        with open(path, "a+b") as handle:
            handle.seek(0, os.SEEK_END)
            if handle.tell() == 0:
                handle.write(b"\0")
                handle.flush()
            handle.seek(0)
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)
                try:
                    yield
                finally:
                    handle.seek(0)
                    msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
                try:
                    yield
                finally:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def write_text(path, text, encoding="utf-8"):
    """Atomic write: temp file → fsync → `os.replace`.

    `os.replace` is atomic within one filesystem, so a reader sees either the old
    content or the new one, never a partial file. A bare `open(path, "w")`
    truncates to zero bytes first, and a crash midway leaves an empty or partial
    file.
    """
    directory = os.path.dirname(os.path.abspath(path))
    os.makedirs(directory, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=".atomic-", dir=directory)
    try:
        with os.fdopen(descriptor, "w", encoding=encoding, newline="\n") as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        temporary = None
    finally:
        if temporary and os.path.exists(temporary):
            os.unlink(temporary)


def append_text(path, text, encoding="utf-8"):
    """Append + fsync, for append-only ledgers (records / usage).

    No temp+rename here: rename rewrites the whole file, while a ledger's value is
    that it only grows, so a git diff shows added lines only.
    """
    directory = os.path.dirname(os.path.abspath(path))
    if directory:
        os.makedirs(directory, exist_ok=True)
    with open(path, "a", encoding=encoding, newline="\n") as stream:
        stream.write(text)
        stream.flush()
        os.fsync(stream.fileno())


def update_json(path, mutate, default=None):
    """Read-modify-write a JSON file while holding the lock throughout — the cure for
    lost updates.

    `mutate(doc) -> doc`; returning None writes nothing.
    """
    import json
    lock = path + ".lock"
    with file_lock(lock):
        try:
            with open(path, encoding="utf-8") as stream:
                current = json.load(stream)
        except (OSError, ValueError):
            current = default if default is not None else {}
        updated = mutate(current)
        if updated is None:
            return current
        write_text(path, json.dumps(updated, ensure_ascii=False, indent=2) + "\n")
        return updated
