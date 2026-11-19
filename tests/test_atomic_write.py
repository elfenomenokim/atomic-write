"""Contract tests for atomic_write: every write publishes whole bytes or nothing."""
import json
import os
import stat
import sys
import threading
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "python"))

import atomic_write  # noqa: E402
from atomic_write import atomic_path, write_bytes, write_json, write_text  # noqa: E402


def only_names(directory: Path) -> list[str]:
    """Every entry in `directory`, so a leaked temporary file fails a test."""
    return sorted(p.name for p in directory.iterdir())


# --- the basic contract -------------------------------------------------------


def test_creates_a_new_file_with_its_text(tmp_path):
    target = tmp_path / "state.json"
    written = write_text(target, '{"a": 1}')
    assert written == 8
    assert target.read_text() == '{"a": 1}'
    assert only_names(tmp_path) == ["state.json"]


def test_replaces_existing_bytes_completely(tmp_path):
    target = tmp_path / "state.json"
    target.write_text("a much longer previous value")
    write_text(target, "short")
    assert target.read_text() == "short"


def test_writes_bytes_and_bytearray_and_memoryview(tmp_path):
    target = tmp_path / "blob.bin"
    assert write_bytes(target, b"\x00\xff") == 2
    assert target.read_bytes() == b"\x00\xff"
    write_bytes(target, bytearray(b"buffer"))
    assert target.read_bytes() == b"buffer"
    write_bytes(target, memoryview(b"view"))
    assert target.read_bytes() == b"view"


