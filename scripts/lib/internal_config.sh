#!/usr/bin/env sh

load_internal_config() {
    INTERNAL_CONFIG_FILE=${INTERNAL_CONFIG_FILE:-.templates/config/internal.env}

    if [ -f "$INTERNAL_CONFIG_FILE" ]; then
        # shellcheck disable=SC1090
        . "$INTERNAL_CONFIG_FILE"
    fi

    INTERNAL_GITEA_HOST=${INTERNAL_GITEA_HOST:-http://nas.asymcatml.net:13000}
    INTERNAL_PYPI_INDEX=${INTERNAL_PYPI_INDEX:-https://mirrors.zju.edu.cn/pypi/web/simple}
    PUBLIC_PYPI_INDEX=${PUBLIC_PYPI_INDEX:-https://pypi.org/simple}
    ACT_PYPI_INDEX=${ACT_PYPI_INDEX:-$INTERNAL_PYPI_INDEX}
    PYTHON_INSTALL_MIRROR=${PYTHON_INSTALL_MIRROR:-https://mirror.nju.edu.cn/github-release/astral-sh/python-build-standalone/}
    GITEA_CHECKOUT_ACTION=${GITEA_CHECKOUT_ACTION:-$INTERNAL_GITEA_HOST/actions/checkout@v7}
    GITHUB_CHECKOUT_ACTION=${GITHUB_CHECKOUT_ACTION:-actions/checkout@v7}
    GITHUB_SETUP_UV_ACTION=${GITHUB_SETUP_UV_ACTION:-astral-sh/setup-uv@v8.2.0}
    GITHUB_RELEASE_ACTION=${GITHUB_RELEASE_ACTION:-softprops/action-gh-release@v3}
}
