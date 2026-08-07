# 本地环境

## 基础要求

启动项目模板前，本机至少需要安装：

- `make`：模板初始化入口，没有它无法执行 `make init`。
- `git`：用于克隆仓库和版本管理。

`uv` 会在 `make init` 中缺失时尝试自动安装。如果内网环境无法访问安装脚本，请先按照内部工具镜像或平台标准文档安装 `uv`。

常见平台安装示例：

```bash
# Debian/Ubuntu
sudo apt-get install make git

# macOS (Homebrew)
brew install make git
```

初始化项目：

```bash
make init
```

## 维护者环境重建

`make init` 只用于从模板创建真实项目时的首次初始化。项目初始化完成并提交生成配置后，后续维护者克隆项目时应使用：

```bash
make setup
source .venv/bin/activate
```

`make setup` 会根据已提交的 `pyproject.toml`、`.python-version` 和 `uv.lock` 恢复本地开发环境，不会重新生成项目元数据、CI workflow 或 Docker 配置。

当本地 `.venv` 损坏、Python 版本切换或依赖状态异常时，使用：

```bash
make rebuild-env
```

该命令会删除 `.venv` 后重新执行 `make setup`。

同步依赖：

```bash
make sync
```

运行检查：

```bash
make check
make test
```

## 文档环境

文档工具由开发依赖提供。预览文档：

```bash
make docs-serve
```
