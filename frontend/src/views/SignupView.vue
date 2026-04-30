<script setup lang="ts">
import { computed, nextTick, onMounted, reactive, ref, watch } from "vue";
import { useRoute, useRouter } from "vue-router";

import { fetchPublicSignupConfig, validateSignupInviteToken } from "../api/auth";
import { fetchInterestSuggestions, type InterestSuggestion } from "../api/interests";
import { submitOnboardingInterests } from "../api/onboarding";
import { fetchProfile } from "../api/profile";
import { COUNTRY_OPTIONS } from "../constants/countries";
import { DEFAULT_INTEREST_SUGGESTIONS } from "../constants/interests";
import { useAuthStore } from "../stores/auth";
import { useErrorModalStore } from "../stores/error-modal";

const router = useRouter();
const route = useRoute();
const authStore = useAuthStore();
const errorModalStore = useErrorModalStore();
const currentStep = ref<1 | 2>(1);
const errorText = ref("");
const saving = ref(false);
const isInviteOnly = ref(false);
const isInviteGateBlocked = ref(false);
const shouldRedirectAfterInviteError = ref(false);
const invitedEmail = ref("");
const interests = ref<string[]>([]);
const interestInput = ref("");
const suggestions = ref<InterestSuggestion[]>([]);
const showCountryDropdown = ref(false);
const activeCountryIndex = ref(-1);
const countryInputRef = ref<HTMLInputElement | null>(null);
const allowedCountries = ref<string[]>([...COUNTRY_OPTIONS]);
const form = reactive({
  username: "",
  email: "",
  password: "",
  confirm_password: "",
  date_of_birth: "",
  gender: "prefer_not_to_say" as "prefer_not_to_say" | "male" | "female" | "non_binary" | "self_describe",
  gender_self_describe: "",
  zip_code: "",
  country: "",
  location: "",
});
const maxDateOfBirth = computed(() => {
  const today = new Date();
  const cutoff = new Date(today.getFullYear() - 13, today.getMonth(), today.getDate());
  return cutoff.toISOString().slice(0, 10);
});
function normalizeInviteToken(rawValue: string): string {
  let token = String(rawValue || "").trim();
  token = token.replace(/[\r\n\s]+/g, "");
  if (token.startsWith("3D")) {
    token = token.slice(2);
  }
  token = token.replace(/=/g, "");
  return token;
}
const inviteToken = computed(() => {
  const raw = route.query.invite;
  if (Array.isArray(raw)) {
    return normalizeInviteToken(String(raw[0] || ""));
  }
  return normalizeInviteToken(String(raw || ""));
});
const isInviteEmailLocked = computed(() => Boolean(invitedEmail.value));
const INVITE_ONLY_SIGNUP_ERROR =
  "We are currenlty only allowing new accounts via invites only. If you have received an invite link, please follow that url to register.";

function blockSignupAndRedirectToLogin(): void {
  isInviteGateBlocked.value = true;
  shouldRedirectAfterInviteError.value = true;
  errorText.value = INVITE_ONLY_SIGNUP_ERROR;
  errorModalStore.showError(INVITE_ONLY_SIGNUP_ERROR);
}

const mergedSuggestions = computed(() => {
  const selected = new Set(interests.value);
  const merged = [...suggestions.value.map((item) => item.tag), ...DEFAULT_INTEREST_SUGGESTIONS];
  const next: string[] = [];
  for (const raw of merged) {
    const token = raw.trim().toLowerCase();
    if (!token || selected.has(token) || next.includes(token)) {
      continue;
    }
    next.push(token);
  }
  return next.slice(0, 10);
});

const filteredCountryOptions = computed(() => {
  const query = form.country.trim().toLowerCase();
  if (!query) {
    return allowedCountries.value;
  }
  return allowedCountries.value.filter((countryName) => countryName.toLowerCase().includes(query));
});

function addInterest(value: string) {
  const token = value.trim().toLowerCase();
  if (!token || interests.value.includes(token)) {
    return;
  }
  interests.value.push(token);
}

function removeInterest(value: string) {
  interests.value = interests.value.filter((item) => item !== value);
}

function commitInterestInput() {
  const segments = interestInput.value.split(",");
  for (const item of segments) {
    addInterest(item);
  }
  interestInput.value = "";
}

function onInterestKeydown(event: KeyboardEvent) {
  if (event.key === "," || event.key === "Enter") {
    event.preventDefault();
    commitInterestInput();
  }
}

function openCountryDropdown() {
  showCountryDropdown.value = true;
  if (filteredCountryOptions.value.length > 0 && activeCountryIndex.value < 0) {
    activeCountryIndex.value = 0;
  }
}

function closeCountryDropdown() {
  window.setTimeout(() => {
    showCountryDropdown.value = false;
    activeCountryIndex.value = -1;
  }, 120);
}

