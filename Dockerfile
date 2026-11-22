# =============================================================================
# DeepSearch Agent 后端镜像
#
# 两阶段构建：
#   builder  —— 用 uv 解析并安装依赖到独立虚拟环境
#   runtime  —— 只拷贝虚拟环境与源码，不携带构建工具与 pip/uv 缓存
#
# 收益：镜像更小；运行阶段不含包管理器，少一层可被利用的面。
# =============================================================================

# ---------- Stage 1: builder ----------
# 基础镜像版本必须与 pyproject.toml 的 requires-python（>=3.12,<3.13）一致，
# 用更高版本会在 uv sync --frozen 阶段直接因版本约束失败。
FROM python:3.12-slim AS builder

# uv 从官方镜像取，避免构建期再联网装 uv 本身
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

ENV UV_COMPILE_BYTECODE=0 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never

# 可选包索引镜像：国内网络 PyPI 直连可能极慢甚至卡死。
# 构建时用 --build-arg UV_INDEX_URL=<镜像地址> 覆盖，不传则走默认 PyPI。
ARG UV_INDEX_URL=https://pypi.org/simple
ENV UV_DEFAULT_INDEX=${UV_INDEX_URL}

WORKDIR /app

# 先只拷依赖清单：源码变更时依赖层仍能命中缓存
COPY pyproject.toml uv.lock ./

# --no-dev 排除 pytest / ruff，避免开发依赖进入生产镜像
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-install-project --no-dev

# ---------- Stage 2: runtime ----------
FROM python:3.12-slim AS runtime

# PYTHONDONTWRITEBYTECODE  容器内不写 .pyc，保持文件系统整洁
# PYTHONUNBUFFERED         日志实时输出，否则被缓冲吞掉
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/app/.venv/bin:$PATH" \
    TZ=Asia/Shanghai

WORKDIR /app

# 非 root 运行：应用被攻破时攻击者也无法直接写系统目录
RUN groupadd --system --gid 1000 appuser \
    && useradd --system --uid 1000 --gid 1000 --create-home appuser

COPY --from=builder --chown=appuser:appuser /app/.venv /app/.venv

COPY --chown=appuser:appuser app ./app
COPY --chown=appuser:appuser pyproject.toml ./

# 运行时目录必须在切到 appuser 之前建好并改属主。
# 关键点：server.py 在**模块导入期**就执行 output_dir.mkdir() / updated_dir.mkdir()，
# app/infra/log.py 也会创建 logs 目录。若 appuser 对这三个路径没有写权限，
# 容器会在导入阶段直接 CrashLoop，日志里看不到应用自身的报错。
RUN mkdir -p /app/app/output /app/app/updated /app/logs \
    && chown -R appuser:appuser /app

USER appuser

EXPOSE 8000

# 探活打就绪接口：它会校验关键环境变量是否齐备。
# 配置漏填时容器直接被标记为不健康，而不是等用户请求失败才发现。
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health/ready', timeout=3).status == 200 else 1)"

CMD ["uvicorn", "app.api.server:app", "--host", "0.0.0.0", "--port", "8000"]
