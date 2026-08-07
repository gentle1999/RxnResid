# Developer Guide

[Primary Chinese guide](../README.dev.md)

This is the secondary English reference. The primary development guide is the Chinese version.

Start with the quick entry section in [README.dev.md](../README.dev.md) when you are new to this repository. To preview generated output safely, run:

```bash
make init-demo
```

## Core Tech Stack

This template is built upon a foundation of modern, high-performance tools:

- **`uv`**: An extremely fast Python package installer and resolver, used for all dependency management, environment creation, and task execution.
- **`Ruff`**: An extremely fast Python linter and code formatter.
- **`Mypy`**: The standard for static type checking.
- **`Pytest`**: The framework for robust and scalable testing.
- **`MkDocs Material`**: The documentation site generator. Chinese is the default documentation language.
- **`Hatch`**: The build backend, with versioning managed by `hatch-vcs`.
- **Gitea Actions and GitHub Actions**: Gitea is the primary internal CI/CD system. GitHub Actions only runs on the public mirror for tag-driven external publishing.

## 🚀 Getting Started

Follow these steps to start your new project from the private Gitea instance.

### 0. Local Prerequisites

Before starting, install at least `make` and `git` locally. `make` is the template setup entry point; without it you cannot run `make init`. `git` is required for cloning and normal version control.

`make init` will try to install `uv` automatically when it is missing. If your internal network cannot reach the installer, install `uv` first through your internal tool mirror or platform documentation.

Common platform examples:

```bash
# Debian/Ubuntu
sudo apt-get install make git

# macOS (Homebrew)
brew install make git
```

### 1. Create Project from Gitea Template

Instead of cloning, you should create a new repository directly from this template on your private Gitea instance.

1. Navigate to the template repository page on Gitea.

2. Click the **"Use this template"** button.

3. Fill in the details for your new repository and create it.

4. Clone your newly created repository to your local machine.

```bash

# Clone the repository YOU created from the template

git clone <your-new-repository-url>

cd <your-new-repository>

```

### 2. Initialize the Environment & Activate

Initialize your development environment with this command. By default it is interactive; for automation or batch repository creation, pass Make variables.

```bash
make init

# Non-interactive example
make init PACKAGE_NAME=demo_app PROJECT_TITLE="Demo App" PROJECT_DESCRIPTION="Internal demo service." GITEA_USER=team AUTHOR_NAME="Team Maintainers" AUTHOR_EMAIL=team@example.com PYTHON_MIN=3.11 PYTHON_MAX=3.13 PLATFORMS="ubuntu-latest macos-latest windows-latest" ARCHES="x86_64 aarch64" TARGETS="ubuntu-latest/x86_64=ubuntu-latest ubuntu-latest/aarch64=linux-arm64 macos-latest/aarch64=macos-arm64" DOCKER=add
```

This command configures your project by:

1. **Checking for `uv`**: If `uv` is not found, it will be automatically installed.
2. **Configuring Project Name**: It prompts for a new Python package name and updates the `src/` directory, `README.md`, `pyproject.toml`, `Makefile`, CLI entry point, tests, docs, and display name.
3. **Rendering Project Metadata**: `README.md`, `pyproject.toml`, and `mkdocs.yml` are generated from `.templates/project` and filled with the package name, project title, project description, author metadata, internal Gitea host, and repository path. Non-interactive mode can pass `PROJECT_TITLE`, `PROJECT_DESCRIPTION`, `AUTHOR_NAME`, `AUTHOR_EMAIL`, and `GITEA_HOST`.
4. **Configuring Gitea Owner**: It offers to replace the `YOUR_USER` placeholder with your Gitea user or organization. Keeping `YOUR_USER` is valid when continuing to maintain this as a template.
5. **Configuring Compatibility Range**: It asks for the minimum and maximum supported Python versions. `PLATFORMS` and `ARCHES` control the full supported matrix, defaulting to Linux, macOS, Windows, `x86_64`, and `aarch64`; GitHub mirror workflows and project metadata use that full matrix. `TARGETS` controls internal Gitea runner mappings and defaults to the currently available `ubuntu-latest/x86_64=ubuntu-latest`, `ubuntu-latest/aarch64=linux-arm64`, and `macos-latest/aarch64=macos-arm64` runners.
6. **Generating Compatibility Metadata**: The template repository does not ship root-level `README.md`, `pyproject.toml`, `mkdocs.yml`, `.python-version`, `uv.lock`, `.gitea/workflows`, or `.github/workflows` by default. Initialization first generates project config from `.templates/project`, writes the minimum Python version to `.python-version`, then updates `requires-python`, Python/OS classifiers, Ruff target, CI targets, and Docker template base images. Workflows are generated from `.templates/ci` according to the selected Python versions, platforms, and architectures.
7. **Configuring Docker**: The template repository does not ship root-level `Dockerfile`, `compose.yaml`, or `.dockerignore` by default. Initialization asks whether to enable Docker; choosing yes generates Docker config from `.templates/docker` and adds Docker checks to the generated CI.
8. **Locking and Syncing Dependencies**: It updates `uv.lock`, creates a virtual environment, and installs all development dependencies.
9. **Running First Checks**: It runs formatting check, lint, type check, tests, and a CLI smoke test.

