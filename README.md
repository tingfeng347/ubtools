# ubtools

Ubuntu 包管理 TUI 工具集，统一 APT / Snap / Flatpak 三个源。

## 安装

```bash
git clone https://github.com/tingfeng347/ubtools.git
cd ubtools
bash install.sh
```

或者一键：

```bash
curl -fsSL https://raw.githubusercontent.com/tingfeng347/ubtools/main/install.sh | bash
```

## 命令

| 命令 | 用途 | 源 |
|------|------|-----|
| `ubti` | 搜索并安装软件包 | APT / Snap / Flatpak |
| `ubtr` | 搜索并卸载软件包 | APT / Snap / Flatpak |

## 用法

```bash
ubti                  # 打开 TUI，搜索所有源
ubti firefox          # 搜索 firefox
ubti --flatpak        # 只看 Flatpak 源
ubti --apt --snap     # APT + Snap
ubti -y               # 强制刷新缓存

ubtr                  # 打开 TUI，卸载已安装包
ubtr firefox          # 搜索并卸载 firefox
```

## 热键

| 键 | 功能 |
|----|------|
| `Tab` | 多选 |
| `Enter` | 确认安装/卸载 |
| `Ctrl+R` | 刷新列表 |
| `Esc` | 退出 |

## 依赖

- **必需**: `fzf`
- **可选**: `snap`, `flatpak` (对应源自动检测)

```bash
sudo apt install fzf
```
