from __future__ import annotations

import pytest

from app.config import REPO_ROOT, Settings, settings


def test_paths_are_absolute() -> None:
    """相対パス設定は起動ディレクトリではなくリポジトリルート基準に解決される。"""
    assert settings.db_path.is_absolute()
    assert settings.watch_root.is_absolute()


def test_defaults_when_env_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("ORCAROUTER_API_KEY", "MODEL_STAGE3", "WATCH_ROOT", "DB_PATH"):
        monkeypatch.delenv(name, raising=False)
    loaded = Settings.load()
    assert loaded.orcarouter_api_key is None
    assert loaded.model_stage3 is None
    assert loaded.watch_root == (REPO_ROOT / "demo-data").resolve()
    assert loaded.db_path == (REPO_ROOT / "data/app.sqlite").resolve()


def test_require_raises_without_leaking_value(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ORCAROUTER_API_KEY", "")
    loaded = Settings.load()
    with pytest.raises(RuntimeError, match="ORCAROUTER_API_KEY"):
        loaded.require("orcarouter_api_key")


def test_require_returns_value() -> None:
    loaded = Settings.load()
    assert loaded.require("orcarouter_base_url").startswith("https://")