Use underscores (`_`) for package names, not hyphens (`-`). The internal Gitea host comes from `INTERNAL_GITEA_HOST` in `.templates/config/internal.env`.

Finally, activate the environment to begin working:

```bash
source .venv/bin/activate
```

You are now ready to code!

### 3. Run the Sample CLI

This template includes a minimal command-line entry point so the repository works immediately after creation. `make init` renames the entry command together with the package name.

```bash
uv run myrepositorytemplate
uv run myrepositorytemplate --version
```

### 4. Rebuild a Maintainer Environment

After the project has been initialized and generated `pyproject.toml`, `.python-version`, `uv.lock`, README, documentation config, and CI files have been committed, later maintainers should not run `make init` again. `make init` is the one-time project creation entry point and re-enters project identity, compatibility, and Docker configuration.

After cloning an initialized project, rebuild the local development environment with:

```bash
make setup
source .venv/bin/activate
```

`make setup` only restores the local environment:

1. Checks for `uv` and installs it when missing.
2. Installs the pinned Python from `.python-version` when present.
3. Runs `uv sync --frozen --all-extras --dev` when `uv.lock` exists.
4. Falls back to `uv sync --all-extras --dev` when `uv.lock` is missing.

When the local virtual environment is broken, Python has changed, or dependency state is inconsistent, run:

```bash
make rebuild-env
```

This removes `.venv` and then runs `make setup`. It does not modify project metadata, CI workflows, Docker config, or the compatibility matrix.

---

## 📖 Command Reference

All common tasks are managed through `make` commands. Here is a comprehensive reference.

### 📦 Dependency Management

Manage your project's dependencies with these commands.

- `make init` or `make install`: The primary setup command. It runs interactively by default and also accepts `PACKAGE_NAME`, `PROJECT_TITLE`, `PROJECT_DESCRIPTION`, `AUTHOR_NAME`, `AUTHOR_EMAIL`, `GITEA_HOST`, `GITEA_USER`, `PYTHON_MIN`, `PYTHON_MAX`, `PLATFORMS`, `ARCHES`, `TARGETS`, and `DOCKER` for non-interactive initialization. `PYTHON_VERSION` or `PYTHON` are compatibility aliases for `PYTHON_MIN`; `DOCKER` accepts `add` or `remove`, and the interactive default is no Docker.

- `make init-demo`: Generates a `demo_app` project in a temporary directory for preview only. It does not modify this template repository.

- `make install-uv`: A helper command to install the `uv` package manager itself, which is called automatically by `make init` if needed.

- `make doctor`: Checks that required local development tools are available.

- `make setup`: The standard maintainer entry point for rebuilding the local environment from committed project config. It does not regenerate project identity, CI, or Docker files.

- `make rebuild-env`: Removes `.venv` and then runs `make setup`, useful for a broken virtual environment or after changing Python versions.

- `make configure-project`: Generates root-level `README.md`, `pyproject.toml`, and `mkdocs.yml`, then configures package name, project title, project description, author metadata, Gitea host, and Gitea owner. You usually do not need to run it directly because `make init` calls it.

- `make configure-user`: Configures only the Gitea owner. It is kept for owner-only changes.

