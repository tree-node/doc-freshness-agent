"""テスト共通設定。

`app.config` はモジュール読み込み時に `.env` を読むため、**app を import する前に**
DB の出力先を一時ディレクトリへ向ける（テストがリポジトリ内にDBを作らないように）。
python-dotenv は既存の環境変数を上書きしないので、ここでの設定が優先される。
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

os.environ["DB_PATH"] = str(Path(tempfile.mkdtemp(prefix="dfa-test-")) / "test.sqlite")
