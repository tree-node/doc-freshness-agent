/**
 * 型定義（JSDoc）。
 *
 * バックエンドの `/api/health` 以外のエンドポイントはまだ無いため、このアプリは
 * `app/pipeline/models.py` の `to_dict()` がそのまま出力するJSON構造の fixture
 * （src/mock/*.json）を読む。フィールド名・粒度はすべてそちらに合わせてあり、
 * ここで勝手にフィールドを増やしていない。
 *
 * 本物のAPIに差し替えるときは `src/api/client.js` の3関数の中身だけを
 * `fetch('/api/...')` に置き換えればよい（コンポーネント側はこの型のまま）。
 */

/**
 * @typedef {'amend'|'add'|'delete'|'effective_date_only'} ChangeType
 * @typedef {'affected'|'none'|'not_applicable'} Impact
 * @typedef {'applicable'|'not_applicable'|'unclear'} Applicability
 * @typedef {'immediate'|'on_renewal'|'none'} DeadlineType
 */

/**
 * Stage 0 の出力 = 変更単位（app/pipeline/models.py Change）。
 * @typedef {Object} Change
 * @property {string} change_id
 * @property {ChangeType} change_type
 * @property {string} target_path
 * @property {string|null} before_excerpt
 * @property {string|null} after_excerpt
 * @property {string} summary
 * @property {string[]} affected_domains
 * @property {string} semantic_query
 * @property {string[]} exact_terms
 * @property {string|null} effective_date
 * @property {string|null} effective_date_note
 * @property {boolean} transitional
 * @property {number} confidence
 * @property {boolean} needs_human_review
 * @property {string|null} note
 */

/**
 * Stage 1 の通過候補（app/pipeline/models.py Candidate）。
 * @typedef {Object} Candidate
 * @property {string} chunk_id
 * @property {string} doc_id
 * @property {string} label
 * @property {number} rrf_score
 * @property {string} reason
 * @property {boolean} linked
 */

/**
 * 絞り込み過程の可視化（app/pipeline/models.py FunnelStats）。
 * @typedef {Object} FunnelStats
 * @property {number} total_chunks
 * @property {number} stage1_passed
 * @property {number} stage2_passed
 * @property {number} stage3_judged
 * @property {number} affected
 * @property {number} not_affected
 * @property {number} stage1_excluded
 */

/**
 * Stage 3 の判定結果（app/pipeline/models.py Finding）。
 * @typedef {Object} Finding
 * @property {string} chunk_id
 * @property {string} doc_id
 * @property {string} label
 * @property {string} document_nature
 * @property {Applicability} law_applicability
 * @property {string} applicability_reason
 * @property {Impact} impact
 * @property {DeadlineType} deadline_type
 * @property {string} evidence_quote
 * @property {string} evidence_location
 * @property {{before: string, after: string}|null} fix_proposal
 * @property {number} confidence
 * @property {boolean} needs_human_review
 * @property {string|null} review_reason
 * @property {boolean} evidence_verified
 * @property {string|null} model
 */

/**
 * 変更1件ぶんの結果（app/pipeline/models.py ChangeResult）。
 * @typedef {Object} ChangeResult
 * @property {Change} change
 * @property {Candidate[]} candidates
 * @property {Object<string, number>} stage2_scores
 * @property {Finding[]} findings
 * @property {FunnelStats} funnel
 */

/**
 * 起票（ファイルインスタンス単位、app/pipeline/models.py Alert）。
 * @typedef {Object} Alert
 * @property {string} doc_id
 * @property {string} location
 * @property {string} chunk_id
 * @property {string} change_id
 * @property {Finding} finding
 */

/**
 * イベント1件ぶんの結果（app/pipeline/models.py PipelineResult）。
 * @typedef {Object} PipelineResult
 * @property {string} law_id
 * @property {string} law_title
 * @property {string} from_revision
 * @property {string} to_revision
 * @property {string|null} enforcement_date
 * @property {ChangeResult[]} changes
 * @property {Alert[]} alerts
 * @property {Object} cost
 */

export {};
