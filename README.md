# ubtools

Ubuntu 终端工具集，用 `ub + 动作` 管理 APT / Snap / Flatpak 软件包、镜像源和 AI 编程工具。

## 安装

```bash
git clone https://github.com/tingfeng347/ubtools.git
cd ubtools
bash install.sh
```

或者一键安装：

```bash
curl -fsSL https://raw.githubusercontent.com/tingfeng347/ubtools/main/install.sh | bash
```

安装到 `${BIN_DIR:-/usr/local/bin}`。安装脚本部署统一入口、兼容命令及共享文件。
一键安装会逐个显示 13 个文件的下载进度：连接超时 10 秒、单次请求最多 30 秒，失败重试一次。
下载失败时退出并保留现有安装；root 用户直接写入安装目录，其他用户通过 sudo 安装。
如果停在下载阶段，请检查 `raw.githubusercontent.com` 的网络连通性。
在源码目录也可以用 `./bin/ub` 代替下面的 `ub`，无需全局安装。

## 卸载 ubtools

独立卸载脚本可以直接运行，无需先克隆仓库，也适用于只安装过 `ubti` / `ubtr` 的旧版本：

```bash
curl -fsSL https://raw.githubusercontent.com/tingfeng347/ubtools/main/uninstall.sh | bash
```

默认删除安装目录中的 `ub`、旧命令 `ubti/ubtr/ubtu/ubtd/ubtc/ubtm/ubta` 和共享文件，保留缓存。
同时清理当前用户的软件包列表缓存：

```bash
curl -fsSL https://raw.githubusercontent.com/tingfeng347/ubtools/main/uninstall.sh | bash -s -- --purge-cache
```

先预览，或从本地源码执行卸载：

```bash
curl -fsSL https://raw.githubusercontent.com/tingfeng347/ubtools/main/uninstall.sh | bash -s -- --dry-run
bash uninstall.sh
bash uninstall.sh --bin-dir /home/yourname/.local/bin
```

卸载不会删除系统依赖、已安装软件、AI 客户端及配置、镜像源及备份。
需要清理旧版再安装新版时，先运行上面的卸载命令，再执行安装命令：

```bash
curl -fsSL https://raw.githubusercontent.com/tingfeng347/ubtools/main/install.sh | bash
```

## 命令

| 功能 | 命令 | 兼容入口 |
|---|---|---|
| 搜索并安装软件 | `ub install` | `ubti` |
| 搜索并卸载软件 | `ub remove` | `ubtr` |
| 查看并更新软件 | `ub update` | `ubtu` |
| 检查环境、缓存和连通性 | `ub doctor` | `ubtd` |
| 预览并清理空间 | `ub clean` | `ubtc` |
| 镜像源测速与切换 | `ub mirror` | `ubtm` |
| AI 编程工具管理 | `ub ai` | `ubta` |

```bash
ub --help
ub update --help
ub help mirror
```

## 软件包安装、卸载和更新

```bash
ub install firefox             # 三源搜索并安装
ub install --flatpak firefox   # 只搜索 Flatpak
ub install --apt --snap vim     # 组合筛选数据源
ub install --exact firefox     # 精确匹配

ub remove                      # 多选卸载已安装软件包
ub remove firefox
ub remove --exact firefox

ub update                      # 查看新旧版本，多选更新
ub update --apt                # 只查看 APT 更新
ub update --list               # 只读列出更新
ub update --dry-run            # 在界面选择后只打印命令
ub update --refresh-index      # 先更新 APT 索引（需要 sudo）
```

更新时，Snap 展示版本和修订号；Flatpak 展示版本和提交标识，并区分用户级与系统级安装，
可识别版本名称相同的更新。APT 使用本机索引，只有 `--refresh-index` 才会先更新索引。
选择后确认，执行 `apt-get install --only-upgrade`、`snap refresh` 或相应范围的
`flatpak update`，包管理器继续提供原生事务提示。

## 诊断

```bash
ub doctor                      # 本地环境与远程连通性检查
ub doctor --offline            # 只检查本地
ub doctor --snap --timeout 5    # 每项最多等待 5 秒
```

