# archivectl create: archive the source into a new archive

run() {
    local name
    parse_dry_run create "$@"
    enter_repo SOURCE_DIR BORG_REPO
    name=$(date '+%Y-%m-%d_%H:%M:%S')
    build_exclude_params borg
    if [ "$DRY_RUN" = true ]; then
        say "would create archive $name of $REPO_ROOT"
        ( cd "$SOURCE_DIR" && borg create --dry-run --list "${EXCLUDE_PARAMS[@]}" "$BORG_REPO::$name" . ) >&2
    else
        open_log
        ( cd "$SOURCE_DIR" &&
          borg create --stats --compression lz4 "${EXCLUDE_PARAMS[@]}" "$BORG_REPO::$name" . ) 2>&1 |
            tee -a "$LOG_FILE" >&2
        say "created archive $name of $REPO_ROOT"
        archive_dates | NAME="$name" awk -F '\t' '$1 == ENVIRON["NAME"]' | with_sizes
    fi
    create_in_parent "$@"
}
