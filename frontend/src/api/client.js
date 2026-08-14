/**
 * データ取得口。今は fixture (src/mock/*.json) を返すが、本物のAPIができたら
 * この3関数の中身だけを `fetch('/api/...')` に差し替えれば済む形にしてある。
 * コンポーネント側は PIPELINE_RESULTS / fixture の存在を知らない。
 */
import { PIPELINE_RESULTS } from './fixtures.js';
import { buildEventSummary, findFindingDetail } from './derive.js';

// 検知時刻はイベントJSONに含まれない（PipelineResult に detected_at フィールドが無い）ため、
// デモ用の表示ラベルをここで補う。チェック履歴・見守り中ルールもここで組み立てる
// ダミー（fixture に無いものの組み立ては指示どおりデータ層内に閉じる）。
const DETECTED_AT_LABEL = '今日 9:00';

/** @returns {Promise<ReturnType<typeof buildEventSummary>[]>} ホームで使うイベント一覧 */
export async function fetchEvents() {
  const summaries = PIPELINE_RESULTS.map((r) => buildEventSummary(r, { detectedAtLabel: DETECTED_AT_LABEL }));
  return summaries;
}

/** @param {string} eventId */
export async function fetchEvent(eventId) {
  const raw = PIPELINE_RESULTS.find((r) => r.law_id === eventId);
  if (!raw) return null;
  return { summary: buildEventSummary(raw, { detectedAtLabel: DETECTED_AT_LABEL }), raw };
}

/**
 * @param {string} eventId
 * @param {string} changeId
 * @param {string} chunkId
 */
export async function fetchFinding(eventId, changeId, chunkId) {
  const raw = PIPELINE_RESULTS.find((r) => r.law_id === eventId);
  if (!raw) return null;
  const detail = findFindingDetail(raw, changeId, chunkId);
  if (!detail) return null;
  return { ...detail, pipelineResult: raw };
}

/** 最近のチェック履歴（「変更なし」も含む）。fixtureに無い巡回履歴はここでダミーとして組み立てる。 */
export async function fetchHistory() {
  const events = await fetchEvents();
  const detected = events.map((e) => ({
    kind: 'detected',
    timeLabel: DETECTED_AT_LABEL,
    lawTitle: e.lawTitle,
    eventId: e.eventId,
    summaryLabel: `${e.counts.affected + e.counts.needsReview + e.counts.notApplicable + e.counts.none}件を確認し、${e.counts.affected}件が要対応・${e.counts.notApplicable + e.counts.none}件は問題なし`,
  }));
  const noChange = [
    { kind: 'no_change', timeLabel: '昨日 9:00', lawTitle: '個人情報保護法' },
    { kind: 'no_change', timeLabel: '8/11 9:00', lawTitle: 'すべてのルール' },
  ];
  return [...detected, ...noChange];
}

/** 見守り中のルール一覧。実イベントの法令に加え、変更が無かった監視対象もダミーで1件添える。 */
export async function fetchRules() {
  const events = await fetchEvents();
  const fromEvents = events.map((e) => ({ lawTitle: e.lawTitle, source: 'e-Gov', schedule: '毎日 9:00' }));
  return [...fromEvents, { lawTitle: '個人情報保護法', source: 'e-Gov', schedule: '毎日 9:00' }];
}
