# =============================================================================
# 🛠️ MyRepositoryTemplate Makefile (Production Ready)
# =============================================================================

comma := ,
INTERNAL_CONFIG_FILE ?= .templates/config/internal.env
ifneq ($(wildcard $(INTERNAL_CONFIG_FILE)),)
include $(INTERNAL_CONFIG_FILE)
endif

INTERNAL_GITEA_HOST ?= http://nas.asymcatml.net:13000
INTERNAL_PYPI_INDEX ?= https://mirrors.zju.edu.cn/pypi/web/simple
PUBLIC_PYPI_INDEX ?= https://pypi.org/simple
ACT_PYPI_INDEX ?= $(INTERNAL_PYPI_INDEX)
PYTHON_INSTALL_MIRROR ?= https://mirror.nju.edu.cn/github-release/astral-sh/python-build-standalone/
GITEA_CHECKOUT_ACTION ?= $(INTERNAL_GITEA_HOST)/actions/checkout@v7
GITHUB_CHECKOUT_ACTION ?= actions/checkout@v7
GITHUB_SETUP_UV_ACTION ?= astral-sh/setup-uv@v8.2.0
GITHUB_RELEASE_ACTION ?= softprops/action-gh-release@v3
ACT_IMAGE ?= catthehacker/ubuntu:act-latest
INTERNAL_DEFAULT_GITEA_TARGETS ?= ubuntu-latest/x86_64=ubuntu-latest,ubuntu-latest/aarch64=linux-arm64,macos-latest/aarch64=macos-arm64
INTERNAL_DEFAULT_PLATFORMS ?= ubuntu-latest,macos-latest,windows-latest
INTERNAL_DEFAULT_ARCHES ?= x86_64,aarch64
DEFAULT_GITEA_TARGETS := $(subst $(comma), ,$(INTERNAL_DEFAULT_GITEA_TARGETS))
DEFAULT_PLATFORMS := $(subst $(comma), ,$(INTERNAL_DEFAULT_PLATFORMS))
DEFAULT_ARCHES := $(subst $(comma), ,$(INTERNAL_DEFAULT_ARCHES))

# ⚠️ 模板使用者请修改这里：你的包名（对应 src/ 下的目录名）
PACKAGE_NAME := myrepositorytemplate
GITEA_HOST := $(INTERNAL_GITEA_HOST)
GITEA_USER := YOUR_USER
PROJECT_TITLE :=
PROJECT_DESCRIPTION :=
AUTHOR_NAME :=
AUTHOR_EMAIL :=
DEFAULT_PYTHON_MIN := 3.11
DEFAULT_PYTHON_MAX := 3.13
ACT ?= act
ACT_WORKFLOW ?= .github/workflows/ci.yaml
ACT_EVENT ?= workflow_dispatch
ACT_JOB ?= build-and-test
ACT_PLATFORM ?= ubuntu-latest
ACT_ARCH ?= x86_64
ACT_PYTHON ?= $(DEFAULT_PYTHON_MIN)
ACT_CONTAINER_ARCH ?= $(if $(filter aarch64 arm64,$(ACT_ARCH)),linux/arm64,linux/amd64)
ACT_PLATFORM_ARGS ?= -P ubuntu-latest=$(ACT_IMAGE) -P ubuntu-24.04-arm=$(ACT_IMAGE) -P ubuntu-22.04-arm=$(ACT_IMAGE)
ACT_ARGS ?= --no-skip-checkout
SKILL_NAME := python-internal-template
SKILL_DIR := .codex/skills/$(SKILL_NAME)
SKILL_VALIDATOR ?= $(HOME)/.codex/skills/.system/skill-creator/scripts/quick_validate.py
SKILL_INSTALL_DIR ?= $(if $(CODEX_HOME),$(CODEX_HOME),$(HOME)/.codex)/skills
INIT_DEMO_TARGETS := ubuntu-latest/x86_64=ubuntu-latest ubuntu-latest/aarch64=linux-arm64 macos-latest/aarch64=macos-arm64
AUDIT_ARGS ?=

