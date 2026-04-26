import { defineStore } from "pinia";

import { login, signup, type LoginInput, type SignupInput } from "../api/auth";
import { setAuthToken } from "../api/client";
import { fetchProfile } from "../api/profile";

interface AuthState {
  accessToken: string | null;
  refreshToken: string | null;
  username: string | null;
  isStaff: boolean;
  isHydrated: boolean;
  sessionChecked: boolean;
}

export const useAuthStore = defineStore("auth", {
  state: (): AuthState => ({
    accessToken: null,
    refreshToken: null,
    username: null,
    isStaff: false,
    isHydrated: false,
    sessionChecked: false,
  }),
  getters: {
    isAuthenticated: (state) => Boolean(state.accessToken),
  },
  actions: {
    persist() {
      localStorage.setItem(
        "unite_auth",
        JSON.stringify({
          accessToken: this.accessToken,
          refreshToken: this.refreshToken,
          username: this.username,
          isStaff: this.isStaff,
        }),
      );
    },
    hydrateFromStorage() {
      if (this.isHydrated) {
        return;
      }
      this.isHydrated = true;
      const raw = localStorage.getItem("unite_auth");
      if (!raw) {
        return;
      }
      try {
        const parsed = JSON.parse(raw) as {
          accessToken?: string;
          refreshToken?: string;
          username?: string;
          isStaff?: boolean;
        };
        this.accessToken = parsed.accessToken || null;
        this.refreshToken = parsed.refreshToken || null;
        this.username = parsed.username || null;
        this.isStaff = Boolean(parsed.isStaff);
        setAuthToken(this.accessToken);
      } catch {
        localStorage.removeItem("unite_auth");
      }
    },
    async refreshUserMeta() {
      if (!this.accessToken) {
        this.isStaff = false;
        return false;
      }
      try {
        const profile = await fetchProfile();
        this.isStaff = Boolean(profile.is_staff);
        return true;
      } catch {
        this.isStaff = false;
        return false;
      }
    },
    async validateSession() {
      if (!this.accessToken) {
        this.sessionChecked = true;
        return false;
      }
      const ok = await this.refreshUserMeta();
      this.sessionChecked = true;
      if (!ok) {
        this.logout();
      }
      return ok;
    },
    setAuthPayload(authPayload: { access: string; refresh: string; username: string }) {
      this.accessToken = authPayload.access;
      this.refreshToken = authPayload.refresh;
      this.username = authPayload.username;
      this.sessionChecked = false;
      setAuthToken(authPayload.access);
      this.persist();
    },
    async loginUser(payload: LoginInput) {
      const authPayload = await login(payload);
      this.setAuthPayload(authPayload);
      await this.refreshUserMeta();
      this.sessionChecked = true;
      this.persist();
    },
    async signupUser(payload: SignupInput) {
      const authPayload = await signup(payload);
      this.setAuthPayload(authPayload);
      await this.refreshUserMeta();
      this.sessionChecked = true;
      this.persist();
    },
    logout() {
      this.accessToken = null;
      this.refreshToken = null;
      this.username = null;
      this.isStaff = false;
      this.sessionChecked = true;
      setAuthToken(null);
      localStorage.removeItem("unite_auth");
    },
    handleUnauthorized() {
      if (!this.accessToken) {
        return;
      }
      this.logout();
    },
  },
});
