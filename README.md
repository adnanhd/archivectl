# archivectl

Numbered, encrypted, deduplicated archives of a directory with [BorgBackup](https://www.borgbackup.org/), on this host or on another one over ssh, the passphrase kept in [pass](https://www.passwordstore.org/). The shared shell code is the `lib` submodule, [backuplib](https://github.com/adnanhd/backuplib).

## Install

```bash
git clone --recurse-submodules git@github.com:adnanhd/archivectl.git
cd archivectl
make install        # into ~/.local; PREFIX=/usr DESTDIR=pkg for a package
make test           # pytest and Hypothesis, in scratch directories
```

`make install` puts the command in `PREFIX/bin`, its modules and `lib/common.sh` in `PREFIX/lib/archivectl`, the bash, fish and zsh completions under `PREFIX/share` and the manual pages `archivectl(1)` and `archivectl(5)`. Run from the checkout, `archivectl` uses `libexec/archivectl/` and `lib/` next to it.

## Commands

```
archivectl [-C <dir>] <command> [<options>]

init [-n] [--repo <url>] [--no-pass] [--store-passphrase] [<path>]
create [-n] [-m <text>] [--stats]
status
list [--human-readable] [--older N] [--newer N] [--first N] [--last N]
delete [-n] [<id>...]
restore [-n] [--to <dir> | --mount <dir>] <id> [<path>...]
diff [--scratch <dir>] <id> [<id2>]
check
export-key [--paper]
change-passphrase [-n]
```

`initialise` is an alias of `init`. An archive is named `N_YYYY-MM-DD_HHMMSS`; a number is never given out again after a delete, the last one kept in `~/.local/state/archivectl/<repository>.sequence`. `list` prints one tab-separated record per archive (number, date, size, files, the size deleting it frees, comment), and `delete` takes ids as arguments or reads them from stdin. `create` then also archives the nearest source in a parent directory. Without a command, `archivectl` prints the status of the source here and the help. `-n` reports and writes nothing.

## Configuration

`init` writes `.archivectl` into the source, a bash file the other commands source from the nearest directory at or above the current one: `SOURCE_DIR`, `BORG_REPO` (`$BORG_BACKUP_ROOT/<path as a name>`, or the `--repo` location), `BORG_PASSCOMMAND` (`pass show archivectl/<name>`) and, for a repository on another host, the `BORG_RSH` set at init. `BORG_BACKUP_ROOT` defaults to `/data/backup/borg` when `/data` is a mount point, else `~/.borg_backups`.

`.archivectlignore` beside it lists what `create` leaves out and `diff` does not compare, one gitignore-style pattern a line; without it `.cache`, `tmp` and `__pycache__` are left out. Logs go to `~/.local/state/archivectl/`.

## Examples

```bash
archivectl init && archivectl create                  # back up the current directory
archivectl status                                     # where it goes, how many, how big
archivectl restore --to /tmp/old 4 notes.txt          # one file from archive 4
archivectl list --older 30 | archivectl delete -n     # what would go; drop -n to delete
BORG_RSH='ssh -i ~/.ssh/borgbase_ed25519' archivectl init --repo ssh://xxxx@xxxx.repo.borgbase.com/./repo
```

`archivectl --help` fits one screen, `archivectl <command> --help` covers one command, and `man archivectl` and `man 5 archivectl` cover the rest. `scripts/gen-docs.py` writes `man/archivectl.1` from the source and `man/archivectl.1.in`; the completions and `man/archivectl.5` are written by hand.

## Tests

`make test` runs `python3 -m pytest tests`: every run gets its own `HOME`, state, backup root, Borg base directory and source tree under `$TMPDIR`, with a stub `pass` and, for remote repositories, a fake ssh. The tests check that `delete` reads back what `list` prints, that `-n` writes nothing, that stdout carries records only, that numbers are given once, and that the help and completions match the code.

## On this machine

The checkout is `~/src/personal/dedupctl`, installed with `make install` into `~/.local`. No systemd unit or timer runs it. `/data`, `~/.claude`, `~/Documents`, `~/.local/share/.tokens`, `~/org`, `~/.password-store`, `~/src` and `~/Zotero` are sources, each with its repository on cengaver at `ssh://cengaver-borg/mnt/data/adnan/backup/borg/<name>` (`cengaver-borg` is a host in `~/.ssh/config`).

## License

MIT.
