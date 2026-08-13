"""環境変数の読み込み。

キーは `.env`（gitignore 済み）から読む。テストや `--help` 相当の起動で落ちないよう、
**未設定でも import は通す**。実際に必要になった時点で `require()` で明示的に落とす。
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parent.parent

load_dotenv(REPO_ROOT / ".env")


def _path_from_env(name: str, default: str) -> Path:
    """相対パスはリポジトリルート基準に解決する（起動ディレクトリに依存させない）。"""
    raw = Path(os.getenv(name) or default)
    return raw if raw.is_absolute() else (REPO_ROOT / raw).resolve()


@dataclass(frozen=True)
class Settings:
    # --- OrcaRouter（呼び出し実装は次タスク。ここでは読み込みのみ） ---
    orcarouter_api_key: str | None
    orcarouter_base_url: str
    model_stage0: str | None
    model_stage2: str | None
    model_stage3: str | None
    model_escalation: str | None

    # --- Embeddings ---
    embeddings_api_key: str | None
    embeddings_model: str | None

    # --- 経路B（P1） ---
    github_token: str | None

    # --- アプリ設定 ---
    watch_root: Path
    db_path: Path
    snapshots_dir: Path

    @classmethod
    def load(cls) -> "Settings":
        return cls(
            orcarouter_api_key=os.getenv("ORCAROUTER_API_KEY") or None,
            orcarouter_base_url=os.getenv("ORCAROUTER_BASE_URL")
            or "https://api.orcarouter.ai/v1",
            model_stage0=os.getenv("MODEL_STAGE0") or None,
            model_stage2=os.getenv("MODEL_STAGE2") or None,
            model_stage3=os.getenv("MODEL_STAGE3") or None,
            model_escalation=os.getenv("MODEL_ESCALATION") or None,
            embeddings_api_key=os.getenv("EMBEDDINGS_API_KEY") or None,
            embeddings_model=os.getenv("EMBEDDINGS_MODEL") or None,
            github_token=os.getenv("GITHUB_TOKEN") or None,
            watch_root=_path_from_env("WATCH_ROOT", "./demo-data"),
            db_path=_path_from_env("DB_PATH", "./data/app.sqlite"),
            snapshots_dir=_path_from_env("SNAPSHOTS_DIR", "./data/snapshots"),
        )

    def require(self, field: str) -> str:
        """未設定なら分かるメッセージで落とす（キーの値そのものは絶対に出さない）。"""
        value = getattr(self, field)
        if not value:
            raise RuntimeError(
                f"設定 {field.upper()} が未設定です。.env.example を参考に .env へ設定してください。"
            )
        return str(value)


settings = Settings.load()