- `make configure-compatibility`: Configures the supported Python version range, CI platform range, and CPU architecture range, then updates project metadata, CI targets, and Docker templates. `PLATFORMS` and `ARCHES` describe the full declared support matrix, defaulting to Linux, macOS, Windows, `x86_64`, and `aarch64`; the GitHub mirror workflow is generated from that full matrix. `TARGETS` describes actual internal Gitea runner mappings, so Gitea only expands combinations that have real internal runners. Non-interactive mode can pass `TARGETS="ubuntu-latest/x86_64=ubuntu-latest ubuntu-latest/aarch64=linux-arm64 macos-latest/aarch64=macos-arm64"` to override internal runner labels. CI workflow skeletons and repeated job snippets live under `.templates/ci`; `.gitea/workflows/ci.yaml` and `.github/workflows/ci.yaml` are generated outputs.

- `make configure-docker`: Configures whether Docker integration is generated. Interactive mode asks whether to enable it; non-interactive mode can pass `DOCKER=add` or `DOCKER=remove`. For compatibility, `DOCKER=keep` is treated as `add`.

- `make pin-python`: Compatibility alias for `make configure-compatibility`.

- `make sync`: Use this if you have manually changed `pyproject.toml` or pulled new changes. It syncs the virtual environment with the `uv.lock` file.

- `make sync-frozen`: Syncs the virtual environment without changing `uv.lock`.

- `make lock`: Updates `uv.lock`.

- `make lock-check`: Checks that `uv.lock` is current.

- `make update`: Upgrades all dependencies to the latest allowed versions according to `pyproject.toml` and updates the `uv.lock` file.

- `make tree`: Displays the complete dependency tree, useful for debugging dependency conflicts.

- `make audit`: Optional dependency vulnerability audit, implemented with `uvx pip-audit` by default. It is not part of `make check` because vulnerability database access and false-positive handling usually depend on team security policy. Pass extra options with `AUDIT_ARGS="--strict"` or replace the target with your internal scanner.

To add or remove dependencies, use `uv` directly:

- `uv add <package>`: Add a new main dependency.

- `uv add --dev <package>`: Add a new development dependency.

- `uv remove <package>`: Remove a dependency.

Maintenance scripts live under `scripts/` and are written in shell. `Makefile` remains the stable command surface, while longer behavior lives in scripts such as `scripts/configure_project.sh`, `scripts/configure_compatibility.sh`, `scripts/manage_docker.sh`, `scripts/init_demo.sh`, `scripts/template_check.sh`, and `scripts/check_actions.sh`. Shared helpers live under `scripts/lib/`. These scripts do not depend on the Python virtual environment, so they can run before `uv sync`; their syntax is kept executable under `sh`, `bash`, and `zsh`.

Project config templates live under `.templates/project`, including `README.md`, `pyproject.toml`, and `mkdocs.yml`. The template repository does not commit root-level generated project config; it is generated by `make init`, `make configure-project`, or `make configure-compatibility`. `README.dev.md` is the template's base development guide and stays at the repository root. In real projects created from this template, generated project config should usually be committed.

CI templates live under `.templates/ci`. The template repository does not commit `.gitea/workflows` or `.github/workflows`; they are generated by `make init` or `make configure-compatibility`. To change Gitea/GitHub workflow steps, internal action URLs, package mirrors, or Docker checks, edit the templates first and then run `make configure-compatibility` to regenerate workflows. Manual edits to expanded combinations inside `.gitea/workflows/ci.yaml` or `.github/workflows/ci.yaml` will be overwritten by later initialization or compatibility changes.

### 🏗️ Internal Infrastructure Config

Internal infrastructure defaults are centralized in `.templates/config/internal.env`. The file is both GNU Make includeable and POSIX shell sourceable, so it works before the Python environment exists.

It currently controls:

- `INTERNAL_GITEA_HOST`: internal Gitea base URL.
- `INTERNAL_PYPI_INDEX`: internal PyPI mirror.
- `PUBLIC_PYPI_INDEX` / `ACT_PYPI_INDEX`: PyPI sources for GitHub mirror and local `act`.
- `PYTHON_INSTALL_MIRROR`: Python download mirror for `uv python install`.
- `GITEA_CHECKOUT_ACTION`: internal checkout action. Gitea CI installs `uv` from `INTERNAL_PYPI_INDEX` instead of using a `setup-uv` action.
- `GITHUB_CHECKOUT_ACTION` / `GITHUB_SETUP_UV_ACTION` / `GITHUB_RELEASE_ACTION`: action versions used by the GitHub mirror workflow.
- `INTERNAL_DEFAULT_GITEA_TARGETS`, `INTERNAL_DEFAULT_PLATFORMS`, and `INTERNAL_DEFAULT_ARCHES`: default platforms, architectures, and Gitea runner mappings.

