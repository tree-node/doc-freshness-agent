"""e-Gov 法令API v2 クライアント（認証不要）。

パラメータの根拠は PROGRESS.md 決定ログ 2026-08-13 の実機確認結果。
出典: e-Gov 法令検索（デジタル庁）https://laws.e-gov.go.jp/
"""

from __future__ import annotations

import time
from dataclasses import dataclass

import httpx

API_BASE = "https://laws.e-gov.go.jp/api/2"

# 法令ID（実機確認済み）。同名の「船員に関する〜施行規則」403M50000800036 と混同しないこと
LAW_ID_IKUKAI = "403AC0000000076"  # 育児・介護休業法
LAW_ID_IKUKAI_RULE = "403M50002000025"  # 育児・介護休業法施行規則


class EGovError(RuntimeError):
    pass


@dataclass(frozen=True)
class Revision:
    """改正履歴の1件。"""

    law_revision_id: str
    enforcement_date: str | None
    promulgate_date: str | None
    amendment_law_title: str | None
    status: str | None  # CurrentEnforced | PreviousEnforced | UnEnforced

    @property
    def is_unenforced(self) -> bool:
        """未施行（施行日が未来）。施行前に先回りして検知するために使う。"""
        return self.status == "UnEnforced"


class EGovClient:
    def __init__(self, timeout: float = 30.0, retries: int = 2, base_url: str = API_BASE) -> None:
        self._base_url = base_url
        self._retries = retries
        self._client = httpx.Client(
            timeout=timeout,
            headers={"User-Agent": "doc-freshness-agent"},
        )

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "EGovClient":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def _get(self, path: str, **params: str | None) -> dict:
        query = {k: v for k, v in params.items() if v is not None}
        url = f"{self._base_url}/{path}"
        last_error: Exception | None = None
        for attempt in range(self._retries + 1):
            try:
                res = self._client.get(url, params=query)
                # 4xx はリトライしても無駄（パラメータが誤っている）
                if res.status_code >= 400:
                    if res.status_code < 500:
                        raise EGovError(f"{res.status_code} {url} {res.text[:200]}")
                    res.raise_for_status()
                return res.json()
            except EGovError:
                raise
            except Exception as exc:  # ネットワーク断・5xx
                last_error = exc
                if attempt < self._retries:
                    time.sleep(1.0 * (attempt + 1))
        raise EGovError(f"e-Gov API への接続に失敗しました: {url}") from last_error

    def search_laws(self, law_title: str, limit: int = 20) -> list[dict]:
        """法令名（部分一致）で検索する。

        **部分一致なので同名の別法令が混ざる**（育介法の検索には船員向け施行規則が入る）。
        呼び出し側で law_id を確定させること。
        """
        data = self._get("laws", law_title=law_title, limit=str(limit))
        return data.get("laws", [])

    def get_revisions(self, law_id: str) -> list[Revision]:
        data = self._get(f"law_revisions/{law_id}")
        return [
            Revision(
                law_revision_id=rev["law_revision_id"],
                enforcement_date=rev.get("amendment_enforcement_date"),
                promulgate_date=rev.get("amendment_promulgate_date"),
                amendment_law_title=rev.get("amendment_law_title"),
                status=rev.get("current_revision_status"),
            )
            for rev in data.get("revisions", [])
        ]

    def get_law_data(self, law_id: str, asof: str | None = None, elm: str | None = None) -> dict:
        """法令本文を取得する。

        asof: `YYYY-MM-DD`。**公布日ではなく施行日基準**で「その時点以前の最新リビジョン」。
        elm : 条の名指し取得。枝番はアンダースコア連結（`Article_16_2`。`Article_16の2` は400）。
        """
        return self._get(
            f"law_data/{law_id}",
            asof=asof,
            elm=elm,
            response_format="json",
            law_full_text_format="json",
            json_format="light",
        )
