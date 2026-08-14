/**
 * 表示整形ユーティリティ（日付・確信度・期限種別など）。
 * ui-mock.html の文言をそのまま使い、技術語（applicability / confidence 等）は出さない。
 */

/** @param {string|null|undefined} iso 'YYYY-MM-DD' */
export function formatDate(iso) {
  if (!iso) return '未定';
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(iso);
  if (!m) return iso;
  return `${m[1]}-${m[2]}-${m[3]}`;
}

/**
 * 施行日バッジの文言（施行済み / 施行前）。
 * @param {string|null|undefined} enforcementDate
 * @param {Date} today
 */
export function formatEnforcement(enforcementDate, today = new Date()) {
  if (!enforcementDate) return { label: '施行日: 未定', enforced: false };
  const enforced = new Date(enforcementDate) <= today;
  return {
    label: `施行日: ${formatDate(enforcementDate)}（${enforced ? '施行済み' : '施行前'}）`,
    enforced,
  };
}

/** @param {import('./types.js').DeadlineType} deadlineType */
export function formatDeadlineType(deadlineType) {
  switch (deadlineType) {
    case 'immediate':
      return '即時対応';
    case 'on_renewal':
      return '更新時対応';
    default:
      return '';
  }
}

/** @param {import('./types.js').ChangeType} changeType */
export function formatChangeTypeLabel(changeType) {
  switch (changeType) {
    case 'delete':
      return '削除';
    case 'add':
      return '追加';
    case 'effective_date_only':
      return '施行日の変更';
    default:
      return '改正';
  }
}

/** 条番号などの短い見出しを target_path から取り出す（"本則 > 第四章 … > 第十六条の二" → "第十六条の二"）。 */
export function shortTargetPath(targetPath) {
  if (!targetPath) return '';
  const parts = targetPath.split('>').map((s) => s.trim());
  return parts[parts.length - 1] || targetPath;
}

/**
 * 文書ステータスの表示区分（バッジ）。
 * shu=要対応 / amber=確認待ち（要確認） / gray=対象外 / green=問題なし
 * @typedef {'affected'|'needs_review'|'not_applicable'|'none'} DocStatus
 * @param {DocStatus} status
 */
export function statusBadge(status) {
  switch (status) {
    case 'affected':
      return { tone: 'shu', label: '要対応' };
    case 'needs_review':
      return { tone: 'amber', label: '確認待ち' };
    case 'not_applicable':
      return { tone: 'gray', label: '対象外' };
    default:
      return { tone: 'green', label: '問題なし' };
  }
}

/** ファイルパス（doc_id）からフォルダ名とファイル名に分ける。 */
export function splitDocPath(docId) {
  const idx = docId.lastIndexOf('/');
  if (idx < 0) return { folder: null, fileName: docId };
  return { folder: docId.slice(0, idx), fileName: docId.slice(idx + 1) };
}

/**
 * 同名ファイルが複数フォルダにまたがる場合（デモデータの想定どおり: 同一内容ファイルの複数配置）、
 * ファイル名だけでは文書を区別できないため、重複するものにだけ親フォルダ名を補って表示する。
 * @param {{fileName: string, folder: string|null}[]} items
 */
export function withDisambiguatedNames(items) {
  const counts = new Map();
  for (const item of items) counts.set(item.fileName, (counts.get(item.fileName) ?? 0) + 1);
  return items.map((item) => ({
    ...item,
    displayName: counts.get(item.fileName) > 1 && item.folder ? `${item.folder}/${item.fileName}` : item.fileName,
  }));
}

/** 文字列を指定長で省略する（全角・半角を区別しない簡易版）。 */
export function truncate(text, max = 46) {
  if (!text) return '';
  return text.length > max ? `${text.slice(0, max)}…` : text;
}

/** 円換算（概算）。DESIGN.md のコスト設計前提（高性能モデル $3/M input）に合わせた目安レート。 */
const USD_TO_JPY = 150;
/** DESIGN.md「素朴実装: 約¥1,800/イベント」を比較基準として使う。 */
const NAIVE_COST_JPY = 1800;

/** @param {number} costUsd */
export function formatCostJpy(costUsd) {
  const yen = Math.round((costUsd ?? 0) * USD_TO_JPY);
  const ratio = yen > 0 ? Math.max(1, Math.round(NAIVE_COST_JPY / yen)) : null;
  return { yen, ratioLabel: ratio ? `約1/${ratio}` : null };
}

/** ISO日時を「今日 9:00」「昨日 9:00」「8/13 9:00」のように短く出す。 */
export function formatCheckedAt(iso, now = new Date()) {
  if (!iso) return '';
  const at = new Date(iso);
  if (Number.isNaN(at.getTime())) return iso;
  const time = `${at.getHours()}:${String(at.getMinutes()).padStart(2, '0')}`;
  if (at.toDateString() === now.toDateString()) return `今日 ${time}`;
  const yesterday = new Date(now);
  yesterday.setDate(now.getDate() - 1);
  if (at.toDateString() === yesterday.toDateString()) return `昨日 ${time}`;
  return `${at.getMonth() + 1}/${at.getDate()} ${time}`;
}
