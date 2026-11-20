"""Replace a file with complete bytes, or leave the previous bytes in place.

Every write goes to a temporary file in the destination's own directory, is
flushed and fsynced, and is then renamed over the destination with `os.replace`.
A reader therefore sees the whole previous file or the whole new file, never a
partial write, and a failed write leaves the destination untouched.

Two contracts the standard library leaves open are explicit here:

- overwrite and create-only. `overwrite=True` (the default) replaces an
  existing file. `overwrite=False` publishes a new file and raises
  FileExistsError rather than replacing one; it publishes through `os.link`,
  so when two writers race the loser raises FileExistsError instead of
  overwriting the winner.
- durability. `durability` is `none`, `file` (fsync the new bytes before the
  rename), `file+directory` (also fsync the containing directory so the
  rename survives a crash; the default) or `full` (`file+directory`, plus
  macOS F_FULLFSYNC on the new bytes so they reach stable media, not only the
  drive cache). A directory that cannot be fsynced (SMB, FUSE: EINVAL or
  ENOTSUP) is skipped, because the rename has already happened by then.

Permissions come from the existing destination unless `mode` is given, so a
0600 state file stays 0600 after a replacement. `mode="umask"` instead gives
every write the fresh default (0666 minus the process umask), as a plain
`open(path, "w")` on a new file would. A path that is a symlink is
followed, so its target is replaced and the link survives. `dir_fd` pins both
the temporary file and the rename to an already-validated directory
descriptor; the destination name is then relative to that descriptor.
"""
from __future__ import annotations

import errno
import json
import os
import stat
import sys
import time
import uuid
from contextlib import contextmanager
from typing import Any, BinaryIO, Iterator, TextIO

__all__ = [
    "DURABILITIES",
    "Staged",
    "atomic_path",
    "write_bytes",
    "write_json",
    "write_text",
]

DURABILITIES = ("none", "file", "file+directory", "full")
_UNSYNCABLE = {errno.EINVAL, errno.ENOTSUP, getattr(errno, "EOPNOTSUPP", errno.ENOTSUP)}


def _resolve(path, dir_fd, follow_symlinks: bool) -> str:
    """Return the name to publish.

    `follow_symlinks=True` (the default) replaces the link's target and keeps the
    link. `follow_symlinks=False` replaces the link itself, which is what a caller
    publishing a deploy entry needs when the entry may have been swapped for a
    link by another process.
    """
    name = os.fspath(path)
    if dir_fd is not None or not follow_symlinks:
        return name
    return os.path.realpath(name) if os.path.islink(name) else name


def _existing_mode(name, dir_fd) -> int | None:
    """Permissions of the regular file now at `name` (through a link), else None."""
    try:
        status = os.stat(name, dir_fd=dir_fd)
    except (FileNotFoundError, NotADirectoryError):
        return None
    return status.st_mode & 0o7777 if stat.S_ISREG(status.st_mode) else None


def _temporary_name(name) -> str:
    """A fresh name beside `name`, in the same directory (or dir_fd-relative directory)."""
    return os.path.join(os.path.dirname(name), f".{os.path.basename(name)}.{uuid.uuid4().hex}.tmp")


def _sync_file(descriptor, durability) -> None:
    """Flush file bytes per `durability`; `full` adds macOS F_FULLFSYNC."""
    if durability == "none":
        return
    os.fsync(descriptor)
    if durability == "full" and sys.platform == "darwin":
        import fcntl

        try:
            fcntl.fcntl(descriptor, getattr(fcntl, "F_FULLFSYNC", 51))
        except OSError as error:
            if error.errno not in _UNSYNCABLE:
                raise


def _sync_directory(directory, dir_fd) -> None:
    """Persist a directory entry. Windows has no directory fsync.

    Runs after the rename, so a filesystem that cannot fsync a directory
    (EINVAL/ENOTSUP on SMB or FUSE) must not turn a finished write into an error.
    """
    try:
        if dir_fd is not None:
            os.fsync(dir_fd)
        elif os.name != "nt":
            descriptor = os.open(directory, os.O_RDONLY)
            try:
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
    except OSError as error:
        if error.errno not in _UNSYNCABLE:
            raise


def _permissions(mode, name, dir_fd) -> int | None:
    """The mode for the new file; None means the process umask decides."""
    if mode == "umask":
        return None
    if mode is not None:
        return mode
    return _existing_mode(name, dir_fd)


def _set_mode(descriptor, temporary, permissions) -> None:
    """Give the temporary file its final mode before any byte is written.

    Windows Python has no `os.fchmod` (before 3.13); `os.chmod` on the path only
    toggles the read-only bit there, which is all the mode means on Windows.
    """
    if hasattr(os, "fchmod"):
        os.fchmod(descriptor, permissions)
    else:
        os.chmod(temporary, permissions)


