import { useEffect, useState } from 'react';
import { fetchRules, setRuleEnabled } from '../api/index.js';

/**
 * 設定（画面④）。
 *
 * 正本ごとに監視を止める／再開できる。止めるとホームからその法令の指摘が消え、
 * 再開すると戻る——正本と社内文書の依存関係が目に見える。
 * **止めても検知結果や判断は消さない**（見るのをやめるだけ）。
 *
 * 正本の新規登録はこの画面では行わない（デモでは事前登録済み。DESIGN.md 画面構成）。
 */
export default function SettingsScreen() {
  const [rules, setRules] = useState(null);
  const [busy, setBusy] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    fetchRules().then(setRules);
  }, []);

  async function toggle(rule) {
    setBusy(rule.lawId);
    setError(null);
    try {
      await setRuleEnabled(rule.lawId, !rule.enabled);
      setRules(await fetchRules());
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(null);
    }
  }

  if (!rules) return <p className="text-sm text-[var(--sub)]">読み込み中…</p>;

  const watching = rules.filter((r) => r.enabled).length;

  return (
    <>
      <div className="py-2 pb-6.5">
        <h1 className="text-[26px] font-bold leading-[1.5] tracking-wide">設定</h1>
        <p className="mt-1.5 text-[14px] text-[var(--sub)]">
          {rules.length}件のルールのうち{watching}件を見張っています。
          監視を止めると、その法令による指摘はホームから消えます（記録は残ります）。
        </p>
      </div>

      {error && (
        <div className="mb-3.5 rounded-[10px] border border-[var(--shu-soft)] bg-[var(--shu-soft)] px-4 py-2.5 text-[12.5px] text-[var(--shu)]">
          {error}
        </div>
      )}

      <div className="mb-3 text-[13px] font-bold tracking-wider text-[var(--sub)]">見守り中のルール</div>
      <div className="mb-7.5 overflow-hidden rounded-xl border border-[var(--line)] bg-[var(--card)]">
        {rules.map((rule) => (
          <div
            key={rule.lawId}
            className="flex flex-wrap items-center gap-x-4 gap-y-2 border-b border-[var(--line)] px-5 py-4 last:border-b-0"
          >
            <span
              className={`flex h-5 w-5 shrink-0 items-center justify-center rounded-[5px] border text-[12px] ${
                rule.enabled
                  ? 'border-[var(--green)] bg-[var(--green)] text-white'
                  : 'border-[var(--line)] text-transparent'
              }`}
              aria-hidden="true"
            >
              ✓
            </span>
            <div className="min-w-0 flex-1">
              <b className={`text-[14px] ${rule.enabled ? '' : 'text-[var(--sub)]'}`}>{rule.lawTitle}</b>
              <span className="block font-mono text-[11.5px] text-[var(--sub)]">
                {rule.enabled ? '監視中' : '監視を停止中'}
                {rule.watchingSince ? ` ・ ${rule.watchingSince} 時点から` : ''}
                {` ・ ${rule.source}`}
              </span>
            </div>
            <button
              type="button"
              disabled={busy === rule.lawId}
              onClick={() => toggle(rule)}
              className="shrink-0 rounded-[9px] border border-[var(--line)] bg-[var(--card)] px-4 py-1.5 text-[13px] disabled:opacity-40"
            >
              {busy === rule.lawId ? '切り替え中…' : rule.enabled ? '監視を止める' : '監視を再開する'}
            </button>
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
