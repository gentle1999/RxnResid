# ==========================================
# Stage 1: Builder (使用 uv 进行依赖安装)
# ==========================================
FROM ghcr.io/astral-sh/uv:python3.11-bookworm-slim AS builder

# 设置环境变量：编译字节码、无缓冲输出
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

WORKDIR /app

# 1. 预先复制依赖定义文件 (利用 Docker 缓存)
# 只要 pyproject.toml 和 uv.lock 不变，这一层就会被缓存
COPY pyproject.toml uv.lock ./

# 2. 安装依赖 (不包含当前项目代码，只安装第三方库)
# --no-install-project: 只安装 [project.dependencies]，不安装 src/ 下的代码
# --frozen: 严格按照 lock 文件安装
RUN uv sync --frozen --no-install-project --no-dev

# 3. 复制源代码
COPY src ./src
COPY README.md ./

# 4. 安装项目本身 (这一步会将 src/ 下的代码安装到 venv 中)
RUN uv sync --frozen --no-dev

# ==========================================
# Stage 2: Runtime (最终运行镜像)
# ==========================================
FROM python:3.11-slim-bookworm

WORKDIR /app

# 从 Builder 阶段复制构建好的虚拟环境
COPY --from=builder /app/.venv /app/.venv

# 将虚拟环境加入 PATH，这样直接运行 `python` 就是 venv 里的 python
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1

# 默认运行模板自带的 CLI。模板使用者可以替换为自己的服务入口。
CMD ["myrepositorytemplate"]
