# archivectl export-key: print the key of the repository

show_help() {
    cat <<'HELP'
Usage:
  archivectl export-key [--paper]

Print the key of the source's repository, for a copy kept away from it.

Options:
  --paper  The form borg gives for typing the key back by hand.
HELP
    exit 0
}

run() {
    local -a form=()
    while [ $# -gt 0 ]; do
        case "$1" in
            --paper) form=(--paper) ;;
            -h|--help) show_help ;;
            *) die "export-key: unknown option '$1'" $EXIT_INVALID_ARGS ;;
        esac
        shift
    done
    enter_repository BORG_REPO
    borg key export "${form[@]}" "$BORG_REPO"
}
