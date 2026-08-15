import { useEffect, useState } from 'react';
import Breadcrumb from '../components/Breadcrumb.jsx';
import {
  downloadRevisedDocument,
  fetchEvent,
  fetchFinding,
  fetchStatuses,
  saveStatus,
  splitDocPath,
  truncate,
} from '../api/index.js';

// バックエンドのステータスと同じ値を使う（app/store.py の STATUSES）
const STATUSES = [
  { key: 'approved', label: '承認する' },
  { key: 'rejected', label: '対応不要' },
  { key: 'pending', label: '検討中' },
];

export default function FindingDetailScreen({ eventId, changeId, chunkId, onHome, onOpenEvent }) {
  const [event, setEvent] = useState(null);
  const [detail, setDetail] = useState(null);
  const [status, setStatus] = useState(null);
  const [downloading, setDownloading] = useState(false);
  const [downloadError, setDownloadError] = useState(null);
  const [statusError, setStatusError] = useState(null);

  useEffect(() => {
    setDetail(null);
    setStatus(null);
    setDownloadError(null);
    setStatusError(null);
    fetchEvent(eventId).then(setEvent);
    fetchFinding(eventId, changeId, chunkId).then(async (found) => {
      setDetail(found);
      if (!found) return;
      // 前に下した判断を復元する（画面を離れても残る）
      const statuses = await fetchStatuses(eventId);
      const saved = statuses.get(`${changeId}|${chunkId}|${found.finding.doc_id}`);
      if (saved) setStatus(saved.status);
    });
  }, [eventId, changeId, chunkId]);

  /** 判断を保存する。保存できなければ、選んだ見た目だけ変えて終わりにしない。 */
  async function chooseStatus(next) {
    const previous = status;
    setStatus(next);
    setStatusError(null);
    try {
      await saveStatus(eventId, {
        changeId,
        chunkId,
        docId: detail.finding.doc_id,
        status: next,
      });
    } catch (error) {
      setStatus(previous);
      setStatusError(error.message);
    }
  }

  /**
   * 修正版ファイルを受け取る。作るのはサーバー側で、元のファイルには触らない。
   * 当てられなかった場合はサーバーが 422 を返すので、成功したふりをせずに理由を出す。
   */
  async function handleDownload() {
    setDownloading(true);
    setDownloadError(null);
    try {
      await downloadRevisedDocument(eventId, detail.finding.doc_id);
    } catch (error) {
      setDownloadError(error.message);
    } finally {
      setDownloading(false);
    }
  }

  if (!event || !detail) return <p className="text-sm text-[var(--sub)]">読み込み中…</p>;

  const { finding, change, otherFindingsForDoc } = detail;
  const { fileName } = splitDocPath(finding.doc_id);
  const changeIndex = event.raw.changes.findIndex((cr) => cr.change.change_id === changeId);

  return (
    <>
      <Breadcrumb
        parts={[
          { label: 'ホーム', onClick: onHome },
          { label: `${event.summary.title} ・ 変更${changeIndex + 1}`, onClick: () => onOpenEvent(eventId, changeId) },
          { label: fileName, current: true },
        ]}
        extra={
          otherFindingsForDoc.length > 0 ? (
            <span className="text-[var(--sub)]">この文書へのほかの指摘が{otherFindingsForDoc.length}件あります</span>
          ) : (
            <span className="text-[var(--sub)]">この文書へのほかの指摘はありません</span>
          )
        }
      />

      {finding.needs_human_review && (
        <div className="mb-4 rounded-[10px] border border-[var(--amber-soft)] bg-[var(--amber-soft)] px-4 py-2.5 text-[12.5px] text-[var(--amber)]">
          要確認: {finding.review_reason ?? '確信度が低いため、人による確認をおすすめします'}
        </div>
      )}

      <div className="grid grid-cols-1 items-start gap-4.5 lg:grid-cols-[1.15fr_.85fr]">
        <div className="rounded-xl border border-[var(--line)] bg-[var(--card)] px-7.5 py-6.5 text-[13.5px] leading-[2.1]">
          <h3 className="mb-3.5 text-[14px] font-bold">{fileName}</h3>
          <p className="mt-3.5 font-bold">{finding.evidence_location || finding.label}</p>
          {finding.evidence_verified && finding.evidence_quote ? (
            <p>
              …<mark>{finding.evidence_quote}</mark>…
            </p>
          ) : (
            <p className="text-[var(--sub)]">
              根拠となる引用箇所を本文中で特定できませんでした。内容を確認のうえご判断ください（要確認）。
            </p>
          )}
        </div>

        <div>
          <div className="mb-3.5 rounded-xl border border-[var(--line)] bg-[var(--card)] px-5.5 py-4.5">
            <h4 className="mb-2.5 text-[12.5px] font-bold tracking-wider text-[var(--sub)]">なぜ対応が必要か</h4>
            <p className="mb-2 text-[13px]">{finding.applicability_reason}</p>
            {change.after_excerpt && (
              <div className="mb-2 rounded-r-lg border-l-[3px] border-[var(--green)] bg-[var(--green-soft)] px-3.5 py-1.5 text-[13px]">
                「{truncate(change.after_excerpt, 90)}」
              </div>
            )}
            <a
              className="font-mono text-[12px] text-[var(--green)]"
              href={`https://laws.e-gov.go.jp/law/${event.raw.law_id}`}
              target="_blank"
              rel="noreferrer"
            >
              改正条文の原文（e-Gov）↗
            </a>
          </div>

          <div className="mb-3.5 rounded-xl border border-[var(--line)] bg-[var(--card)] px-5.5 py-4.5">
            <h4 className="mb-2.5 text-[12.5px] font-bold tracking-wider text-[var(--sub)]">修正の提案</h4>
            {finding.fix_proposal ? (
              <>
                <div className="mb-1.5 rounded-lg bg-[#FAF7F4] px-3 py-2 text-[13px] text-[var(--sub)] line-through decoration-[var(--shu)]">
                  {finding.fix_proposal.before}
                </div>
                <div className="rounded-lg bg-[var(--green-soft)] px-3 py-2 text-[13px]">{finding.fix_proposal.after}</div>
              </>
            ) : (
              <p className="text-[13px] text-[var(--sub)]">自動生成の修正案はありません。内容を確認のうえ、対応方針をご検討ください。</p>
            )}
          </div>

          <div className="rounded-xl border border-[var(--line)] bg-[var(--card)] px-5.5 py-4.5">
            <h4 className="mb-2.5 text-[12.5px] font-bold tracking-wider text-[var(--sub)]">判断</h4>
            <div className="flex flex-wrap gap-2">
              {STATUSES.map((s) => (
                <button
                  key={s.key}
                  type="button"
                  onClick={() => chooseStatus(s.key)}
                  className={`flex-1 rounded-[9px] border px-4.5 py-2.25 text-center text-[13.5px] ${
                    status === s.key
                      ? 'border-[var(--green)] bg-[var(--green)] font-medium text-white'
                      : 'border-[var(--line)] bg-[var(--card)]'
                  }`}
                >
                  {s.label}
                </button>
              ))}
            </div>
            <button
              type="button"
              disabled={status !== 'approved' || !finding.fix_proposal || downloading}
              onClick={handleDownload}
              className="mt-2.5 w-full rounded-[9px] border border-[var(--line)] bg-[var(--card)] px-4.5 py-2.25 text-center text-[13.5px] disabled:cursor-not-allowed disabled:opacity-40"
            >
              {downloading ? '作成中…' : '修正版をダウンロード（承認後）'}
            </button>
            {statusError && <p className="mt-2 text-[12px] text-[var(--shu)]">{statusError}</p>}
            {downloadError && (
              <p className="mt-2 text-[12px] text-[var(--shu)]">{downloadError}</p>
            )}
            <p className="mt-2.5 text-[11.5px] text-[var(--sub)]">
              ファイルの置き換えはご自身で行ってください。置き換え先: <span className="font-mono">{finding.doc_id}</span>
            </p>
          </div>
        </div>
      </div>
    </>
  );
}
