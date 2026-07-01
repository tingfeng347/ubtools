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

prompt_yes_no() {
    local prompt="$1"
    local yn

    if [[ -r /dev/tty ]]; then
        read -rp "$prompt" yn < /dev/tty
    else
        read -rp "$prompt" yn
    fi

    [[ ! "$yn" =~ ^[Nn] ]]
}

ensure_sudo() {
    echo -e "  需要 sudo 权限安装依赖，如提示请输入当前用户密码。"
    sudo -v
}

apt_update_once() {
    if [[ "$APT_UPDATED" -eq 1 ]]; then
        return
    fi

    echo -e "  正在更新 APT 索引（如果网络较慢，这一步可能需要几分钟）..."
    sudo apt-get \
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
    sudo DEBIAN_FRONTEND=noninteractive apt-get -o DPkg::Lock::Timeout=60 install -y "$@"
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
        echo -e "${RED}  已取消，ubti/ubtr 无法运行。${RESET}"
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
    install_snap
fi
echo ""

# --- 3. 安装脚本 ---
echo -e "${CYAN}[3/4]${RESET} 安装 ubti / ubtr 到 ${BIN_DIR}..."

# 如果通过 curl | bash 运行，需要先下载脚本文件
RAW_BASE="https://raw.githubusercontent.com/tingfeng347/ubtools/main"
if [[ ! -f "$SCRIPT_DIR/bin/ubti" ]] || [[ ! -f "$SCRIPT_DIR/bin/ubtr" ]]; then
    TMPDIR="$(mktemp -d)"
    mkdir -p "$TMPDIR/bin"
    echo -e "  正在下载脚本..."
    curl -fsSL "$RAW_BASE/bin/ubti" -o "$TMPDIR/bin/ubti"
    curl -fsSL "$RAW_BASE/bin/ubtr" -o "$TMPDIR/bin/ubtr"
    SCRIPT_DIR="$TMPDIR"
fi

sudo cp "$SCRIPT_DIR/bin/ubti" "$BIN_DIR/ubti"
sudo cp "$SCRIPT_DIR/bin/ubtr" "$BIN_DIR/ubtr"
sudo chmod +x "$BIN_DIR/ubti" "$BIN_DIR/ubtr"

# 清理临时目录
if [[ -n "${TMPDIR:-}" ]]; then
    rm -rf "$TMPDIR"
fi

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
echo -e "  ${CYAN}ubti${RESET}          # 搜索并安装软件包"
echo -e "  ${CYAN}ubti firefox${RESET} # 搜索 firefox"
echo -e "  ${CYAN}ubti --flatpak${RESET} # 仅显示 Flatpak 源"
echo ""
echo -e "  ${CYAN}ubtr${RESET}          # 搜索并卸载软件包"
echo -e "  ${CYAN}ubtr firefox${RESET} # 搜索并卸载 firefox"
echo ""
echo -e "热键:"
echo -e "  ${CYAN}Tab${RESET}  多选  ${CYAN}Enter${RESET} 确认  ${CYAN}Ctrl+R${RESET} 刷新  ${CYAN}Esc${RESET} 退出"
