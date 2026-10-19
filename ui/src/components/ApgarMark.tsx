export function ApgarMark() {
  return (
    <svg className="apgar-mark" viewBox="8 8 48 48" aria-hidden="true">
      <path
        d="M30 8A20 20 0 0 0 30 48Z"
        fill="var(--brand-accent, var(--accent))"
        fillOpacity={0.4}
      />
      <path d="M34 16A20 20 0 0 1 34 56Z" fill="var(--brand-accent, var(--accent))" />
    </svg>
  );
}
