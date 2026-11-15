# archivectl

Numbered, encrypted, deduplicated archives of a directory with [BorgBackup](https://www.borgbackup.org/), on this host or on another one, the passphrase kept in [pass](https://www.passwordstore.org/).

## Install

```bash
git clone --recurse-submodules git@github.com:adnanhd/archivectl.git
cd archivectl
make install        # into ~/.local; PREFIX=/usr DESTDIR=pkg for a package
make test           # pytest and Hypothesis, in scratch directories
```

`make install` puts the command, its modules, bash, fish and zsh completions and the manual pages under `PREFIX`; `make list-old` names what the old dedupctl install left.

## Examples

```bash
archivectl init && archivectl create                  # back up the current directory
archivectl status                                     # where it goes, how many, how big
archivectl restore --to /tmp/old 4 notes.txt          # one file from archive 4
archivectl list --older 30 | archivectl delete -n     # what would go; drop -n to delete
BORG_RSH='ssh -i ~/.ssh/borgbase_ed25519' archivectl init --repo ssh://xxxx@xxxx.repo.borgbase.com/./repo
```

`archivectl --help` fits one screen, `archivectl <command> --help` covers one command, and `man archivectl` and `man 5 archivectl.borgbackup` cover the rest.

## License

MIT.
