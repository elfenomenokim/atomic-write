<div align="center">

<img src="https://raw.githubusercontent.com/elfenomenokim/atomic-write/main/docs/logo.svg" width="96" height="96" alt="A file icon with a check mark">

# atomic-write

A Python library that replaces a file with complete bytes, or leaves the previous bytes in place.

[한국어](README.ko.md) · Python 3.9+ · no dependencies

[![pypi](https://img.shields.io/pypi/v/feno-atomic-write?label=pypi)](https://pypi.org/project/feno-atomic-write/)
[![tests](https://github.com/elfenomenokim/atomic-write/actions/workflows/tests.yml/badge.svg)](https://github.com/elfenomenokim/atomic-write/actions/workflows/tests.yml)
[![license](https://img.shields.io/github/license/elfenomenokim/atomic-write)](https://github.com/elfenomenokim/atomic-write/blob/main/LICENSE)

[Install](#install) · [Quick start](#quick-start) · [Reference](#reference)

</div>

<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="https://raw.githubusercontent.com/elfenomenokim/atomic-write/main/docs/diagrams/write-path.dark.svg">
    <img src="https://raw.githubusercontent.com/elfenomenokim/atomic-write/main/docs/diagrams/write-path.light.svg" width="640" alt="A write creates an exclusive temporary file beside the destination, sets its final mode, writes and fsyncs, then renames it onto the destination; a failure removes the temporary file and leaves the previous bytes.">
  </picture>
</p>

## Why

`os.replace` renames atomically, but it does not give you a temporary file, a
flush, an fsync, mode handling, create-only semantics, or a directory sync. Every
project that writes state ends up assembling those itself, and the assemblies
disagree: some chmod the temporary file after creating it, some never fsync the
directory, some use a temporary name qualified only by the process id.

The best-known dedicated library, [python-atomicwrites](https://github.com/untitaker/python-atomicwrites),
was archived in July 2022. Its `overwrite` flag gives race-free create-only
semantics; it does not document directory fsync or `dir_fd` control. This library
keeps those two contracts explicit and nothing else.

| | `os.replace` | python-atomicwrites | atomic-write |
|---|---|---|---|
| Same-directory temporary file | you build it | yes | yes |
| Directory fsync | no | not documented | `file+directory` (default) |
| Create-only that survives a race | no | `overwrite=False` | `overwrite=False` |
| Keeps the existing mode | no | not documented | default |
| `dir_fd` containment | you build it | no | `dir_fd=` |
| Maintained | stdlib | archived 2022 | this repository |

## Install

```sh
pip install feno-atomic-write
```

The PyPI name is `feno-atomic-write` because `atomic-write` is too close to existing projects; the import name stays `atomic_write`.

Or install from a checkout:

```sh
python3 -m pip install .
```

## Quick start

A real run in an empty directory: replace a file and keep its mode, then claim a lock file that a second writer cannot take.

```python
import os, stat
from atomic_write import write_json, write_text

write_json("state.json", {"plan": "pro", "remaining": 42})
print(open("state.json").read(), end="")

os.chmod("state.json", 0o600)
write_json("state.json", {"plan": "pro", "remaining": 41})
print(oct(stat.S_IMODE(os.stat("state.json").st_mode)))

write_text("owner.lock", "4242", overwrite=False)
try:
    write_text("owner.lock", "5151", overwrite=False)
except FileExistsError as error:
    print("FileExistsError:", error.filename)
print(open("owner.lock").read())
print(sorted(os.listdir(".")))
```

```text
{
  "plan": "pro",
  "remaining": 42
}
0o600
FileExistsError: owner.lock
4242
['owner.lock', 'state.json']
```

Replace a file and keep its permissions:

```python
from atomic_write import write_text

write_text("~/.config/app/token", "abc123")
```

Publish a claim that must not overwrite anyone else's:

```python
from atomic_write import write_json
from pathlib import Path

write_json(Path("run/owner.json"), {"pid": 4242}, overwrite=False)
# FileExistsError when another process already claimed it.
```

Write inside a directory you already validated:

```python
import os
from atomic_write import write_bytes

directory = os.open(state_dir, os.O_RDONLY)
try:
    write_bytes("cursor.bin", b"\x00\x01", dir_fd=directory)
finally:
    os.close(directory)
```

Skip the fsync where a lost file is acceptable, such as a cache:

```python
from atomic_write import write_json

write_json("cache/quota.json", cache, durability="none")
```

## Reference

### `write_text(path, text, *, encoding="utf-8", errors=None, newline=None, mode=None, overwrite=True, durability="file+directory", dir_fd=None, follow_symlinks=True) -> int`

Writes `text` and returns the number of characters written.

### `write_bytes(path, data, *, mode=None, overwrite=True, durability="file+directory", dir_fd=None, follow_symlinks=True) -> int`

Accepts `bytes`, `bytearray` or `memoryview` and returns the number of bytes
written.

### `write_json(path, value, **kwargs) -> int`

Serializes with `json.dumps` before touching the filesystem, so a value that
cannot be encoded leaves the destination untouched. Accepts `indent` (default 2),
`sort_keys` (default `False`), `ensure_ascii` (default `False`), `allow_nan`
(default `True`), `separators` (default the stdlib default), `default` (as in
`json.dumps`) and `newline` (default `"\n"`; `None` for none). Remaining keywords
go to `write_text`.

### `atomic_path(path, **kwargs)`

Context manager yielding a `Staged` file, published when the block exits
normally and discarded when it raises:

```python
from atomic_write import atomic_path

with atomic_path("report.md") as staged:
    for row in rows:
        staged.write(row + "\n")
# report.md is replaced here, only if the loop finished.
```

`binary=True` gives a bytes stream for chunked copies, zip files or uploads.
`staged.path` names the temporary file and `staged.sync()` flushes and fsyncs it,
so a caller can check the staged bytes, or that the destination is unchanged,
before publishing. Calling `staged.discard()` inside the block skips the publish
and keeps the previous file:

```python
import shutil, zipfile

with open(source, "rb") as src, atomic_path(target, binary=True, mode=0o600) as staged:
    shutil.copyfileobj(src, staged)
    staged.sync()
    if not zipfile.is_zipfile(staged.path):
        staged.discard()  # target keeps its previous bytes
```

### Contracts

| Argument | Values | Meaning |
|---|---|---|
| `overwrite` | `True` (default) | Replace an existing file |
| | `False` | Publish a new file; `FileExistsError` if it exists. Uses `os.link`, so of two racing creators exactly one wins |
| `durability` | `none` | No fsync. A crash may lose the new file |
| | `file` | fsync the new bytes before the rename |
| | `file+directory` (default) | Also fsync the directory, so the rename survives a crash |
| | `full` | `file+directory`, plus macOS `F_FULLFSYNC` so the bytes reach stable media, not only the drive cache |
| `mode` | `int` or `None` | `None` keeps the existing file's permissions; a new file gets `0o666` minus the umask |
| | `"umask"` | Every write gets `0o666` minus the umask, ignoring the existing mode, like a plain `open(path, "w")` |
| `dir_fd` | `int` or `None` | Write relative to an open directory descriptor, using that same descriptor for the rename |
| `follow_symlinks` | `True` (default) | Replace the link's target and keep the link |
| | `False` | Replace the link itself |

A failed write never publishes partial bytes: the destination keeps its previous
contents and the temporary file is removed. Serialization happens before the file
is touched.

Two writers of the same path never share a temporary name, so a nested or
concurrent write cannot publish a file another writer is still filling. The
temporary file is always created beside the destination, whatever the process's
working directory (a launchd job runs with `/`).

A directory that cannot be fsynced (`EINVAL` or `ENOTSUP` on SMB or FUSE) is
skipped rather than raised, because the rename has already happened by then.

## Platform notes

- The test suite passes on macOS arm64 (CPython 3.12), Ubuntu 24.04 arm64
  (CPython 3.12) and Windows 11 (CPython 3.10).
- On Windows there are no POSIX permission bits, `dir_fd` is unavailable and a
  directory cannot be fsynced: `mode` only toggles the read-only bit, the
  directory sync is skipped, and the tests for those features are skipped there.
- Windows refuses to replace a file another process holds open. The rename is
  retried for up to about one second before the `PermissionError` surfaces.
- `write_text` uses Python's text mode, so on Windows `newline=None` writes
  `\r\n`, like `open()`. Pass `newline="\n"` for identical bytes on every platform.
- `dir_fd` is a containment tool, not a sandbox: a name containing `..` is still
  resolved by the kernel. Validate names before passing them.

## Limits

- It writes single files. It does not publish a directory tree, a manifest plus
  its members, or a multi-file transaction.
- It does not lock. Callers that need a read-modify-write cycle own their own lock.
- It does not create parent directories. `FileNotFoundError` is raised instead.
- It does not verify the bytes it wrote by reading them back; `atomic_path` with
  `staged.sync()` lets the caller do that before publishing.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). Run the suite with:

```sh
python3 -m pytest tests -q
```

## License

[MIT](LICENSE).
