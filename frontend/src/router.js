/**
 * URL と画面の対応。ルーティングライブラリは足さない（DESIGN.md「リッチな作り込みはしない」、
 * および他メンバーの環境で npm install をやり直させないため）。
 *
 *   /                                        ホーム
 *   /history                                 チェック履歴
 *   /audit                                   監査ログ
 *   /settings                                設定
 *   /events/{法令ID}?change={変更ID}          変更の詳細
 *   /events/{法令ID}/finding?change=&chunk=  指摘詳細
 *
 * チャンクIDは「株式会社サクラベース/休暇規程.docx#6」のようにスラッシュも記号も含むので、
 * **パスに置かずクエリに入れる**。パスに入れると階層と誤認されて壊れる。
 *
 * この2つの関数は React に依存しない（Node からそのまま検証できるようにするため）。
 */

const SIMPLE = ['history', 'audit', 'settings'];

/** 画面の状態から URL を作る。 */
export function toPath(nav) {
  if (!nav) return '/';

  if (SIMPLE.includes(nav.screen)) return `/${nav.screen}`;

  if (nav.screen === 'event' && nav.eventId) {
    const query = nav.changeId ? `?change=${encodeURIComponent(nav.changeId)}` : '';
    return `/events/${encodeURIComponent(nav.eventId)}${query}`;
  }

  if (nav.screen === 'finding' && nav.eventId) {
    const query = new URLSearchParams();
    if (nav.changeId) query.set('change', nav.changeId);
    if (nav.chunkId) query.set('chunk', nav.chunkId);
    return `/events/${encodeURIComponent(nav.eventId)}/finding?${query.toString()}`;
  }

  return '/';
}

/** URL から画面の状態を作る。知らない URL はホームに倒す（404で行き止まりにしない）。 */
export function fromPath(pathname = '/', search = '') {
  const query = new URLSearchParams(search);
  let parts;
  try {
    parts = pathname.split('/').filter(Boolean).map(decodeURIComponent);
  } catch {
    return { screen: 'home' }; // 壊れた文字列が入っていても落とさない
  }

  if (parts.length === 0) return { screen: 'home' };
  if (SIMPLE.includes(parts[0]) && parts.length === 1) return { screen: parts[0] };

  if (parts[0] === 'events' && parts[1]) {
    const eventId = parts[1];
    if (parts[2] === 'finding') {
      return {
        screen: 'finding',
        eventId,
        changeId: query.get('change') ?? undefined,
        chunkId: query.get('chunk') ?? undefined,
      };
    }
    if (parts.length === 2) {
      return { screen: 'event', eventId, changeId: query.get('change') ?? undefined };
    }
  }

  return { screen: 'home' };
}

/** いまのURLから画面の状態を読む。 */
export function currentRoute() {
  return fromPath(window.location.pathname, window.location.search);
}
