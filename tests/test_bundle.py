import json
import shutil
from pathlib import Path

import pytest

from matcher import bundle
from matcher.models import ModelStore, Unavailable, UnknownVersion

ROOT = Path(__file__).parent.parent


def make(tmp: Path, name: str = "b") -> Path:
    dest = tmp / name
    bundle.build(dest, ROOT / "data/skills.yaml", ROOT / "defaults/scoring.yaml", parent=None)
    return dest


def edit_manifest(path: Path, **changes: object) -> None:
    m = json.loads((path / "manifest.json").read_text())
    m.update(changes)
    (path / "manifest.json").write_text(json.dumps(m))


def test_build_and_load(tmp_path: Path) -> None:
    b = bundle.load(make(tmp_path))
    assert len(b.taxonomy.skills) > 100 and b.config.weights["skills"] > 0
    assert b.manifest.compatible_matcher_min == bundle.MATCHER_VERSION
    assert {f.name for f in b.manifest.files} == {"taxonomy.yaml", "scoring.yaml"}


@pytest.mark.parametrize(
    ("change", "message"),
    [
        (
            lambda p: (p / "scoring.yaml").write_text((p / "scoring.yaml").read_text() + "\n#"),
            "checksum",
        ),
        (lambda p: (p / "taxonomy.yaml").unlink(), "missing"),
        (lambda p: edit_manifest(p, format_version=2), "bundle format"),
        (lambda p: edit_manifest(p, compatible_matcher_min="99.0.0"), "needs matcher"),
        (
            lambda p: edit_manifest(p, embedding_model={"model": "x", "revision": "y"}),
            "embedding model",
        ),
        (lambda p: (p / "manifest.json").write_text("{"), "manifest"),
    ],
)
def test_unusable_bundles_are_refused(tmp_path: Path, change, message: str) -> None:  # type: ignore[no-untyped-def]
    path = make(tmp_path)
    change(path)
    with pytest.raises(bundle.BundleError, match=message):
        bundle.load(path)


def test_build_refuses_invalid_inputs(tmp_path: Path) -> None:
    bad = tmp_path / "bad.yaml"
    bad.write_text("weights: {vibes: 1}\n")
    with pytest.raises(ValueError):
        bundle.build(tmp_path / "x", ROOT / "data/skills.yaml", bad, parent=None)


class FakeSource:
    """Serves bundles from a directory of version folders; counts downloads."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.downloads = 0
        self.down = False

    def download(self, version: str, dest: Path) -> None:
        if self.down:
            raise Unavailable("registry down")
        if not (self.root / version).is_dir():
            raise UnknownVersion(version)
        self.downloads += 1
        shutil.copytree(self.root / version, dest)


def test_store_downloads_once_and_survives_registry_outage(tmp_path: Path) -> None:
    make(tmp_path / "registry", "1")
    src = FakeSource(tmp_path / "registry")
    store = ModelStore(src, tmp_path / "cache")
    assert store.get("1").config.bands.strong == 75
    store.get("1")
    assert src.downloads == 1
    # A new process (empty memory) with MLflow down still serves the cached version.
    src.down = True
    assert ModelStore(src, tmp_path / "cache").get("1") is not None
    with pytest.raises(Unavailable):
        ModelStore(src, tmp_path / "cache").get("2")
    assert [m["version"] for m in store.listing()] == ["1"]


def test_store_rejects_unknown_and_bad_versions(tmp_path: Path) -> None:
    make(tmp_path / "registry", "1")
    edit_manifest(tmp_path / "registry/1", compatible_matcher_min="99.0.0")
    store = ModelStore(FakeSource(tmp_path / "registry"), tmp_path / "cache")
    with pytest.raises(UnknownVersion):
        store.get("7")
    with pytest.raises(UnknownVersion):
        store.get("../etc")  # versions are numbers, never paths
    with pytest.raises(bundle.BundleError):
        store.get("1")
    assert not (tmp_path / "cache/1").exists()  # the bad copy is not kept
    with pytest.raises(Unavailable):
        ModelStore(None, tmp_path / "cache").get("1")  # no registry, nothing cached
