# jobradar-matcher

Job-to-candidate matching service for [jobradar](https://github.com/NobodyOne04/jobradar): skill extraction, scoring, explanations, versioned models (Python).

## Run

```sh
uv sync
MATCHER_TOKEN=<at least 16 chars> uv run matcher serve   # http://localhost:8000/healthz
```

Normally it runs from the `jobradar` Docker Compose setup, built from a checkout of a release tag. See `CLAUDE.md` for the checks CI runs.
