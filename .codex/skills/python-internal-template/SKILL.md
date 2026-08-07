---
name: python-internal-template
description: "Use when Codex is working in repositories created from MyRepositoryTemplate or maintaining the template itself: initializing a new internal Python project, regenerating project config from .templates, configuring Python/platform/architecture CI targets, managing optional Docker config, rebuilding a maintainer environment, updating MkDocs docs, or reviewing changes to Makefile, scripts/configure_project.sh, scripts/configure_compatibility.sh, scripts/manage_docker.sh, .templates/project, .templates/ci, or .templates/docker."
---

# Python Internal Template

## Core Model

Treat this repository as an internal-first Python project template for Gitea. Gitea is the source of truth; GitHub is a one-way public mirror used for external publishing.

Mode: template vs initialized project

- Template-maintenance mode: work inside this repository only on template sources such as `.templates/*`, `scripts/*`, `docs/`, and `Makefile`. In this mode, do NOT create or overwrite generated root project files in the template root (for example `README.md`, `pyproject.toml`, `mkdocs.yml`, `.python-version`, `uv.lock`, workflow files, Docker files). Edit templates and scripts only and validate generation in a separate temporary copy.
- Initialized-project mode: run generation targets such as `make init`, `make configure-project`, or `make configure-compatibility` only when the user explicitly requests initializing a separate project directory or a temporary copy of the template. When asked to initialize, always confirm whether the user wants a temporary/isolated copy or to initialize the current working directory.

Common generated root files (not present in the template root):

- README.md
- pyproject.toml
- mkdocs.yml
- .python-version
- uv.lock
- .gitea/workflows/ci.yaml
- .github/workflows/ci.yaml
- Dockerfile
- compose.yaml
- .dockerignore

## File Map

- `README.dev.md`: primary Chinese development guide. Keep this as the root guide for the template. Its opening section is the shortest user-facing entry point for choosing between new-project use and template maintenance.
- `i18n/README.en.md`: secondary English reference.
- `Makefile`: public command surface. Use uppercase `Makefile`, not lowercase `makefile`.
- `.templates/config/internal.env`: centralized internal infrastructure defaults. It is both Makefile-includeable and POSIX-sh-sourceable.
- `scripts/configure_project.sh`: shell-only project identity and metadata renderer. Must work under `sh`, `bash`, and `zsh`.
- `scripts/configure_compatibility.sh`: shell-only Python/platform/architecture and CI generator.
- `scripts/manage_docker.sh`: shell-only Docker config generator/remover.
- `scripts/help.sh`: Make help text renderer behind `make help`.
- `scripts/init_demo.sh`: temporary-copy demo generator behind `make init-demo`.
- `scripts/template_check.sh`: template validation entry point behind `make template-check`.
- `scripts/check_actions.sh`: networked CI action version checker for template maintenance.
- `scripts/check_compatibility_helpers.sh`: fixture-style validation for compatibility helper behavior.
- `scripts/lib/internal_config.sh`: shared internal default loader used by shell maintenance scripts.
- `scripts/lib/compatibility.sh`: Python/platform/architecture target normalization helpers.
- `scripts/lib/ci_render.sh`: CI matrix, job, and workflow rendering helpers.
- `scripts/lib/render.sh`: shared template rendering helpers for shell maintenance scripts.
- `.templates/project/`: generated `README.md`, `pyproject.toml`, and `mkdocs.yml` templates.
- `.templates/ci/`: CI workflow templates and generated job snippets.
- `.templates/docker/`: optional Docker config templates.
- `docs/`: MkDocs documentation skeleton.

## Command Map (quick reference)

If the user intent is clear, choose the corresponding make target:

- **Create a new project in a fresh directory**: `make init`
- **Preview generated project output without touching the template root**: `make init-demo`
- **Setup a maintainer environment for an already-initialized project**: `make setup`
- **Repair local virtualenv**: `make rebuild-env`
- **Regenerate project root files from templates**: `make configure-project`
- **Regenerate compatibility metadata and CI**: `make configure-compatibility`
- **Manage optional Docker config**: `make docker-restore` / `make docker-remove`
- **Validate template changes**: `make template-check`
- **Check upstream CI action versions**: `make action-check`

Detailed behavior and examples follow; always confirm whether you are operating in template-maintenance mode (editing `.templates/*`, `scripts/*`) or initializing an independent project (temporary copy or user-specified directory).

Use `make configure-project` to generate or refresh root `README.md`, `pyproject.toml`, and `mkdocs.yml` from `.templates/project` and render metadata. Pass explicit metadata through Make variables. If any required metadata variable is missing or incomplete, stop and prompt the user for the missing values rather than inventing defaults:

```bash
make configure-project PACKAGE_NAME=demo_app PROJECT_TITLE="Demo App" PROJECT_DESCRIPTION="Internal demo service." GITEA_USER=team AUTHOR_NAME="Team Maintainers" AUTHOR_EMAIL=team@example.com
```

Use `make init-demo` when the user wants to understand what the template generates without initializing the current working directory. It creates a temporary copy and leaves the template root unchanged.

Use `make configure-compatibility` to regenerate Python metadata and CI. If `TARGETS` or other mappings are missing or invalid, stop and ask the user to provide or correct the mapping instead of guessing:

```bash
make configure-compatibility PYTHON_MIN=3.11 PYTHON_MAX=3.13 PLATFORMS="ubuntu-latest macos-latest windows-latest" ARCHES="x86_64 aarch64" TARGETS="ubuntu-latest/x86_64=ubuntu-latest ubuntu-latest/aarch64=linux-arm64 macos-latest/aarch64=macos-arm64"
```

Use `make docker-restore` or `make docker-remove` for optional Docker config. When running generation targets, prefer validating changes in a temporary copy (see Validation Checklist). Do not overwrite generated root files in the template root without explicit user confirmation.

