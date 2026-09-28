# Shared helpers for ubtu, ubtd and ubtc. Installed beside the commands.
UB_LANG="${UBTOOLS_LANG:-${LC_ALL:-${LC_MESSAGES:-${LANG:-C}}}}"
export UBTOOLS_LANG="$UB_LANG"
export LC_ALL=C
export SHELL=/bin/bash
UB_APT=true UB_SNAP=true UB_FLATPAK=true UB_SOURCE_SET=false
UB_LIST=false UB_DRY_RUN=false UB_EXACT=false UB_HELP=false
UB_GENERATE='' UB_QUERY=() UB_SOURCES=()
UB_TIMEOUT=15

ub_text() { if [[ "$UB_LANG" == *zh* ]]; then printf '%s' "$1"; else printf '%s' "$2"; fi; }
ub_error() { printf '%s\n' "$*" >&2; }
ub_source() {
    if [[ "$UB_SOURCE_SET" == false ]]; then
        UB_APT=false UB_SNAP=false UB_FLATPAK=false UB_SOURCE_SET=true
    fi
    case "$1" in apt) UB_APT=true;; snap) UB_SNAP=true;; flatpak) UB_FLATPAK=true;; esac
}
ub_parse() {
    while (( $# )); do
        case "$1" in
            --help|-h) UB_HELP=true;;
            --apt) ub_source apt;; --snap) ub_source snap;; --flatpak) ub_source flatpak;;
            --list) UB_LIST=true;; --dry-run) UB_DRY_RUN=true;; --exact|-e) UB_EXACT=true;;
            --generate)
                [[ $# -ge 2 ]] || return 2
                UB_GENERATE="$2"; shift;;
            --) shift; UB_QUERY+=("$@"); break;;
            -*) ub_error "Unknown option: $1"; return 2;;
            *) UB_QUERY+=("$1");;
        esac
        shift
    done
    [[ "$UB_APT" == false ]] || UB_SOURCES+=(--apt)
    [[ "$UB_SNAP" == false ]] || UB_SOURCES+=(--snap)
    [[ "$UB_FLATPAK" == false ]] || UB_SOURCES+=(--flatpak)
}
ub_init() {
    UB_TMP=$(mktemp -d -t ubtools.XXXXXX)
    UB_PID=''
    trap ub_cleanup EXIT
    trap 'exit 130' INT TERM
}
ub_stop() {
    if [[ -n "$UB_PID" ]]; then
        kill -- "-$UB_PID" 2>/dev/null || true
        wait "$UB_PID" 2>/dev/null || true
        UB_PID=''
    fi
}
ub_cleanup() { ub_stop; rm -rf "$UB_TMP"; }
# Capture first, then parse: a failed/partial query must never become an action.
ub_capture() {
    local output="$1"; shift
    local code=0
    timeout --foreground --kill-after=2s "${UB_TIMEOUT}s" "$@" > "$output" 2> "$output.err" || code=$?
    if (( code != 0 )); then
        ub_error "$(ub_text '查询失败或超时' 'Query failed or timed out'): $1 (exit $code)"
        : > "$output"
        return 1
    fi
}
# Visible label + source + scope + action identifier + two opaque details.
ub_row() {
    local src="$1" scope="$2" id="$3" left="$4" right="$5" label="$6" color='' reset=''
    left="${left:--}" right="${right:--}"
    if [[ "$UB_LIST" != true ]]; then
        case "$src" in apt) color=$'\033[34m';; snap) color=$'\033[35m';; flatpak) color=$'\033[36m';; esac
        reset=$'\033[0m'
    fi
    printf '%s%-15s%s %-52s %-22s %s\t%s\t%s\t%s\t%s\t%s\n' \
        "$color" "$src/$scope" "$reset" "$label" "$left" "$right" "$src" "$scope" "$id" "$left" "$right"
}
ub_command() {
    printf '> '; printf '%q ' "$@"; printf '\n'
    [[ "$UB_DRY_RUN" == true ]] || LC_ALL="$UB_LANG" "$@"
}
ub_confirm() {
    [[ "$UB_DRY_RUN" == true ]] && return 0
    local answer=''
    printf '%s ' "$(ub_text '执行所选操作？[y/N]' 'Apply selected actions? [y/N]')"
    if [[ -t 0 ]]; then read -r answer || return 1
    elif [[ -r /dev/tty ]] && ( : < /dev/tty ) 2>/dev/null; then
        read -r answer < /dev/tty || return 1
    else read -r answer || return 1; fi
    [[ "$answer" == y || "$answer" == Y ]]
}
ub_ui() {
    command -v fzf >/dev/null || { ub_error "$(ub_text '请先安装 fzf。' 'Install fzf first.')"; return 1; }
    local fifo="$UB_TMP/stream" snapshot="$UB_TMP/list" target="$UB_TMP/selected"
    local input="$fifo" query="${UB_QUERY[*]:-}" key='' code=0
    local preview script_quoted
    printf -v script_quoted '%q' "$UB_SCRIPT"
    preview="$script_quoted --preview {2} {3} {4} {5} {6}"
    mkfifo "$fifo"
    ub_start() {
        ub_stop
        : > "$snapshot"
        setsid "$UB_SCRIPT" --generate "$snapshot" "${UB_SOURCES[@]}" > "$fifo" 2> "$UB_TMP/errors" &
        UB_PID=$!
        input="$fifo"
    }
    ub_start
    while true; do
        local options=()
        [[ "$UB_EXACT" == false ]] || options+=(--exact)
        code=0
        fzf --multi --ansi --delimiter=$'\t' --with-nth=1 --layout=reverse --height=95% --border \
            --expect=ctrl-r,ctrl-e --print-query --query "$query" "${options[@]}" \
            --preview "$preview" --preview-window=down:45%:wrap \
            --header "$UB_HEADER" < "$input" > "$target" || code=$?
        [[ "$code" == 0 ]] || break
        query=$(sed -n '1p' "$target")
        key=$(sed -n '2p' "$target")
        case "$key" in
            ctrl-r) ub_start;;
            ctrl-e)
                if [[ "$UB_EXACT" == true ]]; then UB_EXACT=false; else UB_EXACT=true; fi
                if kill -0 "$UB_PID" 2>/dev/null; then ub_start; else input="$snapshot"; fi;;
            *) break;;
        esac
    done
    ub_stop
    [[ ! -s "$UB_TMP/errors" ]] || cat "$UB_TMP/errors" >&2
    [[ "$code" == 0 ]] || { [[ "$code" == 1 || "$code" == 130 ]] && return 0; return "$code"; }
    UB_SELECTED=()
    # fzf --ansi strips color from returned rows. Validate the unchanged
    # metadata against generated records rather than comparing the visible label.
    local allowed="$UB_TMP/allowed" metadata
    cut -f2- "$snapshot" > "$allowed"
    while IFS= read -r row; do
        metadata="${row#*$'\t'}"
        if [[ "$row" == *$'\t'* ]] && grep -Fxq -- "$metadata" "$allowed"; then
            UB_SELECTED+=("$row")
        fi
    done < <(tail -n +3 "$target")
    (( ${#UB_SELECTED[@]} )) || return 0
    printf '%s\n' "$(ub_text '所选操作：' 'Selected actions:')"
    printf '%s\n' "${UB_SELECTED[@]}" | cut -f1
    ub_confirm || return 0
    ub_apply
}
