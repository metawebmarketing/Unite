<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { useRouter } from "vue-router";

import { fetchInterestSuggestions, type InterestSuggestion } from "../api/interests";
import { fetchProfile, updateProfile, uploadProfileImage } from "../api/profile";
import { DEFAULT_INTEREST_SUGGESTIONS } from "../constants/interests";

const props = defineProps<{ embedded?: boolean }>();
const emit = defineEmits<{ close: [] }>();
const router = useRouter();
const profile = ref({
  display_name: "",
  bio: "",
  location: "",
  is_ai_account: false,
  ai_badge_enabled: false,
  profile_image_url: "",
});
const status = ref("idle");
const isBusy = ref(false);
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

async function onUploadImage() {
  if (!selectedImage.value) {
    imageStatusText.value = "Select an image first.";
    return;
  }
  isBusy.value = true;
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
    isBusy.value = false;
  }
}

onMounted(async () => {
  const data = await fetchProfile();
  profile.value = {
    display_name: data.display_name,
    bio: data.bio,
    location: data.location,
    is_ai_account: data.is_ai_account,
    ai_badge_enabled: data.ai_badge_enabled,
    profile_image_url: data.profile_image_url,
  };
  interests.value = data.interests.map((item) => item.trim().toLowerCase()).filter(Boolean);
  await refreshSuggestions();
});

async function onSave() {
  status.value = "saving";
  isBusy.value = true;
  try {
    await updateProfile({
      display_name: profile.value.display_name,
      bio: profile.value.bio,
      location: profile.value.location,
      interests: interests.value,
    });
    status.value = "saved";
  } finally {
    isBusy.value = false;
  }
}

async function onClose() {
  if (props.embedded) {
    emit("close");
    return;
  }
  await router.push("/");
}
</script>

<script lang="ts">
export default {
  name: "ProfileView",
};
</script>

<template>
  <div class="modal-overlay" @click.self="onClose">
    <section class="auth-card modal-card">
      <h1>Profile</h1>
      <p v-if="profile.is_ai_account && profile.ai_badge_enabled" class="ai-badge-row">AI account badge enabled</p>
      <form @submit.prevent="onSave" class="stack">
        <input v-model="profile.display_name" placeholder="Display name" required />
        <input v-model="profile.location" placeholder="Location" />
        <textarea v-model="profile.bio" placeholder="Bio" rows="4" />
        <div class="stack">
          <label>Profile image</label>
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
          <label>Interests</label>
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
        </div>
        <div class="modal-actions">
          <button type="button" @click="onClose">Close</button>
          <button type="submit">Save profile</button>
        </div>
        <p v-if="status === 'saved'">Saved.</p>
      </form>
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
  </div>
</template>
