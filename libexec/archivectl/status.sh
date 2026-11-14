# archivectl status: one record of the backup source here

show_help() {
    cat <<'HELP'
Usage:
  archivectl status

Print one record of the backup source of the current directory: the
source, its repository, the number of archives, the number and date of
the newest, and the bytes the repository takes, deduplicated and
compressed. With no source here it says so on standard error and exits
with status 1. archivectl with no command prints it before the help.
HELP
    exit 0
}

run() {
    local entries count number="" date="" size
    reject_options status "$@"
    enter_repository SOURCE_DIR BORG_REPO
    entries=$(archive_entries)
    count=$(grep -c . <<<"$entries" || true)
    if [ "$count" -gt 0 ]; then
        IFS=$'\t' read -r number date _ < <(tail -n 1 <<<"$entries")
    fi
    size=$(borg info --json "$BORG_REPO" | awk '/"unique_csize": / { gsub(/[^0-9]/, ""); size = $0 } END { print size + 0 }')
    printf '%s\t%s\t%s\t%s\t%s\t%s\n' "$(escaped "$(realpath -m -- "$SOURCE_DIR")")" "$(escaped "$BORG_REPO")" \
        "$count" "$number" "$date" "$size"
}