CONFIG_PACKAGE_NAME := $(strip $(PACKAGE_NAME))
CONFIG_GITEA_HOST := $(strip $(GITEA_HOST))
CONFIG_GITEA_USER := $(strip $(GITEA_USER))
CONFIG_PROJECT_TITLE := $(strip $(PROJECT_TITLE))
CONFIG_PROJECT_DESCRIPTION := $(strip $(PROJECT_DESCRIPTION))
CONFIG_AUTHOR_NAME := $(strip $(AUTHOR_NAME))
CONFIG_AUTHOR_EMAIL := $(strip $(AUTHOR_EMAIL))
CONFIG_PYTHON_MIN_VERSION := $(strip $(PYTHON_MIN))
ifeq ($(CONFIG_PYTHON_MIN_VERSION),)
CONFIG_PYTHON_MIN_VERSION := $(strip $(PYTHON_VERSION))
endif
ifeq ($(CONFIG_PYTHON_MIN_VERSION),)
ifneq ($(origin PYTHON),undefined)
ifneq ($(origin PYTHON),environment)
CONFIG_PYTHON_MIN_VERSION := $(strip $(PYTHON))
endif
endif
endif
CONFIG_PYTHON_MAX_VERSION := $(strip $(PYTHON_MAX))
CONFIG_PLATFORMS := $(strip $(PLATFORMS))
CONFIG_ARCHES := $(strip $(ARCHES))
CONFIG_TARGETS := $(strip $(TARGETS))
CONFIG_REMOVE_PLATFORMS := $(strip $(REMOVE_PLATFORMS))
CONFIG_REMOVE_ARCHES := $(strip $(REMOVE_ARCHES))
CONFIG_REMOVE_TARGETS := $(strip $(REMOVE_TARGETS))
CONFIG_DOCKER := $(strip $(DOCKER))
CONFIG_PROJECT_ARGS :=
CONFIG_USER_ARGS :=
COMPATIBILITY_ARGS :=
DOCKER_CONFIG_ARGS :=

