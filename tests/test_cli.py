from pathlib import Path

import pytest

from matcher.cli import main


@pytest.mark.parametrize("command", ["eval", "train"])
def test_train_and_eval_refuse_without_the_embedding_model(
    command: str,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Metrics measured without the responsibilities dimension would not be comparable.
    monkeypatch.setenv("MLFLOW_TRACKING_URI", "http://127.0.0.1:9")  # never reached
    missing = str(tmp_path / "missing")
    argv = {
        "eval": ["eval", "--model", missing, "run", "--profile", "eval/profile.yaml"],
        "train": ["train", "--from-defaults", "--model", missing],
    }[command]
    assert main(argv) == 2
    assert "embedding model not found" in capsys.readouterr().err
