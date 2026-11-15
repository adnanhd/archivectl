# archivectl delete: delete the archives named as arguments or on standard input

show_help() {
    cat <<'HELP'
Usage:
  archivectl delete [-n] [<id>...]

Delete the archives given by number or name, or else those whose ids
begin the lines on standard input, as list prints them. Ids and piped
input together are refused. borg compact frees the space.

Options:
  -n, --dry-run  Report what would be deleted and delete nothing.
HELP
    exit 0
}

run() {
    local i
    local -a ids=()
    DRY_RUN=false
    while [ $# -gt 0 ]; do
        case "$1" in
            -n|--dry-run) DRY_RUN=true ;;
            -h|--help) show_help ;;
            -*) die "delete: unknown option '$1'" $EXIT_INVALID_ARGS ;;
            *) ids+=("$1") ;;
        esac
        shift
    done
    read_ids "${ids[@]}"
    [ ${#IDS[@]} -gt 0 ] || return 0
    enter_repository BORG_REPO
    require_archive "${IDS[@]}"
    if [ "$DRY_RUN" = true ]; then
        number_archives
        for i in "${NUMBERS[@]}"; do
            say "would delete archive $i"
        done
        return 0
    fi
    open_log
    lock_sequence
    number_archives
    unlock_sequence
    require_archive "${NUMBERS[@]}"
    borg delete "$BORG_REPO" "${NAMES[@]}" >&2
    for i in "${NUMBERS[@]}"; do
        say "deleted archive $i"
    done
}
