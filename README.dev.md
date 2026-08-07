# 开发者指南

[English reference](i18n/README.en.md)

## 快速入口

这个仓库是项目模板。先选你现在要做的事；不确定时先运行 `make help`。

| 场景 | 下一步 |
| --- | --- |
| 创建真实项目 | 在 Gitea 点击 **Use this template**，克隆新仓库后运行 `make init` |
| 预览模板会生成什么 | 运行 `make init-demo`，它只写入临时目录 |
| 维护模板本身 | 修改 `.templates/`、`scripts/`、`docs/`、`.codex/skills/` 或 `Makefile`，然后运行 `make template-check` |
| 维护已初始化项目 | 克隆后运行 `make setup`，不要再次运行 `make init` |

模板仓库根目录不提交生成型项目文件，包括 `README.md`、`pyproject.toml`、`mkdocs.yml`、workflow、Docker 文件和 `uv.lock`。这些文件只应在从模板创建出来的真实项目中出现。

### 最短路径

1. 在 Gitea 页面点击 **Use this template**，创建新仓库。
2. 克隆新仓库到本地。
3. 运行：

```bash
make init
source .venv/bin/activate
make check
make test
```

### 安全预览

```bash
make init-demo
```

### 模板维护

```bash
make template-check
```

`make info` 会显示当前模板/项目配置，`make help` 会按当前仓库状态给出常用命令。

本文档面向使用此项目模板的开发者，旨在说明构建高质量 Python 应用的理念、工具和工作流。

## 核心技术栈

本模板构建于一系列现代、高效的工具基础之上：

- **`uv`**: 一个速度极快的 Python 包安装器和解析器，用于所有依赖管理、环境创建和任务执行。
- **`Ruff`**: 一个速度极快的 Python Linter 和代码格式化工具。
- **`Mypy`**: 事实上的静态类型检查标准。
- **`Pytest`**: 用于编写健壮、可扩展测试的框架。
- **`MkDocs Material`**: 用于维护项目文档站点，中文作为默认文档语言。
- **`Hatch`**: 作为项目构建后端，版本控制由 `hatch-vcs` 管理。
- **Gitea Actions 和 GitHub Actions**: Gitea 是内网开发和 CI/CD 的主入口；GitHub Actions 只在公开镜像仓库中处理 tag 触发的外部发布。

## 🚀 快速上手

请遵循以下步骤在私有 Gitea 实例上启动您的新项目。

### 0. 本机前置条件

开始前，本机至少需要安装 `make` 和 `git`。`make` 是此模板的初始化入口；没有 `make` 时无法执行 `make init`。`git` 用于克隆仓库和后续版本管理。

`uv` 会在 `make init` 中缺失时尝试自动安装。如果内网环境无法访问安装脚本，请先按照内部工具镜像或平台标准文档安装 `uv`。

常见平台安装示例：

```bash
# Debian/Ubuntu
sudo apt-get install make git

# macOS (Homebrew)
brew install make git
```

### 1. 从 Gitea 模板创建项目

您应该直接在私有的 Gitea 实例上从此模板创建一个新仓库，而不是克隆本项目。

1. 在 Gitea 上打开此模板仓库的页面。
2. 点击 **"使用此模板"** (Use this template) 按钮。
3. 填写您新仓库的详细信息并创建它。
4. 将您 **新创建的仓库** 克隆到本地。

```bash
# 克隆您从模板创建的新仓库
git clone <your-new-repository-url>
cd <your-new-repository>
```

### 2. 初始化并激活环境

使用这个命令来初始化您的开发环境。默认是交互式流程；在自动化脚本或批量创建仓库时，也可以通过 Make 变量传入初始化参数。

```bash
make init

# 非交互示例
make init PACKAGE_NAME=demo_app PROJECT_TITLE="Demo App" PROJECT_DESCRIPTION="Internal demo service." GITEA_USER=team AUTHOR_NAME="Team Maintainers" AUTHOR_EMAIL=team@example.com PYTHON_MIN=3.11 PYTHON_MAX=3.13 PLATFORMS="ubuntu-latest macos-latest windows-latest" ARCHES="x86_64 aarch64" TARGETS="ubuntu-latest/x86_64=ubuntu-latest ubuntu-latest/aarch64=linux-arm64 macos-latest/aarch64=macos-arm64" DOCKER=add
```

