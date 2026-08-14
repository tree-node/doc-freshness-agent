/**
 * PipelineResult（バックエンドの生JSON）から画面表示用のモデルを組み立てるロジック。
 * ここに置く理由: 本物のAPIに差し替わっても、バックエンドがこの整形まで
 * やってくれるとは限らないため、フロント側の変換ロジックは1箇所にまとめておく。
 *
 * 「主語はイベント」（DESIGN.md 設計原則1）: PipelineResult 1件 = 法令の変更イベント1件。
 * 配下の changes[] が個々の変更、findings[] が変更ごとの判定（チャンク単位）。
 */
import {
  formatChangeTypeLabel,
  formatDeadlineType,
  formatEnforcement,
  shortTargetPath,
  splitDocPath,
  truncate,
  withDisambiguatedNames,
  formatCheckedAt,
} from './format.js';

/** 法令名が長いので画面表示用の略称を用意する（実データの言い換えであり、内容の創作ではない）。 */
const LAW_ABBREVIATIONS = {
  '403AC0000000076': '育児・介護休業法',
};

export function lawDisplayTitle(pipelineResult) {
  return LAW_ABBREVIATIONS[pipelineResult.law_id] ?? pipelineResult.law_title;
}

/** イベント（法令変更）のタイトル。変更が1件なら「◯◯法 第◯条の改正」、複数なら「◯◯法の改正」。 */
export function eventTitle(pipelineResult) {
  const lawTitle = lawDisplayTitle(pipelineResult);
  const changes = pipelineResult.changes;
  if (changes.length === 1) {
    const { change } = changes[0];
    return `${lawTitle} ${shortTargetPath(change.target_path)}の${formatChangeTypeLabel(change.change_type)}`;
  }
  return `${lawTitle}の改正（${changes.length}件の変更）`;
}

/** ホームの一文サマリー用の短い言い方（「◯◯法の改正」「◯◯法の条文削除」）。 */
export function eventShortDescription(pipelineResult) {
  const lawTitle = lawDisplayTitle(pipelineResult);
  if (pipelineResult.changes.length === 1) {
    const { change_type } = pipelineResult.changes[0].change;
    if (change_type === 'delete') return `${lawTitle}の条文削除`;
    if (change_type === 'effective_date_only') return `${lawTitle}の施行日変更`;
  }
  return `${lawTitle}の改正`;
}

/** 変更タブのラベル（「変更1: 変更の範囲の明示」のように短く）。 */
export function changeTabLabel(change, index) {
  return `変更${index + 1}: ${truncate(change.summary, 20)}`;
}

const STATUS_PRIORITY = { affected: 0, needs_review: 1, not_applicable: 2, none: 3 };

/**
 * 1文書ぶんの findings から、その文書としてのステータスを1つに決める。
 * 見逃し側に倒す（DESIGN.md 原則4）ため、優先度は 要対応 > 確認待ち > 対象外 > 問題なし。
 * @param {import('./types.js').Finding[]} findings
 * @returns {{status: import('./format.js').DocStatus, primary: import('./types.js').Finding, needsHumanReview: boolean}}
 */
function docStatusFromFindings(findings) {
  const needsHumanReview = findings.some((f) => f.needs_human_review);
  let status = 'none';
  if (findings.some((f) => f.impact === 'affected')) status = 'affected';
  else if (needsHumanReview) status = 'needs_review';
  else if (findings.every((f) => f.impact === 'not_applicable')) status = 'not_applicable';

  const primary =
    findings.find((f) => f.impact === 'affected') ??
    findings.find((f) => f.needs_human_review) ??
    findings[0];

  return { status, primary, needsHumanReview };
}

/** 要対応・確認待ちの一覧に出す短い一行。
 *
 * ここに出すのは「**この文書のどこが、どう古いか**」であって、法令が適用される理由ではない。
 * applicability_reason は「なぜこの法令が適用されるか」の法解釈なので、一覧には長すぎるうえ
 * どの文書でも似た文になり、一行として役に立たない。
 * 該当箇所（evidence_location）と、実際に問題になっている記述（evidence_quote）を出す。
 */
