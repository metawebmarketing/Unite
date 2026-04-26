import { fetchActiveTheme } from "./api/themes";

export const THEME_CACHE_KEY = "unite:active-theme-tokens";

export function applyThemeTokens(tokens: Record<string, unknown>): void {
  const root = document.documentElement;
  const colors = (tokens.colors as Record<string, string> | undefined) ?? {};
  const spacing = (tokens.spacing as Record<string, number> | undefined) ?? {};
  const radius = (tokens.radius as Record<string, number> | undefined) ?? {};
  const typography = (tokens.typography as Record<string, number> | undefined) ?? {};

  if (colors.background) {
    root.style.setProperty("--theme-background", colors.background);
  }
  if (colors.surface) {
    root.style.setProperty("--theme-surface", colors.surface);
  }
  if (colors.textPrimary) {
    root.style.setProperty("--theme-text-primary", colors.textPrimary);
  }
  if (colors.border) {
    root.style.setProperty("--theme-border", colors.border);
  }
  if (spacing.sm) {
    root.style.setProperty("--theme-space-sm", `${spacing.sm}px`);
  }
  if (spacing.md) {
    root.style.setProperty("--theme-space-md", `${spacing.md}px`);
  }
  if (radius.md) {
    root.style.setProperty("--theme-radius-md", `${radius.md}px`);
  }
  if (typography.base) {
    root.style.setProperty("--theme-font-size-base", `${typography.base}px`);
  }
}

export function cacheThemeTokens(tokens: Record<string, unknown>): void {
  try {
    localStorage.setItem(THEME_CACHE_KEY, JSON.stringify(tokens));
  } catch {
    // Ignore storage quota/privacy mode issues.
  }
}

function readCachedThemeTokens(): Record<string, unknown> | null {
  try {
    const raw = localStorage.getItem(THEME_CACHE_KEY);
    if (!raw) {
      return null;
    }
    const parsed = JSON.parse(raw) as Record<string, unknown>;
    return parsed && typeof parsed === "object" ? parsed : null;
  } catch {
    return null;
  }
}

export async function loadThemeOnStartup(): Promise<void> {
  const cachedTokens = readCachedThemeTokens();
  if (cachedTokens) {
    applyThemeTokens(cachedTokens);
  }
  const activeTheme = await fetchActiveTheme();
  if (!activeTheme?.tokens) {
    return;
  }
  applyThemeTokens(activeTheme.tokens);
  cacheThemeTokens(activeTheme.tokens);
}
