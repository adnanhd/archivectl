# archivectl diff: the paths that differ from an archive to another, or to the live source

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
            -h|--help) usage 0 ;;
            -*) die "diff: unknown option '$1'" $EXIT_INVALID_ARGS ;;
            *) names+=("$1") ;;
        esac
        shift
    done
    [ ${#names[@]} -ge 1 ] && [ ${#names[@]} -le 2 ] ||
        die "diff takes one or two archive names." $EXIT_INVALID_ARGS
    [ ${#names[@]} -eq 2 ] || [ -d "$scratch" ] ||
        die "comparing with the live source extracts the archive: name a directory with room for it, --scratch <dir>." $EXIT_INVALID_ARGS
    enter_repo SOURCE_DIR BORG_REPO
    require_archive "${names[@]}"
    if [ ${#names[@]} -eq 2 ]; then
        archive_diff "${names[0]}" "${names[1]}"
    else
        [[ "$scratch/" != "$(realpath -- "$SOURCE_DIR")"/* ]] ||
            die "--scratch must be outside the source $(realpath -- "$SOURCE_DIR")." $EXIT_INVALID_ARGS
        live_diff "${names[0]}" "$scratch"
    fi
}

# archive_diff A B: one record per path whose content or type differs from
# archive A to archive B; borg diff writes a byte that is not UTF-8 as ?, so
# the records of paths holding ? are made from the listings of A and B
archive_diff() {
    local records line resolved
    records=$(borg diff --json-lines "$BORG_REPO::$1" "$2" | LC_ALL=C awk "$AWK_ESCAPE$AWK_JSON$AWK_BORG_DIFF")
    [ -n "$records" ] || return 0
    if ! LC_ALL=C grep -aq '?' <<<"$records"; then
        printf '%s\n' "$records"
        return 0
    fi
    resolved=$({ raw_paths "$1" | sed 's/^/1\t/'; raw_paths "$2" | sed 's/^/2\t/'
                 printf '%s\n' "$records" | sed 's/^/D\t/'; } | LC_ALL=C awk -F '\t' "$AWK_RAW_PATHS" |
        while IFS= read -r line; do
            case "$line" in
                CHECK$'\t'*) resolve_shown "$1" "$2" "${line#CHECK$'\t'}" ;;
                *) printf '%s\n' "$line" ;;
            esac
        done)
    printf '%s\n' "$resolved"
}

# resolve_shown A B CHECK: the records of the paths borg diff shows the same
# way, CHECK being "shown<TAB>change<TAB>count<TAB>candidate...": each
# candidate is in B only (added), in A only (removed), or in both and
# different (modified); unless they are as many as borg's records, it dies
resolve_shown() {
    local candidate
    local -a fields chosen=()
    IFS=$'\t' read -r -a fields <<<"$3"
    for candidate in "${fields[@]:3}"; do
        if [ "${fields[1]}" != modified ] || item_differs "$1" "$2" "$candidate"; then
            chosen+=("$candidate")
        fi
    done
    [ ${#chosen[@]} -eq "${fields[2]}" ] ||
        die "borg shows several paths as ${fields[0]} and cannot tell which is ${fields[1]}; compare with diff --scratch."
    for candidate in "${chosen[@]}"; do
        printf '%s\t%s\n' "$candidate" "${fields[1]}"
    done
}

# item_differs A B PATH: whether item PATH, escaped like a record, differs in
# type, link target or content from archive A to archive B
item_differs() {
    local raw
    printf -v raw '%b' "$3"
    [ "$(item_print "$1" "$raw")" != "$(item_print "$2" "$raw")" ]
}

# item_print NAME PATH: type, link target and SHA-256 of item PATH of archive NAME
item_print() {
    PYTHONIOENCODING=unicode_escape borg list --format '{type}{TAB}{linktarget}{TAB}{sha256}{NUL}' \
        "$BORG_REPO::$1" "pf:$2"
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
function shown(s,    out, i, n, b, c, need, j, ok) {
    if (s !~ /[\200-\377]/) return s
    out = ""; n = length(s)
    for (i = 1; i <= n; i++) {
        b = byte[substr(s, i, 1)]
        if (b < 128) { out = out substr(s, i, 1); continue }
        need = (b >= 194 && b <= 223) ? 1 : (b >= 224 && b <= 239) ? 2 : (b >= 240 && b <= 244) ? 3 : 0
        ok = need > 0 && i + need <= n
        for (j = 1; ok && j <= need; j++) { c = byte[substr(s, i + j, 1)]; if (c < 128 || c > 191) ok = 0 }
        if (ok && need >= 2) {
            c = byte[substr(s, i + 1, 1)]
            if ((b == 224 && c < 160) || (b == 237 && c > 159) || (b == 240 && c < 144) || (b == 244 && c > 143)) ok = 0
        }
        if (ok) { out = out substr(s, i, need + 1); i += need } else out = out "?"
    }
    return out
}
BEGIN { for (i = 1; i < 256; i++) byte[sprintf("%c", i)] = i }
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
