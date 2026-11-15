# archivectl check: check the integrity of the repository

show_help() {
    cat <<'HELP'
Usage:
  archivectl check

Check the repository with borg check; the status is borg's.
HELP
    exit 0
}

run() {
    reject_options check "$@"
    enter_repository BORG_REPO
    borg check "$BORG_REPO" >&2
}
