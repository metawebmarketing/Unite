<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from "vue";
import { useRouter } from "vue-router";

import { fetchInterestSuggestions, type InterestSuggestion } from "../api/interests";
import { fetchProfile, updateProfile, uploadProfileImage } from "../api/profile";
import { DEFAULT_INTEREST_SUGGESTIONS } from "../constants/interests";
import { useAuthStore } from "../stores/auth";
import { extractFirstHttpUrl } from "../utils/link-input";

const router = useRouter();
const authStore = useAuthStore();
const profile = ref({
  user_id: 0,
  display_name: "",
  bio: "",
  location: "",
  profile_link_url: "",
  receive_notifications: true,
  receive_email_notifications: true,
  receive_push_notifications: true,
  is_private_profile: false,
  require_connection_approval: false,
  is_ai_account: false,
  ai_badge_enabled: false,
  profile_image_url: "",
  date_of_birth: "",
  gender: "",
  gender_self_describe: "",
  zip_code: "",
  country: "",
});
const status = ref("idle");
const isSavingProfile = ref(false);
const isUploadingImage = ref(false);
const pendingSaveField = ref<string | null>(null);
const activeSavingField = ref<string | null>(null);
const interests = ref<string[]>([]);
const interestInput = ref("");
const suggestions = ref<InterestSuggestion[]>([]);
const selectedImage = ref<File | null>(null);
const imagePreviewUrl = ref("");
const imageNaturalWidth = ref(0);
const imageNaturalHeight = ref(0);
const cropXPercent = ref(0.5);
const cropYPercent = ref(0.5);
const cropScale = ref(0.8);
const showCropModal = ref(false);
const imageStatusText = ref("");
const isHydrated = ref(false);
const lastSavedSignature = ref("");
let autosaveTimer: ReturnType<typeof setTimeout> | null = null;
const AUTOSAVE_DELAY_MS = 700;

const isBusy = computed(() => isUploadingImage.value);

const mergedSuggestions = computed(() => {
  const selected = new Set(interests.value);
  const dynamic = suggestions.value.map((item) => item.tag);
  const merged = [...dynamic, ...DEFAULT_INTEREST_SUGGESTIONS];
  const normalized: string[] = [];
  for (const item of merged) {
    const token = item.trim().toLowerCase();
    if (!token || selected.has(token) || normalized.includes(token)) {
      continue;
    }
    normalized.push(token);
  }
  return normalized.slice(0, 10);
});