这个命令会通过以下步骤配置您的项目：

1. **检查 `uv`**：如果您系统中没有 `uv`，它将被自动安装。
2. **配置项目名称**：它会提示输入新的 Python 包名，并自动更新 `src/` 目录、`README.md`、`pyproject.toml`、`Makefile`、CLI 入口、测试、文档和展示名称。
3. **渲染项目元数据**：`README.md`、`pyproject.toml` 和 `mkdocs.yml` 会从 `.templates/project` 生成，并在初始化时填入包名、项目标题、项目描述、作者信息、内网 Gitea 地址和仓库路径。非交互模式可以传入 `PROJECT_TITLE`、`PROJECT_DESCRIPTION`、`AUTHOR_NAME`、`AUTHOR_EMAIL` 和 `GITEA_HOST`。
4. **配置 Gitea 所有者**：它会提示是否把 `YOUR_USER` 占位符替换为你的 Gitea 用户名或组织名。保留 `YOUR_USER` 也可以，适合继续作为模板维护。
5. **配置兼容范围**：它会请求您输入最低/最高支持的 Python 版本。`PLATFORMS`/`ARCHES` 控制完整支持矩阵，默认覆盖 Linux、macOS、Windows 以及 `x86_64`/`aarch64`，用于生成 GitHub mirror workflow 和项目元数据。`TARGETS` 控制内网 Gitea runner 映射，默认只启用当前实际存在 runner 的 `ubuntu-latest/x86_64=ubuntu-latest`、`ubuntu-latest/aarch64=linux-arm64` 和 `macos-latest/aarch64=macos-arm64`。
6. **生成兼容性配置**：默认仓库不预置正式 `README.md`、`pyproject.toml`、`mkdocs.yml`、`.python-version`、`uv.lock`、`.gitea/workflows` 或 `.github/workflows`。初始化会先从 `.templates/project` 生成项目配置，再把最低 Python 版本写入 `.python-version`，并更新 `pyproject.toml` 的 `requires-python`、Python/OS classifiers、Ruff target 和 Docker 模板基础镜像。CI workflow 会在这一步从 `.templates/ci` 中的模板按所选 Python 版本、平台和架构生成。
7. **配置 Docker**：默认仓库不预置 `Dockerfile`、`compose.yaml` 或 `.dockerignore`。初始化会询问是否启用 Docker；选择启用时才会从 `.templates/docker` 生成 Docker 配置，并把 Docker 检查加入生成后的 CI。
8. **锁定并同步依赖**：它会更新 `uv.lock`，创建虚拟环境，并安装开发依赖。
9. **运行首次校验**：它会运行格式检查、lint、类型检查、测试和 CLI smoke test。

包名请使用下划线（`_`），而不是连字符（`-`）。内网 Gitea 地址默认来自 `.templates/config/internal.env` 中的 `INTERNAL_GITEA_HOST`。

最后，激活环境以开始工作：

```bash
source .venv/bin/activate
```

现在您可以开始编码了！

### 3. 运行示例 CLI

模板内置了一个最小命令行入口，因此新仓库创建后可以直接运行。`make init` 会把入口命令同步改成新的包名。

```bash
uv run myrepositorytemplate
uv run myrepositorytemplate --version
```

### 4. 维护者重建本地环境

项目完成初始化并提交生成后的 `pyproject.toml`、`.python-version`、`uv.lock`、README、文档配置和 CI 后，后续维护者不应该再运行 `make init`。`make init` 是从模板创建真实项目时的一次性入口，会重新进入项目身份、兼容性和 Docker 配置流程。

维护者克隆已经初始化过的项目后，使用以下命令重建本地开发环境：

```bash
make setup
source .venv/bin/activate
```

