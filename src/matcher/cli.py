"""CLI: `matcher serve` runs the API; `matcher openapi` prints the contract (openapi.yaml);
`matcher extract job.json` shows what extraction finds in one posting."""

import argparse
import json
import sys
from pathlib import Path

import yaml

from matcher.api.app import create_app
from matcher.config import Settings


def openapi_yaml() -> str:
    # The token plays no part in the schema; any valid value will do.
    app = create_app(Settings(token="x" * 16))
    return yaml.safe_dump(app.openapi(), sort_keys=False, allow_unicode=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="matcher")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("serve", help="run the HTTP API")
    sub.add_parser("openapi", help="print the OpenAPI document as YAML")
    ext = sub.add_parser("extract", help="extract skills and requirements from one job posting")
    ext.add_argument("job", type=Path, help='JSON file with "title" and "description_text"')
    ext.add_argument("--taxonomy", type=Path, default=Path("data/skills.yaml"))
    sc = sub.add_parser("score", help="score one job against one profile")
    sc.add_argument("--profile", type=Path, required=True, help="profile YAML or JSON (schema v1)")
    sc.add_argument("--job", type=Path, required=True, help="normalized job JSON")
    sc.add_argument("--taxonomy", type=Path, default=Path("data/skills.yaml"))
    sc.add_argument("--config", type=Path, default=Path("defaults/scoring.yaml"))
    args = parser.parse_args(argv)

    if args.command == "openapi":
        sys.stdout.write(openapi_yaml())
        return 0
    if args.command == "score":
        from matcher.schemas import Job, Profile
        from matcher.score import score
        from matcher.score.config import load as load_config
        from matcher.taxonomy import load as load_taxonomy

        profile = Profile.model_validate(yaml.safe_load(args.profile.read_text(encoding="utf-8")))
        job = Job.model_validate_json(args.job.read_text(encoding="utf-8"))
        match = score(profile, job, load_taxonomy(args.taxonomy), load_config(args.config))
        print(match.model_dump_json(indent=2))
        return 0
    if args.command == "extract":
        from matcher.extract import extract
        from matcher.taxonomy import load

        job = json.loads(args.job.read_text(encoding="utf-8"))
        result = extract(job.get("title", ""), job.get("description_text", ""), load(args.taxonomy))
        print(result.model_dump_json(indent=2))
        return 0

    try:
        settings = Settings.from_env()
    except ValueError as e:
        print(f"config error: {e}", file=sys.stderr)
        return 2

    import uvicorn

    from matcher import logs

    logs.configure(settings.log_level)
    # Uvicorn's own logs are plain text, so keep them to warnings and up; the request
    # middleware logs each request as JSON with its request_id.
    uvicorn.run(
        create_app(settings),
        host=settings.host,
        port=settings.port,
        access_log=False,
        log_level="warning",
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
