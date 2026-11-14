# archivectl delete: delete the archives named on standard input

run() {
    local id
    parse_dry_run delete "$@"
    read_ids
    [ ${#IDS[@]} -gt 0 ] || return 0
    enter_repo BORG_REPO
    require_known "${IDS[@]}" < <(archive_dates | cut -f1)
    if [ "$DRY_RUN" = true ]; then
        for id in "${IDS[@]}"; do
            say "would delete archive $id"
        done
        return 0
    fi
    open_log
    borg delete "$BORG_REPO" "${IDS[@]}" 2>&1 | tee -a "$LOG_FILE" >&2
    for id in "${IDS[@]}"; do
        say "deleted archive $id"
    done
}