`make setup` 只做本地环境恢复：

1. 检查并安装 `uv`。
2. 如果存在 `.python-version`，通过 `uv python install` 安装项目钉住的 Python。
3. 如果存在 `uv.lock`，使用 `uv sync --frozen --all-extras --dev` 按锁文件同步环境。
4. 如果缺少 `uv.lock`，退回到 `uv sync --all-extras --dev`，由当前 `pyproject.toml` 创建或更新锁文件。

当本地虚拟环境损坏、Python 版本切换或依赖状态异常时，使用：

```bash
make rebuild-env
```

这个命令会删除 `.venv`，然后重新执行 `make setup`。它不会修改项目元数据、CI workflow、Docker 配置或兼容性矩阵。

---

## 📖 命令参考手册

所有常见任务都通过 `make` 命令管理。这是一份完整的参考。

### 📦 依赖管理

使用这些命令来管理您项目的依赖关系。

- `make init` 或 `make install`: 设置项目的主要初始化命令。默认交互式运行，也支持 `PACKAGE_NAME`、`PROJECT_TITLE`、`PROJECT_DESCRIPTION`、`AUTHOR_NAME`、`AUTHOR_EMAIL`、`GITEA_HOST`、`GITEA_USER`、`PYTHON_MIN`、`PYTHON_MAX`、`PLATFORMS`、`ARCHES`、`TARGETS`、`DOCKER` 变量用于非交互初始化。`PYTHON_VERSION` 或 `PYTHON` 会作为 `PYTHON_MIN` 的兼容别名，`DOCKER` 支持 `add` 或 `remove`，默认交互选项是不启用 Docker。
- `make init-demo`: 在临时目录中生成一个 `demo_app` 示例项目，只用于预览生成结果，不修改当前模板仓库。
- `make install-uv`: 一个辅助命令，用于安装 `uv` 包管理器。如果需要，`make init` 会自动调用它。
- `make doctor`: 检查本地开发必需工具是否可用。
- `make setup`: 维护者重建本地环境的标准入口。它读取已经提交的项目配置，不重新生成项目身份、CI 或 Docker 文件。
- `make rebuild-env`: 删除 `.venv` 后运行 `make setup`，用于修复损坏的虚拟环境或切换 Python 版本后的环境重建。
- `make configure-project`: 生成正式 `README.md`、`pyproject.toml` 和 `mkdocs.yml`，并配置包名、项目标题、项目描述、作者信息、Gitea 地址和 Gitea 所有者。通常不需要单独运行，因为 `make init` 会自动调用。
- `make configure-user`: 只配置 Gitea 所有者。保留给需要单独调整 owner 的场景。
- `make configure-compatibility`: 配置支持的 Python 版本范围、CI 平台范围和 CPU 架构范围，并同步更新项目元数据、CI 目标和 Docker 模板。`PLATFORMS`/`ARCHES` 表示项目声明支持的完整矩阵，默认是 Linux、macOS、Windows 以及 `x86_64`/`aarch64`，GitHub mirror workflow 会按这个完整矩阵生成。`TARGETS` 表示 Gitea 内网实际 runner 映射，默认只展开当前有 runner 的 Linux x86_64、Linux aarch64 和 macOS aarch64；没有实际 runner 的组合会从 Gitea workflow 中排除。非交互模式可用 `TARGETS="ubuntu-latest/x86_64=ubuntu-latest ubuntu-latest/aarch64=linux-arm64 macos-latest/aarch64=macos-arm64"` 显式指定内网 runner 标签。CI 的 workflow 骨架和重复 job 片段位于 `.templates/ci`，实际 `.gitea/workflows/ci.yaml` 和 `.github/workflows/ci.yaml` 是生成结果。
- `make configure-docker`: 配置是否生成 Docker 集成。交互模式询问是否启用；非交互模式可用 `DOCKER=add` 或 `DOCKER=remove`。兼容旧用法时，`DOCKER=keep` 会被视为 `add`。
- `make pin-python`: `make configure-compatibility` 的兼容别名。
- `make sync`: 当您手动修改了 `pyproject.toml` 或拉取了新变更时使用。它会根据 `uv.lock` 文件同步虚拟环境。
- `make sync-frozen`: 在不修改 `uv.lock` 的情况下同步虚拟环境。
- `make lock`: 更新 `uv.lock`。
- `make lock-check`: 检查 `uv.lock` 是否与当前配置一致。
- `make update`: 根据 `pyproject.toml` 的规则，将所有依赖项升级到允许的最新版本，并更新 `uv.lock` 文件。
- `make tree`: 显示完整的依赖关系树，用于调试依赖冲突。
- `make audit`: 可选依赖漏洞审计，默认通过 `uvx pip-audit` 执行。它不属于 `make check`，因为漏洞库访问和误报处理通常依赖团队安全流程。可通过 `AUDIT_ARGS="--strict"` 传参，或在内网项目中替换为统一安全扫描入口。