ifneq ($(origin PACKAGE_NAME),file)
CONFIG_PROJECT_ARGS += --package-name $(CONFIG_PACKAGE_NAME)
else
ifneq ($(CONFIG_PACKAGE_NAME),myrepositorytemplate)
CONFIG_PROJECT_ARGS += --package-name $(CONFIG_PACKAGE_NAME)
endif
endif
ifneq ($(origin GITEA_HOST),file)
CONFIG_PROJECT_ARGS += --gitea-host "$(CONFIG_GITEA_HOST)"
CONFIG_USER_ARGS += --gitea-host "$(CONFIG_GITEA_HOST)"
else
ifneq ($(CONFIG_GITEA_HOST),$(INTERNAL_GITEA_HOST))
CONFIG_PROJECT_ARGS += --gitea-host "$(CONFIG_GITEA_HOST)"
CONFIG_USER_ARGS += --gitea-host "$(CONFIG_GITEA_HOST)"
endif
endif
ifneq ($(origin GITEA_USER),file)
CONFIG_PROJECT_ARGS += --gitea-user $(CONFIG_GITEA_USER)
CONFIG_USER_ARGS += --gitea-user $(CONFIG_GITEA_USER)
else
ifneq ($(CONFIG_GITEA_USER),YOUR_USER)
CONFIG_PROJECT_ARGS += --gitea-user $(CONFIG_GITEA_USER)
CONFIG_USER_ARGS += --gitea-user $(CONFIG_GITEA_USER)
endif
endif
ifneq ($(CONFIG_PROJECT_TITLE),)
CONFIG_PROJECT_ARGS += --project-title "$(CONFIG_PROJECT_TITLE)"
endif
ifneq ($(CONFIG_PROJECT_DESCRIPTION),)
CONFIG_PROJECT_ARGS += --description "$(CONFIG_PROJECT_DESCRIPTION)"
endif
ifneq ($(CONFIG_AUTHOR_NAME),)
CONFIG_PROJECT_ARGS += --author-name "$(CONFIG_AUTHOR_NAME)"
endif
ifneq ($(CONFIG_AUTHOR_EMAIL),)
CONFIG_PROJECT_ARGS += --author-email "$(CONFIG_AUTHOR_EMAIL)"
endif
ifneq ($(CONFIG_PYTHON_MIN_VERSION),)
COMPATIBILITY_ARGS += --python-min $(CONFIG_PYTHON_MIN_VERSION)
endif
ifneq ($(CONFIG_PYTHON_MAX_VERSION),)
COMPATIBILITY_ARGS += --python-max $(CONFIG_PYTHON_MAX_VERSION)
else
ifneq ($(CONFIG_PYTHON_MIN_VERSION),)
COMPATIBILITY_ARGS += --python-max $(DEFAULT_PYTHON_MAX)
endif
endif
ifneq ($(CONFIG_PYTHON_MAX_VERSION),)
ifeq ($(CONFIG_PYTHON_MIN_VERSION),)
COMPATIBILITY_ARGS += --python-min $(DEFAULT_PYTHON_MIN)
endif
endif
ifneq ($(CONFIG_PLATFORMS),)
ifeq ($(CONFIG_PYTHON_MIN_VERSION),)
ifeq ($(CONFIG_PYTHON_MAX_VERSION),)
COMPATIBILITY_ARGS += --python-min $(DEFAULT_PYTHON_MIN) --python-max $(DEFAULT_PYTHON_MAX)
endif
endif
endif
ifneq ($(CONFIG_PLATFORMS),)
COMPATIBILITY_ARGS += --platforms "$(CONFIG_PLATFORMS)"
else
ifeq ($(CONFIG_TARGETS),)
ifneq ($(CONFIG_PYTHON_MIN_VERSION),)
COMPATIBILITY_ARGS += --platforms "$(DEFAULT_PLATFORMS)"
else
ifneq ($(CONFIG_PYTHON_MAX_VERSION),)
COMPATIBILITY_ARGS += --platforms "$(DEFAULT_PLATFORMS)"
endif
endif
endif
endif
ifneq ($(CONFIG_ARCHES),)
COMPATIBILITY_ARGS += --arches "$(CONFIG_ARCHES)"
else
ifeq ($(CONFIG_TARGETS),)
ifneq ($(CONFIG_PYTHON_MIN_VERSION),)
COMPATIBILITY_ARGS += --arches "$(DEFAULT_ARCHES)"
else
ifneq ($(CONFIG_PYTHON_MAX_VERSION),)
COMPATIBILITY_ARGS += --arches "$(DEFAULT_ARCHES)"
else
ifneq ($(CONFIG_PLATFORMS),)
COMPATIBILITY_ARGS += --arches "$(DEFAULT_ARCHES)"
endif
endif
endif
endif
endif
ifneq ($(CONFIG_TARGETS),)
COMPATIBILITY_ARGS += --targets "$(CONFIG_TARGETS)"
endif
ifneq ($(CONFIG_REMOVE_PLATFORMS),)
COMPATIBILITY_ARGS += --remove-platforms "$(CONFIG_REMOVE_PLATFORMS)"
endif
ifneq ($(CONFIG_REMOVE_ARCHES),)
COMPATIBILITY_ARGS += --remove-arches "$(CONFIG_REMOVE_ARCHES)"
endif
ifneq ($(CONFIG_REMOVE_TARGETS),)
COMPATIBILITY_ARGS += --remove-targets "$(CONFIG_REMOVE_TARGETS)"
endif
ifneq ($(CONFIG_DOCKER),)
DOCKER_CONFIG_ARGS += --docker "$(CONFIG_DOCKER)"
endif

# --- 自动检测版本号 ---
# 尝试通过 importlib 读取已安装包的版本，如果失败则显示 "dynamic"
VERSION := $(shell if [ -f pyproject.toml ] && command -v uv >/dev/null 2>&1; then uv run python -c "from importlib.metadata import version; print(version('$(PACKAGE_NAME)'))" 2>/dev/null || echo "dynamic"; else echo "dynamic"; fi)

# 检测操作系统，用于打开浏览器命令
DETECTED_OS := $(shell uname)
ifeq ($(DETECTED_OS), Darwin)
	OPEN_CMD := open
else
	OPEN_CMD := xdg-open
endif

.DEFAULT_GOAL := help

.PHONY: help info doctor init init-demo install-uv install setup rebuild-env configure-project configure-user configure-compatibility configure-docker pin-python sync sync-frozen lock lock-check update tree format format-check lint lint-fix type-check check test test-cov smoke docs-serve docs-build docs-check clean distclean build release audit template-check action-check skill-check skill-install act-check act-list act-dry-run act-ci ci-local docker-remove docker-restore docker-build docker-check docker-up docker-down

# =============================================================================
# 📝 帮助文档
# =============================================================================
help:
	@PACKAGE_NAME="$(PACKAGE_NAME)" VERSION="$(VERSION)" sh scripts/help.sh

