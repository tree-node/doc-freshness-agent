const TONE_CLASS = {
  shu: 'bg-[var(--shu-soft)] text-[var(--shu)]',
  amber: 'bg-[var(--amber-soft)] text-[var(--amber)]',
  green: 'bg-[var(--green-soft)] text-[var(--green)]',
  gray: 'bg-[#EFEEEA] text-[var(--sub)]',
};

/** ui-mock.html の .badge 相当。tone: 'shu' | 'amber' | 'green' | 'gray' */
export default function Badge({ tone = 'gray', children }) {
  return (
    <span className={`inline-block whitespace-nowrap rounded-full px-2.5 py-0.5 text-[11.5px] font-medium ${TONE_CLASS[tone]}`}>
      {children}
    </span>
  );
}