def test_relative_path_is_accepted(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    write_text("relative.txt", "body")
    assert (tmp_path / "relative.txt").read_text() == "body"


# --- create-only --------------------------------------------------------------


def test_create_only_publishes_a_new_file(tmp_path):
    target = tmp_path / "claim.json"
    write_text(target, "first", overwrite=False)
    assert target.read_text() == "first"


def test_create_only_refuses_an_existing_file(tmp_path):
    target = tmp_path / "claim.json"
    target.write_text("held")
    with pytest.raises(FileExistsError):
        write_text(target, "replacement", overwrite=False)
    assert target.read_text() == "held"
    assert only_names(tmp_path) == ["claim.json"]


def test_create_only_lets_exactly_one_of_two_creators_win(tmp_path):
    target = tmp_path / "claim.json"
    outcomes = []
    start = threading.Barrier(2)

    def create(body):
        start.wait()
        try:
            write_text(target, body, overwrite=False)
            outcomes.append(("created", body))
        except FileExistsError:
            outcomes.append(("refused", body))

    threads = [threading.Thread(target=create, args=(body,)) for body in ("one", "two")]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert sorted(outcome for outcome, _ in outcomes) == ["created", "refused"]
    winner = next(body for outcome, body in outcomes if outcome == "created")
    assert target.read_text() == winner


# --- permissions --------------------------------------------------------------


def test_keeps_the_existing_mode_by_default(tmp_path):
    target = tmp_path / "secret.json"
    target.write_text("old")
    target.chmod(0o600)
    write_text(target, "new")
    assert stat.S_IMODE(target.stat().st_mode) == 0o600


def test_a_new_file_uses_the_umask_not_the_previous_file(tmp_path):
    target = tmp_path / "fresh.json"
    write_text(target, "body")
    # 0o666 minus the process umask; the write must not impose a wider mode.
    assert stat.S_IMODE(target.stat().st_mode) & 0o022 == 0


def test_an_explicit_mode_wins_over_the_existing_one(tmp_path):
    target = tmp_path / "secret.json"
    target.write_text("old")
    target.chmod(0o644)
    write_text(target, "new", mode=0o600)
    assert stat.S_IMODE(target.stat().st_mode) == 0o600


# --- symlinks -----------------------------------------------------------------


def test_replaces_the_target_and_keeps_the_symlink(tmp_path):
    target = tmp_path / "auth.json"
    target.write_text("old")
    target.chmod(0o640)
    link = tmp_path / "linked.json"
    link.symlink_to(target.name)
    write_text(link, '{"한글": "value"}')
    assert target.read_text() == '{"한글": "value"}'
    assert stat.S_IMODE(target.stat().st_mode) == 0o640
    assert link.is_symlink()
    assert only_names(tmp_path) == ["auth.json", "linked.json"]


def test_a_dangling_symlink_creates_its_target(tmp_path):
    target = tmp_path / "missing.json"
    link = tmp_path / "linked.json"
    link.symlink_to(target.name)
    write_text(link, "body")
    assert target.read_text() == "body"
    assert link.is_symlink()


def test_follow_symlinks_false_replaces_the_link_itself(tmp_path):
    target = tmp_path / "outside.txt"
    target.write_text("outside")
    entry = tmp_path / "index.html"
    entry.symlink_to(target)
    write_text(entry, "new entry", follow_symlinks=False)
    assert entry.is_symlink() is False
    assert entry.read_text() == "new entry"
    assert target.read_text() == "outside", "the link target is untouched"
    assert only_names(tmp_path) == ["index.html", "outside.txt"]


def test_follow_symlinks_true_is_the_default(tmp_path):
    target = tmp_path / "real.txt"
    target.write_text("old")
    entry = tmp_path / "entry.txt"
    entry.symlink_to(target.name)
    write_text(entry, "new")
    assert entry.is_symlink() is True
    assert target.read_text() == "new"


def test_write_bytes_follows_the_same_symlink_policy(tmp_path):
    target = tmp_path / "outside.bin"
    target.write_bytes(b"outside")
    entry = tmp_path / "entry.bin"
    entry.symlink_to(target)
    write_bytes(entry, b"inside", follow_symlinks=False)
    assert target.read_bytes() == b"outside"
    assert entry.read_bytes() == b"inside"


# --- failure keeps the previous bytes ----------------------------------------


def test_a_failed_write_keeps_the_previous_bytes(tmp_path, monkeypatch):
    target = tmp_path / "receipt.json"
    target.write_text('{"status":"complete"}')
    real_fdopen = os.fdopen

    class Interrupted:
        def __init__(self, stream):
            self.stream = stream

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            self.stream.close()

        def fileno(self):
            return self.stream.fileno()

        def write(self, text):
            self.stream.write(text[:3])
            self.stream.flush()
            raise OSError("simulated disk-full after a partial write")

    monkeypatch.setattr(os, "fdopen", lambda *a, **k: Interrupted(real_fdopen(*a, **k)))
    with pytest.raises(OSError, match="disk-full"):
        write_text(target, '{"status":"replacement"}')
    assert target.read_text() == '{"status":"complete"}'
    assert only_names(tmp_path) == ["receipt.json"]


def test_a_failed_rename_keeps_the_previous_bytes_and_leaves_no_temporary(tmp_path, monkeypatch):
    target = tmp_path / "state.json"
    target.write_text("previous")

    def refuse(*_args, **_kwargs):
        raise OSError("simulated rename failure")

    monkeypatch.setattr(os, "replace", refuse)
    with pytest.raises(OSError, match="rename failure"):
        write_text(target, "replacement")
    assert target.read_text() == "previous"
    assert only_names(tmp_path) == ["state.json"]


def test_an_unserializable_json_value_leaves_the_file_untouched(tmp_path):
    target = tmp_path / "state.json"
    target.write_text('{"kept":true}')
    with pytest.raises(TypeError):
        write_json(target, {"bad": object()})
    assert target.read_text() == '{"kept":true}'
    assert only_names(tmp_path) == ["state.json"]


def test_a_missing_parent_directory_raises_and_leaves_nothing(tmp_path):
    target = tmp_path / "absent" / "state.json"
    with pytest.raises(FileNotFoundError):
        write_text(target, "body")
    assert only_names(tmp_path) == []


# --- concurrency --------------------------------------------------------------


def test_concurrent_writers_never_publish_partial_bytes(tmp_path):
    target = tmp_path / "ledger.json"
    bodies = [json.dumps({"writer": index, "padding": "x" * 4096}) for index in range(8)]
    failures = []

    def write(body):
        try:
            write_text(target, body)
        except Exception as error:  # pragma: no cover - surfaced below
            failures.append(error)

    threads = [threading.Thread(target=write, args=(body,)) for body in bodies]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert failures == []
    assert target.read_text() in bodies
    assert only_names(tmp_path) == ["ledger.json"]


def test_nested_writes_use_independent_temporary_files(tmp_path, monkeypatch):
    target = tmp_path / "cursor.json"
    target.write_text('{"old": true}')
    real_replace = os.replace
    nested = []

    def reentrant(source, destination, **kwargs):
        if not nested:
            nested.append(True)
            write_text(target, '{"nested": true}')
        return real_replace(source, destination, **kwargs)

    monkeypatch.setattr(os, "replace", reentrant)
    write_text(target, '{"outer": true}')
    assert json.loads(target.read_text()) == {"outer": True}
    assert only_names(tmp_path) == ["cursor.json"]


# --- json ---------------------------------------------------------------------


def test_json_serialization_is_stable_and_readable(tmp_path):
    target = tmp_path / "latest.json"
    value = {"z": "한글", "a": [1, None]}
    write_json(target, value, indent=2, sort_keys=True)
    expected = json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    assert target.read_text() == expected


def test_json_defaults_and_compact_form(tmp_path):
    target = tmp_path / "compact.json"
    write_json(target, {"b": 2, "a": 1}, indent=None, sort_keys=True, newline="")
    assert target.read_text() == '{"a": 1, "b": 2}'


# --- durability ---------------------------------------------------------------


@pytest.mark.parametrize("durability", atomic_write.DURABILITIES)
def test_every_durability_level_publishes_the_bytes(tmp_path, durability):
    target = tmp_path / "state.json"
    write_text(target, durability, durability=durability)
    assert target.read_text() == durability


def test_an_unknown_durability_level_is_refused_before_writing(tmp_path):
    target = tmp_path / "state.json"
    with pytest.raises(ValueError, match="durability must be one of"):
        write_text(target, "body", durability="eventually")
    assert only_names(tmp_path) == []


def test_durability_none_skips_fsync(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(os, "fsync", lambda fd: calls.append(fd))
    write_text(tmp_path / "state.json", "body", durability="none")
    assert calls == []


def test_file_durability_fsyncs_the_file_and_not_the_directory(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(os, "fsync", lambda fd: calls.append(fd))
    write_text(tmp_path / "state.json", "body", durability="file")
    assert len(calls) == 1


def test_file_and_directory_durability_fsyncs_the_directory(tmp_path, monkeypatch):
    calls = []

    def record(fd):
        calls.append(stat.S_ISDIR(os.fstat(fd).st_mode))

    monkeypatch.setattr(os, "fsync", record)
    write_text(tmp_path / "state.json", "body", durability="file+directory")
    assert calls == [False, True], "the file is synced, then its directory"


# --- dir_fd -------------------------------------------------------------------


def test_dir_fd_writes_inside_the_validated_directory(tmp_path):
    directory = os.open(tmp_path, os.O_RDONLY)
    try:
        write_text("state.json", "body", dir_fd=directory)
        current = os.stat("state.json", dir_fd=directory, follow_symlinks=False)
        assert current.st_size == 4
        with open(tmp_path / "state.json") as stream:
            assert stream.read() == "body"
        assert only_names(tmp_path) == ["state.json"]
    finally:
        os.close(directory)


def test_create_only_with_dir_fd_refuses_an_existing_file(tmp_path):
    directory = os.open(tmp_path, os.O_RDONLY)
    try:
        write_bytes("claim.json", b'{"claimed":true}', mode=0o600, overwrite=False, dir_fd=directory)
        current = os.stat("claim.json", dir_fd=directory, follow_symlinks=False)
        assert stat.S_IMODE(current.st_mode) == 0o600
        with pytest.raises(FileExistsError):
            write_bytes("claim.json", b"replacement", mode=0o600, overwrite=False, dir_fd=directory)
        assert (tmp_path / "claim.json").read_bytes() == b'{"claimed":true}'
        assert only_names(tmp_path) == ["claim.json"]
    finally:
        os.close(directory)


def test_dir_fd_writes_a_nested_name_relative_to_the_descriptor(tmp_path):
    inside = tmp_path / "inside"
    (inside / "nested").mkdir(parents=True)
    directory = os.open(inside / "nested", os.O_RDONLY)
    try:
        write_text("state.json", "body", dir_fd=directory)
        assert (inside / "nested/state.json").read_text() == "body"
        assert sorted(p.name for p in (inside / "nested").iterdir()) == ["state.json"]
    finally:
        os.close(directory)


# --- the context manager ------------------------------------------------------


def test_atomic_path_publishes_on_success(tmp_path):
    target = tmp_path / "state.json"
    target.write_text("previous")
    with atomic_path(target) as staged:
        staged.write("{")
        staged.write('"a": 1')
        staged.write("}")
    assert target.read_text() == '{"a": 1}'
    assert only_names(tmp_path) == ["state.json"]


def test_atomic_path_discards_on_exception(tmp_path):
    target = tmp_path / "state.json"
    target.write_text("previous")
    with pytest.raises(RuntimeError):
        with atomic_path(target) as staged:
            staged.write("partial")
            raise RuntimeError("the caller gave up")
    assert target.read_text() == "previous"
    assert only_names(tmp_path) == ["state.json"]


def test_atomic_path_honours_create_only(tmp_path):
    target = tmp_path / "claim.json"
    target.write_text("held")
    with pytest.raises(FileExistsError):
        with atomic_path(target, overwrite=False) as staged:
            staged.write("replacement")
    assert target.read_text() == "held"
    assert only_names(tmp_path) == ["claim.json"]


def test_atomic_path_keeps_the_existing_mode_by_default(tmp_path):
    target = tmp_path / "secret.json"
    target.write_text("old")
    target.chmod(0o600)
    with atomic_path(target) as staged:
        staged.write("new")
    assert stat.S_IMODE(target.stat().st_mode) == 0o600


def test_a_staged_file_cannot_be_published_twice(tmp_path):
    target = tmp_path / "state.json"
    staged = atomic_path(target)
    handle = staged.__enter__()
    handle.write("body")
    handle.publish()
    with pytest.raises(RuntimeError, match="already finished"):
        handle.publish()


# --- argument checking --------------------------------------------------------


def test_write_text_refuses_bytes(tmp_path):
    with pytest.raises(TypeError, match="write_bytes"):
        write_text(tmp_path / "x", b"bytes")


def test_write_bytes_refuses_str(tmp_path):
    with pytest.raises(TypeError, match="write_text"):
        write_bytes(tmp_path / "x", "text")


def test_overwrite_must_be_a_bool(tmp_path):
    with pytest.raises(TypeError, match="overwrite"):
        write_text(tmp_path / "x", "body", overwrite=1)


def test_temporary_file_stays_beside_destination_when_cwd_is_elsewhere(tmp_path, monkeypatch):
    # launchd services run with cwd "/"; the temporary file must not land in cwd.
    elsewhere = tmp_path / "cwd"
    elsewhere.mkdir()
    target_dir = tmp_path / "state"
    target_dir.mkdir()
    monkeypatch.chdir(elsewhere)
    atomic_write.write_text(target_dir / "a.json", "x")
    with atomic_write.atomic_path(target_dir / "b.json") as staged:
        staged.write("y")
    assert sorted(p.name for p in target_dir.iterdir()) == ["a.json", "b.json"]
    assert list(elsewhere.iterdir()) == []


def test_write_json_newline_none_appends_nothing(tmp_path):
    atomic_write.write_json(tmp_path / "v.json", {"a": 1}, newline=None, indent=None)
    assert (tmp_path / "v.json").read_text() == '{"a": 1}'


def test_replacing_a_link_takes_the_regular_file_mode(tmp_path):
    real = tmp_path / "real"
    real.write_text("old")
    real.chmod(0o600)
    link = tmp_path / "link"
    link.symlink_to(real)
    atomic_write.write_text(link, "new", follow_symlinks=False)
    assert not link.is_symlink()
    assert link.stat().st_mode & 0o7777 == 0o600


def test_binary_staged_check_then_discard_keeps_destination(tmp_path):
    target = tmp_path / "blob.bin"
    target.write_bytes(b"old")
    with atomic_path(target, binary=True) as staged:
        staged.write(b"new-bytes")
        staged.sync()
        assert (tmp_path / os.path.basename(staged.path)).read_bytes() == b"new-bytes"
        staged.discard()  # the caller's check failed: do not publish
    assert target.read_bytes() == b"old"
    assert sorted(p.name for p in tmp_path.iterdir()) == ["blob.bin"]


def test_binary_staged_publishes_chunks(tmp_path):
    target = tmp_path / "blob.bin"
    with atomic_path(target, binary=True, mode=0o600) as staged:
        for chunk in (b"a" * 10, b"b" * 10):
            staged.write(chunk)
    assert target.read_bytes() == b"a" * 10 + b"b" * 10
    assert target.stat().st_mode & 0o7777 == 0o600


def test_full_durability_writes(tmp_path):
    write_text(tmp_path / "j.json", "x", durability="full")
    assert (tmp_path / "j.json").read_text() == "x"


def test_unsyncable_directory_does_not_fail_finished_write(tmp_path, monkeypatch):
    import errno
    real_fsync = os.fsync

    def fsync(fd):
        if stat.S_ISDIR(os.fstat(fd).st_mode):
            raise OSError(errno.EINVAL, "not supported")
        return real_fsync(fd)

    monkeypatch.setattr(atomic_write.os, "fsync", fsync)
    write_text(tmp_path / "s.txt", "done")
    assert (tmp_path / "s.txt").read_text() == "done"


def test_write_json_default(tmp_path):
    write_json(tmp_path / "d.json", {"p": Path("/x")}, default=str, indent=None)
    assert (tmp_path / "d.json").read_text() == '{"p": "/x"}\n'


def test_mode_umask_ignores_the_existing_mode(tmp_path):
    target = tmp_path / "u.txt"
    target.write_text("old")
    target.chmod(0o600)
    old = os.umask(0o022)
    try:
        write_text(target, "new", mode="umask")
    finally:
        os.umask(old)
    assert target.stat().st_mode & 0o7777 == 0o644
