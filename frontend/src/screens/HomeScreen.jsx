import { useEffect, useState } from 'react';
import Badge from '../components/Badge.jsx';
import { fetchEvents, fetchHistory, fetchRules, pollCheck, startCheck } from '../api/index.js';

function joinJa(labels) {
  if (labels.length <= 1) return labels.join('');
  if (labels.length === 2) return `${labels[0]}と、${labels[1]}`;
  return `${labels.slice(0, -1).join('、')}、${labels[labels.length - 1]}`;
}

function EventGroup({ event, defaultOpen, onOpenEvent, onOpenFinding }) {
  const [open, setOpen] = useState(defaultOpen);
  const total = event.counts.affected + event.counts.needsReview;

  return (
    <div className="mb-3.5 overflow-hidden rounded-xl border border-[var(--line)] bg-[var(--card)]">
      <div
        className="flex cursor-pointer items-center gap-3 bg-[#F6F4EF] px-5 py-3.5"
        onClick={() => setOpen((v) => !v)}
      >
        <span className={`chev w-3.5 shrink-0 text-[11px] text-[var(--sub)] ${open ? 'open' : ''}`} />
        <div className="min-w-0 flex-1">
          <b className="text-[14.5px] font-bold">{event.title}</b>
          <span className="block text-[12px] font-normal text-[var(--sub)]">
            {event.changesCount}件の変更 ・ {event.enforcement.enforced ? '施行済み' : '施行前'} ・ {event.detectedAtLabel}に検知
          </span>
        </div>
        <span className="flex shrink-0 gap-1.5">
          {event.counts.affected > 0 && <Badge tone="shu">要対応 {event.counts.affected}</Badge>}
          {event.counts.needsReview > 0 && <Badge tone="amber">確認待ち {event.counts.needsReview}</Badge>}
        </span>
        <button
          type="button"
          className="whitespace-nowrap text-[13px] text-[var(--green)]"
          onClick={(e) => {
            e.stopPropagation();
            onOpenEvent(event.eventId);
          }}
        >
          変更の内容を見る →
        </button>
      </div>
      {open && (
        <div className="border-t border-[var(--line)]">
          {total === 0 ? (
            <p className="px-5 py-4 text-[13px] text-[var(--sub)]">対応が必要な文書はありません。</p>
          ) : (
            event.actionDocs.map((doc) => (
              <div key={doc.docId} className="flex items-center gap-3.5 border-b border-[var(--line)] px-5 py-3.5 last:border-b-0">
                <Badge tone={doc.status === 'affected' ? 'shu' : 'amber'}>
                  {doc.status === 'affected' ? '要対応' : '確認待ち'}
                </Badge>
                <div className="min-w-0 flex-1">
                  <b className="text-[14.5px] font-bold">{doc.displayName}</b>
                  <span className="block text-[12.5px] text-[var(--sub)]">{doc.issueLabel}</span>
                </div>
                <button
                  type="button"
                  className="whitespace-nowrap text-[13px] text-[var(--green)]"
                  onClick={() => onOpenFinding(event.eventId, doc.changeId, doc.chunkId)}
                >
                  確認する →
                </button>
              </div>
            ))
          )}
        </div>
      )}
    </div>
  );
}