要添加或移除依赖，请直接使用 `uv`：

- `uv add <package>`: 添加一个新的主依赖。
- `uv add --dev <package>`: 添加一个新的开发依赖。
- `uv remove <package>`: 移除一个依赖。

维护脚本位于 `scripts/` 目录，并使用 shell 编写。`Makefile` 只保留稳定命令入口，较长逻辑下沉到脚本中：`scripts/configure_project.sh` 渲染项目身份，`scripts/configure_compatibility.sh` 生成兼容性和 CI，`scripts/manage_docker.sh` 管理 Docker 集成，`scripts/init_demo.sh` 生成临时预览，`scripts/template_check.sh` 执行模板校验，`scripts/check_actions.sh` 检查 action 版本，`scripts/check_compatibility_helpers.sh` 校验兼容性 helper 的基础行为。共享逻辑放在 `scripts/lib/`。这些脚本不依赖 Python 虚拟环境，可在 `uv sync` 之前运行；脚本语法保持在 `sh`、`bash` 和 `zsh` 下可执行。

项目配置模板位于 `.templates/project`，包括 `README.md`、`pyproject.toml` 和 `mkdocs.yml`。默认模板仓库不提交根目录正式项目配置，运行 `make init`、`make configure-project` 或 `make configure-compatibility` 后才会生成。`README.dev.md` 是模板自身的基础开发指南，会保留在根目录。对于从模板创建出来的真实项目，这些生成后的正式配置通常应该提交到项目仓库。

CI 模板位于 `.templates/ci`。默认模板仓库不提交 `.gitea/workflows` 或 `.github/workflows`，运行 `make init` 或 `make configure-compatibility` 后才会生成它们。如果要调整 Gitea/GitHub workflow 的步骤、内网 action 地址、镜像源或 Docker 检查，请优先修改模板，然后运行 `make configure-compatibility` 重新生成 workflow。直接修改 `.gitea/workflows/ci.yaml` 或 `.github/workflows/ci.yaml` 中展开出来的组合，后续初始化或兼容性配置会覆盖这些修改。

### 🏗️ 内网基础设施配置

内网基础设施默认值集中在 `.templates/config/internal.env`。这个文件同时兼容 Makefile `include` 和 POSIX shell `.`，因此初始化 Python 环境之前也能读取。

当前集中管理的内容包括：

- `INTERNAL_GITEA_HOST`：内网 Gitea 地址。
- `INTERNAL_PYPI_INDEX`：内网 PyPI 镜像。
- `PUBLIC_PYPI_INDEX` / `ACT_PYPI_INDEX`：GitHub mirror 和本地 `act` 使用的 PyPI 源。
- `PYTHON_INSTALL_MIRROR`：`uv python install` 使用的 Python 下载镜像。
- `GITEA_CHECKOUT_ACTION`：内网 checkout action 地址。Gitea CI 会通过 `INTERNAL_PYPI_INDEX` 安装 `uv`，不依赖 `setup-uv` action。
- `GITHUB_CHECKOUT_ACTION` / `GITHUB_SETUP_UV_ACTION` / `GITHUB_RELEASE_ACTION`：GitHub mirror workflow 使用的 action 版本。
- `INTERNAL_DEFAULT_GITEA_TARGETS`、`INTERNAL_DEFAULT_PLATFORMS`、`INTERNAL_DEFAULT_ARCHES`：默认平台、架构和 Gitea runner 映射。

