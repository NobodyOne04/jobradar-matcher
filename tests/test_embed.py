import shutil
from pathlib import Path

import pytest
import yaml

from matcher.embed import Embedder, manifest, verify
from matcher.schemas import Job, Profile
from matcher.score import score
from matcher.score.config import load as load_config
from matcher.taxonomy import load

ROOT = Path(__file__).parent.parent
MODEL = ROOT / ".models/bge-small-en-v1.5"

pytestmark = pytest.mark.skipif(
    not MODEL.is_dir(), reason="embedding model missing: run `uv run matcher fetch-model`"
)


@pytest.fixture(scope="module")
def embedder() -> Embedder:
    return Embedder(MODEL, manifest(ROOT / "data/embedding_model.json"))


def test_tampered_model_is_refused(tmp_path: Path) -> None:
    m = manifest(ROOT / "data/embedding_model.json")
    shutil.copytree(MODEL, tmp_path / "m")
    (tmp_path / "m/vocab.txt").write_text("changed")
    with pytest.raises(ValueError, match=r"vocab\.txt"):
        verify(tmp_path / "m", m)
    (tmp_path / "m/vocab.txt").unlink()
    with pytest.raises(ValueError, match="missing or changed"):
        verify(tmp_path / "m", m)


def test_vectors_are_unit_length_and_stable(embedder: Embedder) -> None:
    texts = ["Built streaming ingestion with Kafka", "Perform dental cleanings"]
    a = embedder.embed(texts)
    assert a.shape == (2, 384)
    assert abs(float((a[0] ** 2).sum()) - 1) < 1e-5
    fresh = Embedder(MODEL, manifest(ROOT / "data/embedding_model.json")).embed(texts)
    assert (a == fresh).all()  # bit-identical across separate loads


def _responsibilities(
    embedder: Embedder | None, title: str, text: str
) -> tuple[float | None, list[str]]:
    p = Profile.model_validate(
        yaml.safe_load((ROOT / "tests/fixtures/profile_example.yaml").read_text())
    )
    r = score(
        p,
        Job(title=title, description_text=text),
        load(ROOT / "data/skills.yaml"),
        load_config(ROOT / "defaults/scoring.yaml"),
        embedder,
    )
    d = next(d for d in r.dimensions if d.name == "responsibilities")
    return d.score, d.evidence


def test_related_duties_score_above_unrelated(embedder: Embedder) -> None:
    data, ev = _responsibilities(
        embedder,
        "Data Engineer",
        "What you'll do\n"
        "Build and run batch pipelines with Airflow and dbt on Snowflake.\n"
        "Operate Kafka streaming ingestion at high volume.",
    )
    dentist, _ = _responsibilities(
        embedder,
        "Dentist",
        "What you'll do\n"
        "Perform dental cleanings, exams and fillings for patients.\n"
        "Educate patients about oral hygiene and preventive care.",
    )
    assert data is not None and dentist is not None
    assert data > 0.5 > dentist
    assert len(ev) == 3 and "~" in ev[1]  # summary + the closest pairs


def test_unknown_without_model_or_duties(embedder: Embedder) -> None:
    assert (
        _responsibilities(
            None, "Data Engineer", "What you'll do\nBuild data pipelines on AWS daily."
        )[0]
        is None
    )
    assert _responsibilities(embedder, "Data Engineer", "Python, SQL")[0] is None