function selectCountry(countryName: string) {
  form.country = countryName;
  showCountryDropdown.value = false;
  activeCountryIndex.value = -1;
}

function onCountryInput() {
  openCountryDropdown();
  activeCountryIndex.value = filteredCountryOptions.value.length > 0 ? 0 : -1;
}

function scrollActiveCountryIntoView() {
  void nextTick(() => {
    const activeIndex = activeCountryIndex.value;
    if (activeIndex < 0) {
      return;
    }
    const activeOption = document.getElementById(`signup-country-option-${activeIndex}`);
    activeOption?.scrollIntoView({ block: "nearest" });
  });
}

function onCountryKeydown(event: KeyboardEvent) {
  const optionsCount = filteredCountryOptions.value.length;
  if (event.key === "Escape") {
    showCountryDropdown.value = false;
    activeCountryIndex.value = -1;
    return;
  }
  if (event.key === "Tab") {
    showCountryDropdown.value = false;
    activeCountryIndex.value = -1;
    return;
  }
  if (!optionsCount) {
    return;
  }
  if (event.key === "ArrowDown") {
    event.preventDefault();
    if (!showCountryDropdown.value) {
      openCountryDropdown();
      activeCountryIndex.value = 0;
    } else {
      activeCountryIndex.value = (activeCountryIndex.value + 1 + optionsCount) % optionsCount;
    }
    scrollActiveCountryIntoView();
    return;
  }
  if (event.key === "ArrowUp") {
    event.preventDefault();
    if (!showCountryDropdown.value) {
      openCountryDropdown();
      activeCountryIndex.value = optionsCount - 1;
    } else {
      activeCountryIndex.value = (activeCountryIndex.value - 1 + optionsCount) % optionsCount;
    }
    scrollActiveCountryIntoView();
    return;
  }
  if (event.key === "Enter" && showCountryDropdown.value && activeCountryIndex.value >= 0) {
    event.preventDefault();
    const selected = filteredCountryOptions.value[activeCountryIndex.value];
    if (selected) {
      selectCountry(selected);
      countryInputRef.value?.blur();
    }
  }
}

async function refreshSuggestions() {
  try {
    suggestions.value = await fetchInterestSuggestions(interests.value, interestInput.value.trim().toLowerCase(), 8);
  } catch {
    suggestions.value = [];
  }
}

async function onContinueToStep2() {
  errorText.value = "";
  if (isInviteGateBlocked.value) {
    return;
  }
  if (isInviteOnly.value && invitedEmail.value && form.email.trim().toLowerCase() !== invitedEmail.value) {
    const mismatchMessage = "This invite is only valid for the invited email address.";
    errorText.value = mismatchMessage;
    errorModalStore.showError(mismatchMessage);
    return;
  }
  if (form.password !== form.confirm_password) {
    const mismatchMessage = "Passwords do not match.";
    errorText.value = mismatchMessage;
    errorModalStore.showError(mismatchMessage);
    return;
  }
  saving.value = true;
  try {
    await authStore.signupUser({
      username: form.username,
      email: form.email,
      password: form.password,
      date_of_birth: form.date_of_birth,
      gender: form.gender,
      gender_self_describe: form.gender === "self_describe" ? form.gender_self_describe.trim() : "",
      zip_code: form.zip_code,
      country: form.country,
      invite_token: inviteToken.value || undefined,
    });
    currentStep.value = 2;
    await refreshSuggestions();
  } catch (error: unknown) {
    const apiError = error as {
      response?: {
        data?: {
          detail?: string;
          non_field_errors?: string[];
        };
      };
    };
    const apiDetail = String(apiError?.response?.data?.detail || "").trim();
    const nonFieldError = String(apiError?.response?.data?.non_field_errors?.[0] || "").trim();
    const fallback = "Signup failed. Please verify your credentials.";
    const message = apiDetail || nonFieldError || fallback;
    errorText.value = message;
    errorModalStore.showError(message);
  } finally {
    saving.value = false;
  }
}

async function onFinishSignup() {
  errorText.value = "";
  if (interests.value.length < 5) {
    errorText.value = "Add at least 5 interests.";
    errorModalStore.showError("Add at least 5 interests.");
    return;
  }
  saving.value = true;
  try {
    await submitOnboardingInterests({
      interests: interests.value,
      location: form.location || undefined,
    });
    try {
      const profile = await fetchProfile();
      await router.push(profile.algorithm_profile_status === "ready" ? "/" : "/profile-generation?next=/");
    } catch {
      await router.push("/");
    }
  } finally {
    saving.value = false;
  }
}

async function onCancel() {
  authStore.logout();
  await router.push("/login");
}

