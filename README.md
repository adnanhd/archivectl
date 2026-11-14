# archivectl

Encrypted, compressed, deduplicated archives of a directory tree with [BorgBackup](https://www.borgbackup.org/), one Borg repository per backed-up directory.

## Commands

| Command | Does |
|---------|------|
| `init [-n] [--repo <url>] [--no-pass] [<path>]` | Make a directory a backup source: write its `.borgbackup`, initialise its repository (repokey), here or on another host, and keep its passphrase in pass. `initialise` is an alias. |
| `init [-n] --store-passphrase [<path>]` | Keep the passphrase of a source initialised before in pass, and have its `.borgbackup` read it from there. |
| `create [-n] [--stats]` | Archive the source into a new archive (lz4) and print its record. |
| `status` | Print one record of the source here: source, repository, number of archives, number and date of the newest, size of the repository. |
| `list [--older N] [--newer N] [--first N] [--last N]` | Print one record per archive, oldest first: `number<TAB>date<TAB>size`. |
| `delete [-n] [<id>...]` | Delete the archives named as arguments, or else those whose ids begin the lines on standard input. |
| `restore [-n] [--to <dir> \| --mount <dir>] <id> [<path>...]` | Extract an archive, or paths in it, into the source or `<dir>`, or mount it. |
| `diff [--scratch <dir>] <id> [<id2>]` | Print one record per changed path, `path<TAB>added\|removed\|modified`, from `<id>` to `<id2>`, or to the live source after extracting `<id>` under `<dir>`. |
| `check` | Check the repository with `borg check`. |

`archivectl -C <dir> <command>` runs as if started in `<dir>`. `archivectl` alone prints `status` and the help, one screen; `archivectl <command> --help` prints the help of one command.

An archive's id is its number: 1, 2, 3 and so on per repository, never given twice, also after a delete; the last one given is kept in `${XDG_STATE_HOME:-~/.local/state}/archivectl/<repository>.sequence`. It is part of the archive's name, `<N>_<YYYY-MM-DD_HHMMSS>`, and a command takes that full name too. Archives named otherwise, as earlier versions named them, get numbers in time order the first time `create` or `delete` runs, which renames them with `borg rename` and says so; with `-n` they only report it.

Selecting and acting are separate: `list` prints records, `delete` reads them, or takes numbers as arguments.

```bash
archivectl init && archivectl create
archivectl list --older 30 | archivectl delete -n   # what would go
archivectl list --older 30 | archivectl delete
archivectl delete 4
archivectl restore --to /tmp/old "$(archivectl list --last 1 | cut -f1)" notes.txt
```

Standard output carries records only, one per line, tab-separated, id first; messages, summaries and borg's own output go to standard error, and an empty answer prints nothing. Every command that writes takes `-n`, which reports what it would do and writes nothing. A write's log goes to `${XDG_STATE_HOME:-~/.local/state}/archivectl/<repository>.log`. `delete` does not run `borg compact`, which frees the space.

`create` prints its record and one line on standard error; `--stats` adds borg's statistics. It keeps an archive borg finished with warnings (status 1 or 100 to 127): borg names the files it could not read (`E`) or that changed while it read them (`C`) on standard error, `create` logs them and ends with status 0. A failed create deletes only an archive its own borg committed.

## The passphrase

`init` reads the passphrase of a new repository once, or takes `BORG_PASSPHRASE`, keeps it in [pass](https://www.passwordstore.org/) as `archivectl/<name>`, and writes `BORG_PASSCOMMAND="pass show archivectl/<name>"` into `.borgbackup`; every command exports it for its borg calls, so gpg-agent answers and nothing is typed. `init --no-pass`, or no pass installed, leaves it out. For a source initialised before, `archivectl init --store-passphrase` reads the passphrase once, checks it with borg, keeps it in pass and adds the line. With neither `BORG_PASSPHRASE` nor `BORG_PASSCOMMAND`, a command on an encrypted repository reads the passphrase once from the terminal and hands it to its borg calls in their environment only, never writing it anywhere.

## Remote repositories

`init --repo <url>` uses the repository as given: `ssh://user@host[:port]/path`, scp-style `user@host:path`, or a local path. Without `--repo`, a `BORG_BACKUP_ROOT` that is such a URL means `<root>/<name>` on that host. borg itself checks whether the repository exists (`borg info`), and `init` initialises it (`borg init --make-parent-dirs`) or uses the one there. borg reaches the host with ssh, or with `BORG_RSH` from the environment or `.borgbackup`. For BorgBase:

```bash
export BORG_RSH='ssh -i ~/.ssh/borgbase_ed25519'
archivectl init --repo ssh://xxxx@xxxx.repo.borgbase.com/./repo
archivectl create
```

archivectl asks for nothing beyond what borg and ssh ask.

A path in a record writes a backslash, tab or newline as `\\`, `\t` or `\n`.

`man archivectl` documents every command and option, and `man 5 archivectl.borgbackup` the configuration file.

## Configuration

`.borgbackup` in the backed-up directory, written by `init`:

```bash
SOURCE_DIR="./"
BORG_REPO="/path/to/borg/repository"
BORG_PASSCOMMAND="pass show archivectl/<name>"
# Optional: EXCLUDES=(".cache" "node_modules" "*.log")
```

Without `EXCLUDES`, `.cache`, `tmp` and `__pycache__` are left out. `init` puts the repository under `BORG_BACKUP_ROOT`: by default `/data/backup/borg` when `/data` is a mount point, else `~/.borg_backups`. The repository is named after the source's path, the leading `/` dropped and every other `/` written `__`: `/home/adhd/test` is kept in `home__adhd__test`. `%`, a newline, an `_` at either end of a part of the path or next to another `_`, and a `!` that begins the name are written `%25`, `%0A`, `%5F` and `%21`, so that no two sources share a name; a name over 199 bytes is cut to 135 bytes, `~` and the SHA-256 of the path. A repository under the name earlier versions gave, the path with `/` written `%2F`, is found and used where it is.

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

The section-1 page is generated from the source by `scripts/gen-docs.py`, which reads the dispatcher, `libexec/` and `lib/` and never runs the tool; rerun it after changing a command or an option. The prose of the page is in `man/archivectl.1.in`; the section-5 page is written by hand. The bash, fish and zsh completions are written by hand: they complete commands and options, directories only after `init`, `-C`, `--to`, `--mount` and `--scratch`, nothing after an option that takes a number or a URL and none after a command that takes no argument, the numbers `archivectl list` prints after `restore`, `diff` and `delete`, with their dates in fish and zsh, and after `restore`'s number the paths in that archive. They run borg only when `BORG_PASSPHRASE` is set or `BORG_PASSCOMMAND` is, in the environment or in `.borgbackup`, keep gpg from asking (`--pinentry-mode=error`) and never let borg ask anything; otherwise they offer no numbers and no paths. `scripts/gen-docs.py --check` checks the bash and fish ones against the code.

## Tests

```bash
make test
```

runs the pytest and Hypothesis suite in `tests/` against borg: every run gets a scratch HOME, state directory, Borg base directory, backup root and source tree under `$TMPDIR`. It checks that `delete` reads back unchanged what `list` prints, that `-n` writes nothing for every write command and option, that `delete` with no input does nothing, and that `list` prints records only. It takes about three minutes.

## License

This project is licensed under the MIT License.
