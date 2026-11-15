# archivectl diff: the paths that differ from an archive to another, or to the live source

show_help() {
    cat <<'HELP'
Usage:
  archivectl diff [--scratch <dir>] <id> [<id2>]

Print one record per path that differs from archive <id> to <id2>, or to
the live source: the path, then added, removed or modified. Files are
compared by content.

Options:
  --scratch <dir>  Where comparing with the live source extracts it.
HELP
    exit 0
}

run() {
    local scratch=""
    local -a names=()
    while [ $# -gt 0 ]; do
        case "$1" in
            --scratch)
                [ $# -gt 1 ] || die "--scratch needs a directory." $EXIT_INVALID_ARGS
                scratch=$(realpath -m -- "$2")
                shift
                ;;
            -h|--help) show_help ;;
            -*) die "diff: unknown option '$1'" $EXIT_INVALID_ARGS ;;
            *) names+=("$1") ;;
        esac
        shift
    done
    [ ${#names[@]} -ge 1 ] && [ ${#names[@]} -le 2 ] ||
        die "diff takes one or two archive ids." $EXIT_INVALID_ARGS
    enter_repository SOURCE_DIR BORG_REPO
    require_archive "${names[@]}"
    [ ${#names[@]} -eq 2 ] || [ -d "$scratch" ] ||
        die "comparing with the live source extracts the archive: name a directory with room for it, --scratch <dir>." $EXIT_INVALID_ARGS
    if [ ${#names[@]} -eq 2 ]; then
        # one archive named twice compares with itself
        archive_diff "${NAMES[0]}" "${NAMES[1]:-${NAMES[0]}}"
    else
        [[ "$scratch/" != "$(realpath -- "$SOURCE_DIR")"/* ]] ||
            die "--scratch must be outside the source $(realpath -- "$SOURCE_DIR")." $EXIT_INVALID_ARGS
        live_diff "${NAMES[0]}" "$scratch"
    fi
}

# archive_diff A B: one record per path whose content or type differs from
# archive A to archive B; borg diff writes a byte that is not UTF-8 as ?, so
# the records of paths holding ? are made from the listings of A and B. No
# borg command runs inside $(...) of a pipeline, so each one's failure ends
# the run with borg's status.
archive_diff() {
    local records first second checks line
    local -a output=()
    records=$(borg diff --json-lines "$BORG_REPO::$1" "$2" | LC_ALL=C awk "$AWK_ESCAPE$AWK_JSON$AWK_BORG_DIFF")
    [ -n "$records" ] || return 0
    if ! LC_ALL=C grep -aq '?' <<<"$records"; then
        printf '%s\n' "$records"
        return 0
    fi
    first=$(raw_paths "$1")
    second=$(raw_paths "$2")
    checks=$({ sed 's/^/1\t/' <<<"$first"; sed 's/^/2\t/' <<<"$second"; sed 's/^/D\t/' <<<"$records"; } |
        LC_ALL=C awk -F '\t' "$AWK_JSON$AWK_RAW_PATHS")
    while IFS= read -r line; do
        case "$line" in
            CHECK$'\t'*) resolve_shown "$1" "$2" "${line#CHECK$'\t'}" ;;
            ?*) output+=("$line") ;;
        esac
    done <<<"$checks"
    printf '%s\n' "${output[@]}"
}

# resolve_shown A B CHECK: add to output the records of the paths borg diff
# shows the same way, CHECK being "shown<TAB>change<TAB>count<TAB>candidate...":
# each candidate is in B only (added), in A only (removed), or in both with
# another content (modified); unless they are as many as borg's records, it dies
resolve_shown() {
    local candidate raw before after
    local -a fields chosen=()
    IFS=$'\t' read -r -a fields <<<"$3"
    for candidate in "${fields[@]:3}"; do
        if [ "${fields[1]}" = modified ]; then
            printf -v raw '%b' "$candidate"
            before=$(item_content "$1" "$raw")
            after=$(item_content "$2" "$raw")
            [ "$before" != "$after" ] || continue
        fi
        chosen+=("$candidate")
    done
    [ ${#chosen[@]} -eq "${fields[2]}" ] ||
        die "borg shows several paths as ${fields[0]} and cannot tell which is ${fields[1]}; compare with diff --scratch."
    for candidate in "${chosen[@]}"; do
        output+=("$candidate"$'\t'"${fields[1]}")
    done
}

# item_content NAME PATH: type, link target and SHA-256 of item PATH of
# archive NAME; borg lists a hard link to an earlier item as a regular file
# with that item's path as link target and no content, so its content is
# taken from that item
item_content() {
    local listed
    local -a field
    listed=$(PYTHONIOENCODING=unicode_escape borg list --format '{type}{NUL}{linktarget}{NUL}{sha256}{NUL}' \
        "$BORG_REPO::$1" "pf:$2" | LC_ALL=C awk "$AWK_ESCAPE$AWK_JSON$AWK_BORG_PATHS") || return
    mapfile -t field <<<"$listed"
    if [ "${field[0]}" = - ] && [ -n "${field[1]:-}" ]; then
        local master
        printf -v master '%b' "${field[1]}"
        item_content "$1" "$master"
        return
    fi
    printf '%s\t%s\t%s\n' "${field[0]}" "${field[1]:-}" "${field[2]:-}"
}

# raw_paths NAME: the path of every item of archive NAME, in borg's order,
# its bytes as they are but a backslash, tab or newline escaped
raw_paths() {
    PYTHONIOENCODING=unicode_escape borg list --format '{bpath}{NUL}' "$BORG_REPO::$1" |
        LC_ALL=C awk "$AWK_ESCAPE$AWK_JSON$AWK_BORG_PATHS"
}

# An awk program, run with LC_ALL=C, that reads the paths of archive A
# ("1<TAB>path"), of archive B ("2<TAB>path") and the records of borg diff
# ("D<TAB>path<TAB>change"). It prints a record without ? as it is, and for
# each path and change of the others "CHECK<TAB>path<TAB>change<TAB>count"
# and every path borg shows that way that is in B only (added), in A only
# (removed) or in both (modified).
AWK_RAW_PATHS='
$1 == "1" { first[$2]; order[++n] = $2; next }
$1 == "2" { second[$2]; if (!($2 in first)) order[++n] = $2; next }
index($2, "?") == 0 { print $2 "\t" $3; next }
{ key = $2 "\t" $3; if (!(key in count)) keys[++k] = key; count[key]++ }
END {
    for (j = 1; j <= k; j++) {
        split(keys[j], part, "\t")
        line = "CHECK\t" part[1] "\t" part[2] "\t" count[keys[j]]
        for (i = 1; i <= n; i++) {
            p = order[i]
            if (!(p in look)) look[p] = shown(p)
            if (look[p] != part[1]) continue
            if (part[2] == "added" ? (p in second) && !(p in first) : part[2] == "removed" ? (p in first) && !(p in second) : (p in first) && (p in second))
                line = line "\t" p
        }
        print line
    }
}'

# An awk program, run with LC_ALL=C, that turns the output of borg list
# --format "{bpath}{NUL}" written with PYTHONIOENCODING=unicode_escape into
# one path per line, escaped like a record: \uDCxx there is a byte that is
# not UTF-8, \x00 the end of a path. borg writes ? for such a byte in any
# other output.
AWK_BORG_PATHS='
{
    s = $0; out = ""; n = length(s)
    for (i = 1; i <= n; i++) {
        c = substr(s, i, 1)
        if (c != "\\") { out = out c; continue }
        c = substr(s, ++i, 1)
        if (c == "x") {
            code = hex(substr(s, i + 1, 2)); i += 2
            if (code == 0) { print esc(out); out = ""; continue }
            out = out utf8(code)
        } else if (c == "u") {
            code = hex(substr(s, i + 1, 4)); i += 4
            out = out ((code >= 56448 && code < 56576) ? sprintf("%c", code - 56320) : utf8(code))
        } else if (c == "U") {
            code = hex(substr(s, i + 1, 8)); i += 8
            out = out utf8(code)
        } else out = out (c == "n" ? "\n" : c == "t" ? "\t" : c == "r" ? "\r" : c)
    }
}'

# An awk program, run with LC_ALL=C, that turns the lines of borg diff
# --json-lines into records "path<TAB>change": content changes and changes
# of type (the first character of the mode); borg writes the path as a JSON
# string, a byte that is not UTF-8 as ?.
AWK_BORG_DIFF='
{
    if (!match($0, /"path": "([^"\\]|\\.)*"}$/)) next
    path = substr($0, RSTART + 9, RLENGTH - 11); changes = substr($0, 1, RSTART - 1)
    change = ""
    if (changes ~ /"type": "added/) change = "added"
    else if (changes ~ /"type": "removed/) change = "removed"
    else if (changes ~ /"type": "(modified|changed link)"/) change = "modified"
    else if (match(changes, /"new_mode": "./)) {
        type = substr(changes, RSTART + 13, 1)
        if (match(changes, /"old_mode": "./) && substr(changes, RSTART + 13, 1) != type) change = "modified"
    }
    if (change != "") print esc(unjson(path)) "\t" change
}'

# live_diff NAME DIR: compare archive NAME, extracted into a directory made
# under DIR and removed afterwards, with the live source
live_diff() {
    EXTRACTED=$(mktemp -d "$2/archivectl-diff.XXXXXX")
    trap 'chmod -R u+w "$EXTRACTED" 2>/dev/null; rm -rf "$EXTRACTED"' EXIT
    ( cd "$EXTRACTED" && borg extract "$BORG_REPO::$1" )
    build_exclude_params rsync
    compare_trees "$EXTRACTED" "$SOURCE_DIR" "${EXCLUDE_PARAMS[@]}"
}
