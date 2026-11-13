"""The sentence-embedding model (matcher ADR 0002): pinned, checksum-verified, CPU, one thread.

The model files are fetched once (`matcher fetch-model`, at image build time) at the revision
in data/embedding_model.json and never at runtime. One ONNX thread keeps results bit-stable.
"""

import hashlib
import json
from pathlib import Path

import numpy as np
from numpy.typing import NDArray
from pydantic import BaseModel

MANIFEST = Path("data/embedding_model.json")


class PinnedFile(BaseModel):
    name: str
    sha256: str


class Manifest(BaseModel):
    model: str
    repo: str
    revision: str
    license: str
    dim: int
    files: list[PinnedFile]


def manifest(path: Path = MANIFEST) -> Manifest:
    return Manifest.model_validate(json.loads(path.read_text(encoding="utf-8")))


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def verify(model_dir: Path, m: Manifest) -> None:
    """Raise unless every pinned file is present with its pinned checksum."""
    bad = [
        f.name
        for f in m.files
        if not (model_dir / f.name).is_file() or _sha256(model_dir / f.name) != f.sha256
    ]
    if bad:
        raise ValueError(
            f"embedding model files missing or changed in {model_dir}: {', '.join(bad)}"
        )


def fetch(model_dir: Path, m: Manifest) -> None:
    """Download the pinned files (the only network access, at build time) and verify them."""
    from huggingface_hub import hf_hub_download

    for f in m.files:
        hf_hub_download(m.repo, f.name, revision=m.revision, local_dir=model_dir)
    verify(model_dir, m)


class Embedder:
    """Unit-length sentence vectors; repeated texts are embedded once per process."""

    def __init__(self, model_dir: Path, m: Manifest) -> None:
        import onnxruntime
        from fastembed import TextEmbedding

        # ONNX Runtime has opt-out telemetry; nothing about this machine or its use leaves it.
        onnxruntime.disable_telemetry_events()

        verify(model_dir, m)
        self.manifest = m
        self._model = TextEmbedding(
            model_name=m.model, specific_model_path=str(model_dir), threads=1
        )
        self._cache: dict[str, NDArray[np.float32]] = {}

    def embed(self, texts: list[str]) -> NDArray[np.float32]:
        todo = [t for t in dict.fromkeys(texts) if t not in self._cache]
        if todo:
            for text, vec in zip(todo, self._model.embed(todo), strict=True):
                v = np.asarray(vec, dtype=np.float32)
                self._cache[text] = v / (np.linalg.norm(v) or 1.0)
        return (
            np.stack([self._cache[t] for t in texts])
            if texts
            else np.zeros((0, self.manifest.dim), np.float32)
        )
