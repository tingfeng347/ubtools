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

echo -e "${CYAN}========================================${RESET}"
echo -e "${CYAN}  ubtools - Ubuntu Package TUI Tools${RESET}"
echo -e "${CYAN}========================================${RESET}"
echo ""

# --- 自动安装 fzf ---
install_fzf() {
    echo -e "${YELLOW}  未检测到 fzf，核心依赖，必须安装。${RESET}"
    read -rp "  是否安装? [Y/n] " yn
    if [[ "$yn" =~ ^[Nn] ]]; then
        echo -e "${RED}  已取消，ubti/ubtr 无法运行。${RESET}"
        exit 1
    fi
    sudo apt update -qq
    sudo apt install -y fzf
    echo -e "  ${GREEN}✓${RESET} fzf 已安装"
}

# --- 自动安装 flatpak + flathub ---
install_flatpak() {
    echo -e "${YELLOW}  未检测到 flatpak。${RESET}"
    read -rp "  是否安装 flatpak? [Y/n] " yn
    if [[ "$yn" =~ ^[Nn] ]]; then
        echo -e "  - 跳过，Flatpak 源将不可用"
        return 1
    fi
    sudo apt update -qq
    sudo apt install -y flatpak
    echo -e "  ${GREEN}✓${RESET} flatpak 已安装"
    return 0
}

setup_flathub() {
    if ! flatpak remotes 2>/dev/null | grep -q flathub; then
        echo -e "${YELLOW}  未检测到 flathub 远程。${RESET}"
        read -rp "  是否添加 flathub? [Y/n] " yn
        if [[ "$yn" =~ ^[Nn] ]]; then
            echo -e "  - 跳过，Flatpak 源将不可用"
            return
        fi
        flatpak remote-add --if-not-exists flathub https://flathub.org/repo/flathub.flatpakrepo
        echo -e "  ${GREEN}✓${RESET} flathub 远程已添加"
    fi
}

# --- 自动安装 snap ---
install_snap() {
    echo -e "${YELLOW}  未检测到 snap。${RESET}"
    read -rp "  是否安装 snapd? [Y/n] " yn
    if [[ "$yn" =~ ^[Nn] ]]; then
        echo -e "  - 跳过，Snap 源将不可用"
        return 1
    fi
    sudo apt update -qq
    sudo apt install -y snapd
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
sudo cp "$SCRIPT_DIR/ubti" "$BIN_DIR/ubti"
sudo cp "$SCRIPT_DIR/ubtr" "$BIN_DIR/ubtr"
sudo chmod +x "$BIN_DIR/ubti" "$BIN_DIR/ubtr"
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