`make audit` is an optional initialized-project dependency audit. If your organization provides a documented internal dependency scanner, run that scanner instead of `make audit`; otherwise run `make audit` unchanged. Do not invent or name undocumented scanners.

Use `make template-check` after changing template scripts, templates, docs, Makefile, or this skill. Use `make skill-check` for skill-only validation and `make skill-install` when the user wants the bundled skill installed into the local Codex skills directory.

Use `make action-check` when upgrading CI action references or during periodic CI template maintenance. It checks upstream Git tags and requires network access.

## CI Rules

Keep two support concepts separate:

- `PLATFORMS` and `ARCHES`: full declared support matrix used for project metadata and GitHub mirror workflow.
- `TARGETS`: actual internal Gitea runner mappings. Gitea workflow only expands combinations with real internal runners.

Default internal Gitea target mappings:

- `ubuntu-latest/x86_64=ubuntu-latest`
- `ubuntu-latest/aarch64=linux-arm64`
- `macos-latest/aarch64=macos-arm64`

GitHub mirror may include the full matrix, including Windows and macOS x86_64. Gitea must exclude combinations with no internal runner unless the user supplies a `TARGETS` mapping. If `TARGETS` contains combinations that do not match declared `PLATFORMS`/`ARCHES` or reference unknown runners, stop and ask the user for a corrected `TARGETS` mapping instead of guessing.

Act support is for validating the GitHub mirror workflow locally. Prefer the Make targets `make act-check`, `make act-list`, `make act-dry-run`, and `make act-ci` instead of invoking `act` ad hoc.

Gitea publishing uses repository secrets `OWNER` and `PASSWORD` for the internal package registry. GitHub mirror publishing uses PyPI Trusted Publishing with environment `pypi`; do not introduce long-lived PyPI tokens unless the user explicitly asks to change the release model.

Versions are derived from Git tags by `hatch-vcs`. Stable external releases should use Gitea-originated tags such as `v0.1.0`; release candidates may use tags such as `v0.1.0rc1`.

If internal hosts, mirrors, action URLs, Python download mirrors, or default runner mappings change, edit `.templates/config/internal.env` first. Keep values explicit; do not use nested `${OTHER_VAR}` references because the file is shared by Makefile and POSIX shell. Then regenerate generated config with `make configure-project` and `make configure-compatibility`. Do not patch generated workflows as the primary fix.

GitHub mirror action versions are centralized in `.templates/config/internal.env` as `GITHUB_CHECKOUT_ACTION`, `GITHUB_SETUP_UV_ACTION`, and `GITHUB_RELEASE_ACTION`. Shared shell defaults live in `scripts/lib/internal_config.sh`; keep that loader in sync with new internal config keys.

## Metadata Rendering

Project templates use explicit placeholders such as `{{PACKAGE_NAME}}`, `{{PROJECT_TITLE}}`, `{{PROJECT_DESCRIPTION_TOML}}`, `{{AUTHOR_ENTRY}}`, `{{GITEA_HOST}}`, and `{{GITEA_USER}}`.

When changing generated project fields, update `.templates/project/*` and `scripts/configure_project.sh`, then validate with a temporary copy. Avoid broad manual edits to root generated files in the template repository.

`YOUR_USER` is a placeholder, not the template author's username. It may remain in the uninitialized template.

## Documentation Rules

Chinese is the primary development guide. Update `README.dev.md` first, then keep `i18n/README.en.md` as a secondary reference.

Generated project README should stay concise and point long-lived docs to `docs/`. Put detailed user, development, reference, operation, and ADR material under `docs/` and keep `mkdocs.yml` nav in sync.

Recommended development docs include environment, workflow, platforms, release credentials, security/audit, contribution conventions, and template maintenance.

For internal publishing failures, prefer updating or referencing `docs/development/release-troubleshooting.md`.

## Validation Checklist

For script changes, run:

```bash
sh -n scripts/configure_project.sh scripts/configure_compatibility.sh scripts/manage_docker.sh scripts/help.sh scripts/init_demo.sh scripts/template_check.sh scripts/check_actions.sh scripts/check_compatibility_helpers.sh scripts/lib/internal_config.sh scripts/lib/compatibility.sh scripts/lib/ci_render.sh scripts/lib/render.sh
```

For Makefile changes, run dry-run checks:

```bash
make -n help
make -n setup
make -n rebuild-env
```

For generation changes, validate in a temporary copy, not the template root:

```bash
tmpdir=$(mktemp -d)
cp -a . "$tmpdir/repo"
cd "$tmpdir/repo"
make configure-project PACKAGE_NAME=demo_app PROJECT_TITLE="Demo App" PROJECT_DESCRIPTION="Internal demo service." GITEA_USER=team AUTHOR_NAME="Team Maintainers"
make configure-compatibility PYTHON_MIN=3.11 PYTHON_MAX=3.13 PLATFORMS="ubuntu-latest macos-latest windows-latest" ARCHES="x86_64 aarch64" TARGETS="ubuntu-latest/x86_64=ubuntu-latest ubuntu-latest/aarch64=linux-arm64 macos-latest/aarch64=macos-arm64"
```

After validation, confirm the template root still has no generated root project files:

```bash
find . -maxdepth 2 \( -name README.md -o -name pyproject.toml -o -name mkdocs.yml -o -name Dockerfile -o -name compose.yaml -o -name uv.lock -o -name .python-version \) -print
```

This should print nothing in the template repository.

If you run generation in a target directory and generated root files already exist there, do NOT overwrite them automatically; ask the user whether to use a temporary copy, to overwrite, or to abort.

The consolidated validation entry point is:

```bash
make template-check
```
