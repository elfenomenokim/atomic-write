# Contributing to atomic-write

Fixes and reports are welcome. You do not need to ask before opening a pull
request for a bug fix.

## Before you start

- **A bug:** open an [issue](https://github.com/elfenomenokim/atomic-write/issues/new/choose)
  with the call you made, the platform and Python version (`python3 --version`),
  and what you expected. A failing test helps most.
- **A bigger change** (a new keyword, a change to `durability` or to the symlink
  policy): open an issue first so the shape can be agreed before you write it.
- **A security problem:** do not open a public issue. See [SECURITY.md](SECURITY.md).

## Set up

Nothing to build; the library is pure Python and has no dependencies.

```sh
git clone https://github.com/elfenomenokim/atomic-write
cd atomic-write
python3 -m pytest tests -q
```

Run the tests from the repository root. The test module adds `python/` to
`sys.path` itself, so you do not need to install the package first.

## What a good patch has

- **A test that fails without the change**, in `tests/test_atomic_write.py`, run
  once against the old code.
- **One write path.** Every public function publishes through the private
  `_publish` helper. A change that gives one function its own temporary-file
  handling is a defect, not a follow-up.
- **A line under Unreleased** in [CHANGELOG.md](CHANGELOG.md) when a caller would
  notice the change.
- **The platforms you did not test** written in the pull request. The `tests`
  workflow runs the suite on Ubuntu, macOS and Windows with Python 3.9 and 3.13.

## Review

Every pull request runs an automatic DeepSeek review. Ask for another pass with
`@claude review` in a comment. If a finding looks wrong, say why in the pull request.

A change is a real defect when it lets a reader see a partially written file,
leaves a temporary file behind after a failure, creates the temporary file wider
than its final mode, or makes `overwrite=False` overwrite an existing file.

Not defects: wording, formatting, type annotations, or a renamed private helper.
