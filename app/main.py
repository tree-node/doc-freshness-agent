"""FastAPI アプリ本体（雛形）。

パイプライン・画面用のエンドポイントは以降のタスクで `app/api/` に足していく。
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import db
from app.api import router as api_router
from app.config import settings

# 出典明示（政府標準利用規約）。README とアプリのフッターに出す文言の単一の出所
EGOV_ATTRIBUTION = (
    "法令データは e-Gov 法令検索（デジタル庁）法令API v2 より取得しています。"
    "https://laws.e-gov.go.jp/"
)

app = FastAPI(
    title="ドキュメント鮮度監視エージェント",
    description="正本の変更イベントを起点に、影響を受ける社内文書と箇所を特定する",
    version="0.1.0",
)

# 開発時は Vite dev server (5173) から叩く
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


app.include_router(api_router)


@app.get("/api/health")
def health() -> dict:
    """疎通確認。キーの値は返さず、設定済みかどうかだけを返す。"""
    return {
        "status": "ok",
        "db": {"path": str(settings.db_path), "writable": db.ping()},
        "watch_root": str(settings.watch_root),
        "configured": {
            "orcarouter_api_key": settings.orcarouter_api_key is not None,
            "models": {
                "stage0": settings.model_stage0,
                "stage2": settings.model_stage2,
                "stage3": settings.model_stage3,
                "escalation": settings.model_escalation,
            },
        },
        "attribution": EGOV_ATTRIBUTION,
    }
