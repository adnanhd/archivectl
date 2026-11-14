# archivectl check: check the integrity of the repository

run() {
    reject_options check "$@"
    enter_repo BORG_REPO
    borg check "$BORG_REPO" >&2
}
