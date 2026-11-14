# archivectl list: one record per archive, oldest first

show_help() {
    cat <<'HELP'
Usage:
  archivectl list [--older N] [--newer N] [--first N] [--last N]

Print one record per archive, oldest first: its number, the date it was
made as YYYY-MM-DD HH:MM:SS, and its original size in bytes. An archive
not numbered yet shows the number the next create or delete gives it.

Options:
  --older N  Only the archives older than N days.
  --newer N  Only the archives newer than N days.
  --first N  Then only the oldest N of those.
  --last N   Then only the newest N of those.
HELP
    exit 0
}

run() {
    parse_select_options "$@"
    enter_repository BORG_REPO
    archive_entries | select_records | with_sizes
}