info:
	@echo "📌 Package: $(PACKAGE_NAME)"
	@echo "📌 Version: $(VERSION)"
	@echo "📌 Gitea Host: $(GITEA_HOST)"
	@echo "📌 Gitea User/Org: $(GITEA_USER)"
	@echo "📌 Internal config: $(INTERNAL_CONFIG_FILE)"
	@echo "📌 Internal PyPI index: $(INTERNAL_PYPI_INDEX)"
	@echo "📌 Public PyPI index: $(PUBLIC_PYPI_INDEX)"
	@echo "📌 Python install mirror: $(PYTHON_INSTALL_MIRROR)"
	@if [ -n "$(PROJECT_TITLE)" ]; then \
		echo "📌 Project title: $(PROJECT_TITLE)"; \
	else \
		echo "📌 Project title: derived from package name"; \
	fi
	@if [ -f pyproject.toml ]; then \
		echo "📌 Project config: generated"; \
	else \
		echo "📌 Project config: not generated (run make init)"; \
	fi
	@echo "📌 Default Python range: $(DEFAULT_PYTHON_MIN) - $(DEFAULT_PYTHON_MAX)"
	@echo "📌 Default Gitea CI targets: $(DEFAULT_GITEA_TARGETS)"
	@echo "📌 Default platforms: $(DEFAULT_PLATFORMS)"
	@echo "📌 Default architectures: $(DEFAULT_ARCHES)"
	@if [ -f .python-version ]; then \
		echo "📌 Pinned Python: $$(cat .python-version)"; \
	else \
		echo "📌 Pinned Python: not set"; \
	fi

# =============================================================================
# 📦 依赖管理
# =============================================================================

# --- 🛠️ 安装 uv 工具 ---
install-uv:
	@echo "⬇️ Installing uv via official script..."
	@curl -LsSf https://astral.sh/uv/install.sh | sh
	@echo "✅ uv installed! You might need to restart your shell or run 'source $$HOME/.cargo/env'"

# --- 🔎 检查本机工具 ---
doctor:
	@echo "🔎 Checking local development tools..."
	@command -v git >/dev/null 2>&1 || { echo "❌ git is required"; exit 1; }
	@command -v make >/dev/null 2>&1 || { echo "❌ make is required"; exit 1; }
	@if ! command -v uv >/dev/null 2>&1; then \
		echo "❌ uv is not installed. Run 'make install-uv' first."; \
		exit 1; \
	fi
	@uv --version
	@echo "✅ Required tools are available."

# --- 🚀 初始化项目 ---
init: install

init-demo:
	@DEFAULT_PLATFORMS="$(DEFAULT_PLATFORMS)" DEFAULT_ARCHES="$(DEFAULT_ARCHES)" INIT_DEMO_TARGETS="$(INIT_DEMO_TARGETS)" sh scripts/init_demo.sh

install:
	@if ! command -v uv >/dev/null 2>&1; then \
		echo "⚠️ uv not found. Installing now..."; \
		$(MAKE) install-uv; \
	fi
	@echo "🚀 \033[1;33mInitializing project from template.\033[0m"
	@$(MAKE) configure-project
	@$(MAKE) configure-compatibility
	@$(MAKE) configure-docker
	@$(MAKE) lock
	@$(MAKE) sync
	@$(MAKE) check
	@$(MAKE) test
	@$(MAKE) smoke
	@echo "✅ Environment ready! Activate with: source .venv/bin/activate"

setup:
	@if ! command -v uv >/dev/null 2>&1; then \
		echo "⚠️ uv not found. Installing now..."; \
		$(MAKE) install-uv; \
	fi
	@test -f pyproject.toml || { echo "❌ pyproject.toml not found. This command is for initialized projects; run 'make init' only when creating a project from the template."; exit 1; }
	@if [ -f .python-version ]; then \
		echo "🐍 Installing pinned Python $$(cat .python-version)..."; \
		uv python install "$$(cat .python-version)"; \
	else \
		echo "⚠️ .python-version not found; using uv default Python."; \
	fi
	@if [ -f uv.lock ]; then \
		echo "🔒 Syncing from committed uv.lock..."; \
		uv sync --frozen --all-extras --dev; \
	else \
		echo "⚠️ uv.lock not found; syncing from pyproject.toml and creating/updating lock."; \
		uv sync --all-extras --dev; \
	fi
	@echo "✅ Maintainer environment ready. Activate with: source .venv/bin/activate"

