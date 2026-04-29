import type { AxiosRequestConfig } from "axios";
import { createPinia } from "pinia";
import { createApp } from "vue";

import App from "./App.vue";
import GlobalErrorModal from "./components/GlobalErrorModal.vue";
import { apiClient } from "./api/client";
import { fetchInstallStatus } from "./api/install";
import router from "./router";
import { useAuthStore } from "./stores/auth";
import { useErrorModalStore } from "./stores/error-modal";
import { useRouteLoadingStore } from "./stores/route-loading";
import { loadThemeOnStartup } from "./theme";
import "./style.css";

void loadThemeOnStartup();

const pinia = createPinia();
const app = createApp(App);
app.component("GlobalErrorModal", GlobalErrorModal);
app.use(pinia);
const authStore = useAuthStore(pinia);
const errorModalStore = useErrorModalStore(pinia);
const routeLoadingStore = useRouteLoadingStore(pinia);
authStore.hydrateFromStorage();
if (authStore.refreshToken) {
  void authStore.refreshAccessToken().catch(() => null);
}
let installKnown: boolean | null = null;
const cachedInstallState = sessionStorage.getItem("unite_install_known");
if (cachedInstallState === "true") {
  installKnown = true;
}
if (cachedInstallState === "false") {
  installKnown = false;
}

let redirectingUnauthorized = false;
let refreshAccessPromise: Promise<string | null> | null = null;

async function refreshAccessTokenIfPossible(): Promise<string | null> {
  if (!authStore.refreshToken) {
    return null;
  }
  if (!refreshAccessPromise) {
    refreshAccessPromise = authStore
      .refreshAccessToken()
      .then((token) => token || null)
      .catch(() => null)
      .finally(() => {
        refreshAccessPromise = null;
      });
  }
  return refreshAccessPromise;
}

function shouldAttemptRefresh(
  statusCode: number,
  hasAuthHeader: boolean,
  requestUrl: string,
  requestConfig: Record<string, unknown>,
) {
  if (statusCode !== 401 || !hasAuthHeader) {
    return false;
  }
  if (requestUrl.includes("/auth/token/refresh")) {
    return false;
  }
  return !Boolean(requestConfig._retryAfterRefresh);
}

function buildRetryConfig(requestConfig: Record<string, unknown>, nextToken: string): AxiosRequestConfig {
  const retryConfig: AxiosRequestConfig = { ...(requestConfig as AxiosRequestConfig) };
  const retryHeaders = { ...((retryConfig.headers as Record<string, string>) || {}) };
  retryHeaders.Authorization = `Bearer ${nextToken}`;
  retryConfig.headers = retryHeaders;
  (retryConfig as Record<string, unknown>)._retryAfterRefresh = true;
  return retryConfig;
}

apiClient.interceptors.response.use(
  (response) => response,
  async (error) => {
    const requestConfig = (error?.config || {}) as Record<string, unknown>;
    const statusCode = Number(error?.response?.status || 0);
    const requestHeaders = (requestConfig.headers || {}) as Record<string, unknown>;
    const requestUrl = String(requestConfig.url || "");
    const hasAuthHeader =
      typeof requestHeaders.Authorization === "string" ||
      typeof requestHeaders.authorization === "string";

    if (shouldAttemptRefresh(statusCode, hasAuthHeader, requestUrl, requestConfig)) {
      const refreshedToken = await refreshAccessTokenIfPossible();
      if (refreshedToken) {
        const retryConfig = buildRetryConfig(requestConfig, refreshedToken);
        return apiClient.request(retryConfig);
      }
    }

    if (statusCode === 401 && hasAuthHeader) {
      authStore.handleUnauthorized();
      if (!redirectingUnauthorized && router.currentRoute.value.name !== "login") {
        redirectingUnauthorized = true;
        try {
          await router.replace({ name: "login" });
        } finally {
          redirectingUnauthorized = false;
        }
      }
      return Promise.reject(error);
    }

    const responseData = error?.response?.data;
    const responseDetail =
      typeof responseData?.detail === "string"
        ? responseData.detail
        : Array.isArray(responseData?.non_field_errors)
          ? String(responseData.non_field_errors[0] || "")
          : "";
    const fallbackMessage =
      statusCode >= 500
        ? "A server error occurred. Please retry."
        : statusCode === 429
          ? "Too many requests. Please wait and retry."
          : "Request failed. Please retry.";
    const message = String(responseDetail || fallbackMessage).trim();
    if (message) {
      errorModalStore.showError(message);
    }
    return Promise.reject(error);
  },
);

router.beforeEach(async (to) => {
  routeLoadingStore.startNavigation();
  const publicNames = new Set(["login", "signup", "forgot-password", "reset-password", "install"]);
  if (installKnown === null) {
    try {
      const installStatus = await fetchInstallStatus();
      installKnown = installStatus.installed;
      sessionStorage.setItem("unite_install_known", String(installKnown));
    } catch {
      installKnown = true;
      sessionStorage.setItem("unite_install_known", "true");
    }
  }
  if (!installKnown && to.name !== "install") {
    return { name: "install" };
  }
  if (installKnown && to.name === "install") {
    return authStore.isAuthenticated ? { name: "feed" } : { name: "login" };
  }
  if (authStore.isAuthenticated && !authStore.sessionChecked) {
    await authStore.validateSession();
  }
  if (to.meta.requiresAuth && !authStore.isAuthenticated) {
    return { name: "login", query: { redirect: to.fullPath } };
  }
  if (to.meta.requiresStaff) {
    if (!authStore.isAuthenticated) {
      return { name: "login", query: { redirect: to.fullPath } };
    }
    if (!authStore.isStaff) {
      return { name: "feed" };
    }
  }
  if (authStore.isAuthenticated && publicNames.has(String(to.name))) {
    return { name: "feed" };
  }
  return true;
});

router.afterEach(() => {
  routeLoadingStore.finishNavigation();
});

router.onError(() => {
  routeLoadingStore.resetNavigation();
});

app.use(router).mount("#app");

if ("serviceWorker" in navigator) {
  window.addEventListener("load", async () => {
    try {
      await navigator.serviceWorker.register("/sw.js");
    } catch {
      // ignore service worker registration errors in development
    }
  });
}
