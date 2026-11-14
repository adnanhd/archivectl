# archivectl initialise: make a directory a backup source

run() {
    local path="" DRY_RUN=false repo
    while [ $# -gt 0 ]; do
        case "$1" in
            -n|--dry-run) DRY_RUN=true ;;
            -h|--help) usage 0 ;;
            -*) die "initialise: unknown option '$1'" $EXIT_INVALID_ARGS ;;
            *)
                [ -z "$path" ] || die "initialise takes at most one path." $EXIT_INVALID_ARGS
                path="$1"
                ;;
        esac
        shift
    done
    [ -z "$path" ] || [ -d "$path" ] || die "'$path' is not a directory." $EXIT_INVALID_ARGS
    REPO_ROOT=$(realpath "${path:-.}")
    if [ -f "$REPO_ROOT/$CONFIG" ]; then
        say "$REPO_ROOT holds a $CONFIG already."
        return 0
    fi
    repo="$BORG_BACKUP_ROOT/$(safe_name "$REPO_ROOT")"
    if [ "$DRY_RUN" = true ]; then
        say "would write $REPO_ROOT/$CONFIG and initialise the Borg repository $repo"
        return 0
    fi
    open_log
    if [ -e "$repo/config" ]; then
        say "using the existing Borg repository $repo"
    else
        mkdir -p "$repo"
        borg init --encryption=repokey "$repo" 2>&1 | tee -a "$LOG_FILE" >&2
    fi
    cat >"$REPO_ROOT/$CONFIG" <<EOF
# Borg backup configuration for ${REPO_ROOT}
SOURCE_DIR="./"
BORG_REPO="${repo}"
EOF
    say "initialised $REPO_ROOT, Borg repository $repo"
}
