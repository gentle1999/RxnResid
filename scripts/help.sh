#!/usr/bin/env sh
if [ -n "${ZSH_VERSION:-}" ] && command -v emulate >/dev/null 2>&1; then
    emulate -L sh
fi
set -eu

is_template_repo=1
if [ -f README.md ]; then
    command_reference=README.md
    is_template_repo=0
else
    command_reference=README.dev.md
fi

if [ "$is_template_repo" -eq 1 ]; then
    cat <<'EOF'
📚 Python Project Helper

Choose one path:
  New project from this template   Use Gitea "Use this template", clone it, run: make init
  Preview generated output safely  Run: make init-demo
  Maintain this template repo      Run: make template-check
EOF
else
    cat <<'EOF'
📚 Python Project Helper

Choose one path:
  First setup after cloning         Run: make setup
  Broken local environment          Run: make rebuild-env
  Change project metadata or CI     Run the configuration commands below
EOF
fi

cat <<'EOF'

Daily commands:
  make check        format, lint, type-check, and docs-check
  make test         run pytest
  make docs-serve   preview MkDocs locally
  make build        run checks/tests and build distributions
  make release      print the Gitea-tag release flow

Configuration commands:
  make info                         show current project/template settings
  make doctor                       check required local tools
  make configure-project            refresh README/pyproject/mkdocs identity
  make configure-compatibility      refresh Python/platform/arch metadata and CI
  make configure-docker             add or remove generated Docker support
EOF

if [ "$is_template_repo" -eq 1 ]; then
    cat <<'EOF'
Template maintenance:
  make template-check validate this template repository
  make action-check   check upstream CI action tags
  make skill-check    validate the bundled Codex skill
  make skill-install  install the bundled Codex skill locally
EOF
fi

printf "Full command reference: %s\n" "$command_reference"
printf "📌 Current Package: %s\n" "${PACKAGE_NAME:-unknown}"
printf "📌 Detected Version: %s\n" "${VERSION:-dynamic}"
