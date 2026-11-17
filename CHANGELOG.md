# Changelog

## Unreleased

### Added
- Profile schema version 2 (jobradar ADR 0015): target roles, languages, remote regions, relocation, and the `languages` / `work_authorization` hard constraints (unknown until ADR 0006 evaluates them); v1 profiles unchanged (0.4.0)
- ADR 0006 (Accepted): eligibility from languages, relocation, remote regions and visa sponsorship
- ADR 0007 (Accepted): role fit from a pretrained cross-encoder reranker

### Fixed
- Locations: "worldwide" in company boilerplate ("20,000 organizations worldwide") made every posting open worldwide; it now counts only in hiring phrases ("Remote - Worldwide", "work from anywhere"). The posting's location fields win over regions named in its text. Common cities, all US states, Cambodia, Myanmar, China, Pakistan, Bangladesh, Sri Lanka, Saudi Arabia, Costa Rica are known (0.3.2)
- `matcher train` and `eval run` in the image ran without the embedding model (the default path existed only in a checkout), so model versions 1–3 carry metrics without the responsibilities dimension; the default is now `MATCHER_EMBEDDING_DIR`, and both refuse to run without the model (0.3.1)
- `/metrics` required no token; it now needs the same bearer token as /v1
- openapi.yaml documented error responses as application/json with FastAPI's validation shape; they are application/problem+json with the Problem schema, as sent (0.2.1)

### Added
- Each model version is tied to its data: `matcher train` logs the eval set snapshot with checksums (`eval/dataset.json`) and the eval report as run artifacts, and tags `git_commit` and `eval_dataset_sha256`; the image takes `GIT_COMMIT` as a build arg
- Evaluation set version 1: 250 real postings, fit grades, 50 skill-labelled postings, `export_eligible.sql` for jobs the candidate can take, and the baseline (NDCG@10 0.10, P@10 0.10: jobs with no recognized skills rank as strong)
- `/metrics` (Prometheus): requests by route template and code, match duration by model version; a test checks that profile content never appears in logs
- Model versions in MLflow: bundles (taxonomy + scoring config, checksummed, compatibility-checked), `matcher train` (from defaults or a parent, with eval metrics when the eval set exists), `matcher promote` (eval gate, `--force`, rollback), `matcher models`
- `POST /v1/match` (explicit model version, batches of up to 50, item-level errors) and `GET /v1/models`; versions cached on disk so matching keeps working while MLflow is down; version 0.2.0
- Evaluation tooling: `matcher eval grade` and `eval skills` (one posting at a time, resumable), `eval run` (skill precision/recall, required accuracy, NDCG@10, P@10, false fails, latency, low-confidence share), `eval check` (regression gate with tolerances); job export query and walkthrough in `eval/`
- Responsibilities dimension: the posting's duties against your experience bullets with a pinned, checksum-verified embedding model (bge-small-en-v1.5, CPU, one thread, bit-stable), baked into the image; `matcher fetch-model`
- Scoring a job against a profile: skills (matched, transferable, missing), seniority, compensation with fixed FX rates, location/remote/time zone, employment type; hard constraints as pass/fail/unknown; banded score with separate confidence and completeness; explanations; `matcher score`
- Skill taxonomy (151 data/backend skills) and deterministic extraction from postings: skills as required or preferred, years of experience, title level, salary text, regions, UTC offsets, unrecognized terms; `matcher extract`
- ADRs 0001–0004 (Proposed): Python stack, hybrid matching, evaluation, model versions in MLflow
- ADR 0005: skill evidence
- Service skeleton: FastAPI app with `/healthz`, `/readyz`, `/v1/version`, bearer auth, problem+json errors, JSON logs with request IDs, committed `openapi.yaml`, Dockerfile, CI

### Changed
- Skills dimension (ADR 0005): a posting naming fewer than `skills.min_evidence` (3) known skills is shrunk, one naming none scores 0 instead of unknown; eval baseline NDCG@10 0.18 → 0.63, P@10 0.20 → 0.60; version 0.3.0 (bundles with `min_evidence` need it)
- Scoring defaults favour relevance: skills 0.40 and responsibilities 0.30 of the weight (were 0.35 and 0.15), duty matching from cosine 0.6 to 0.85 (was 0.5 to 0.8); eval baseline NDCG@10 0.10 → 0.18, P@10 0.10 → 0.20
- Locations: Thailand, South Korea, Taiwan, Hong Kong; "Southeast Asia", "Asia", "Asia-Pacific" as regions
- CI workflow disabled until the coding phases are done; checks run locally
- ADR 0004 (model versions in MLflow) accepted
