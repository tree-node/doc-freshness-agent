/**
 * ロゴ（案6「断層」）。
 *
 * 条文の行が途中から横にズレている——改正とは足元が動くこと、という意味。
 * 真ん中の朱が、ズレて古くなった一行。
 *
 * 小さいサイズでは行数を減らし、ズレを大きくする。3本のまま縮めると
 * 断層が1px程度になり、ただの横棒に見えてしまうため。
 */

const SHU = 'var(--shu, #B0482B)';

/** @param {{size?: number, title?: string}} props */
export default function Logo({ size = 28, title }) {
  const compact = size < 28;
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 64 64"
      role={title ? 'img' : 'presentation'}
      aria-label={title}
      aria-hidden={title ? undefined : 'true'}
      style={{ display: 'block', flex: 'none' }}
    >
      {compact ? <Compact /> : <Full />}
    </svg>
  );
}

/** 48px 以上向け。左3行・右3行が下へズレる */
function Full() {
  return (
    <>
      <rect x="6" y="12" width="24" height="6" rx="3" fill="currentColor" opacity=".32" />
      <rect x="6" y="28" width="24" height="6" rx="3" fill="currentColor" opacity=".32" />
      <rect x="6" y="44" width="24" height="6" rx="3" fill="currentColor" opacity=".32" />
      <rect x="34" y="19" width="24" height="6" rx="3" fill="currentColor" opacity=".32" />
      <rect x="34" y="35" width="24" height="6" rx="3" style={{ fill: SHU }} />
      <rect x="34" y="51" width="24" height="6" rx="3" fill="currentColor" opacity=".32" />
      <rect x="31" y="6" width="2" height="52" style={{ fill: SHU }} opacity=".55" />
    </>
  );
}

/** 16〜24px 向け。行を2本に減らし、ズレと太さを上げる */
function Compact() {
  return (
    <>
      <rect x="4" y="14" width="26" height="10" rx="5" fill="currentColor" opacity=".38" />
      <rect x="4" y="40" width="26" height="10" rx="5" fill="currentColor" opacity=".38" />
      <rect x="34" y="26" width="26" height="10" rx="5" style={{ fill: SHU }} />
      <rect x="34" y="52" width="26" height="10" rx="5" fill="currentColor" opacity=".38" />
      <rect x="31" y="8" width="3" height="52" style={{ fill: SHU }} opacity=".6" />
    </>
  );
}
