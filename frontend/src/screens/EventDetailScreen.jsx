import { useEffect, useState } from 'react';
import Badge from '../components/Badge.jsx';
import Breadcrumb from '../components/Breadcrumb.jsx';
import ProvisionDiff from '../components/ProvisionDiff.jsx';
import { fetchEvent, buildDocTree, buildReflist, buildFunnelView, changeTabLabel, formatCostJpy } from '../api/index.js';

export default function EventDetailScreen({ eventId, initialChangeId, onHome, onOpenFinding }) {
  const [data, setData] = useState(null);
  const [activeChangeId, setActiveChangeId] = useState(initialChangeId ?? null);

  useEffect(() => {
    setData(null);
    fetchEvent(eventId).then((res) => {
      setData(res);
      setActiveChangeId(initialChangeId ?? res?.raw.changes[0]?.change.change_id ?? null);
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [eventId]);

  if (!data) return <p className="text-sm text-[var(--sub)]">読み込み中…</p>;

  const { summary, raw } = data;
  const changeResult = raw.changes.find((cr) => cr.change.change_id === activeChangeId) ?? raw.changes[0];
  const { change } = changeResult;
  const tree = buildDocTree(changeResult);
  const reflist = buildReflist(changeResult);
  const funnel = buildFunnelView(raw, changeResult);
  const cost = formatCostJpy(funnel.costUsd);

  const unchecked = event.raw.changes_unchecked ?? 0;

  return (
    <>
      {unchecked > 0 && (
        <div className="mb-4 rounded-[10px] border border-[var(--amber-soft)] bg-[var(--amber-soft)] px-4 py-2.5 text-[12.5px] text-[var(--amber)]">
          この法令には{event.raw.changes_found}件の変更がありますが、確認したのは
          {event.raw.changes.length}件です。残り{unchecked}件はまだ確認していません。
        </div>
      )}
      <Breadcrumb parts={[{ label: 'ホーム', onClick: onHome }, { label: summary.title, current: true }]} />

      <div className="mb-5">
        <h1 className="mb-1.5 text-[21px] font-bold">{summary.title}</h1>
        <div className="flex flex-wrap items-center gap-2.5">
          {summary.counts.affected > 0 && <Badge tone="shu">要対応 {summary.counts.affected}</Badge>}
          {summary.counts.needsReview > 0 && <Badge tone="amber">確認待ち {summary.counts.needsReview}</Badge>}
          <Badge tone="green">問題なし {summary.counts.notApplicable + summary.counts.none}</Badge>
          <Badge tone="gray">{summary.enforcement.label}</Badge>
          <a
            className="font-mono text-[12px] text-[var(--green)]"
            href={`https://laws.e-gov.go.jp/law/${raw.law_id}`}
            target="_blank"
            rel="noreferrer"
          >
            改正の原文を見る（e-Gov）↗
          </a>
        </div>
      </div>

      <div className="mb-3 mt-7.5 text-[13px] font-bold tracking-wider text-[var(--sub)]">
        何が変わったか（{raw.changes.length}つの変更）
      </div>

      {raw.changes.length > 1 && (
        <div className="mb-3 flex flex-wrap gap-2">
          {raw.changes.map((cr, i) => (
            <button
              key={cr.change.change_id}
              type="button"
              onClick={() => setActiveChangeId(cr.change.change_id)}
              className={`rounded-full border px-4 py-1.5 text-[13px] ${
                cr.change.change_id === activeChangeId
                  ? 'border-[var(--green)] bg-[var(--green)] font-medium text-white'
                  : 'border-[var(--line)] bg-[var(--card)] text-[var(--sub)]'
              }`}
            >
              {changeTabLabel(cr.change, i)}
            </button>
          ))}
        </div>
      )}

      <ProvisionDiff before={change.before_excerpt} after={change.after_excerpt} />

      <div className="mb-3 mt-7.5 text-[13px] font-bold tracking-wider text-[var(--sub)]">この変更の影響ドキュメント</div>
      <div className="overflow-hidden rounded-xl border border-[var(--line)] bg-[var(--card)] py-2">
        {tree.length === 0 && <p className="px-5 py-4 text-[13px] text-[var(--sub)]">影響が見られたドキュメントはありません。</p>}
        {tree.map(({ folder, items }) => (
          <div key={folder}>
            <div className="px-5 pb-0.5 pt-2 font-mono text-[12.5px] text-[var(--sub)]">{folder}/</div>
            {items.map((doc) => (
              <div
                key={doc.docId}
                className={`flex items-center gap-3 border-t border-[var(--line)] py-2.5 pl-9.5 pr-5 ${
                  doc.status === 'affected' ? 'bg-gradient-to-r from-[var(--shu-soft)] to-transparent' : ''
                }`}
              >
                <Badge tone={doc.status === 'affected' ? 'shu' : doc.status === 'needs_review' ? 'amber' : 'gray'}>
                  {doc.status === 'affected' ? '要対応' : doc.status === 'needs_review' ? '確認待ち' : '対象外'}
                </Badge>
                <b className={`flex-1 text-[13.5px] ${doc.status === 'affected' ? 'font-bold' : 'font-medium'}`}>{doc.fileName}</b>
                {doc.status === 'not_applicable' ? (
                  <span className="text-[12px] text-[var(--sub)]">{doc.reason}</span>
                ) : (
                  <button
                    type="button"
                    className="whitespace-nowrap text-[13px] text-[var(--green)]"
                    onClick={() => onOpenFinding(eventId, change.change_id, doc.chunkId)}
                  >
                    確認する →
                  </button>
                )}
              </div>
            ))}
          </div>
        ))}
      </div>

      <details className="mt-2.5 rounded-[10px] border border-[var(--line)] bg-[var(--card)]">
        <summary className="flex list-none items-center gap-2 px-4.5 py-3 text-[13px] text-[var(--sub)]">
          詳細情報（確認の内訳と処理コスト）
        </summary>
        <div className="border-t border-dashed border-[var(--line)] px-4.5 pb-4.5 pt-1">
          <p className="my-2.5 text-[13px]">全ドキュメントを段階的に絞り込んで確認しています。</p>
          <div className="flex flex-wrap items-center gap-2 font-mono text-[12px] text-[var(--sub)]">
            <b className="text-[var(--ink)]">{funnel.totalChunks}</b>箇所
            <span className="text-[var(--line)]">→</span>
            検索で<b className="text-[var(--ink)]">{funnel.stage1Passed}</b>件
            <span className="text-[var(--line)]">→</span>
            一次確認で<b className="text-[var(--ink)]">{funnel.stage2Passed}</b>件
            <span className="text-[var(--line)]">→</span>
            詳細確認の結果 <b style={{ color: 'var(--shu)' }}>要対応{funnel.affected}</b> ／ 問題なし{funnel.none} ／ 対象外
            {funnel.notApplicable}
          </div>
          <p className="mt-2.5 text-[12.5px] text-[var(--sub)]">
            {funnel.isWholeEventCost ? 'このイベント全体の処理コスト' : 'この変更の処理コスト'}:{' '}
            <span className="font-mono">¥{cost.yen}</span>
            {cost.ratioLabel && `（全文を毎回AIに渡す方式との比較: ${cost.ratioLabel}）`}
          </p>

          <p className="mb-0.5 mt-4 text-[13px] font-bold">確認したドキュメント</p>
          <p className="text-[12px] text-[var(--sub)]">検索で候補に挙がり、内容を実際に確認したドキュメントの一覧です。</p>
          <div className="mt-3">
            {reflist.rows.map((row) => (
              <div key={row.docId} className="flex items-center gap-2.5 border-b border-[var(--line)] py-1.75 text-[12.5px] last:border-b-0">
                <b className="flex-1 font-medium">{row.displayName}</b>
                <span className="whitespace-nowrap font-mono text-[11px] text-[var(--sub)]">{row.count}箇所を確認</span>
                <Badge
                  tone={
                    row.status === 'affected' ? 'shu' : row.status === 'needs_review' ? 'amber' : row.status === 'not_applicable' ? 'gray' : 'green'
                  }
                >
                  {row.status === 'affected' ? '要対応' : row.status === 'needs_review' ? '確認待ち' : row.status === 'not_applicable' ? '対象外' : '問題なし'}
                </Badge>
              </div>
            ))}
          </div>
          {reflist.skippedCount > 0 && (
            <p className="mt-2.5 text-[12px] text-[var(--sub)]">
              ほか{reflist.skippedCount}件のドキュメントは、検索では候補に挙がったものの優先度が低いと判断され、詳細確認の対象になりませんでした。
            </p>
          )}
        </div>
      </details>
    </>
  );
}
