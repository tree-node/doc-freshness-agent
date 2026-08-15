/**
 * データ取得口。ここだけがバックエンドを知っている。
 *
 * バックエンドは PipelineResult（パイプラインの出力）をそのまま返すので、
 * 画面用の整形は derive.js に置いたまま変わらない。
 *
 * APIに繋がらないときは fixture（src/mock/*.json）にフォールバックする。
 * デモ当日にバックエンドが落ちても画面が真っ白にならないようにするため。
 */
import { PIPELINE_RESULTS } from './fixtures.js';
import { buildEventSummary, findFindingDetail } from './derive.js';
import { formatCheckedAt } from './format.js';

/** APIが落ちている／未起動のときに fixture を使ったかどうか。画面に出す用。 */
export const dataSource = { usingFallback: false, reason: null };

async function getJson(path) {
  const res = await fetch(path, { headers: { Accept: 'application/json' } });
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.json();
}

/** APIを試し、駄目なら fixture を返す。 */
async function withFallback(path, fallback, { allow404 = false } = {}) {
  try {
    const value = await getJson(path);
    dataSource.usingFallback = false;
    dataSource.reason = null;
    return value;
  } catch (error) {
    if (allow404 && String(error.message).includes('404')) throw error;
    dataSource.usingFallback = true;
    dataSource.reason = error.message;
    return fallback();
  }
}

/** イベントの生JSON一覧。API優先、駄目なら fixture。 */
async function loadResults() {
  const body = await withFallback('/api/events', () => ({ events: PIPELINE_RESULTS }));
  return body.events ?? [];
}

/** ホームで使うイベント一覧。 */
export async function fetchEvents() {
  const results = await loadResults();
  return results.map((r) => buildEventSummary(r));
}

/** @param {string} eventId */
export async function fetchEvent(eventId) {
  const results = await loadResults();
  const raw = results.find((r) => r.law_id === eventId);
  if (!raw) return null;
  return { summary: buildEventSummary(raw), raw };
}

/**
 * @param {string} eventId
 * @param {string} changeId
 * @param {string} chunkId
 */
export async function fetchFinding(eventId, changeId, chunkId) {
  const results = await loadResults();
  const raw = results.find((r) => r.law_id === eventId);
  if (!raw) return null;
  const detail = findFindingDetail(raw, changeId, chunkId);
  if (!detail) return null;
  return { ...detail, pipelineResult: raw };
}

/**
 * 最近のチェック履歴。**変更が無かったチェックも含む**（DESIGN.md 原則3）。
 * APIが無いときは、検知したイベントぶんだけを履歴として組み立てる。
 */
export async function fetchHistory() {
  const body = await withFallback('/api/history', () => null);
  if (body?.history) {
    return body.history.map((h) => ({
      kind: h.detected ? 'detected' : 'no_change',
      timeLabel: formatCheckedAt(h.checked_at),
      lawTitle: h.law_title,
      eventId: h.law_id,
      summaryLabel: h.summary
        ? `${h.summary.judged}件を確認し、${h.summary.affected}件が要対応・${h.summary.not_affected}件は問題なし`
        : null,
    }));
  }

  const events = await fetchEvents();
  return events.map((e) => ({
    kind: 'detected',
    timeLabel: e.detectedAtLabel,
    lawTitle: e.lawTitle,
    eventId: e.eventId,
    summaryLabel: `${e.counts.affected + e.counts.needsReview + e.counts.notApplicable + e.counts.none}件を確認し、${e.counts.affected}件が要対応`,
  }));
}

/** 見守り中のルール（登録済みの正本）。 */
export async function fetchRules() {
  const body = await withFallback('/api/rules', () => null);
  if (body?.rules) {
    return body.rules.map((r) => ({
      lawId: r.law_id,
      lawTitle: r.law_title,
      source: r.source ?? 'e-Gov',
      enabled: r.enabled !== false,
      watchingSince: r.watching_since ?? null,
      schedule: r.last_fetched_at ? `最終チェック ${formatCheckedAt(r.last_fetched_at)}` : '未チェック',
    }));
  }

  const events = await fetchEvents();
  return events.map((e) => ({
    lawId: e.eventId,
    lawTitle: e.lawTitle,
    source: 'e-Gov',
    enabled: true,
    watchingSince: null,
    schedule: '毎日 9:00',
  }));
}

/**
 * 修正版ファイルを受け取る。作るのはサーバー側で、元のファイルには触らない。
 * 当てられなかったときはサーバーが 422 を返すので、成功したふりをせず理由を投げる。
 */