const cropPreviewStyle = computed(() => {
  const box = 220;
  const scale = 1 / Math.max(cropScale.value, 0.1);
  const translateX = (cropXPercent.value - 0.5) * box * 1.2;
  const translateY = (cropYPercent.value - 0.5) * box * 1.2;
  return {
    transform: `translate(${-translateX}px, ${-translateY}px) scale(${scale})`,
    transformOrigin: "center center",
  };
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
  for (const segment of segments) {
    addInterest(segment);
  }
  interestInput.value = "";
  void refreshSuggestions();
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

async function onImageSelected(event: Event) {
  const target = event.target as HTMLInputElement;
  const file = target.files?.[0] || null;
  selectedImage.value = file;
  if (!file) {
    showCropModal.value = false;
    imageStatusText.value = "";
    return;
  }
  imagePreviewUrl.value = URL.createObjectURL(file);
  const image = new Image();
  image.onload = () => {
    imageNaturalWidth.value = image.width;
    imageNaturalHeight.value = image.height;
    showCropModal.value = true;
    imageStatusText.value = "Adjust crop and save.";
  };
  image.src = imagePreviewUrl.value;
}

function closeCropModal() {
  showCropModal.value = false;
}

function toggleNotificationMaster() {
  profile.value.receive_notifications = !profile.value.receive_notifications;
  if (!profile.value.receive_notifications) {
    profile.value.receive_email_notifications = false;
    profile.value.receive_push_notifications = false;
  }
}

async function onUploadImage() {
  if (!selectedImage.value) {
    imageStatusText.value = "Select an image first.";
    return;
  }
  isUploadingImage.value = true;
  const payload = new FormData();
  payload.append("image", selectedImage.value);
  const minSide = Math.min(imageNaturalWidth.value || 1, imageNaturalHeight.value || 1);
  const cropSizePixels = Math.max(32, Math.floor(minSide * cropScale.value));
  const maxX = Math.max(0, (imageNaturalWidth.value || cropSizePixels) - cropSizePixels);
  const maxY = Math.max(0, (imageNaturalHeight.value || cropSizePixels) - cropSizePixels);
  const cropX = Math.round(maxX * cropXPercent.value);
  const cropY = Math.round(maxY * cropYPercent.value);
  payload.append("crop_x", String(cropX));
  payload.append("crop_y", String(cropY));
  payload.append("crop_size", String(cropSizePixels));
  try {
    const updated = await uploadProfileImage(payload);
    profile.value.profile_image_url = updated.profile_image_url;
    imageStatusText.value = "Profile image updated.";
    showCropModal.value = false;
  } finally {
    isUploadingImage.value = false;
  }
}

function buildSavePayload() {
  return {
    display_name: profile.value.display_name,
    bio: profile.value.bio,
    location: profile.value.location,
    profile_link_url: extractFirstHttpUrl(profile.value.profile_link_url),
    interests: [...interests.value],
    receive_notifications: profile.value.receive_notifications,
    receive_email_notifications: profile.value.receive_email_notifications,
    receive_push_notifications: profile.value.receive_push_notifications,
    is_private_profile: profile.value.is_private_profile,
    require_connection_approval: profile.value.require_connection_approval,
  };
}

function buildChangedPayload(
  currentPayload: ReturnType<typeof buildSavePayload>,
  previousPayload: ReturnType<typeof buildSavePayload> | null,
): Partial<ReturnType<typeof buildSavePayload>> {
  if (!previousPayload) {
    return { ...currentPayload };
  }
  const changed: Partial<ReturnType<typeof buildSavePayload>> = {};
  if (currentPayload.display_name !== previousPayload.display_name) {
    changed.display_name = currentPayload.display_name;
  }
  if (currentPayload.bio !== previousPayload.bio) {
    changed.bio = currentPayload.bio;
  }
  if (currentPayload.location !== previousPayload.location) {
    changed.location = currentPayload.location;
  }
  if (currentPayload.profile_link_url !== previousPayload.profile_link_url) {
    changed.profile_link_url = currentPayload.profile_link_url;
  }
  if (currentPayload.receive_notifications !== previousPayload.receive_notifications) {
    changed.receive_notifications = currentPayload.receive_notifications;
  }
  if (currentPayload.receive_email_notifications !== previousPayload.receive_email_notifications) {
    changed.receive_email_notifications = currentPayload.receive_email_notifications;
  }
  if (currentPayload.receive_push_notifications !== previousPayload.receive_push_notifications) {
    changed.receive_push_notifications = currentPayload.receive_push_notifications;
  }
  if (currentPayload.is_private_profile !== previousPayload.is_private_profile) {
    changed.is_private_profile = currentPayload.is_private_profile;
  }
  if (currentPayload.require_connection_approval !== previousPayload.require_connection_approval) {
    changed.require_connection_approval = currentPayload.require_connection_approval;
  }
  if (JSON.stringify(currentPayload.interests) !== JSON.stringify(previousPayload.interests)) {
    changed.interests = [...currentPayload.interests];
  }
  return changed;
}

const lastSavedPayload = ref<ReturnType<typeof buildSavePayload> | null>(null);

function isFieldSaving(fieldName: string): boolean {
  return Boolean(isSavingProfile.value && activeSavingField.value === fieldName);
}

async function persistProfileChanges() {
  if (!isHydrated.value) {
    return;
  }
  if (isSavingProfile.value || isUploadingImage.value) {
    scheduleAutosave();
    return;
  }
  const payload = buildSavePayload();
  const signature = JSON.stringify(payload);
  if (signature === lastSavedSignature.value) {
    status.value = "saved";
    return;
  }
  const changedPayload = buildChangedPayload(payload, lastSavedPayload.value);
  if (Object.keys(changedPayload).length === 0) {
    lastSavedSignature.value = signature;
    status.value = "saved";
    return;
  }
  status.value = "saving";
  activeSavingField.value = pendingSaveField.value;
  pendingSaveField.value = null;
  isSavingProfile.value = true;
  try {
    await updateProfile(changedPayload);
    lastSavedSignature.value = signature;
    lastSavedPayload.value = payload;
    status.value = "saved";
  } finally {
    isSavingProfile.value = false;
    activeSavingField.value = null;
  }
}

function scheduleAutosave() {
  if (!isHydrated.value) {
    return;
  }
  if (autosaveTimer) {
    clearTimeout(autosaveTimer);
  }
  status.value = "pending";
  autosaveTimer = setTimeout(() => {
    autosaveTimer = null;
    void persistProfileChanges();
  }, AUTOSAVE_DELAY_MS);
}

onMounted(async () => {
  const data = await fetchProfile();
  profile.value = {
    user_id: Number(data.user_id || 0),
    display_name: data.display_name,
    bio: data.bio,
    location: data.location,
    profile_link_url: data.profile_link_url || "",
    receive_notifications: Boolean(data.receive_notifications),
    receive_email_notifications: Boolean(data.receive_email_notifications),
    receive_push_notifications: Boolean(data.receive_push_notifications),
    is_private_profile: Boolean(data.is_private_profile),
    require_connection_approval: Boolean(data.require_connection_approval),
    is_ai_account: data.is_ai_account,
    ai_badge_enabled: data.ai_badge_enabled,
    profile_image_url: data.profile_image_url,
      date_of_birth: String(data.date_of_birth || ""),
      gender: String(data.gender || ""),
      gender_self_describe: String(data.gender_self_describe || ""),
      zip_code: String(data.zip_code || ""),
      country: String(data.country || ""),
  };
  interests.value = data.interests.map((item) => item.trim().toLowerCase()).filter(Boolean);
  const initialPayload = buildSavePayload();
  lastSavedSignature.value = JSON.stringify(initialPayload);
  lastSavedPayload.value = initialPayload;
  isHydrated.value = true;
  void refreshSuggestions();
});

async function goBack() {
  await router.push({ name: "feed" });
}

async function viewPublicProfile() {
  const userId = Number(profile.value.user_id || 0);
  if (!userId) {
    return;
  }
  await router.push({ name: "user-profile", params: { userId } });
}

onUnmounted(() => {
  if (autosaveTimer) {
    clearTimeout(autosaveTimer);
    autosaveTimer = null;
  }
});

watch(
  [
    () => profile.value.display_name,
    () => profile.value.bio,
    () => profile.value.location,
    () => profile.value.profile_link_url,
    () => profile.value.receive_notifications,
    () => profile.value.receive_email_notifications,
    () => profile.value.receive_push_notifications,
    () => profile.value.is_private_profile,
    () => profile.value.require_connection_approval,
  ],
  (newValues, previousValues) => {
    const fieldByIndex = [
      "display_name",
      "bio",
      "location",
      "profile_link_url",
      "receive_notifications",
      "receive_email_notifications",
      "receive_push_notifications",
      "is_private_profile",
      "require_connection_approval",
    ];
    const changedIndex = newValues.findIndex((value, index) => value !== previousValues?.[index]);
    if (changedIndex >= 0) {
      pendingSaveField.value = fieldByIndex[changedIndex] || pendingSaveField.value;
    }
    scheduleAutosave();
  },
);

watch(
  interests,
  () => {
    pendingSaveField.value = "interests";
    scheduleAutosave();
  },
  { deep: true },
);
</script>

<script lang="ts">
export default {
  name: "ProfileView",
};
</script>

<template>
  <main class="profile-detail-page">
    <button class="back-button icon-only-button" type="button" @click="goBack" title="Back" aria-label="Back">
      <svg viewBox="0 0 16 16" class="icon"><path d="M5 1H4L0 5L4 9H5V6H11C12.6569 6 14 7.34315 14 9C14 10.6569 12.6569 12 11 12H4V14H11C13.7614 14 16 11.7614 16 9C16 6.23858 13.7614 4 11 4H5V1Z" fill="currentColor"/></svg>
    </button>
    <section class="feed-item">
      <div class="profile-title-row">
        <h1>Profile</h1>
        <button type="button" class="profile-view-profile-button" @click="viewPublicProfile">View Profile</button>
      </div>
      <p v-if="profile.is_ai_account && profile.ai_badge_enabled" class="ai-badge-row">AI account badge enabled</p>
      <div v-if="authStore.isStaff" class="stack">
        <label class="profile-section-heading">Admin-only demographics</label>
        <input :value="profile.date_of_birth" placeholder="Date of birth" readonly />
        <input :value="profile.gender" placeholder="Gender" readonly />
        <input
          v-if="profile.gender === 'self_describe' && profile.gender_self_describe"
          :value="profile.gender_self_describe"
          placeholder="Gender self describe"
          readonly
        />
        <input :value="profile.zip_code" placeholder="ZIP / postal code" readonly />
        <input :value="profile.country" placeholder="Country" readonly />
      </div>
      <div class="stack">
        <input v-model="profile.display_name" placeholder="Display name" required />
        <div v-if="isFieldSaving('display_name')" class="field-saving-indicator"><span class="spinner" />Saving...</div>
        <input v-model="profile.location" placeholder="Location" />
        <div v-if="isFieldSaving('location')" class="field-saving-indicator"><span class="spinner" />Saving...</div>
        <input v-model="profile.profile_link_url" placeholder="Profile link (optional)" />
        <div v-if="isFieldSaving('profile_link_url')" class="field-saving-indicator"><span class="spinner" />Saving...</div>
        <textarea v-model="profile.bio" placeholder="Bio" rows="4" />
        <div v-if="isFieldSaving('bio')" class="field-saving-indicator"><span class="spinner" />Saving...</div>
        <div class="stack">
          <label class="profile-section-heading">Profile image</label>
          <img
            v-if="profile.profile_image_url"
            :src="profile.profile_image_url"
            alt="Profile image"
            class="profile-image-preview"
          />
          <input type="file" accept="image/*" @change="onImageSelected" />
          <p v-if="imageStatusText">{{ imageStatusText }}</p>
        </div>
        <div class="stack">
          <label class="profile-section-heading">Interests</label>
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
          <div v-if="isFieldSaving('interests')" class="field-saving-indicator"><span class="spinner" />Saving...</div>
        </div>
        <div class="stack settings-panel">
          <label class="profile-section-heading">Settings</label>
          <div class="stack settings-section">
            <h3>Notifications</h3>
            <div class="settings-toggle-row">
              <span>Receive Notifications</span>
              <button
                type="button"
                class="settings-switch"
                :class="{ on: profile.receive_notifications }"
                role="switch"
                :aria-checked="profile.receive_notifications ? 'true' : 'false'"
                @click="toggleNotificationMaster"
              >
                <span class="settings-switch-label">{{ profile.receive_notifications ? "ON" : "OFF" }}</span>
                <span class="settings-switch-knob" />
              </button>
            </div>
            <div v-if="isFieldSaving('receive_notifications')" class="field-saving-indicator"><span class="spinner" />Saving...</div>
            <div class="settings-toggle-row">
              <span>Receive Email Notifications</span>
              <button
                type="button"
                class="settings-switch"
                :class="{ on: profile.receive_email_notifications }"
                role="switch"
                :aria-checked="profile.receive_email_notifications ? 'true' : 'false'"
                :disabled="!profile.receive_notifications"
                @click="profile.receive_email_notifications = !profile.receive_email_notifications"
              >
                <span class="settings-switch-label">{{ profile.receive_email_notifications ? "ON" : "OFF" }}</span>
                <span class="settings-switch-knob" />
              </button>
            </div>
            <div v-if="isFieldSaving('receive_email_notifications')" class="field-saving-indicator"><span class="spinner" />Saving...</div>
            <div class="settings-toggle-row">
              <span>Receive Push Notifications</span>
              <button
                type="button"
                class="settings-switch"
                :class="{ on: profile.receive_push_notifications }"
                role="switch"
                :aria-checked="profile.receive_push_notifications ? 'true' : 'false'"
                :disabled="!profile.receive_notifications"
                @click="profile.receive_push_notifications = !profile.receive_push_notifications"
              >
                <span class="settings-switch-label">{{ profile.receive_push_notifications ? "ON" : "OFF" }}</span>
                <span class="settings-switch-knob" />
              </button>
            </div>
            <div v-if="isFieldSaving('receive_push_notifications')" class="field-saving-indicator"><span class="spinner" />Saving...</div>
          </div>
          <div class="stack settings-section">
            <h3>Privacy</h3>
            <div class="settings-toggle-row">
              <span>Private Profile</span>
              <button
                type="button"
                class="settings-switch"
                :class="{ on: profile.is_private_profile }"
                role="switch"
                :aria-checked="profile.is_private_profile ? 'true' : 'false'"
                @click="profile.is_private_profile = !profile.is_private_profile"
              >
                <span class="settings-switch-label">{{ profile.is_private_profile ? "ON" : "OFF" }}</span>
                <span class="settings-switch-knob" />
              </button>
            </div>
            <div v-if="isFieldSaving('is_private_profile')" class="field-saving-indicator"><span class="spinner" />Saving...</div>
            <div class="settings-toggle-row">
              <span>Approve Connections</span>
              <button
                type="button"
                class="settings-switch"
                :class="{ on: profile.require_connection_approval }"
                role="switch"
                :aria-checked="profile.require_connection_approval ? 'true' : 'false'"
                @click="profile.require_connection_approval = !profile.require_connection_approval"
              >
                <span class="settings-switch-label">{{ profile.require_connection_approval ? "ON" : "OFF" }}</span>
                <span class="settings-switch-knob" />
              </button>
            </div>
            <div v-if="isFieldSaving('require_connection_approval')" class="field-saving-indicator"><span class="spinner" />Saving...</div>
          </div>
        </div>
      </div>
      <div v-if="isBusy" class="loading-overlay">
        <div class="spinner" />
      </div>
    </section>

    <div v-if="showCropModal" class="modal-overlay cropper-overlay" @click.self="closeCropModal">
      <section class="auth-card modal-card">
        <h2>Crop profile image</h2>
        <div class="crop-preview-frame">
          <img :src="imagePreviewUrl" alt="Crop preview" class="crop-preview-image" :style="cropPreviewStyle" />
        </div>
        <div class="stack">
          <label>Horizontal <input v-model.number="cropXPercent" type="range" min="0" max="1" step="0.01" /></label>
          <label>Vertical <input v-model.number="cropYPercent" type="range" min="0" max="1" step="0.01" /></label>
          <label>Crop size <input v-model.number="cropScale" type="range" min="0.35" max="1" step="0.01" /></label>
        </div>
        <div class="modal-actions">
          <button type="button" @click="closeCropModal">Cancel</button>
          <button type="button" @click="onUploadImage">Save crop</button>
        </div>
      </section>
    </div>
  </main>
</template>
