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
# a path holding ? is matched to its bytes in the listings of A and B
archive_diff() {
    local records
    records=$(borg diff --json-lines "$BORG_REPO::$1" "$2" | LC_ALL=C awk "$AWK_ESCAPE$AWK_CODE_POINTS$AWK_BORG_DIFF")
    [ -n "$records" ] || return 0
    if ! LC_ALL=C grep -aq '?' <<<"$records"; then
        printf '%s\n' "$records"
        return 0
    fi
    { raw_paths "$1" | sed 's/^/1\t/'; raw_paths "$2" | sed 's/^/2\t/'; printf '%s\n' "$records" | sed 's/^/D\t/'; } |
        LC_ALL=C awk -F '\t' "$AWK_RAW_PATHS"
}

# raw_paths NAME: the path of every item of archive NAME, in borg's order,
# its bytes as they are but a backslash, tab or newline escaped
raw_paths() {
    PYTHONIOENCODING=unicode_escape borg list --format '{bpath}{NUL}' "$BORG_REPO::$1" |
        LC_ALL=C awk "$AWK_ESCAPE$AWK_CODE_POINTS$AWK_BORG_PATHS"
}

# An awk program, run with LC_ALL=C, that reads the paths of archive A
# ("1<TAB>path"), of archive B ("2<TAB>path") and the records of borg diff
# ("D<TAB>path<TAB>change"), and prints each record with its path's own
# bytes: the first path not yet used that borg shows the same way and that
# is in B only (added), in A only (removed) or in both (modified).
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
{
    for (i = 1; i <= n; i++) {
        p = order[i]
        if (p in used) continue
        if (!(p in look)) look[p] = shown(p)
        if (look[p] != $2) continue
        if ($3 == "added" ? (p in second) && !(p in first) : $3 == "removed" ? (p in first) && !(p in second) : (p in first) && (p in second)) {
            used[p]; print p "\t" $3; next
        }
    }
    print $2 "\t" $3
}'

# Awk functions for the programs below: hex reads up to 8 hex digits, utf8
# writes a code point as UTF-8.
AWK_CODE_POINTS='
function hex(h,    i, v) {
    v = 0
    for (i = 1; i <= length(h); i++) v = v * 16 + index("0123456789abcdef", tolower(substr(h, i, 1))) - 1
    return v
}
function utf8(c) {
    if (c < 128) return sprintf("%c", c)
    if (c < 2048) return sprintf("%c%c", 192 + int(c / 64), 128 + c % 64)
    if (c < 65536) return sprintf("%c%c%c", 224 + int(c / 4096), 128 + int(c / 64) % 64, 128 + c % 64)
    return sprintf("%c%c%c%c", 240 + int(c / 262144), 128 + int(c / 4096) % 64, 128 + int(c / 64) % 64, 128 + c % 64)
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
function unjson(s,    out, i, c, code) {
    out = ""
    for (i = 1; i <= length(s); i++) {
        c = substr(s, i, 1)
        if (c != "\\") { out = out c; continue }
        c = substr(s, ++i, 1)
        if (c != "u") { out = out (c == "n" ? "\n" : c == "t" ? "\t" : c == "r" ? "\r" : c == "b" ? "\b" : c == "f" ? "\f" : c); continue }
        code = hex(substr(s, i + 1, 4)); i += 4
        if (code >= 55296 && code < 56320 && substr(s, i + 1, 2) == "\\u") {
            code = 65536 + (code - 55296) * 1024 + hex(substr(s, i + 3, 4)) - 56320; i += 6
        }
        out = out utf8(code)
    }
    return out
}
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
