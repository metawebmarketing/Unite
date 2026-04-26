<script setup lang="ts">
import { reactive, ref } from "vue";
import { useRouter } from "vue-router";

import { uploadTheme } from "../api/themes";
import { applyThemeTokens, cacheThemeTokens } from "../theme";

const form = reactive({
  name: "custom_dark",
  version: "v1",
  tokensText: JSON.stringify(
    {
      colors: {
        background: "#0a0c10",
        surface: "#11141c",
        textPrimary: "#ebefff",
        border: "#2f3a56",
      },
      spacing: { sm: 8, md: 16 },
      radius: { md: 14 },
      typography: { base: 16 },
    },
    null,
    2,
  ),
});
const statusText = ref("");
const errorText = ref("");
const isBusy = ref(false);
const router = useRouter();
const props = defineProps<{ embedded?: boolean }>();
const emit = defineEmits<{ close: [] }>();

async function onSubmit() {
  errorText.value = "";
  statusText.value = "Uploading...";
  isBusy.value = true;
  try {
    const payload = {
      name: form.name,
      version: form.version,
      tokens: JSON.parse(form.tokensText) as Record<string, unknown>,
    };
    const activeTheme = await uploadTheme(payload);
    applyThemeTokens(activeTheme.tokens);
    cacheThemeTokens(activeTheme.tokens);
    statusText.value = "Theme uploaded and activated.";
  } catch {
    statusText.value = "";
    errorText.value = "Failed to upload theme. Validate JSON and required token groups.";
  } finally {
    isBusy.value = false;
  }
}

async function onCancel() {
  if (props.embedded) {
    emit("close");
    return;
  }
  await router.push("/");
}
</script>

<script lang="ts">
export default {
  name: "ThemeStudioView",
};
</script>

<template>
  <div class="modal-overlay">
    <section class="auth-card modal-card">
      <h1>Theme Studio</h1>
      <form class="stack" @submit.prevent="onSubmit">
        <input v-model="form.name" placeholder="Theme name" required />
        <input v-model="form.version" placeholder="Version" required />
        <textarea v-model="form.tokensText" rows="14" />
        <div class="modal-actions">
          <button type="button" @click="onCancel">Close</button>
          <button type="submit">Upload theme</button>
        </div>
        <div v-if="isBusy" class="progress-track"><div class="progress-fill progress-indeterminate" /></div>
        <p v-if="statusText">{{ statusText }}</p>
        <p v-if="errorText">{{ errorText }}</p>
      </form>
      <div v-if="isBusy" class="loading-overlay">
        <div class="spinner" />
      </div>
    </section>
  </div>
</template>
