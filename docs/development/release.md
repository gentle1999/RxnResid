# 发布与凭据

## 发布边界

本模板采用内网优先发布流程：

- Gitea 是开发、代码评审、CI 和内部包发布的事实主仓库。
- GitHub 只接收来自 Gitea 的单向镜像。
- 外部公开发布由 GitHub mirror 在同步到稳定 tag 后完成。

日常开发不要把 GitHub 当作写入 remote。分支、tag 和 release 都从 Gitea 发起。

## 版本策略

项目版本由 `hatch-vcs` 从 Git tag 推导。`pyproject.toml` 中的 `dynamic = ["version"]` 和 `[tool.hatch.version] source = "vcs"` 表示不手写版本号。

推荐 tag 约定：

- 稳定版本：`v0.1.0`、`v1.2.3`
- 候选版本：`v0.1.0rc1`
- 开发版本：不手动打 `.dev` tag，日常 `main` 分支快照由 SCM 版本推导

`main` 分支推送用于内部开发快照。稳定公开发布应使用干净的 `vX.Y.Z` tag。候选版本可以在内网验证，但不应作为公共 PyPI 稳定发布入口。

## Gitea 凭据

生成后的 `.gitea/workflows/ci.yaml` 会在 `main` 分支 push 和 `v*` tag push 时构建包，并发布到内网 Gitea PyPI registry。

需要在 Gitea 仓库 secrets 中配置：

- `OWNER`：用于发布包的 Gitea 用户名或机器人账号。
- `PASSWORD`：对应的密码或访问令牌。建议使用最小权限的包发布令牌。

包发布地址由 workflow 拼接为：

```text
<GITEA_HOST>/api/packages/<repository-owner>/pypi
```

初始化时 `make init` 会把 `pyproject.toml` 中的内部包索引替换为当前 Gitea 用户或组织。

## GitHub/PyPI 凭据

GitHub mirror workflow 使用 PyPI Trusted Publishing，不应在 GitHub secrets 中保存 PyPI 密码。

外部发布前需要确认：

- GitHub mirror 仓库已同步 Gitea tag。
- PyPI 项目配置了 Trusted Publisher。
- GitHub Actions environment 名称为 `pypi`。
- GitHub workflow 的 `deploy` job 保留 `id-token: write` 权限。

如果项目不需要发布到公共 PyPI，应删除或替换 `.templates/ci/github-ci.yaml.tpl` 中的 `deploy` job，并重新运行 `make configure-compatibility` 生成 workflow。

## 本地验证

`make act-ci` 只验证 GitHub mirror workflow 的 Linux 路径。`deploy` job 只在 tag push 条件下运行，不应通过本地 `act` 发布包。

发布前建议顺序：

```bash
make check
make test
make docs-check
make build
make act-dry-run
```

涉及 macOS、Windows 或真实异构 runner 的行为，以 Gitea runner 和 GitHub mirror CI 的结果为准。
