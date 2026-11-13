# Build: uv installs the locked dependencies and the package into a venv.
FROM python:3.14.10-slim AS build
COPY --from=ghcr.io/astral-sh/uv:0.13.7 /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never
WORKDIR /app
COPY pyproject.toml uv.lock README.md .python-version ./
RUN uv sync --locked --no-dev --no-install-project
COPY src ./src
RUN uv sync --locked --no-dev --no-editable
# The pinned embedding model, fetched and checksum-verified once, here (matcher ADR 0001, 0002).
COPY data/embedding_model.json data/
RUN /app/.venv/bin/matcher fetch-model /opt/models/bge-small-en-v1.5

# Runtime: just Python and the venv, as a non-root user.
FROM python:3.14.10-slim
# The commit the image was built from, tagged on every model version `matcher train` registers.
ARG GIT_COMMIT=unknown
ENV MATCHER_GIT_COMMIT=$GIT_COMMIT
RUN useradd --system --uid 10001 --no-create-home matcher \
    && mkdir -p /cache/models && chown -R matcher /cache  # downloaded model versions (a volume)
COPY --from=build /app/.venv /app/.venv
COPY --from=build /opt/models /opt/models
COPY data /app/data
COPY defaults /app/defaults
WORKDIR /app
# Nothing is downloaded at runtime: the model is in the image.
ENV PATH=/app/.venv/bin:$PATH PYTHONUNBUFFERED=1 HF_HUB_OFFLINE=1 \
    MATCHER_EMBEDDING_DIR=/opt/models/bge-small-en-v1.5 MATCHER_CACHE_DIR=/cache/models \
    MLFLOW_DISABLE_AGENT_HINT=1
USER matcher
EXPOSE 8000
CMD ["matcher", "serve"]
