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

## 卸载

```bash
curl -fsSL https://raw.githubusercontent.com/tingfeng347/ubtools/main/uninstall.sh | bash
```

或者在源码目录运行：

```bash
bash uninstall.sh
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
ubti --exact firefox  # 关闭模糊匹配，适合长包名
ubti -y               # 强制刷新缓存

ubtr                  # 打开 TUI，卸载已安装包
ubtr firefox          # 搜索并卸载 firefox
ubtr -e firefox       # 关闭模糊匹配
```

## 启动与缓存

`ubti` 启动后在后台加载软件包列表，界面可立即搜索，结果随加载逐步补充。
Snap / Flatpak 的列表缓存位于 `${XDG_CACHE_HOME:-$HOME/.cache}/ubti_tui/`，
有效期为一小时。过期缓存会先显示，后台更新供下次启动使用；按 `Ctrl+R`
或使用 `--refresh` 可在当前界面获取最新列表。查询失败会保留原缓存。
APT 列表来自本机索引，不需要联网刷新。

## 热键

| 键 | 功能 |
|----|------|
| `Tab` | 多选 |
| `Enter` | 确认安装/卸载 |
| `Ctrl+R` | 刷新列表 |
| `Ctrl+E` | 切换精确匹配/模糊匹配 |
| `Esc` | 退出 |

## 依赖

- **必需**: `fzf`
- **可选**: `snap`, `flatpak` (对应源自动检测)

```bash
sudo apt install fzf
```

## 验证

```bash
python3 -m unittest discover -s tests -v
```

启动回归测试使用可控的慢数据源，检查界面不会等待远程列表、缓存刷新失败保护、
退出时终止后台查询，以及模式切换和刷新。已安装 `fzf` 时，还会在伪终端中验证真实首屏渲染。
