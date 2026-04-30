<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from "vue";
import { useRouter } from "vue-router";

import { fetchSiteSettings, sendSignupInvite, updateSiteSettings } from "../api/auth";
import { COUNTRY_OPTIONS } from "../constants/countries";
import { useErrorModalStore } from "../stores/error-modal";

const router = useRouter();
const errorModalStore = useErrorModalStore();
const isLoading = ref(false);
const isSaving = ref(false);
const isSendingInvite = ref(false);
const statusText = ref("");
const statusType = ref<"success" | "error" | "info">("info");
const statusAction = ref("");
const settingsForm = reactive({
  register_via_invite_only: false,
  site_name: "",
  support_email: "",
  frontend_base_url: "",
  default_from_email: "",
  email_backend: "",
  email_host: "",
  email_port: null as number | null,
  email_host_user: "",
  has_email_host_password: false,
  email_use_tls: false,
  email_use_ssl: false,
  email_timeout_seconds: 10,
  enforce_signup_ip_country_match: true,
  allow_signup_on_ip_country_lookup_failure: true,
  ip_country_lookup_timeout_seconds: 3,
  ip_country_lookup_url_template: "",
});
const allowedCountries = ref<string[]>([]);
const countryInput = ref("");
const inviteForm = reactive({
  email: "",
});
const smtpPasswordInput = ref("");
const isHydrated = ref(false);
const lastSavedCountriesSignature = ref<string>("[]");
let countriesAutosaveTimer: ReturnType<typeof setTimeout> | null = null;
const COUNTRY_AUTOSAVE_DELAY_MS = 400;
const shouldShowLookupFailureBehavior = computed(() => settingsForm.enforce_signup_ip_country_match);

function goBack() {
  void router.push({ name: "feed" });
}

function showStatus(action: string, message: string, type: "success" | "error" | "info" = "info"): void {
  statusAction.value = action.trim();
  statusText.value = message.trim();
  statusType.value = type;
}

function clearStatus(): void {
  statusAction.value = "";
  statusText.value = "";
  statusType.value = "info";
}

function extractApiErrorMessage(error: unknown, fallback: string): string {
  const apiError = error as {
    response?: {
      data?: {
        detail?: string;
        non_field_errors?: string[];
        [key: string]: unknown;
      };
    };
  };
  const detail = String(apiError?.response?.data?.detail || "").trim();
  if (detail) {
    return detail;
  }
  const nonField = String(apiError?.response?.data?.non_field_errors?.[0] || "").trim();
  if (nonField) {
    return nonField;
  }
  const data = apiError?.response?.data || {};
  for (const [key, value] of Object.entries(data)) {
    if (key === "detail" || key === "non_field_errors") {
      continue;
    }
    if (Array.isArray(value) && value.length > 0) {
      const candidate = String(value[0] || "").trim();
      if (candidate) {
        return `${key}: ${candidate}`;
      }
    }
  }
  return fallback;
}

function normalizeCountryToken(value: string): string {
  return value.trim().toLowerCase();
}

function resolveCountryName(rawValue: string): string {
  const trimmed = rawValue.trim();
  if (!trimmed) {
    return "";
  }
  const token = trimmed.toLowerCase();
  return COUNTRY_OPTIONS.find((countryName) => countryName.toLowerCase() === token) || trimmed;
}

function addCountry(rawValue: string) {
  const resolved = resolveCountryName(rawValue);
  if (!resolved) {
    return;
  }
  const target = normalizeCountryToken(resolved);
  if (allowedCountries.value.some((item) => normalizeCountryToken(item) === target)) {
    return;
  }
  allowedCountries.value = [...allowedCountries.value, resolved].sort((a, b) => a.localeCompare(b));
  void flushCountriesAutosave();
}

function removeCountry(value: string) {
  const target = normalizeCountryToken(value);
  allowedCountries.value = allowedCountries.value.filter((item) => normalizeCountryToken(item) !== target);
  void flushCountriesAutosave();
}

function commitCountryInput() {
  const segments = countryInput.value.split(",");
  for (const segment of segments) {
    addCountry(segment);
  }
  countryInput.value = "";
}

function onCountryKeydown(event: KeyboardEvent) {
  if (event.key === "," || event.key === "Enter") {
    event.preventDefault();
    commitCountryInput();
  }
}

