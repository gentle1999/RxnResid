  {{JOB_ID}}:
    name: Test on {{PLATFORM}}/{{ARCH}} (Py {{PYTHON_VERSION}})
    runs-on: {{RUNNER}}
    steps:
      - name: Checkout code
        uses: {{GITEA_CHECKOUT_ACTION}}
        with:
          fetch-depth: 0

      - name: Install uv
        run: |
          python3 -m ensurepip --upgrade || true
          python3 -m pip install --user --upgrade -i "${INTERNAL_PYPI_INDEX}" uv || \
            python3 -m pip install --user --upgrade --break-system-packages -i "${INTERNAL_PYPI_INDEX}" uv
          USER_BIN="$(python3 -m site --user-base)/bin"
          echo "$USER_BIN" >> "$GITHUB_PATH"
          export PATH="$USER_BIN:$PATH"
          uv --version

      - name: Set up Python {{PYTHON_VERSION}}
        run: uv python install {{PYTHON_VERSION}}

      - name: Install dependencies
        run: uv sync --python {{PYTHON_VERSION}} --all-extras --dev

      - name: Lint, format, and type check
        run: |
          uv run --no-sync --python {{PYTHON_VERSION}} ruff check .
          uv run --no-sync --python {{PYTHON_VERSION}} ruff format --check .
          uv run --no-sync --python {{PYTHON_VERSION}} mypy --package "$PACKAGE_NAME"

      - name: Run tests
        run: uv run --no-sync --python {{PYTHON_VERSION}} pytest

      - name: Build documentation
        run: uv run --no-sync --python {{PYTHON_VERSION}} mkdocs build --strict
