# bash completion for archivectl: commands, options, directories where one
# is wanted, the archive numbers list prints, and the paths in an archive
# after its number; borg runs only when it needs no passphrase typed

# Run with bash -c in DIR [ID PREFIX]: the records of archivectl list for the
# source of DIR, or the items of archive ID below PREFIX, "type path"; only
# when the passphrase is in the environment or .archivectl sets
# BORG_PASSCOMMAND, and with gpg kept from asking for its own
_archivectl_borg='dir=$(realpath -- "$1") || exit 1
until [ -f "$dir/.archivectl" ]; do [ "$dir" != / ] || exit 1; dir=$(dirname "$dir"); done
cd "$dir" && source ./.archivectl >/dev/null 2>&1 || exit 1
[ -n "${BORG_PASSPHRASE:-}${BORG_PASSCOMMAND:-}" ] || exit 1
export BORG_PASSCOMMAND BORG_RSH BORG_RELOCATED_REPO_ACCESS_IS_OK=no BORG_UNKNOWN_UNENCRYPTED_REPO_ACCESS_IS_OK=no
export PASSWORD_STORE_GPG_OPTS="${PASSWORD_STORE_GPG_OPTS:-} --pinentry-mode=error"
[ $# -gt 1 ] || exec archivectl list
name=$(borg list --short --glob-archives "${2}_*" "$BORG_REPO" | head -n 1)
exec borg list --format "{type} {path}{NL}" "$BORG_REPO::${name:-$2}" "sh:$3*"'

# _archivectl_dirs: the directories that begin with cur
_archivectl_dirs() {
    mapfile -t COMPREPLY < <(compgen -d -- "$cur")
    compopt -o filenames 2>/dev/null
}

# _archivectl_ids DIR: the archive numbers that begin with cur, of the source of DIR
_archivectl_ids() {
    mapfile -t COMPREPLY < <(compgen -W "$(bash -c "$_archivectl_borg" _ "$1" </dev/null 2>/dev/null | cut -f1)" -- "$cur")
}

# _archivectl_paths DIR ID: the paths in archive ID one level below cur's
# directory, a directory with / after it
_archivectl_paths() {
    local prefix="" path kind
    [[ $cur == */* ]] && prefix=${cur%/*}/
    while IFS= read -r path; do
        kind=${path%% *}
        path=${path#? }
        # borg lists all below a directory that matches, and . for the root
        [[ $path == . || ${path#"$prefix"} == */* ]] && continue
        [ "$kind" = d ] && path+=/
        [[ $path == "$cur"* ]] && COMPREPLY+=("$path")
    done < <(bash -c "$_archivectl_borg" _ "$1" "$2" "$prefix" </dev/null 2>/dev/null)
    compopt -o nospace 2>/dev/null
}

_archivectl() {
    local line=${COMP_LINE:0:COMP_POINT} cur previous word cmd="" value="" cdir=. opts=""
    local subcommands="init initialise create status list delete restore diff check export-key change-passphrase"
    local -a words operands=()
    COMPREPLY=()
    read -ra words <<<"$line"
    [[ $line == *[[:space:]] || ${#words[@]} -eq 1 ]] && words+=("")
    cur=${words[-1]}
    previous=${words[-2]}
    # the directory -C names, the command, then the operands before cur, option values left out
    for word in "${words[@]:1:${#words[@]}-2}"; do
        if [ -n "$value" ]; then
            [ "$value" = C ] && cdir=${word/#\~/$HOME}
            value=""
            continue
        fi
        case $word in
            -C) if [ -z "$cmd" ]; then value=C; fi ;;
            --to|--mount|--scratch|--repo|--older|--newer|--first|--last|-m|--message) value=1 ;;
            -*) ;;
            *) if [ -z "$cmd" ]; then cmd=$word; else operands+=("$word"); fi ;;
        esac
    done
    if [ -z "$cmd" ]; then
        if [ "$previous" = -C ]; then
            _archivectl_dirs
        else
            mapfile -t COMPREPLY < <(compgen -W "$subcommands -C -h --help" -- "$cur")
        fi
        return
    fi
    case $cmd in
        init|initialise) opts="-n --dry-run --repo --no-pass --store-passphrase -h --help" ;;
        create) opts="-n --dry-run -m --message --stats -h --help" ;;
        status) opts="-h --help" ;;
        list) opts="--human-readable --older --newer --first --last -h --help" ;;
        delete) opts="-n --dry-run -h --help" ;;
        restore) opts="-n --dry-run --to --mount -h --help" ;;
        diff) opts="--scratch -h --help" ;;
        check) opts="-h --help" ;;
        export-key) opts="--paper -h --help" ;;
        change-passphrase) opts="-n --dry-run -h --help" ;;
    esac
    case $previous in
        --to|--mount|--scratch) _archivectl_dirs; return ;;
        --repo|--older|--newer|--first|--last|-m|--message) return ;;
    esac
    if [[ $cur == -* ]]; then
        mapfile -t COMPREPLY < <(compgen -W "$opts" -- "$cur")
        return
    fi
    case $cmd in
        init|initialise) [ ${#operands[@]} -gt 0 ] || _archivectl_dirs ;;
        delete) _archivectl_ids "$cdir" ;;
        diff) [ ${#operands[@]} -ge 2 ] || _archivectl_ids "$cdir" ;;
        restore)
            if [ ${#operands[@]} -eq 0 ]; then
                _archivectl_ids "$cdir"
            else
                _archivectl_paths "$cdir" "${operands[0]}"
            fi
            ;;
    esac
}

complete -F _archivectl archivectl
