# archivectl diff: the paths that differ from an archive to another, or to the live source

run() {
    local -a names=()
    while [ $# -gt 0 ]; do
        case "$1" in
            -h|--help) usage 0 ;;
            -*) die "diff: unknown option '$1'" $EXIT_INVALID_ARGS ;;
            *) names+=("$1") ;;
        esac
        shift
    done
    [ ${#names[@]} -ge 1 ] && [ ${#names[@]} -le 2 ] ||
        die "diff takes one or two archive names." $EXIT_INVALID_ARGS
    enter_repo SOURCE_DIR BORG_REPO
    if [ ${#names[@]} -eq 2 ]; then
        # borg pads the change to 19 columns and a space before the path
        borg diff --content-only "$BORG_REPO::${names[0]}" "${names[1]}" |
            awk '{ change = $1; path = substr($0, 21)
                   if (change != "added" && change != "removed") change = "modified"
                   print path "\t" change }'
    else
        live_diff "${names[0]}"
    fi
}

# live_diff NAME: compare archive NAME, extracted into a temporary directory, with the live source
live_diff() {
    EXTRACTED=$(mktemp -d)
    trap 'chmod -R u+w "$EXTRACTED" 2>/dev/null; rm -rf "$EXTRACTED"' EXIT
    ( cd "$EXTRACTED" && borg extract "$BORG_REPO::$1" )
    build_exclude_params rsync
    compare_trees "$EXTRACTED" "$SOURCE_DIR" "${EXCLUDE_PARAMS[@]}"
}
