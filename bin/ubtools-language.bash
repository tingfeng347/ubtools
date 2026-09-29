# Shared language preference for the ubtools commands.
ub_language_file() {
    printf '%s/ubtools/language' "${XDG_CONFIG_HOME:-$HOME/.config}"
}

ub_language_load() {
    local value="${UBTOOLS_LANG:-}" file
    if [[ "$value" != en && "$value" != zh ]]; then value=''; fi
    if [[ -z "$value" ]]; then
        file="$(ub_language_file)"
        if [[ -r "$file" ]]; then IFS= read -r value < "$file" || true; fi
    fi
    case "$value" in en|zh) ;; *) value=zh;; esac
    export UBTOOLS_LANG="$value"
}

ub_language_set() {
    local value="$1" file directory temporary
    case "$value" in zh|en) ;; *) return 2;; esac
    file="$(ub_language_file)"
    directory="${file%/*}"
    mkdir -p -- "$directory"
    temporary="$(mktemp "$directory/.language.XXXXXX")"
    (umask 077; printf '%s\n' "$value" > "$temporary")
    mv -f -- "$temporary" "$file"
    export UBTOOLS_LANG="$value"
}

ub_language_load