async function persistAllowedCountries(nextCountries: string[], options: { silent?: boolean } = {}): Promise<boolean> {
  if (isSaving.value) {
    return false;
  }
  isSaving.value = true;
  if (!options.silent) {
    clearStatus();
  }
  try {
    const updated = await updateSiteSettings({ allowed_signup_countries: nextCountries });
    const normalized = Array.isArray(updated.allowed_signup_countries)
      ? updated.allowed_signup_countries.map((item) => String(item))
      : [];
    lastSavedCountriesSignature.value = JSON.stringify(normalized);
    if (!options.silent) {
      showStatus("Allowed Countries", "Allowed countries updated.", "success");
    }
    return true;
  } catch (error) {
    const message = extractApiErrorMessage(error, "Unable to update allowed countries.");
    showStatus("Allowed Countries", message, "error");
    errorModalStore.showError(message);
    return false;
  } finally {
    isSaving.value = false;
  }
}

function scheduleCountriesAutosave() {
  if (!isHydrated.value) {
    return;
  }
  if (countriesAutosaveTimer) {
    clearTimeout(countriesAutosaveTimer);
  }
  countriesAutosaveTimer = setTimeout(() => {
    countriesAutosaveTimer = null;
    void flushCountriesAutosave();
  }, COUNTRY_AUTOSAVE_DELAY_MS);
}

async function flushCountriesAutosave() {
  if (countriesAutosaveTimer) {
    clearTimeout(countriesAutosaveTimer);
    countriesAutosaveTimer = null;
  }
  const nextCountries = [...allowedCountries.value];
  const signature = JSON.stringify(nextCountries);
  if (signature === lastSavedCountriesSignature.value) {
    return;
  }
  await persistAllowedCountries(nextCountries);
}

watch(allowedCountries, scheduleCountriesAutosave, { deep: true });

async function loadSettings() {
  isLoading.value = true;
  try {
    const payload = await fetchSiteSettings();
    settingsForm.register_via_invite_only = Boolean(payload.register_via_invite_only);
    settingsForm.site_name = String(payload.site_name || "");
    settingsForm.support_email = String(payload.support_email || "");
    settingsForm.frontend_base_url = String(payload.frontend_base_url || "");
    settingsForm.default_from_email = String(payload.default_from_email || "");
    settingsForm.email_backend = String(payload.email_backend || "");
    settingsForm.email_host = String(payload.email_host || "");
    settingsForm.email_port = payload.email_port == null ? null : Number(payload.email_port);
    settingsForm.email_host_user = String(payload.email_host_user || "");
    settingsForm.has_email_host_password = Boolean(payload.has_email_host_password);
    settingsForm.email_use_tls = Boolean(payload.email_use_tls);
    settingsForm.email_use_ssl = Boolean(payload.email_use_ssl);
    settingsForm.email_timeout_seconds = Number(payload.email_timeout_seconds || 10);
    settingsForm.enforce_signup_ip_country_match = Boolean(payload.enforce_signup_ip_country_match);
    settingsForm.allow_signup_on_ip_country_lookup_failure = Boolean(payload.allow_signup_on_ip_country_lookup_failure);
    settingsForm.ip_country_lookup_timeout_seconds = Number(payload.ip_country_lookup_timeout_seconds || 3);
    settingsForm.ip_country_lookup_url_template = String(payload.ip_country_lookup_url_template || "");
    const savedCountries = Array.isArray(payload.allowed_signup_countries)
      ? payload.allowed_signup_countries.map((item) => String(item).trim()).filter(Boolean)
      : [];
    if (savedCountries.length === 0) {
      const defaults = [...COUNTRY_OPTIONS].sort((a, b) => a.localeCompare(b));
      await persistAllowedCountries(defaults, { silent: true });
      allowedCountries.value = defaults;
    } else {
      allowedCountries.value = savedCountries.sort((a, b) => a.localeCompare(b));
      lastSavedCountriesSignature.value = JSON.stringify(allowedCountries.value);
    }
  } catch {
    errorModalStore.showError("Unable to load site settings.");
  } finally {
    isLoading.value = false;
    isHydrated.value = true;
  }
}

