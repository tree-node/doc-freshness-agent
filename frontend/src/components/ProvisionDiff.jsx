/**
 * 改正前後の条文を、共通の接頭辞・接尾辞をくくり出して差分表示する簡易diff。
 * fixture には単語単位の差分情報が無いため（before_excerpt / after_excerpt が全文のみ）、
 * 文字列の共通の前後だけを機械的に見つけて中間部分を強調する（ライブラリ追加なしの最小実装）。
 */
function diffParts(before, after) {
  const b = before ?? '';
  const a = after ?? '';
  const minLen = Math.min(b.length, a.length);
  let start = 0;
  while (start < minLen && b[start] === a[start]) start++;
  let endB = b.length;
  let endA = a.length;
  while (endB > start && endA > start && b[endB - 1] === a[endA - 1]) {
    endB--;
    endA--;
  }
  return { prefix: b.slice(0, start), beforeMid: b.slice(start, endB), afterMid: a.slice(start, endA), suffix: b.slice(endB) };
}

export default function ProvisionDiff({ before, after }) {
  if (before == null) {
    return (
      <div className="grid grid-cols-1 overflow-hidden rounded-xl border border-[var(--line)] bg-[var(--card)] md:grid-cols-2">
        <div className="border-b border-[var(--line)] bg-[#FAF7F4] px-5 py-4 text-[13px] md:border-b-0 md:border-r">
          <div className="mb-2 font-mono text-[10.5px] tracking-wider text-[var(--sub)]">改正前</div>
          <span className="italic text-[var(--sub)]">（この規定はありませんでした）</span>
        </div>
        <div className="px-5 py-4 text-[13px]">
          <div className="mb-2 font-mono text-[10.5px] tracking-wider text-[var(--sub)]">改正後</div>
          <span className="font-bold text-[var(--green)]">{after}</span>
        </div>
      </div>
    );
  }

  if (after == null) {
    return (
      <div className="grid grid-cols-1 overflow-hidden rounded-xl border border-[var(--line)] bg-[var(--card)] md:grid-cols-2">
        <div className="border-b border-[var(--line)] bg-[#FAF7F4] px-5 py-4 text-[13px] md:border-b-0 md:border-r">
          <div className="mb-2 font-mono text-[10.5px] tracking-wider text-[var(--sub)]">改正前</div>
          {before}
        </div>
        <div className="px-5 py-4 text-[13px]">
          <div className="mb-2 font-mono text-[10.5px] tracking-wider text-[var(--sub)]">改正後</div>
          <span className="italic text-[var(--sub)]">（削除されました）</span>
        </div>
      </div>
    );
  }

  const { prefix, beforeMid, afterMid, suffix } = diffParts(before, after);

  return (
    <div className="grid grid-cols-1 overflow-hidden rounded-xl border border-[var(--line)] bg-[var(--card)] md:grid-cols-2">
      <div className="border-b border-[var(--line)] bg-[#FAF7F4] px-5 py-4 text-[13px] leading-relaxed md:border-b-0 md:border-r">
        <div className="mb-2 font-mono text-[10.5px] tracking-wider text-[var(--sub)]">改正前</div>
        {prefix}
        {beforeMid && <del className="text-[var(--shu)] decoration-[var(--shu)]">{beforeMid}</del>}
        {suffix}
      </div>
      <div className="px-5 py-4 text-[13px] leading-relaxed">
        <div className="mb-2 font-mono text-[10.5px] tracking-wider text-[var(--sub)]">改正後</div>
        {prefix}
        {afterMid && <ins className="font-bold text-[var(--green)] no-underline">{afterMid}</ins>}
        {suffix}
      </div>
    </div>
  );
}
