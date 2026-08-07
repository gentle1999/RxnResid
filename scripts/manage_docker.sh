#!/usr/bin/env sh
if [ -n "${ZSH_VERSION:-}" ] && command -v emulate >/dev/null 2>&1; then
    emulate -L sh
fi
set -eu

DOCKER_FILES="Dockerfile compose.yaml .dockerignore"
DOCKER_TEMPLATE_DIR=".templates/docker"
DOCKER_BACKUP_DIR=".templates/docker/removed"
CI_TEMPLATE_DIR=".templates/ci"
INTERNAL_CONFIG_FILE=".templates/config/internal.env"
INTERNAL_CONFIG_LIB="scripts/lib/internal_config.sh"
RENDER_LIB="scripts/lib/render.sh"

# shellcheck disable=SC1091
. "$INTERNAL_CONFIG_LIB"
load_internal_config
# shellcheck disable=SC1091
. "$RENDER_LIB"

usage() {
    cat <<'EOF'
Usage: scripts/manage_docker.sh {configure|remove|restore} [options]

Generate or remove Docker integration files and CI jobs.

Options for configure:
  --docker add|remove    Generate or remove Docker integration without prompting
                         keep/yes/no aliases are accepted for compatibility
EOF
}

remove_job() {
    workflow=$1
    job_name=${2:-docker-check}

    [ -f "$workflow" ] || return 0

    tmp="${workflow}.tmp"
    awk -v job="  ${job_name}:" '
        $0 == job { skipping = 1; next }
        skipping && /^  [^ ].*:$/ { skipping = 0 }
        !skipping { print }
    ' "$workflow" > "$tmp"
    mv "$tmp" "$workflow"
}

insert_job() {
    workflow=$1
    snippet=$2
    before_job=$3

    [ -f "$workflow" ] || return 0
    [ -f "$snippet" ] || return 0

    if grep -q "^  docker-check:$" "$workflow"; then
        return 0
    fi

    tmp="${workflow}.tmp"
    rendered_snippet=$(mktemp)
    render_action_template "$snippet" "$rendered_snippet"

    awk -v marker="  ${before_job}:" -v snippet="$rendered_snippet" '
        function print_snippet() {
            while ((getline line < snippet) > 0) {
                print line
            }
            close(snippet)
        }
        $0 == marker && inserted == 0 {
            print ""
            print_snippet()
            print ""
            inserted = 1
        }
        { print }
        END {
            if (inserted == 0) {
                print ""
                print_snippet()
            }
        }
    ' "$workflow" > "$tmp"
    mv "$tmp" "$workflow"
    rm -f "$rendered_snippet"
}

remove_docker() {
    mkdir -p "$DOCKER_BACKUP_DIR"

    for file in $DOCKER_FILES; do
        if [ -f "$file" ]; then
            mv "$file" "$DOCKER_BACKUP_DIR/$file"
            echo "  moved $file -> $DOCKER_BACKUP_DIR/$file"
        fi
    done

    remove_job ".gitea/workflows/ci.yaml" "docker-check"
    remove_job ".github/workflows/ci.yaml" "docker-check"
}

restore_docker() {
    if [ ! -f pyproject.toml ]; then
        echo "Missing pyproject.toml. Run 'make configure-project' or 'make init' first." >&2
        exit 1
    fi

    for file in $DOCKER_FILES; do
        if [ -f "$DOCKER_BACKUP_DIR/$file" ]; then
            cp "$DOCKER_BACKUP_DIR/$file" "$file"
            echo "  restored $file from backup"
        elif [ -f "$DOCKER_TEMPLATE_DIR/$file" ]; then
            cp "$DOCKER_TEMPLATE_DIR/$file" "$file"
            echo "  restored $file from template"
        else
            echo "Missing Docker template for $file" >&2
            exit 1
        fi
    done

    insert_job ".gitea/workflows/ci.yaml" "$CI_TEMPLATE_DIR/docker-check.gitea.yaml" "publish"
    insert_job ".github/workflows/ci.yaml" "$CI_TEMPLATE_DIR/docker-check.github.yaml" "deploy"
}

prompt_docker_choice() {
    printf "👉 Enable Docker integration? [y/N]: " >&2
    IFS= read -r value
    case "$value" in
        y|Y|yes|YES|Yes|add|ADD|enable|ENABLE|keep|KEEP)
            printf "add"
            ;;
        ""|n|N|no|NO|No|remove|REMOVE|disable|DISABLE|none|NONE)
            printf "remove"
            ;;
        *)
            echo "Please answer y or n" >&2
            prompt_docker_choice
            ;;
    esac
}

configure_docker() {
    choice=""
    while [ "$#" -gt 0 ]; do
        case "$1" in
            --docker)
                choice="${2:-}"
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

    if [ -z "$choice" ]; then
        choice=$(prompt_docker_choice)
    fi

    case "$choice" in
        add|ADD|enable|ENABLE|keep|KEEP|y|Y|yes|YES|Yes)
            restore_docker
            echo "✅ Docker integration generated."
            ;;
        remove|REMOVE|disable|DISABLE|none|NONE|n|N|no|NO|No)
            remove_docker
            echo "✅ Docker integration removed."
            ;;
        *)
            echo "Docker option must be add or remove" >&2
            exit 1
            ;;
    esac
}

case "${1:-}" in
    configure)
        shift
        configure_docker "$@"
        ;;
    remove)
        remove_docker
        ;;
    restore)
        restore_docker
        ;;
    -h|--help)
        usage
        ;;
    *)
        usage >&2
        exit 1
        ;;
esac
