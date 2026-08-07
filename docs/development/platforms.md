# 平台与架构

## 支持矩阵

模板把“项目声明支持范围”和“内网实际 runner”分开维护。

`PLATFORMS` 和 `ARCHES` 表示项目声明支持的完整矩阵。默认值：

```text
PLATFORMS="ubuntu-latest macos-latest windows-latest"
ARCHES="x86_64 aarch64"
```

GitHub mirror workflow 会按完整矩阵生成，用于公开发布前的完整验证。

`TARGETS` 表示内网 Gitea 实际 runner 映射。默认值：

```text
ubuntu-latest/x86_64=ubuntu-latest
ubuntu-latest/aarch64=linux-arm64
macos-latest/aarch64=macos-arm64
```

Gitea workflow 只展开这些有实际 runner 的组合。

## 调整方式

从默认完整矩阵中移除不支持的平台或架构：

```bash
make configure-compatibility REMOVE_PLATFORMS="windows-latest"
make configure-compatibility REMOVE_ARCHES="aarch64"
```

显式指定内网 runner 映射：

```bash
make configure-compatibility TARGETS="ubuntu-latest/x86_64=ubuntu-latest ubuntu-latest/aarch64=linux-arm64 macos-latest/aarch64=macos-arm64"
```

新增内网 runner 后，可以增加对应 `TARGETS`。没有内网 runner 的组合不应出现在 Gitea workflow 中。

## 本地开发

Linux 和 macOS 可直接安装 `make`、`git`、`uv` 后运行模板命令。

Windows 本地开发建议使用以下方式之一：

- WSL2 + Ubuntu，按 Linux 流程安装 `make` 和 `git`。
- MSYS2 或 Git Bash，确保 `make`、`sh`、`git`、`uv` 在 `PATH` 中。

模板配置脚本使用 POSIX shell 编写，并保持在 `sh`、`bash` 和 `zsh` 下可执行。PowerShell 可以作为外层终端，但执行模板配置仍依赖 `sh`。
