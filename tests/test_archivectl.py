"""archivectl: delete reads back what list prints, -n writes nothing,
delete without input does nothing, and stdout carries records only."""
from __future__ import annotations

import re
import subprocess
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from conftest import CONFIG, ROOT, Sandbox, options_table, wait_for_a_new_second

RECORD = re.compile(r"(\d{4}-\d\d-\d\d_\d\d:\d\d:\d\d)\t(\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d)\t(\d+)")
WRITE_VERBS = ["create", "delete", "initialise", "restore"]
OLD_NAMES = ["backup", "prune", "mount", "extract", "size", "log"]
OPTIONS = options_table()
REPOSITORY_PATHS = {"src": ["a.txt", "plain", "inner/b.txt"], "inner": ["b.txt", "sub"]}

# An age is (days, seconds) before now, the seconds keeping every archive
# at least an hour away from a whole number of days.
AGES = st.lists(st.tuples(st.integers(0, 60), st.integers(3600, 82800)), max_size=4, unique=True)
FILTERS = st.fixed_dictionaries({}, optional={
    "--older": st.integers(0, 61), "--newer": st.integers(0, 61),
    "--first": st.integers(0, 5), "--last": st.integers(0, 5)})


def record_names(stdout: str) -> list[str]:
    """The names of the records on STDOUT; any other line fails the test."""
    names = []
    for line in stdout.splitlines():
        match = RECORD.fullmatch(line)
        assert match, f"not a record: {line!r}"
        names.append(match.group(1))
    return names


def changes(stdout: str) -> set[tuple[str, ...]]:
    return {tuple(line.split("\t")) for line in stdout.splitlines()}


def expected_selection(ages: list[tuple[int, int]], filters: dict[str, int]) -> list[int]:
    """Indexes of the AGES list selects with FILTERS, oldest first."""
    kept = [i for i in sorted(range(len(ages)), key=lambda i: ages[i], reverse=True)
            if ("--older" not in filters or ages[i][0] >= filters["--older"])
            and ("--newer" not in filters or ages[i][0] < filters["--newer"])]
    if "--first" in filters:
        kept = kept[:filters["--first"]]
    if "--last" in filters:
        kept = kept[max(0, len(kept) - filters["--last"]):] if filters["--last"] else []
    return kept


@settings(max_examples=8)
@given(ages=AGES, filters=FILTERS)
def test_delete_reads_back_what_list_prints(ages: list[tuple[int, int]], filters: dict[str, int]) -> None:
    with Sandbox() as box:
        box.initialise()
        now = datetime.now(timezone.utc).replace(microsecond=0)
        names = [box.fake_archive(now - timedelta(days=days, seconds=seconds)) for days, seconds in ages]
        listed = box.run_ok("list", *[str(word) for option in filters.items() for word in option])
        assert listed.stderr == ""
        selected = record_names(listed.stdout)
        assert selected == [names[i] for i in expected_selection(ages, filters)]
        before = box.state()
        dry_run = box.run_ok("delete", "-n", stdin=listed.stdout)
        assert (dry_run.stdout, box.state()) == ("", before)
        assert re.findall(r"would delete archive (\S+)", dry_run.stderr) == selected
        assert box.run_ok("delete", stdin=listed.stdout).stdout == ""
        assert record_names(box.run_ok("list").stdout) == sorted(set(names) - set(selected))


@pytest.fixture(scope="module")
def listings(populated: Sandbox) -> dict[Path, str]:
    """What list prints in each directory of the populated sandbox."""
    return {cwd: populated.run_ok("list", cwd=cwd).stdout
            for cwd in (populated.source, populated.source / "plain", populated.source / "inner")}


def draw_options(data: st.DataObject, verb: str, box: Sandbox) -> list[str]:
    """-n or --dry-run among a drawn subset of VERB's other options, values filled in."""
    values = {"--to": str(box.root / "elsewhere"), "--mount": str(box.root / "mountpoint")}
    others = [(name, takes) for name, takes in OPTIONS[verb] if name not in ("-n", "--dry-run")]
    chosen = data.draw(st.lists(st.sampled_from(others), unique=True)) if others else []
    groups = [[name, values[name]] if takes else [name] for name, takes in chosen]
    groups.insert(data.draw(st.integers(0, len(groups))), [data.draw(st.sampled_from(["-n", "--dry-run"]))])
    return [word for group in groups for word in group]


def draw_operands(data: st.DataObject, verb: str, box: Sandbox, listing: str,
                  cwd: Path) -> tuple[list[str], str]:
    """The arguments after the options and the standard input VERB needs, run from CWD."""
    if verb == "initialise":
        return data.draw(st.sampled_from([[], [str(box.source / "fresh")]])), ""
    if verb == "delete":
        return [], listing
    if verb == "restore":
        paths = REPOSITORY_PATHS["inner" if cwd.name == "inner" else "src"]
        return [record_names(listing)[-1], *data.draw(st.lists(st.sampled_from(paths), unique=True))], ""
    return [], ""


@settings(max_examples=25)
@given(data=st.data())
def test_dry_run_writes_nothing(populated: Sandbox, listings: dict[Path, str], data: st.DataObject) -> None:
    assert sorted(verb for verb, options in OPTIONS.items() if ("-n", False) in options) == WRITE_VERBS
    verb = data.draw(st.sampled_from(WRITE_VERBS))
    cwd = data.draw(st.sampled_from(sorted(listings)))
    options = draw_options(data, verb, populated)
    operands, stdin = draw_operands(data, verb, populated, listings[cwd], cwd)
    if verb == "create":
        wait_for_a_new_second({name for listing in listings.values() for name in record_names(listing)})
    before = populated.state()
    result = populated.run(verb, *options, *operands, cwd=cwd, stdin=stdin)
    refused = "--to" in options and "--mount" in options
    assert (result.returncode, result.stdout) == (2 if refused else 0, ""), result.stderr
    assert populated.state() == before


