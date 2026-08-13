"""監視対象の取り込みインターフェース。

DESIGN.md「取り込みとチャンク分割」:
  - 取り込みは DocumentSource（list / read / メタデータ）で抽象化し、LocalFolderSource から実装する
  - クラウド対応は将来 GoogleDriveSource（サービスアカウント方式のみ）に差し替える
  - **ファイル名・フォルダ構造は判定に使わない**（中身で判定する）ため、ここでは位置情報を
    「置換先パスの表示」と「同一ファイルの追跡」にのみ使う
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Literal

# 対応形式は md / txt / docx のみ（CLAUDE.md 実装上の制約）。PDF・pptx は対象外
DocumentFormat = Literal["md", "txt", "docx"]
SUPPORTED_FORMATS: tuple[DocumentFormat, ...] = ("md", "txt", "docx")


@dataclass(frozen=True)
class DocumentRef:
    """一覧に出てくる文書の識別子とメタデータ（本文は読まない）。

    巡回時にこの一覧の差分を取って新規・更新・削除ファイルを検出する。
    """

    doc_id: str  # ソース内で安定した識別子（LocalFolderSource では相対パス）
    name: str
    location: str  # 人間に見せる位置（修正版ファイルの置換先として提示する）
    format: DocumentFormat
    size: int
    modified_at: str  # ISO8601


@dataclass(frozen=True)
class SourceDocument:
    """本文まで読み込んだ文書。"""

    ref: DocumentRef
    text: str

    @property
    def doc_id(self) -> str:
        return self.ref.doc_id


class DocumentSource(ABC):
    """監視対象の読み取り口。実装を差し替えればクラウドにも対応できる。"""

    @property
    @abstractmethod
    def source_id(self) -> str:
        """ソースの識別子（表示用）。"""

    @abstractmethod
    def list(self) -> list[DocumentRef]:
        """配下の対応形式ファイルを再帰的に列挙する。"""

    @abstractmethod
    def read(self, ref: DocumentRef) -> SourceDocument:
        """本文をプレーンテキストとして読む。"""

    def read_all(self) -> list[SourceDocument]:
        return [self.read(ref) for ref in self.list()]


@dataclass(frozen=True)
class ListingDiff:
    """巡回時のファイル一覧差分（新規ファイルの検出）。"""

    added: list[DocumentRef]
    updated: list[DocumentRef]
    removed: list[DocumentRef]

    @property
    def is_empty(self) -> bool:
        return not (self.added or self.updated or self.removed)


def diff_listings(previous: list[DocumentRef], current: list[DocumentRef]) -> ListingDiff:
    prev = {ref.doc_id: ref for ref in previous}
    curr = {ref.doc_id: ref for ref in current}
    return ListingDiff(
        added=[ref for doc_id, ref in curr.items() if doc_id not in prev],
        updated=[
            ref
            for doc_id, ref in curr.items()
            if doc_id in prev
            and (prev[doc_id].size != ref.size or prev[doc_id].modified_at != ref.modified_at)
        ],
        removed=[ref for doc_id, ref in prev.items() if doc_id not in curr],
    )
