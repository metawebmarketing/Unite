<script setup lang="ts">
import { defineAsyncComponent, onUnmounted, reactive, ref } from "vue";
import { useRouter } from "vue-router";

import { createPost, uploadPostImage } from "../api/posts";
import { enqueueCreatePost } from "../offline/action-queue";
import { useErrorModalStore } from "../stores/error-modal";
import { extractFirstHttpUrl } from "../utils/link-input";

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
      link_url: extractFirstHttpUrl(form.link_url) || undefined,
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
      <h1>Start Conversation</h1>
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
            <svg viewBox="0 0 24 24" class="icon"><path fill-rule="evenodd" clip-rule="evenodd" d="M23 4C23 2.34315 21.6569 1 20 1H4C2.34315 1 1 2.34315 1 4V20C1 21.6569 2.34315 23 4 23H20C21.6569 23 23 21.6569 23 20V4ZM21 4C21 3.44772 20.5523 3 20 3H4C3.44772 3 3 3.44772 3 4V20C3 20.5523 3.44772 21 4 21H20C20.5523 21 21 20.5523 21 20V4Z" fill="currentColor"/><path d="M4.80665 17.5211L9.1221 9.60947C9.50112 8.91461 10.4989 8.91461 10.8779 9.60947L14.0465 15.4186L15.1318 13.5194C15.5157 12.8476 16.4843 12.8476 16.8682 13.5194L19.1451 17.5039C19.526 18.1705 19.0446 19 18.2768 19H5.68454C4.92548 19 4.44317 18.1875 4.80665 17.5211Z" fill="currentColor"/><path d="M18 8C18 9.10457 17.1046 10 16 10C14.8954 10 14 9.10457 14 8C14 6.89543 14.8954 6 16 6C17.1046 6 18 6.89543 18 8Z" fill="currentColor"/></svg>
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
          <button type="submit" :disabled="isSaving">{{ isSaving ? "Publishing..." : "Publish Conversation" }}</button>
        </div>
        <div v-if="isSaving" class="progress-track"><div class="progress-fill progress-indeterminate" /></div>
      </form>
      <div v-if="isSaving" class="loading-overlay">
        <div class="spinner" />
      </div>
    </section>
  </div>
</template>
