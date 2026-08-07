#!/usr/bin/env sh
if [ -n "${ZSH_VERSION:-}" ] && command -v emulate >/dev/null 2>&1; then
    emulate -L sh
fi
set -eu

DEFAULT_PYTHON_MIN="3.11"
DEFAULT_PYTHON_MAX="3.13"
DEFAULT_TARGETS="ubuntu-latest/x86_64=ubuntu-latest ubuntu-latest/aarch64=linux-arm64 macos-latest/aarch64=macos-arm64"
DEFAULT_PLATFORMS="ubuntu-latest macos-latest windows-latest"
DEFAULT_ARCHES="x86_64 aarch64"
INTERNAL_CONFIG_FILE=".templates/config/internal.env"
INTERNAL_CONFIG_LIB="scripts/lib/internal_config.sh"
COMPATIBILITY_LIB="scripts/lib/compatibility.sh"
RENDER_LIB="scripts/lib/render.sh"
CI_RENDER_LIB="scripts/lib/ci_render.sh"
PYTHON_MIN=""
PYTHON_MAX=""
PLATFORMS=""
ARCHES=""
TARGETS=""
REMOVE_PLATFORMS=""
REMOVE_ARCHES=""
REMOVE_TARGETS=""

usage() {
    cat <<'EOF'
Usage: scripts/configure_compatibility.sh [options]

Configure supported Python versions, CI platforms, and CPU architectures before
the Python environment exists.

Options:
  --python-min VERSION     Minimum supported Python version, for example 3.11
  --python-max VERSION     Maximum supported Python version, for example 3.13
  --platforms LIST         Space or comma separated supported CI platforms.
                           GitHub mirror uses the full platform/arch matrix.
                           aliases: linux/ubuntu, mac/macos/darwin, win/windows
  --arches LIST            Space or comma separated supported CPU architectures.
                           GitHub mirror uses the full platform/arch matrix.
                           aliases: x86/x64/amd64/x86_64, arm64/aarch/aarch64
  --targets LIST           Explicit target list. Each item is platform/arch or
                           platform/arch=runner-label, for example:
                           ubuntu-latest/aarch64=linux-arm64
  --remove-platforms LIST  Platforms to remove from the default platform set
  --remove-arches LIST     Architectures to remove from the default arch set
  --remove-targets LIST    Gitea target pairs to remove, for example linux/aarch64
  --python-version VERSION Compatibility alias for --python-min
  --default-min VERSION    Default minimum Python version for prompts
  --default-max VERSION    Default maximum Python version for prompts
  --default-targets LIST   Default internal platform/arch=runner target list
  --default-platforms LIST Default platform list for prompts
  --default-arches LIST    Default architecture list for prompts
  -h, --help               Show this help
EOF
}

while [ "$#" -gt 0 ]; do
    case "$1" in
        --python-min)
            PYTHON_MIN="${2:-}"
            shift 2
            ;;
        --python-max)
            PYTHON_MAX="${2:-}"
            shift 2
            ;;
        --platforms)
            PLATFORMS="${2:-}"
            shift 2
            ;;
        --arches)
            ARCHES="${2:-}"
            shift 2
            ;;
        --targets)
            TARGETS="${2:-}"
            shift 2
            ;;
        --remove-platforms)
            REMOVE_PLATFORMS="${2:-}"
            shift 2
            ;;
        --remove-arches)
            REMOVE_ARCHES="${2:-}"
            shift 2
            ;;
        --remove-targets)
            REMOVE_TARGETS="${2:-}"
            shift 2
            ;;
        --python-version)
            PYTHON_MIN="${2:-}"
            shift 2
            ;;
        --default-min)
            DEFAULT_PYTHON_MIN="${2:-}"
            shift 2
            ;;
        --default-max)
            DEFAULT_PYTHON_MAX="${2:-}"
            shift 2
            ;;
        --default-targets)
            DEFAULT_TARGETS="${2:-}"
            shift 2
            ;;
        --default-platforms)
            DEFAULT_PLATFORMS="${2:-}"
            shift 2
            ;;
        --default-arches)
            DEFAULT_ARCHES="${2:-}"
            shift 2
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        *)
            echo "Unknown option: $1" >&2
            usage >&2
            exit 1
            ;;
    esac
done

script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
root_dir=$(CDPATH= cd -- "$script_dir/.." && pwd)
cd "$root_dir"

