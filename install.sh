#!/usr/bin/env bash
# ==============================================================================
# ubtools - Ubuntu 包管理 TUI 一键安装脚本
# 支持 APT / Snap / Flatpak 三源统一搜索安装与卸载
# ==============================================================================
set -euo pipefail

RED='\033[1;31m'
GREEN='\033[1;32m'
YELLOW='\033[1;33m'
CYAN='\033[1;36m'
RESET='\033[0m'

BIN_DIR="${BIN_DIR:-/usr/local/bin}"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
APT_UPDATED=0

run_as_root() {
    if [[ "$EUID" -eq 0 ]]; then
        "$@"
    else
        sudo "$@"
    fi
}

prompt_yes_no() {
    local prompt="$1"
    local yn=""

    if [[ -r /dev/tty ]] && ( : < /dev/tty ) 2>/dev/null; then
        read -rp "$prompt" yn < /dev/tty || return 1
    else
        read -rp "$prompt" yn || return 1
    fi

    [[ ! "$yn" =~ ^[Nn] ]]
}

ensure_sudo() {
    [[ "$EUID" -ne 0 ]] || return 0
    echo -e "  需要 sudo 权限安装依赖，如提示请输入当前用户密码。"
    sudo -v
}

apt_update_once() {
    if [[ "$APT_UPDATED" -eq 1 ]]; then
        return
    fi

    echo -e "  正在更新 APT 索引（如果网络较慢，这一步可能需要几分钟）..."
    run_as_root apt-get \
        -o Acquire::http::Timeout=30 \
        -o Acquire::https::Timeout=30 \
        -o Acquire::Retries=2 \
        -o DPkg::Lock::Timeout=60 \
        update
    APT_UPDATED=1
}

apt_install_packages() {
    echo -e "  正在安装: $*"
    apt_update_once
    run_as_root env DEBIAN_FRONTEND=noninteractive apt-get -o DPkg::Lock::Timeout=60 install -y "$@"
}

# --- 检查是否为 Ubuntu ---
if ! grep -qi 'ubuntu' /etc/os-release 2>/dev/null; then
    echo -e "${RED}错误：此脚本仅支持 Ubuntu 系统。${RESET}"
    echo -e "当前系统：$(grep '^PRETTY_NAME=' /etc/os-release 2>/dev/null | cut -d= -f2 | tr -d '"' || echo '未知')"
    exit 1
fi

echo -e "${CYAN}========================================${RESET}"
echo -e "${CYAN}  ubtools - Ubuntu Package TUI Tools${RESET}"
echo -e "${CYAN}========================================${RESET}"
echo ""

# --- 自动安装 fzf ---
install_fzf() {
    echo -e "${YELLOW}  未检测到 fzf，核心依赖，必须安装。${RESET}"
    if ! prompt_yes_no "  是否安装? [Y/n] "; then
        echo -e "${RED}  已取消，包管理 TUI 无法运行。${RESET}"
        exit 1
    fi
    ensure_sudo
    apt_install_packages fzf
    echo -e "  ${GREEN}✓${RESET} fzf 已安装"
}

# --- 自动安装 flatpak + flathub ---
install_flatpak() {
    echo -e "${YELLOW}  未检测到 flatpak。${RESET}"
    if ! prompt_yes_no "  是否安装 flatpak? [Y/n] "; then
        echo -e "  - 跳过，Flatpak 源将不可用"
        return 1
    fi
    ensure_sudo
    apt_install_packages flatpak
    echo -e "  ${GREEN}✓${RESET} flatpak 已安装"
    return 0
}

setup_flathub() {
    if ! flatpak remotes --user 2>/dev/null | grep -q flathub; then
        echo -e "${YELLOW}  未检测到 flathub 远程。${RESET}"
        if ! prompt_yes_no "  是否添加 flathub? [Y/n] "; then
            echo -e "  - 跳过，Flatpak 源将不可用"
            return
        fi
        echo -e "  正在为当前用户添加 flathub 远程（网络不可达时最多等待 45 秒）..."
        if timeout 45s flatpak remote-add --user --if-not-exists flathub https://flathub.org/repo/flathub.flatpakrepo; then
            echo -e "  ${GREEN}✓${RESET} flathub 远程已添加"
            return
        fi

        echo -e "${YELLOW}  flathub 添加失败或超时，已跳过。APT/Snap 功能仍可正常使用。${RESET}"
        echo -e "  可稍后手动执行：flatpak remote-add --user --if-not-exists flathub https://flathub.org/repo/flathub.flatpakrepo"
    fi
}

# --- 自动安装 snap ---
install_snap() {
    echo -e "${YELLOW}  未检测到 snap。${RESET}"
    if ! prompt_yes_no "  是否安装 snapd? [Y/n] "; then
        echo -e "  - 跳过，Snap 源将不可用"
        return 1
    fi
    ensure_sudo
    apt_install_packages snapd
    echo -e "  ${GREEN}✓${RESET} snap 已安装"
    return 0
}

# --- 1. 检查并安装依赖 ---
echo -e "${CYAN}[1/4]${RESET} 检查核心依赖..."
if ! command -v fzf >/dev/null 2>&1; then
    install_fzf
else
    echo -e "  ${GREEN}✓${RESET} fzf 已安装"
fi
echo ""

# Mirror and AI management use Python's standard library and curl installers.
for dependency in python3 curl; do
    if ! command -v "$dependency" >/dev/null 2>&1; then
        ensure_sudo
        apt_install_packages "$dependency"
    fi
