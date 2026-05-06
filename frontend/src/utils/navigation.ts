import type { RouteLocationRaw, Router } from "vue-router";

export async function navigateBack(
  router: Router,
  fallbackRoute: RouteLocationRaw = { name: "feed" },
): Promise<void> {
  if (typeof window !== "undefined") {
    const historyState = window.history.state as { back?: unknown } | null;
    if (window.history.length > 1 && historyState?.back) {
      router.back();
      return;
    }
  }
  await router.push(fallbackRoute);
}
