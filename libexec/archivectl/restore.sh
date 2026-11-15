# archivectl restore: extract an archive, or paths in it, or mount it

show_help() {
    cat <<'HELP'
Usage:
  archivectl restore [-n] [--to <dir> | --mount <dir>] <id> [<path>...]

Extract archive <id>, or the given paths in it, into the source, but no
.archivectl file. A mount needs FUSE; borg umount <dir> unmounts it.

Options:
  -n, --dry-run  Report what would be done and write nothing.
  --to <dir>     Extract into <dir> instead.
  --mount <dir>  Mount the archive at <dir> instead.
HELP
    exit 0
}

run() {
    local name="" target="" mount="" DRY_RUN=false path
    local -a paths=()
    while [ $# -gt 0 ]; do
        case "$1" in
            -n|--dry-run) DRY_RUN=true ;;
            --to)
                [ $# -gt 1 ] || die "--to needs a directory." $EXIT_INVALID_ARGS
                target=$(realpath -m -- "$2")
                shift
                ;;
            --mount)
                [ $# -gt 1 ] || die "--mount needs a directory." $EXIT_INVALID_ARGS
                mount=$(realpath -m -- "$2")
                shift
                ;;
            -h|--help) show_help ;;
            -*) die "restore: unknown option '$1'" $EXIT_INVALID_ARGS ;;
            *)
                path="${1#/}"
                if [ -z "$name" ]; then name="$1"; else paths+=("${path#./}"); fi
                ;;
        esac
        shift
    done
    [ -n "$name" ] || die "restore needs an archive id." $EXIT_INVALID_ARGS
    [ -z "$target" ] || [ -z "$mount" ] || die "--to and --mount exclude each other." $EXIT_INVALID_ARGS
    enter_repository SOURCE_DIR BORG_REPO
    require_archive "$name"
    if [ -n "$mount" ]; then
        mount_archive "${NAMES[0]}" "$mount" "${paths[@]}"
    else
        extract_archive "${NAMES[0]}" "${target:-$(realpath -m -- "$SOURCE_DIR")}" "${paths[@]}"
    fi
}

# extract_archive NAME DIR [PATH...]: extract archive NAME, or PATHs in it,
# into DIR, leaving out every configuration and ignore file, so that a
# restore never turns the source back to the settings it had when NAME was made
extract_archive() {
    local name="$1" target="$2" config="re:(^|/)(${CONFIG//./\\.}|${IGNORE//./\\.})\$"
    shift 2
    if [ "$DRY_RUN" = true ]; then
        say "would restore archive ${NUMBERS[0]} into $target"
        borg extract --dry-run --list --exclude "$config" "$BORG_REPO::$name" "$@" >&2
        return 0
    fi
    open_log
    mkdir -p "$target"
    ( cd "$target" && borg extract --exclude "$config" "$BORG_REPO::$name" "$@" ) >&2
    say "restored archive ${NUMBERS[0]} into $target"
}

# mount_archive NAME DIR [PATH...]: mount archive NAME, or PATHs in it, at DIR
mount_archive() {
    local name="$1" mount="$2"
    shift 2
    if [ "$DRY_RUN" = true ]; then
        say "would mount archive ${NUMBERS[0]} at $mount"
        return 0
    fi
    open_log
    mkdir -p "$mount"
    borg mount "$BORG_REPO::$name" "$mount" "$@"
    say "mounted archive ${NUMBERS[0]} at $mount; unmount it with borg umount $mount"
}
