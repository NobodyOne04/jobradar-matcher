"""Model bundles (matcher ADR 0004): everything that decides a score, apart from code and the
pretrained embedding model, as files with checksums. A bundle never changes once written.

    manifest.json   format, parent, matcher range, embedding model, files and their sha256
    taxonomy.yaml   the skill taxonomy (ADR 0002)
    scoring.yaml    weights, thresholds, cut-offs, FX rates (ADR 0002)
"""

import hashlib
import json
import shutil
from dataclasses import dataclass
from importlib.metadata import version as package_version
from pathlib import Path

from pydantic import BaseModel

from matcher import embed
from matcher.score.config import ScoringConfig
from matcher.score.config import load as load_config
from matcher.taxonomy import Taxonomy
from matcher.taxonomy import load as load_taxonomy

FORMAT_VERSION = 1
FILES = ("taxonomy.yaml", "scoring.yaml")
MATCHER_VERSION = package_version("jobradar-matcher")


class BundleError(ValueError):
    """The bundle cannot be used: missing, changed, or made for another matcher or model."""


class PinnedFile(BaseModel):
    name: str
    sha256: str


class EmbeddingRef(BaseModel):
    model: str
    revision: str


class Manifest(BaseModel):
    format_version: int
    parent: str | None  # the model version it was derived from
    matcher_version: str  # the matcher that built it
    compatible_matcher_min: str  # this matcher version or newer, within the same major
    embedding_model: EmbeddingRef
    seed: int
    training_data: dict[str, object] | None  # label snapshot summary, when trained on labels
    files: list[PinnedFile]


@dataclass(frozen=True)
class Bundle:
    manifest: Manifest
    taxonomy: Taxonomy
    config: ScoringConfig


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _parse(v: str) -> tuple[int, ...]:
    return tuple(int(x) for x in v.split(".")[:3])


def build(dest: Path, taxonomy: Path, config: Path, parent: str | None) -> Manifest:
    """Write a new bundle into the empty directory dest. Both files are validated first."""
    load_taxonomy(taxonomy)
    load_config(config)
    dest.mkdir(parents=True, exist_ok=False)
    shutil.copyfile(taxonomy, dest / "taxonomy.yaml")
    shutil.copyfile(config, dest / "scoring.yaml")
    emb = embed.manifest()
    m = Manifest(
        format_version=FORMAT_VERSION,
        parent=parent,
        matcher_version=MATCHER_VERSION,
        compatible_matcher_min=MATCHER_VERSION,
        embedding_model=EmbeddingRef(model=emb.model, revision=emb.revision),
        seed=0,
        training_data=None,
        files=[PinnedFile(name=f, sha256=_sha256(dest / f)) for f in FILES],
    )
    (dest / "manifest.json").write_text(m.model_dump_json(indent=1) + "\n", encoding="utf-8")
    return m


def load(path: Path) -> Bundle:
    """Verify and load a bundle; BundleError says why it cannot be used here."""
    try:
        m = Manifest.model_validate_json((path / "manifest.json").read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise BundleError(f"no valid manifest.json: {e}") from e
    if m.format_version != FORMAT_VERSION:
        raise BundleError(f"bundle format {m.format_version}, this matcher reads {FORMAT_VERSION}")
    current, minimum = _parse(MATCHER_VERSION), _parse(m.compatible_matcher_min)
    if current[0] != minimum[0] or current < minimum:
        raise BundleError(
            f"needs matcher >= {m.compatible_matcher_min} within the same major; "
            f"this is {MATCHER_VERSION}"
        )
    emb = embed.manifest()
    if (m.embedding_model.model, m.embedding_model.revision) != (emb.model, emb.revision):
        raise BundleError(
            f"made for embedding model {m.embedding_model.model}@"
            f"{m.embedding_model.revision[:8]}, this image has {emb.model}@{emb.revision[:8]}"
        )
    if {f.name for f in m.files} != set(FILES):
        raise BundleError(f"files {sorted(f.name for f in m.files)}, expected {sorted(FILES)}")
    for f in m.files:
        if not (path / f.name).is_file() or _sha256(path / f.name) != f.sha256:
            raise BundleError(f"{f.name} is missing or does not match its checksum")
    return Bundle(
        manifest=m,
        taxonomy=load_taxonomy(path / "taxonomy.yaml"),
        config=load_config(path / "scoring.yaml"),
    )


def manifest_dict(path: Path) -> dict[str, object]:
    return dict(json.loads((path / "manifest.json").read_text(encoding="utf-8")))
