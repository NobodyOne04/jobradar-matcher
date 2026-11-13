from pathlib import Path

import pytest

from matcher.taxonomy import TaxonomyError, load, parse
from matcher.tokens import tokens

ROOT = Path(__file__).parent.parent


def test_real_taxonomy_is_valid() -> None:
    tax = load(ROOT / "data/skills.yaml")
    assert len(tax.skills) >= 150
    assert tax.index[("apache", "airflow")] == "airflow"
    assert tax.cased_index[("Go",)] == "go"
    assert tax.related("airflow", "dagster")


@pytest.mark.parametrize(
    ("skills", "problem"),
    [
        ("- {id: a, name: A, category: nope, aliases: [a]}", "unknown category"),
        (
            "- {id: a, name: A, category: language, aliases: [a]}\n"
            "- {id: b, name: B, category: language, aliases: [A]}",
            "already belongs to a",
        ),
        ("- {id: a, name: A, category: language, aliases: [a], related: [zzz]}", "does not exist"),
        ("- {id: a, name: A, category: language, aliases: [one two three four five]}", "1-4 words"),
        ("- {id: Bad, name: A, category: language, aliases: [a]}", "id must be"),
        (
            "- {id: a, name: A, category: language, aliases: [a]}\n"
            "- {id: a, name: A2, category: language, aliases: [a2]}",
            "duplicate id",
        ),
    ],
)
def test_invalid_taxonomies(skills: str, problem: str) -> None:
    with pytest.raises(TaxonomyError, match=problem):
        parse("categories: [language]\nskills:\n" + skills)


@pytest.mark.parametrize(
    ("text", "want"),
    [
        ("Python, SQL and C++.", ["Python", "SQL", "and", "C++"]),
        ("C# / .NET / Node.js", ["C#", ".NET", "Node.js"]),
        ("Python/Scala, CI/CD", ["Python", "Scala", "CI", "CD"]),
        ("scikit-learn (sklearn)", ["scikit", "learn", "sklearn"]),
        ("ｆｕｌｌｗｉｄｔｈ Ｓｐａｒｋ", ["fullwidth", "Spark"]),  # NFKC
    ],
)
def test_tokens(text: str, want: list[str]) -> None:
    assert tokens(text) == want
