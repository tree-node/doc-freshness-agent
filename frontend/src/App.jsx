import { useCallback, useEffect, useState } from 'react';
import { currentRoute, toPath } from './router.js';
import Sidebar from './components/Sidebar.jsx';
import AuditLogScreen from './screens/AuditLogScreen.jsx';
import HistoryScreen from './screens/HistoryScreen.jsx';
import HomeScreen from './screens/HomeScreen.jsx';
import SettingsScreen from './screens/SettingsScreen.jsx';
import EventDetailScreen from './screens/EventDetailScreen.jsx';
import FindingDetailScreen from './screens/FindingDetailScreen.jsx';

// 画面の行き来は URL で表す（router.js）。ルーティングライブラリは足していない。
// URLが正になるので、再読み込みしても同じ画面に戻り、リンクを人に渡せる。
export default function App() {
  const [nav, setNav] = useState(currentRoute);

  useEffect(() => {
    window.scrollTo(0, 0);
  }, [nav]);

  // 「戻る」「進む」は URL を読み直す（履歴に積んだ状態ではなく URL を正とする）
  useEffect(() => {
    const onPop = () => setNav(currentRoute());
    window.addEventListener('popstate', onPop);
    return () => window.removeEventListener('popstate', onPop);
  }, []);

  const go = useCallback((next) => {
    const path = toPath(next);
    if (path !== window.location.pathname + window.location.search) {
      window.history.pushState(null, '', path);
    }
    setNav(next);
  }, []);

  const goHome = () => go({ screen: 'home' });
  const goTo = (screen) => go({ screen });
  const goEvent = (eventId, changeId) => go({ screen: 'event', eventId, changeId });
  const goFinding = (eventId, changeId, chunkId) => go({ screen: 'finding', eventId, changeId, chunkId });

  return (
    <div className="flex min-h-screen">
      <Sidebar screen={nav.screen} onNavigate={goTo} />
      <main className="min-w-0 flex-1 px-11 pb-18 pt-9" style={{ maxWidth: 980 }}>
        {nav.screen === 'home' && <HomeScreen onOpenEvent={goEvent} onOpenFinding={goFinding} />}
        {nav.screen === 'history' && <HistoryScreen onOpenEvent={goEvent} />}
        {nav.screen === 'audit' && <AuditLogScreen />}
        {nav.screen === 'settings' && <SettingsScreen />}
        {nav.screen === 'event' && (
          <EventDetailScreen eventId={nav.eventId} initialChangeId={nav.changeId} onHome={goHome} onOpenFinding={goFinding} />
        )}
        {nav.screen === 'finding' && (
          <FindingDetailScreen
            eventId={nav.eventId}
            changeId={nav.changeId}
            chunkId={nav.chunkId}
            onHome={goHome}
            onOpenEvent={goEvent}
          />
        )}
        <Attribution />
      </main>
    </div>
  );
}

/**
 * 法令データの出典明示。政府標準利用規約に基づき、READMEとアプリのフッターの両方に出す
 * （DESIGN.md 公開リポジトリの制約）。全画面で出したいので App に置く。
 */
function Attribution() {
  return (
    <footer className="mt-14 border-t border-[var(--line)] pt-4 text-[11.5px] leading-relaxed text-[var(--sub)]">
      法令データは{' '}
      <a href="https://laws.e-gov.go.jp/" target="_blank" rel="noreferrer" className="underline">
        e-Gov 法令検索
      </a>
      （デジタル庁）の法令API v2 より取得しています。利用は{' '}
      <a href="https://www.digital.go.jp/copyright-policy" target="_blank" rel="noreferrer" className="underline">
        政府標準利用規約
      </a>
      に基づきます。表示している社内文書はデモ用の架空の会社のものです。
    </footer>
  );
}
