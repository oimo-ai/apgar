const MINUS = "\u2212";

export function formatCount(value: number): string {
  return Math.round(value).toLocaleString("en-US");
}

function signed(body: string, value: number): string {
  if (value > 0) {
    return `+${body}`;
  }
  if (value < 0) {
    return `${MINUS}${body}`;
  }
  return body;
}

export function formatRate(value: number | null | undefined): string {
  if (value == null || Number.isNaN(value)) {
    return "n/a";
  }
  const pct = value * 100;
  const digits = pct !== 0 && Math.abs(pct) < 1 ? 2 : 1;
  const body = Math.abs(pct).toFixed(digits);
  return `${pct < 0 ? MINUS : ""}${body}%`;
}

export function formatPp(delta: number | null | undefined): string {
  if (delta == null || Number.isNaN(delta)) {
    return "n/a";
  }
  const pct = delta * 100;
  return `${signed(Math.abs(pct).toFixed(1), pct)} pp`;
}

export function formatRel(delta: number | null | undefined): string {
  if (delta == null || Number.isNaN(delta)) {
    return "n/a";
  }
  const pct = delta * 100;
  return `${signed(Math.abs(pct).toFixed(0), pct)}%`;
}

function points(tolerance: number): string {
  const n = tolerance * 100;
  if (Math.abs(n - Math.round(n)) < 1e-6) {
    return Math.round(n).toString();
  }
  return n.toFixed(1);
}

export function formatTolerance(
  mode: "abs" | "rel",
  direction: "up" | "down" | "both",
  tolerance: number,
): string {
  const n = points(tolerance);
  if (direction === "both") {
    return mode === "abs" ? `±${n} pp` : `±${n}%`;
  }
  if (direction === "down") {
    return mode === "abs" ? `${MINUS}${n} pp` : `${MINUS}${n}%`;
  }
  return mode === "abs" ? `+${n} pp` : `+${n}%`;
}

export function formatCi(
  interval: [number, number] | null | undefined,
  mode: "abs" | "rel",
): string {
  if (!interval) {
    return "n/a";
  }
  if (mode === "rel") {
    return `${formatRel(interval[0])} to ${formatRel(interval[1])}`;
  }
  const left = formatPp(interval[0]).replace(/ pp$/, "");
  const right = formatPp(interval[1]).replace(/ pp$/, "");
  return `${left} to ${right} pp`;
}

export function formatDelta(
  delta: number | null | undefined,
  mode: "abs" | "rel",
): string {
  return mode === "abs" ? formatPp(delta) : formatRel(delta);
}

export function formatValue(value: number | null | undefined, unit: string): string {
  if (value == null || Number.isNaN(value)) {
    return "n/a";
  }
  if (unit === "rate") {
    return formatRate(value);
  }
  if (unit === "count") {
    return value.toFixed(2);
  }
  if (unit === "tokens" || unit === "chars") {
    return formatCount(value);
  }
  if (unit === "ms") {
    if (value > 10_000) {
      return `${(value / 1000).toFixed(1)} s`;
    }
    return `${Math.round(value).toLocaleString("en-US")} ms`;
  }
  if (unit === "usd") {
    return `$${value.toFixed(4)}`;
  }
  return String(value);
}

export function formatUtc(iso: string | null | undefined): string {
  if (!iso) {
    return "";
  }
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) {
    return iso;
  }
  const y = date.getUTCFullYear();
  const m = String(date.getUTCMonth() + 1).padStart(2, "0");
  const d = String(date.getUTCDate()).padStart(2, "0");
  const hh = String(date.getUTCHours()).padStart(2, "0");
  const mm = String(date.getUTCMinutes()).padStart(2, "0");
  return `${y}-${m}-${d} ${hh}:${mm} UTC`;
}

export function formatRelative(iso: string | null | undefined, now = Date.now()): string {
  if (!iso) {
    return "";
  }
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) {
    return "";
  }
  const seconds = Math.round((now - then) / 1000);
  const abs = Math.abs(seconds);
  const suffix = seconds >= 0 ? "ago" : "from now";
  if (abs < 60) {
    return "just now";
  }
  if (abs < 3600) {
    return `${Math.floor(abs / 60)}m ${suffix}`;
  }
  if (abs < 86400) {
    return `${Math.floor(abs / 3600)}h ${suffix}`;
  }
  if (abs < 7 * 86400) {
    return `${Math.floor(abs / 86400)}d ${suffix}`;
  }
  return formatUtcDate(iso, now);
}

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

export function formatUtcDate(iso: string, now = Date.now()): string {
  const date = new Date(iso);
  const day = `${MONTHS[date.getUTCMonth()]} ${date.getUTCDate()}`;
  return date.getUTCFullYear() === new Date(now).getUTCFullYear() ? day : `${day}, ${date.getUTCFullYear()}`;
}

export function formatUtcShort(iso: string | null | undefined, now = Date.now()): string {
  if (!iso) {
    return "n/a";
  }
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) {
    return iso;
  }
  const hh = String(date.getUTCHours()).padStart(2, "0");
  const mm = String(date.getUTCMinutes()).padStart(2, "0");
  return `${formatUtcDate(iso, now)}, ${hh}:${mm}`;
}

export function releaseHref(agent: string, release: string): string {
  return `/agents/${encodeURIComponent(agent)}/releases/${encodeURIComponent(release)}`;
}
