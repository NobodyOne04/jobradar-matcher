-- Exports the evaluation sample from the jobradar backend database as eval/jobs.jsonl lines
-- ({"job_id", "job"}); null fields are left out so they stay "unknown". See eval/README.md.
-- Stratified, so grades are informative: 100 data-engineering-like open jobs (at most 10 per
-- company) and 50 others for contrast (at most 5 per company). A fixed seed keeps it
-- reproducible on the same data.
SELECT setseed(0.42);

WITH tagged AS (
    SELECT j.*,
           j.search @@ to_tsquery('english', 'data | analytics | pipeline | warehouse | etl | dbt | spark | kafka')
           AND j.search @@ to_tsquery('english', 'engineer | engineering | developer | architect') AS relevant,
           random() AS r
    FROM jobs j WHERE j.closed_at IS NULL
),
ranked AS (
    SELECT t.*, row_number() OVER (PARTITION BY relevant, company_key ORDER BY r) AS per_company
    FROM tagged t
),
sample AS (
    (SELECT * FROM ranked WHERE relevant AND per_company <= 10 ORDER BY r LIMIT 100)
    UNION ALL
    (SELECT * FROM ranked WHERE NOT relevant AND per_company <= 5 ORDER BY r LIMIT 50)
)
SELECT json_build_object(
  'job_id', id::text,
  'job', json_strip_nulls(json_build_object(
    'title', title, 'company_name', company_name, 'description_text', description_text,
    'location_text', location_text, 'remote_policy', remote_policy, 'countries', countries,
    'employment_type', employment_type, 'salary_min', salary_min, 'salary_max', salary_max,
    'salary_currency', salary_currency, 'salary_period', salary_period)))
FROM sample ORDER BY r;
