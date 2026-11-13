# Changelog

## Unreleased

### Fixed
- openapi.yaml documented error responses as application/json with FastAPI's validation shape; they are application/problem+json with the Problem schema, as sent (0.2.1)

### Added
- `/metrics` (Prometheus): requests by route template and code, match duration by model version; a test checks that profile content never appears in logs
- Model versions in MLflow: bundles (taxonomy + scoring config, checksummed, compatibility-checked), `matcher train` (from defaults or a parent, with eval metrics when the eval set exists), `matcher promote` (eval gate, `--force`, rollback), `matcher models`
- `POST /v1/match` (explicit model version, batches of up to 50, item-level errors) and `GET /v1/models`; versions cached on disk so matching keeps working while MLflow is down; version 0.2.0
- Evaluation tooling: `matcher eval grade` and `eval skills` (one posting at a time, resumable), `eval run` (skill precision/recall, required accuracy, NDCG@10, P@10, false fails, latency, low-confidence share), `eval check` (regression gate with tolerances); job export query and walkthrough in `eval/`
- Responsibilities dimension: the posting's duties against your experience bullets with a pinned, checksum-verified embedding model (bge-small-en-v1.5, CPU, one thread, bit-stable), baked into the image; `matcher fetch-model`
- Scoring a job against a profile: skills (matched, transferable, missing), seniority, compensation with fixed FX rates, location/remote/time zone, employment type; hard constraints as pass/fail/unknown; banded score with separate confidence and completeness; explanations; `matcher score`
- Skill taxonomy (151 data/backend skills) and deterministic extraction from postings: skills as required or preferred, years of experience, title level, salary text, regions, UTC offsets, unrecognized terms; `matcher extract`
- ADRs 0001–0004 (Proposed): Python stack, hybrid matching, evaluation, model versions in MLflow
- Service skeleton: FastAPI app with `/healthz`, `/readyz`, `/v1/version`, bearer auth, problem+json errors, JSON logs with request IDs, committed `openapi.yaml`, Dockerfile, CI

### Changed
- CI workflow disabled until the coding phases are done; checks run locally
- ADR 0004 (model versions in MLflow) accepted