rebuild-env:
	@echo "♻️ Rebuilding local virtual environment from project config..."
	rm -rf .venv
	@$(MAKE) setup

configure-project:
	@echo "🧩 \033[1;33mConfiguring project identity.\033[0m"
	@sh scripts/configure_project.sh $(CONFIG_PROJECT_ARGS)

configure-user:
	@echo "🧩 \033[1;33mConfiguring internal Gitea owner.\033[0m"
	@sh scripts/configure_project.sh --skip-package $(CONFIG_USER_ARGS)

configure-compatibility:
	@echo "🧭 \033[1;33mConfiguring supported Python/platform/architecture targets.\033[0m"
	@sh scripts/configure_project.sh --skip-package --skip-owner
	@sh scripts/configure_compatibility.sh --default-min "$(DEFAULT_PYTHON_MIN)" --default-max "$(DEFAULT_PYTHON_MAX)" --default-targets "$(DEFAULT_GITEA_TARGETS)" --default-platforms "$(DEFAULT_PLATFORMS)" --default-arches "$(DEFAULT_ARCHES)" $(COMPATIBILITY_ARGS)

configure-docker:
	@echo "🐳 \033[1;33mConfiguring Docker integration.\033[0m"
	@sh scripts/manage_docker.sh configure $(DOCKER_CONFIG_ARGS)

pin-python: configure-compatibility

# 仅仅同步
sync:
	@echo "📥 Syncing dependencies..."
	@test -f pyproject.toml || { echo "❌ pyproject.toml not found. Run 'make init' first."; exit 1; }
	uv sync --all-extras --dev

sync-frozen:
	@echo "🔒 Syncing dependencies from uv.lock..."
	@test -f pyproject.toml || { echo "❌ pyproject.toml not found. Run 'make init' first."; exit 1; }
	uv sync --frozen --all-extras --dev

lock:
	@echo "🔐 Updating uv.lock..."
	@test -f pyproject.toml || { echo "❌ pyproject.toml not found. Run 'make init' first."; exit 1; }
	uv lock

lock-check:
	@echo "✅ Checking uv.lock..."
	@test -f pyproject.toml || { echo "❌ pyproject.toml not found. Run 'make init' first."; exit 1; }
	uv lock --check

# 升级依赖
update:
	@echo "🔄 Updating dependencies..."
	@test -f pyproject.toml || { echo "❌ pyproject.toml not found. Run 'make init' first."; exit 1; }
	uv lock --upgrade
	uv sync --all-extras --dev

# 显示依赖树
tree:
	@test -f pyproject.toml || { echo "❌ pyproject.toml not found. Run 'make init' first."; exit 1; }
	uv tree

audit:
	@echo "🔐 Running optional dependency audit with pip-audit..."
	@test -f pyproject.toml || { echo "❌ pyproject.toml not found. Run 'make init' first."; exit 1; }
	@command -v uv >/dev/null 2>&1 || { echo "❌ uv is required. Run 'make install-uv' first."; exit 1; }
	uvx pip-audit $(AUDIT_ARGS)

# =============================================================================
# 🧰 模板维护
# =============================================================================
skill-check:
	@echo "🧠 Validating bundled Codex skill..."
	@test -f "$(SKILL_DIR)/SKILL.md" || { echo "❌ Missing $(SKILL_DIR)/SKILL.md"; exit 1; }
	@if [ -f "$(SKILL_VALIDATOR)" ]; then \
		python "$(SKILL_VALIDATOR)" "$(SKILL_DIR)"; \
	else \
		echo "⚠️ Skill validator not found at $(SKILL_VALIDATOR); checking required files only."; \
		grep -q '^name: $(SKILL_NAME)$$' "$(SKILL_DIR)/SKILL.md"; \
		grep -q '^description:' "$(SKILL_DIR)/SKILL.md"; \
	fi

skill-install: skill-check
	@echo "📥 Installing bundled Codex skill into $(SKILL_INSTALL_DIR)/$(SKILL_NAME) ..."
	@mkdir -p "$(SKILL_INSTALL_DIR)/$(SKILL_NAME)/agents"
	@cp "$(SKILL_DIR)/SKILL.md" "$(SKILL_INSTALL_DIR)/$(SKILL_NAME)/SKILL.md"
	@if [ -f "$(SKILL_DIR)/agents/openai.yaml" ]; then \
		cp "$(SKILL_DIR)/agents/openai.yaml" "$(SKILL_INSTALL_DIR)/$(SKILL_NAME)/agents/openai.yaml"; \
	fi
	@echo "✅ Installed $(SKILL_NAME)."

