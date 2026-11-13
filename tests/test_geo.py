from matcher.score.geo import covers, mentioned


def test_southeast_asia() -> None:
    assert covers("Thailand") == {"TH"}
    assert "TH" in covers("Southeast Asia") and "TH" in covers("APAC") and "TH" in covers("Asia")
    assert "JP" not in covers("Southeast Asia")
    assert mentioned("Remote within Asia-Pacific or Thailand") >= {"TH", "SG"}
    assert mentioned("sea freight and ocean visibility") == frozenset()


def test_cities_and_states_name_their_country() -> None:
    assert mentioned("San Francisco, California; Mountain View") == {"US"}
    assert mentioned("Bengaluru, India") == {"IN"} and mentioned("Tokyo, Japan") == {"JP"}
    assert mentioned("AMER") >= {"US", "BR"}


def test_worldwide_only_in_a_hiring_phrase() -> None:
    from matcher.extract import _regions

    assert _regions("More than 20,000 organizations worldwide use our platform.") == []
    assert _regions("Our global team spans 30 countries.") == []
    for text in ("Remote - Worldwide", "We are a globally remote team", "work from anywhere"):
        assert _regions(text) == ["Worldwide"], text
    assert _regions("This is a fully remote role") == []


def test_location_field_wins_over_regions_in_the_text() -> None:
    from pathlib import Path

    import yaml

    from matcher.schemas import Job, Profile
    from matcher.score import score
    from matcher.score.config import load as load_config
    from matcher.taxonomy import load as load_taxonomy

    root = Path(__file__).parent.parent
    data = yaml.safe_load((root / "tests/fixtures/profile_example.yaml").read_text())
    data["preferences"] = {"locations": ["Thailand"], "hard_constraints": ["locations"]}
    profile = Profile.model_validate(data)
    tax, cfg = load_taxonomy(root / "data/skills.yaml"), load_config(root / "defaults/scoring.yaml")

    def gate(location_text: str) -> str:
        job = Job(
            title="Data Engineer",
            description_text="We serve customers across APAC. Python, SQL.",
            location_text=location_text,
        )
        return score(profile, job, tax, cfg).gates[0].result

    assert gate("Germany (Remote)") == "fail"
    assert gate("Philadelphia, Pennsylvania") == "fail"
    assert gate("Remote") == "pass"  # nothing listed: the text's APAC counts
