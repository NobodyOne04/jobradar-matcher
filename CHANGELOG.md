# Changelog

## Unreleased

### Added
- ADRs 0001–0004 (Proposed): Python stack, hybrid matching, evaluation, model versions in MLflow
- Service skeleton: FastAPI app with `/healthz`, `/readyz`, `/v1/version`, bearer auth, problem+json errors, JSON logs with request IDs, committed `openapi.yaml`, Dockerfile, CI

### Changed
- CI workflow disabled until the coding phases are done; checks run locally
- ADR 0004 (model versions in MLflow) accepted
