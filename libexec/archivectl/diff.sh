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
        borg diff --json-lines "$BORG_REPO::${names[0]}" "${names[1]}" | LC_ALL=C awk "$AWK_ESCAPE$AWK_BORG_DIFF"
    else
        live_diff "${names[0]}" "$scratch"
    fi
}

# An awk program, run with LC_ALL=C, that turns the lines of borg diff
# --json-lines into records "path<TAB>change": content changes and changes
# of type (the first character of the mode); borg writes the path as a JSON
# string, a byte that is not UTF-8 as \udcXX.
AWK_BORG_DIFF='
function hex(h,    i, v) {
    v = 0
    for (i = 1; i <= 4; i++) v = v * 16 + index("0123456789abcdef", tolower(substr(h, i, 1))) - 1
    return v
}
function utf8(c) {
    if (c < 128) return sprintf("%c", c)
    if (c < 2048) return sprintf("%c%c", 192 + int(c / 64), 128 + c % 64)
    if (c < 65536) return sprintf("%c%c%c", 224 + int(c / 4096), 128 + int(c / 64) % 64, 128 + c % 64)
    return sprintf("%c%c%c%c", 240 + int(c / 262144), 128 + int(c / 4096) % 64, 128 + int(c / 64) % 64, 128 + c % 64)
}
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
        } else if (code >= 56448 && code < 56576) { out = out sprintf("%c", code - 56320); continue }
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
