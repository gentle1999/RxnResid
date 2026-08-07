# {{PROJECT_TITLE}}

{{PROJECT_DESCRIPTION}}

This repository is an internal-first Python project using `uv`, `Ruff`, `Mypy`, `Pytest`, `Hatch`, MkDocs, optional Docker, and Gitea CI. Gitea is the source of truth; GitHub publishing is handled through the one-way mirror workflow.

## Quick Start

Install `make` and `git` before starting. `make init` can install `uv` when it is missing, but internal networks may require installing `uv` from the approved internal mirror first.

For the first maintainer creating a repository from the template:

```bash
make init
```

For non-interactive setup:

```bash
make init PACKAGE_NAME=demo_app PROJECT_TITLE="Demo App" PROJECT_DESCRIPTION="Internal demo service." GITEA_USER=team AUTHOR_NAME="Team Maintainers" AUTHOR_EMAIL=team@example.com PYTHON_MIN=3.11 PYTHON_MAX=3.13 PLATFORMS="ubuntu-latest macos-latest windows-latest" ARCHES="x86_64 aarch64" TARGETS="ubuntu-latest/x86_64=ubuntu-latest ubuntu-latest/aarch64=linux-arm64 macos-latest/aarch64=macos-arm64" DOCKER=add
```

For day-to-day development after initialization:

```bash
make setup
make sync
make check
make test
make docs-check
```

Run the sample CLI:

```bash
uv run {{PACKAGE_NAME}}
uv run {{PACKAGE_NAME}} --version
```

Preview the documentation site:

```bash
make docs-serve
```

Build the package:

```bash
make build
```

## What To Commit

After the first successful `make init`, commit the generated project files:

- `README.md`, `pyproject.toml`, `mkdocs.yml`
- `.python-version`, `uv.lock`
- `.gitea/workflows/ci.yaml`, `.github/workflows/ci.yaml`
- `Dockerfile`, `compose.yaml`, `.dockerignore` only if Docker was enabled
- source, tests, docs, and template configuration changes you intentionally made

Do not commit `.venv/`, `site/`, build artifacts, caches, `.secrets`, or `.vars`.

## Common Commands

Most developers only need these commands:

- `make info`: show current project/template settings.
- `make doctor`: check required local tools.
- `make setup`: rebuild a maintainer's local environment from committed `pyproject.toml`, `.python-version`, and `uv.lock` without changing project metadata or CI.
- `make rebuild-env`: remove `.venv` and then run `make setup`.
- `make sync`: sync the local development environment.
- `make sync-frozen`: sync using the existing `uv.lock`.
- `make lock`: update `uv.lock`.
- `make lock-check`: verify `uv.lock` is current.
- `make update`: upgrade locked dependencies.
- `make audit`: run an optional dependency vulnerability audit.
- `make check`: run formatting, linting, typing, and docs checks.
- `make test`, `make test-cov`: run tests, optionally with HTML coverage.
- `make smoke`: run the generated CLI once.
- `make docs-serve`: preview MkDocs locally.
- `make docs-build`: build documentation into `site/`.
- `make docs-check`: build documentation in strict mode.
- `make build`: run checks/tests and build distributions.
- `make release`: print the internal Gitea release flow.
- `make clean`: remove build artifacts and tool caches.
- `make distclean`: additionally remove `.venv`; rebuild initialized projects with `make setup`.

Configuration commands are usually run only by repository maintainers:

- `make init`: one-time setup after creating a new repository from the template.
- `make configure-project`: refresh generated `README.md`, `pyproject.toml`, and `mkdocs.yml`.
- `make configure-compatibility`: regenerate Python version metadata and CI workflows.
- `make configure-docker`: choose whether Docker config should be generated.
- `make docker-restore`: generate or restore Docker files and CI Docker checks.
- `make docker-remove`: remove generated Docker files and Docker checks from generated CI.
- `make act-check`, `make act-list`, `make act-dry-run`, `make act-ci`: validate the GitHub mirror workflow locally with `act`.

## Compatibility

Use `PLATFORMS` and `ARCHES` for the full declared support matrix. The GitHub mirror workflow uses that full matrix. Use `TARGETS` for internal Gitea runner mappings; Gitea CI only expands combinations that have real internal runners.

```bash
make configure-compatibility PLATFORMS="ubuntu-latest macos-latest windows-latest" ARCHES="x86_64 aarch64" TARGETS="ubuntu-latest/x86_64=ubuntu-latest ubuntu-latest/aarch64=linux-arm64 macos-latest/aarch64=macos-arm64"
```

Remove default platform, architecture, or Gitea target combinations when the project does not support them:

```bash
make configure-compatibility REMOVE_PLATFORMS="windows-latest" REMOVE_TARGETS="ubuntu-latest/aarch64"
```

## Documentation

Long-lived project documentation lives under `docs/` and is built by MkDocs. See [README.dev.md](README.dev.md) for the development workflow and documentation conventions.

Recommended development pages include local environment setup, workflow, platform/architecture support, release credentials, security/audit notes, contribution conventions, and template maintenance notes.

## CI And Publishing

Gitea is the source of truth for internal development. GitHub is a one-way public mirror used for external publishing.

CI workflows are generated from `.templates/ci` during initialization. Validate the GitHub mirror workflow locally with `act`:

```bash
make act-check
make act-dry-run
make act-ci
```

Configure Gitea secrets `OWNER` and `PASSWORD` for internal package publishing. Public PyPI publishing uses GitHub mirror CI with PyPI Trusted Publishing and the `pypi` environment.

Internal infrastructure defaults such as Gitea host, package mirrors, Python download mirror, mirrored actions, and default runner mappings live in `.templates/config/internal.env`. Edit that file first, then regenerate project config and CI.

If internal publishing fails, start with `docs/development/release-troubleshooting.md`.

## Docker

Docker support is optional. Generate, build, and run the Docker image only when this project needs containerization:

```bash
make docker-restore
make docker-build
make docker-up
```

Projects that do not need Docker can remove generated config:

```bash
make docker-remove
```
