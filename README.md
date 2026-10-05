# ubtools

Ubuntu 终端工具集，用 `ub + 动作` 管理 APT / Snap / Flatpak 软件包、镜像源和 AI 编程工具。

## 安装

```bash
git clone https://github.com/tingfeng347/ubtools.git
cd ubtools
bash install.sh
```

或者一行安装：

```bash
curl -fsSL https://cdn.jsdelivr.net/gh/tingfeng347/ubtools@main/install.sh | bash
```

安装到 `${BIN_DIR:-/usr/local/bin}`。安装脚本部署统一入口、缩写命令及共享文件。
安装脚本会先尝试 GitHub Raw，再回退到 jsDelivr；会逐个显示文件下载进度。
文件未完整下载时不会执行脚本或覆盖现有安装；root 用户直接写入安装目录，其他用户通过 sudo 安装。
在源码目录也可以用 `./bin/ub` 代替下面的 `ub`，无需全局安装。

## 卸载

```bash
curl -fsSL https://cdn.jsdelivr.net/gh/tingfeng347/ubtools@main/uninstall.sh | bash
```

卸载默认保留缓存。预览、同时清除缓存，或指定安装目录：

```bash
curl -fsSL https://cdn.jsdelivr.net/gh/tingfeng347/ubtools@main/uninstall.sh | bash -s -- --dry-run
curl -fsSL https://cdn.jsdelivr.net/gh/tingfeng347/ubtools@main/uninstall.sh | bash -s -- --purge-cache
bash uninstall.sh --bin-dir /home/yourname/.local/bin
```

卸载只移除 ubtools 命令和共享文件；系统依赖、已安装软件、AI 工具及配置、镜像源及备份均保留。

## 命令

| 功能 | 完整命令 | 缩写 |
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

完整命令和缩写命令均可直接使用，例如 `ub install` / `ubti`、`ub mirror` / `ubtm`。

## 界面语言

默认使用简体中文；设置会保存到当前用户配置中，并应用于完整命令和缩写命令：

```bash
ub setup en  # 切换为英文
ub setup zh  # 切换为简体中文
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

安装界面只按软件包名称匹配关键词，版本号、来源和安装状态不参与搜索。
Snap 在启动时和修改搜索词后查询商店；未输入关键词时展示推荐包。
输入停顿 0.3 秒后开始查询，关键词结果与推荐列表分别缓存，Ctrl+R 可强制刷新当前查询。

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
ub mirror                      # 测速后询问是否切换并刷新 APT 索引
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
裸命令 `ub mirror` 会先完成测速，再询问是否备份并切换到最快可用源；确认后自动刷新 APT
索引，失败会恢复原配置。回答否只会测速，不修改源。显式 `test` 始终只测速；`--json`
适合脚本读取结果。`--dry-run` 无需 sudo；实际换源和恢复系统配置时使用 sudo。

```bash
ub mirror test --mirror https://mirror.example/ubuntu  # 替换为实际镜像地址
ub mirror test --timeout 5 --limit 4
```

`--mirror` 可重复指定。用于测试或自定义环境的选项还有 `--apt-dir`、`--state-dir`、
`--reference`、`--keyring` 和 `--arch`。自定义 APT 目录使用独立索引目录，不覆盖本机 APT 状态。
签名密钥应来自可信的 Ubuntu archive keyring。

## AI 编程工具

```bash
ub ai                          # 安装界面，显示安装状态
ub ai install                  # 多选 Codex / Claude Code / OpenCode / Pi Agent
ub ai install codex claude opencode pi
ub ai install --all --dry-run  # 只预览安装/更新计划
ub ai install pi               # 单独安装 Pi Agent
ub ai update pi                # 更新 Pi Agent
ub ai update --check           # 只检查所有已安装工具是否有上游新版本
ub ai update codex --check     # 只检查 Codex
ub ai remove                   # 多选卸载已安装的 AI 工具
ub ai remove pi                # 卸载单个工具
ub ai remove --all --dry-run    # 预览全部工具、全部来源的卸载命令
ub ai remove codex --path ~/.local/bin/codex # 卸载指定安装副本
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
`status --latest` 和 `update --check` 的最新版本来自 npm 上游发布，可能与 APT、Homebrew 或预发布渠道不同。
`update --check` 按 [SemVer](https://semver.org/) 比较每处安装的版本，显示可更新、已是最新、本机版本较新或无法比较；不执行更新。查询失败会报告错误并继续检查其他工具。

Pi Agent 的命令名是 `pi`，新安装使用 [Pi 官方安装脚本](https://pi.dev/docs/latest/quickstart)。
官方托管安装通过 `pi update` 更新；npm 安装沿用 npm，并使用当前包
`@earendil-works/pi-coding-agent@latest` 和 `--ignore-scripts`。
检测到旧的 `@mariozechner/pi-coding-agent` 安装时，按[官方迁移说明](https://pi.dev/changelog/2026/5/7/pi-has-a-new-home)
执行两次 `pi update`，先更新旧发行版，再切换新包名。

TUI 中按 `Tab` 多选，`Ctrl+A` 全选列表项，`Ctrl+D` 取消全选，`Enter` 进入计划确认，`Esc` 退出。
安装、更新和卸载先展示计划并确认；`--dry-run` 只预览命令，`--yes` 可跳过 ub 的计划确认。
Pi 官方安装器可能继续询问 Node.js 运行时和安装方式，请按它的提示完成。
`ub ai`（或 `ub ai install`）打开安装界面，显示各工具是否已安装及安装来源，仅按工具名搜索。
`ub ai remove` 打开独立的卸载界面，按来源和路径分别列出已安装副本。两个界面均用 Tab 多选、Enter 继续、Esc 退出。
检测范围包含 PATH 中的可执行文件、官方用户安装目录、常见 npm/Bun/pnpm 目录、NVM 的 Node 版本目录，以及已配置的安装目录。同一目标的软链合并为一处安装；`ub ai status` 显示全部副本并标记当前 PATH 生效的副本。
直接指定工具名且有多处安装时，需用 `--path` 指定副本或进入卸载界面选择；`remove --all` 选择全部工具的全部安装副本。
操作结束后重新检测状态；卸载未完成会返回失败，卸载一处但仍有其他安装时会列出剩余路径。安装和更新也会复查版本并提示重复安装。
卸载前显示命令并要求确认，按已检测到的来源运行原包管理器或官方卸载方式，默认保留客户端配置、凭据和会话。原 `ub ai uninstall` 命令仍可使用。
OpenCode 通过官方 `opencode uninstall --keep-config --keep-data` 保留配置和会话；
Pi 托管安装器需在其界面按 `U` 选择卸载。Pi 安装器仍会保留 `~/.pi/agent/` 数据。
OpenCode、Pi 与 Codex 按各自的[官方 CLI 文档](https://opencode.ai/v2/docs/cli)、
[官方卸载说明](https://pi.dev/docs/latest/quickstart)及[官方安装仓库](https://github.com/openai/codex)处理。
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
