-- Second part of the evaluation sample: up to 100 open jobs from sources filtered to countries
-- the candidate can work from (config "country"), data/platform/ML titles first, at most 6 per
-- company, excluding jobs already in eval/jobs.jsonl (:'existing' is a comma-separated id list).
-- The first sample (export.sql) had no job a remote candidate in Thailand could take.
SELECT setseed(0.42);

WITH eligible AS (
    SELECT DISTINCT j.*
    FROM jobs j
    JOIN source_postings p ON p.job_id = j.id AND p.closed_at IS NULL
    JOIN sources s ON s.id = p.source_id
    WHERE j.closed_at IS NULL AND s.config ? 'country'
      AND NOT j.id = ANY(string_to_array(:'existing', ',')::bigint[])
),
ranked AS (
    SELECT e.*,
           e.title ~* '(data|etl|elt|analytics engineer|platform|mlops|machine learning|ml |spark|big data|pipeline)' AS relevant_title,
           row_number() OVER (PARTITION BY company_key ORDER BY random()) AS per_company,
           random() AS r
    FROM eligible e
)
SELECT json_build_object(
  'job_id', id::text,
  'job', json_strip_nulls(json_build_object(
    'title', title, 'company_name', company_name, 'description_text', description_text,
    'location_text', location_text, 'remote_policy', remote_policy, 'countries', countries,
    'employment_type', employment_type, 'salary_min', salary_min, 'salary_max', salary_max,
    'salary_currency', salary_currency, 'salary_period', salary_period)))
FROM (SELECT * FROM ranked WHERE per_company <= 6 ORDER BY relevant_title DESC, r LIMIT 100) s
ORDER BY r;
