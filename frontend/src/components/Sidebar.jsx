import Logo from './Logo.jsx';

const ITEMS = [
  { key: 'home', label: 'ホーム' },
  { key: 'history', label: 'チェック履歴' },
  { key: 'audit', label: '監査ログ' },
  { key: 'settings', label: '設定' },
];

/** ui-mock.html nav.side の移植。 */
export default function Sidebar({ screen, onNavigate }) {
  // 変更の詳細・指摘詳細を見ている間もホームを選択状態にしておく（どこにいるか見失わないように）
  const active = ['event', 'finding'].includes(screen) ? 'home' : screen;

  // 幅252px は「ロゴ30 + 余白 + 鮮度監視エージェント（15px×10字）」が折り返さない実測値。
  // 名称を変えるときは一緒に見直すこと（ui-mock.html の 196px から広げてある）
  return (
    <nav className="w-[252px] shrink-0 border-r border-[var(--line)] bg-[var(--card)] px-3.5 py-6.5">
      <div className="flex items-center gap-2.5 px-2.5 pb-5">
        <Logo size={30} title="鮮度監視エージェント" />
        <div className="text-[15px] font-bold tracking-wide whitespace-nowrap">
          鮮度監視エージェント
          <small className="mt-0.5 block font-mono text-[10.5px] font-normal tracking-wider text-[var(--sub)]">
            DOC FRESHNESS MONITOR
          </small>
        </div>
      </div>
      {ITEMS.map((item) => (
        <button
          key={item.key}
          type="button"
          onClick={() => onNavigate(item.key)}
          className={`mb-0.5 block w-full rounded-lg px-3 py-2 text-left text-[13.5px] ${
            active === item.key
              ? 'bg-[var(--green-soft)] font-bold text-[var(--green)]'
              : 'text-[var(--ink)]'
          }`}
        >
          {item.label}
        </button>
      ))}
    </nav>
  );
}