为了兼容 Makefile 和 POSIX shell，`internal.env` 中不要写 `${OTHER_VAR}` 这类嵌套变量引用；需要派生值时请直接写完整 URL。

如果内网地址、镜像源或 runner 标签变化，优先修改 `.templates/config/internal.env`，然后重新运行：

```bash
make configure-project
make configure-compatibility
```

维护模板本身时，修改后运行 `make template-check`。不要只修改生成后的 workflow 或 `pyproject.toml`。

### 🧰 模板维护

这些命令主要面向模板维护者。真实项目开发者通常只需要 `make setup`、`make check`、`make test` 和发布相关命令。

- `make template-check`: 验证模板仓库结构、shell 脚本语法、Makefile 关键目标、内置 Codex skill、根目录生成物清理状态，以及临时目录中的项目配置和 CI 生成结果。它也会检查生成后的 workflow 是否包含关键 action、镜像源、发布步骤和 Gitea/GitHub 矩阵差异。
- `make action-check`: 通过上游 Git tag 检查 CI action 版本是否落后。该命令需要网络访问，适合升级或定期维护 CI 模板时运行。
- `make skill-check`: 验证 `.codex/skills/python-internal-template` 的 skill 结构。如果本机存在 Codex 系统 skill validator，会优先使用 validator。
- `make skill-install`: 将内置 skill 安装到 `$CODEX_HOME/skills/` 或 `~/.codex/skills/`，便于 agent 在其它会话中自动发现。

维护模板时请遵循：

1. 修改 `.templates/*`、`scripts/*` 或 `Makefile`，不要直接提交生成后的根目录项目文件。
2. 中文主版本先更新 `README.dev.md`，再同步 `docs/` 中长期有效的页面；`i18n/README.en.md` 保持英文简版参考，只同步命令、配置项、兼容性和发布语义，不要求逐段翻译中文全文。
3. 提交前运行 `make template-check`，再用 `git status --short` 确认没有误生成 `README.md`、`pyproject.toml`、`mkdocs.yml`、workflow 或 Docker 根目录文件。

脚本共享配置位于 `scripts/lib/internal_config.sh`，兼容性解析位于 `scripts/lib/compatibility.sh`，CI 渲染位于 `scripts/lib/ci_render.sh`，通用渲染 helper 位于 `scripts/lib/render.sh`。新增内部 host、镜像源、action 版本或模板占位符时，优先更新 `.templates/config/internal.env` 和共享 helper，再由生成脚本复用。

### 🎨 代码质量

确保您的代码保持整洁、格式统一且类型安全。

- `make format`: 使用 `Ruff Formatter` 格式化项目中的所有代码。
- `make format-check`: 只检查格式，不修改文件。`make check` 使用这个命令。
- `make lint`: 使用 `Ruff Linter` 检查所有代码，不修改文件。
- `make lint-fix`: 使用 `Ruff Linter` 检查代码，并应用安全的自动修复。
- `make type-check`: 使用配置的包名运行 `Mypy` 静态类型检查。
- `make check`: 一体化的质量检查命令。它会依次运行 `format-check`、`lint` 和 `type-check`。**请在每次提交前运行此命令！**

### 🧪 测试

运行您的测试套件并检查代码覆盖率。

- `make test`: 使用 `pytest` 执行完整的测试套件。
- `make test-cov`: 运行测试并生成一份详细的 HTML 格式的覆盖率报告。随后，它会自动在您的默认浏览器中打开该报告供您查阅。
- `make smoke`: 运行一次已安装的 CLI，用于快速发现入口点损坏。

### 📚 文档

