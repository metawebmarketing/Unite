<script setup lang="ts">
import { defineAsyncComponent, onUnmounted, reactive, ref } from "vue";
import { useRouter } from "vue-router";

import { createPost, uploadPostImage } from "../api/posts";
import { enqueueCreatePost } from "../offline/action-queue";
import { useErrorModalStore } from "../stores/error-modal";

const MentionComposerInput = defineAsyncComponent(async () => {
  const componentModule = await import("../components/MentionComposerInput.vue");
  return (componentModule as { default?: unknown }).default || componentModule;
});

const router = useRouter();
const errorModalStore = useErrorModalStore();
const props = defineProps<{ embedded?: boolean }>();
const emit = defineEmits<{ close: [] }>();
const form = reactive({
  content: "",
  link_url: "",
  interest_tags: "",
});
const isSaving = ref(false);
const taggedUserIds = ref<number[]>([]);
const attachmentInputRef = ref<HTMLInputElement | null>(null);
const isUploadingImage = ref(false);
const attachmentItems = ref<Array<{
  media_type: "image";
  media_url: string;
  preview_url: string;
  is_uploaded: boolean;
}>>([]);
const MAX_IMAGE_UPLOAD_BYTES = 5 * 1024 * 1024;

function revokePreviewUrl(url: string) {
  if (url.startsWith("blob:")) {
    URL.revokeObjectURL(url);
  }
}

function clearAttachmentPreviews() {
  for (const attachment of attachmentItems.value) {
    revokePreviewUrl(String(attachment.preview_url || ""));
  }
  attachmentItems.value = [];
}

function openImagePicker() {
  attachmentInputRef.value?.click();
}

async function onAttachmentFilesSelected(event: Event) {
  const input = event.target as HTMLInputElement | null;
  const files = input?.files ? Array.from(input.files) : [];
  if (!files.length) {
    return;
  }
  if (!navigator.onLine) {
    errorModalStore.showError("Image upload requires an online connection.");
    if (input) {
      input.value = "";
    }
    return;
  }
  isUploadingImage.value = true;
  try {
    const file = files[0];
    if (file && String(file.type || "").toLowerCase().startsWith("image/")) {
      if (Number(file.size || 0) > MAX_IMAGE_UPLOAD_BYTES) {
        errorModalStore.showError("Image is too large. Maximum size is 5 MB.");
        return;
      }
      clearAttachmentPreviews();
      const localPreviewUrl = URL.createObjectURL(file);
      attachmentItems.value = [
        {
          media_type: "image",
          media_url: "",
          preview_url: localPreviewUrl,
          is_uploaded: false,
        },
      ];
      const uploaded = await uploadPostImage(file);
      attachmentItems.value = [
        {
          media_type: "image",
          media_url: uploaded.media_url,
          preview_url: localPreviewUrl,
          is_uploaded: true,
        },
      ];
    }
  } catch {
    clearAttachmentPreviews();
    errorModalStore.showError("Unable to upload image. Please retry.");
  } finally {
    isUploadingImage.value = false;
    if (input) {
      input.value = "";
    }
  }
}

function removeAttachment(index: number) {
  const removed = attachmentItems.value[index];
  if (removed) {
    revokePreviewUrl(String(removed.preview_url || ""));
  }
  attachmentItems.value = attachmentItems.value.filter((_, currentIndex) => currentIndex !== index);
}

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
      tagged_user_ids: taggedUserIds.value,
      attachments: attachmentItems.value.length
        ? attachmentItems.value
            .filter((item) => item.is_uploaded && String(item.media_url || "").trim())
            .map((item) => ({ media_type: item.media_type, media_url: item.media_url }))
        : undefined,
    };
    if (attachmentItems.value.length && !navigator.onLine) {
      errorModalStore.showError("Image attachments require an online connection.");
      return;
    }
    if (attachmentItems.value.length && !payload.attachments?.length) {
      errorModalStore.showError("Please wait for the image upload to finish.");
      return;
    }
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

onUnmounted(() => {
  clearAttachmentPreviews();
});
</script>

<script lang="ts">
export default {
  name: "ComposeView",
};
</script>

<template>
  <div class="modal-overlay" @click.self="onCancel">
    <section class="auth-card modal-card mention-host-card">
      <h1>Compose Post</h1>
      <form @submit.prevent="onSubmit" class="stack">
        <MentionComposerInput
          v-model="form.content"
          :tagged-user-ids="taggedUserIds"
          :required="true"
          placeholder="What's happening?"
          @update:tagged-user-ids="taggedUserIds = $event"
        />
        <div class="composer-attachment-tools">
          <button
            type="button"
            class="icon-action-button"
            title="Add image"
            aria-label="Add image"
            @click="openImagePicker"
          >
            <svg viewBox="0 0 24 24" class="icon">
              <rect x="3" y="5" width="18" height="14" rx="2" fill="none" stroke="currentColor" stroke-width="1.8" />
              <circle cx="9" cy="10" r="1.8" fill="none" stroke="currentColor" stroke-width="1.8" />
              <path d="m5 17 4.5-4.5L13 16l2.5-2.5L19 17" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" />
            </svg>
          </button>
          <input
            ref="attachmentInputRef"
            type="file"
            accept="image/*"
            class="hidden-file-input"
            @change="onAttachmentFilesSelected"
          />
        </div>
        <div v-if="attachmentItems.length" class="post-attachment-grid">
          <div v-for="(attachment, index) in attachmentItems" :key="`${attachment.preview_url}-${index}`" class="post-attachment-card">
            <button type="button" class="post-attachment-remove" @click="removeAttachment(index)">x</button>
            <img :src="attachment.preview_url || attachment.media_url" alt="Attachment preview" />
          </div>
        </div>
        <p v-if="isUploadingImage">Uploading image...</p>
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
