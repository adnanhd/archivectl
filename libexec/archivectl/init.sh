# archivectl init: make a directory a backup source

show_help() {
    cat <<'HELP'
Usage:
  archivectl init [-n] [--repo <url>] [--no-pass] [--store-passphrase] [<path>]

Make <path>, or the current directory, a backup source with an encrypted
Borg repository under $BORG_BACKUP_ROOT, or at <url>, and keep its
passphrase in pass. initialise is an alias.

Options:
  -n, --dry-run       Report what would be written and write nothing.
  --repo <url>        Use the repository at <url>, ssh:// or user@host:path.
  --no-pass           Keep the passphrase out of pass.
  --store-passphrase  Keep the passphrase of an older source in pass.
HELP
    exit 0
}

run() {
    local path="" repo="" DRY_RUN=false use_pass=true store=false entry
    while [ $# -gt 0 ]; do
        case "$1" in
            -n|--dry-run) DRY_RUN=true ;;
            --repo)
                [ $# -gt 1 ] && [ -n "$2" ] || die "--repo needs a repository location." $EXIT_INVALID_ARGS
                repo="$2"
                shift
                ;;
            --no-pass) use_pass=false ;;
            --store-passphrase) store=true ;;
            -h|--help) show_help ;;
            -*) die "init: unknown option '$1'" $EXIT_INVALID_ARGS ;;
            *)
                [ -z "$path" ] || die "init takes at most one path." $EXIT_INVALID_ARGS
                path="$1"
                ;;
        esac
        shift
    done
    [ -z "$path" ] || [ -d "$path" ] || die "'$path' is not a directory." $EXIT_INVALID_ARGS
    [ "$store" = false ] || { [ -z "$repo" ] && [ "$use_pass" = true ]; } ||
        die "--store-passphrase takes neither --repo nor --no-pass." $EXIT_INVALID_ARGS
    REPO_ROOT=$(realpath "${path:-.}")
    command -v pass >/dev/null || use_pass=false
    if [ "$store" = true ]; then
        store_passphrase
        return
    fi
    entry="$PROG/$(safe_name "$REPO_ROOT")"
    if [ -f "$REPO_ROOT/$CONFIG" ]; then
        say "$REPO_ROOT holds a $CONFIG already."
        return 0
    fi
    if [ -z "$repo" ]; then
        repo=$(repository_for "$REPO_ROOT")
    fi
    initialise_source
}

# repository_for DIR: the repository of the source DIR under
# BORG_BACKUP_ROOT, a local path or a location on another host
repository_for() {
    local name
    if ! is_remote "$BORG_BACKUP_ROOT"; then
        storage_for "$BORG_BACKUP_ROOT" "$1"
        return
    fi
    name=$(safe_name "$1")
    case "$BORG_BACKUP_ROOT" in
        *: | */) printf '%s\n' "$BORG_BACKUP_ROOT$name" ;;
        *) printf '%s\n' "$BORG_BACKUP_ROOT/$name" ;;
    esac
}

# initialise_source: write the configuration of REPO_ROOT for the
# repository repo, initialising it unless it exists, and keep its
# passphrase in pass unless use_pass=false
initialise_source() {
    local exists=false passcommand=""
    local -a settings
    if repository_exists "$repo"; then
        exists=true
    fi
    if [ "$DRY_RUN" = true ]; then
        if [ "$exists" = true ]; then
            say "would write $REPO_ROOT/$CONFIG for the existing Borg repository $repo"
        else
            say "would write $REPO_ROOT/$CONFIG and initialise the Borg repository $repo"
        fi
        [ "$use_pass" = false ] || say "would keep its passphrase in pass as $entry"
        return 0
    fi
    open_log
    if [ "$use_pass" = true ]; then
        refuse_taken_entry
        read_passphrase "$repo"
        [ "$exists" = false ] || check_passphrase "$repo"
        keep_passphrase
        passcommand="pass show $(quoted "$entry")"
    fi
    if [ "$exists" = true ]; then
        say "using the existing Borg repository $repo"
    elif [ "$use_pass" = true ]; then
        # borg's own output stays out of the log: it can show the passphrase
        BORG_PASSPHRASE="$NEW_PASSPHRASE" command borg init --encryption=repokey --make-parent-dirs "$repo" >&2 || {
            pass rm -f "$entry" >/dev/null 2>&1 || true
            die "borg init of $repo failed, so pass keeps no passphrase for it."
        }
    else
        borg init --encryption=repokey --make-parent-dirs "$repo" >&2
    fi
    settings=(SOURCE_DIR=./ BORG_REPO="$repo")
    [ -z "$passcommand" ] || settings+=(BORG_PASSCOMMAND="$passcommand")
    # the ssh command that reached another host keeps reaching it
    ! is_remote "$repo" || [ -z "${BORG_RSH:-}" ] || settings+=(BORG_RSH="$BORG_RSH")
    write_config "$REPO_ROOT/$CONFIG" "${settings[@]}"
    say "initialised $REPO_ROOT, Borg repository $repo"
}