本模板使用 MkDocs Material 维护项目文档。`README.md` 由 `make init` 从 `.templates/project/README.md` 生成，只保留真实项目的快速入口和最小说明；长期维护的使用说明、开发流程、接口参考和运维手册应放在 `docs/` 中。

- `make docs-serve`: 在本地启动文档预览服务，默认地址为 `http://127.0.0.1:8000`。
- `make docs-build`: 构建静态文档站点到 `site/`。
- `make docs-check`: 使用严格模式构建文档，适合在提交前检查链接、导航和配置问题。

推荐文档布局：

```text
docs/
├── index.md                  # 项目文档首页：项目定位、快速入口、读者导航
├── development/              # 面向开发者
│   ├── index.md
│   ├── environment.md        # 本地环境、依赖、工具
│   ├── workflow.md           # 分支、测试、CI、发布流程
│   ├── platforms.md          # Python、系统、架构和 runner 映射
│   ├── release.md            # 发布策略、版本和凭据
│   ├── release-troubleshooting.md # 内部发布失败排错
│   ├── security.md           # 依赖审计和凭据处理
│   ├── contributing.md       # 贡献约定
│   └── template-maintenance.md # 模板维护检查清单
├── user-guide/               # 面向使用者
│   └── index.md              # 安装、配置、常见场景
├── reference/                # 精确查询材料
│   └── index.md              # CLI、配置项、API、错误码
├── operations/               # 面向维护和部署
│   └── deployment.md
└── adr/                      # 架构决策记录
    └── index.md
```

写作建议：

- 文档首页回答“这个项目是什么、适合谁、从哪里开始”。
- 用户指南按任务组织，例如安装、配置、运行、排错，不按源码文件组织。
- 参考文档追求完整和稳定，适合放 CLI 参数、配置项、API、环境变量和数据格式。
- 开发文档记录本地环境、测试策略、CI 生成逻辑、代码风格和发布流程。
- ADR 只记录影响较大且未来需要追溯的技术决策。

新增或移动文档页面后，需要同步更新 `mkdocs.yml` 的 `nav`。

内部发布失败时，优先阅读 `docs/development/release-troubleshooting.md`。这份文档按 checkout、uv 安装、依赖安装、构建、`uv publish`、GitHub mirror 发布等阶段列出了常见排查点。

### 💻 平台开发提示

Linux 和 macOS 可以直接安装 `make`、`git`、`uv` 后运行模板命令。macOS Apple Silicon 是当前内网有真实 runner 的 macOS 路径；macOS x86_64 仍可通过 GitHub mirror workflow 验证。

Windows 本地开发建议优先使用 WSL2 + Ubuntu。也可以使用 MSYS2 或 Git Bash，但必须确保 `make`、`sh`、`git` 和 `uv` 都在 `PATH` 中。配置脚本是 shell 脚本，PowerShell 可以作为外层终端，但不能替代脚本执行所需的 `sh`。

### 🧪 本地 CI 验证

本模板提供 `act` 本地验证入口，用来在提交前快速验证 GitHub mirror workflow 的 Linux 路径。`act` 基于 Docker 运行，所以需要先安装并启动 Docker。

- `make act-check`: 检查 `act` 和 Docker 是否可用。
- `make act-list`: 列出 `.github/workflows/ci.yaml` 中 `act` 可识别的任务。
- `make act-dry-run`: 使用 `act --dryrun` 验证 workflow、job 和矩阵筛选能否解析。
- `make act-ci`: 运行默认本地 CI 路径，默认是 `ubuntu-latest`、`x86_64`、最低支持 Python 版本。

本地执行时，`.github/workflows/ci.yaml` 会通过 `env.ACT == 'true'` 分支使用 `.templates/config/internal.env` 中的 `ACT_PYPI_INDEX` 安装 `uv` 和依赖，并使用 `PYTHON_INSTALL_MIRROR` 加速 Python 下载。正常 GitHub mirror 发布仍使用 `PUBLIC_PYPI_INDEX`。

可以通过 Make 变量选择本地验证目标：

