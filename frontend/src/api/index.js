/**
 * データ層の入口。コンポーネントはこのファイルからのみ import する
 * （fixture / derive の実装詳細を直接 import しない）。
 */
export {
  downloadRevisedDocument,
  fetchEvent,
  fetchEvents,
  fetchFinding,
  fetchHistory,
  fetchRules,
  fetchStatuses,
  saveStatus,
} from './client.js';
export { buildDocTree, buildReflist, buildFunnelView, changeTabLabel } from './derive.js';
export * from './format.js';
