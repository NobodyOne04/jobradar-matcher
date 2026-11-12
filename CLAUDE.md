# jobradar-matcher

The Python matching service of jobradar: compares a candidate profile with normalized jobs
and returns explainable, versioned match results. Stateless: no database.

## Commands
None yet: Phase 0 (architecture) comes before any code.

## Layout
- System spec, architecture and cross-service ADRs live in the `jobradar` repo
  (`docs/SPEC.md`, `docs/ARCHITECTURE.md`); matcher-internal ADRs are in `docs/adr/` here
  (`NNNN-title.adr`, index in its README).

## Conventions
- No code before the architecture in `jobradar` is approved (SPEC §14).
- This repo owns the matcher API contract (`openapi.yaml`); the backend pins a release tag.
  Breaking changes go to a new `/vN` path.
- Model bundles are immutable once written; every result names its model version.
- No LLM API dependency (SPEC §13). Matching must be reproducible for the same inputs and
  model version.
- Candidate data is personal: never hardcode it, never log it.
