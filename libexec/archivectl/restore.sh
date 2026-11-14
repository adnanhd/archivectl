# archivectl restore: extract an archive, or paths in it, or mount it

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
            -h|--help) usage 0 ;;
            -*) die "restore: unknown option '$1'" $EXIT_INVALID_ARGS ;;
            *)
                path="${1#/}"
                if [ -z "$name" ]; then name="$1"; else paths+=("${path#./}"); fi
                ;;
        esac
        shift
    done
    [ -n "$name" ] || die "restore needs an archive name." $EXIT_INVALID_ARGS
    [ -z "$target" ] || [ -z "$mount" ] || die "--to and --mount exclude each other." $EXIT_INVALID_ARGS
    enter_repo SOURCE_DIR BORG_REPO
    if [ -n "$mount" ]; then
        mount_archive "$name" "$mount" "${paths[@]}"
    else
        extract_archive "$name" "${target:-$(realpath -m -- "$SOURCE_DIR")}" "${paths[@]}"
    fi
}

# extract_archive NAME DIR [PATH...]: extract archive NAME, or PATHs in it, into DIR
extract_archive() {
    local name="$1" target="$2"
    shift 2
    if [ "$DRY_RUN" = true ]; then
        say "would restore archive $name into $target"
        borg extract --dry-run --list "$BORG_REPO::$name" "$@" >&2
        return 0
    fi
    open_log
    mkdir -p "$target"
    ( cd "$target" && borg extract "$BORG_REPO::$name" "$@" ) 2>&1 | tee -a "$LOG_FILE" >&2
    say "restored archive $name into $target"
}

# mount_archive NAME DIR [PATH...]: mount archive NAME, or PATHs in it, at DIR
mount_archive() {
    local name="$1" mount="$2"
    shift 2
    require_known "$name" < <(archive_dates | cut -f1)
    if [ "$DRY_RUN" = true ]; then
        say "would mount archive $name at $mount"
        return 0
    fi
    open_log
    mkdir -p "$mount"
    borg mount "$BORG_REPO::$name" "$mount" "$@"
    say "mounted archive $name at $mount; unmount it with borg umount $mount"
}