```bash
make act-ci ACT_PLATFORM=ubuntu-latest ACT_ARCH=x86_64 ACT_PYTHON=3.11
make act-ci ACT_PLATFORM=ubuntu-latest ACT_ARCH=aarch64 ACT_PYTHON=3.12
```

`act` 主要适合验证 Linux 容器路径。macOS、Windows 和真实异构 runner 行为仍应以内网 Gitea runner 或 GitHub mirror CI 为准。

### 🏗️ 构建与发布

本模板采用内网优先发布策略。Gitea 是事实主仓库；GitHub 只接收来自 Gitea 的单向镜像，并在同步到 tag 后处理公开发布。

- `make build`: 一个安全的构建命令。它会首先运行 `make clean`、`make check` 和 `make test`。如果一切顺利，它会将项目构建为分发包（`.whl` 和 `.tar.gz`）并存放在 `dist/` 目录中。
- `make release`: 这是一个辅助命令，它 **本身不执行发布**。它会打印内网 Gitea release URL，并提醒后续由单向 GitHub 镜像处理公开发布。

版本号由 `hatch-vcs` 从 Git tag 推导，不在源码中手写。稳定版本使用 `vX.Y.Z`，例如 `v0.1.0`；候选版本可以使用 `v0.1.0rc1` 在内网验证。日常 `main` 分支推送用于内部开发快照，公开稳定发布应从 Gitea 创建干净的稳定 tag 或 release。

#### 内部开发快照 (Gitea)

- **触发条件**: 向 **私有 Gitea 仓库** 的 `main` 分支执行 `git push`。
- **最终结果**: Gitea Actions 自动构建一个开发快照版本 (例如 `0.1.0.dev5`) 并将其发布到 **内部 Gitea 包注册中心**。
- **配置要求**: 工作流使用内网镜像的 actions 和 Python 下载镜像。请将发布凭据配置到 `OWNER` 和 `PASSWORD` secrets。
- **包索引**: `pyproject.toml` 使用内部 Gitea 包仓库。`make init` 会把模板占位符替换为你的 Gitea 地址、用户名或组织名。
- **异构 runner**: Gitea Actions 的 `runs-on` 表达能力较弱，本模板会根据 `.templates/ci/gitea-test-job.yaml.tpl` 把 `TARGETS` 展开成静态 job。当前默认内网 runner 标签为 `ubuntu-latest`（Linux x86_64）、`linux-arm64`（Linux aarch64）和 `macos-arm64`（macOS Apple Silicon）。可用别名还包括 Linux x86 runner 上的 `ubuntu-22.04`、`ubuntu-20.04`、`ubuntu-18.04`，Linux arm runner 上的 `linux-aarch64`、`ubuntu-arm64`、`ubuntu-aarch64`、`ubuntu-24.04-arm64`、`ubuntu-24.04-aarch64`、`ubuntu-22.04-arm64`、`ubuntu-22.04-aarch64`，以及 macOS arm runner 上的 `macos-aarch64`、`darwin-arm64`、`darwin-aarch64`、`apple-silicon`。如果内网 runner 标签变化，请用 `TARGETS="platform/arch=runner-label"` 在初始化时指定。

#### 公开稳定版本 (GitHub 镜像)

- **触发条件**: 在 Gitea 创建 tag 或 release，例如 `v0.1.0`。单向镜像会把 tag 同步到 GitHub。
- **最终结果**: GitHub Actions 在同步后的 tag 上运行测试，构建稳定版本，将其发布到 **公共 PyPI**，并将软件包产物附加到 GitHub Release 页面。
- **注意**: 开发者日常不要把 GitHub 当作开发 remote。分支、提交和 release 都从 Gitea 发起。
- **本地验证**: GitHub workflow 额外提供 `workflow_dispatch`，用于 `make act-ci` 本地验证。`deploy` job 会跳过 `act` 环境，避免本地误发布。

GitHub 公开发布默认使用 PyPI Trusted Publishing。请在 PyPI 项目侧配置 Trusted Publisher，并保持 GitHub environment 名称为 `pypi`、`deploy` job 权限包含 `id-token: write`。不需要发布到公共 PyPI 的内部项目，应删除或替换 `.templates/ci/github-ci.yaml.tpl` 中的 `deploy` job，再重新运行 `make configure-compatibility`。