# store_passphrase: for the source at or above REPO_ROOT, initialised
# already, keep the passphrase of its repository in pass and add
# BORG_PASSCOMMAND to its configuration
store_passphrase() {
    [ "$use_pass" = true ] || die "init --store-passphrase needs pass, which is not installed."
    REPO_ROOT=$(find_repo_root "$REPO_ROOT" "$CONFIG") ||
        die "no $CONFIG in ${path:-the current directory} or its parents."
    entry="$PROG/$(safe_name "$REPO_ROOT")"
    cd "$REPO_ROOT"
    require_config "$CONFIG" BORG_REPO
    if grep -q '^BORG_PASSCOMMAND=' "$CONFIG"; then
        say "$REPO_ROOT/$CONFIG sets BORG_PASSCOMMAND already."
        return 0
    fi
    refuse_taken_entry
    if [ "$DRY_RUN" = true ]; then
        say "would check the passphrase of $BORG_REPO, keep it in pass as $entry and add BORG_PASSCOMMAND to $REPO_ROOT/$CONFIG"
        return 0
    fi
    open_log
    read_passphrase "$BORG_REPO"
    check_passphrase "$BORG_REPO"
    keep_passphrase
    printf 'BORG_PASSCOMMAND=%q\n' "pass show $(quoted "$entry")" >>"$CONFIG"
    say "$REPO_ROOT/$CONFIG reads it from there"
}

# quoted TEXT: TEXT in single quotes, for the shell and for borg, which splits BORG_PASSCOMMAND as a shell would
quoted() {
    printf "'%s'\n" "${1//\'/\'\\\'\'}"
}

# refuse_taken_entry: die when pass holds entry already
refuse_taken_entry() {
    [ ! -e "${PASSWORD_STORE_DIR:-$HOME/.password-store}/$entry.gpg" ] ||
        die "pass holds $entry already; remove it with pass rm $entry, or use --no-pass."
}

# read_passphrase LOCATION: NEW_PASSPHRASE, the passphrase of the
# repository at LOCATION: BORG_PASSPHRASE when it is set, else read once
# from the terminal
read_passphrase() {
    if [ -n "${BORG_PASSPHRASE+set}" ]; then
        NEW_PASSPHRASE="$BORG_PASSPHRASE"
        return 0
    fi
    [ -t 2 ] && { : </dev/tty; } 2>/dev/null ||
        die "init needs the passphrase of $1: set BORG_PASSPHRASE, run it on a terminal, or use --no-pass."
    IFS= read -rs -p "Passphrase for $1: " NEW_PASSPHRASE </dev/tty
    printf '\n' >&2
    [ -n "$NEW_PASSPHRASE" ] || die "an empty passphrase is refused."
}

# check_passphrase LOCATION: die unless NEW_PASSPHRASE opens the repository at LOCATION
check_passphrase() {
    local status=0 output
    output=$(BORG_PASSPHRASE="$NEW_PASSPHRASE" BORG_EXIT_CODES=modern command borg info "$1" 2>&1 >/dev/null) || status=$?
    case "$status" in
        0) ;;
        52) die "that is not the passphrase of $1." ;;
        *)
            printf '%s\n' "$output" >&2
            die "borg cannot open $1 (borg status $status)." "$status"
            ;;
    esac
}

# keep_passphrase: keep NEW_PASSPHRASE in pass as entry
keep_passphrase() {
    printf '%s\n' "$NEW_PASSPHRASE" | pass insert -m "$entry" >/dev/null ||
        die "pass could not keep $entry; set it up with pass init, or use --no-pass."
    say "kept the passphrase in pass as $entry"
}
