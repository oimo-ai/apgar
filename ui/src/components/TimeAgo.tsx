import { formatRelative, formatUtc } from "@/lib/format";

export function TimeAgo({ iso }: { iso: string | null | undefined }) {
  if (!iso) {
    return <span>n/a</span>;
  }
  return (
    <time dateTime={iso} title={formatUtc(iso)}>
      {formatRelative(iso)}
    </time>
  );
}
