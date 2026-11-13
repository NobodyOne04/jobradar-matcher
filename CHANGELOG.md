# Changelog

## Unreleased

### Added
- Evaluation tooling: `matcher eval grade` and `eval skills` (one posting at a time, resumable), `eval run` (skill precision/recall, required accuracy, NDCG@10, P@10, false fails, latency, low-confidence share), `eval check` (regression gate with tolerances); job export query and walkthrough in `eval/`
- Responsibilities dimension: the posting's duties against your experience bullets with a pinned, checksum-verified embedding model (bge-small-en-v1.5, CPU, one thread, bit-stable), baked into the image; `matcher fetch-model`
- Scoring a job against a profile: skills (matched, transferable, missing), seniority, compensation with fixed FX rates, location/remote/time zone, employment type; hard constraints as pass/fail/unknown; banded score with separate confidence and completeness; explanations; `matcher score`
- Skill taxonomy (151 data/backend skills) and deterministic extraction from postings: skills as required or preferred, years of experience, title level, salary text, regions, UTC offsets, unrecognized terms; `matcher extract`
- ADRs 0001–0004 (Proposed): Python stack, hybrid matching, evaluation, model versions in MLflow
- Service skeleton: FastAPI app with `/healthz`, `/readyz`, `/v1/version`, bearer auth, problem+json errors, JSON logs with request IDs, committed `openapi.yaml`, Dockerfile, CI

### Changed
- CI workflow disabled until the coding phases are done; checks run locally
- ADR 0004 (model versions in MLflow) accepted