action-check:
	@echo "🔎 Checking CI action versions..."
	@sh scripts/check_actions.sh

template-check:
	@INTERNAL_CONFIG_FILE="$(INTERNAL_CONFIG_FILE)" sh scripts/template_check.sh

# =============================================================================
# 🎨 代码质量
# =============================================================================
format:
	@echo "🎨 Running Ruff Formatter..."
	@test -f pyproject.toml || { echo "❌ pyproject.toml not found. Run 'make init' first."; exit 1; }
	uv run ruff format .

format-check:
	@echo "🎨 Checking Ruff formatting..."
	@test -f pyproject.toml || { echo "❌ pyproject.toml not found. Run 'make init' first."; exit 1; }
	uv run ruff format --check .

lint:
	@echo "🔍 Running Ruff Linter..."
	@test -f pyproject.toml || { echo "❌ pyproject.toml not found. Run 'make init' first."; exit 1; }
	uv run ruff check .

lint-fix:
	@echo "🔍 Running Ruff Linter with fixes..."
	@test -f pyproject.toml || { echo "❌ pyproject.toml not found. Run 'make init' first."; exit 1; }
	uv run ruff check . --fix

type-check:
	@echo "🦆 Running Mypy Type Checker..."
	@test -f pyproject.toml || { echo "❌ pyproject.toml not found. Run 'make init' first."; exit 1; }
	uv run mypy --package $(PACKAGE_NAME)

check: format-check lint type-check docs-check

# =============================================================================
# 🧪 测试与覆盖率
# =============================================================================
test:
	@echo "🧪 Running Pytest..."
	@test -f pyproject.toml || { echo "❌ pyproject.toml not found. Run 'make init' first."; exit 1; }
	uv run pytest

test-cov:
	@echo "📊 Running Test Coverage..."
	@test -f pyproject.toml || { echo "❌ pyproject.toml not found. Run 'make init' first."; exit 1; }
	uv run pytest --cov=src --cov-report=html
	@echo "🌍 Opening coverage report..."
	@$(OPEN_CMD) htmlcov/index.html

smoke:
	@echo "💨 Running CLI smoke test..."
	@test -f pyproject.toml || { echo "❌ pyproject.toml not found. Run 'make init' first."; exit 1; }
	uv run $(PACKAGE_NAME) --version

# =============================================================================
# 📚 文档
# =============================================================================
docs-serve:
	@echo "📚 Serving documentation at http://127.0.0.1:8000 ..."
	@test -f mkdocs.yml || { echo "❌ mkdocs.yml not found. Run 'make init' first."; exit 1; }
	uv run mkdocs serve -a 127.0.0.1:8000

docs-build:
	@echo "📚 Building documentation..."
	@test -f mkdocs.yml || { echo "❌ mkdocs.yml not found. Run 'make init' first."; exit 1; }
	uv run mkdocs build

docs-check:
	@echo "📚 Checking documentation..."
	@test -f mkdocs.yml || { echo "❌ mkdocs.yml not found. Run 'make init' first."; exit 1; }
	uv run mkdocs build --strict

# =============================================================================
# 🧪 本地 CI 验证（act）
# =============================================================================
act-check:
	@echo "🧰 Checking local act dependencies..."
	@command -v $(ACT) >/dev/null 2>&1 || { echo "❌ act is required. See https://nektosact.com/installation/"; exit 1; }
	@command -v docker >/dev/null 2>&1 || { echo "❌ Docker is required for act."; exit 1; }
	@docker info >/dev/null 2>&1 || { echo "❌ Docker daemon is not available."; exit 1; }
	@$(ACT) --version
	@docker --version
	@echo "✅ act and Docker are available."

act-list:
	@echo "📋 Listing workflow jobs with act..."
	@test -f $(ACT_WORKFLOW) || { echo "❌ $(ACT_WORKFLOW) not found. Run 'make init' or 'make configure-compatibility' first."; exit 1; }
	$(ACT) -W $(ACT_WORKFLOW) $(ACT_PLATFORM_ARGS) -l

