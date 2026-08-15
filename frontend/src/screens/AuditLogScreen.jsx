import { useEffect, useState } from 'react';
import { fetchAudit, formatCheckedAt } from '../api/index.js';

/**
 * 監査ログ（画面⑤）。
 * 「誰が・いつ・どの改正を根拠に・どう判断したか」を、根拠法令とセットで一覧にする。
 * 「対応不要」の判断も残るので、何を見送ったかも追える。
 */
export default function AuditLogScreen() {
  const [entries, setEntries] = useState(null);
  const [filter, setFilter] = useState('all');

  useEffect(() => {
    fetchAudit().then(setEntries);
  }, []);

  if (!entries) return <p className="text-sm text-[var(--sub)]">読み込み中…</p>;

  const shown = filter === 'all' ? entries : entries.filter((e) => e.to_status === filter);

  return (
    <>
      <div className="py-2 pb-6.5">
        <h1 className="text-[26px] font-bold leading-[1.5] tracking-wide">監査ログ</h1>
        <p className="mt-1.5 text-[14px] text-[var(--sub)]">
          誰が、いつ、どの法令の変更を根拠に、どう判断したかの記録です。「対応不要」とした判断も残ります。
        </p>
      </div>

      <div className="mb-3.5 flex flex-wrap gap-2">
        {[
          { key: 'all', label: 'すべて' },
          { key: 'approved', label: '承認' },
          { key: 'rejected', label: '対応不要' },
          { key: 'pending', label: '検討中' },
        ].map((f) => (
          <button
            key={f.key}
            type="button"
            onClick={() => setFilter(f.key)}
            className={`rounded-[9px] border px-4 py-1.5 text-[13px] ${
              filter === f.key
                ? 'border-[var(--green)] bg-[var(--green)] font-medium text-white'
                : 'border-[var(--line)] bg-[var(--card)]'
            }`}
          >
            {f.label}
          </button>
        ))}
      </div>

      {shown.length === 0 ? (
        <div className="rounded-xl border border-[var(--line)] bg-[var(--card)] px-5 py-8 text-center text-[13.5px] text-[var(--sub)]">
          {entries.length === 0
            ? 'まだ判断の記録がありません。指摘詳細で「承認する」「対応不要」「検討中」を選ぶとここに残ります。'
            : 'この条件に当てはまる記録はありません。'}
        </div>
      ) : (
        <div className="overflow-hidden rounded-xl border border-[var(--line)] bg-[var(--card)]">
          {shown.map((entry, i) => (
            <div key={i} className="border-b border-[var(--line)] px-5 py-4 last:border-b-0">
              <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
                <span className="font-mono text-[11.5px] text-[var(--sub)]">
                  {formatCheckedAt(entry.at)}
                </span>
                <b className="text-[14px]">{entry.actor}</b>
                <span className="text-[13px] text-[var(--sub)]">
                  {entry.from_status_label ?? '未対応'} → <b className="text-[var(--ink)]">{entry.to_status_label}</b>
                </span>
              </div>
              <div className="mt-1 text-[13.5px]">{entry.doc_id}</div>
              {entry.evidence_law && (
                <div className="mt-1 text-[12.5px] text-[var(--sub)]">
                  根拠: {entry.evidence_law}
                  {entry.evidence_location ? ` ／ ${entry.evidence_location}` : ''}
                </div>
              )}
              {entry.change_summary && (
                <div className="mt-1 text-[12.5px] text-[var(--sub)]">変更: {entry.change_summary}</div>
              )}
              {entry.note && <div className="mt-1 text-[12.5px]">備考: {entry.note}</div>}
            </div>
          ))}
        </div>
      )}
    </>
  );
}
