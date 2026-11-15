"""archivectl: delete reads back what list prints, -n writes nothing,
delete without input does nothing, stdout carries records only, archives
are numbered once and for good, the passphrase is asked for at most once,
remote repositories work as local ones, and the help and completions say
what the code does."""
from __future__ import annotations

import os
import pty
import re
import shlex
import shutil
import stat
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from conftest import CONFIG, ROOT, TOOL, Sandbox, options_table

# a record of list: number, date, size
RECORD = re.compile(r"([1-9]\d*)\t(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d)\t(\d+)")
WRITE_VERBS = ["change-passphrase", "create", "delete", "init", "initialise", "restore"]
OLD_TOOL = "dedupctl"
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
        for days, seconds in ages:
            box.fake_archive(now - timedelta(days=days, seconds=seconds))
        # archives named the old way show the numbers they get, in time order
        oldest_first = sorted(range(len(ages)), key=lambda i: ages[i], reverse=True)
        numbers = {i: str(rank + 1) for rank, i in enumerate(oldest_first)}
        listed = box.run_ok("list", *[str(word) for option in filters.items() for word in option])
        assert listed.stderr == ""
        selected = record_names(listed.stdout)
        assert selected == [numbers[i] for i in expected_selection(ages, filters)]
        before = box.state()
        dry_run = box.run_ok("delete", "-n", stdin=listed.stdout)
        assert (dry_run.stdout, box.state()) == ("", before)
        assert re.findall(r"would delete archive (\S+)", dry_run.stderr) == selected
        assert box.run_ok("delete", stdin=listed.stdout).stdout == ""
        assert record_names(box.run_ok("list").stdout) == [numbers[i] for i in oldest_first if numbers[i] not in selected]


@pytest.fixture(scope="module")
def listings(populated: Sandbox) -> dict[Path, str]:
    """What list prints in each directory of the populated sandbox."""
    return {cwd: populated.run_ok("list", cwd=cwd).stdout
            for cwd in (populated.source, populated.source / "plain", populated.source / "inner")}


def draw_options(data: st.DataObject, verb: str, box: Sandbox) -> list[str]:
    """-n or --dry-run among a drawn subset of VERB's other options, values filled in."""
    values = {"--to": str(box.root / "elsewhere"), "--mount": str(box.root / "mountpoint"),
              "--repo": str(box.root / "other-repository")}
    others = [(name, takes) for name, takes in OPTIONS[verb] if name not in ("-n", "--dry-run")]
    chosen = data.draw(st.lists(st.sampled_from(others), unique=True)) if others else []
    groups = [[name, values[name]] if takes else [name] for name, takes in chosen]
    groups.insert(data.draw(st.integers(0, len(groups))), [data.draw(st.sampled_from(["-n", "--dry-run"]))])
    return [word for group in groups for word in group]


def draw_operands(data: st.DataObject, verb: str, box: Sandbox, listing: str,
                  cwd: Path) -> tuple[list[str], str | None]:
    """The arguments after the options and the standard input VERB needs, run from CWD."""
    if verb in ("init", "initialise"):
        return data.draw(st.sampled_from([[], [str(box.source / "fresh")]])), None
    if verb == "delete":
        return (record_names(listing), None) if data.draw(st.booleans()) else ([], listing)
    if verb == "restore":
        paths = REPOSITORY_PATHS["inner" if cwd.name == "inner" else "src"]
        return [record_names(listing)[-1], *data.draw(st.lists(st.sampled_from(paths), unique=True))], None
    return [], None


