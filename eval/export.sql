-- Exports 150 random open jobs from the jobradar backend database as eval/jobs.jsonl lines
-- ({"job_id", "job"}); null fields are left out so they stay "unknown". See eval/README.md.
SELECT json_build_object(
  'job_id', id::text,
  'job', json_strip_nulls(json_build_object(
    'title', title, 'company_name', company_name, 'description_text', description_text,
    'location_text', location_text, 'remote_policy', remote_policy, 'countries', countries,
    'employment_type', employment_type, 'salary_min', salary_min, 'salary_max', salary_max,
    'salary_currency', salary_currency, 'salary_period', salary_period)))
FROM jobs WHERE closed_at IS NULL ORDER BY random() LIMIT 150;
