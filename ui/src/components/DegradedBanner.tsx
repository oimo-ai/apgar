import { useStatus } from "@/api/queries";

export function DegradedBanner() {
  const status = useStatus();
  const show = status.isError || (status.data != null && status.data.storage !== "ok");
  if (!show) {
    return null;
  }
  return (
    <div data-testid="degraded-banner" role="status" className="border-b border-l-4 border-b-border border-l-fail bg-fail-bg px-4 py-2.5 text-sm font-medium text-fail">
      Storage unavailable; data may be stale
    </div>
  );
}
