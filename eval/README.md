# Evaluation set (matcher ADR 0003)

Measures how well matching ranks jobs **for you**, and catches regressions. Files:

| File | What | Committed |
|---|---|---|
| `VERSION` | dataset version; metrics only compare within one | yes |
| `jobs.jsonl` | 250 real postings (`export.sql` + `export_eligible.sql`), `{"job_id", "job"}` | yes (public posting text only) |
| `grades.jsonl` | fit grades, `{"job_id", "grade": 0-3}` | yes |
| `skills.jsonl` | ~50 postings with hand-checked skills | yes |
| `profile.yaml` | the profile the grades were given for | **no** (git-ignored) |
| `tolerances.yaml`, `baseline.json` | the regression gate | yes |

## Build it once

1. Export jobs from your running backend (after a few syncs, so several sources are mixed):
   ```sh
   cd ../jobradar
   docker compose exec -T postgres psql -U postgres -d jobradar -At \
     < ../jobradar-matcher/eval/export.sql > ../jobradar-matcher/eval/jobs.jsonl
   ```
   Then the second part, jobs from country-filtered sources the candidate can actually take
   (the random sample had none):
   ```sh
   docker compose exec -T postgres psql -U postgres -d jobradar -At \
     -v existing="$(jq -r .job_id ../jobradar-matcher/eval/jobs.jsonl | paste -sd, -)" \
     < ../jobradar-matcher/eval/export_eligible.sql >> ../jobradar-matcher/eval/jobs.jsonl
   ```
2. Grade each job's fit for you, 0 no fit · 1 weak · 2 good · 3 strong (stop and resume
   any time; each answer is saved at once):
   ```sh
   uv run matcher eval grade
   ```
3. Check the extracted skills of ~50 of them (`+kafka`, `+kafka?` preferred, `-sql`, `~dbt`):
   ```sh
   uv run matcher eval skills
   ```
4. Put the profile you graded for in `eval/profile.yaml` (yours or a stand-in).
5. Record the baseline:
   ```sh
   uv run matcher eval run --profile eval/profile.yaml --out eval/baseline.json
   ```

## On every matching change

```sh
uv run matcher eval run --profile eval/profile.yaml --out /tmp/metrics.json
uv run matcher eval check /tmp/metrics.json
```

`check` fails on any **false fail** (a job you graded 2 or 3 excluded by a hard constraint)
and on any metric worse than the baseline beyond `tolerances.yaml`. A change that is meant
to move the numbers commits the new `baseline.json` in the same PR.

New jobs or grades change the dataset: bump `VERSION` and commit a new baseline.

## Dataset version 1

250 jobs: 150 from the stratified sample, 100 from Thailand-filtered sources. Grades
{0: 190, 1: 47, 2: 7, 3: 6}, written by Claude from the candidate's CV and stated preferences
as a proxy for the candidate's own judgement; grades the candidate gives later go in a new
dataset version, not mixed into this one. 50 jobs (the 13 graded 2–3, then 37 graded 1) have
hand-checked skills; postings cut at 4,000 characters in review kept the extracted skills
for the unseen rest.
