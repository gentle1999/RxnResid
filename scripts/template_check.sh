#!/usr/bin/env sh
if [ -n "${ZSH_VERSION:-}" ] && command -v emulate >/dev/null 2>&1; then
    emulate -L sh
fi
set -eu

script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
root_dir=$(CDPATH= cd -- "$script_dir/.." && pwd)
cd "$root_dir"

internal_config_file=${INTERNAL_CONFIG_FILE:-.templates/config/internal.env}
generated_files="README.md pyproject.toml mkdocs.yml .python-version uv.lock Dockerfile compose.yaml .dockerignore .gitea/workflows/ci.yaml .github/workflows/ci.yaml"

check_shell_syntax() {
    sh -n \
        scripts/configure_project.sh \
        scripts/configure_compatibility.sh \
        scripts/manage_docker.sh \
        scripts/check_actions.sh \
        scripts/check_compatibility_helpers.sh \
        scripts/init_demo.sh \
        scripts/template_check.sh \
        scripts/help.sh \
        scripts/lib/internal_config.sh \
        scripts/lib/compatibility.sh \
        scripts/lib/ci_render.sh \
        scripts/lib/render.sh
}

check_make_targets() {
    make -n help >/dev/null
    make -n setup >/dev/null
    make -n rebuild-env >/dev/null
    make skill-check
}

check_template_root_clean() {
    for file in $generated_files; do
        if [ -e "$file" ]; then
            echo "❌ Generated file should not exist in template root: $file" >&2
            exit 1
        fi
    done
}

check_template_sources() {
    grep -q '{{PACKAGE_NAME}}' .templates/project/pyproject.toml
    grep -q '{{PROJECT_TITLE}}' .templates/project/README.md
    grep -q '{{GITEA_USER}}' .templates/project/mkdocs.yml
    grep -q '^INTERNAL_GITEA_HOST=' "$internal_config_file"
    grep -q '^GITHUB_CHECKOUT_ACTION=' "$internal_config_file"
    grep -q '## 快速入口' README.dev.md
    grep -q 'make init-demo' README.dev.md
    grep -q '{{INTERNAL_GITEA_HOST}}' .templates/ci/gitea-ci.yaml.tpl
}

check_generated_workflows() {
    grep -q 'runner: windows-latest' .github/workflows/ci.yaml
    grep -q 'runner: macos-15-intel' .github/workflows/ci.yaml
    grep -q 'http://nas.asymcatml.net:13000/actions/checkout@v7' .gitea/workflows/ci.yaml
    grep -q 'uses: actions/checkout@v7' .github/workflows/ci.yaml
    grep -q 'uses: astral-sh/setup-uv@v8.2.0' .github/workflows/ci.yaml
    grep -q 'uses: softprops/action-gh-release@v3' .github/workflows/ci.yaml
    grep -q 'python3 -m pip install --user --upgrade -i "${INTERNAL_PYPI_INDEX}" uv' .gitea/workflows/ci.yaml
    grep -q 'uv sync --python 3.11 --all-extras --dev' .gitea/workflows/ci.yaml
    grep -q 'uv sync --python ${{ matrix.python-version }} --all-extras --dev --index "${{ env.PUBLIC_PYPI_INDEX }}"' .github/workflows/ci.yaml
    grep -q 'https://mirrors.zju.edu.cn/pypi/web/simple' pyproject.toml .github/workflows/ci.yaml
    ! grep -q 'runs-on: windows' .gitea/workflows/ci.yaml
    ! grep -q 'runs-on: macos-15-intel' .gitea/workflows/ci.yaml
}

check_generated_help() {
    help_output=$(make help)
    printf "%s\n" "$help_output" | grep -q 'First setup after cloning'
    printf "%s\n" "$help_output" | grep -q 'Full command reference: README.md'
    ! printf "%s\n" "$help_output" | grep -q 'make template-check'
    ! printf "%s\n" "$help_output" | grep -q 'make init-demo'
}

check_project_generation() {
    tmpdir=$(mktemp -d)
    trap 'rm -rf "$tmpdir"' EXIT INT TERM
    cp -a . "$tmpdir/repo"

    (
        cd "$tmpdir/repo"
        make configure-project \
            PACKAGE_NAME=demo_app \
            PROJECT_TITLE="Demo App" \
            PROJECT_DESCRIPTION="Internal demo service." \
            GITEA_USER=team \
            AUTHOR_NAME="Team Maintainers"
        make configure-compatibility \
            PYTHON_MIN=3.11 \
            PYTHON_MAX=3.13 \
            PLATFORMS="ubuntu-latest macos-latest windows-latest" \
            ARCHES="x86_64 aarch64" \
            TARGETS="ubuntu-latest/x86_64=ubuntu-latest ubuntu-latest/aarch64=linux-arm64 macos-latest/aarch64=macos-arm64"

        test -f README.md
        test -f pyproject.toml
        test -f mkdocs.yml
        test -f .github/workflows/ci.yaml
        test -f .gitea/workflows/ci.yaml
        check_generated_help

        ! grep -R -E '\{\{(PACKAGE_NAME|PROJECT_TITLE|PROJECT_DESCRIPTION|PROJECT_DESCRIPTION_TOML|PROJECT_TITLE_YAML|PROJECT_DESCRIPTION_YAML|AUTHOR_ENTRY|GITEA_HOST|GITEA_USER|INTERNAL_PYPI_INDEX|INTERNAL_GITEA_HOST|PUBLIC_PYPI_INDEX|ACT_PYPI_INDEX|PYTHON_INSTALL_MIRROR|GITEA_CHECKOUT_ACTION|GITHUB_CHECKOUT_ACTION|GITHUB_SETUP_UV_ACTION|GITHUB_RELEASE_ACTION)\}\}' \
            README.md pyproject.toml mkdocs.yml .github/workflows/ci.yaml .gitea/workflows/ci.yaml
        ! grep -R 'myrepositorytemplate\|MyRepositoryTemplate\|YOUR_USER\|Your Name\|you@example.com' \
            README.md pyproject.toml mkdocs.yml src tests docs
        check_generated_workflows
    )
}

echo "✅ Validating template repository structure..."
check_shell_syntax
sh scripts/check_compatibility_helpers.sh
check_make_targets
check_template_root_clean
check_template_sources
check_project_generation
echo "✅ Template check passed."
