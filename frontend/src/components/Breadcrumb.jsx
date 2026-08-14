/**
 * ui-mock.html .crumb の移植。
 * @param {{label: string, onClick?: () => void, current?: boolean}[]} parts
 * @param {React.ReactNode} [extra] 末尾に添える補助リンク（例: 「この文書へのほかの指摘」）
 */
export default function Breadcrumb({ parts, extra }) {
  return (
    <div className="mb-4.5 text-[12.5px] text-[var(--sub)]">
      {parts.map((part, i) => (
        <span key={i}>
          {i > 0 && <span> ／ </span>}
          {part.onClick && !part.current ? (
            <button type="button" onClick={part.onClick} className="text-[var(--sub)] hover:underline">
              {part.label}
            </button>
          ) : (
            <b className="font-medium text-[var(--ink)]">{part.label}</b>
          )}
        </span>
      ))}
      {extra && <span className="ml-2.5 text-[12px]">{extra}</span>}
    </div>
  );
}