# shellcheck disable=SC1091
. "$INTERNAL_CONFIG_LIB"
load_internal_config
# shellcheck disable=SC1091
. "$COMPATIBILITY_LIB"
# shellcheck disable=SC1091
. "$RENDER_LIB"
# shellcheck disable=SC1091
. "$CI_RENDER_LIB"

DEFAULT_TARGETS=${INTERNAL_DEFAULT_GITEA_TARGETS:-$DEFAULT_TARGETS}
DEFAULT_PLATFORMS=${INTERNAL_DEFAULT_PLATFORMS:-$DEFAULT_PLATFORMS}
DEFAULT_ARCHES=${INTERNAL_DEFAULT_ARCHES:-$DEFAULT_ARCHES}

CI_TEMPLATE_DIR=".templates/ci"

require_project_config() {
    for file in pyproject.toml mkdocs.yml; do
        if [ ! -f "$file" ]; then
            echo "Missing $file. Run 'make configure-project' or 'make init' first." >&2
            exit 1
        fi
    done
}

prompt_default() {
    prompt=$1
    default=$2
    printf "%s (default: %s): " "$prompt" "$default" >&2
    IFS= read -r value
    if [ -z "$value" ]; then
        value=$default
    fi
    printf "%s" "$value"
}

prompt_removed_platforms() {
    default=$1

    echo "📌 Enabled CI platforms by default:" >&2
    printf "%s\n" "$default" | tr ',' ' ' | awk '{ for (i = 1; i <= NF; i++) print "  - " $i }' >&2
    printf "👉 Enter platforms to remove, or press Enter to keep all: " >&2
    IFS= read -r value
    printf "%s" "$value"
}

prompt_removed_arches() {
    default=$1

    echo "📌 Enabled CPU architectures by default:" >&2
    printf "%s\n" "$default" | tr ',' ' ' | awk '{ for (i = 1; i <= NF; i++) print "  - " $i }' >&2
    printf "👉 Enter architectures to remove, or press Enter to keep all: " >&2
    IFS= read -r value
    printf "%s" "$value"
}

prompt_removed_targets() {
    targets_text=$1

    echo "📌 Enabled CI target combinations:" >&2
    printf "%s\n" "$targets_text" | awk -F'|' '{ print "  - " $1 "/" $2 " -> " $3 }' >&2
    printf "👉 Enter target combinations to remove, or press Enter to keep all: " >&2
    IFS= read -r value
    printf "%s" "$value"
}

replace_line() {
    file=$1
    pattern=$2
    replacement=$3

    [ -f "$file" ] || return 0
    sed -i.bak "s#${pattern}#${replacement}#" "$file"
    rm -f "${file}.bak"
}

set_config_variable() {
    file=$1
    name=$2
    value=$3

    [ -f "$file" ] || return 0
    tmp="${file}.tmp"
    awk -v name="$name" -v value="$value" '
        index($0, name "=") == 1 {
            print name "=" value
            updated = 1
            next
        }
        { print }
        END {
            if (updated == 0) {
                print name "=" value
            }
        }
    ' "$file" > "$tmp"
    mv "$tmp" "$file"
}

comma_list_from_lines() {
    paste -sd ',' -
}

target_list_for_config() {
    awk -F'|' '
        $1 != "" {
            printf "%s%s/%s=%s", sep, $1, $2, $3
            sep = ","
        }
        END { print "" }
    '
}

python_versions_for_range() {
    min_version=$1
    max_version=$2

    awk -v min_version="$min_version" -v max_version="$max_version" '
        BEGIN {
            split(min_version, min_parts, ".")
            split(max_version, max_parts, ".")

            for (minor = min_parts[2]; minor <= max_parts[2]; minor++) {
                print "3." minor
            }
        }
    '
}

upper_bound_python() {
    max_version=$1
    major=$(printf "%s\n" "$max_version" | awk -F. '{ print $1 }')
    minor=$(printf "%s\n" "$max_version" | awk -F. '{ print $2 + 1 }')
    printf "%s.%s" "$major" "$minor"
}

