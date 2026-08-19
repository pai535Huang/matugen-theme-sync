# Matugen 必要依赖自动安装设计

## 目标

在 `install.sh` 安装项目文件前检查必要依赖 `matugen`。若未安装，脚本必须先征得用户明确同意，再按可用包管理器自动安装；用户拒绝、环境不支持或安装失败时，不得继续安装本项目。

## 安装流程

`do_install` 首先调用 `ensure_matugen`，之后才获取源码和写入项目文件。

1. `command -v matugen` 成功时直接继续。
2. 未找到时显示 `[y/N]` 提示。仅大小写不敏感的 `y` 或 `yes` 表示同意；空输入、其他输入以及没有交互终端都报错并退出。
3. 按下列顺序探测包管理器并执行首个匹配流程：
   - Arch 系：`pacman` 存在且 `/etc/pacman.conf` 存在时，运行 `pacman -S --needed --noconfirm matugen`。
   - Fedora 系：`dnf` 存在时，运行 `dnf -y install matugen`。
   - Debian 系：`apt-get` 存在时，先运行 `apt-get update` 和 `apt-get install -y cargo`，再以当前用户运行 `cargo install --root "$HOME/.local" matugen`。这会把可执行文件安装到本项目已使用的 `~/.local/bin`。
4. 系统级包管理命令在 root 用户下直接执行；其他用户通过 `sudo` 执行。需要提权但没有 `sudo` 时给出明确错误。
5. 安装命令完成后再次验证 `matugen`。验证同时接受 `PATH` 中的命令和 Debian 流程产生的 `~/.local/bin/matugen`。验证失败时退出。

脚本不会解析 `/etc/os-release`。这种基于实际工具的探测能直接覆盖 Ubuntu、Linux Mint、CachyOS、Manjaro 等衍生发行版。`pacman` 分支额外检查 `/etc/pacman.conf`，避免在 Debian 系统中将同名迷宫游戏误认为包管理器。

## 代码结构

所有逻辑保留在 `install.sh`，拆成职责单一的 shell 函数：

- `matugen_available`：判断依赖是否可执行。
- `confirm_matugen_install`：从 `/dev/tty` 读取安全默认值为否的确认。
- `run_as_root`：根据 EUID 选择直接运行或 `sudo`。
- `detect_package_manager`：返回 `pacman`、`dnf` 或 `apt-get`。
- `install_matugen`：分派三种安装流程。
- `ensure_matugen`：串联检查、确认、安装和安装后验证。

为测试函数而不触发真实安装，脚本入口会整理为 `main`，仅在直接执行 `install.sh` 时调用；被测试脚本 `source` 时只加载函数。生产环境中的默认行为保持不变。

## 错误处理

- 用户拒绝或无交互终端：说明 `matugen` 是必要依赖并返回非零状态。
- 找不到受支持的包管理器：列出当前支持的三类工具并退出。
- 包管理器、Cargo 或提权命令失败：保留原命令的非零状态，输出安装失败信息并退出。
- Debian 安装 Cargo 后仍没有 `cargo`：给出明确错误，不尝试继续。
- 安装结束后找不到 `matugen`：报验证失败并退出。

所有失败都发生在 `install_files`、符号链接和桌面入口写入之前，因此不会产生新的半安装状态。

## 现有依赖提示

现有 `check_dependencies` 继续对 Python、GTK、libadwaita 和 gsettings 做非阻断提示，但不再把 `matugen` 作为普通缺失项，也不再打印仅适用于 Arch 的统一安装命令。

## 测试与文档

新增安装脚本测试，通过临时目录中的伪命令和可覆盖的系统路径隔离真实主机状态，覆盖：

- 已安装 `matugen` 时不询问、不调用包管理器；
- 用户拒绝、空输入或无交互终端时退出；
- `pacman`、`dnf`、`apt-get` 三种命令分派；
- 包管理器探测顺序与 `pacman.conf` 防误判；
- 无支持包管理器、无 `sudo`、安装命令失败；
- 安装后验证成功与失败。

README 的 Requirements 和 Install 部分同步说明自动检查范围、三类安装方式，以及 Debian 系会通过 APT 安装 Cargo 后编译到 `~/.local/bin`。
