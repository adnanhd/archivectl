# archivectl create: archive the source into a new archive

run() {
    local name status=0 parent=0
    parse_dry_run create "$@"
    enter_repo SOURCE_DIR BORG_REPO
    name=$(date '+%Y-%m-%d_%H:%M:%S')
    build_exclude_params borg
    if [ "$DRY_RUN" = true ]; then
        say "would create archive $name of $REPO_ROOT"
        ( cd "$SOURCE_DIR" && BORG_EXIT_CODES=modern \
          borg create --dry-run --list "${EXCLUDE_PARAMS[@]}" "$BORG_REPO::$name" . ) >&2 || status=$?
    else
        open_log
        ( cd "$SOURCE_DIR" && BORG_EXIT_CODES=modern \
          borg create --stats --compression lz4 "${EXCLUDE_PARAMS[@]}" "$BORG_REPO::$name" . ) >&2 || status=$?
    fi
    # Modern borg exit codes: 100, 103 and 107 say only that files changed or
    # vanished while they were read; any other status leaves files out.
    case "$status" in
        100|103|107)
            say "files changed or vanished in $REPO_ROOT while archive $name was read"
            status=0
            ;;
    esac
    if [ "$status" -eq 0 ] && [ "$DRY_RUN" = false ]; then
        say "created archive $name of $REPO_ROOT"
        archive_dates | NAME="$name" awk -F '\t' '$1 == ENVIRON["NAME"]' | with_sizes
    elif [ "$status" -ne 0 ]; then
        say "archive $name of $REPO_ROOT is incomplete (borg status $status), so none is kept"
        drop_archive "$name"
    fi
    create_in_parent "$@" || parent=$?
    [ "$status" -eq 0 ] || return "$status"
    return "$parent"
}

# drop_archive NAME: delete archive NAME again if borg committed it
drop_archive() {
    [ "$DRY_RUN" = false ] || return 0
    if grep -qxF -e "$1" <<<"$(archive_dates | cut -f1)"; then
        borg delete "$BORG_REPO::$1" >&2 || say "could not delete the incomplete archive $1"
    fi
}
