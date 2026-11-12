# Build: uv installs the locked dependencies and the package into a venv.
FROM python:3.14.10-slim AS build
COPY --from=ghcr.io/astral-sh/uv:0.13.7 /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never
WORKDIR /app
COPY pyproject.toml uv.lock README.md .python-version ./
RUN uv sync --locked --no-dev --no-install-project
COPY src ./src
RUN uv sync --locked --no-dev --no-editable

# Runtime: just Python and the venv, as a non-root user.
FROM python:3.14.10-slim
RUN useradd --system --uid 10001 --no-create-home matcher
COPY --from=build /app/.venv /app/.venv
ENV PATH=/app/.venv/bin:$PATH PYTHONUNBUFFERED=1
USER matcher
EXPOSE 8000
CMD ["matcher", "serve"]
