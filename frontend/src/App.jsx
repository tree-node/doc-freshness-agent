import { useEffect, useState } from 'react'

// 雛形。画面（ホーム → 変更の詳細 → 指摘詳細）は DESIGN.md の実装順で足していく。
// ここではバックエンド疎通と Tailwind が効いていることだけを確認する。
export default function App() {
  const [health, setHealth] = useState(null)
  const [error, setError] = useState(null)

  useEffect(() => {
    fetch('/api/health')
      .then((res) => {
        if (!res.ok) throw new Error(`HTTP ${res.status}`)
        return res.json()
      })
      .then(setHealth)
      .catch((e) => setError(e.message))
  }, [])

  return (
    <div className="min-h-screen bg-slate-50 text-slate-900">
      <header className="border-b border-slate-200 bg-white">
        <div className="mx-auto max-w-4xl px-6 py-4">
          <h1 className="text-lg font-semibold">ドキュメント鮮度監視エージェント</h1>
        </div>
      </header>

      <main className="mx-auto max-w-4xl px-6 py-10">
        <section className="rounded-lg border border-slate-200 bg-white p-6">
          <h2 className="mb-3 text-sm font-medium text-slate-500">バックエンド接続</h2>
          {error && <p className="text-sm text-red-600">接続できません: {error}</p>}
          {!error && !health && <p className="text-sm text-slate-500">確認中…</p>}
          {health && (
            <p className="text-sm">
              接続できました（データベース:{' '}
              {health.db.writable ? '書き込み可' : '書き込み不可'}）
            </p>
          )}
        </section>
      </main>

      <footer className="mx-auto max-w-4xl px-6 pb-10 text-xs text-slate-500">
        {health?.attribution ??
          '法令データは e-Gov 法令検索（デジタル庁）法令API v2 より取得しています。'}
      </footer>
    </div>
  )
}