update_python_classifiers() {
    file=$1
    min_version=$2
    max_version=$3

    [ -f "$file" ] || return 0

    tmp="${file}.tmp"
    awk -v min_version="$min_version" -v max_version="$max_version" '
        function emit_versions() {
            split(min_version, min_parts, ".")
            split(max_version, max_parts, ".")

            for (minor = min_parts[2]; minor <= max_parts[2]; minor++) {
                print "    \"Programming Language :: Python :: 3." minor "\","
            }
        }

        /"Programming Language :: Python :: [0-9][0-9]*[.][0-9][0-9.]*",/ {
            if (printed == 0) {
                emit_versions()
                printed = 1
            }
            next
        }
        { print }
    ' "$file" > "$tmp"
    mv "$tmp" "$file"
}

update_platform_classifiers() {
    file=$1
    platforms_text=$2

    [ -f "$file" ] || return 0

    platforms_file=$(mktemp)
    printf "%s\n" "$platforms_text" > "$platforms_file"

    tmp="${file}.tmp"
    awk -v platforms_file="$platforms_file" '
        function emit_platforms(    platform) {
            while ((getline platform < platforms_file) > 0) {
                if (platform == "ubuntu-latest") {
                    print "    \"Operating System :: POSIX :: Linux\","
                } else if (platform == "macos-latest") {
                    print "    \"Operating System :: MacOS\","
                } else if (platform == "windows-latest") {
                    print "    \"Operating System :: Microsoft :: Windows\","
                }
            }
            close(platforms_file)
        }

        /"Operating System :: / {
            if (printed == 0) {
                emit_platforms()
                printed = 1
            }
            next
        }

        /"Programming Language :: Python :: 3",/ && printed == 0 {
            emit_platforms()
            printed = 1
        }

        { print }
    ' "$file" > "$tmp"
    mv "$tmp" "$file"
    rm -f "$platforms_file"
}

update_compatibility() {
    min_version=$1
    max_version=$2
    github_targets_text=$3
    gitea_targets_text=$4

    min_major_minor=$(python_major_minor "$min_version")
    max_major_minor=$(python_major_minor "$max_version")
    upper_bound=$(upper_bound_python "$max_major_minor")
    ruff_target=$(printf "%s\n" "$min_major_minor" | awk -F. '{ print "py" $1 $2 }')
    python_versions=$(python_versions_for_range "$min_major_minor" "$max_major_minor")
    target_platforms=$(printf "%s\n" "$github_targets_text" | unique_target_field 1)
    target_arches=$(printf "%s\n" "$github_targets_text" | unique_target_field 2)

    matrix_block=$(mktemp)
    gitea_jobs_block=$(mktemp)
    gitea_needs_block=$(mktemp)
    write_ci_matrix_block "$matrix_block" "$github_targets_text" "$python_versions"
    write_gitea_jobs_block "$gitea_jobs_block" "$gitea_targets_text" "$python_versions"
    write_gitea_needs_block "$gitea_needs_block" "$gitea_targets_text" "$python_versions"

    echo "📌 Pinning local Python to $min_version (.python-version)..."
    printf "%s\n" "$min_version" > .python-version

    echo "📝 Updating project metadata and CI compatibility matrix..."
    replace_line pyproject.toml '^requires-python = .*' "requires-python = \">=$min_version,<$upper_bound\""
    replace_line pyproject.toml '^target-version = .*' "target-version = \"$ruff_target\""
    update_platform_classifiers pyproject.toml "$target_platforms"
    update_python_classifiers pyproject.toml "$min_major_minor" "$max_major_minor"
    replace_line .templates/project/pyproject.toml '^requires-python = .*' "requires-python = \">=$min_version,<$upper_bound\""
    replace_line .templates/project/pyproject.toml '^target-version = .*' "target-version = \"$ruff_target\""
    update_platform_classifiers .templates/project/pyproject.toml "$target_platforms"
    update_python_classifiers .templates/project/pyproject.toml "$min_major_minor" "$max_major_minor"
    replace_line Makefile '^DEFAULT_PYTHON_MIN := .*' "DEFAULT_PYTHON_MIN := $min_major_minor"
    replace_line Makefile '^DEFAULT_PYTHON_MAX := .*' "DEFAULT_PYTHON_MAX := $max_major_minor"
    set_config_variable "$INTERNAL_CONFIG_FILE" "INTERNAL_DEFAULT_GITEA_TARGETS" "$(printf "%s\n" "$gitea_targets_text" | target_list_for_config)"
    set_config_variable "$INTERNAL_CONFIG_FILE" "INTERNAL_DEFAULT_PLATFORMS" "$(printf "%s\n" "$target_platforms" | comma_list_from_lines)"
    set_config_variable "$INTERNAL_CONFIG_FILE" "INTERNAL_DEFAULT_ARCHES" "$(printf "%s\n" "$target_arches" | comma_list_from_lines)"
    write_ci_workflows "$matrix_block" "$gitea_jobs_block" "$gitea_needs_block"
    replace_line Dockerfile 'uv:python[0-9][0-9.]*-bookworm-slim' "uv:python${min_major_minor}-bookworm-slim"
    replace_line Dockerfile 'python:[0-9][0-9.]*-slim-bookworm' "python:${min_major_minor}-slim-bookworm"
    replace_line .templates/docker/Dockerfile 'uv:python[0-9][0-9.]*-bookworm-slim' "uv:python${min_major_minor}-bookworm-slim"
    replace_line .templates/docker/Dockerfile 'python:[0-9][0-9.]*-slim-bookworm' "python:${min_major_minor}-slim-bookworm"
    rm -f "$matrix_block" "$gitea_jobs_block" "$gitea_needs_block"
}