For Makefile and POSIX shell compatibility, do not use nested references such as `${OTHER_VAR}` in `internal.env`; write derived URLs explicitly.

When internal hosts, mirrors, or runner labels change, edit `.templates/config/internal.env` first, then regenerate:

```bash
make configure-project
make configure-compatibility
```

When maintaining the template itself, run `make template-check` afterward. Do not only edit generated workflows or `pyproject.toml`.

### 🧰 Template Maintenance

These commands are mainly for template maintainers. Developers in initialized projects usually only need `make setup`, `make check`, `make test`, and release commands.

- `make template-check`: Validates template repository structure, shell script syntax, key Makefile targets, the bundled Codex skill, absence of generated root files, and temporary project/CI generation. It also checks key generated workflow actions, mirrors, publish steps, and Gitea/GitHub matrix differences.

- `make action-check`: Checks CI action versions against upstream Git tags. It needs network access and is intended for CI template upgrades or periodic maintenance.

- `make skill-check`: Validates `.codex/skills/python-internal-template`. If the local Codex system skill validator exists, it is used first.

- `make skill-install`: Installs the bundled skill into `$CODEX_HOME/skills/` or `~/.codex/skills/` so agents can discover it automatically.

Template maintenance convention:

1. Edit `.templates/*`, `scripts/*`, or `Makefile`; do not commit generated root project files.
2. Update the primary Chinese guide `README.dev.md` first, then sync long-lived `docs/` pages. Keep `i18n/README.en.md` as a concise English reference and sync commands, configuration keys, compatibility rules, and release semantics instead of translating every paragraph.
3. Before committing, run `make template-check` and use `git status --short` to confirm no root-level `README.md`, `pyproject.toml`, `mkdocs.yml`, workflow, or Docker files were generated accidentally.

Shared script configuration lives in `scripts/lib/internal_config.sh`; compatibility parsing lives in `scripts/lib/compatibility.sh`; CI rendering lives in `scripts/lib/ci_render.sh`; reusable render helpers live in `scripts/lib/render.sh`. The `Makefile` should remain a stable command surface. Longer behavior belongs in shell scripts such as `scripts/help.sh`, `scripts/init_demo.sh`, `scripts/template_check.sh`, and shared helpers under `scripts/lib/`.

### 🎨 Code Quality

Ensure your code stays clean, formatted, and type-safe.

- `make format`: Formats all code in the project using `Ruff Formatter`.

- `make format-check`: Checks formatting without changing files. This is what `make check` uses.

- `make lint`: Lints all code using `Ruff Linter` without changing files.

- `make lint-fix`: Lints all code and applies safe automatic fixes.

- `make type-check`: Runs `Mypy` against the configured package name.

- `make check`: The all-in-one quality command. It runs `format-check`, `lint`, and `type-check` sequentially. **Run this before every commit!**

### 🧪 Testing

Run your test suite and check for code coverage.

- `make test`: Executes the entire test suite using `pytest`.

- `make test-cov`: Runs the tests and generates a detailed HTML coverage report. It will then automatically open the report in your default web browser for inspection.

- `make smoke`: Runs the installed CLI once to catch broken entry points.

### 📚 Documentation

This template uses MkDocs Material for project documentation. `README.md` is generated from `.templates/project/README.md` by `make init` and should stay as the short entry point for the real project; long-lived user guides, development workflows, references, and operations notes should live under `docs/`.

- `make docs-serve`: Starts a local preview server at `http://127.0.0.1:8000`.
- `make docs-build`: Builds the static site into `site/`.
- `make docs-check`: Builds in strict mode, useful before committing documentation changes.

Recommended layout:

```text
docs/
├── index.md
├── development/
│   ├── index.md
│   ├── environment.md
│   ├── workflow.md
│   ├── platforms.md
│   ├── release.md
│   ├── release-troubleshooting.md
│   ├── security.md
│   ├── contributing.md
│   └── template-maintenance.md
├── user-guide/
│   └── index.md
├── reference/
│   └── index.md
├── operations/
│   └── deployment.md
└── adr/
    └── index.md
```

Writing guidance:

