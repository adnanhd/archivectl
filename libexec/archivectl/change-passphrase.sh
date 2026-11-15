# archivectl change-passphrase: give the repository a new passphrase

show_help() {
    cat <<'HELP'
Usage:
  archivectl change-passphrase [-n]

Give the repository a new passphrase, typed twice or BORG_NEW_PASSPHRASE,
in the pass entry the configuration reads too.

Options:
  -n, --dry-run  Report what would change and change nothing.
HELP
    exit 0
}

# pass_entry: the entry of a BORG_PASSCOMMAND that is `pass show ENTRY', else nothing
pass_entry() {
    case "${BORG_PASSCOMMAND:-}" in
        "pass show "*) eval "printf '%s\n' ${BORG_PASSCOMMAND#pass show }" ;;
    esac
}

# read_new_passphrase: NEW_PASSPHRASE, BORG_NEW_PASSPHRASE when it is set,
# else typed twice on the terminal
read_new_passphrase() {
    local again
    if [ -n "${BORG_NEW_PASSPHRASE+set}" ]; then
        NEW_PASSPHRASE="$BORG_NEW_PASSPHRASE"
    else
        [ -t 2 ] && { : </dev/tty; } 2>/dev/null ||
            die "change-passphrase needs the new passphrase: run it on a terminal, or set BORG_NEW_PASSPHRASE."
        IFS= read -rs -p "New passphrase for $BORG_REPO: " NEW_PASSPHRASE </dev/tty
        printf '\n' >&2
        IFS= read -rs -p "The new passphrase for $BORG_REPO again: " again </dev/tty
        printf '\n' >&2
        [ "$NEW_PASSPHRASE" = "$again" ] || die "the two passphrases differ; nothing changed."
    fi
    [ -n "$NEW_PASSPHRASE" ] || die "an empty passphrase is refused."
}

run() {
    local DRY_RUN=false entry
    while [ $# -gt 0 ]; do
        case "$1" in
            -n|--dry-run) DRY_RUN=true ;;
            -h|--help) show_help ;;
            *) die "change-passphrase: unknown option '$1'" $EXIT_INVALID_ARGS ;;
        esac
        shift
    done
    enter_repository BORG_REPO
    entry=$(pass_entry)
    if [ "$DRY_RUN" = true ]; then
        say "would give $BORG_REPO a new passphrase${entry:+ and keep it in pass as $entry}"
        return 0
    fi
    read_new_passphrase
    export BORG_NEW_PASSPHRASE="$NEW_PASSPHRASE"
    borg key change-passphrase "$BORG_REPO" >&2
    say "gave $BORG_REPO a new passphrase"
    [ -n "$entry" ] || return 0
    printf '%s\n' "$NEW_PASSPHRASE" | pass insert -m -f "$entry" >/dev/null ||
        die "$BORG_REPO has the new passphrase, but pass could not keep it as $entry: run pass insert -f $entry and type it."
    say "kept the new passphrase in pass as $entry"
}
