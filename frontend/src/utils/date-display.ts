export function formatLocalizedPostDateTime(value: string | Date | null | undefined): string {
  if (!value) {
    return "";
  }

  const parsed = value instanceof Date ? value : new Date(value);
  const timestamp = parsed.getTime();
  if (Number.isNaN(timestamp)) {
    return "";
  }

  const nowMs = Date.now();
  const diffMs = Math.max(0, nowMs - timestamp);
  const oneDayMs = 24 * 60 * 60 * 1000;
  if (diffMs < oneDayMs) {
    const hoursAgo = Math.floor(diffMs / (60 * 60 * 1000));
    if (hoursAgo <= 0) {
      const minutesAgo = Math.max(1, Math.floor(diffMs / (60 * 1000)));
      return `${minutesAgo} minute${minutesAgo === 1 ? "" : "s"}`;
    }
    return `${hoursAgo} hour${hoursAgo === 1 ? "" : "s"}`;
  }

  return new Intl.DateTimeFormat(undefined, {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(parsed);
}
