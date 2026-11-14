# archivectl create: archive the source into a new archive

run() {
    local name status=0 parent=0
    parse_dry_run create "$@"
    enter_repo SOURCE_DIR BORG_REPO
    name=$(date '+%Y-%m-%d_%H:%M:%S')
    require_free_name "$name"
    build_exclude_params borg
    if [ "$DRY_RUN" = true ]; then
        say "would create archive $name of $REPO_ROOT"
        ( cd "$SOURCE_DIR" && borg create --dry-run --list "${EXCLUDE_PARAMS[@]}" "$BORG_REPO::$name" . ) >&2 ||
            status=$?
    else
        open_log
        BORG_OUTPUT=$(umask 077 && mktemp)
        trap 'rm -f "$BORG_OUTPUT"' EXIT
        # --list --filter=CE names each file that changed while borg read it
        # (C) or that it could not read (E); the archive keeps the rest.
        ( cd "$SOURCE_DIR" && BORG_EXIT_CODES=modern borg create --stats --list --filter=CE \
            --compression lz4 "${EXCLUDE_PARAMS[@]}" "$BORG_REPO::$name" . ) 2>&1 |
            tee "$BORG_OUTPUT" >&2 || status=$?
    fi
    # Status 1 and 100 to 127 are borg's warnings: the archive is committed.
    if [ "$status" -eq 1 ] || { [ "$status" -ge 100 ] && [ "$status" -le 127 ]; }; then
        [ "$DRY_RUN" = true ] || log_skipped_files "$name" "$status"
        status=0
    fi
    if [ "$status" -eq 0 ] && [ "$DRY_RUN" = false ]; then
        say "created archive $name of $REPO_ROOT"
        archive_dates | NAME="$name" awk -F '\t' '$1 == ENVIRON["NAME"]' | with_sizes
    elif [ "$status" -ne 0 ]; then
        say "archive $name of $REPO_ROOT failed (borg status $status)"
        [ "$DRY_RUN" = true ] || drop_archive "$name"
    fi
    create_in_parent "$@" || parent=$?
    [ "$status" -eq 0 ] || return "$status"
    return "$parent"
}

# require_free_name NAME: die when the repository holds an archive NAME
require_free_name() {
    local known
    known=$(archive_dates | cut -f1)
    if LC_ALL=C grep -aqxF -e "$1" <<<"$known"; then
        die "archive $1 exists already."
    fi
}

# log_skipped_files NAME STATUS: log the files borg named with C or E
log_skipped_files() {
    local line
    say "archive $1 of $REPO_ROOT lacks or holds changed files borg named above (borg status $2)"
    while IFS= read -r line; do
        case "$line" in
            "C "*) say "${line#C } changed while borg read it" ;;
            "E "*) say "${line#E } could not be read" ;;
        esac
    done <"$BORG_OUTPUT"
}

# drop_archive NAME: delete archive NAME if this run's borg committed it, as
# the fingerprint borg printed shows; an archive made by another run stays
drop_archive() {
    local fingerprint known
    fingerprint=$(sed -n 's/^Archive fingerprint: \([0-9a-f]*\)$/\1/p' "$BORG_OUTPUT")
    [ -n "$fingerprint" ] || return 0
    known=$(archive_dates)
    if LC_ALL=C grep -aqxF -e "$1"$'\t'"$fingerprint" <<<"$(cut -f1,3 <<<"$known")"; then
        borg delete "$BORG_REPO::$1" >&2 || say "could not delete the failed archive $1"
    fi
}