- The home page should explain what the project is, who it is for, and where to start.
- User guides should be task-oriented: install, configure, run, and troubleshoot.
- Reference pages should be complete and stable: CLI flags, config keys, APIs, environment variables, and data formats.
- Development docs should cover local setup, testing strategy, generated CI, coding style, and release workflow.
- ADRs should record important technical decisions that future maintainers may need to revisit.

After adding or moving pages, update `nav` in `mkdocs.yml`.

For internal publishing failures, start with `docs/development/release-troubleshooting.md`. It breaks the problem down by checkout, uv installation, dependency installation, build, `uv publish`, and GitHub mirror publishing stages.

### 💻 Platform Notes

Linux and macOS can run the template commands directly after installing `make`, `git`, and `uv`. Apple Silicon macOS is the current internal macOS runner path; macOS x86_64 remains covered by the GitHub mirror workflow.

On Windows, WSL2 + Ubuntu is preferred. MSYS2 or Git Bash can also work, but `make`, `sh`, `git`, and `uv` must all be on `PATH`. The configuration scripts are shell scripts; PowerShell can be the outer terminal, but it does not replace the required `sh` runtime.

### 🧪 Local CI Validation

This template provides `act` entry points to validate the GitHub mirror workflow locally before pushing. `act` runs through Docker, so Docker must be installed and running.

- `make act-check`: Checks that `act` and Docker are available.
- `make act-list`: Lists jobs from `.github/workflows/ci.yaml`.
- `make act-dry-run`: Validates workflow parsing, job selection, and matrix selection with `act --dryrun`.
- `make act-ci`: Runs the default local CI path: `ubuntu-latest`, `x86_64`, and the minimum supported Python version.

When running under `act`, `.github/workflows/ci.yaml` uses the `env.ACT == 'true'` branch, installs `uv` and dependencies from `ACT_PYPI_INDEX`, and uses `PYTHON_INSTALL_MIRROR` for Python downloads. Normal GitHub mirror publishing still uses `PUBLIC_PYPI_INDEX`.

Examples:

```bash
make act-ci ACT_PLATFORM=ubuntu-latest ACT_ARCH=x86_64 ACT_PYTHON=3.11
make act-ci ACT_PLATFORM=ubuntu-latest ACT_ARCH=aarch64 ACT_PYTHON=3.12
```

`act` is mainly for validating Linux container paths. macOS, Windows, and real heterogeneous runner behavior should still be validated by internal Gitea runners or GitHub mirror CI.

### 🏗️ Build & Release

This template is configured for internal-first development. Gitea is the source of truth. GitHub receives a one-way mirror from Gitea and only handles public publishing after mirrored tags arrive.

- `make build`: A safe build command. It first runs `make clean`, `make check`, and `make test`. If everything passes, it builds the distribution packages (`.whl` and `.tar.gz`) into the `dist/` directory.

- `make release`: This is a helper command that **does not perform a release**. Instead, it prints the internal Gitea release URL and the one-way mirror publishing reminder.

Versions are derived from Git tags by `hatch-vcs`; do not hand-edit a version string in source. Use stable tags such as `v0.1.0` or `v1.2.3`. Release candidates such as `v0.1.0rc1` are useful for internal validation. Daily pushes to `main` are for internal development snapshots; public stable releases should start from a clean stable tag or release in Gitea.

#### Internal Development Snapshots (Gitea)

- **Trigger**: `git push` to the `main` branch on the **private Gitea repository**.

- **Outcome**: Gitea Actions automatically builds a development snapshot (e.g., `0.1.0.dev5`) and publishes it to the **internal Gitea package registry**.

- **Configuration**: The workflow uses internal mirrored actions and Python download mirrors. Set the secrets `OWNER` and `PASSWORD` for publishing credentials.

- **Package index**: `pyproject.toml` uses the internal Gitea package registry. `make init` replaces template placeholders with your Gitea host, user, or organization.

- **Heterogeneous runners**: Gitea Actions has weaker `runs-on` expression support, so this template expands `TARGETS` into static jobs through `.templates/ci/gitea-test-job.yaml.tpl`. Current default internal labels are `ubuntu-latest` for Linux x86_64, `linux-arm64` for Linux aarch64, and `macos-arm64` for Apple Silicon macOS. Available aliases also include `ubuntu-22.04`, `ubuntu-20.04`, `ubuntu-18.04`, Linux arm labels such as `linux-aarch64`, `ubuntu-arm64`, `ubuntu-aarch64`, `ubuntu-24.04-arm64`, and macOS arm labels such as `macos-aarch64`, `darwin-arm64`, `darwin-aarch64`, and `apple-silicon`. Use `TARGETS="platform/arch=runner-label"` if internal labels change.

