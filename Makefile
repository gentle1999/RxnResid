.DEFAULT_GOAL := help

.PHONY: help setup rebuild-env sync sync-frozen lock update tree pyg-accelerators \
	pyg-accelerators-dry-run format format-check lint lint-fix type-check check test \
	test-cov clean distclean

help:
	@echo "RxnResid commands:"
	@echo "  make setup                    Restore the locked development environment"
	@echo "  make pyg-accelerators         Install CUDA-matched PyG extension wheels"
	@echo "  make check                    Run Ruff, Mypy, and Pyright"
	@echo "  make test                     Run the test suite"

setup:
	@command -v uv >/dev/null 2>&1 || { echo "uv is required: https://docs.astral.sh/uv/"; exit 1; }
	uv sync --frozen --all-extras --dev

rebuild-env:
	rm -rf .venv
	$(MAKE) setup

sync:
	uv sync --all-extras --dev

sync-frozen:
	uv sync --frozen --all-extras --dev

lock:
	uv lock

update:
	uv lock --upgrade
	uv sync --all-extras --dev

tree:
	uv tree

pyg-accelerators:
	uv run --no-sync python scripts/install_pyg_accelerators.py

pyg-accelerators-dry-run:
	uv run --no-sync python scripts/install_pyg_accelerators.py --dry-run

format:
	uv run ruff format .

format-check:
	uv run ruff format --check .

lint:
	uv run ruff check .

lint-fix:
	uv run ruff check . --fix

type-check:
	uv run mypy --package rxnresid
	uv run mypy train.py predict.py scripts/*.py
	uv run pyright

check: format-check lint type-check

test:
	uv run pytest

test-cov:
	uv run pytest --cov=src --cov-report=html

clean:
	rm -rf dist build htmlcov site coverage.xml .coverage
	find . -type d -name "__pycache__" -exec rm -rf {} +
	find . -type d -name "*.egg-info" -exec rm -rf {} +
	find . -type d -name ".pytest_cache" -exec rm -rf {} +
	find . -type d -name ".ruff_cache" -exec rm -rf {} +
	find . -type d -name ".mypy_cache" -exec rm -rf {} +
	find . -type d -name ".pyright" -exec rm -rf {} +

distclean: clean
	rm -rf .venv
