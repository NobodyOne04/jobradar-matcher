# Architecture Decision Records

Files are `NNNN-title.adr` (Markdown). Lower numbers are implemented first, one PR each
(the ADR flips to Accepted in the PR that implements it, after your approval).
System-level and backend decisions live in `jobradar/docs/adr/`.

| # | Decision | Status |
|---|---|---|
| [0001](0001-python-service-stack.adr) | Python service stack: FastAPI, Pydantic, uv, one small image | Proposed |
| [0002](0002-hybrid-matching.adr) | Matching: deterministic rules and taxonomy, plus one small embedding dimension | Proposed |
| [0003](0003-evaluation.adr) | Evaluation: a labeled set you grade, fixed metrics, a CI regression gate | Proposed |
| [0004](0004-model-bundles.adr) | Model bundles: immutable versioned directories, built by `matcher train` | Proposed |
