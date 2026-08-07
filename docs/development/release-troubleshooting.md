# 内部发布排错

## 快速定位

内部发布失败时，先确认失败发生在哪个阶段：

- `checkout` 失败：通常是内网 action 地址、仓库权限或 runner 网络问题。
- `uv` 安装失败：通常是内网 PyPI 镜像、runner 自带 Python/pip 或 runner 网络问题。
- `uv sync` / `uv build` 失败：通常是依赖解析、lock 文件、构建后端或包元数据问题。
- `uv publish` 失败：通常是 Gitea package registry 权限、`OWNER`/`PASSWORD` secrets 或发布 URL 问题。
- GitHub mirror 发布失败：通常是 tag 未同步、Trusted Publishing 未配置或 GitHub environment 权限问题。

建议先打开失败 job 的完整日志，确认最后一个失败 step，而不是从最终状态判断。

## 内网配置不一致

内网基础设施默认值集中在：

```text
.templates/config/internal.env
```

如果 Gitea 地址、内网 PyPI 镜像、Python 下载镜像、内网 action 地址或 runner 默认标签发生变化，先修改这个文件，再重新生成项目配置或 CI：

```bash
make configure-project
make configure-compatibility
```

维护模板本身时，修改后运行：

```bash
make template-check
```

不要只改生成后的 `.gitea/workflows/ci.yaml`，后续配置流程会覆盖它。

注意：为了同时兼容 Makefile 和 POSIX shell，`internal.env` 中不要使用 `${OTHER_VAR}` 这类嵌套变量引用。需要派生 URL 时请直接写完整值，例如同时修改 `INTERNAL_GITEA_HOST` 和 `GITEA_CHECKOUT_ACTION`。

## Gitea Secrets

发布到内网 Gitea package registry 需要仓库 secrets：

- `OWNER`：发布账号或机器人账号。
- `PASSWORD`：对应密码或访问令牌。

排查点：

- secret 名称必须完全匹配，大小写敏感。
- token 需要有包发布权限。
- 发布账号需要能访问目标仓库或目标组织的 package registry。
- 如果仓库从个人空间迁移到组织空间，确认 secrets 和 package 权限也已迁移。

`uv publish` 返回 401/403 时，优先检查这部分。

## 发布地址

Gitea workflow 默认发布到：

```text
<GITEA_HOST>/api/packages/<repository-owner>/pypi
```

如果项目希望发布到固定组织而不是 `github.repository_owner`，需要调整 `.templates/ci/gitea-ci.yaml.tpl` 中的 `PUBLISH_URL` 生成逻辑，然后重新运行 `make configure-compatibility`。

## 版本问题

项目使用 `hatch-vcs` 从 Git 历史和 tag 推导版本。发布 job checkout 时必须保留完整历史：

```yaml
fetch-depth: 0
```

常见问题：

- 构建版本为 `0.0.0`：通常是没有 tag 或 checkout 历史不完整。
- 稳定发布版本不符合预期：检查 tag 是否是 `vX.Y.Z` 格式。
- 同一版本重复发布失败：Gitea/PyPI registry 通常不允许覆盖同名同版本包。需要提升版本或删除错误发布产物。

## Runner 与架构

Gitea workflow 只应包含有真实内网 runner 的组合。默认映射来自 `.templates/config/internal.env`：

```text
INTERNAL_DEFAULT_GITEA_TARGETS=ubuntu-latest/x86_64=ubuntu-latest,ubuntu-latest/aarch64=linux-arm64,macos-latest/aarch64=macos-arm64
```

如果 job 长时间排队或提示没有 runner：

- 检查 Gitea runner 标签是否与 `runs-on` 完全一致。
- 检查 runner 是否在线、空闲并能访问仓库。
- 使用 `TARGETS="platform/arch=runner-label"` 重新生成 CI。
- 不要把没有实际 runner 的 Windows 或 macOS x86_64 组合加入 Gitea workflow。

## 镜像源与网络

依赖安装失败时，检查：

- `INTERNAL_PYPI_INDEX` 是否可从 runner 访问。
- `PYTHON_INSTALL_MIRROR` 是否可从 runner 访问。
- runner 是否需要 HTTP/HTTPS proxy。
- 私有依赖是否已发布到内部 Gitea package registry。

如果只有 `act` 本地验证失败，而 Gitea/GitHub CI 正常，优先检查本地 Docker、代理和 `.secrets`/`.vars` 配置。

## GitHub Mirror 发布

公开发布失败时，先确认 GitHub mirror 是否已经收到 Gitea tag。

排查点：

- GitHub 仓库是否同步了 `refs/tags/v*`。
- PyPI 项目是否配置 Trusted Publisher。
- GitHub environment 是否名为 `pypi`。
- `deploy` job 是否保留 `id-token: write`。
- release tag 是否来自 Gitea，而不是直接在 GitHub 手动创建。

内部项目如果不发布到公共 PyPI，应删除或替换 GitHub workflow 的 `deploy` job 模板。
