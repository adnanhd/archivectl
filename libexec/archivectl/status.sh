# archivectl status: one record of the backup source here

show_help() {
    cat <<'HELP'
Usage:
  archivectl status

Print one record of the backup source here: source, repository, number
of archives, number and date of the newest, and the bytes it takes.
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
