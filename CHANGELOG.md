# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses `MAJOR.MINOR.PATCH`.

## [Unreleased]

## [0.1.1] - 2026-11-20

### Fixed

- Windows: writes that set a mode no longer fail with `AttributeError`, because
  Windows Python has no `os.fchmod`; the mode is applied by path instead.
- Windows: the final rename is retried for up to about one second when another
  process holds the destination open, instead of failing at once with `PermissionError`.
- The umask test computes the expected mode from the live umask, so it passes on
  systems whose umask is `002`.

### Changed

- The test suite now runs on macOS, Ubuntu and Windows; POSIX-only features are
  skipped on Windows.

## [0.1.0] - 2026-11-19

### Added

- `write_text`, `write_bytes` and `write_json`, which publish a same-directory
  temporary file and rename it over the destination.
- `overwrite=False` for create-only publication through `os.link`, so of two
  racing creators exactly one succeeds.
- `durability="none" | "file" | "file+directory"`, defaulting to the file and
  directory fsync.
- `mode=` to set permissions, and the existing file's mode kept by default.
- `dir_fd=` to write and rename relative to an open directory descriptor.
- `follow_symlinks=False` to replace a link itself instead of its target.
- `atomic_path()`, a context manager that publishes on a normal exit and discards
  on an exception. `binary=True`, `staged.path`, `staged.sync()` and
  `staged.discard()` let a caller stream chunks and check the staged file before
  it is published.
- `durability="full"` for macOS `F_FULLFSYNC`.
- `mode="umask"` for a fresh default mode on every write.
- `write_json(default=...)`, passed to `json.dumps`.
- A directory that cannot be fsynced (SMB, FUSE) no longer fails a finished write.