export async function downloadRevisedDocument(eventId, docId) {
  const url = `/api/events/${encodeURIComponent(eventId)}/revised?doc_id=${encodeURIComponent(docId)}`;
  const res = await fetch(url);
  if (!res.ok) {
    let detail = `HTTP ${res.status}`;
    try {
      detail = (await res.json()).detail ?? detail;
    } catch {
      /* JSONで返ってこない場合はステータスだけ出す */
    }
    throw new Error(`修正版を作れませんでした: ${detail}`);
  }

  const blob = await res.blob();
  const link = document.createElement('a');
  link.href = URL.createObjectURL(blob);
  link.download = docId.split('/').pop();
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(link.href);
}

/** この法令変更に対して人が下した判断の一覧（chunk_id + doc_id をキーに引ける形で返す）。 */
export async function fetchStatuses(eventId) {
  const body = await withFallback(`/api/events/${encodeURIComponent(eventId)}/statuses`, () => null);
  const map = new Map();
  for (const s of body?.statuses ?? []) {
    map.set(`${s.change_id}|${s.chunk_id}|${s.doc_id}`, s);
  }
  return map;
}

/**
 * 判断を保存する。棄却（対応不要）も監査ログに残る。
 * 保存できなかったときは、保存できたふりをせずに投げる。
 */
export async function saveStatus(eventId, { changeId, chunkId, docId, status, note, actor }) {
  const res = await fetch(`/api/events/${encodeURIComponent(eventId)}/statuses`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      change_id: changeId,
      chunk_id: chunkId,
      doc_id: docId,
      status,
      note: note ?? null,
      actor: actor ?? '担当者',
    }),
  });
  if (!res.ok) {
    let detail = `HTTP ${res.status}`;
    try {
      detail = (await res.json()).detail ?? detail;
    } catch {
      /* JSONで返ってこない場合はステータスだけ出す */
    }
    throw new Error(`判断を保存できませんでした: ${detail}`);
  }
  return res.json();
}

/** 監査ログ。誰が・いつ・何を根拠に・どう判断したか。 */
export async function fetchAudit(lawId) {
  const query = lawId ? `?law_id=${encodeURIComponent(lawId)}` : '';
  const body = await withFallback(`/api/audit${query}`, () => ({ audit: [] }));
  return body.audit ?? [];
}

/**
 * 正本の監視を止める／再開する。
 * 止めてもスナップショットや検知結果は消えない（見るのをやめるだけ）。
 */
export async function setRuleEnabled(lawId, enabled) {
  const res = await fetch(`/api/rules/${encodeURIComponent(lawId)}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ enabled }),
  });
  if (!res.ok) {
    let detail = `HTTP ${res.status}`;
    try {
      detail = (await res.json()).detail ?? detail;
    } catch {
      /* JSONで返ってこない場合はステータスだけ出す */
    }
    throw new Error(`監視の切り替えに失敗しました: ${detail}`);
  }
  return res.json();
}

/** 法令をキーワードで探す（登録時に法令IDを知らなくて済むように）。 */
export async function searchLaws(query) {
  const res = await fetch(`/api/laws?q=${encodeURIComponent(query)}`);
  if (!res.ok) throw new Error(await errorDetail(res, '法令を検索できませんでした'));
  return (await res.json()).laws ?? [];
}

/** 正本を登録する。指定した時点の条文を取ってきて、比較の出発点として保存する。 */
export async function registerRule(lawId, asof) {
  const res = await fetch('/api/rules', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ law_id: lawId, asof: asof || null }),
  });
  if (!res.ok) throw new Error(await errorDetail(res, '登録できませんでした'));
  return res.json();
}

async function errorDetail(res, fallback) {
  try {
    return (await res.json()).detail ?? `${fallback}（HTTP ${res.status}）`;
  } catch {
    return `${fallback}（HTTP ${res.status}）`;
  }
}

/** チェックを始める。すぐ受付だけ返るので、進捗は pollCheck で追う。 */
export async function startCheck(lawId) {
  const res = await fetch('/api/checks', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ law_id: lawId ?? null }),
  });
  if (!res.ok) throw new Error(await errorDetail(res, 'チェックを始められませんでした'));
  return res.json();
}

/**
 * チェックの進み具合を追う。終わる（または失敗する）まで待って最後の状態を返す。
 * 進捗が来るたびに onProgress を呼ぶので、画面に出せる。
 */
export async function pollCheck(jobId, onProgress, { intervalMs = 1500, timeoutMs = 900000 } = {}) {
  const until = Date.now() + timeoutMs;
  let seen = 0;
  while (Date.now() < until) {
    const res = await fetch(`/api/checks/${encodeURIComponent(jobId)}`);
    if (!res.ok) throw new Error(await errorDetail(res, 'チェックの状態を取得できませんでした'));
    const job = await res.json();

    if (job.progress.length > seen) {
      onProgress?.(job.progress.slice(seen));
      seen = job.progress.length;
    }
    if (job.state !== 'running') return job;

    await new Promise((resolve) => setTimeout(resolve, intervalMs));
  }
  throw new Error('チェックが時間内に終わりませんでした');
}
