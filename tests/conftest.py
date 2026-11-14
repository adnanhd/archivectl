"""Sandboxes for the archivectl tests: every run gets its own HOME, state,
backup root, Borg base directory and source tree under $TMPDIR."""
from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import tempfile
import time
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from types import TracebackType

import pytest
from hypothesis import HealthCheck, settings

ROOT = Path(__file__).resolve().parent.parent
TOOL = ROOT / "archivectl"
CONFIG = ".borgbackup"
CONFIGS = (".myrsyncbackup", ".borgbackup")
NAME_FORMAT = "%Y-%m-%d_%H:%M:%S"

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
    """Type, mode and content hash or link target of PATH, no times."""
    status = path.lstat()
    if path.is_symlink():
        return (str(path), "link", os.readlink(path))
    if path.is_dir():
        return (str(path), "dir", oct(status.st_mode))
    return (str(path), "file", oct(status.st_mode), hashlib.sha256(path.read_bytes()).hexdigest())


class Sandbox:
    """home/ (HOME and XDG dirs), backups/ (the backup root), borg/ (Borg's
    own cache and security files) and src/, the source, with src/plain a
    plain directory and src/inner a nested source."""

    def __init__(self) -> None:
        self.root = Path(tempfile.mkdtemp(prefix=f"{TOOL.name}-test."))
        refuse_inside_repository(self.root)
        self.home = self.root / "home"
        self.backups = self.root / "backups"
        self.source = self.root / "src"
        for directory in (self.home, self.backups, self.root / "borg", self.root / "tmp",
                          self.source / "plain", self.source / "inner" / "sub", self.source / "fresh"):
            directory.mkdir(parents=True)
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
                   BORG_PASSPHRASE="throwaway", BORG_DISPLAY_PASSPHRASE="no", TZ="UTC")
        return env

    def __enter__(self) -> Sandbox:
        return self

    def __exit__(self, kind: type[BaseException] | None, error: BaseException | None,
                 trace: TracebackType | None) -> None:
        subprocess.run(["chmod", "-R", "u+w", str(self.root)], check=False)
        shutil.rmtree(self.root)

    def run(self, *args: str, cwd: Path | None = None, stdin: str = "") -> Result:
        completed = subprocess.run([str(TOOL), *args], cwd=cwd or self.source, input=stdin,
                                   capture_output=True, text=True, env=self.env, timeout=300)
        return Result(completed.returncode, completed.stdout, completed.stderr)

    def run_ok(self, *args: str, cwd: Path | None = None, stdin: str = "") -> Result:
        result = self.run(*args, cwd=cwd, stdin=stdin)
        assert result.returncode == 0, f"{args}: {result.stderr}"
        return result

    def borg(self, *args: str, cwd: Path | None = None) -> None:
        subprocess.run(["borg", *args], cwd=cwd or self.source, env=self.env, check=True,
                       capture_output=True, timeout=300)

    def state(self) -> list[tuple[str, ...]]:
        """Every path under home/, backups/ and src/, described without times."""
        entries = []
        for top in (self.home, self.backups, self.source):
            for directory, subdirectories, files in os.walk(top):
                entries += [describe(Path(directory) / name) for name in subdirectories + files]
        return sorted(entries)

    def initialise(self, directory: Path | None = None) -> None:
        """Initialise DIRECTORY (src); small segments keep borg's free space check under 30 MB."""
        self.run_ok("initialise", cwd=directory or self.source)
        self.borg("config", str(self.repository(directory)), "max_segment_size", "1048576")

    def populate(self) -> None:
        """Initialise src and src/inner, and create from src/inner, which creates in src too."""
        self.initialise()
        self.initialise(self.source / "inner")
        self.run_ok("create", cwd=self.source / "inner")

    def repository(self, directory: Path | None = None) -> Path:
        """The Borg repository of DIRECTORY (src)."""
        text = ((directory or self.source) / CONFIG).read_text()
        line = next(line for line in text.splitlines() if line.startswith("BORG_REPO="))
        return Path(line.split("=", 1)[1].strip('"'))

    def fake_archive(self, moment: datetime) -> str:
        """An archive of src/plain in the repository of src, dated MOMENT by borg itself."""
        name = moment.strftime(NAME_FORMAT)
        self.borg("create", "--timestamp", moment.strftime("%Y-%m-%dT%H:%M:%S"),
                  f"{self.repository()}::{name}", ".", cwd=self.source / "plain")
        return name


def wait_for_a_new_second(taken: set[str]) -> None:
    """Names have one-second resolution: wait until a create would not hit one in TAKEN."""
    while datetime.now(timezone.utc).strftime(NAME_FORMAT) in taken:
        time.sleep(0.05)


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