function issueLabel(finding, status) {
  if (status === 'needs_review' && finding.review_reason) return finding.review_reason;

  const where = finding.evidence_location?.trim();
  const what = finding.evidence_quote?.trim();
  if (where && what) return `${where} ・「${truncate(what, 46)}」`;
  if (what) return `「${truncate(what, 52)}」`;
  if (where) return `${where} の記載が改正後の内容と合っていません`;
  return truncate(finding.applicability_reason, 52);
}

/**
 * イベント全体（複数変更をまたぐ場合を含む）の findings を文書単位に集約する。
 * @param {import('./types.js').PipelineResult} pipelineResult
 */
function collectDocsAcrossEvent(pipelineResult) {
  /** @type {Map<string, Array<{finding: import('./types.js').Finding, changeId: string}>>} */
  const byDoc = new Map();
  for (const cr of pipelineResult.changes) {
    for (const finding of cr.findings) {
      const list = byDoc.get(finding.doc_id) ?? [];
      list.push({ finding, changeId: cr.change.change_id });
      byDoc.set(finding.doc_id, list);
    }
  }

  const docs = [];
  for (const [docId, entries] of byDoc) {
    const findings = entries.map((e) => e.finding);
    const { status, primary, needsHumanReview } = docStatusFromFindings(findings);
    const primaryEntry = entries.find((e) => e.finding === primary) ?? entries[0];
    const { folder, fileName } = splitDocPath(docId);
    docs.push({
      docId,
      folder,
      fileName,
      status,
      needsHumanReview,
      issueLabel: issueLabel(primary, status),
      deadlineTypeLabel: formatDeadlineType(primary.deadline_type),
      changeId: primaryEntry.changeId,
      chunkId: primary.chunk_id,
    });
  }

  docs.sort((a, b) => STATUS_PRIORITY[a.status] - STATUS_PRIORITY[b.status] || a.docId.localeCompare(b.docId));
  return withDisambiguatedNames(docs);
}

/**
 * ホーム画面用のイベントサマリー。
 * @param {import('./types.js').PipelineResult} pipelineResult
 * @param {{detectedAtLabel: string}} meta ダミーで補う検知時刻ラベル
 */
export function buildEventSummary(pipelineResult, meta) {
  const docs = collectDocsAcrossEvent(pipelineResult);
  const counts = { affected: 0, needsReview: 0, notApplicable: 0, none: 0 };
  for (const d of docs) {
    if (d.status === 'affected') counts.affected += 1;
    else if (d.status === 'needs_review') counts.needsReview += 1;
    else if (d.status === 'not_applicable') counts.notApplicable += 1;
    else counts.none += 1;
  }
  const actionDocs = docs.filter((d) => d.status === 'affected' || d.status === 'needs_review');
  const enforcement = formatEnforcement(pipelineResult.enforcement_date);

  return {
    eventId: pipelineResult.law_id,
    lawTitle: lawDisplayTitle(pipelineResult),
    title: eventTitle(pipelineResult),
    shortDescription: eventShortDescription(pipelineResult),
    changesCount: pipelineResult.changes.length,
    enforcement,
    // 検知時刻は PipelineResult.detected_at から作る（呼び出し側が渡す必要はない）
    detectedAtLabel: meta?.detectedAtLabel ?? formatCheckedAt(pipelineResult.detected_at),
    counts,
    actionDocs,
    raw: pipelineResult,
  };
}

/**
 * 変更タブ1件ぶんの「影響ドキュメント」ツリー（フォルダ単位グループ）。
 * 問題なし（green・要確認なし）はここには出さず、「詳細情報」の一覧にのみ出す
 * （DESIGN.md「影響あり=強調、影響なし=折りたたみ」）。
 * @param {import('./types.js').ChangeResult} changeResult
 */