def _replace(source, destination, **kwargs) -> None:
    """`os.replace`, retried briefly on Windows.

    Windows refuses to replace a file another process holds open (a reader or a
    concurrent writer's rename) with PermissionError. The refusal is transient,
    so retry for up to about one second before letting it surface. POSIX renames
    never hit this and are not retried.
    """
    if os.name != "nt":
        os.replace(source, destination, **kwargs)
        return
    delay = 0.005
    deadline = time.monotonic() + 1.0
    while True:
        try:
            os.replace(source, destination, **kwargs)
            return
        except PermissionError:
            if time.monotonic() >= deadline:
                raise
            time.sleep(delay)
            delay = min(delay * 2, 0.1)


def _check(durability, overwrite) -> None:
    if durability not in DURABILITIES:
        raise ValueError(f"durability must be one of {DURABILITIES}, not {durability!r}")
    if not isinstance(overwrite, bool):
        raise TypeError("overwrite must be True or False")


def _publish(
    path,
    data,
    *,
    encoding: str | None,
    errors: str | None,
    newline: str | None,
    mode: int | None,
    overwrite: bool,
    durability: str,
    dir_fd: int | None,
    follow_symlinks: bool,
) -> int:
    """Write `data` to a same-directory temporary file, then publish it.

    `encoding is None` writes bytes; otherwise `data` is a str.
    """
    _check(durability, overwrite)
    name = _resolve(path, dir_fd, follow_symlinks)
    permissions = _permissions(mode, name, dir_fd)
    directory = None if dir_fd is not None else os.path.dirname(os.path.abspath(name))
    temporary = _temporary_name(name)
    created = False
    extra_kwargs = {} if dir_fd is None else {"src_dir_fd": dir_fd, "dst_dir_fd": dir_fd}
    try:
        descriptor = os.open(
            temporary,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL,
            0o666 if permissions is None else permissions,
            dir_fd=dir_fd,
        )
        created = True
        open_kwargs = {} if encoding is None else {"encoding": encoding, "errors": errors, "newline": newline}
        with os.fdopen(descriptor, "wb" if encoding is None else "w", **open_kwargs) as stream:
            if permissions is not None:
                _set_mode(stream.fileno(), temporary, permissions)
            written = stream.write(data)
            stream.flush()
            _sync_file(stream.fileno(), durability)
        if overwrite:
            _replace(temporary, name, **extra_kwargs)
        else:
            os.link(temporary, name, follow_symlinks=False, **extra_kwargs)
            os.unlink(temporary, dir_fd=dir_fd)
        if durability in ("file+directory", "full"):
            _sync_directory(directory, dir_fd)
        return written
    finally:
        if created:
            try:
                os.unlink(temporary, dir_fd=dir_fd)
            except FileNotFoundError:
                pass


def write_text(
    path,
    text: str,
    *,
    encoding: str = "utf-8",
    errors: str | None = None,
    newline: str | None = None,
    mode: int | str | None = None,
    overwrite: bool = True,
    durability: str = "file+directory",
    dir_fd: int | None = None,
    follow_symlinks: bool = True,
) -> int:
    """Publish `text` as `path`; return the number of characters written."""
    if not isinstance(text, str):
        raise TypeError("write_text expects str; use write_bytes for bytes")
    return _publish(
        path,
        text,
        encoding=encoding,
        errors=errors,
        newline=newline,
        mode=mode,
        overwrite=overwrite,
        durability=durability,
        dir_fd=dir_fd,
        follow_symlinks=follow_symlinks,
    )


def write_bytes(
    path,
    data,
    *,
    mode: int | str | None = None,
    overwrite: bool = True,
    durability: str = "file+directory",
    dir_fd: int | None = None,
    follow_symlinks: bool = True,
) -> int:
    """Publish bytes-like `data` as `path`; return the number of bytes written."""
    if not isinstance(data, (bytes, bytearray, memoryview)):
        raise TypeError("write_bytes expects bytes, bytearray or memoryview; use write_text for str")
    return _publish(
        path,
        bytes(data),
        encoding=None,
        errors=None,
        newline=None,
        mode=mode,
        overwrite=overwrite,
        durability=durability,
        dir_fd=dir_fd,
        follow_symlinks=follow_symlinks,
    )