if [ -z "$PYTHON_MIN" ]; then
    PYTHON_MIN=$(prompt_default "👉 Enter minimum supported Python version" "$DEFAULT_PYTHON_MIN")
fi

if [ -z "$PYTHON_MAX" ]; then
    PYTHON_MAX=$(prompt_default "👉 Enter maximum supported Python version" "$DEFAULT_PYTHON_MAX")
fi

validate_python_range "$PYTHON_MIN" "$PYTHON_MAX"

if [ -z "$PLATFORMS" ]; then
    if [ -z "$REMOVE_PLATFORMS" ]; then
        if [ -z "$TARGETS" ]; then
            REMOVE_PLATFORMS=$(prompt_removed_platforms "$DEFAULT_PLATFORMS")
        fi
    fi
    normalized_platforms=$(normalize_platforms "$DEFAULT_PLATFORMS")
else
    normalized_platforms=$(normalize_platforms "$PLATFORMS")
fi

if [ -z "$ARCHES" ]; then
    if [ -z "$REMOVE_ARCHES" ]; then
        if [ -z "$TARGETS" ]; then
            REMOVE_ARCHES=$(prompt_removed_arches "$DEFAULT_ARCHES")
        fi
    fi
    normalized_arches=$(normalize_arches "$DEFAULT_ARCHES")
else
    normalized_arches=$(normalize_arches "$ARCHES")
fi

normalized_removed_platforms=""
normalized_removed_arches=""
if [ -n "$REMOVE_PLATFORMS" ]; then
    normalized_removed_platforms=$(normalize_platforms "$REMOVE_PLATFORMS")
fi
if [ -n "$REMOVE_ARCHES" ]; then
    normalized_removed_arches=$(normalize_arches "$REMOVE_ARCHES")
fi

github_base_targets=$(build_github_targets "$normalized_platforms" "$normalized_arches")
github_targets=$(filter_removed_targets "$github_base_targets" "$normalized_removed_platforms" "$normalized_removed_arches" "")

if [ -z "$github_targets" ]; then
    echo "At least one supported CI target is required" >&2
    exit 1
fi

if [ -n "$TARGETS" ]; then
    gitea_base_targets=$(normalize_targets "$TARGETS")
else
    gitea_base_targets=$(normalize_targets "$DEFAULT_TARGETS")
fi

supported_pairs=$(printf "%s\n" "$github_targets" | target_pairs)
gitea_supported_targets=$(filter_targets_by_pairs "$gitea_base_targets" "$supported_pairs")
normalized_removed_targets=""
if [ -z "$REMOVE_TARGETS" ] && [ -z "$TARGETS" ] && [ -z "$PLATFORMS" ] && [ -z "$ARCHES" ]; then
    REMOVE_TARGETS=$(prompt_removed_targets "$gitea_supported_targets")
fi
if [ -n "$REMOVE_TARGETS" ]; then
    normalized_removed_targets=$(normalize_target_pairs "$REMOVE_TARGETS")
fi

gitea_targets=$(filter_removed_targets "$gitea_supported_targets" "" "" "$normalized_removed_targets")

if [ -z "$gitea_targets" ]; then
    echo "At least one Gitea CI target with an internal runner is required" >&2
    exit 1
fi

require_project_config
update_compatibility "$PYTHON_MIN" "$PYTHON_MAX" "$github_targets" "$gitea_targets"
