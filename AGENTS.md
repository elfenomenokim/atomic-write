# Agent guide

## Layout

- `python/atomic_write/__init__.py`: the whole library. Every function delegates to
  one private `_publish`, so a change to the write path happens once.
- `tests/test_atomic_write.py`: the contract suite. It runs in under a second and
  needs nothing but the standard library and pytest.
- `pyproject.toml`: packaging. `package-dir` points at `python/`.
- `docs/diagrams/`: Mermaid sources and light/dark SVG output used by the README.
- `public.json`: the file list exported to the public repository.

## Test

```sh
python3 -m pytest tests -q
```

Run the suite from this directory. The test module adds `python/` to `sys.path`
itself, so no install is needed.

## Implementation rules

- Keep one write path. `write_text`, `write_bytes`, `write_json`, `Staged` and
  `atomic_path` all publish through the same private `_publish`; do not give one
  of them its own temporary-file handling.
- Create the temporary file with its final mode. `os.open(..., O_CREAT | O_EXCL,
  mode)` receives the permission, and `os.fchmod` only runs when a mode is known.
  Never create the file first and chmod it afterwards: that is the window this
  library exists to close.
- The temporary file lives in the destination's own directory. `os.replace` is
  only atomic within one filesystem, and `<destination>.tmp` is not unique per
  writer.
- Pass `src_dir_fd`/`dst_dir_fd` to `os.replace` and `os.link` only when a
  `dir_fd` was supplied. A plain path write must call `os.replace(source,
  destination)` with two positional arguments, because callers and tests wrap
  `os.replace` with a two-argument function.
- A failed write leaves the destination untouched and removes the temporary file.
  The `finally` block is the only place that unlinks, and it must tolerate the
  file already being gone.
- `write_json` serializes before it touches the filesystem. A `TypeError` from
  `json.dumps` must not leave a partial file.
- Keep `durability="file+directory"` the default. A caller opts down to `file` or
  `none` explicitly.
- Keep `follow_symlinks=True` the default. `False` replaces the link itself and
  exists for callers that publish an entry another process may have swapped for a
  link.
- Do not add a lock. Callers that need a read-modify-write cycle own their lock;
  this library publishes one complete file.

## Code review rules

A change is a real defect when it:

- lets a reader observe a partially written destination;
- leaves a temporary file behind after a failed write;
- creates the temporary file with wider permissions than its final mode;
- makes `overwrite=False` overwrite an existing file, or lets two racing
  creators both succeed;
- changes what `durability` levels do, or silently skips the fsync the default
  promises;
- breaks the rule that a plain path write calls `os.replace` with two arguments;
- adds a dependency.

Not defects: wording, formatting, type annotations, comment style, requested extra
tests, or a renamed private helper.

## Do not

- Do not publish to PyPI or create the public repository without owner review.
- Do not put real home paths, hostnames, credentials or account data in the README,
  the diagrams or the tests.
- Do not regenerate diagram SVGs by hand; render them with `mmdc` from the `.mmd`.
