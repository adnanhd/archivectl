"""Sandboxes for the archivectl tests: every run gets its own HOME, state,
backup root, Borg base directory and source tree under $TMPDIR."""
from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import tempfile
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from types import TracebackType

import pytest
from hypothesis import HealthCheck, settings

ROOT = Path(__file__).resolve().parent.parent
TOOL = ROOT / "archivectl"
CONFIG = ".borgbackup"
CONFIGS = (".myrsyncbackup", ".borgbackup")
# a pass that keeps its entries as plain files in $PASSWORD_STORE_DIR
PASS_STUB = """#!/bin/sh
case "$1" in
    insert) shift; while [ "${1#-}" != "$1" ]; do shift; done; mkdir -p "$PASSWORD_STORE_DIR/$(dirname "$1")"; cat >"$PASSWORD_STORE_DIR/$1.gpg" ;;
    show) cat "$PASSWORD_STORE_DIR/$2.gpg" ;;
    rm) shift; [ "$1" = -f ] && shift; rm -f "$PASSWORD_STORE_DIR/$1.gpg" ;;
    *) exit 1 ;;
esac
"""

settings.register_profile("tools", deadline=None, suppress_health_check=[HealthCheck.too_slow])
settings.load_profile("tools")


@dataclass
class Result:
    returncode: int
    stdout: str
    stderr: str


def refuse_inside_repository(path: Path) -> None:
    """A sandbox below a backed-up directory would make create back that up too."""
    for parent in path.parents:
        for name in CONFIGS:
            if (parent / name).exists():
                raise RuntimeError(f"{parent} holds {name}; run the tests under another TMPDIR")


def describe(path: Path) -> tuple[str, ...]:
    """Type, mode, and content hash and time or link target and time of PATH;
    a directory's time is left out, since borg's lock files touch it."""
    status = path.lstat()
    if path.is_symlink():
        return (str(path), "link", os.readlink(path), str(status.st_mtime_ns))
    if path.is_dir():
        return (str(path), "dir", oct(status.st_mode))
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    return (str(path), "file", oct(status.st_mode), digest, str(status.st_mtime_ns))


