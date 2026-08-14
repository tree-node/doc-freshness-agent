/** ui-mock.html nav.side の移植。ホーム以外の画面（チェック履歴・監査ログ・設定）は未実装のため非活性表示のまま。 */
export default function Sidebar({ screen, onHome }) {
  return (
    <nav className="w-[196px] shrink-0 border-r border-[var(--line)] bg-[var(--card)] px-3.5 py-6.5">
      <div className="px-2.5 pb-5 text-[15px] font-bold tracking-wide">
        鮮度監視エージェント
        <small className="mt-0.5 block font-mono text-[10.5px] font-normal tracking-wider text-[var(--sub)]">
          DOC FRESHNESS MONITOR
        </small>
      </div>
      <button
        type="button"
        onClick={onHome}
        className={`mb-0.5 block w-full rounded-lg px-3 py-2 text-left text-[13.5px] ${
          screen === 'home' ? 'bg-[var(--green-soft)] font-bold text-[var(--green)]' : 'text-[var(--ink)]'
        }`}
      >
        ホーム
      </button>
      <span className="mb-0.5 block cursor-default rounded-lg px-3 py-2 text-[13.5px] text-[var(--sub)]">チェック履歴</span>
      <span className="mb-0.5 block cursor-default rounded-lg px-3 py-2 text-[13.5px] text-[var(--sub)]">監査ログ</span>
      <span className="mb-0.5 block cursor-default rounded-lg px-3 py-2 text-[13.5px] text-[var(--sub)]">設定</span>
    </nav>
  );
}
