"""`matcher eval grade` and `matcher eval skills`: one posting at a time, saved after each
answer, so a session can stop and resume anywhere."""

from collections.abc import Callable
from pathlib import Path

from matcher.evaluate import EvalJob, Grade, SkillLabels, append_jsonl, read_jsonl, ungraded
from matcher.extract import extract
from matcher.schemas import Job
from matcher.taxonomy import Taxonomy

Ask = Callable[[str], str]
Show = Callable[[str], None]

GRADES = "0 no fit · 1 weak · 2 good · 3 strong · m more text · s skip · q quit"


def _card(job: Job, n: int, total: int, full: bool) -> str:
    salary = (
        f"{job.salary_currency} {job.salary_min or '?'}-{job.salary_max or '?'}/{job.salary_period}"
        if job.salary_currency
        else "not stated"
    )
    text = job.description_text if full else job.description_text[:1500]
    more = "" if full or len(job.description_text) <= 1500 else "\n[... m for the rest]"
    return (
        f"\n=== {n}/{total} ===  {job.title} — {job.company_name or '?'}\n"
        f"where: {job.location_text or '?'} · remote: {job.remote_policy} · "
        f"type: {job.employment_type} · salary: {salary}\n\n{text}{more}\n"
    )


def grade_session(eval_dir: Path, ask: Ask = input, show: Show = print) -> int:
    """Ask a 0-3 fit grade for each ungraded job; returns how many were graded."""
    jobs = read_jsonl(eval_dir / "jobs.jsonl", EvalJob)
    path = eval_dir / "grades.jsonl"
    done = {g.job_id for g in read_jsonl(path, Grade)}
    graded = 0
    for n, item in enumerate(ungraded(jobs, done), len(done) + 1):
        full = False
        while True:
            show(_card(item.job, n, len(jobs), full))
            answer = ask(f"fit for you? {GRADES}: ").strip().lower()
            if answer == "q":
                return graded
            if answer == "s":
                break
            if answer == "m":
                full = True
                continue
            if answer in {"0", "1", "2", "3"}:
                append_jsonl(path, Grade(job_id=item.job_id, grade=int(answer)))
                graded += 1
                break
            show("please answer 0, 1, 2, 3, m, s or q")
    show(f"all {len(jobs)} jobs graded")
    return graded


SKILL_HELP = (
    "enter: correct as shown · +id add required · +id? add preferred · -id remove · "
    "~id toggle required/preferred · several at once: +kafka -sql · s skip · q quit"
)


def skills_session(eval_dir: Path, tax: Taxonomy, ask: Ask = input, show: Show = print) -> int:
    """Show the extracted skills of each unlabelled job and record your corrections."""
    jobs = read_jsonl(eval_dir / "jobs.jsonl", EvalJob)
    path = eval_dir / "skills.jsonl"
    done = {s.job_id for s in read_jsonl(path, SkillLabels)}
    labelled = 0
    for n, item in enumerate(ungraded(jobs, done), len(done) + 1):
        labels = {
            s.id: s.requirement
            for s in extract(item.job.title, item.job.description_text, tax).skills
        }
        show(_card(item.job, n, len(jobs), full=True))
        while True:
            shown = ", ".join(
                f"{sid}{'' if req == 'required' else '?'}" for sid, req in sorted(labels.items())
            )
            show(f"skills (? = preferred): {shown or '(none)'}")
            answer = ask(f"{SKILL_HELP}\n> ").strip()
            if answer == "q":
                return labelled
            if answer == "s":
                break
            if not answer:
                append_jsonl(path, SkillLabels(job_id=item.job_id, skills=labels))
                labelled += 1
                break
            for op in answer.split():
                sid = op[1:].rstrip("?")
                if op[0] not in "+-~" or sid not in tax.skills:
                    show(f"unknown command or skill id: {op}")
                elif op[0] == "+":
                    labels[sid] = "preferred" if op.endswith("?") else "required"
                elif op[0] == "-":
                    labels.pop(sid, None)
                elif sid in labels:
                    labels[sid] = "preferred" if labels[sid] == "required" else "required"
    show(f"all {len(jobs)} jobs labelled")
    return labelled
