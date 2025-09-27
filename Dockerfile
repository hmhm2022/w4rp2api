FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim
WORKDIR /app
ENV WARP_LOG_LEVEL=info
ENV WARP_ACCESS_LOG=true
ENV OPENAI_LOG_LEVEL=info
ENV OPENAI_ACCESS_LOG=true
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen
COPY . .
# 创建数据目录用于账户文件持久化
RUN mkdir -p /app/data/accounts && chmod 755 /app/data/accounts
# 设置Docker环境下的账户文件路径
ENV LOCAL_JWT_FILEPATH=/app/data/accounts/warp_accounts_simple.json
CMD ["uv", "run", "./start.py"]