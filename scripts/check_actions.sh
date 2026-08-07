#!/usr/bin/env sh
if [ -n "${ZSH_VERSION:-}" ] && command -v emulate >/dev/null 2>&1; then
    emulate -L sh
fi
set -eu

script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
root_dir=$(CDPATH= cd -- "$script_dir/.." && pwd)
cd "$root_dir"

INTERNAL_CONFIG_FILE=".templates/config/internal.env"
# shellcheck disable=SC1091
. scripts/lib/internal_config.sh
load_internal_config

check_major_action() {
    action_ref=$1
    repo_url=$2
    current_major=$3

    latest_major=$(
        git ls-remote --tags "$repo_url" 'refs/tags/v[0-9]*' |
            sed -n 's#.*refs/tags/v\([0-9][0-9]*\)\(\..*\)\{0,1\}\(\^{}\)\{0,1\}$#\1#p' |
            sort -n |
            tail -1
    )

    if [ -z "$latest_major" ]; then
        echo "Cannot determine latest major for $action_ref" >&2
        return 1
    fi

    if [ "$current_major" != "$latest_major" ]; then
        echo "$action_ref is behind: v$current_major < v$latest_major" >&2
        return 1
    fi

    echo "$action_ref is current at v$current_major"
}

check_exact_action() {
    action_ref=$1
    repo_url=$2
    current_version=$3

    latest_version=$(
        git ls-remote --tags "$repo_url" 'refs/tags/v[0-9]*' |
            sed -n 's#.*refs/tags/v\([0-9][0-9]*[.][0-9][0-9]*[.][0-9][0-9]*\)\(\^{}\)\{0,1\}$#\1#p' |
            sort -t. -k1,1n -k2,2n -k3,3n |
            tail -1
    )

    if [ -z "$latest_version" ]; then
        echo "Cannot determine latest version for $action_ref" >&2
        return 1
    fi

    if [ "$current_version" != "$latest_version" ]; then
        echo "$action_ref is behind: v$current_version < v$latest_version" >&2
        return 1
    fi

    echo "$action_ref is current at v$current_version"
}

case "$GITHUB_CHECKOUT_ACTION" in
    actions/checkout@v*)
        checkout_major=${GITHUB_CHECKOUT_ACTION#actions/checkout@v}
        checkout_major=${checkout_major%%.*}
        ;;
    *)
        echo "Unsupported GITHUB_CHECKOUT_ACTION: $GITHUB_CHECKOUT_ACTION" >&2
        exit 1
        ;;
esac

case "$GITEA_CHECKOUT_ACTION" in
    *@v*)
        gitea_checkout_major=${GITEA_CHECKOUT_ACTION##*@v}
        gitea_checkout_major=${gitea_checkout_major%%.*}
        ;;
    *)
        echo "Unsupported GITEA_CHECKOUT_ACTION: $GITEA_CHECKOUT_ACTION" >&2
        exit 1
        ;;
esac

case "$GITHUB_SETUP_UV_ACTION" in
    astral-sh/setup-uv@v*)
        setup_uv_version=${GITHUB_SETUP_UV_ACTION#astral-sh/setup-uv@v}
        ;;
    *)
        echo "Unsupported GITHUB_SETUP_UV_ACTION: $GITHUB_SETUP_UV_ACTION" >&2
        exit 1
        ;;
esac

case "$GITHUB_RELEASE_ACTION" in
    softprops/action-gh-release@v*)
        release_major=${GITHUB_RELEASE_ACTION#softprops/action-gh-release@v}
        release_major=${release_major%%.*}
        ;;
    *)
        echo "Unsupported GITHUB_RELEASE_ACTION: $GITHUB_RELEASE_ACTION" >&2
        exit 1
        ;;
esac

check_major_action "$GITHUB_CHECKOUT_ACTION" https://github.com/actions/checkout.git "$checkout_major"
check_major_action "$GITEA_CHECKOUT_ACTION" https://github.com/actions/checkout.git "$gitea_checkout_major"
check_exact_action "$GITHUB_SETUP_UV_ACTION" https://github.com/astral-sh/setup-uv.git "$setup_uv_version"
check_major_action "$GITHUB_RELEASE_ACTION" https://github.com/softprops/action-gh-release.git "$release_major"