done

# --- 2. 检查并安装可选依赖 ---
echo -e "${CYAN}[2/4]${RESET} 检查可选依赖..."
if command -v flatpak >/dev/null 2>&1; then
    echo -e "  ${GREEN}✓${RESET} flatpak 已安装"
    setup_flathub
else
    if install_flatpak; then
        setup_flathub
    fi
fi
if command -v snap >/dev/null 2>&1; then
    echo -e "  ${GREEN}✓${RESET} snap 已安装"
else
    install_snap || true
fi
echo ""

# --- 3. 安装脚本 ---
echo -e "${CYAN}[3/4]${RESET} 安装 ub 和七个缩写命令 到 ${BIN_DIR}..."
COMMANDS=(ub ubti ubtr ubtu ubtd ubtc ubtm ubta)
HELPERS=(ubtools-completion.bash ubtools-common.bash ubtools_runtime.py ubtools_mirror.py ubtools_ai.py)
FILES=("${COMMANDS[@]}" "${HELPERS[@]}")
DOWNLOAD_BASES=(
    "https://raw.githubusercontent.com/tingfeng347/ubtools/main"
    "https://cdn.jsdelivr.net/gh/tingfeng347/ubtools@main"
)
if [[ -n "${UBTOOLS_DOWNLOAD_BASES:-}" ]]; then
    read -r -a DOWNLOAD_BASES <<< "$UBTOOLS_DOWNLOAD_BASES"
fi
NEED_DOWNLOAD=false
for file in "${FILES[@]}"; do
    if [[ ! -f "$SCRIPT_DIR/bin/$file" ]]; then NEED_DOWNLOAD=true; break; fi
done
if [[ "$NEED_DOWNLOAD" == true ]]; then
    UBTOOLS_INSTALL_TMP="$(mktemp -d)"
    trap 'rm -rf "$UBTOOLS_INSTALL_TMP"' EXIT
    DOWNLOAD_READY=false
    LAST_DOWNLOAD_STATUS=1
    for base in "${DOWNLOAD_BASES[@]}"; do
        rm -rf "$UBTOOLS_INSTALL_TMP/bin"
        mkdir -p "$UBTOOLS_INSTALL_TMP/bin"
        echo "  正在尝试下载源: $base"
        DOWNLOAD_INDEX=0
        DOWNLOAD_READY=true
        for file in "${FILES[@]}"; do
            DOWNLOAD_INDEX=$((DOWNLOAD_INDEX + 1))
            echo "  [$DOWNLOAD_INDEX/${#FILES[@]}] 下载 $file..."
            target="$UBTOOLS_INSTALL_TMP/bin/$file"
            if curl -fsSL --connect-timeout 10 --max-time 30 --retry 1 --retry-delay 1 --retry-max-time 65 "$base/bin/$file" -o "$target" && [[ -s "$target" ]]; then
                echo "    ✓ 下载完成"
            else
                status=$?
                LAST_DOWNLOAD_STATUS=$status
                echo "    下载源失败: $base/bin/$file (curl exit $status)" >&2
                DOWNLOAD_READY=false
                break
            fi
        done
        if [[ "$DOWNLOAD_READY" == true ]]; then break; fi
    done
    if [[ "$DOWNLOAD_READY" != true ]]; then
        echo '所有下载源均失败，现有安装未修改。请检查网络后重试。' >&2
        exit "$LAST_DOWNLOAD_STATUS"
    fi
    SCRIPT_DIR="$UBTOOLS_INSTALL_TMP"
fi
echo "  下载/本地文件准备完成，写入 $BIN_DIR..."
run_as_root mkdir -p "$BIN_DIR"
for cmd in "${COMMANDS[@]}"; do
    echo "  安装 $cmd..."
    run_as_root install -m 755 "$SCRIPT_DIR/bin/$cmd" "$BIN_DIR/$cmd"
done
for file in "${HELPERS[@]}"; do
    echo "  安装 $file..."
    run_as_root install -m 644 "$SCRIPT_DIR/bin/$file" "$BIN_DIR/$file"
done
echo -e "  ${GREEN}✓${RESET} 已安装"

# --- 4. 初始化缓存 ---
echo ""
echo -e "${CYAN}[4/4]${RESET} 初始化缓存目录..."
mkdir -p "${XDG_CACHE_HOME:-$HOME/.cache}/ubti_tui"
echo -e "  ${GREEN}✓${RESET} 缓存目录已创建"

# --- 完成 ---
echo ""
echo -e "${GREEN}========================================${RESET}"
echo -e "${GREEN}  安装完成！${RESET}"
echo -e "${GREEN}========================================${RESET}"
echo ""
echo -e "用法:"
echo -e "  ${CYAN}ub install firefox${RESET} # 搜索并安装"
echo -e "  ${CYAN}ub remove${RESET}          # 搜索并卸载"
echo -e "  ${CYAN}ub update${RESET}          # 多选更新"
echo -e "  ${CYAN}ub doctor${RESET}          # 环境诊断"
echo -e "  ${CYAN}ub clean${RESET}           # 预览并清理"
echo -e "  ${CYAN}ub mirror test${RESET}     # 镜像源测速"
echo -e "  ${CYAN}ub ai install${RESET}      # 多选安装 AI 工具"
echo -e "  ${CYAN}ub --help${RESET}          # 查看全部命令"
echo ""
echo -e "缩写命令：ubti / ubtr / ubtu / ubtd / ubtc / ubtm / ubta。"
