const URL_CANDIDATE_REGEX = /(https?:\/\/[^\s<>"']+)/gi;

function trimTrailingPunctuation(value: string): string {
  return value.replace(/[),.;!?]+$/g, "");
}

export function extractFirstHttpUrl(value: string): string {
  const input = String(value || "").trim();
  if (!input) {
    return "";
  }
  const candidates = input.match(URL_CANDIDATE_REGEX) || [];
  for (const rawCandidate of candidates) {
    const candidate = trimTrailingPunctuation(rawCandidate);
    try {
      const parsed = new URL(candidate);
      if (parsed.protocol === "http:" || parsed.protocol === "https:") {
        return parsed.toString();
      }
    } catch {
      // Ignore invalid candidates and continue.
    }
  }
  return "";
}
