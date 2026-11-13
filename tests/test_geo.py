from matcher.score.geo import covers, mentioned


def test_southeast_asia() -> None:
    assert covers("Thailand") == {"TH"}
    assert "TH" in covers("Southeast Asia") and "TH" in covers("APAC") and "TH" in covers("Asia")
    assert "JP" not in covers("Southeast Asia")
    assert mentioned("Remote within Asia-Pacific or Thailand") >= {"TH", "SG"}
    assert mentioned("sea freight and ocean visibility") == frozenset()