export function buildDocTree(changeResult) {
  /** @type {Map<string, import('./types.js').Finding[]>} */
  const byDoc = new Map();
  for (const f of changeResult.findings) {
    const list = byDoc.get(f.doc_id) ?? [];
    list.push(f);
    byDoc.set(f.doc_id, list);
  }

  const docs = [];
  for (const [docId, findings] of byDoc) {
    const { status, primary } = docStatusFromFindings(findings);
    if (status === 'none') continue; // 問題なしは詳細情報の一覧に譲る
    const { folder, fileName } = splitDocPath(docId);
    docs.push({
      docId,
      folder: folder ?? '(直下)',
      fileName,
      status,
      chunkId: primary.chunk_id,
      reason: status === 'not_applicable' ? truncate(primary.applicability_reason, 40) : null,
    });
  }
  docs.sort((a, b) => a.folder.localeCompare(b.folder) || STATUS_PRIORITY[a.status] - STATUS_PRIORITY[b.status]);

  /** @type {Map<string, typeof docs>} */
  const byFolder = new Map();
  for (const d of docs) {
    const list = byFolder.get(d.folder) ?? [];
    list.push(d);
    byFolder.set(d.folder, list);
  }
  return [...byFolder.entries()].map(([folder, items]) => ({ folder, items }));
}

/**
 * 「詳細情報」内の確認したドキュメント一覧（Stage 3 で確認した全文書、問題なし含む）。
 * @param {import('./types.js').ChangeResult} changeResult
 */
export function buildReflist(changeResult) {
  /** @type {Map<string, import('./types.js').Finding[]>} */
  const byDoc = new Map();
  for (const f of changeResult.findings) {
    const list = byDoc.get(f.doc_id) ?? [];
    list.push(f);
    byDoc.set(f.doc_id, list);
  }
  const rows = [];
  for (const [docId, findings] of byDoc) {
    const { status } = docStatusFromFindings(findings);
    const { folder, fileName } = splitDocPath(docId);
    rows.push({ docId, folder, fileName, count: findings.length, status });
  }
  rows.sort((a, b) => STATUS_PRIORITY[a.status] - STATUS_PRIORITY[b.status] || a.docId.localeCompare(b.docId));

  const judgedDocCount = rows.length;
  const candidateDocCount = new Set(changeResult.candidates.map((c) => c.doc_id)).size;
  const skippedCount = Math.max(candidateDocCount - judgedDocCount, 0);

  return { rows: withDisambiguatedNames(rows), skippedCount };
}

/** ファネル可視化（3段階の絞り込み件数）＋実測コスト。「詳細情報」折りたたみ用。 */
export function buildFunnelView(pipelineResult, changeResult) {
  const { funnel } = changeResult;
  const affected = changeResult.findings.filter((f) => f.impact === 'affected').length;
  const notApplicable = changeResult.findings.filter((f) => f.impact === 'not_applicable').length;
  const none = changeResult.findings.filter((f) => f.impact === 'none').length;
  return {
    totalChunks: funnel.total_chunks,
    stage1Passed: funnel.stage1_passed,
    stage2Passed: funnel.stage2_passed,
    affected,
    notApplicable,
    none,
    costUsd: pipelineResult.cost?.cost_usd ?? 0,
    isWholeEventCost: pipelineResult.changes.length > 1,
  };
}

/**
 * 指摘詳細画面向けに、イベント内の特定チャンクの判定を1件引き当てる。
 * @param {import('./types.js').PipelineResult} pipelineResult
 * @param {string} changeId
 * @param {string} chunkId
 */
export function findFindingDetail(pipelineResult, changeId, chunkId) {
  const changeResult = pipelineResult.changes.find((cr) => cr.change.change_id === changeId);
  if (!changeResult) return null;
  const finding = changeResult.findings.find((f) => f.chunk_id === chunkId);
  if (!finding) return null;

  const otherFindingsForDoc = pipelineResult.changes
    .flatMap((cr) => cr.findings.map((f) => ({ finding: f, changeId: cr.change.change_id })))
    .filter(
      (entry) =>
        entry.finding.doc_id === finding.doc_id &&
        entry.finding.chunk_id !== finding.chunk_id &&
        (entry.finding.impact === 'affected' || entry.finding.needs_human_review),
    );

  return { change: changeResult.change, finding, otherFindingsForDoc };
}
