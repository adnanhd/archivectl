# fish completion for archivectl: commands, options, directories where one
# is wanted, the archive numbers list prints with their dates, and the paths
# in an archive after its number; borg runs only when it needs no
# passphrase typed

function __archivectl_args --argument-names want --description 'dir: the directory -C names; operands: the words after the command, options and their values left out'
    set -l words (commandline -opc)
    set -e words[1]
    set -l dir .
    set -l command ""
    set -l skip ""
    for word in $words
        if test -n "$skip"
            test $skip = C; and set dir (string replace -r '^~' -- $HOME $word)
            set skip ""
            continue
        end
        switch $word
            case -C
                test -z "$command"; and set skip C
            case --to --mount --scratch --repo --older --newer --first --last
                set skip value
            case '-*'
            case '*'
                if test -z "$command"
                    set command $word
                else if test $want = operands
                    echo $word
                end
        end
    end
    test $want = dir; and echo $dir
end

# in DIR [ID PREFIX]: the records of archivectl list for the source of DIR,
# or the items of archive ID below PREFIX, "type path"; only when the
# passphrase is in the environment or .archivectl sets BORG_PASSCOMMAND, and
# with gpg kept from asking for its own
set -g __archivectl_borg 'dir=$(realpath -- "$1") || exit 1
until [ -f "$dir/.archivectl" ]; do [ "$dir" != / ] || exit 1; dir=$(dirname "$dir"); done
cd "$dir" && source ./.archivectl >/dev/null 2>&1 || exit 1
[ -n "${BORG_PASSPHRASE:-}${BORG_PASSCOMMAND:-}" ] || exit 1
export BORG_PASSCOMMAND BORG_RSH BORG_RELOCATED_REPO_ACCESS_IS_OK=no BORG_UNKNOWN_UNENCRYPTED_REPO_ACCESS_IS_OK=no
export PASSWORD_STORE_GPG_OPTS="${PASSWORD_STORE_GPG_OPTS:-} --pinentry-mode=error"
[ $# -gt 1 ] || exec archivectl list
name=$(borg list --short --glob-archives "${2}_*" "$BORG_REPO" | head -n 1)
exec borg list --format "{type} {path}{NL}" "$BORG_REPO::${name:-$2}" "sh:$3*"'

function __archivectl_ids --description 'the archive numbers archivectl list prints, with their dates'
    bash -c $__archivectl_borg _ (__archivectl_args dir) </dev/null 2>/dev/null | cut -f1,2
end

function __archivectl_paths --description 'the paths in the archive one level below the current token'
    set -l cur (commandline -ct)
    set -l prefix (string match -r '.*/' -- $cur)
    for item in (bash -c $__archivectl_borg _ (__archivectl_args dir) (__archivectl_args operands)[1] "$prefix" </dev/null 2>/dev/null)
        set -l kind (string sub -l 1 -- $item)
        set -l path (string sub -s 3 -- $item)
        # borg lists all below a directory that matches, and . for the root
        test "$path" = .; and continue
        string match -q -- '*/*' (string sub -s (math (string length -- "$prefix") + 1) -- $path); and continue
        test $kind = d; and set path $path/
        string match -q -- "$cur*" $path; and echo $path
    end
end

function __archivectl_operands_fewer_than --argument-names n --description 'whether the command has fewer than N operands before the current token'
    test (count (__archivectl_args operands)) -lt $n
end

complete -c archivectl -f
complete -c archivectl -n 'not __fish_seen_subcommand_from init create status list delete restore diff check export-key change-passphrase initialise' -a init -d 'make a directory a backup source'
complete -c archivectl -n 'not __fish_seen_subcommand_from init create status list delete restore diff check export-key change-passphrase initialise' -a create -d 'archive the source into a new archive'
complete -c archivectl -n 'not __fish_seen_subcommand_from init create status list delete restore diff check export-key change-passphrase initialise' -a status -d 'print the source and its repository'
complete -c archivectl -n 'not __fish_seen_subcommand_from init create status list delete restore diff check export-key change-passphrase initialise' -a list -d 'print each archive: number, date, size'
complete -c archivectl -n 'not __fish_seen_subcommand_from init create status list delete restore diff check export-key change-passphrase initialise' -a delete -d 'delete the archives named or piped in'
complete -c archivectl -n 'not __fish_seen_subcommand_from init create status list delete restore diff check export-key change-passphrase initialise' -a restore -d 'extract an archive, or paths in it'
complete -c archivectl -n 'not __fish_seen_subcommand_from init create status list delete restore diff check export-key change-passphrase initialise' -a diff -d 'print the paths that differ'
complete -c archivectl -n 'not __fish_seen_subcommand_from init create status list delete restore diff check export-key change-passphrase initialise' -a check -d 'check the repository with borg check'
complete -c archivectl -n 'not __fish_seen_subcommand_from init create status list delete restore diff check export-key change-passphrase initialise' -a export-key -d 'print the key of the repository'
complete -c archivectl -n 'not __fish_seen_subcommand_from init create status list delete restore diff check export-key change-passphrase initialise' -a change-passphrase -d 'give the repository a new passphrase'
complete -c archivectl -n 'not __fish_seen_subcommand_from init create status list delete restore diff check export-key change-passphrase initialise' -a initialise -d 'same as init'
complete -c archivectl -n 'not __fish_seen_subcommand_from init create status list delete restore diff check export-key change-passphrase initialise' -s C -x -a '(__fish_complete_directories (commandline -ct))' -d 'run in <dir>'
complete -c archivectl -s h -l help -d 'this help'
complete -c archivectl -n '__fish_seen_subcommand_from init initialise' -s n -l dry-run -d 'Report what would be written and write nothing.'
complete -c archivectl -n '__fish_seen_subcommand_from init initialise' -l repo -x -d 'Use the repository at <url>.'
complete -c archivectl -n '__fish_seen_subcommand_from init initialise' -l no-pass -d 'Keep the passphrase out of pass.'
complete -c archivectl -n '__fish_seen_subcommand_from init initialise' -l store-passphrase -d 'Keep the passphrase of an initialised source in pass.'
complete -c archivectl -n '__fish_seen_subcommand_from create' -s n -l dry-run -d 'Report what would be renamed and archived and write nothing.'
complete -c archivectl -n '__fish_seen_subcommand_from create' -s m -l message -x -d 'Keep <text> with the archive as its comment.'
complete -c archivectl -n '__fish_seen_subcommand_from create' -l stats -d 'Also print the statistics borg gives.'
complete -c archivectl -n '__fish_seen_subcommand_from list' -l human-readable -d 'Sizes in K, M, G, T instead of bytes.'
complete -c archivectl -n '__fish_seen_subcommand_from list' -l older -x -d 'Only the archives older than N days.'
complete -c archivectl -n '__fish_seen_subcommand_from list' -l newer -x -d 'Only the archives newer than N days.'
complete -c archivectl -n '__fish_seen_subcommand_from list' -l first -x -d 'Then only the oldest N of those.'
complete -c archivectl -n '__fish_seen_subcommand_from list' -l last -x -d 'Then only the newest N of those.'
complete -c archivectl -n '__fish_seen_subcommand_from delete' -s n -l dry-run -d 'Report what would be renamed and deleted and change nothing.'
complete -c archivectl -n '__fish_seen_subcommand_from restore' -s n -l dry-run -d 'Report what would be extracted or mounted and write nothing.'
complete -c archivectl -n '__fish_seen_subcommand_from restore' -l to -x -a '(__fish_complete_directories (commandline -ct))' -d 'Extract into <dir> instead.'
complete -c archivectl -n '__fish_seen_subcommand_from restore' -l mount -x -a '(__fish_complete_directories (commandline -ct))' -d 'Mount the archive at <dir> instead.'
complete -c archivectl -n '__fish_seen_subcommand_from export-key' -l paper -d 'The form for typing the key back by hand.'
complete -c archivectl -n '__fish_seen_subcommand_from change-passphrase' -s n -l dry-run -d 'Report what would change and change nothing.'
complete -c archivectl -n '__fish_seen_subcommand_from diff' -l scratch -x -a '(__fish_complete_directories (commandline -ct))' -d 'Extract the archive under <dir> to compare it with the live source.'
complete -c archivectl -n '__fish_seen_subcommand_from init initialise; and __archivectl_operands_fewer_than 1' -a '(__fish_complete_directories (commandline -ct))'
complete -c archivectl -n '__fish_seen_subcommand_from delete' -a '(__archivectl_ids)'
complete -c archivectl -n '__fish_seen_subcommand_from diff; and __archivectl_operands_fewer_than 2' -a '(__archivectl_ids)'
complete -c archivectl -n '__fish_seen_subcommand_from restore; and __archivectl_operands_fewer_than 1' -a '(__archivectl_ids)'
complete -c archivectl -n '__fish_seen_subcommand_from restore; and not __archivectl_operands_fewer_than 1' -a '(__archivectl_paths)'