export default function HomeScreen({ onOpenEvent, onOpenFinding }) {
  const [events, setEvents] = useState(null);
  const [history, setHistory] = useState(null);
  const [rules, setRules] = useState(null);
  const [checking, setChecking] = useState(false);
  const [checkLog, setCheckLog] = useState([]);
  const [checkError, setCheckError] = useState(null);
  const [allChanges, setAllChanges] = useState(false);

  async function load() {
    const list = await fetchEvents();
    setEvents(
      [...list].sort((a, b) => b.counts.affected - a.counts.affected || b.counts.needsReview - a.counts.needsReview),
    );
    setHistory(await fetchHistory());
    setRules(await fetchRules());
  }

  useEffect(() => {
    load();
  }, []);

  /**
   * 見張っている法令を今すぐ確認する。1件あたり2〜3分かかるので、
   * 受付だけ先に返してもらい、進み具合を出しながら待つ。
   */
  async function checkNow() {
    setChecking(true);
    setCheckError(null);
    setCheckLog(['チェックを始めます…']);
    try {
      const job = await startCheck(null, { allChanges });
      const done = await pollCheck(job.job_id, (lines) => setCheckLog((prev) => [...prev, ...lines]));
      if (done.state === 'failed') {
        setCheckError(done.error);
      } else {
        await load();
      }
    } catch (e) {
      setCheckError(e.message);
    } finally {
      setChecking(false);
    }
  }

  if (!events || !history || !rules) {
    return <p className="text-sm text-[var(--sub)]">読み込み中…</p>;
  }

  const totalActionDocs = new Set(events.flatMap((e) => e.actionDocs.map((d) => d.docId))).size;
  const actionableEvents = events.filter((e) => e.actionDocs.length > 0);

  return (
    <>
      <div className="py-2 pb-6.5">
        <div className="mb-2.5 font-mono text-[12px] text-[var(--sub)]">最終チェック: 今日 9:00 ／ 次回: 明日 9:00（毎日自動）</div>
        {totalActionDocs === 0 ? (
          <h1 className="text-[26px] font-bold leading-[1.5] tracking-wide">すべてのドキュメントは最新です ✓</h1>
        ) : (
          <h1 className="text-[26px] font-bold leading-[1.5] tracking-wide">
            <span className="text-[var(--shu)]">{actionableEvents.length}件</span>の法令変更により、
            <span className="text-[var(--shu)]">{totalActionDocs}個</span>のドキュメントで対応が必要です。
          </h1>
        )}
        {actionableEvents.length > 0 && (
          <div className="mt-1.5 text-[14px] text-[var(--sub)]">
            {joinJa(actionableEvents.map((e) => e.shortDescription))}の影響を検知しました。
          </div>
        )}
        <div className="mt-4.5 flex items-center gap-2.5">
          <button
            type="button"
            className="rounded-[9px] border border-[var(--shu)] bg-[var(--shu)] px-4.5 py-2.5 text-[13.5px] font-medium text-white"
            onClick={() => actionableEvents[0] && onOpenEvent(actionableEvents[0].eventId)}
          >
            対応が必要なことを見る
          </button>
          <button
            type="button"
            disabled={checking}
            onClick={checkNow}
            className="rounded-[9px] border border-[var(--line)] bg-[var(--card)] px-4.5 py-2.5 text-[13.5px] disabled:opacity-50"
          >
            {checking ? 'チェック中…' : '今すぐチェック'}
          </button>
          <label className="flex items-center gap-1.5 text-[12.5px] text-[var(--sub)]">
            <input
              type="checkbox"
              checked={allChanges}
              disabled={checking}
              onChange={(e) => setAllChanges(e.target.checked)}
            />
            {/* 具体的な分数はここに書かない。変更の数で大きく変わるので、押した直後に
                サーバーが実際の件数から見積もった数字を進捗の1行目に出す */}
            すべての変更を確認する（時間がかかります。目安は実行直後に出します）
          </label>
        </div>

        {(checking || checkLog.length > 0 || checkError) && (
          <div className="mt-3.5 rounded-[10px] border border-[var(--line)] bg-[var(--card)] px-4.5 py-3.5">
            {checkLog.map((line, i) => (
              <p key={i} className={`text-[12.5px] ${i === checkLog.length - 1 && checking ? '' : 'text-[var(--sub)]'}`}>
                {line}
              </p>
            ))}
            {checkError && <p className="mt-1 text-[12.5px] text-[var(--shu)]">{checkError}</p>}
            {checking && (
              <p className="mt-1.5 text-[11.5px] text-[var(--sub)]">
                法令の条文と社内文書を突き合わせています。2〜3分かかります。
              </p>
            )}
          </div>
        )}
      </div>

      <div className="mb-3 mt-7.5 text-[13px] font-bold tracking-wider text-[var(--sub)]">対応が必要なこと</div>
      {events.map((event, i) => (
        <EventGroup key={event.eventId} event={event} defaultOpen={i === 0} onOpenEvent={onOpenEvent} onOpenFinding={onOpenFinding} />
      ))}

      <div className="mb-3 mt-7.5 text-[13px] font-bold tracking-wider text-[var(--sub)]">最近のチェック</div>
      <div className="rounded-xl border border-[var(--line)] bg-[var(--card)]">
        {history.map((h, i) => (
          <div key={i} className="flex items-baseline gap-3.5 border-b border-[var(--line)] px-5 py-2.75 text-[13px] last:border-b-0">
            <span className="w-23 shrink-0 font-mono text-[11.5px] text-[var(--sub)]">{h.timeLabel}</span>
            {h.kind === 'detected' ? (
              <span>
                {h.lawTitle} —{' '}
                <button type="button" className="font-bold text-[var(--shu)]" onClick={() => onOpenEvent(h.eventId)}>
                  変更を検知 →
                </button>
                （{h.summaryLabel}）
              </span>
            ) : (
              <span className="text-[var(--sub)]">{h.lawTitle} — 変更なし</span>
            )}
          </div>
        ))}
      </div>

      <div className="mb-3 mt-7.5 text-[13px] font-bold tracking-wider text-[var(--sub)]">見守り中のルール</div>
      <div className="flex flex-wrap gap-2.5">
        {rules.map((r, i) => (
          <div key={i} className="rounded-[10px] border border-[var(--line)] bg-[var(--card)] px-4 py-2.5 text-[13px]">
            {r.lawTitle}
            <small className="block font-mono text-[10.5px] text-[var(--sub)]">
              {r.source} ／ {r.schedule}
            </small>
          </div>
        ))}
        <div className="rounded-[10px] border border-dashed border-[var(--line)] px-4 py-2.5 text-[13px] text-[var(--sub)]">
          ＋ ルールを追加
        </div>
      </div>
    </>
  );
}
