<script setup lang="ts">
import { computed, reactive, ref } from "vue";
import { useRouter } from "vue-router";

import { fetchInterestSuggestions, type InterestSuggestion } from "../api/interests";
import { submitOnboardingInterests } from "../api/onboarding";
import { fetchProfile } from "../api/profile";
import { DEFAULT_INTEREST_SUGGESTIONS } from "../constants/interests";
import { useAuthStore } from "../stores/auth";

const router = useRouter();
const authStore = useAuthStore();
const currentStep = ref<1 | 2>(1);
const errorText = ref("");
const saving = ref(false);
const interests = ref<string[]>([]);
const interestInput = ref("");
const suggestions = ref<InterestSuggestion[]>([]);
const form = reactive({
  username: "",
  email: "",
  password: "",
  location: "",
});

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

async function refreshSuggestions() {
  try {
    suggestions.value = await fetchInterestSuggestions(interests.value, interestInput.value.trim().toLowerCase(), 8);
  } catch {
    suggestions.value = [];
  }
}

async function onContinueToStep2() {
  errorText.value = "";
  saving.value = true;
  try {
    await authStore.signupUser({
      username: form.username,
      email: form.email,
      password: form.password,
    });
    currentStep.value = 2;
    await refreshSuggestions();
  } catch {
    errorText.value = "Signup failed. Please verify your credentials.";
  } finally {
    saving.value = false;
  }
}

async function onFinishSignup() {
  errorText.value = "";
  if (interests.value.length < 5) {
    errorText.value = "Add at least 5 interests.";
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
</script>

<template>
  <div class="modal-overlay">
    <section class="auth-card modal-card">
      <h1>Sign up</h1>
      <p>Step {{ currentStep }} of 2</p>

      <form v-if="currentStep === 1" @submit.prevent="onContinueToStep2" class="stack">
        <input v-model="form.username" placeholder="Username" required />
        <input v-model="form.email" type="email" placeholder="Email" required />
        <input v-model="form.password" type="password" placeholder="Password" required />
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

      <p v-if="errorText">{{ errorText }}</p>
      <div v-if="saving" class="loading-overlay">
        <div class="spinner" />
      </div>
    </section>
  </div>
</template>
