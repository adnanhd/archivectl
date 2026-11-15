# archivectl list: one record per archive, oldest first

show_help() {
    cat <<'HELP'
Usage:
  archivectl list [--older N] [--newer N] [--first N] [--last N]

Print one record per archive, oldest first: number, date, original size
in bytes. The age options select first, then --first and --last.

Options:
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
    archive_entries | select_records | with_sizes
}