async function onToggleInviteOnly() {
  if (isSaving.value) {
    return;
  }
  const nextValue = !settingsForm.register_via_invite_only;
  isSaving.value = true;
  clearStatus();
  try {
    const updated = await updateSiteSettings({ register_via_invite_only: nextValue });
    settingsForm.register_via_invite_only = Boolean(updated.register_via_invite_only);
    showStatus("Invite-Only Registration", "Invite-only setting updated.", "success");
  } catch (error) {
    const message = extractApiErrorMessage(error, "Unable to save site settings.");
    showStatus("Invite-Only Registration", message, "error");
    errorModalStore.showError(message);
  } finally {
    isSaving.value = false;
  }
}

async function onSaveDeliverySettings() {
  if (isSaving.value) {
    return;
  }
  isSaving.value = true;
  clearStatus();
  try {
    const payload: Partial<{
      site_name: string;
      support_email: string;
      frontend_base_url: string;
      default_from_email: string;
      email_backend: string;
      email_host: string;
      email_port: number | null;
      email_host_user: string;
      email_host_password: string;
      email_use_tls: boolean;
      email_use_ssl: boolean;
      email_timeout_seconds: number;
      enforce_signup_ip_country_match: boolean;
      allow_signup_on_ip_country_lookup_failure: boolean;
      ip_country_lookup_timeout_seconds: number;
      ip_country_lookup_url_template: string;
    }> = {
      site_name: settingsForm.site_name.trim(),
      support_email: settingsForm.support_email.trim(),
      frontend_base_url: settingsForm.frontend_base_url.trim(),
      default_from_email: settingsForm.default_from_email.trim(),
      email_backend: settingsForm.email_backend.trim(),
      email_host: settingsForm.email_host.trim(),
      email_port: settingsForm.email_port == null ? null : Number(settingsForm.email_port),
      email_host_user: settingsForm.email_host_user.trim(),
      email_use_tls: Boolean(settingsForm.email_use_tls),
      email_use_ssl: Boolean(settingsForm.email_use_ssl),
      email_timeout_seconds: Number(settingsForm.email_timeout_seconds || 10),
      enforce_signup_ip_country_match: Boolean(settingsForm.enforce_signup_ip_country_match),
      allow_signup_on_ip_country_lookup_failure: settingsForm.enforce_signup_ip_country_match
        ? Boolean(settingsForm.allow_signup_on_ip_country_lookup_failure)
        : true,
      ip_country_lookup_timeout_seconds: Number(settingsForm.ip_country_lookup_timeout_seconds || 3),
      ip_country_lookup_url_template: settingsForm.ip_country_lookup_url_template.trim(),
    };
    if (smtpPasswordInput.value.trim()) {
      payload.email_host_password = smtpPasswordInput.value.trim();
    }
    const updated = await updateSiteSettings(payload);
    settingsForm.site_name = String(updated.site_name || "");
    settingsForm.support_email = String(updated.support_email || "");
    settingsForm.frontend_base_url = String(updated.frontend_base_url || "");
    settingsForm.default_from_email = String(updated.default_from_email || "");
    settingsForm.email_backend = String(updated.email_backend || "");
    settingsForm.email_host = String(updated.email_host || "");
    settingsForm.email_port = updated.email_port == null ? null : Number(updated.email_port);
    settingsForm.email_host_user = String(updated.email_host_user || "");
    settingsForm.has_email_host_password = Boolean(updated.has_email_host_password);
    settingsForm.email_use_tls = Boolean(updated.email_use_tls);
    settingsForm.email_use_ssl = Boolean(updated.email_use_ssl);
    settingsForm.email_timeout_seconds = Number(updated.email_timeout_seconds || 10);
    settingsForm.enforce_signup_ip_country_match = Boolean(updated.enforce_signup_ip_country_match);
    settingsForm.allow_signup_on_ip_country_lookup_failure = Boolean(updated.allow_signup_on_ip_country_lookup_failure);
    settingsForm.ip_country_lookup_timeout_seconds = Number(updated.ip_country_lookup_timeout_seconds || 3);
    settingsForm.ip_country_lookup_url_template = String(updated.ip_country_lookup_url_template || "");
    smtpPasswordInput.value = "";
    showStatus("Delivery and Runtime", "Delivery and runtime settings updated.", "success");
  } catch (error) {
    const message = extractApiErrorMessage(error, "Unable to save delivery settings.");
    showStatus("Delivery and Runtime", message, "error");
    errorModalStore.showError(message);
  } finally {
    isSaving.value = false;
  }
}

