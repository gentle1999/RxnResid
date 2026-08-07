#!/usr/bin/env sh
if [ -n "${ZSH_VERSION:-}" ] && command -v emulate >/dev/null 2>&1; then
    emulate -L sh
fi
set -eu

script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
root_dir=$(CDPATH= cd -- "$script_dir/.." && pwd)
cd "$root_dir"

default_platforms=${DEFAULT_PLATFORMS:-ubuntu-latest macos-latest windows-latest}
default_arches=${DEFAULT_ARCHES:-x86_64 aarch64}
demo_targets=${INIT_DEMO_TARGETS:-ubuntu-latest/x86_64=ubuntu-latest ubuntu-latest/aarch64=linux-arm64 macos-latest/aarch64=macos-arm64}

tmpdir=$(mktemp -d)
demo_dir="$tmpdir/demo"

echo "🧪 Creating a disposable demo project in a temporary directory..."
mkdir -p "$demo_dir"
git archive --format=tar HEAD | (cd "$demo_dir" && tar -xf -)
cp -R .templates scripts docs i18n "$demo_dir/"
cp Makefile README.dev.md LICENSE "$demo_dir/"
if [ -d .codex ]; then
    mkdir -p "$demo_dir/.codex"
    cp -R .codex/skills "$demo_dir/.codex/"
fi
rm -rf \
    "$demo_dir/.venv" \
    "$demo_dir/site" \
    "$demo_dir/.pytest_cache" \
    "$demo_dir/.ruff_cache" \
    "$demo_dir/.mypy_cache"

(
    cd "$demo_dir"
    make configure-project \
        PACKAGE_NAME=demo_app \
        PROJECT_TITLE="Demo App" \
        PROJECT_DESCRIPTION="Internal demo service." \
        GITEA_USER=team \
        AUTHOR_NAME="Team Maintainers" \
        AUTHOR_EMAIL=team@example.com
    make configure-compatibility \
        PYTHON_MIN=3.11 \
        PYTHON_MAX=3.13 \
        PLATFORMS="$default_platforms" \
        ARCHES="$default_arches" \
        TARGETS="$demo_targets"
)

echo ""
echo "✅ Demo project generated at: $demo_dir"
echo "📄 Key generated files:"
find "$demo_dir" \
    \( -path "$demo_dir/.templates" \
    -o -path "$demo_dir/.templates/*" \
    -o -path "$demo_dir/.venv" \
    -o -path "$demo_dir/.venv/*" \) -prune \
    -o \( -name README.md \
    -o -name pyproject.toml \
    -o -name mkdocs.yml \
    -o -name .python-version \
    -o -path "$demo_dir/.gitea/workflows/ci.yaml" \
    -o -path "$demo_dir/.github/workflows/ci.yaml" \) -print |
    sort
echo ""
echo "This was a preview only. Your template repository was not modified."
