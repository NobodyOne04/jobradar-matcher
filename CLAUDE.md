# jobradar-matcher

The Python matching service of jobradar: compares a candidate profile with normalized jobs
and returns explainable, versioned match results. Stateless: no database.

## Commands
```sh
uv sync                                   # Python 3.14 (.python-version), locked deps
uv run matcher fetch-model                # once: pinned embedding model into .models/ (64 MB)
uv run ruff check && uv run ruff format --check   # CI
uv run mypy src tests                     # CI, strict
uv run pytest                             # CI
uv run matcher openapi > openapi.yaml     # after any API change; a test enforces it
MATCHER_TOKEN=<16+ chars> uv run matcher serve    # :8000; /healthz /readyz /v1/version
uv run matcher extract job.json           # {"title","description_text"} -> skills, years, salary...
uv run matcher score --profile tests/fixtures/profile_example.yaml --job job.json   # one match
docker build -t jobradar-matcher:vX.Y.Z .
```

## Layout
- System spec, architecture and cross-service ADRs live in the `jobradar` repo
  (`docs/SPEC.md`, `docs/ARCHITECTURE.md`); matcher-internal ADRs are in `docs/adr/` here
  (`NNNN-title.adr`, index in its README).
- `src/matcher/api/app.py`: `create_app(settings)`, routes, problem+json errors, bearer auth,
  request-ID middleware; `config.py`: env settings; `logs.py`: structlog JSON; `cli.py`
- `data/skills.yaml`: the skill taxonomy (aliases, `cased` aliases, categories, `related`);
  `src/matcher/taxonomy/`: loads and validates it; `src/matcher/tokens.py`: the one tokenizer
  for both job text and aliases
- `src/matcher/extract/`: deterministic extraction (skills with required/preferred from
  sections, years, title level, salary text, regions, UTC offsets, unrecognized terms)
- `src/matcher/schemas/`: `Profile` (schema v1, mirrors jobradar `docs/api/profile.schema.json`)
  and `Job` (the backend's normalized job), both strict
- `src/matcher/score/`: dimensions, hard-constraint gates, banded score, confidence,
  explanations; `config.py` + `defaults/scoring.yaml` (weights, cut-offs, fixed FX rates);
  `geo.py`: which countries a location phrase covers
- `src/matcher/embed.py` + `data/embedding_model.json`: the embedding model (BAAI/bge-small-en-v1.5
  via fastembed/ONNX), pinned by repo revision and per-file sha256; the image fetches it at
  build time into /opt/models, `.models/` locally (git-ignored); tests skip without it
- `tests/fixtures/`: recorded real postings, and the fictional example profile
- `openapi.yaml`: the contract, generated and committed; the backend pins a copy per tag
- `tests/`: pytest, through `create_app` and `TestClient`

## Conventions
- One ADR, one PR, lowest number first; commits start with `[ADR-NNNN]`.
- Python is pinned to the newest version ONNX Runtime ships wheels for (ADR 0001): 3.14
  today, although 3.15 exists. Pin exact versions in the Dockerfile.
- Extraction is pure and deterministic: no clock, no randomness, sorted output. A new alias
  must not be a common English word ("rest", "rails", "yarn" were removed for that); short
  ambiguous names go in `cased`. Grow the taxonomy from `unrecognized` on real postings.
- Unknown is never a mismatch: a dimension without data is left out (lower completeness),
  a hard constraint without data is `unknown`, never `fail`. Score, band, confidence and
  completeness stay separate fields.
- Nothing is fetched at runtime (`HF_HUB_OFFLINE=1` in the image) and ONNX Runtime telemetry
  is disabled in `Embedder`. Changing the model means a new manifest (repo, revision, hashes).
- Weights and thresholds live in `defaults/scoring.yaml`, never in code: they will be part of
  each model version (ADR 0004). Change them only together with the eval baseline (ADR 0003).
- Error bodies never echo request input (it may be personal data): field paths only.
- Tests use `httpx` with Starlette's `TestClient`; its deprecation warning about `httpx2`
  is known and accepted. Don't switch to `httpx2` without asking.
- CI is disabled (`gh workflow disable CI`, 2026-11-13) until the coding phases are done.
  Before every PR, run its checks locally: ruff check, ruff format --check, mypy, pytest,
  pip-audit, docker build. Re-enable with `gh workflow enable CI`.
- This repo owns the matcher API contract (`openapi.yaml`); the backend pins a release tag.
  Breaking changes go to a new `/vN` path.
- Model versions in MLflow are immutable; every result names its model version (ADR 0004).
- No LLM API dependency (SPEC §13). Matching must be reproducible for the same inputs and
  model version.
- Candidate data is personal: never hardcode it, never log it.
