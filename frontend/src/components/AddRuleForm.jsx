import { useState } from 'react';
import { registerRule, searchLaws } from '../api/index.js';

const LAW_TYPE_LABELS = {
  Act: '法律',
  CabinetOrder: '政令',
  MinisterialOrdinance: '省令',
  Rule: '規則',
};

/**
 * 正本（法令）を登録するフォーム。
 *
 * 法令IDを覚えている人はいないので、まず名前で探して選ぶ。
 * 名前は部分一致なので同名の別法令が混ざる（育介法を探すと船員向けの施行規則も出る）。
 * 法令の種類と法令番号を併記して、選び間違えないようにする。
 */
export default function AddRuleForm({ onRegistered }) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState('');
  const [candidates, setCandidates] = useState(null);
  const [selected, setSelected] = useState(null);
  const [asof, setAsof] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  async function search(event) {
    event.preventDefault();
    if (!query.trim()) return;
    setBusy(true);
    setError(null);
    setCandidates(null);
    setSelected(null);
    try {
      setCandidates(await searchLaws(query.trim()));
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }

  async function register() {
    setBusy(true);
    setError(null);
    try {
      await registerRule(selected.law_id, asof);
      setOpen(false);
      setQuery('');
      setCandidates(null);
      setSelected(null);
      setAsof('');
      onRegistered();
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }

  if (!open) {
    return (
      <button
        type="button"
        onClick={() => setOpen(true)}
        className="w-full border-t border-dashed border-[var(--line)] px-5 py-3.5 text-left text-[13px] text-[var(--green)]"
      >
        ＋ ルールを追加
      </button>
    );
  }

  return (
    <div className="border-t border-dashed border-[var(--line)] bg-[#FAFAF8] px-5 py-4.5">
      <form onSubmit={search} className="flex flex-wrap gap-2">
        <input
          type="text"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="法令の名前で探す（例: 労働安全衛生法）"
          className="min-w-0 flex-1 rounded-[9px] border border-[var(--line)] bg-[var(--card)] px-3.5 py-2 text-[13.5px]"
        />
        <button
          type="submit"
          disabled={busy || !query.trim()}
          className="rounded-[9px] border border-[var(--line)] bg-[var(--card)] px-4 py-2 text-[13px] disabled:opacity-40"
        >
          {busy ? '探しています…' : '探す'}
        </button>
        <button
          type="button"
          onClick={() => setOpen(false)}
          className="rounded-[9px] px-3 py-2 text-[13px] text-[var(--sub)]"
        >
          やめる
        </button>
      </form>

      {error && <p className="mt-2.5 text-[12.5px] text-[var(--shu)]">{error}</p>}

      {candidates && candidates.length === 0 && (
        <p className="mt-2.5 text-[12.5px] text-[var(--sub)]">
          見つかりませんでした。正式名称の一部で探してみてください。
        </p>
      )}

      {candidates && candidates.length > 0 && (
        <div className="mt-3 overflow-hidden rounded-[10px] border border-[var(--line)] bg-[var(--card)]">
          {candidates.map((law) => (
            <button
              key={law.law_id}
              type="button"
              disabled={law.registered}
              onClick={() => setSelected(law)}
              className={`block w-full border-b border-[var(--line)] px-4 py-2.5 text-left text-[13px] last:border-b-0 disabled:opacity-40 ${
                selected?.law_id === law.law_id ? 'bg-[var(--green-soft)]' : ''
              }`}
            >
              <b>{law.law_title}</b>
              <span className="block font-mono text-[11px] text-[var(--sub)]">
                {LAW_TYPE_LABELS[law.law_type] ?? law.law_type} ・ {law.law_num}
                {law.registered ? ' ・ 登録済み' : ''}
              </span>
            </button>
          ))}
        </div>
      )}

      {selected && (
        <div className="mt-3 rounded-[10px] border border-[var(--line)] bg-[var(--card)] px-4 py-3.5">
          <p className="mb-2 text-[13px]">
            <b>{selected.law_title}</b> を見張ります
          </p>
          <label className="block text-[12.5px] text-[var(--sub)]">
            いつ時点の条文を出発点にするか
            <input
              type="date"
              value={asof}
              onChange={(e) => setAsof(e.target.value)}
              className="ml-2 rounded-[7px] border border-[var(--line)] px-2.5 py-1 text-[13px] text-[var(--ink)]"
            />
          </label>
          <p className="mt-1.5 text-[11.5px] leading-relaxed text-[var(--sub)]">
            空のままなら今の条文が出発点になり、これ以降の改正だけを検知します。
            過去の日付を入れると、その時点から今までの改正をまとめて検知します。
          </p>
          <button
            type="button"
            disabled={busy}
            onClick={register}
            className="mt-2.5 rounded-[9px] border border-[var(--green)] bg-[var(--green)] px-4.5 py-2 text-[13.5px] font-medium text-white disabled:opacity-40"
          >
            {busy ? '条文を取得しています…' : 'このルールを追加する'}
          </button>
        </div>
      )}
    </div>
  );
}