onMounted(async () => {
  try {
    const config = await fetchPublicSignupConfig();
    isInviteOnly.value = Boolean(config.register_via_invite_only);
    const next = Array.isArray(config.allowed_signup_countries)
      ? config.allowed_signup_countries.map((item) => String(item).trim()).filter(Boolean)
      : [];
    allowedCountries.value = next.length ? next.sort((a, b) => a.localeCompare(b)) : [...COUNTRY_OPTIONS];
    if (isInviteOnly.value) {
      if (!inviteToken.value) {
        blockSignupAndRedirectToLogin();
        return;
      }
      const inviteValidation = await validateSignupInviteToken(inviteToken.value);
      if (!inviteValidation.is_valid) {
        blockSignupAndRedirectToLogin();
        return;
      }
      invitedEmail.value = String(inviteValidation.invited_email || "").trim().toLowerCase();
      if (invitedEmail.value) {
        form.email = invitedEmail.value;
      }
    }
  } catch {
    allowedCountries.value = [...COUNTRY_OPTIONS];
  }
});

watch(
  () => errorModalStore.isOpen,
  (isOpen, wasOpen) => {
    if (shouldRedirectAfterInviteError.value && wasOpen && !isOpen) {
      shouldRedirectAfterInviteError.value = false;
      void router.replace("/login");
    }
  },
);
</script>

<template>
  <div class="modal-overlay">
    <section class="auth-card modal-card mention-host-card filter-modal-card">
      <h1>Sign up</h1>
      <p>Step {{ currentStep }} of 2</p>

      <div v-if="isInviteGateBlocked" class="stack">
        <p>{{ INVITE_ONLY_SIGNUP_ERROR }}</p>
      </div>
      <form v-else-if="currentStep === 1" @submit.prevent="onContinueToStep2" class="stack">
        <input v-model="form.username" placeholder="Username" required />
        <input v-model="form.email" type="email" placeholder="Email" :readonly="isInviteEmailLocked" required />
        <input v-model="form.password" type="password" placeholder="Password" required />
        <input v-model="form.confirm_password" type="password" placeholder="Confirm password" required />
        <label class="signup-field-label" for="signup-dob">Date of birth</label>
        <input id="signup-dob" v-model="form.date_of_birth" type="date" :max="maxDateOfBirth" required />
        <select v-model="form.gender" required>
          <option value="prefer_not_to_say">Prefer not to say</option>
          <option value="male">Male</option>
          <option value="female">Female</option>
          <option value="non_binary">Non Binary</option>
          <option value="self_describe">Self Describe</option>
        </select>
        <input
          v-if="form.gender === 'self_describe'"
          v-model="form.gender_self_describe"
          placeholder="Describe your gender"
          required
        />
        <input v-model="form.zip_code" placeholder="ZIP / postal code" required />
        <div class="signup-country-field">
          <input
            ref="countryInputRef"
            v-model="form.country"
            placeholder="Country"
            required
            @focus="openCountryDropdown"
            @input="onCountryInput"
            @blur="closeCountryDropdown"
            @keydown="onCountryKeydown"
          />
          <div v-if="showCountryDropdown" class="signup-country-dropdown">
            <button
              v-for="(countryName, index) in filteredCountryOptions"
              :key="countryName"
              :id="`signup-country-option-${index}`"
              type="button"
              class="signup-country-option"
              :class="{ active: index === activeCountryIndex }"
              @mousedown.prevent="selectCountry(countryName)"
            >
              {{ countryName }}
            </button>
          </div>
        </div>
        <div class="modal-actions">
          <button type="button" @click="onCancel">Cancel</button>
          <button type="submit" :disabled="saving">{{ saving ? "Creating..." : "Continue" }}</button>
        </div>
        <div v-if="saving" class="progress-track"><div class="progress-fill progress-indeterminate" /></div>
      </form>

      <form v-else @submit.prevent="onFinishSignup" class="stack">
        <input v-model="form.location" placeholder="Location (optional)" />
        <input
          v-model="interestInput"
          placeholder="Type an interest then comma"
          @keydown="onInterestKeydown"
          @blur="commitInterestInput"
          @input="refreshSuggestions"
        />
        <div class="chip-row">
          <span v-for="item in interests" :key="item" class="interest-chip">
            {{ item }}
            <button type="button" class="chip-remove" @click="removeInterest(item)">x</button>
          </span>
        </div>
        <div class="suggestion-list">
          <button
            v-for="suggested in mergedSuggestions"
            :key="suggested"
            type="button"
            class="suggestion-chip"
            @click="addInterest(suggested)"
          >
            #{{ suggested }}
          </button>
        </div>
        <div class="modal-actions">
          <button type="button" @click="onCancel">Cancel</button>
          <button type="submit" :disabled="saving">{{ saving ? "Saving..." : "Finish signup" }}</button>
        </div>
        <div v-if="saving" class="progress-track"><div class="progress-fill progress-indeterminate" /></div>
      </form>

      <div v-if="saving" class="loading-overlay">
        <div class="spinner" />
      </div>
    </section>
  </div>
</template>