class Sandbox:
    """home/ (HOME and XDG dirs), backups/ (the backup root), borg/ (Borg's
    own cache and security files), pass/ (the entries of a pass stub in
    bin/) and src/, the source, with src/plain a plain directory and
    src/inner a nested source."""

    def __init__(self) -> None:
        self.root = Path(tempfile.mkdtemp(prefix=f"{TOOL.name}-test."))
        refuse_inside_repository(self.root)
        self.home = self.root / "home"
        self.backups = self.root / "backups"
        self.source = self.root / "src"
        for directory in (self.home, self.backups, self.root / "borg", self.root / "tmp", self.root / "pass",
                          self.root / "bin", self.source / "plain", self.source / "inner" / "sub",
                          self.source / "fresh"):
            directory.mkdir(parents=True)
        (self.root / "bin" / "pass").write_text(PASS_STUB)
        (self.root / "bin" / "pass").chmod(0o755)
        for name, text in {"a.txt": "outer", "plain/p.txt": "plain", "inner/b.txt": "inner",
                           "inner/sub/c.txt": "sub"}.items():
            (self.source / name).write_text(text + "\n")
        self.env = self.environment()

    def environment(self) -> dict[str, str]:
        env = {name: value for name, value in os.environ.items()
               if not name.startswith("BORG_") and name not in ("EXCLUDES", "LOG_FILE")}
        env.update(HOME=str(self.home), XDG_CONFIG_HOME=str(self.home / ".config"),
                   XDG_CACHE_HOME=str(self.home / ".cache"), XDG_DATA_HOME=str(self.home / ".local/share"),
                   XDG_STATE_HOME=str(self.home / ".local/state"), TMPDIR=str(self.root / "tmp"),
                   BORG_BACKUP_ROOT=str(self.backups), BORG_BASE_DIR=str(self.root / "borg"),
                   BORG_PASSPHRASE="throwaway", BORG_DISPLAY_PASSPHRASE="no", TZ="UTC",
                   PASSWORD_STORE_DIR=str(self.root / "pass"), PATH=f"{self.root / 'bin'}:{os.environ['PATH']}")
        return env

    def __enter__(self) -> Sandbox:
        return self

    def __exit__(self, kind: type[BaseException] | None, error: BaseException | None,
                 trace: TracebackType | None) -> None:
        subprocess.run(["chmod", "-R", "u+rwx", str(self.root)], check=False)
        shutil.rmtree(self.root)

    def run(self, *args: str, cwd: Path | None = None, stdin: str | None = None, tool: Path = TOOL) -> Result:
        """TOOL with ARGS in CWD (src); STDIN piped in, or else /dev/null as input."""
        completed = subprocess.run([str(tool), *args], cwd=cwd or self.source, input=stdin,
                                   stdin=subprocess.DEVNULL if stdin is None else None,
                                   capture_output=True, text=True, errors="surrogateescape", env=self.env, timeout=300)
        return Result(completed.returncode, completed.stdout, completed.stderr)

    def run_ok(self, *args: str, cwd: Path | None = None, stdin: str | None = None, tool: Path = TOOL) -> Result:
        result = self.run(*args, cwd=cwd, stdin=stdin, tool=tool)
        assert result.returncode == 0, f"{args}: {result.stderr}"
        return result

    def borg(self, *args: str, cwd: Path | None = None) -> None:
        subprocess.run(["borg", *args], cwd=cwd or self.source, env=self.env, check=True,
                       capture_output=True, timeout=300)

    def state(self) -> list[tuple[str, ...]]:
        """Every path in the sandbox, Borg's own base directory included, described by describe."""
        entries = []
        for directory, subdirectories, files in os.walk(self.root):
            entries += [describe(Path(directory) / name) for name in subdirectories + files]
        return sorted(entries)

    def initialise(self, directory: Path | None = None, tool: Path = TOOL, verb: str = "initialise",
                   *flags: str) -> None:
        """Initialise DIRECTORY (src) with FLAGS; small segments keep borg's free space check under 30 MB."""
        self.run_ok(verb, *flags, cwd=directory or self.source, tool=tool)
        self.borg("config", str(self.repository(directory)), "max_segment_size", "1048576")

    def populate(self) -> None:
        """Initialise src and src/inner, and create from src/inner, which creates in src too."""
        self.initialise()
        self.initialise(self.source / "inner")
        self.run_ok("create", cwd=self.source / "inner")

    def config_value(self, name: str, directory: Path | None = None) -> str:
        """NAME as the configuration of DIRECTORY (src) sets it, read the way the tool reads it."""
        script = f'source {CONFIG} && printf %s "${name}"'
        return subprocess.run(["bash", "-c", script], cwd=directory or self.source,
                              capture_output=True, text=True, check=True).stdout

    def repository(self, directory: Path | None = None) -> Path:
        """The Borg repository of DIRECTORY (src)."""
        return Path(self.config_value("BORG_REPO", directory))

    def fake_archive(self, moment: datetime, number: int) -> str:
        """An archive of src/plain in the repository of src, dated MOMENT by borg
        itself and named with NUMBER as archivectl names one."""
        name = f"{number}_{moment.strftime('%Y-%m-%d_%H%M%S')}"
        self.borg("create", "--timestamp", moment.strftime("%Y-%m-%dT%H:%M:%S"),
                  f"{self.repository()}::{name}", ".", cwd=self.source / "plain")
        return name


@pytest.fixture
def sandbox() -> Iterator[Sandbox]:
    with Sandbox() as box:
        yield box


@pytest.fixture(scope="module")
def populated() -> Iterator[Sandbox]:
    """One populated sandbox for the tests that must leave it unchanged."""
    with Sandbox() as box:
        box.populate()
        yield box


def options_table() -> dict[str, list[tuple[str, bool]]]:
    """Every command's options as the source parses them, from gen-docs.py --options."""
    output = subprocess.run(["python3", str(ROOT / "scripts" / "gen-docs.py"), "--options", TOOL.name],
                            capture_output=True, text=True, check=True).stdout
    table: dict[str, list[tuple[str, bool]]] = {}
    for line in output.splitlines():
        command, _, spellings = line.partition("\t")
        table[command] = [(word.rsplit(":", 1)[0], word.endswith(":value")) for word in spellings.split()]
    return table
