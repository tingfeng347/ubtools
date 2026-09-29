#!/usr/bin/env bash
# Standalone uninstaller for ubtools commands and shared files.
set -euo pipefail

uninstall_ubtools() {
BIN_DIR="${BIN_DIR:-/usr/local/bin}"
CACHE_DIR="${XDG_CACHE_HOME:-$HOME/.cache}/ubti_tui"
PURGE_CACHE=false
DRY_RUN=false

while (( $# )); do
    case "$1" in
        --purge-cache) PURGE_CACHE=true;;
        --dry-run) DRY_RUN=true;;
        --bin-dir)
            [[ $# -ge 2 && -n "$2" ]] || { echo '--bin-dir 需要目录参数' >&2; exit 2; }
            BIN_DIR="$2"; shift;;
        --help|-h)
            cat <<'HELP'
Usage: bash uninstall.sh [--purge-cache] [--dry-run] [--bin-dir DIR]

移除 ubtools 统一入口、缩写命令和共享文件，默认保留缓存。
  --purge-cache  同时删除当前用户的软件包列表缓存
  --dry-run      只列出将删除的文件，不执行删除
  --bin-dir DIR  指定安装目录（默认 /usr/local/bin，也可设置 BIN_DIR）

保留系统依赖、已安装软件、AI 客户端和配置、镜像源及其备份。
HELP
            exit 0;;
        *) echo "未知参数: $1" >&2; exit 2;;
    esac
    shift
done
[[ "$BIN_DIR" == /* && "$BIN_DIR" != / ]] || { echo '安装目录必须是绝对路径，且不能是 /' >&2; exit 2; }

remove_file() {
    if [[ "$DRY_RUN" == true ]]; then
        printf '将删除: %s\n' "$1"
    elif [[ "$EUID" -eq 0 || -w "$BIN_DIR" ]]; then
        rm -f -- "$1"
        printf '已删除: %s\n' "$1"
    else
        sudo rm -f -- "$1"
        printf '已删除: %s\n' "$1"
    fi
}

FOUND=false
for file in ub ubti ubtr ubtu ubtd ubtc ubtm ubta ubtools-completion.bash ubtools-common.bash ubtools-language.bash ubtools_runtime.py ubtools_mirror.py ubtools_ai.py; do
    target="$BIN_DIR/$file"
    if [[ -e "$target" || -L "$target" ]]; then
        remove_file "$target"
        FOUND=true
    fi
done
[[ "$FOUND" == true ]] || echo "未发现已安装的 ubtools 文件: $BIN_DIR"

if [[ "$PURGE_CACHE" == true && ( -e "$CACHE_DIR" || -L "$CACHE_DIR" ) ]]; then
    if [[ "$DRY_RUN" == true ]]; then
        printf '将删除缓存: %s\n' "$CACHE_DIR"
    else
        rm -rf -- "$CACHE_DIR"
        echo '已删除当前用户的软件包列表缓存。'
    fi
else
    echo '保留当前用户的软件包列表缓存；使用 --purge-cache 可一并清理。'
fi

if [[ "$DRY_RUN" == true ]]; then
    echo '预览完成，未删除文件。'
else
    echo 'ubtools 卸载完成。'
fi
echo '系统依赖、已安装软件、AI 客户端及配置、镜像源和 /var/lib/ubtools/mirror 备份保留。'
}

uninstall_ubtools "$@"
