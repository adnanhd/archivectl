"""archivectl: delete reads back what list prints, -n writes nothing,
delete without input does nothing, and stdout carries records only."""
from __future__ import annotations

import os
import re
import shutil
import stat
import subprocess
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from conftest import CONFIG, ROOT, TOOL, Sandbox, options_table, wait_for_a_new_second

RECORD = re.compile(r"(\d{4}-\d\d-\d\d_\d\d:\d\d:\d\d)\t(\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d)\t(\d+)")
WRITE_VERBS = ["create", "delete", "init", "initialise", "restore"]
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
    if verb in ("init", "initialise"):
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
    scratch = str(sandbox.root / "tmp")
    assert changes(sandbox.run_ok("diff", "--scratch", scratch, first).stdout) == expected
    time.sleep(1)
    second = record_names(sandbox.run_ok("create").stdout)[0]
    assert changes(sandbox.run_ok("diff", first, second).stdout) == expected
    assert sandbox.run_ok("diff", "--scratch", scratch, second).stdout == ""
    assert not list((sandbox.root / "tmp").iterdir())


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


def test_create_refuses_a_name_that_is_taken(sandbox: Sandbox) -> None:
    sandbox.initialise()
    shim(sandbox, "date", f'case "$1" in +%Y-%m-%d_%H:%M:%S) echo 2030-01-01_00:00:00 ;; '
                          f'*) exec {shutil.which("date")} "$@" ;; esac\n')
    first = sandbox.run_ok("create").stdout
    result = sandbox.run("create")
    assert (result.returncode, result.stdout) == (1, "") and "exists already" in result.stderr
    assert sandbox.run_ok("list").stdout == first


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


def test_delete_takes_no_names_as_arguments(populated: Sandbox, listings: dict[Path, str]) -> None:
    name = record_names(listings[populated.source])[0]
    before = populated.state()
    for stdin in ("", name + "\n"):
        result = populated.run("delete", name, stdin=stdin)
        assert (result.returncode, result.stdout) == (2, "")
    assert populated.state() == before


@pytest.mark.parametrize("args", [["restore", "--to", "{root}/out", "nosuch"], ["restore", "-n", "nosuch"],
                                  ["restore", "--mount", "{root}/mountpoint", "nosuch"],
                                  ["diff", "--scratch", "{root}/tmp", "nosuch"], ["diff", "nosuch", "nosuch2"]])
def test_a_name_that_names_no_archive_ends_with_status_1(populated: Sandbox, args: list[str]) -> None:
    before = populated.state()
    result = populated.run(*[arg.format(root=populated.root) for arg in args])
    assert (result.returncode, result.stdout) == (1, "")
    assert "no such id: nosuch" in result.stderr
    assert populated.state() == before


def test_diff_with_the_live_source_needs_a_scratch_directory(populated: Sandbox, listings: dict[Path, str]) -> None:
    result = populated.run("diff", record_names(listings[populated.source])[0])
    assert (result.returncode, result.stdout) == (2, "")
    assert "--scratch" in result.stderr


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
    wait_for_a_new_second({first})
    second = record_names(sandbox.run_ok("create").stdout)[0]
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
    logs = list(directory.iterdir())
    assert [stat.S_IMODE(log.stat().st_mode) for log in logs] == [0o600]
    text = logs[0].read_text()
    assert "passphrase" not in text.lower() and "Archive fingerprint" not in text
    assert all(line.split(" ", 1)[1].startswith(("initialised ", "created ")) for line in text.splitlines())


@pytest.mark.parametrize("name", ["cost$USER", "`touch PWNED`"])
def test_a_path_with_shell_characters_stays_one_path(sandbox: Sandbox, name: str) -> None:
    directory = sandbox.root / "w" / name
    directory.mkdir(parents=True)
    (directory / "f.txt").write_text("kept\n")
    sandbox.initialise(directory)
    assert sandbox.repository(directory).parent == sandbox.backups
    archive = record_names(sandbox.run_ok("create", cwd=directory).stdout)[0]
    assert archive == newest(sandbox, directory)
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
    wait_for_a_new_second({first})
    second = record_names(sandbox.run_ok("create").stdout)[0]
    assert changes(sandbox.run_ok("diff", first, second).stdout) == expected


def test_completions_know_the_init_alias() -> None:
    script = (f"source {ROOT}/completions/bash/{TOOL.name}.bash; COMP_WORDS=({TOOL.name} init -); "
              f'COMP_CWORD=2; _{TOOL.name}; printf "%s\\n" "${{COMPREPLY[@]}}"')
    offered = subprocess.run(["bash", "-c", script], capture_output=True, text=True, check=True).stdout.split()
    assert {"-n", "--dry-run"} <= set(offered)


def test_both_diffs_give_the_bytes_of_a_name_that_is_not_utf8(sandbox: Sandbox) -> None:
    sandbox.initialise()
    first = record_names(sandbox.run_ok("create").stdout)[0]
    for name in (b"\xff\xfe-bytes", b"\xff-x", b"?-x", b"tab\tname"):
        (sandbox.source / os.fsdecode(name)).write_text("new\n")
    expected = {(os.fsdecode(b"\xff\xfe-bytes"), "added"), (os.fsdecode(b"\xff-x"), "added"), ("?-x", "added"),
                ("tab\\tname", "added")}
    live = sandbox.run_ok("diff", "--scratch", str(sandbox.root / "tmp"), first).stdout
    assert changes(live) == expected
    wait_for_a_new_second({first})
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
    assert len(names) == 2 and max(len(os.fsencode(name)) for name in names) <= 255


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


def test_fish_completes_directories_after_initialise(tmp_path: Path) -> None:
    if shutil.which("fish") is None:
        pytest.skip("fish is not installed")
    (tmp_path / "subdir").mkdir()
    script = (f"source {ROOT}/completions/fish/{TOOL.name}.fish; "
              f"complete -C '{TOOL.name} initialise su'; complete -C '{TOOL.name} init su'")
    env = {**os.environ, "HOME": str(tmp_path), "XDG_CONFIG_HOME": str(tmp_path), "XDG_DATA_HOME": str(tmp_path)}
    offered = subprocess.run(["fish", "--no-config", "-c", script], cwd=tmp_path, env=env,
                             capture_output=True, text=True, check=True).stdout.split()
    assert offered == ["subdir/", "subdir/"]