### 🧹 工具与维护

保持您的项目目录干净整洁。

- `make clean`: 移除构建产物和临时文件，例如 `__pycache__`、`.pytest_cache`、`build/`、`dist/` 和覆盖率报告。
- `make distclean`: 更彻底的清理。它会先执行 `make clean`，然后 **彻底删除虚拟环境目录 (`.venv`)**。`.python-version` 属于项目兼容性配置，会保留在仓库中。已初始化项目清理后用 `make setup` 重建环境，不要重新运行 `make init`。

### 🐳 Docker 集成

此模板默认不在项目根目录生成 Docker 配置。需要容器化时，可以在 `make init` 中选择启用 Docker，或稍后运行 `make docker-restore` 生成配置。

- `make docker-build`：构建你的应用程序的 Docker 镜像。这对于测试镜像构建过程或准备部署非常有用。

- `make docker-check`：不打 tag，仅检查 Docker 镜像能否成功构建。这个命令与 CI 中的 Docker 构建检查一致。

- `make docker-up`：使用 `docker compose` 构建（如果需要）并以分离模式启动你的应用程序服务。这是在开发过程中以 Docker 化环境运行应用程序的主要方式。

- `make docker-down`：停止并移除由 `docker compose up` 创建的容器、网络和卷。完成工作后使用此命令清理你的 Docker 环境。

- `make docker-remove`：移除生成出来的 `Dockerfile`、`compose.yaml`、`.dockerignore`，并从 Gitea 和 GitHub workflow 中移除 Docker 构建检查。被移除的文件会备份到 `.templates/docker/removed/`，该目录不提交。

- `make docker-restore`：优先从本地备份恢复 Docker 文件；如果没有备份，则从 `.templates/docker/` 生成，并把 Docker 构建检查重新加入已生成的 CI。

运行 `make docker-up` 后，你可以使用 `docker compose logs -f` 查看正在运行的容器日志。

Docker 支持是可选的。对于纯库项目或 notebook 项目，初始化时直接选择不启用即可。之后需要容器化时，再运行 `make docker-restore`。

## Lock 文件策略

模板仓库不提交根目录 `uv.lock`，真实项目运行 `make init` 后会生成。对于应用、服务或需要可复现开发环境的项目，建议提交生成后的 `uv.lock`。生成出来的 Dockerfile 使用 `uv sync --frozen`，CI 也依赖 lock 文件来保证可复现安装。

如果真实项目把它改造成可复用库，并决定不提交 `uv.lock`，也需要同步修改 Dockerfile 和 CI，避免继续使用 `--frozen`。

## 内网包索引

默认模板有意使用内网镜像和内部 Gitea 包仓库：

- 公共依赖镜像由 `.templates/config/internal.env` 中的 `INTERNAL_PYPI_INDEX` 控制。
- 内部包仓库模板：`<INTERNAL_GITEA_HOST>/api/packages/<gitea-user-or-org>/pypi/`

创建真实项目后，`make init` 会交互式配置拥有该仓库的 Gitea 用户名或组织名。

## Agent Skill

仓库内置了一份 Codex skill，路径为 `.codex/skills/python-internal-template/SKILL.md`。它用于指导 agent 正确使用和维护此模板，尤其是区分：

- `make init`：从模板创建真实项目时的一次性入口。
- `make setup` / `make rebuild-env`：维护者在已初始化项目中的本地环境重建入口。
- `.templates/*` 与生成文件的关系。
- Gitea runner 目标矩阵和 GitHub mirror 完整矩阵的差异。

如果需要让 Codex 自动发现它，运行：

```bash
make skill-install
```

该命令会安装到 `$CODEX_HOME/skills/`；如果没有设置 `CODEX_HOME`，则安装到 `~/.codex/skills/`。

修改 skill 后用以下命令验证结构：

```bash
make skill-check
```