#### Public Stable Releases (GitHub Mirror)

- **Trigger**: Create a tag or release in Gitea, for example `v0.1.0`. The one-way mirror syncs that tag to GitHub.

- **Outcome**: GitHub Actions runs tests on the mirrored tag, builds the stable distribution, publishes it to **public PyPI**, and attaches artifacts to the GitHub Release page.

- **Important**: Developers should not use GitHub as the day-to-day development remote. Pushes, branches, and releases start from Gitea.

- **Local validation**: The GitHub workflow also exposes `workflow_dispatch` for `make act-ci`. The `deploy` job is skipped under `act` to avoid accidental local publishing.

Public PyPI publishing defaults to PyPI Trusted Publishing. Configure the Trusted Publisher on the PyPI project, keep the GitHub environment name as `pypi`, and keep `id-token: write` on the `deploy` job. Internal-only projects that should not publish to public PyPI should remove or replace the `deploy` job in `.templates/ci/github-ci.yaml.tpl`, then regenerate workflows with `make configure-compatibility`.

### 🧹 Utilities & Maintenance

Keep your project directory clean.

- `make clean`: Removes temporary files and build artifacts, such as `__pycache__`, `.pytest_cache`, `build/`, `dist/`, and coverage reports.

- `make distclean`: A more thorough cleaning. It performs `make clean` and then **completely removes the virtual environment (`.venv`)**. `.python-version` is project compatibility configuration and remains in the repository. In initialized projects, rebuild with `make setup` after cleaning; do not rerun `make init`.

### 🐳 Docker Integration

This template does not generate root-level Docker config by default. Enable Docker during `make init`, or run `make docker-restore` later when a project needs containerization.

- `make docker-build`: Builds the Docker image for your application. This is useful for testing the image build process or preparing for deployment.

- `make docker-check`: Builds the Docker image without tagging it. This mirrors the CI Docker build check.

- `make docker-up`: Builds (if necessary) and starts your application services in detached mode using `docker compose`. This is the primary way to run your application in a Dockerized environment during development.

- `make docker-down`: Stops and removes the containers, networks, and volumes created by `docker compose up`. Use this to clean up your Docker environment when you're done.

- `make docker-remove`: Removes generated `Dockerfile`, `compose.yaml`, `.dockerignore`, and the Docker build jobs from both Gitea and GitHub workflows. Removed files are backed up under `.templates/docker/removed/`, which is not committed.

- `make docker-restore`: Restores Docker files from a local backup, or generates them from `.templates/docker/` if no backup exists, and re-adds Docker build jobs to generated CI.

You can view the running container logs with `docker compose logs -f` after running `make docker-up`.

Docker support is optional. For library-only or notebook-only projects, keep Docker disabled during initialization. Reintroduce it later with `make docker-restore`.

## Lock File Strategy

The template repository does not commit root-level `uv.lock`; real projects generate it during `make init`. For applications, services, or projects that need reproducible development environments, commit the generated `uv.lock`. The generated Dockerfile uses `uv sync --frozen`, and CI relies on the lock file for reproducible installs.

If a real project turns into a reusable library and chooses not to commit `uv.lock`, also update the Dockerfile and CI commands to avoid `--frozen`.

## Internal Package Indexes

The default template intentionally uses the internal mirror and internal Gitea package registry:

- Public dependency mirror is controlled by `INTERNAL_PYPI_INDEX` in `.templates/config/internal.env`.
- Internal package registry template: `<INTERNAL_GITEA_HOST>/api/packages/<gitea-user-or-org>/pypi/`

When creating a real project, `make init` interactively configures the owning Gitea user or organization.

## Agent Skill

This repository includes a Codex skill at `.codex/skills/python-internal-template/SKILL.md`. It guides agents that use or maintain this template, especially around:

- `make init` as the one-time project creation entry point.
- `make setup` and `make rebuild-env` as maintainer environment rebuild commands.
- The relationship between `.templates/*` and generated files.
- The difference between Gitea runner targets and the full GitHub mirror matrix.

To make Codex discover it automatically, install it into `$CODEX_HOME/skills/` or `~/.codex/skills/`. Validate changes with:

```bash
make skill-install
make skill-check
```
