# archivectl create: archive the source into a new archive

show_help() {
    cat <<'HELP'
Usage:
  archivectl create [-n] [--stats]

Archive the source into a new archive and print its record. A backup
source in a parent directory is then archived too.

Options:
  -n, --dry-run  Only list, on standard error, what would be archived.
  --stats        Also print the statistics borg gives.
HELP
    exit 0
}

run() {
    local arg status=0 parent=0 STATS=false
    DRY_RUN=false
    for arg in "$@"; do
        case "$arg" in
            -n|--dry-run) DRY_RUN=true ;;
            --stats) STATS=true ;;
            -h|--help) show_help ;;
            *) die "create: unknown argument '$arg'" $EXIT_INVALID_ARGS ;;
        esac
    done
    enter_repository SOURCE_DIR BORG_REPO
    build_exclude_params borg
    # borg runs in SOURCE_DIR, entered here, so that a failure to enter it
    # is not taken for one of borg's
    if [ ! -d "$SOURCE_DIR" ] || [ ! -r "$SOURCE_DIR" ] || ! cd -- "$SOURCE_DIR" 2>/dev/null; then
        [ "$DRY_RUN" = true ] || open_log
        say "$REPO_ROOT has no directory $SOURCE_DIR it can read, so no archive is made"
        status=1
    elif [ "$DRY_RUN" = true ]; then
        next_number
        say "would create archive $NUMBER of $REPO_ROOT"
        borg create --dry-run --list "${EXCLUDE_PARAMS[@]}" "$BORG_REPO::$NUMBER" . >&2 || status=$?
        ! is_warning "$status" || status=0
        cd -- "$REPO_ROOT"
    else
        archive_source
    fi
    create_in_parent "$@" || parent=$?
    [ "$status" -eq 0 ] || return "$status"
    return "$parent"
}

# is_warning STATUS: whether STATUS is one of borg's warnings, 1 or 100 to 127
is_warning() {
    [ "$1" -eq 1 ] || { [ "$1" -ge 100 ] && [ "$1" -le 127 ]; }
}

# archive_source: take the next number, run borg create for its archive
# and set status; on a warning the archive is kept, on an error dropped if
# this run made it
archive_source() {
    local name
    open_log
    lock_sequence
    next_number
    name="${NUMBER}_$(date '+%Y-%m-%d_%H%M%S')"
    printf '%s\n' "$NUMBER" >"$SEQUENCE"
    unlock_sequence
    BORG_OUTPUT=$(mktemp "${LOG_FILE%.log}.borg.XXXXXX")
    trap 'rm -f "$BORG_OUTPUT"' EXIT
    # status is borg's own, PIPESTATUS[0]; --log-json keeps the file status
    # lines (C: changed while read, E: not read) apart from borg's messages,
    # and the reader shows them as text, the statistics only with --stats;
    # drop_archive reads the fingerprint in them
    if BORG_EXIT_CODES=modern borg create --log-json --stats --list --filter=CE --compression lz4 \
            "${EXCLUDE_PARAMS[@]}" "$BORG_REPO::$name" . 2>&1 |
        tee "$BORG_OUTPUT" | STATS="$STATS" LC_ALL=C awk "$AWK_JSON$AWK_BORG_LOG" >&2; then
        status=0
    else
        status=${PIPESTATUS[0]}
    fi
    cd -- "$REPO_ROOT"
    if is_warning "$status"; then
        log_skipped_files "$name" "$status"
        status=0
    fi
    if [ "$status" -eq 0 ]; then
        say "created archive $NUMBER of $REPO_ROOT"
        archive_entries | NAME="$name" awk -F '\t' '$3 == ENVIRON["NAME"]' | with_sizes
    else
        say "archive $NUMBER of $REPO_ROOT failed (borg status $status)"
        drop_archive "$name"
    fi
}

# An awk program, run with LC_ALL=C, that shows borg's --log-json output as
# text: each message, and each file status as "C path" or "E path"; the
# statistics only with STATS=true in the environment
AWK_BORG_LOG='
/^\{"type": "log_message"/ && /"name": "borg\.output\.stats"/ && ENVIRON["STATS"] != "true" { next }
/^\{"type": "(log_message|file_status)"/ {
    if (match($0, /"message": "([^"\\]|\\.)*"/)) print unjson(substr($0, RSTART + 12, RLENGTH - 13))
    else if (match($0, /"path": "([^"\\]|\\.)*"/)) {
        path = substr($0, RSTART + 9, RLENGTH - 10)
        match($0, /"status": "."/)
        print substr($0, RSTART + 11, 1) " " unjson(path)
    }
    fflush()
    next
}
{ print; fflush() }'

# log_skipped_files NAME STATUS: log each file borg's file status lines name
log_skipped_files() {
    local status path
    say "archive $NUMBER of $REPO_ROOT lacks or holds changed files borg named above (borg status $2)"
    while IFS=$'\t' read -r status path; do
        case "$status" in
            C) say "$path changed while borg read it" ;;
            E) say "$path could not be read" ;;
        esac
    done < <(LC_ALL=C awk "$AWK_ESCAPE$AWK_JSON$AWK_SKIPPED_FILES" "$BORG_OUTPUT")
}

# An awk program, run with LC_ALL=C, that prints "C<TAB>path" or "E<TAB>path"
# for each file status line of borg's --log-json output. borg writes a byte
# of the path that is not UTF-8 as ? there, but keeps it in the warning just
# before, "<path>: <reason>", from which the path is taken when it shows so.
AWK_SKIPPED_FILES='
function raw_of(path, message,    i) {
    for (i = 1; i < length(message); i++)
        if (substr(message, i, 2) == ": " && shown(substr(message, 1, i - 1)) == path) return substr(message, 1, i - 1)
    return path
}
/^\{"type": "log_message"/ && /"levelname": "WARNING"/ && match($0, /"message": "([^"\\]|\\.)*"/) {
    warning = unjson(substr($0, RSTART + 12, RLENGTH - 13))
    next
}
/^\{"type": "file_status"/ && match($0, /"path": "([^"\\]|\\.)*"/) {
    path = unjson(substr($0, RSTART + 9, RLENGTH - 10))
    match($0, /"status": "."/)
    status = substr($0, RSTART + 11, 1)
    if (index(path, "?") && warning != "") path = raw_of(path, warning)
    print status "\t" esc(path)
    warning = ""
}'

# drop_archive NAME: delete archive NAME if this run's borg committed it, as
# the fingerprint borg printed shows; an archive made by another run stays
drop_archive() {
    local fingerprint known
    fingerprint=$(grep -ao 'Archive fingerprint: [0-9a-f]\{64\}' "$BORG_OUTPUT" | cut -d' ' -f3 || true)
    [ -n "$fingerprint" ] || return 0
    known=$(archive_entries)
    if LC_ALL=C grep -aqxF -e "$1"$'\t'"$fingerprint" <<<"$(cut -f3,4 <<<"$known")"; then
        borg delete "$BORG_REPO::$1" >&2 || say "could not delete the failed archive $1"
    fi
}