逐项输出 `OK` / `WARN` / `FAIL` / `SKIP` 和耗时，检查依赖、APT 状态、锁文件使用者、
列表查询、`ub install` 缓存年龄、Snap 服务和 Flatpak 远程配置。
检查失败或超时返回 1，缺失的可选数据源记为 `SKIP`。
APT 网络探测对最多三个不同主机的索引 URL 发出 HEAD 请求；拒绝 HEAD 的源可能失败，
需要结合实际 APT 请求判断。锁检查覆盖当前用户可见的进程，打开文件不一定代表已持有锁。

## 清理

```bash
ub clean                       # 多选清理项，预览后确认
ub clean --list                # 只读列出清理入口
ub clean --snap --dry-run       # 只打印删除旧修订的命令
```

- APT 下载缓存：显示目录占用估算，执行 `apt-get clean`。
- APT 孤立依赖：预览 `apt-get --simulate autoremove`，执行时由 APT 展示最终移除清单。
- Snap 已禁用旧修订：逐修订选择，删除前重新检查是否仍为禁用状态。
- Flatpak 闲置运行时：按用户级、系统级选择；原生命令在最终确认前筛选并展示准确清单。

Flatpak 的 TUI 预览展示已安装运行时，**不代表全部可清理**。未知可释放空间显示 `-`。
清理不传入 `--delete-data`，不清除应用数据。

## 镜像源

```bash
ub mirror                      # 默认等同于 test
ub mirror test                 # 测速并输出结果
ub mirror test --json          # JSON 格式结果
ub mirror auto --dry-run       # 测速并预览换源，不修改配置
ub mirror auto                 # 备份、确认、应用最快可用源
ub mirror restore              # 恢复最近一次尚未恢复的备份
```

候选源来自 Ubuntu 镜像列表，并补充清华、中科大镜像，默认最多测八个，最多四个并发。
每个候选都要通过 Ubuntu `InRelease` 签名验证、架构与发行套件检查、有效期检查，
并与官方参考源的各套件 main 架构索引校验值一致；随后下载最多 256 KiB 的真实包索引样本测速。
显示的是当前网络环境下的样本速度，不代表持续带宽。
非 amd64/i386 使用 Ubuntu Ports 候选，可以用 `--mirror` 添加相应架构的镜像。

支持传统 `.list` 和 deb822 `.sources`，保留注释、组件、签名配置、禁用条目与第三方仓库，
保留独立的 `security.ubuntu.com` 源。自动切换后运行 APT 索引更新验证；失败时恢复原源配置。
备份存放在 `/var/lib/ubtools/mirror`，恢复时检查完整性，并拒绝覆盖换源后的手动修改。
确认需要覆盖手动修改时可使用 `ub mirror restore --force`。
`test` 和 `--dry-run` 无需 sudo；实际换源和恢复系统配置时使用 sudo。

```bash
ub mirror test --mirror https://mirror.example/ubuntu  # 替换为实际镜像地址
ub mirror test --timeout 5 --limit 4
```

`--mirror` 可重复指定。用于测试或自定义环境的选项还有 `--apt-dir`、`--state-dir`、
`--reference`、`--keyring` 和 `--arch`。自定义 APT 目录使用独立索引目录，不覆盖本机 APT 状态。
签名密钥应来自可信的 Ubuntu archive keyring。

## AI 编程工具

```bash
ub ai                          # 多选安装，等同于 install
ub ai install                  # 多选 Codex / Claude Code / OpenCode / Pi Agent
ub ai install codex claude opencode pi
ub ai install --all --dry-run  # 只预览安装/更新计划
ub ai install pi               # 单独安装 Pi Agent
ub ai update pi                # 更新 Pi Agent
ub ai status pi                # 查看 Pi 版本和安装来源
ub ai update                   # 多选更新已安装的客户端
ub ai update --all             # 更新全部已安装客户端
ub ai status                   # 查看本机版本、位置和安装方式；不联网
ub ai status --latest          # 同时查询 npm 最新发布版本
ub ai doctor --offline         # 本机版本及安装依赖检查
ub ai doctor                  # 加上官方安装入口连通性检查
```

首次安装使用各项目的官方安装脚本，下载为临时文件后执行，默认选择最新发布渠道；
安装后检查命令和版本，并提示登录入口与 PATH 配置。
已有 npm、pnpm、Bun、Homebrew、APT 或官方原生安装会沿用相应方式更新。
原生 Claude Code 更新遵循它已有的更新渠道设置，APT/Homebrew 更新遵循已有仓库或渠道。
无法可靠识别的安装以及由 Arch 包管理器管理的客户端，会提示用原安装工具更新，不创建重复安装。
`status --latest` 标注的是 npm 渠道版本，可能与其他发布渠道不同。