def write_json(path, value: Any, **kwargs) -> int:
    """Serialize `value` as JSON and publish it as `path`.

    Serialization happens before the file is touched, so a value that cannot be
    encoded leaves the destination untouched instead of publishing a fragment.

    Accepted JSON keywords: `indent` (default 2), `sort_keys` (default False),
    `ensure_ascii` (default False), `allow_nan` (default True), `separators`
    (default None, the stdlib default), `default` (default None, as in
    `json.dumps`), `newline` (default "\\n", None for none). Remaining
    keywords go to `write_text`.
    """
    indent = kwargs.pop("indent", 2)
    sort_keys = kwargs.pop("sort_keys", False)
    ensure_ascii = kwargs.pop("ensure_ascii", False)
    allow_nan = kwargs.pop("allow_nan", True)
    separators = kwargs.pop("separators", None)
    default = kwargs.pop("default", None)
    newline = kwargs.pop("newline", "\n")
    body = json.dumps(value, indent=indent, sort_keys=sort_keys, ensure_ascii=ensure_ascii,
                      allow_nan=allow_nan, separators=separators, default=default)
    return write_text(path, body + (newline or ""), **kwargs)


class Staged:
    """An open temporary file beside `path`, published only when asked.

    `publish()` renames it over the destination; `discard()` removes it. The
    context manager from `atomic_path` does one of the two for you.

    `binary=True` gives a bytes stream (for chunked copies, zip files, uploads).
    `path` is the temporary file's name (relative to `dir_fd` when one is
    given). A caller that must check something before publishing (the staged
    bytes, or that the destination is unchanged) calls `sync()`, checks, then
    `publish()` or `discard()`; inside `atomic_path`, `discard()` also stops
    the automatic publish.
    """

    def __init__(self, path, *, mode=None, overwrite=True, durability="file+directory",
                 dir_fd=None, encoding="utf-8", follow_symlinks=True, binary=False):
        _check(durability, overwrite)
        self._name = _resolve(path, dir_fd, follow_symlinks)
        self._dir_fd = dir_fd
        self._overwrite = overwrite
        self._durability = durability
        self._directory = None if dir_fd is not None else os.path.dirname(os.path.abspath(self._name))
        self._temporary = _temporary_name(self._name)
        self._finished = False
        permissions = _permissions(mode, self._name, dir_fd)
        descriptor = os.open(
            self._temporary,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL,
            0o666 if permissions is None else permissions,
            dir_fd=dir_fd,
        )
        try:
            if permissions is not None:
                _set_mode(descriptor, self._temporary, permissions)
            if binary:
                self.stream: TextIO | BinaryIO = os.fdopen(descriptor, "wb")
            else:
                self.stream = os.fdopen(descriptor, "w", encoding=encoding, newline="")
        except BaseException:
            os.close(descriptor)
            os.unlink(self._temporary, dir_fd=dir_fd)
            raise

    @property
    def path(self) -> str:
        """The temporary file, relative to `dir_fd` when one was given."""
        return self._temporary

    @property
    def finished(self) -> bool:
        return self._finished

    def write(self, data) -> int:
        return self.stream.write(data)

    def fileno(self) -> int:
        return self.stream.fileno()

    def sync(self) -> None:
        """Flush and fsync the staged bytes so they can be read back and checked."""
        self.stream.flush()
        _sync_file(self.stream.fileno(), self._durability)

    def publish(self) -> None:
        if self._finished:
            raise RuntimeError("staged write is already finished")
        self._finished = True
        try:
            self.sync()
            self.stream.close()
            extra_kwargs = {} if self._dir_fd is None else {"src_dir_fd": self._dir_fd, "dst_dir_fd": self._dir_fd}
            if self._overwrite:
                _replace(self._temporary, self._name, **extra_kwargs)
            else:
                os.link(self._temporary, self._name, follow_symlinks=False, **extra_kwargs)
                os.unlink(self._temporary, dir_fd=self._dir_fd)
            if self._durability in ("file+directory", "full"):
                _sync_directory(self._directory, self._dir_fd)
        except BaseException:
            self.discard()
            raise

    def discard(self) -> None:
        self._finished = True
        if not self.stream.closed:
            self.stream.close()
        try:
            os.unlink(self._temporary, dir_fd=self._dir_fd)
        except FileNotFoundError:
            pass

    def __enter__(self) -> "Staged":
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        if not self._finished:
            self.discard()


@contextmanager
def atomic_path(path, **kwargs) -> Iterator[Staged]:
    """Yield a `Staged` file; publish it when the block exits normally.

        with atomic_path(target) as staged:
            staged.write("{")
            staged.write(body)
        # `target` is replaced here.

    An exception inside the block discards the temporary file and re-raises, so
    the destination keeps its previous bytes.
    """
    staged = Staged(path, **kwargs)
    try:
        yield staged
    except BaseException:
        staged.discard()
        raise
    else:
        if not staged.finished:
            staged.publish()
