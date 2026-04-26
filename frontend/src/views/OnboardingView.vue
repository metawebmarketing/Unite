<script setup lang="ts">
import { reactive, ref, watch } from "vue";
import { useRouter } from "vue-router";

import { fetchInterestSuggestions, type InterestSuggestion } from "../api/interests";
import { submitOnboardingInterests } from "../api/onboarding";
import { fetchProfile } from "../api/profile";
import { DEFAULT_INTEREST_SUGGESTIONS } from "../constants/interests";

const router = useRouter();
const form = reactive({
  interests: "",
  location: "",
});
const errorText = ref("");
const isBusy = ref(false);
const suggestions = ref<InterestSuggestion[]>([]);
const suggestionsLoading = ref(false);
const chips = ref<string[]>([]);

function parseSelectedInterests(): string[] {
  return chips.value;
}

function buildQueryHint(): string {
  const rawItems = form.interests.split(",");
  if (!rawItems.length) {
    return "";
  }
  return rawItems[rawItems.length - 1]?.trim().toLowerCase() || "";
}

async function refreshSuggestions() {
  suggestionsLoading.value = true;
  try {
    suggestions.value = await fetchInterestSuggestions(parseSelectedInterests(), buildQueryHint(), 8);
  } catch {
    suggestions.value = [];
  } finally {
    suggestionsLoading.value = false;
  }
}

function addSuggestion(tag: string) {
  const normalized = tag.trim().toLowerCase();
  if (!normalized || chips.value.includes(normalized)) {
    return;
  }
  chips.value.push(normalized);
}

function removeChip(tag: string) {
  chips.value = chips.value.filter((item) => item !== tag);
}

function commitInterestInput() {
  const values = form.interests.split(",");
  for (const value of values) {
    addSuggestion(value);
  }
  form.interests = "";
}

function onInterestKeydown(event: KeyboardEvent) {
  if (event.key === "," || event.key === "Enter") {
    event.preventDefault();
    commitInterestInput();
  }
}

function defaultSuggestions(): string[] {
  const selected = new Set(chips.value);
  return DEFAULT_INTEREST_SUGGESTIONS.filter((item) => !selected.has(item));
}

async function onSubmit() {
  commitInterestInput();
  const tags = chips.value;
  if (tags.length < 5) {
    errorText.value = "Add at least 5 interests.";
    return;
  }
  errorText.value = "";
  isBusy.value = true;
  try {
    await submitOnboardingInterests({ interests: tags, location: form.location || undefined });
    try {
      const profile = await fetchProfile();
      if (profile.algorithm_profile_status === "ready") {
        await router.push("/");
        return;
      }
    } catch {
      // Fall through to progress screen.
    }
    await router.push("/profile-generation?next=/");
  } finally {
    isBusy.value = false;
  }
}

watch(
  () => form.interests,
  async () => {
    await refreshSuggestions();
  },
  { immediate: true },
);
</script>

<template>
  <section class="auth-card">
    <h1>Onboarding</h1>
    <form class="stack" @submit.prevent="onSubmit">
      <input v-model="form.location" placeholder="Location" />
      <input
        v-model="form.interests"
        placeholder="At least 5 interests (comma separated)"
        @keydown="onInterestKeydown"
        @blur="commitInterestInput"
      />
      <div class="onboarding-suggestions">
        <h3>Suggested interests</h3>
        <p v-if="suggestionsLoading">Loading suggestions...</p>
        <div v-else class="suggestion-list">
          <button
            v-for="suggestion in [...suggestions.map((item) => item.tag), ...defaultSuggestions()]"
            :key="suggestion"
            type="button"
            class="suggestion-chip"
            @click="addSuggestion(suggestion)"
          >
            #{{ suggestion }}
          </button>
        </div>
      </div>
      <div class="chip-row">
        <span v-for="chip in chips" :key="chip" class="interest-chip">
          {{ chip }}
          <button type="button" class="chip-remove" @click="removeChip(chip)">x</button>
        </span>
      </div>
      <p v-if="errorText">{{ errorText }}</p>
      <button type="submit">Save onboarding</button>
      <div v-if="isBusy" class="progress-track"><div class="progress-fill progress-indeterminate" /></div>
    </form>
    <div v-if="isBusy" class="loading-overlay">
      <div class="spinner" />
    </div>
  </section>
</template>