Pi Agent 的命令名是 `pi`，新安装使用 [Pi 官方安装脚本](https://pi.dev/docs/latest/quickstart)。
官方托管安装通过 `pi update` 更新；npm 安装沿用 npm，并使用当前包
`@earendil-works/pi-coding-agent@latest` 和 `--ignore-scripts`。
检测到旧的 `@mariozechner/pi-coding-agent` 安装时，按[官方迁移说明](https://pi.dev/changelog/2026/5/7/pi-has-a-new-home)
执行两次 `pi update`，先更新旧发行版，再切换新包名。

TUI 中按 `Tab` 多选，`Ctrl+A` 全选四个工具，`Ctrl+D` 取消全选，`Enter` 进入计划确认，`Esc` 退出。
安装和更新先展示计划并确认；`--dry-run` 不下载或执行安装脚本，`--yes` 可跳过 ub 的计划确认。
Pi 官方安装器可能继续询问 Node.js 运行时和安装方式，请按它的提示完成。
没有 `fzf` 时可以直接指定客户端名称或 `--all`。
工具不会写入 API Key、切换模型配置或清除客户端登录数据。

## 热键与缓存

软件包 TUI 支持：

| 键 | 功能 |
|---|---|
| `Tab` | 多选 |
| `Enter` | 确认安装/卸载，或进入更新/清理确认 |
| `Ctrl+R` | 刷新列表 |
| `Ctrl+E` | 切换精确/模糊匹配 |
| `Esc` | 退出 |

安装、更新和清理列表在后台加载，远程查询不会阻塞界面启动；退出会终止后台查询。
`ub install` 的 Snap / Flatpak 列表缓存仍位于 `${XDG_CACHE_HOME:-$HOME/.cache}/ubti_tui/`，
有效期一小时。过期缓存先展示，后台更新供下次使用；`Ctrl+R` 或 `--refresh` 会获取当前会话的新列表。
查询失败保留可用缓存。更新/清理列表不使用安装目录缓存，读取当前包管理器状态。

## 命令补全

在当前 Shell 启用：

```bash
# Bash
source <(ub completion bash)

# Zsh（先启用 compinit）
autoload -Uz compinit && compinit
source <(ub completion zsh)

# Fish
ub completion fish | source
```

需要每次启动启用时，将相应语句加入自己的 Shell 配置。
补全只提示当前已实现的命令、子命令和选项。

## 依赖与验证

Ubuntu 默认提供 Bash、GNU coreutils、util-linux；软件包 TUI 使用 `fzf`。
镜像源和 AI 管理使用 Python 3 标准库；镜像验证使用 `gpgv` 和 `ubuntu-keyring`。
AI 官方安装脚本可能需要 `curl`、`tar`、`unzip`，可用 `ub ai doctor` 检查。
包管理诊断可选 `curl` 和 `fuser`（`psmisc`）；Snap / Flatpak 根据安装情况自动检测。

```bash
python3 -m unittest discover -s tests -v
```

测试使用隔离包管理器验证更新、清理、退出清理、超时和确认流程；
使用本地 HTTP 服务和临时 GPG 签名验证镜像排名、过期/失效签名拒绝、换源回滚与精确恢复；
AI 安装使用临时脚本验证，不安装真实客户端。有 `fzf` 时会在伪终端里验证实际渲染与选包。

实现参考：[APT 手册](https://manpages.ubuntu.com/manpages/noble/man8/apt-get.8.html)、
[Ubuntu 镜像列表](https://ubuntu.com/docs/launchpad/developer/reference/services/ubuntu-mirrors-index/)、
[清华镜像帮助](https://mirrors.tuna.tsinghua.edu.cn/help/ubuntu/)、
[中科大镜像帮助](https://mirrors.ustc.edu.cn/help/ubuntu.html)、
[Snap 更新管理](https://snapcraft.io/docs/how-to-guides/manage-snaps/manage-updates/)、
[Flatpak 命令参考](https://docs.flatpak.org/en/latest/flatpak-command-reference.html)、
[Codex CLI](https://learn.chatgpt.com/docs/codex/cli)、
[Claude Code 安装](https://code.claude.com/docs/en/setup)、[OpenCode 安装](https://opencode.ai/docs/)。
