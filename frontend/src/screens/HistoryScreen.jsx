import { useEffect, useState } from 'react';
import { fetchHistory } from '../api/index.js';

/**
 * チェック履歴。**変更が無かったチェックも出す**（DESIGN.md 原則3「影響なしも見せる」）。
 * 何もしていないのではなく、見た上で変更が無かった、と分かることが大事。
 */
export default function HistoryScreen({ onOpenEvent }) {
  const [history, setHistory] = useState(null);

  useEffect(() => {
    fetchHistory().then(setHistory);
  }, []);

  if (!history) return <p className="text-sm text-[var(--sub)]">読み込み中…</p>;

  const detected = history.filter((h) => h.kind === 'detected').length;

  return (
    <>
      <div className="py-2 pb-6.5">
        <h1 className="text-[26px] font-bold leading-[1.5] tracking-wide">チェック履歴</h1>
        <p className="mt-1.5 text-[14px] text-[var(--sub)]">
          {history.length}回のチェックのうち、{detected}回で変更を検知しました。変更が無かったチェックも記録しています。
        </p>
      </div>

      {history.length === 0 ? (
        <div className="rounded-xl border border-[var(--line)] bg-[var(--card)] px-5 py-8 text-center text-[13.5px] text-[var(--sub)]">
          まだチェックの記録がありません。
        </div>
      ) : (
        <div className="overflow-hidden rounded-xl border border-[var(--line)] bg-[var(--card)]">
          {history.map((h, i) => (
            <div key={i} className="flex flex-wrap items-baseline gap-x-3.5 gap-y-1 border-b border-[var(--line)] px-5 py-3.5 text-[13.5px] last:border-b-0">
              <span className="w-23 shrink-0 font-mono text-[11.5px] text-[var(--sub)]">{h.timeLabel}</span>
              {h.kind === 'detected' ? (
                <span className="min-w-0 flex-1">
                  {h.lawTitle} —{' '}
                  <button type="button" className="font-bold text-[var(--shu)]" onClick={() => onOpenEvent(h.eventId)}>
                    変更を検知 →
                  </button>
                  {h.summaryLabel && <span className="text-[var(--sub)]">（{h.summaryLabel}）</span>}
                </span>
              ) : (
                <span className="min-w-0 flex-1 text-[var(--sub)]">{h.lawTitle} — 変更なし</span>
              )}
            </div>
          ))}
        </div>
      )}
    </>
  );
}
