# archivectl list: one record per archive, oldest first

run() {
    parse_select_options "$@"
    enter_repo BORG_REPO
    archive_dates | select_records | with_sizes
}
