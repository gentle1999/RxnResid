# 工作流

## 日常开发

1. 从内网 Gitea 拉取最新代码。
2. 首次进入一个已经初始化过的项目时运行 `make setup`；本地 `.venv` 损坏时运行 `make rebuild-env`。
3. 修改代码和文档。
4. 运行 `make check` 和 `make test`。
5. 提交并推送到 Gitea。
6. 通过 Gitea Actions 完成内部验证和发布。

`make init` 只用于从模板创建真实项目的首次初始化。维护者日常重建环境不要运行 `make init`，避免重新进入项目身份、兼容性和 Docker 配置流程。

## CI 生成

模板仓库默认不提交 `.gitea/workflows` 或 `.github/workflows`。运行 `make init` 或 `make configure-compatibility` 后，会根据 `.templates/ci` 生成实际 workflow。

`PLATFORMS`/`ARCHES` 表示项目声明支持的完整平台和架构矩阵，GitHub mirror workflow 会按完整矩阵生成。`TARGETS` 表示内网 Gitea 实际 runner 映射，Gitea workflow 只会展开当前存在 runner 的组合。

默认内网 Gitea CI 目标按当前可用 runner 配置：

- `ubuntu-latest/x86_64=ubuntu-latest`
- `ubuntu-latest/aarch64=linux-arm64`
- `macos-latest/aarch64=macos-arm64`

Windows 和 macOS x86_64 等没有内网 runner 的组合会保留在 GitHub mirror workflow 的完整支持矩阵中，但不会出现在 Gitea workflow 中。需要调整 runner 标签或新增内网目标时，使用 `TARGETS="platform/arch=runner-label"` 重新运行 `make configure-compatibility`。

## Docker 生成

模板仓库默认不提交根目录 Docker 配置。需要 Docker 时运行：

```bash
make docker-restore
```