@settings(max_examples=25)
@given(data=st.data())
def test_dry_run_writes_nothing(populated: Sandbox, listings: dict[Path, str], data: st.DataObject) -> None:
    assert sorted(verb for verb, options in OPTIONS.items() if ("-n", False) in options) == WRITE_VERBS
    verb = data.draw(st.sampled_from(WRITE_VERBS))
    cwd = data.draw(st.sampled_from(sorted(listings)))
    options = draw_options(data, verb, populated)
    operands, stdin = draw_operands(data, verb, populated, listings[cwd], cwd)
    before = populated.state()
    result = populated.run(verb, *options, *operands, cwd=cwd, stdin=stdin)
    refused = ("--to" in options and "--mount" in options or
               "--store-passphrase" in options and ("--repo" in options or "--no-pass" in options))
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
    assert created.stderr == f"{TOOL.name}: created archive 1 of {sandbox.source}\n"
    assert len(record_names(created.stdout)) == 1
    status = sandbox.run_ok("status")
    assert (status.stdout.count("\n"), status.stderr) == (1, "")
    listed = sandbox.run_ok("list")
    assert (listed.stdout, listed.stderr) == (created.stdout, "")
    name = record_names(created.stdout)[0]
    for args in (["check"], ["diff", "--scratch", str(sandbox.root / "tmp"), name], ["restore", name],
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
    assert (result.returncode, result.stdout) == (2, "")
    assert result.stderr == f"{TOOL.name}: unknown command '{name}'; see {TOOL.name} --help\n"
    assert populated.state() == before
    assert not (ROOT / OLD_TOOL).exists()


# A wrong invocation: arguments ({root} the sandbox), standard input, status, and what its one line says.
WRONG = [
    (["frobnicate"], None, 2, "unknown command 'frobnicate'; see"),
    (["--frobnicate", "list"], None, 2, "unknown option '--frobnicate'; see"),
    *[([command, "--no-such-option"], None, 2, "'--no-such-option'") for command in sorted(OPTIONS)],
    (["restore", "99"], None, 1, "no such archive: 99"),
    (["diff", "99"], None, 1, "no such archive: 99"),
    (["delete", "99"], None, 1, "no such archive: 99"),
    (["restore"], None, 2, "restore needs an archive id"),
    (["restore", "abc"], None, 1, "no such archive: abc"),
    (["list", "--older", "abc"], None, 2, "--older needs a number"),
    (["list", "--first", "-3"], None, 2, "--first needs a number"),
    *[([command, "extra"], None, 2, "'extra'") for command in ("create", "check", "status", "list")],
    (["-C", "{root}/missing", "list"], None, 2, "cannot change into"),
    (["init", "{root}/missing"], None, 2, "is not a directory"),
    (["restore", "--to"], None, 2, "--to needs a directory"),
    (["restore", "--mount"], None, 2, "--mount needs a directory"),
    (["diff", "--scratch"], None, 2, "--scratch needs a directory"),
    (["init", "--repo"], None, 2, "--repo needs a repository location"),
    (["delete", "1"], "1\n", 2, "not both"),
]


@pytest.mark.parametrize("args, stdin, status, says", WRONG, ids=[" ".join(case[0]) for case in WRONG])
def test_a_wrong_invocation_is_refused_in_one_line_and_changes_nothing(
        populated: Sandbox, args: list[str], stdin: str | None, status: int, says: str) -> None:
    before = populated.state()
    result = populated.run(*[arg.format(root=populated.root) for arg in args], stdin=stdin)
    assert (result.returncode, result.stdout) == (status, "")
    assert result.stderr.count("\n") == 1 and says in result.stderr, result.stderr
    assert populated.state() == before


@pytest.mark.parametrize("bad", ["nosuch", "..", "*"])
def test_delete_refuses_an_unknown_name(populated: Sandbox, listings: dict[Path, str], bad: str) -> None:
    before = populated.state()
    result = populated.run("delete", stdin=listings[populated.source] + bad + "\n")
    assert (result.returncode, result.stdout) == (1, "")
    assert populated.state() == before


def test_initialise_is_init(sandbox: Sandbox) -> None:
    sandbox.run_ok("initialise", "-n")
    assert not (sandbox.source / CONFIG).exists()
    sandbox.run_ok("initialise")
    assert (sandbox.source / CONFIG).read_text().count("BORG_REPO=") == 1


def test_restore_leaves_every_configuration_as_it_is(sandbox: Sandbox) -> None:
    sandbox.populate()
    first = record_names(sandbox.run_ok("list").stdout)[0]
    configs = [sandbox.source / CONFIG, sandbox.source / "inner" / CONFIG]
    for config in configs:
        config.write_text(config.read_text() + "# changed after the backup\n")
    after = [config.read_text() for config in configs]
    (sandbox.source / "a.txt").unlink()
    sandbox.run_ok("restore", first)
    assert [config.read_text() for config in configs] == after
    assert (sandbox.source / "a.txt").read_text() == "outer\n"
    elsewhere = sandbox.root / "elsewhere"
    sandbox.run_ok("restore", "--to", str(elsewhere), first)
    assert (elsewhere / "a.txt").read_text() == "outer\n" and not list(elsewhere.rglob(CONFIG))


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
    scratch = str(sandbox.root / "tmp")
    assert changes(sandbox.run_ok("diff", "--scratch", scratch, first).stdout) == expected
    second = record_names(sandbox.run_ok("create").stdout)[0]
    assert changes(sandbox.run_ok("diff", first, second).stdout) == expected
    assert sandbox.run_ok("diff", "--scratch", scratch, second).stdout == ""
    assert not list((sandbox.root / "tmp").iterdir())


def test_writes_are_logged_under_the_state_directory(sandbox: Sandbox) -> None:
    sandbox.initialise()
    name = record_names(sandbox.run_ok("create").stdout)[0]
    logs = list((sandbox.home / ".local/state/archivectl").glob("*.log"))
    assert len(logs) == 1
    assert "initialised" in logs[0].read_text()
    assert f"created archive {name} of" in logs[0].read_text()


def test_docs_agree_with_the_code() -> None:
    result = subprocess.run(["python3", str(ROOT / "scripts" / "gen-docs.py"), "--check"],
                            capture_output=True, text=True)
    assert (result.returncode, result.stdout) == (0, "")


def newest(box: Sandbox, directory: Path | None = None) -> str:
    return record_names(box.run_ok("list", "--last", "1", cwd=directory).stdout)[0]


def test_create_keeps_an_archive_with_files_borg_could_not_read(sandbox: Sandbox) -> None:
    inner = sandbox.source / "inner"
    sandbox.initialise()
    sandbox.initialise(inner)
    (inner / "locked").write_text("unreadable\n")
    (inner / "locked").chmod(0)
    result = sandbox.run("create", cwd=inner)
    assert result.returncode == 0 and "E locked" in result.stderr
    assert record_names(result.stdout) == [newest(sandbox, inner)]
    logs = (sandbox.home / ".local/state/archivectl").iterdir()
    assert any("locked could not be read" in log.read_text(errors="replace") for log in logs)
    assert len(record_names(sandbox.run_ok("list").stdout)) == 1


def shim(box: Sandbox, name: str, script: str) -> None:
    """A command NAME in front of the real one on the sandbox's PATH."""
    directory = box.root / "shims"
    directory.mkdir(exist_ok=True)
    (directory / name).write_text("#!/bin/sh\n" + script)
    (directory / name).chmod(0o755)
    box.env["PATH"] = f"{directory}:{box.env['PATH']}"


def test_creates_in_the_same_second_get_the_next_numbers(sandbox: Sandbox) -> None:
    sandbox.initialise()
    shim(sandbox, "date", f'case "$1" in +%Y-%m-%d_%H%M%S) echo 2030-01-01_000000 ;; '
                          f'*) exec {shutil.which("date")} "$@" ;; esac\n')
    created = [record_names(sandbox.run_ok("create").stdout)[0] for _ in range(2)]
    assert created == ["1", "2"] and record_names(sandbox.run_ok("list").stdout) == created
    assert archive_names(sandbox) == ["1_2030-01-01_000000", "2_2030-01-01_000000"]


def archive_names(box: Sandbox, directory: Path | None = None) -> list[str]:
    """The names of the archives of the repository of DIRECTORY (src), as borg lists them."""
    listed = subprocess.run(["borg", "list", "--short", str(box.repository(directory))], env=box.env,
                            capture_output=True, text=True, check=True).stdout
    return sorted(listed.splitlines())


def test_numbers_are_never_given_again_after_a_delete(sandbox: Sandbox) -> None:
    sandbox.initialise()
    created = [record_names(sandbox.run_ok("create").stdout)[0] for _ in range(2)]
    sandbox.run_ok("delete", "2")
    assert record_names(sandbox.run_ok("create").stdout) == ["3"]
    sandbox.run_ok("delete", stdin=sandbox.run_ok("list").stdout)
    assert record_names(sandbox.run_ok("create").stdout) == ["4"] and created == ["1", "2"]


def test_a_number_and_a_full_name_name_one_archive(sandbox: Sandbox) -> None:
    sandbox.initialise()
    first = record_names(sandbox.run_ok("create").stdout)[0]
    name = archive_names(sandbox)[0]
    assert sandbox.run_ok("diff", first, name).stdout == ""
    sandbox.run_ok("restore", "--to", str(sandbox.root / "out"), name, "a.txt")
    assert (sandbox.root / "out/a.txt").read_text() == "outer\n"
    assert re.findall(r"would delete archive (\S+)", sandbox.run_ok("delete", "-n", name, first).stderr) == [first]
    sandbox.run_ok("delete", name)
    assert sandbox.run_ok("list").stdout == ""


def test_archives_named_otherwise_are_numbered_once_in_time_order(sandbox: Sandbox) -> None:
    sandbox.initialise()
    for moment in (datetime(2026, 6, 1, 12, tzinfo=timezone.utc), datetime(2026, 1, 2, 3, 4, 5, tzinfo=timezone.utc)):
        sandbox.fake_archive(moment)
    sandbox.borg("create", "--timestamp", "2026-03-01T00:00:00", f"{sandbox.repository()}::by-hand", ".",
                 cwd=sandbox.source / "plain")
    listed = sandbox.run_ok("list").stdout
    assert [line.split("\t")[:2] for line in listed.splitlines()] == [
        ["1", "2026-01-02 03:04:05"], ["2", "2026-03-01 00:00:00"], ["3", "2026-06-01 12:00:00"]]
    sandbox.run_ok("restore", "--to", str(sandbox.root / "out"), "2")
    assert (sandbox.root / "out/p.txt").exists()
    before = sandbox.state()
    assert sandbox.run_ok("diff", "1", "by-hand").stdout == ""
    for args in (["create", "-n"], ["delete", "-n", "2"]):
        result = sandbox.run_ok(*args)
        assert len(re.findall(r"would give archive \S+ the number", result.stderr)) == 3
    assert sandbox.state() == before
    created = sandbox.run_ok("create")
    assert record_names(created.stdout) == ["4"] and created.stderr.count("gave archive") == 3
    assert archive_names(sandbox)[:3] == ["1_2026-01-02_030405", "2_2026-03-01_000000", "3_2026-06-01_120000"]
    assert sandbox.run_ok("list").stdout.splitlines()[:3] == listed.splitlines()
    assert "gave archive" not in sandbox.run_ok("delete", "2").stderr


def test_a_failed_create_deletes_only_the_archive_it_made(sandbox: Sandbox) -> None:
    sandbox.initialise()
    borg = shutil.which("borg")
    shim(sandbox, "borg", f'if [ "$1" = create ]; then {borg} "$@"; exit 2; fi\nexec {borg} "$@"\n')
    result = sandbox.run("create")
    assert (result.returncode, result.stdout) == (2, "")
    assert sandbox.run_ok("list").stdout == ""
    # another run's archive of the same name, which this run's borg did not print
    shim(sandbox, "borg", f'if [ "$1" = create ]; then {borg} "$@" >/dev/null 2>&1; exit 30; fi\nexec {borg} "$@"\n')
    result = sandbox.run("create")
    assert result.returncode == 30
    assert len(record_names(sandbox.run_ok("list").stdout)) == 1


def test_delete_takes_ids_as_arguments_or_on_standard_input_not_both(populated: Sandbox,
                                                                     listings: dict[Path, str]) -> None:
    numbers = record_names(listings[populated.source])
    before = populated.state()
    dry_run = populated.run_ok("delete", "-n", *numbers)
    assert re.findall(r"would delete archive (\S+)", dry_run.stderr) == numbers
    for stdin in ("", numbers[0] + "\n"):
        result = populated.run("delete", numbers[0], stdin=stdin)
        assert (result.returncode, result.stdout) == (2, "") and "not both" in result.stderr
    assert populated.state() == before


@pytest.mark.parametrize("args", [["restore", "--to", "{root}/out", "nosuch"], ["restore", "-n", "nosuch"],
                                  ["restore", "--mount", "{root}/mountpoint", "nosuch"],
                                  ["diff", "--scratch", "{root}/tmp", "nosuch"], ["diff", "nosuch", "nosuch2"]])
def test_a_name_that_names_no_archive_ends_with_status_1(populated: Sandbox, args: list[str]) -> None:
    before = populated.state()
    result = populated.run(*[arg.format(root=populated.root) for arg in args])
    assert (result.returncode, result.stdout) == (1, "")
    assert "no such archive: nosuch" in result.stderr
    assert populated.state() == before


def test_diff_with_the_live_source_extracts_into_tmpdir_and_leaves_nothing(populated: Sandbox,
                                                                          listings: dict[Path, str]) -> None:
    name = record_names(listings[populated.source])[0]
    tmp = Path(populated.env["TMPDIR"])
    tmp.mkdir(exist_ok=True)
    before = sorted(tmp.iterdir())
    assert populated.run_ok("diff", name).stdout == populated.run_ok("diff", "--scratch", str(tmp), name).stdout
    assert sorted(tmp.iterdir()) == before


def test_diff_with_too_little_room_ends_with_status_1(populated: Sandbox, listings: dict[Path, str]) -> None:
    name = record_names(listings[populated.source])[0]
    stub = populated.root / "bin" / "df"
    stub.write_text('#!/bin/sh\necho "Filesystem 1024-blocks Used Available Capacity Mounted on"\necho "x 1 1 0 100% /"\n')
    stub.chmod(0o755)
    try:
        before = populated.state()
        result = populated.run("diff", name)
        assert (result.returncode, result.stdout) == (1, "") and "--scratch" in result.stderr
        assert populated.state() == before
    finally:
        stub.unlink()


def test_check_fails_on_a_damaged_repository(sandbox: Sandbox) -> None:
    sandbox.initialise()
    sandbox.run_ok("create")
    assert sandbox.run_ok("check").stdout == ""
    segment = max((path for path in (sandbox.repository() / "data").rglob("*") if path.is_file()),
                  key=lambda path: path.stat().st_size)
    with open(segment, "r+b") as damaged:
        damaged.seek(segment.stat().st_size // 2)
        damaged.write(b"\0" * 64)
    result = sandbox.run("check")
    assert result.returncode != 0 and result.stdout == ""


def test_repositories_made_by_dedupctl_keep_working(sandbox: Sandbox) -> None:
    old = sandbox.old_tool()
    sandbox.initialise(tool=old, verb="init")
    sandbox.run_ok("backup", tool=old)
    assert (sandbox.repository() / "logs").is_dir()
    first = newest(sandbox)
    sandbox.run_ok("check")
    second = record_names(sandbox.run_ok("create").stdout)[0]
    assert (first, second) == ("1", "2") and archive_names(sandbox)[0].startswith("1_")
    sandbox.run_ok("restore", "--to", str(sandbox.root / "out"), first, "a.txt")
    assert (sandbox.root / "out/a.txt").read_text() == "outer\n"
    assert sandbox.run_ok("diff", first, second).stdout == ""
    sandbox.run_ok("delete", stdin=sandbox.run_ok("list").stdout)
    assert sandbox.run_ok("list").stdout == ""


def test_initialise_refuses_a_repository_under_the_old_name(sandbox: Sandbox) -> None:
    sandbox.run_ok("init", tool=sandbox.old_tool())
    repository = str(sandbox.repository())
    (sandbox.source / CONFIG).unlink()
    before = sandbox.state()
    for flags in (["-n"], []):
        result = sandbox.run("initialise", *flags)
        assert result.returncode == 1 and repository in result.stderr
        assert sandbox.state() == before


def test_the_log_is_private_and_holds_no_borg_output(sandbox: Sandbox) -> None:
    sandbox.initialise()
    sandbox.run_ok("create")
    directory = sandbox.home / ".local/state/archivectl"
    assert stat.S_IMODE(directory.stat().st_mode) == 0o700
    assert {stat.S_IMODE(path.stat().st_mode) for path in directory.iterdir()} == {0o600}
    logs = list(directory.glob("*.log"))
    text = logs[0].read_text()
    assert "throwaway" not in text and "Archive fingerprint" not in text
    assert all(line.split(" ", 1)[1].startswith(("initialised ", "kept the passphrase in pass ", "created "))
               for line in text.splitlines())


@pytest.mark.parametrize("name", ["cost$USER", "`touch PWNED`"])
def test_a_path_with_shell_characters_stays_one_path(sandbox: Sandbox, name: str) -> None:
    directory = sandbox.root / "w" / name
    directory.mkdir(parents=True)
    (directory / "f.txt").write_text("kept\n")
    sandbox.initialise(directory)
    assert sandbox.repository(directory).parent == sandbox.backups
    archive = record_names(sandbox.run_ok("create", cwd=directory).stdout)[0]
    assert archive == newest(sandbox, directory)
    # the passphrase comes from pass, through the BORG_PASSCOMMAND init wrote
    del sandbox.env["BORG_PASSPHRASE"]
    assert record_names(sandbox.run_ok("list", cwd=directory).stdout) == [archive]
    assert not list(sandbox.root.rglob("PWNED"))


def test_diff_escapes_paths_and_reports_changes_of_type(sandbox: Sandbox) -> None:
    source = sandbox.source
    (source / "typ").write_text("a file\n")
    (source / "lnk").symlink_to("a.txt")
    sandbox.initialise()
    first = record_names(sandbox.run_ok("create").stdout)[0]
    (source / "typ").unlink()
    (source / "typ").mkdir()
    (source / "lnk").unlink()
    (source / "lnk").write_text("a file now\n")
    for name in ("tab\tname", "new\nline", "back\\slash", "türkçe ş"):
        (source / name).write_text("new\n")
    expected = {("typ", "modified"), ("lnk", "modified"), ("tab\\tname", "added"), ("new\\nline", "added"),
                ("back\\\\slash", "added"), ("türkçe ş", "added")}
    assert changes(sandbox.run_ok("diff", "--scratch", str(sandbox.root / "tmp"), first).stdout) == expected
    second = record_names(sandbox.run_ok("create").stdout)[0]
    assert changes(sandbox.run_ok("diff", first, second).stdout) == expected


def test_both_diffs_give_the_bytes_of_a_name_that_is_not_utf8(sandbox: Sandbox) -> None:
    def name(raw: bytes) -> Path:
        return sandbox.source / os.fsdecode(raw)
    for raw in (b"a\xfe", b"a\xff", b"b?", b"b\xff", b"gone\xff", b"c?"):
        name(raw).write_text("old\n")
    sandbox.initialise()
    first = record_names(sandbox.run_ok("create").stdout)[0]
    name(b"a\xff").write_text("changed\n")
    name(b"b?").write_text("changed\n")
    name(b"gone\xff").unlink()
    for raw in (b"\xff\xfe-bytes", b"\xff-x", b"?-x", b"tab\tname"):
        name(raw).write_text("new\n")
    expected = {(os.fsdecode(b"a\xff"), "modified"), ("b?", "modified"), (os.fsdecode(b"gone\xff"), "removed"),
                (os.fsdecode(b"\xff\xfe-bytes"), "added"), (os.fsdecode(b"\xff-x"), "added"), ("?-x", "added"),
                ("tab\\tname", "added")}
    live = sandbox.run_ok("diff", "--scratch", str(sandbox.root / "tmp"), first).stdout
    assert changes(live) == expected
    second = record_names(sandbox.run_ok("create").stdout)[0]
    assert changes(sandbox.run_ok("diff", first, second).stdout) == expected


def test_diff_refuses_a_scratch_directory_inside_the_source(populated: Sandbox, listings: dict[Path, str]) -> None:
    name = record_names(listings[populated.source])[0]
    before = populated.state()
    for scratch in (".", "plain"):
        result = populated.run("diff", "--scratch", scratch, name)
        assert (result.returncode, result.stdout) == (2, "") and "outside the source" in result.stderr
    assert populated.state() == before


@pytest.mark.parametrize("args", [["diff", "{first}", "{first}"], ["restore", "-n", "{first}"], ["delete", "-n"]])
def test_a_failing_borg_list_ends_with_borg_status(populated: Sandbox, listings: dict[Path, str],
                                                   args: list[str]) -> None:
    first = record_names(listings[populated.source])[0]
    populated.env["BORG_PASSPHRASE"] = "wrong"
    try:
        result = populated.run(*[arg.format(first=first) for arg in args], stdin=first + "\n")
    finally:
        populated.env["BORG_PASSPHRASE"] = "throwaway"
    assert (result.returncode, result.stdout) == (2, "") and "no such id" not in result.stderr


def test_a_long_path_keeps_its_names_under_name_max(sandbox: Sandbox) -> None:
    directory = sandbox.root / "w"
    while len(os.fsencode(directory)) < 230:
        directory = directory / "dd"
    directory.mkdir(parents=True)
    (directory / "f.txt").write_text("deep\n")
    sandbox.initialise(directory)
    sandbox.run_ok("create", cwd=directory)
    names = [path.name for path in sandbox.backups.iterdir()]
    names += [path.name for path in (sandbox.home / ".local/state/archivectl").iterdir()]
    assert len(names) == 3 and max(len(os.fsencode(name)) for name in names) <= 255


MAKE_DIRECTORIES = {"BINDIR": "bin", "LIBDIR": f"lib/{TOOL.name}", "BASH_COMPLETIONS_DIR": "share/bash-completion/completions",
                    "FISH_COMPLETIONS_DIR": "share/fish/vendor_completions.d", "ZSH_COMPLETIONS_DIR": "share/zsh/site-functions",
                    "MAN1DIR": "share/man/man1", "MAN5DIR": "share/man/man5", "OLD_FISH_COMPLETIONS_DIR": "old-fish"}
OLD_PROG, CONFIG_NAME = "dedupctl", "borgbackup"


def make(target: str, prefix: Path, **overrides: str) -> subprocess.CompletedProcess[str]:
    """make TARGET with PREFIX and every directory the Makefile writes inside PREFIX."""
    directories = {"PREFIX": str(prefix), **{name: str(prefix / path) for name, path in MAKE_DIRECTORIES.items()},
                   **overrides}
    assert all(Path(path).is_relative_to(prefix.parent) for path in directories.values())
    env = {name: value for name, value in os.environ.items()
           if name not in directories and name not in ("DESTDIR", "MAKEFLAGS")}
    return subprocess.run(["make", "-s", target, "DESTDIR=", *(f"{name}={path}" for name, path in directories.items())],
                          cwd=ROOT, env=env, capture_output=True, text=True, check=False)


def test_install_replaces_a_link_and_not_what_it_points_at(tmp_path: Path) -> None:
    prefix, checkout = tmp_path / "prefix", tmp_path / "checkout-copy"
    shutil.copy(TOOL, checkout)
    (prefix / "bin").mkdir(parents=True)
    (prefix / "bin" / TOOL.name).symlink_to(checkout)
    assert make("install", prefix, LIBDIR=str(tmp_path / "elsewhere")).returncode == 0
    installed = prefix / "bin" / TOOL.name
    assert not installed.is_symlink() and checkout.read_bytes() == TOOL.read_bytes()
    result = subprocess.run([str(installed), "list"], cwd=tmp_path, capture_output=True, text=True)
    assert result.returncode == 1 and f"no {CONFIG}" in result.stderr


def test_list_old_shows_what_uninstall_old_removes(tmp_path: Path) -> None:
    prefix = tmp_path / "prefix"
    assert make("install", prefix).returncode == 0
    installed = sorted(path for path in prefix.rglob("*") if not path.is_dir())
    old = [prefix / "bin" / OLD_PROG, prefix / "lib" / OLD_PROG, prefix / "libexec" / OLD_PROG,
           prefix / "old-fish" / f"{OLD_PROG}.fish", prefix / f"share/man/man1/{OLD_PROG}.1",
           prefix / f"share/man/man5/{OLD_PROG}.{CONFIG_NAME}.5"]
    for path in old:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("old\n")
    dangling = prefix / "share/bash-completion/completions" / OLD_PROG
    dangling.symlink_to(tmp_path / "gone")
    assert sorted(make("list-old", prefix).stdout.splitlines()) == sorted(map(str, old + [dangling]))
    assert make("uninstall-old", prefix).returncode == 0
    assert make("list-old", prefix).stdout == ""
    assert sorted(path for path in prefix.rglob("*") if not path.is_dir()) == installed


def test_create_without_its_source_fails_and_still_creates_in_the_parent(sandbox: Sandbox) -> None:
    inner = sandbox.source / "inner"
    sandbox.initialise()
    sandbox.initialise(inner)
    with open(inner / CONFIG, "a") as config:
        config.write("SOURCE_DIR=./missing\n")
    for flags in (["-n"], []):
        result = sandbox.run("create", *flags, cwd=inner)
        assert (result.returncode, result.stdout) == (1, "") and "no directory ./missing" in result.stderr
    assert sandbox.run_ok("list", cwd=inner).stdout == ""
    assert len(record_names(sandbox.run_ok("list").stdout)) == 1


def test_the_log_names_files_borg_could_not_read_and_not_its_messages(sandbox: Sandbox) -> None:
    (sandbox.source / "C dir").mkdir()
    (sandbox.source / "C dir/secret").write_text("unreadable\n")
    (sandbox.source / "C dir/secret").chmod(0)
    sandbox.initialise()
    assert sandbox.run("create").returncode == 0
    text = next((sandbox.home / ".local/state/archivectl").glob("*.log")).read_text()
    assert "C dir/secret could not be read" in text
    assert "changed while borg read it" not in text and "Errno" not in text


def name_of(box: Sandbox, raw: bytes) -> Path:
    return box.source / os.fsdecode(raw)


def test_both_diffs_agree_on_hard_links_whose_names_show_alike(sandbox: Sandbox) -> None:
    name_of(sandbox, b"a\xfe").write_text("lone\n")
    (sandbox.source / "c").write_text("c\n")
    os.link(sandbox.source / "c", name_of(sandbox, b"a\xff"))
    (sandbox.source / "m").mkdir()
    (sandbox.source / "q").mkdir()
    (sandbox.source / "m/a.txt").write_text("m\n")
    os.link(sandbox.source / "m/a.txt", sandbox.source / "q/why?.txt")
    sandbox.initialise()
    first = record_names(sandbox.run_ok("create").stdout)[0]
    os.link(name_of(sandbox, b"a\xfe"), sandbox.source / "u")
    for name in ("c", "m/a.txt"):
        with open(sandbox.source / name, "a") as changed:
            changed.write("more\n")
    expected = {("c", "modified"), ("u", "added"), (os.fsdecode(b"a\xff"), "modified"), ("m/a.txt", "modified"),
                ("q/why?.txt", "modified")}
    assert changes(sandbox.run_ok("diff", "--scratch", str(sandbox.root / "tmp"), first).stdout) == expected
    second = record_names(sandbox.run_ok("create").stdout)[0]
    assert changes(sandbox.run_ok("diff", first, second).stdout) == expected


def archives_with_names_that_show_alike(box: Sandbox) -> tuple[str, str]:
    """Two archives in which only a\\xff of a\\xfe and a\\xff changed."""
    for raw in (b"a\xfe", b"a\xff"):
        name_of(box, raw).write_text("old\n")
    box.initialise()
    first = record_names(box.run_ok("create").stdout)[0]
    name_of(box, b"a\xff").write_text("changed\n")
    return first, record_names(box.run_ok("create").stdout)[0]


@pytest.mark.parametrize("lookup, status", [("printf same; exit 0", 1), ("exit 2", 2)])
def test_diff_of_names_that_show_alike_refuses_or_fails_with_borg(sandbox: Sandbox, lookup: str, status: int) -> None:
    first, second = archives_with_names_that_show_alike(sandbox)
    borg = shutil.which("borg")
    shim(sandbox, "borg", f'case "$*" in *pf:*) {lookup} ;; esac\nexec {borg} "$@"\n')
    result = sandbox.run("diff", first, second)
    assert (result.returncode, result.stdout) == (status, "")
    assert ("cannot tell which is modified" in result.stderr) == (status == 1)


def test_a_failing_listing_of_raw_paths_ends_with_borg_status(sandbox: Sandbox) -> None:
    first, second = archives_with_names_that_show_alike(sandbox)
    borg = shutil.which("borg")
    shim(sandbox, "borg", f'case "$*" in *bpath*) exit 2 ;; esac\nexec {borg} "$@"\n')
    result = sandbox.run("diff", first, second)
    assert (result.returncode, result.stdout) == (2, "")


def test_files_borg_could_not_read_are_named_with_their_own_bytes(sandbox: Sandbox) -> None:
    for raw in (b"x\xfe", b"x\xff"):
        name_of(sandbox, raw).write_text("unreadable\n")
        name_of(sandbox, raw).chmod(0)
    sandbox.initialise()
    result = sandbox.run("create")
    assert result.returncode == 0
    stderr = os.fsencode(result.stderr)
    assert b"x\xfe" in stderr and b"x\xff" in stderr and b"\xed\xb3" not in stderr
    log = next((sandbox.home / ".local/state/archivectl").glob("*.log")).read_bytes()
    assert b"x\xfe could not be read" in log and b"x\xff could not be read" in log


def test_a_source_borg_cannot_enter_is_reported_as_such(sandbox: Sandbox) -> None:
    sandbox.initialise()
    (sandbox.source / "closed").mkdir(mode=0o600)
    with open(sandbox.source / CONFIG, "a") as config:
        config.write("SOURCE_DIR=./closed\n")
    result = sandbox.run("create")
    assert (result.returncode, result.stdout) == (1, "")
    assert "no directory ./closed it can read" in result.stderr and "borg status" not in result.stderr
    log = next((sandbox.home / ".local/state/archivectl").glob("*.log")).read_text()
    assert "no directory ./closed it can read" in log


def test_delete_with_a_terminal_on_stdin_waits_for_nothing(populated: Sandbox) -> None:
    before = populated.state()
    leader, follower = pty.openpty()
    try:
        result = subprocess.run([str(TOOL), "delete", "-n"], cwd=populated.source, stdin=follower,
                                capture_output=True, text=True, env=populated.env, timeout=60)
    finally:
        os.close(follower)
        os.close(leader)
    assert (result.returncode, result.stdout) == (2, "")
    assert f"{TOOL.name} list --older 30 | {TOOL.name} delete -n" in result.stderr
    assert result.stderr.count("\n") == 1
    assert populated.state() == before




def bash_completion(box: Sandbox, line: str) -> list[str]:
    """What the bash completion offers for LINE, the cursor at its end, run in src/."""
    script = (f"source {ROOT}/completions/bash/{TOOL.name}.bash; COMP_LINE=$1; COMP_POINT=${{#1}}; "
              f'_{TOOL.name}; printf "%s\\n" "${{COMPREPLY[@]}}"')
    result = subprocess.run(["bash", "-c", script, "bash", line], cwd=box.source, env=box.env, stdin=subprocess.DEVNULL,
                            capture_output=True, text=True, check=True)
    return sorted(word for word in result.stdout.split("\n") if word)


def fish_completion(box: Sandbox, line: str) -> list[str]:
    """What the fish completion offers for LINE, run in src/: candidate and description, one per line."""
    if shutil.which("fish") is None:
        pytest.skip("fish is not installed")
    script = f"source {ROOT}/completions/fish/{TOOL.name}.fish; complete -C {shlex.quote(line)}"
    result = subprocess.run(["fish", "--no-config", "-c", script], cwd=box.source, env=box.env,
                            stdin=subprocess.DEVNULL, capture_output=True, text=True, check=True)
    return sorted(result.stdout.splitlines())


def completion_sandbox(box: Sandbox) -> list[str]:
    """src initialised, its passphrase in pass, with two archives and the tool
    on PATH, but no passphrase in the environment; the archives' records"""
    box.initialise()
    box.run_ok("create")
    box.run_ok("create")
    box.env["PATH"] = f"{ROOT}:{box.env['PATH']}"
    del box.env["BORG_PASSPHRASE"]
    return box.run_ok("list").stdout.splitlines()


def test_bash_completes_numbers_directories_and_the_paths_in_an_archive(sandbox: Sandbox) -> None:
    completion_sandbox(sandbox)
    directories = ["fresh", "inner", "plain"]
    cases = {"restore ": ["1", "2"], "delete ": ["1", "2"], "delete 1 ": ["1", "2"], "diff 1 ": ["1", "2"],
             "diff 1 2 ": [], "restore 1 pl": ["plain/"], "restore 1 plain/": ["plain/p.txt"],
             "restore --to /x 2 inner/s": ["inner/sub/"], "init ": directories, "init fresh ": [], "-C ": directories,
             "restore --to ": directories, "restore --mount ": directories, "diff --scratch ": directories,
             "init --repo ": [], "list --older ": [], "create ": [], "check ": [], "list ": [], "status ": [],
             f"-C {sandbox.root} restore ": [], f"-C {sandbox.source}/plain restore ": ["1", "2"]}
    for line, offered in cases.items():
        assert bash_completion(sandbox, f"{TOOL.name} {line}") == sorted(offered), line


def test_fish_completes_numbers_with_dates_directories_and_the_paths_in_an_archive(sandbox: Sandbox) -> None:
    records = completion_sandbox(sandbox)
    dated = sorted("\t".join(record.split("\t")[:2]) for record in records)
    directories = ["fresh/\tDirectory", "inner/\tDirectory", "plain/\tDirectory"]
    cases = {"restore ": dated, "delete ": dated, "delete 1 ": dated, "diff 1 ": dated, "diff 1 2 ": [],
             "restore 1 pl": ["plain/"], "restore 1 plain/": ["plain/p.txt"], "init ": directories,
             "-C ": directories, "restore --to ": directories, "restore --mount ": directories,
             "diff --scratch ": directories, "init --repo ": [], "list --older ": [], "list --last ": [],
             "create ": [], "check ": [], "list ": [], "status ": [], f"-C {sandbox.source}/plain restore ": dated}
    for line, offered in cases.items():
        assert fish_completion(sandbox, f"{TOOL.name} {line}") == offered, line


def test_completion_runs_no_borg_that_would_ask_for_the_passphrase(sandbox: Sandbox) -> None:
    sandbox.initialise(None, TOOL, "init", "--no-pass")
    sandbox.run_ok("create")
    sandbox.env["PATH"] = f"{ROOT}:{sandbox.env['PATH']}"
    assert bash_completion(sandbox, f"{TOOL.name} restore ") == ["1"]
    del sandbox.env["BORG_PASSPHRASE"]
    for line in ("restore ", "restore 1 pl", "delete "):
        assert bash_completion(sandbox, f"{TOOL.name} {line}") == [], line
    if shutil.which("fish") is not None:
        assert fish_completion(sandbox, f"{TOOL.name} restore ") == []


def help_phrases() -> dict[str, str]:
    """Each command of the top-level help and the phrase after it."""
    lines = subprocess.run([str(TOOL), "--help"], capture_output=True, text=True, check=True).stdout.splitlines()
    phrases: dict[str, str] = {}
    for i, line in enumerate(lines):
        match = re.match(r"^  ([a-z][a-z-]*)\b(.*?)(?:\s{2,}(\S.*))?$", line)
        if match and match.group(1) != TOOL.name:
            phrases[match.group(1)] = match.group(3) or lines[i + 1].strip()
    return phrases


def test_the_help_fits_one_screen_and_every_command_has_its_own() -> None:
    result = subprocess.run([str(TOOL), "--help"], capture_output=True, text=True)
    lines = result.stdout.splitlines()
    assert result.returncode == 0 and len(lines) <= 24 and max(map(len, lines)) <= 80
    commands = sorted(help_phrases())
    assert commands == sorted(name for name in OPTIONS if name != "initialise")
    for command in commands + ["initialise"]:
        own = subprocess.run([str(TOOL), command, "--help"], capture_output=True, text=True, stdin=subprocess.DEVNULL)
        assert own.returncode == 0 and own.stdout.startswith("Usage:\n"), command
        assert f"{TOOL.name} {'init' if command == 'initialise' else command}" in own.stdout.splitlines()[1]
        assert own.stdout != result.stdout


def test_completions_describe_commands_with_the_phrases_of_the_help() -> None:
    phrases = help_phrases()
    fish = (ROOT / "completions/fish" / f"{TOOL.name}.fish").read_text()
    fished = dict(re.findall(r"-a ([\w-]+) -d '([^']*)'", fish))
    zsh = (ROOT / "completions/zsh" / f"_{TOOL.name}").read_text()
    zshed = {name: text.replace("\\:", ":") for name, text in re.findall(r"^    '([\w-]+):(.*)'$", zsh, re.M)}
    for command, phrase in phrases.items():
        assert fished[command] == phrase and zshed[command] == phrase, command


def test_status_prints_the_source_and_the_bare_command_status_then_help(sandbox: Sandbox) -> None:
    result = sandbox.run("status")
    assert (result.returncode, result.stdout) == (1, "") and CONFIG in result.stderr
    sandbox.initialise()
    repository = str(sandbox.repository())
    assert sandbox.run_ok("status").stdout.split("\t")[:5] == [str(sandbox.source), repository, "0", "", ""]
    sandbox.run_ok("create")
    date = sandbox.run_ok("list").stdout.split("\t")[1]
    fields = sandbox.run_ok("status", cwd=sandbox.source / "plain").stdout.rstrip("\n").split("\t")
    assert fields[:5] == [str(sandbox.source), repository, "1", "1", date] and int(fields[5]) > 0
    assert sandbox.run_ok().stdout.startswith(sandbox.run_ok("status").stdout + "usage: ")
    elsewhere = sandbox.run(cwd=sandbox.root)
    assert elsewhere.returncode == 1 and elsewhere.stdout.startswith("usage: ") and CONFIG in elsewhere.stderr


def test_dash_c_runs_as_if_started_in_the_directory(populated: Sandbox, listings: dict[Path, str]) -> None:
    inner = populated.source / "inner"
    assert populated.run_ok("-C", str(inner), "list", cwd=populated.root).stdout == listings[inner]
    assert populated.run_ok("-C", "src", "-C", "inner", "status", cwd=populated.root).stdout.startswith(f"{inner}\t")
    result = populated.run("-C", str(populated.root / "nowhere"), "list")
    assert (result.returncode, result.stdout) == (2, "")


def test_create_prints_borg_statistics_only_with_stats(sandbox: Sandbox) -> None:
    sandbox.initialise()
    assert sandbox.run_ok("create").stderr.count("\n") == 1
    with_stats = sandbox.run_ok("create", "--stats")
    assert "Archive fingerprint" in with_stats.stderr and with_stats.stderr.count("\n") > 5
    assert record_names(with_stats.stdout) == ["2"]


def test_init_keeps_the_passphrase_in_pass_and_commands_read_it_from_there(sandbox: Sandbox) -> None:
    sandbox.initialise()
    entry = sandbox.root / "pass" / TOOL.name / f"{storage_name('safe_name', sandbox.source)}.gpg"
    assert entry.read_text() == "throwaway\n"
    assert sandbox.config_value("BORG_PASSCOMMAND") == f"pass show '{TOOL.name}/{entry.name[:-4]}'"
    del sandbox.env["BORG_PASSPHRASE"]
    assert record_names(sandbox.run_ok("create").stdout) == ["1"]
    assert record_names(sandbox.run_ok("list").stdout) == ["1"]
    (sandbox.source / CONFIG).unlink()
    result = sandbox.run("init")
    assert result.returncode == 1 and "pass holds" in result.stderr and not (sandbox.source / CONFIG).exists()


def test_store_passphrase_moves_an_old_source_to_pass(sandbox: Sandbox) -> None:
    sandbox.initialise(None, TOOL, "init", "--no-pass")
    assert "BORG_PASSCOMMAND" not in (sandbox.source / CONFIG).read_text()
    sandbox.run_ok("create")
    before = sandbox.state()
    sandbox.run_ok("init", "-n", "--store-passphrase")
    sandbox.env["BORG_PASSPHRASE"] = "wrong"
    result = sandbox.run("init", "--store-passphrase")
    assert result.returncode == 1 and "not the passphrase" in result.stderr
    assert sandbox.state() == before
    sandbox.env["BORG_PASSPHRASE"] = "throwaway"
    sandbox.run_ok("init", "--store-passphrase")
    assert sandbox.config_value("BORG_PASSCOMMAND").startswith("pass show ")
    assert "already" in sandbox.run_ok("init", "--store-passphrase").stderr
    del sandbox.env["BORG_PASSPHRASE"]
    assert record_names(sandbox.run_ok("list").stdout) == ["1"]


def run_on_a_terminal(box: Sandbox, *args: str, answer: bytes) -> tuple[int, str]:
    """TOOL with ARGS in src/ on a terminal of its own, ANSWER typed at each
    passphrase prompt; its status and all it wrote there."""
    pid, fd = pty.fork()
    if pid == 0:
        os.chdir(box.source)
        os.execve(str(TOOL), [str(TOOL), *args], box.env)
    output = b""
    answered = 0
    while True:
        try:
            chunk = os.read(fd, 4096)
        except OSError:
            break
        if not chunk:
            break
        output += chunk
        while output.count(b"assphrase for") > answered:
            os.write(fd, answer + b"\n")
            answered += 1
    _, status = os.waitpid(pid, 0)
    os.close(fd)
    return os.waitstatus_to_exitcode(status), output.decode(errors="replace").replace("\r", "")


def test_without_a_passphrase_set_it_is_read_once_or_refused(sandbox: Sandbox) -> None:
    sandbox.initialise(None, TOOL, "init", "--no-pass")
    sandbox.run_ok("create")
    sandbox.run_ok("create")
    del sandbox.env["BORG_PASSPHRASE"]
    status, output = run_on_a_terminal(sandbox, "list", answer=b"throwaway")
    assert status == 0 and output.count("assphrase for") == 1
    assert [line.split("\t")[0] for line in output.splitlines() if RECORD.fullmatch(line)] == ["1", "2"]
    result = sandbox.run("list")
    assert (result.returncode, result.stdout) == (1, "") and "needs its passphrase" in result.stderr


def test_init_reads_the_passphrase_of_a_new_repository_once(sandbox: Sandbox) -> None:
    del sandbox.env["BORG_PASSPHRASE"]
    status, output = run_on_a_terminal(sandbox, "init", answer=b"typed once")
    assert status == 0 and output.count("assphrase for") == 1, output
    sandbox.borg("config", str(sandbox.repository()), "max_segment_size", "1048576")
    assert record_names(sandbox.run_ok("create").stdout) == ["1"]
    result = sandbox.run("init", str(sandbox.source / "fresh"))
    assert result.returncode == 1 and "BORG_PASSPHRASE" in result.stderr


def fake_ssh(box: Sandbox) -> str:
    """BORG_RSH for a host that is borg serve in remote/ of the sandbox; the URL of that directory."""
    remote = box.root / "remote"
    remote.mkdir()
    (box.root / "bin" / "fake-ssh").write_text(f"#!/bin/sh\ncd {remote} && exec borg serve --restrict-to-path {remote}\n")
    (box.root / "bin" / "fake-ssh").chmod(0o755)
    box.env["BORG_RSH"] = str(box.root / "bin" / "fake-ssh")
    return f"ssh://tester@fakehost{remote}"


def test_a_repository_on_another_host_works_as_a_local_one(sandbox: Sandbox) -> None:
    url = fake_ssh(sandbox)
    sandbox.run_ok("init", "--repo", f"{url}/papers")
    assert sandbox.config_value("BORG_REPO") == f"{url}/papers"
    # later commands reach the host the way init did, with no BORG_RSH set
    assert sandbox.config_value("BORG_RSH") == sandbox.env.pop("BORG_RSH")
    sandbox.borg("config", str(sandbox.root / "remote/papers"), "max_segment_size", "1048576")
    first = record_names(sandbox.run_ok("create").stdout)[0]
    (sandbox.source / "a.txt").write_text("changed\n")
    second = record_names(sandbox.run_ok("create").stdout)[0]
    assert record_names(sandbox.run_ok("list").stdout) == [first, second] == ["1", "2"]
    assert changes(sandbox.run_ok("diff", first, second).stdout) == {("a.txt", "modified")}
    sandbox.run_ok("restore", "--to", str(sandbox.root / "out"), first, "a.txt")
    assert (sandbox.root / "out/a.txt").read_text() == "outer\n"
    sandbox.run_ok("check")
    sandbox.run_ok("delete", first)
    assert record_names(sandbox.run_ok("list").stdout) == [second]
    # a root that is a URL holds the repository of each source under its name
    sandbox.env.update(BORG_BACKUP_ROOT=url, BORG_RSH=sandbox.config_value("BORG_RSH"))
    inner = sandbox.source / "inner"
    sandbox.run_ok("init", cwd=inner)
    name = storage_name("safe_name", inner)
    assert sandbox.config_value("BORG_REPO", inner) == f"{url}/{name}" and (sandbox.root / "remote" / name).is_dir()
    # init on a source whose repository is there already uses it
    (inner / CONFIG).unlink()
    (sandbox.root / "pass" / TOOL.name / f"{name}.gpg").unlink()
    assert "using the existing" in sandbox.run_ok("init", cwd=inner).stderr


def storage_name(function: str, path: Path) -> str:
    """What FUNCTION of lib/common.sh makes of PATH."""
    script = 'source "$0" && "$1" "$2"'
    return subprocess.run(["bash", "-c", script, str(ROOT / "lib" / "common.sh"), function, str(path)],
                          capture_output=True, text=True, check=True).stdout.rstrip("\n")


def test_repositories_are_named_after_the_path_and_found_under_the_earlier_name(sandbox: Sandbox) -> None:
    sandbox.initialise()
    assert sandbox.repository() == sandbox.backups / storage_name("safe_name", sandbox.source)
    assert storage_name("safe_name", Path("/home/adhd/test")) == "home__adhd__test"
    inner = sandbox.source / "inner"
    encoded = sandbox.backups / storage_name("encoded_name", inner)
    sandbox.borg("init", "--encryption=repokey", str(encoded))
    sandbox.run_ok("init", cwd=inner)
    assert sandbox.repository(inner) == encoded


def test_storage_goes_under_data_backup_when_data_is_mounted(sandbox: Sandbox) -> None:
    del sandbox.env["BORG_BACKUP_ROOT"]
    mounted = subprocess.run(["mountpoint", "-q", "/data"], check=False).returncode == 0
    root = "/data/backup/borg" if mounted else str(sandbox.home / ".borg_backups")
    result = sandbox.run_ok("init", "-n")
    assert f"initialise the Borg repository {root}/{storage_name('safe_name', sandbox.source)}" in result.stderr


def test_the_manual_pages_fit_150_lines_at_80_columns() -> None:
    if shutil.which("man") is None:
        pytest.skip("man is not installed")
    pages = sorted((ROOT / "man").glob("*.[15]"))
    assert len(pages) == 2
    for page in pages:
        rendered = subprocess.run(["man", "-l", str(page)], env={**os.environ, "MANWIDTH": "80", "MANPAGER": "cat"},
                                  capture_output=True, text=True, check=True).stdout
        assert 0 < len(rendered.splitlines()) <= 150, page.name


def test_export_key_prints_the_key_borg_imports_back(sandbox: Sandbox) -> None:
    sandbox.initialise()
    sandbox.run_ok("create")
    before = sandbox.state()
    key = sandbox.run_ok("export-key").stdout
    paper = sandbox.run_ok("export-key", "--paper").stdout
    assert key.startswith("BORG_KEY ") and paper and paper != key
    assert sandbox.state() == before
    exported = sandbox.root / "exported.key"
    exported.write_text(key)
    sandbox.borg("key", "import", str(sandbox.repository()), str(exported))
    assert record_names(sandbox.run_ok("list").stdout) == ["1"]
    result = sandbox.run("export-key", "--qr")
    assert (result.returncode, result.stdout) == (2, "")


def test_change_passphrase_changes_the_repository_and_its_pass_entry(sandbox: Sandbox) -> None:
    sandbox.initialise()
    sandbox.run_ok("create")
    entry = sandbox.root / "pass" / TOOL.name / f"{storage_name('safe_name', sandbox.source)}.gpg"
    del sandbox.env["BORG_PASSPHRASE"]
    before = sandbox.state()
    assert "would give" in sandbox.run_ok("change-passphrase", "-n").stderr
    assert sandbox.state() == before and entry.read_text() == "throwaway\n"
    sandbox.env["BORG_NEW_PASSPHRASE"] = "fresh"
    sandbox.run_ok("change-passphrase")
    del sandbox.env["BORG_NEW_PASSPHRASE"]
    assert entry.read_text() == "fresh\n"
    assert record_names(sandbox.run_ok("list").stdout) == ["1"]
    sandbox.env["BORG_PASSPHRASE"] = "throwaway"
    assert sandbox.run("list").returncode != 0


def test_change_passphrase_reads_the_new_one_twice_on_a_terminal(sandbox: Sandbox) -> None:
    sandbox.initialise(None, TOOL, "init", "--no-pass")
    sandbox.run_ok("create")
    status, output = run_on_a_terminal(sandbox, "change-passphrase", answer=b"typed twice")
    assert status == 0 and output.count("assphrase for") == 2, output
    sandbox.env["BORG_PASSPHRASE"] = "typed twice"
    assert record_names(sandbox.run_ok("list").stdout) == ["1"]
    result = sandbox.run("change-passphrase")
    assert result.returncode == 1 and "BORG_NEW_PASSPHRASE" in result.stderr
