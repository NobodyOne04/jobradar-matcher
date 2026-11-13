"""CLI: `matcher serve` runs the API; `matcher openapi` prints the contract (openapi.yaml);
`matcher extract job.json` shows what extraction finds in one posting; `matcher score` scores
one job against one profile; `matcher fetch-model DIR` downloads the pinned embedding model."""

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
    sc.add_argument(
        "--model",
        type=Path,
        default=Path(".models/bge-small-en-v1.5"),
        help="embedding model dir; responsibilities are unknown if it is missing",
    )
    ev = sub.add_parser("eval", help="the evaluation set (ADR 0003)")
    evs = ev.add_subparsers(dest="eval_command", required=True)
    evs.add_parser("grade", help="grade each job's fit for you, 0-3, one at a time")
    evs.add_parser("skills", help="correct the extracted skills of each job")
    er = evs.add_parser("run", help="compute the metrics")
    er.add_argument("--profile", type=Path, required=True, help="the eval profile (not committed)")
    er.add_argument("--out", type=Path, help="write the metrics JSON here as well")
    ec = evs.add_parser("check", help="compare metrics with the baseline; exit 1 on regression")
    ec.add_argument("metrics", type=Path)
    ev.add_argument("--dir", type=Path, default=Path("eval"))
    ev.add_argument("--taxonomy", type=Path, default=Path("data/skills.yaml"))
    ev.add_argument("--config", type=Path, default=Path("defaults/scoring.yaml"))
    ev.add_argument("--model", type=Path, default=Path(".models/bge-small-en-v1.5"))
    fm = sub.add_parser("fetch-model", help="download the pinned embedding model and verify it")
    fm.add_argument("dir", type=Path, nargs="?", default=Path(".models/bge-small-en-v1.5"))
    args = parser.parse_args(argv)

    if args.command == "openapi":
        sys.stdout.write(openapi_yaml())
        return 0
    if args.command == "eval":
        return _eval(args)
    if args.command == "fetch-model":
        from matcher.embed import fetch, manifest

        fetch(args.dir, manifest())
        print(f"embedding model verified in {args.dir}")
        return 0
    if args.command == "score":
        from matcher.embed import Embedder, manifest
        from matcher.schemas import Job, Profile
        from matcher.score import score
        from matcher.score.config import load as load_config
        from matcher.taxonomy import load as load_taxonomy

        profile = Profile.model_validate(yaml.safe_load(args.profile.read_text(encoding="utf-8")))
        job = Job.model_validate_json(args.job.read_text(encoding="utf-8"))
        embedder = Embedder(args.model, manifest()) if args.model.is_dir() else None
        match = score(
            profile, job, load_taxonomy(args.taxonomy), load_config(args.config), embedder
        )
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


def _eval(args: argparse.Namespace) -> int:
    from matcher.taxonomy import load as load_taxonomy

    if args.eval_command == "grade":
        from matcher.evaluate.interactive import grade_session

        grade_session(args.dir)
        return 0
    if args.eval_command == "skills":
        from matcher.evaluate.interactive import skills_session

        skills_session(args.dir, load_taxonomy(args.taxonomy))
        return 0
    if args.eval_command == "run":
        from matcher.embed import Embedder, manifest
        from matcher.evaluate import run
        from matcher.schemas import Profile
        from matcher.score.config import load as load_config

        profile = Profile.model_validate(yaml.safe_load(args.profile.read_text(encoding="utf-8")))
        embedder = Embedder(args.model, manifest()) if args.model.is_dir() else None
        result = run(
            args.dir, profile, load_taxonomy(args.taxonomy), load_config(args.config), embedder
        )
        out = json.dumps(result, indent=2, sort_keys=True)
        print(out)
        if args.out:
            args.out.write_text(out + "\n", encoding="utf-8")
        return 0
    # check
    from matcher.evaluate import check

    problems = check(
        json.loads(args.metrics.read_text(encoding="utf-8")),
        json.loads((args.dir / "baseline.json").read_text(encoding="utf-8")),
        yaml.safe_load((args.dir / "tolerances.yaml").read_text(encoding="utf-8")),
    )
    for p in problems:
        print("FAIL", p, file=sys.stderr)
    print("eval gate passed" if not problems else f"eval gate failed: {len(problems)} problem(s)")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
