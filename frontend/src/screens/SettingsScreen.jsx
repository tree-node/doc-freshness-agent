import { useEffect, useState } from 'react';
import { fetchRules } from '../api/index.js';

/**
 * 設定（画面④）。デモでは正本も監視対象も事前に登録済みなので、
 * **いま何を見ているかを確認できる表示にとどめる**（登録・編集は実装しない）。
 */
export default function SettingsScreen() {
  const [rules, setRules] = useState(null);

  useEffect(() => {
    fetchRules().then(setRules);
  }, []);

  if (!rules) return <p className="text-sm text-[var(--sub)]">読み込み中…</p>;

  return (
    <>
      <div className="py-2 pb-6.5">
        <h1 className="text-[26px] font-bold leading-[1.5] tracking-wide">設定</h1>
        <p className="mt-1.5 text-[14px] text-[var(--sub)]">
          いま見張っているルールと、チェックしている文書の置き場所です。
        </p>
      </div>

      <div className="mb-3 text-[13px] font-bold tracking-wider text-[var(--sub)]">見守り中のルール</div>
      <div className="mb-7.5 overflow-hidden rounded-xl border border-[var(--line)] bg-[var(--card)]">
        {rules.map((rule, i) => (
          <div key={i} className="border-b border-[var(--line)] px-5 py-3.5 last:border-b-0">
            <b className="text-[14px]">{rule.lawTitle}</b>
            <span className="block font-mono text-[11.5px] text-[var(--sub)]">
              {rule.source} ／ {rule.schedule}
            </span>
          </div>
        ))}
        <div className="border-t border-dashed border-[var(--line)] px-5 py-3.5 text-[13px] text-[var(--sub)]">
          ＋ ルールを追加（この画面からの登録は未実装です）
        </div>
      </div>

      <div className="mb-3 text-[13px] font-bold tracking-wider text-[var(--sub)]">チェックする文書</div>
      <div className="rounded-xl border border-[var(--line)] bg-[var(--card)] px-5 py-4 text-[13.5px]">
        <p className="mb-1">
          監視対象フォルダ: <span className="font-mono text-[12.5px]">demo-data/監視対象</span>
        </p>
        <p className="text-[12.5px] text-[var(--sub)]">
          フォルダの中を再帰的に読みます。対応形式は md / txt / docx です。
          ファイル名やフォルダ名は判定に使わず、中身だけで判断します。
        </p>
      </div>
    </>
  );
}
