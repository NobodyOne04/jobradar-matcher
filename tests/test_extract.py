import json
from pathlib import Path

import pytest

from matcher.extract import extract
from matcher.taxonomy import Taxonomy, load

ROOT = Path(__file__).parent.parent


@pytest.fixture(scope="module")
def tax() -> Taxonomy:
    return load(ROOT / "data/skills.yaml")


def skills(tax: Taxonomy, text: str, title: str = "Data Engineer") -> dict[str, str]:
    return {s.id: s.requirement for s in extract(title, text, tax).skills}


def test_aliases_longest_first_and_not_across_punctuation(tax: Taxonomy) -> None:
    got = skills(tax, "Data pipelines with Apache Airflow on AWS (S3, EMR) using Spark SQL.")
    assert set(got) == {"etl", "airflow", "aws", "s3", "emr", "spark"}  # "spark sql" is one alias

    # A heading with a list after the colon sets the section and lists skills.
    assert skills(tax, "Nice to have: Kafka, Flink") == {"kafka": "preferred", "flink": "preferred"}


def test_case_sensitive_aliases(tax: Taxonomy) -> None:
    assert "go" in skills(tax, "Backend services in Go and Python")
    assert "go" not in skills(tax, "You will go the extra mile")
    assert "r" in skills(tax, "Statistics in R or Python")
    assert "r" not in skills(tax, "r and d")


def test_sections_and_inline_preference(tax: Taxonomy) -> None:
    text = "\n".join(
        [
            "What you'll do",
            "Own our Kafka platform.",
            "Requirements:",
            "Strong SQL.",
            "Experience with dbt is a plus.",
            "Nice to have",
            "Terraform, SQL",
            "Benefits",
            "Free Snowflake credits for side projects.",
        ]
    )
    got = skills(tax, text)
    assert got == {
        "kafka": "required",
        "sql": "required",
        "dbt": "preferred",
        "terraform": "preferred",
    }


def test_no_sections_means_required(tax: Taxonomy) -> None:
    assert skills(tax, "We use Python and Airflow.") == {
        "python": "required",
        "airflow": "required",
    }


@pytest.mark.parametrize(
    ("text", "want"),
    [
        ("5+ years of experience with Python", 5),
        ("3-5 years of experience; 7+ years of experience preferred", 7),
        ("At least 4 yrs of data engineering", 4),
        ("We were founded 12 years ago.", None),  # no "experience"/"years of": not a requirement
        ("Experience: 40 years of experience", None),  # out of range
    ],
)
def test_years(tax: Taxonomy, text: str, want: int | None) -> None:
    assert extract("Engineer", text, tax).years_required == want


@pytest.mark.parametrize(
    ("title", "want"),
    [
        ("Senior Data Engineer", "senior"),
        ("Sr. Analytics Engineer", "senior"),
        ("Senior Staff Engineer", "staff"),
        ("Head of Data", "manager"),
        ("Data Engineer", None),
        ("Junior Data Engineer (Intern)", "junior"),
    ],
)
def test_title_level(tax: Taxonomy, title: str, want: str | None) -> None:
    assert extract(title, "", tax).title_level == want


@pytest.mark.parametrize(
    ("text", "want"),
    [
        ("Salary: €80-100k per year", (80000, 100000, "EUR", "year")),
        ("$120,000 - $150,000", (120000, 150000, "USD", "year")),
        ("Rate: 60 - 80 EUR per hour", (60, 80, "EUR", "hour")),
        ("Pay: £5.000 – £6.500 per month", (5000, 6500, "GBP", "month")),
        ("3-5 years of experience", None),
        ("$150k - $100k", None),  # min above max: not a range
    ],
)
def test_salary(tax: Taxonomy, text: str, want: tuple[float, float, str, str] | None) -> None:
    s = extract("Engineer", text, tax).salary
    assert (None if s is None else (s.min, s.max, s.currency, s.period)) == want


def test_regions_and_offsets(tax: Taxonomy) -> None:
    e = extract(
        "Engineer (EU)", "Remote within Europe, UTC-1 to UTC+3, CET preferred. Not for us.", tax
    )
    assert e.regions == ["Europe"]  # "us" (the word) is not the United States
    assert e.utc_offsets == [-1.0, 1.0, 3.0]
    assert extract("Engineer", "US only, GMT±2", tax).utc_offsets == [-2.0, 2.0]


def test_real_posting(tax: Taxonomy) -> None:
    job = json.loads((ROOT / "tests/fixtures/job_senior_data_engineer.json").read_text())
    e = extract(job["title"], job["description_text"], tax)
    got = {s.id: s.requirement for s in e.skills}
    assert got["data_modeling"] == "required"
    assert got["gcp"] == "preferred"  # "...is a significant advantage"
    assert (e.years_required, e.title_level, e.regions) == (7, "senior", ["Europe"])
    assert "SAP" in e.unrecognized
    assert not {"GOOD", "WORK", "FAMILY"} & set(e.unrecognized)  # shouted headings are not terms


def test_deterministic(tax: Taxonomy) -> None:
    job = json.loads((ROOT / "tests/fixtures/job_senior_data_engineer.json").read_text())
    a = extract(job["title"], job["description_text"], tax).model_dump_json()
    assert all(
        extract(job["title"], job["description_text"], tax).model_dump_json() == a for _ in range(5)
    )


def test_duties(tax: Taxonomy) -> None:
    text = "\n".join(
        [
            "About us",
            "We are a fast growing company building tools for logistics.",
            "What you'll do",
            "Design and operate our streaming data platform.",
            "Python, Kafka",  # a tool list, not a duty
            "Requirements",
            "Five years building data pipelines in production.",
        ]
    )
    assert extract("Data Engineer", text, tax).duties == [
        "Design and operate our streaming data platform."
    ]
    # Without a responsibilities heading: sentence-like lines outside ignored sections.
    no_heading = "\n".join(
        [
            "We build data pipelines for retail clients.",
            "Benefits",
            "Free lunch for the whole team daily.",
        ]
    )
    assert extract("Data Engineer", no_heading, tax).duties == [
        "We build data pipelines for retail clients."
    ]