act-dry-run:
	@echo "🧪 Validating local CI path with act --dryrun..."
	@test -f $(ACT_WORKFLOW) || { echo "❌ $(ACT_WORKFLOW) not found. Run 'make init' or 'make configure-compatibility' first."; exit 1; }
	$(ACT) $(ACT_EVENT) -W $(ACT_WORKFLOW) -j $(ACT_JOB) $(ACT_PLATFORM_ARGS) --matrix platform:$(ACT_PLATFORM) --matrix arch:$(ACT_ARCH) --matrix python-version:$(ACT_PYTHON) --container-architecture $(ACT_CONTAINER_ARCH) --env ACT=true --dryrun $(ACT_ARGS)

act-ci:
	@echo "🧪 Running local CI path with act..."
	@test -f $(ACT_WORKFLOW) || { echo "❌ $(ACT_WORKFLOW) not found. Run 'make init' or 'make configure-compatibility' first."; exit 1; }
	$(ACT) $(ACT_EVENT) -W $(ACT_WORKFLOW) -j $(ACT_JOB) $(ACT_PLATFORM_ARGS) --matrix platform:$(ACT_PLATFORM) --matrix arch:$(ACT_ARCH) --matrix python-version:$(ACT_PYTHON) --container-architecture $(ACT_CONTAINER_ARCH) --env ACT=true $(ACT_ARGS)

ci-local: act-ci

# =============================================================================
# 🏗️ 构建与打包
# =============================================================================
build: clean check test
	@echo "🏗️ Building package (Hatchling + UV)..."
	uv build

# =============================================================================
# 🚀 发布流程
# =============================================================================
release:
	@echo ""
	@echo "🚀 \033[1;32mReady to release version?\033[0m (Current detection: $(VERSION))"
	@echo "---------------------------------------------------"
	@echo "Since you are using CI/CD driven releases:"
	@echo "1. Commit all your changes."
	@echo "2. Internal snapshots are published by Gitea Actions on every main branch push."
	@echo "3. For a stable release, create a Gitea tag/release (e.g., v0.1.0):"
	@echo "   🔗 Gitea: $(GITEA_HOST)/$(GITEA_USER)/$(PACKAGE_NAME)/releases/new"
	@echo "4. The GitHub mirror receives the release through one-way sync and handles public publishing."
	@echo "---------------------------------------------------"

# =============================================================================
# 🧹 清理
# =============================================================================
clean:
	@echo "🧹 Cleaning artifacts..."
	rm -rf dist build htmlcov site coverage.xml .coverage
	find . -type d -name "__pycache__" -exec rm -rf {} +
	find . -type d -name "*.egg-info" -exec rm -rf {} +
	find . -type d -name ".pytest_cache" -exec rm -rf {} +
	find . -type d -name ".ruff_cache" -exec rm -rf {} +
	find . -type d -name ".mypy_cache" -exec rm -rf {} +

distclean: clean
	@echo "🗑️ Removing virtual environment (.venv)..."
	rm -rf .venv
	@echo "✨ Project is clean. In initialized projects run 'make setup' to rebuild the environment."

# =============================================================================
# 🐳 Docker 常用命令
# =============================================================================
docker-remove:
	@echo "🧹 Removing Docker integration..."
	@sh scripts/manage_docker.sh remove
	@echo "✅ Docker integration removed. Generate again with: make docker-restore"

docker-restore:
	@echo "♻️ Generating/restoring Docker integration..."
	@sh scripts/manage_docker.sh restore
	@echo "✅ Docker integration generated."

docker-build:
	@echo "🏗️ Building Docker image for $(PACKAGE_NAME)..."
	@test -f Dockerfile || { echo "❌ Dockerfile not found. Run 'make docker-restore' first."; exit 1; }
	docker build -t $(PACKAGE_NAME):latest .

docker-check:
	@echo "✅ Checking Docker build..."
	@test -f Dockerfile || { echo "❌ Dockerfile not found. Run 'make docker-restore' first."; exit 1; }
	docker build .

docker-up:
	@echo "🚀 Starting services..."
	@test -f compose.yaml || { echo "❌ compose.yaml not found. Run 'make docker-restore' first."; exit 1; }
	docker compose up -d --build
	@echo "📜 Use 'docker compose logs -f' to follow logs."

docker-down:
	@echo "🛑 Stopping services..."
	@test -f compose.yaml || { echo "❌ compose.yaml not found. Run 'make docker-restore' first."; exit 1; }
	docker compose down
