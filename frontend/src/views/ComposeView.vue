<script setup lang="ts">
import { reactive, ref } from "vue";
import { useRouter } from "vue-router";

import { createPost } from "../api/posts";
import { enqueueCreatePost } from "../offline/action-queue";

const router = useRouter();
const props = defineProps<{ embedded?: boolean }>();
const emit = defineEmits<{ close: [] }>();
const form = reactive({
  content: "",
  link_url: "",
  interest_tags: "",
});
const isSaving = ref(false);

async function onSubmit() {
  isSaving.value = true;
  try {
    const payload = {
      content: form.content,
      link_url: form.link_url || undefined,
      interest_tags: form.interest_tags
        .split(",")
        .map((item) => item.trim())
        .filter(Boolean),
    };
    if (!navigator.onLine) {
      await enqueueCreatePost(payload);
    } else {
      await createPost(payload);
    }
    if (props.embedded) {
      emit("close");
    } else {
      await router.push("/");
    }
  } finally {
    isSaving.value = false;
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
  name: "ComposeView",
};
</script>

<template>
  <div class="modal-overlay">
    <section class="auth-card modal-card">
      <h1>Compose Post</h1>
      <form @submit.prevent="onSubmit" class="stack">
        <textarea v-model="form.content" placeholder="What's happening?" rows="5" required />
        <input v-model="form.link_url" placeholder="Optional link URL" />
        <input v-model="form.interest_tags" placeholder="Interest tags (comma separated)" />
        <div class="modal-actions">
          <button type="button" @click="onCancel">Cancel</button>
          <button type="submit" :disabled="isSaving">{{ isSaving ? "Posting..." : "Post" }}</button>
        </div>
        <div v-if="isSaving" class="progress-track"><div class="progress-fill progress-indeterminate" /></div>
      </form>
      <div v-if="isSaving" class="loading-overlay">
        <div class="spinner" />
      </div>
    </section>
  </div>
</template>
