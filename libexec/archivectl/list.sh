# archivectl list: one record per archive, oldest first

show_help() {
    cat <<'HELP'
Usage:
  archivectl list [--human-readable] [--older N] [--newer N] [--first N] [--last N]

One record per archive, oldest first: number, date, size, files, the size
deleting it frees, and its comment. Age options select, then --first, --last.

Options:
  --human-readable  Sizes in K, M, G, T instead of bytes.
  --older N  Only the archives older than N days.
  --newer N  Only the archives newer than N days.
  --first N  Then only the oldest N.
  --last N   Then only the newest N.
HELP
    exit 0
}

run() {
    parse_select_options "$@"
    enter_repository BORG_REPO
    archive_entries | select_records | HUMAN="$HUMAN" with_sizes
}
