# archivectl

Encrypted, compressed, deduplicated archives of a directory tree with [BorgBackup](https://www.borgbackup.org/), one Borg repository per backed-up directory.

## Commands

| Command | Does |
|---------|------|
| `initialise [-n] [<path>]` | Make a directory a backup source: write its `.borgbackup`, initialise its repository (repokey). `init` is an alias. |
| `create [-n]` | Archive the source into a new archive (lz4) and print its record. |
| `list [--older N] [--newer N] [--first N] [--last N]` | Print one record per archive, oldest first: `name<TAB>date<TAB>size`. |
| `delete [-n]` | Delete the archives whose names begin the lines on standard input. |
| `restore [-n] [--to <dir> \| --mount <dir>] <name> [<path>...]` | Extract an archive, or paths in it, into the source or `<dir>`, or mount it. |
| `diff [--scratch <dir>] <name> [<name2>]` | Print one record per changed path, `path<TAB>added\|removed\|modified`, from `<name>` to `<name2>`, or to the live source after extracting `<name>` under `<dir>`. |
| `check` | Check the repository with `borg check`. |

Selecting and acting are separate: `list` prints records, `delete` reads them.

```bash
archivectl list --older 30 | archivectl delete -n   # what would go
archivectl list --older 30 | archivectl delete
archivectl restore --to /tmp/old "$(archivectl list --last 1 | cut -f1)" notes.txt
```

Standard output carries records only, one per line, tab-separated, name first; messages, summaries and borg's own output go to standard error, and an empty answer prints nothing. Every command that writes takes `-n`, which reports what it would do and writes nothing. A write's log goes to `${XDG_STATE_HOME:-~/.local/state}/archivectl/<repository>.log`. `delete` does not run `borg compact`, which frees the space.

A path in a record writes a backslash, tab or newline as `\\`, `\t` or `\n`.

`man archivectl` documents every command and option, and `man 5 archivectl.borgbackup` the configuration file.

## Configuration

`.borgbackup` in the backed-up directory, written by `initialise`:

```bash
SOURCE_DIR="./"
BORG_REPO="/path/to/borg/repository"
# Optional: EXCLUDES=(".cache" "node_modules" "*.log")
```

Without `EXCLUDES`, `.cache`, `tmp` and `__pycache__` are left out. `initialise` puts the repository under `BORG_BACKUP_ROOT` (default `~/.borg_backups`); borg reads its passphrase from `BORG_PASSPHRASE` or `BORG_PASSCOMMAND`.

## Installation

```bash
git clone --recurse-submodules git@github.com:adnanhd/archivectl.git
cd archivectl
make install                  # PREFIX=~/.local by default
make PREFIX=/usr DESTDIR=pkg install
make uninstall
make list-old                 # the files the old dedupctl install left, one per line
make uninstall-old            # remove them
```

| Component | Installed to |
|-----------|--------------|
| `archivectl` | `PREFIX/bin/` |
| command modules and `lib/common.sh` | `PREFIX/lib/archivectl/` |
| completions | `PREFIX/share/bash-completion/completions/`, `PREFIX/share/fish/vendor_completions.d/`, `PREFIX/share/zsh/site-functions/` |
| manual pages | `PREFIX/share/man/man1/`, `PREFIX/share/man/man5/` |

`make install` writes `LIBDIR` into the installed script, so `BINDIR` and `LIBDIR` can be set apart; a copy that `make install` did not write finds its modules in the source tree (`libexec/archivectl/`, `lib/`) or under `PREFIX/lib/archivectl/`. `lib/` is the submodule [backuplib](https://github.com/adnanhd/backuplib). `diff` against the live source also needs rsync.

The section-1 page and the three completions are generated from the source by `scripts/gen-docs.py`, which reads the dispatcher, `libexec/` and `lib/` and never runs the tool; rerun it after changing a command or an option. The prose of the page is in `man/archivectl.1.in`; the section-5 page is written by hand.

## Tests

```bash
make test
```

runs the pytest and Hypothesis suite in `tests/` against borg: every run gets a scratch HOME, state directory, Borg base directory, backup root and source tree under `$TMPDIR`. It checks that `delete` reads back unchanged what `list` prints, that `-n` writes nothing for every write command and option, that `delete` with no input does nothing, and that `list` prints records only. It takes about three minutes.

## License

This project is licensed under the MIT License.
