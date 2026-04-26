import { createPinia } from "pinia";
import { createApp } from "vue";

import App from "./App.vue";
import { apiClient } from "./api/client";
import { fetchInstallStatus } from "./api/install";
import router from "./router";
import { useAuthStore } from "./stores/auth";
import { loadThemeOnStartup } from "./theme";
import "./style.css";

void loadThemeOnStartup();

const pinia = createPinia();
const app = createApp(App);
app.use(pinia);
const authStore = useAuthStore(pinia);
authStore.hydrateFromStorage();
let installKnown: boolean | null = null;
const cachedInstallState = sessionStorage.getItem("unite_install_known");
if (cachedInstallState === "true") {
  installKnown = true;
}
if (cachedInstallState === "false") {
  installKnown = false;
}

let redirectingUnauthorized = false;
apiClient.interceptors.response.use(
  (response) => response,
  async (error) => {
    const statusCode = Number(error?.response?.status || 0);
    if (statusCode === 401) {
      authStore.handleUnauthorized();
      if (!redirectingUnauthorized && router.currentRoute.value.name !== "login") {
        redirectingUnauthorized = true;
        try {
          await router.replace({ name: "login" });
        } finally {
          redirectingUnauthorized = false;
        }
      }
    }
    return Promise.reject(error);
  },
);

router.beforeEach(async (to) => {
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
