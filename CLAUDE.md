# jobradar-matcher

The Python matching service of jobradar: compares a candidate profile with normalized jobs
and returns explainable, versioned match results. Stateless: no database.

## Commands
```sh
uv sync                                   # Python 3.14 (.python-version), locked deps
uv run ruff check && uv run ruff format --check   # CI
uv run mypy src tests                     # CI, strict
uv run pytest                             # CI
uv run matcher openapi > openapi.yaml     # after any API change; a test enforces it
MATCHER_TOKEN=<16+ chars> uv run matcher serve    # :8000; /healthz /readyz /v1/version
docker build -t jobradar-matcher:vX.Y.Z .
```

## Layout
- System spec, architecture and cross-service ADRs live in the `jobradar` repo
  (`docs/SPEC.md`, `docs/ARCHITECTURE.md`); matcher-internal ADRs are in `docs/adr/` here
  (`NNNN-title.adr`, index in its README).
- `src/matcher/api/app.py`: `create_app(settings)`, routes, problem+json errors, bearer auth,
  request-ID middleware; `config.py`: env settings; `logs.py`: structlog JSON; `cli.py`
- `openapi.yaml`: the contract, generated and committed; the backend pins a copy per tag
- `tests/`: pytest, through `create_app` and `TestClient`

## Conventions
- One ADR, one PR, lowest number first; commits start with `[ADR-NNNN]`.
- Python is pinned to the newest version ONNX Runtime ships wheels for (ADR 0001): 3.14
  today, although 3.15 exists. Pin exact versions in the Dockerfile.
- Error bodies never echo request input (it may be personal data): field paths only.
- Tests use `httpx` with Starlette's `TestClient`; its deprecation warning about `httpx2`
  is known and accepted. Don't switch to `httpx2` without asking.
- This repo owns the matcher API contract (`openapi.yaml`); the backend pins a release tag.
  Breaking changes go to a new `/vN` path.
- Model versions in MLflow are immutable; every result names its model version (ADR 0004).
- No LLM API dependency (SPEC §13). Matching must be reproducible for the same inputs and
  model version.
- Candidate data is personal: never hardcode it, never log it.