async function onSendInvite() {
  if (isSendingInvite.value) {
    return;
  }
  const email = inviteForm.email.trim();
  if (!email) {
    errorModalStore.showError("Email is required.");
    return;
  }
  isSendingInvite.value = true;
  clearStatus();
  try {
    await sendSignupInvite({ email });
    showStatus("Send Invite", `Invite email sent to ${email}.`, "success");
    inviteForm.email = "";
  } catch (error) {
    const message = extractApiErrorMessage(error, "Unable to send invite email.");
    showStatus("Send Invite", message, "error");
    errorModalStore.showError(message);
  } finally {
    isSendingInvite.value = false;
  }
}

onMounted(async () => {
  await loadSettings();
});
</script>

<template>
  <section class="auth-card">
    <div v-if="statusText" class="settings-ribbon" :class="`is-${statusType}`">
      <span class="settings-ribbon-title">{{ statusAction }}</span>
      <span>{{ statusText }}</span>
      <button type="button" class="chip-remove" aria-label="Dismiss status" @click="clearStatus">x</button>
    </div>
    <button class="back-button icon-only-button" type="button" @click="goBack" title="Back" aria-label="Back">
      <svg viewBox="0 0 16 16" class="icon"><path d="M5 1H4L0 5L4 9H5V6H11C12.6569 6 14 7.34315 14 9C14 10.6569 12.6569 12 11 12H4V14H11C13.7614 14 16 11.7614 16 9C16 6.23858 13.7614 4 11 4H5V1Z" fill="currentColor"/></svg>
    </button>
    <h1>Site Settings</h1>
    <p v-if="isLoading">Loading settings...</p>
    <div v-else class="stack settings-panel">
      <div class="stack settings-section">
        <h3>Registration</h3>
        <div class="settings-toggle-row">
          <span>Register via Invite Only</span>
          <button
            type="button"
            class="settings-switch"
            :class="{ on: settingsForm.register_via_invite_only }"
            role="switch"
            :aria-checked="settingsForm.register_via_invite_only ? 'true' : 'false'"
            :disabled="isSaving"
            @click="onToggleInviteOnly"
          >
            <span class="settings-switch-label">{{ settingsForm.register_via_invite_only ? "ON" : "OFF" }}</span>
            <span class="settings-switch-knob" />
          </button>
        </div>
        <div class="stack">
          <input v-model="inviteForm.email" type="email" placeholder="Invite email address" />
          <button type="button" :disabled="isSendingInvite" @click="onSendInvite">
            {{ isSendingInvite ? "Sending..." : "Send Invite" }}
          </button>
        </div>
        <div class="stack">
          <h3>Live Runtime Settings</h3>
          <label class="profile-section-heading admin-settings">Site Name</label>
          <input v-model="settingsForm.site_name" type="text" placeholder="Site name" />
          <label class="profile-section-heading admin-settings">Support Email</label>
          <input v-model="settingsForm.support_email" type="email" placeholder="Support email" />
          <label class="profile-section-heading admin-settings">Frontend Base URL</label>
          <input v-model="settingsForm.frontend_base_url" type="url" placeholder="Frontend base URL" />
          <label class="profile-section-heading admin-settings">Default From Email</label>
          <input v-model="settingsForm.default_from_email" type="email" placeholder="Default from email" />
          <h3>SMTP Settings</h3>
          <label class="profile-section-heading admin-settings">Email Backend</label>
          <input
            v-model="settingsForm.email_backend"
            type="text"
            placeholder="Email backend (django.core.mail.backends.smtp.EmailBackend)"
            autocomplete="off"
          />
          <label class="profile-section-heading admin-settings">SMTP Host</label>
          <input v-model="settingsForm.email_host" type="text" placeholder="SMTP host" autocomplete="off" />
          <label class="profile-section-heading admin-settings">SMTP Port</label>
          <input
            v-model.number="settingsForm.email_port"
            type="number"
            min="1"
            placeholder="SMTP port"
            autocomplete="off"
          />
          <label class="profile-section-heading admin-settings">SMTP Username</label>
          <input v-model="settingsForm.email_host_user" type="text" placeholder="SMTP username" autocomplete="off" />
          <label class="profile-section-heading admin-settings">SMTP Password</label>
          <input
            v-model="smtpPasswordInput"
            type="password"
            placeholder="SMTP password (leave blank to keep current)"
            autocomplete="new-password"
          />
          <p v-if="settingsForm.has_email_host_password">SMTP password is currently configured.</p>
          <div class="settings-toggle-row">
            <span>Use TLS</span>
            <button
              type="button"
              class="settings-switch"
              :class="{ on: settingsForm.email_use_tls }"
              role="switch"
              :aria-checked="settingsForm.email_use_tls ? 'true' : 'false'"
              :disabled="isSaving"
              @click="settingsForm.email_use_tls = !settingsForm.email_use_tls"
            >
              <span class="settings-switch-label">{{ settingsForm.email_use_tls ? "ON" : "OFF" }}</span>
              <span class="settings-switch-knob" />
            </button>
          </div>
          <div class="settings-toggle-row">
            <span>Use SSL</span>
            <button
              type="button"
              class="settings-switch"
              :class="{ on: settingsForm.email_use_ssl }"
              role="switch"
              :aria-checked="settingsForm.email_use_ssl ? 'true' : 'false'"
              :disabled="isSaving"
              @click="settingsForm.email_use_ssl = !settingsForm.email_use_ssl"
            >
              <span class="settings-switch-label">{{ settingsForm.email_use_ssl ? "ON" : "OFF" }}</span>
              <span class="settings-switch-knob" />
            </button>
          </div>
          <label class="profile-section-heading admin-settings">Email Timeout Seconds</label>
          <input v-model.number="settingsForm.email_timeout_seconds" type="number" min="1" placeholder="Email timeout seconds" />
          <h3>IP Country Validation Settings</h3>
          <div class="settings-toggle-row">
            <span>Enforce Signup IP-Country Match</span>
            <button
              type="button"
              class="settings-switch"
              :class="{ on: settingsForm.enforce_signup_ip_country_match }"
              role="switch"
              :aria-checked="settingsForm.enforce_signup_ip_country_match ? 'true' : 'false'"
              :disabled="isSaving"
              @click="settingsForm.enforce_signup_ip_country_match = !settingsForm.enforce_signup_ip_country_match"
            >
              <span class="settings-switch-label">{{ settingsForm.enforce_signup_ip_country_match ? "ON" : "OFF" }}</span>
              <span class="settings-switch-knob" />
            </button>
          </div>
          <div v-if="shouldShowLookupFailureBehavior" class="settings-toggle-row">
            <span>Allow Signup If IP Lookup Fails</span>
            <button
              type="button"
              class="settings-switch"
              :class="{ on: settingsForm.allow_signup_on_ip_country_lookup_failure }"
              role="switch"
              :aria-checked="settingsForm.allow_signup_on_ip_country_lookup_failure ? 'true' : 'false'"
              :disabled="isSaving"
              @click="settingsForm.allow_signup_on_ip_country_lookup_failure = !settingsForm.allow_signup_on_ip_country_lookup_failure"
            >
              <span class="settings-switch-label">{{ settingsForm.allow_signup_on_ip_country_lookup_failure ? "ON" : "OFF" }}</span>
              <span class="settings-switch-knob" />
            </button>
          </div>
          <label class="profile-section-heading admin-settings">IP Lookup Timeout Seconds</label>
          <input
            v-model.number="settingsForm.ip_country_lookup_timeout_seconds"
            type="number"
            min="1"
            placeholder="IP country lookup timeout seconds"
          />
          <label class="profile-section-heading admin-settings">IP Lookup URL Template</label>
          <input
            v-model="settingsForm.ip_country_lookup_url_template"
            type="text"
            placeholder="IP country lookup URL template (use {ip})"
          />
          <button type="button" :disabled="isSaving" @click="onSaveDeliverySettings">
            {{ isSaving ? "Saving..." : "Save delivery/runtime settings" }}
          </button>
        </div>
        <div class="stack">
          <label class="profile-section-heading admin-settings">Allowed Countries</label>
          <input
            v-model="countryInput"
            type="text"
            placeholder="Type a country then comma"
            @keydown="onCountryKeydown"
            @blur="commitCountryInput"
          />
          <div class="chip-row">
            <span v-for="countryName in allowedCountries" :key="countryName" class="interest-chip">
              {{ countryName }}
              <button type="button" class="chip-remove" @click="removeCountry(countryName)">x</button>
            </span>
          </div>
        </div>
      </div>
    </div>
  </section>
</template>
