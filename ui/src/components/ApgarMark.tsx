export function ApgarMark() {
  return (
    <svg className="apgar-mark" viewBox="0 0 32 32" aria-hidden="true">
      <rect width="32" height="32" rx="8" fill="var(--brand-accent, var(--accent))" />
      <rect x="6.5" y="16" width="3.25" height="9" rx="1.1" fill="var(--accent-text)" />
      <rect x="11.75" y="12" width="3.25" height="13" rx="1.1" fill="var(--accent-text)" />
      <rect x="17" y="7.5" width="3.25" height="17.5" rx="1.1" fill="var(--accent-text)" />
      <rect x="22.25" y="13" width="3.25" height="12" rx="1.1" fill="var(--accent-text)" />
    </svg>
  );
}