@settings(max_examples=30)
@given(text=st.text(alphabet=" \t\n", max_size=12), flags=st.sampled_from([[], ["-n"], ["--dry-run"]]))
def test_delete_without_input_does_nothing(populated: Sandbox, text: str, flags: list[str]) -> None:
    before = populated.state()
    for cwd in (populated.source, populated.root):
        result = populated.run("delete", *flags, cwd=cwd, stdin=text)
        assert (result.returncode, result.stdout, result.stderr) == (0, "", "")
    assert populated.state() == before


def test_stdout_carries_records_only(sandbox: Sandbox) -> None:
    sandbox.initialise()
    assert sandbox.run_ok("list").stdout == ""
    created = sandbox.run_ok("create")
    assert created.stderr != ""
    assert len(record_names(created.stdout)) == 1
    listed = sandbox.run_ok("list")
    assert (listed.stdout, listed.stderr) == (created.stdout, "")
    name = record_names(created.stdout)[0]
    for args in (["check"], ["diff", name], ["restore", name],
                 ["restore", "--to", str(sandbox.root / "out"), name, "a.txt"],
                 ["initialise", str(sandbox.source / "fresh")]):
        assert sandbox.run_ok(*args).stdout == ""
    assert sandbox.run_ok("delete", stdin=created.stdout).stdout == ""
    assert sandbox.run_ok("list").stdout == ""


def test_create_in_a_parent_keeps_stdout_to_this_repository(sandbox: Sandbox) -> None:
    inner = sandbox.source / "inner"
    sandbox.initialise()
    sandbox.initialise(inner)
    created = sandbox.run_ok("create", cwd=inner)
    assert created.stdout == sandbox.run_ok("list", cwd=inner).stdout
    assert len(record_names(sandbox.run_ok("list").stdout)) == 1


@pytest.mark.parametrize("name", OLD_NAMES)
def test_old_commands_are_gone(populated: Sandbox, name: str) -> None:
    before = populated.state()
    result = populated.run(name)
    assert (result.returncode, result.stdout) == (1, "")
    assert "unknown command" in result.stderr
    assert populated.state() == before
    assert not (ROOT / "dedupctl").exists()


@pytest.mark.parametrize("command", sorted(OPTIONS))
def test_unknown_option_is_refused(populated: Sandbox, command: str) -> None:
    before = populated.state()
    result = populated.run(command, "--no-such-option", stdin="x\n")
    assert (result.returncode, result.stdout) == (2, "")
    assert populated.state() == before


@pytest.mark.parametrize("bad", ["nosuch", "..", "*"])
def test_delete_refuses_an_unknown_name(populated: Sandbox, listings: dict[Path, str], bad: str) -> None:
    before = populated.state()
    result = populated.run("delete", stdin=listings[populated.source] + bad + "\n")
    assert (result.returncode, result.stdout) == (1, "")
    assert populated.state() == before


def test_init_is_initialise(sandbox: Sandbox) -> None:
    sandbox.run_ok("init", "-n")
    assert not (sandbox.source / CONFIG).exists()
    sandbox.run_ok("init")
    assert (sandbox.source / CONFIG).read_text().count("BORG_REPO=") == 1


def test_restore_puts_files_back(sandbox: Sandbox) -> None:
    sandbox.populate()
    name = record_names(sandbox.run_ok("list").stdout)[0]
    (sandbox.source / "a.txt").unlink()
    (sandbox.source / "plain/p.txt").write_text("changed\n")
    sandbox.run_ok("restore", name, cwd=sandbox.source / "plain")
    assert (sandbox.source / "a.txt").read_text() == "outer\n"
    assert (sandbox.source / "plain/p.txt").read_text() == "plain\n"
    elsewhere = sandbox.root / "elsewhere"
    sandbox.run_ok("restore", "--to", str(elsewhere), name, "plain", "inner/b.txt")
    restored = sorted(str(path.relative_to(elsewhere)) for path in elsewhere.rglob("*") if path.is_file())
    assert restored == ["inner/b.txt", "plain/p.txt"]


def test_diff_prints_one_record_per_changed_path(sandbox: Sandbox) -> None:
    sandbox.populate()
    first = record_names(sandbox.run_ok("list").stdout)[0]
    (sandbox.source / "a.txt").write_text("changed\n")
    (sandbox.source / "new.txt").write_text("new\n")
    (sandbox.source / "plain/p.txt").unlink()
    (sandbox.source / ".cache").mkdir()
    (sandbox.source / ".cache/x").write_text("excluded\n")
    expected = {("a.txt", "modified"), ("new.txt", "added"), ("plain/p.txt", "removed")}
    assert changes(sandbox.run_ok("diff", first).stdout) == expected
    time.sleep(1)
    second = record_names(sandbox.run_ok("create").stdout)[0]
    assert changes(sandbox.run_ok("diff", first, second).stdout) == expected
    assert sandbox.run_ok("diff", second).stdout == ""


def test_writes_are_logged_under_the_state_directory(sandbox: Sandbox) -> None:
    sandbox.initialise()
    name = record_names(sandbox.run_ok("create").stdout)[0]
    logs = list((sandbox.home / ".local/state/archivectl").iterdir())
    assert len(logs) == 1
    assert "initialised" in logs[0].read_text()
    assert f"created archive {name}" in logs[0].read_text()


def test_docs_agree_with_the_code() -> None:
    result = subprocess.run(["python3", str(ROOT / "scripts" / "gen-docs.py"), "--check"],
                            capture_output=True, text=True)
    assert (result.returncode, result.stdout) == (0, "")
