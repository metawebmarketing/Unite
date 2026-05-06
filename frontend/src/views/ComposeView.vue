<script setup lang="ts">
import { computed, defineAsyncComponent, onUnmounted, reactive, ref, watch } from "vue";
import { useRouter } from "vue-router";

import { createPost, uploadPostImage, uploadPostVideo } from "../api/posts";
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
const isUploadingMedia = ref(false);
const attachmentItems = ref<Array<{
  media_type: "image" | "video";
  media_url: string;
  preview_url: string;
  preview_poster_url?: string;
  has_verified_thumbnail?: boolean;
  is_uploaded: boolean;
  processing_status?: string;
  thumbnail_url?: string;
  hls_manifest_url?: string;
  media_bytes?: number;
}>>([]);
const MAX_IMAGE_UPLOAD_BYTES = 5 * 1024 * 1024;
const MAX_VIDEO_UPLOAD_BYTES = 1024 * 1024 * 1024;
const composeCarouselIndex = ref(0);
const hasMultipleAttachments = computed(() => attachmentItems.value.length > 1);
const activeComposeAttachment = computed(() => attachmentItems.value[composeCarouselIndex.value] || null);
const composeCarouselDirection = ref<"next" | "prev">("next");
const composeCarouselTransitionName = computed(() =>
  composeCarouselDirection.value === "next" ? "compose-media-slide-next" : "compose-media-slide-prev",
);

function resolveApiErrorMessage(error: unknown, fallback: string): string {
  const detail = String((error as { response?: { data?: { detail?: string } } })?.response?.data?.detail || "").trim();
  return detail || fallback;
}

function revokePreviewUrl(url: string) {
  if (url.startsWith("blob:")) {
    URL.revokeObjectURL(url);
  }
}

function clearAttachmentPreviews() {
  for (const attachment of attachmentItems.value) {
    revokePreviewUrl(String(attachment.preview_url || ""));
    revokePreviewUrl(String(attachment.preview_poster_url || ""));
  }
  attachmentItems.value = [];
}

function openImagePicker() {
  attachmentInputRef.value?.click();
}

async function createVideoPosterUrl(file: File): Promise<string> {
  const objectUrl = URL.createObjectURL(file);
  return await new Promise((resolve) => {
    const QUICK_FALLBACK_MS = 3500;
    let hasResolved = false;
    const video = document.createElement("video");
    video.preload = "metadata";
    video.muted = true;
    video.playsInline = true;
    video.src = objectUrl;
    const resolveOnce = (value: string) => {
      if (hasResolved) {
        return;
      }
      hasResolved = true;
      URL.revokeObjectURL(objectUrl);
      resolve(value);
    };
    const isFrameUsable = (canvas: HTMLCanvasElement): boolean => {
      try {
        const context = canvas.getContext("2d");
        if (!context) {
          return false;
        }
        const width = canvas.width;
        const height = canvas.height;
        if (width <= 0 || height <= 0) {
          return false;
        }
        const sampleWidth = Math.min(64, width);
        const sampleHeight = Math.min(64, height);
        const offsetX = Math.max(0, Math.floor((width - sampleWidth) / 2));
        const offsetY = Math.max(0, Math.floor((height - sampleHeight) / 2));
        const imageData = context.getImageData(offsetX, offsetY, sampleWidth, sampleHeight).data;
        let totalLuma = 0;
        let sampledPixels = 0;
        for (let index = 0; index < imageData.length; index += 16) {
          const red = imageData[index] || 0;
          const green = imageData[index + 1] || 0;
          const blue = imageData[index + 2] || 0;
          totalLuma += 0.2126 * red + 0.7152 * green + 0.0722 * blue;
          sampledPixels += 1;
        }
        if (!sampledPixels) {
          return false;
        }
        const averageLuma = totalLuma / sampledPixels;
        return averageLuma >= 18;
      } catch {
        return false;
      }
    };
    const captureFrame = (enforceBrightness = true) => {
      try {
        if (!video.videoWidth || !video.videoHeight) {
          return "";
        }
        const canvas = document.createElement("canvas");
        canvas.width = video.videoWidth || 640;
        canvas.height = video.videoHeight || 360;
        const context = canvas.getContext("2d");
        if (!context) {
          return "";
        }
        context.drawImage(video, 0, 0, canvas.width, canvas.height);
        if (enforceBrightness && !isFrameUsable(canvas)) {
          return "";
        }
        return canvas.toDataURL("image/jpeg", 0.82);
      } catch {
        return "";
      }
    };
    const durationToTargets = (durationSeconds: number) => {
      const duration = Number(durationSeconds || 0);
      if (!Number.isFinite(duration) || duration <= 0) {
        return [0.15, 0.35, 0.75];
      }
      const nearStart = Math.min(0.35, Math.max(0.1, duration * 0.05));
      const quarter = Math.min(duration - 0.1, Math.max(0.15, duration * 0.25));
      const middle = Math.min(duration - 0.1, Math.max(0.2, duration * 0.5));
      const threeQuarter = Math.min(duration - 0.1, Math.max(0.25, duration * 0.75));
      const nearEnd = Math.max(0.15, duration - 0.4);
      return Array.from(
        new Set([nearStart, quarter, middle, threeQuarter, nearEnd].filter((item) => Number.isFinite(item) && item >= 0)),
      );
    };
    const tryCaptureAtTargets = (targets: number[], index = 0) => {
      if (index >= targets.length) {
        resolveOnce("");
        return;
      }
      const target = targets[index];
      let settled = false;
      const cleanup = () => {
        video.onseeked = null;
        video.onloadeddata = null;
        video.onerror = null;
      };
      const onFrameReady = () => {
        if (settled) {
          return;
        }
        settled = true;
        cleanup();
        const captured = captureFrame();
        if (captured) {
          resolveOnce(captured);
          return;
        }
        tryCaptureAtTargets(targets, index + 1);
      };
      video.onseeked = onFrameReady;
      video.onloadeddata = onFrameReady;
      video.onerror = () => {
        if (settled) {
          return;
        }
        settled = true;
        cleanup();
        tryCaptureAtTargets(targets, index + 1);
      };
      try {
        video.currentTime = target;
      } catch {
        onFrameReady();
      }
      window.setTimeout(() => {
        if (settled) {
          return;
        }
        settled = true;
        cleanup();
        tryCaptureAtTargets(targets, index + 1);
      }, 1800);
    };
    video.onloadedmetadata = () => {
      const durationSeconds = Number(video.duration || 0);
      const targets = durationToTargets(durationSeconds);
      const fallbackTarget =
        Number.isFinite(durationSeconds) && durationSeconds > 0
          ? Math.min(durationSeconds - 0.1, Math.max(0.15, durationSeconds * 0.25))
          : 0.25;
      tryCaptureAtTargets(targets);
      window.setTimeout(() => {
        if (hasResolved) {
          return;
        }
        let settled = false;
        const cleanup = () => {
          video.onseeked = null;
          video.onloadeddata = null;
          video.onerror = null;
        };
        const onFrameReady = () => {
          if (settled || hasResolved) {
            return;
          }
          settled = true;
          cleanup();
          const captured = captureFrame(false);
          if (captured) {
            resolveOnce(captured);
          }
        };
        video.onseeked = onFrameReady;
        video.onloadeddata = onFrameReady;
        video.onerror = () => {
          if (settled || hasResolved) {
            return;
          }
          settled = true;
          cleanup();
        };
        try {
          video.currentTime = fallbackTarget;
        } catch {
          onFrameReady();
        }
      }, QUICK_FALLBACK_MS);
    };
    video.onerror = () => resolveOnce("");
    video.load();
    window.setTimeout(() => resolveOnce(""), 15000);
  });
}

function resolveAttachmentPoster(attachment: {
  preview_url: string;
  media_url: string;
  preview_poster_url?: string;
  thumbnail_url?: string;
}): string | undefined {
  const localPoster = String(attachment.preview_poster_url || "").trim();
  if (localPoster) {
    return localPoster;
  }
  const remotePoster = String(attachment.thumbnail_url || "").trim();
  return remotePoster || undefined;
}

function resolveAttachmentPreviewImage(attachment: {
  media_type: "image" | "video";
  preview_url: string;
  media_url: string;
  preview_poster_url?: string;
  thumbnail_url?: string;
}): string {
  if (attachment.media_type === "image") {
    return String(attachment.preview_url || attachment.media_url || "");
  }
  return String(resolveAttachmentPoster(attachment) || "");
}

function isUploadedVideo(attachment: {
  media_type: "image" | "video";
  is_uploaded: boolean;
  preview_url: string;
  media_url: string;
  has_verified_thumbnail?: boolean;
  preview_poster_url?: string;
  thumbnail_url?: string;
}): boolean {
  return (
    attachment.media_type === "video" &&
    attachment.is_uploaded &&
    Boolean(attachment.has_verified_thumbnail) &&
    Boolean(String(resolveAttachmentPoster(attachment) || "").trim()) &&
    Boolean(String(attachment.media_url || "").trim())
  );
}

async function canLoadImage(url: string): Promise<boolean> {
  const token = String(url || "").trim();
  if (!token) {
    return false;
  }
  return await new Promise((resolve) => {
    const image = new Image();
    let resolved = false;
    const settle = (value: boolean) => {
      if (resolved) {
        return;
      }
      resolved = true;
      resolve(value);
    };
    image.onload = () => settle(true);
    image.onerror = () => settle(false);
    image.src = `${token}${token.includes("?") ? "&" : "?"}thumb_probe=${Date.now()}`;
    window.setTimeout(() => settle(false), 1500);
  });
}

async function waitForRemoteThumbnail(url: string, timeoutMs = 12000): Promise<boolean> {
  const startedAt = Date.now();
  while (Date.now() - startedAt < timeoutMs) {
    const ready = await canLoadImage(url);
    if (ready) {
      return true;
    }
    await new Promise((resolve) => window.setTimeout(resolve, 900));
  }
  return false;
}

function showPreviousAttachment() {
  if (!attachmentItems.value.length) {
    return;
  }
  composeCarouselDirection.value = "prev";
  composeCarouselIndex.value =
    composeCarouselIndex.value <= 0 ? attachmentItems.value.length - 1 : Math.max(0, composeCarouselIndex.value - 1);
}

function showNextAttachment() {
  if (!attachmentItems.value.length) {
    return;
  }
  composeCarouselDirection.value = "next";
  composeCarouselIndex.value =
    composeCarouselIndex.value >= attachmentItems.value.length - 1 ? 0 : Math.min(attachmentItems.value.length - 1, composeCarouselIndex.value + 1);
}

async function onAttachmentFilesSelected(event: Event) {
  const input = event.target as HTMLInputElement | null;
  const files = input?.files ? Array.from(input.files) : [];
  if (!files.length) {
    return;
  }
  if (!navigator.onLine) {
    errorModalStore.showError("Media upload requires an online connection.");
    if (input) {
      input.value = "";
    }
    return;
  }
  isUploadingMedia.value = true;
  try {
    const remainingSlots = Math.max(0, 20 - attachmentItems.value.length);
    if (!remainingSlots) {
      errorModalStore.showError("A post can include up to 20 media attachments.");
      return;
    }
    const selectedFiles = files.slice(0, remainingSlots);
    if (selectedFiles.length < files.length) {
      errorModalStore.showError("Only the first 20 media files were selected.");
    }
    for (const file of selectedFiles) {
      const fileType = String(file.type || "").toLowerCase();
      if (fileType.startsWith("image/")) {
        if (Number(file.size || 0) > MAX_IMAGE_UPLOAD_BYTES) {
          errorModalStore.showError("Image is too large. Maximum size is 5 MB.");
          continue;
        }
        const localPreviewUrl = URL.createObjectURL(file);
        attachmentItems.value = [
          ...attachmentItems.value,
          {
            media_type: "image",
            media_url: "",
            preview_url: localPreviewUrl,
            is_uploaded: false,
          },
        ];
        const insertedIndex = attachmentItems.value.length - 1;
        composeCarouselDirection.value = "next";
        composeCarouselIndex.value = insertedIndex;
        try {
          const uploaded = await uploadPostImage(file);
          attachmentItems.value[insertedIndex] = {
            ...attachmentItems.value[insertedIndex],
            media_url: uploaded.media_url,
            is_uploaded: true,
            processing_status: "ready",
          };
        } catch (error) {
          revokePreviewUrl(localPreviewUrl);
          attachmentItems.value = attachmentItems.value.filter((_, idx) => idx !== insertedIndex);
          errorModalStore.showError(resolveApiErrorMessage(error, "Unable to upload media. Please retry."));
        }
        continue;
      }
      if (fileType.startsWith("video/")) {
        if (Number(file.size || 0) > MAX_VIDEO_UPLOAD_BYTES) {
          errorModalStore.showError("Video is too large. Maximum size is 1 GB.");
          continue;
        }
        const localPreviewUrl = URL.createObjectURL(file);
        const localPosterUrl = await createVideoPosterUrl(file);
        attachmentItems.value = [
          ...attachmentItems.value,
          {
            media_type: "video",
            media_url: "",
            preview_url: localPreviewUrl,
            preview_poster_url: localPosterUrl,
            has_verified_thumbnail: Boolean(localPosterUrl),
            is_uploaded: false,
            processing_status: "processing",
          },
        ];
        const insertedIndex = attachmentItems.value.length - 1;
        composeCarouselDirection.value = "next";
        composeCarouselIndex.value = insertedIndex;
        try {
          const uploaded = await uploadPostVideo(file);
          attachmentItems.value[insertedIndex] = {
            ...attachmentItems.value[insertedIndex],
            media_url: uploaded.media_url,
            is_uploaded: true,
            processing_status: uploaded.processing_status || "processing",
            thumbnail_url: uploaded.thumbnail_url || "",
            hls_manifest_url: uploaded.hls_manifest_url || "",
            media_bytes: Number(uploaded.media_bytes || 0),
          };
          const remoteThumbnailUrl = String(uploaded.thumbnail_url || "").trim();
          if (!attachmentItems.value[insertedIndex]?.has_verified_thumbnail && remoteThumbnailUrl) {
            const remoteReady = await waitForRemoteThumbnail(remoteThumbnailUrl);
            if (remoteReady && attachmentItems.value[insertedIndex]) {
              attachmentItems.value[insertedIndex] = {
                ...attachmentItems.value[insertedIndex],
                has_verified_thumbnail: true,
                preview_poster_url: remoteThumbnailUrl,
              };
            }
          }
        } catch (error) {
          revokePreviewUrl(localPreviewUrl);
          revokePreviewUrl(localPosterUrl);
          attachmentItems.value = attachmentItems.value.filter((_, idx) => idx !== insertedIndex);
          errorModalStore.showError(resolveApiErrorMessage(error, "Unable to upload media. Please retry."));
        }
        continue;
      }
      errorModalStore.showError("Unsupported file type. Use an image or video.");
    }
  } catch (error) {
    errorModalStore.showError(resolveApiErrorMessage(error, "Unable to upload media. Please retry."));
  } finally {
    isUploadingMedia.value = false;
    if (input) {
      input.value = "";
    }
  }
}

function removeAttachment(index: number) {
  const removed = attachmentItems.value[index];
  if (removed) {
    revokePreviewUrl(String(removed.preview_url || ""));
    revokePreviewUrl(String(removed.preview_poster_url || ""));
  }
  attachmentItems.value = attachmentItems.value.filter((_, currentIndex) => currentIndex !== index);
}

watch(
  () => attachmentItems.value.length,
  (nextLength) => {
    if (nextLength <= 0) {
      composeCarouselIndex.value = 0;
      return;
    }
    if (composeCarouselIndex.value >= nextLength) {
      composeCarouselIndex.value = nextLength - 1;
    }
  },
  { immediate: true },
);

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
      errorModalStore.showError("Media attachments require an online connection.");
      return;
    }
    if (attachmentItems.value.length && !payload.attachments?.length) {
      errorModalStore.showError("Please wait for the media upload to finish.");
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
  <div class="modal-overlay compose-modal-overlay" @click.self="onCancel">
    <section class="auth-card modal-card mention-host-card compose-modal-card">
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
            aria-label="Add media"
            @click="openImagePicker"
          >
            <svg viewBox="0 0 24 24" class="icon"><path fill-rule="evenodd" clip-rule="evenodd" d="M23 4C23 2.34315 21.6569 1 20 1H4C2.34315 1 1 2.34315 1 4V20C1 21.6569 2.34315 23 4 23H20C21.6569 23 23 21.6569 23 20V4ZM21 4C21 3.44772 20.5523 3 20 3H4C3.44772 3 3 3.44772 3 4V20C3 20.5523 3.44772 21 4 21H20C20.5523 21 21 20.5523 21 20V4Z" fill="currentColor"/><path d="M4.80665 17.5211L9.1221 9.60947C9.50112 8.91461 10.4989 8.91461 10.8779 9.60947L14.0465 15.4186L15.1318 13.5194C15.5157 12.8476 16.4843 12.8476 16.8682 13.5194L19.1451 17.5039C19.526 18.1705 19.0446 19 18.2768 19H5.68454C4.92548 19 4.44317 18.1875 4.80665 17.5211Z" fill="currentColor"/><path d="M18 8C18 9.10457 17.1046 10 16 10C14.8954 10 14 9.10457 14 8C14 6.89543 14.8954 6 16 6C17.1046 6 18 6.89543 18 8Z" fill="currentColor"/></svg>
          </button>
          <input
            ref="attachmentInputRef"
            type="file"
            accept="image/*,video/*"
            multiple
            class="hidden-file-input"
            @change="onAttachmentFilesSelected"
          />
        </div>
        <div v-if="attachmentItems.length && !hasMultipleAttachments" class="post-attachment-grid">
          <div v-for="(attachment, index) in attachmentItems" :key="`${attachment.preview_url}-${index}`" class="post-attachment-card">
            <button type="button" class="post-attachment-remove" @click="removeAttachment(index)">x</button>
            <img
              v-if="attachment.media_type === 'image'"
              :src="attachment.preview_url || attachment.media_url"
              alt="Attachment preview"
            />
            <video
              v-else-if="isUploadedVideo(attachment)"
              :src="attachment.media_url"
              :poster="resolveAttachmentPoster(attachment)"
              controls
              playsinline
              preload="metadata"
            />
            <img
              v-else-if="resolveAttachmentPreviewImage(attachment)"
              :src="resolveAttachmentPreviewImage(attachment)"
              alt="Video thumbnail preview"
            />
            <div v-else class="post-media-unavailable">Generating thumbnail preview...</div>
          </div>
        </div>
        <div v-else-if="attachmentItems.length && hasMultipleAttachments" class="compose-attachment-carousel">
          <button
            type="button"
            class="carousel-nav carousel-nav-prev"
            aria-label="Previous attachment"
            @click="showPreviousAttachment"
          >
            ‹
          </button>
          <Transition :name="composeCarouselTransitionName" mode="out-in">
            <div
              v-if="activeComposeAttachment"
              :key="`${activeComposeAttachment.preview_url || activeComposeAttachment.media_url}-${composeCarouselIndex}`"
              class="post-attachment-card compose-active-attachment"
            >
              <button type="button" class="post-attachment-remove" @click="removeAttachment(composeCarouselIndex)">x</button>
              <img
                v-if="activeComposeAttachment.media_type === 'image'"
                :src="activeComposeAttachment.preview_url || activeComposeAttachment.media_url"
                alt="Attachment preview"
              />
              <video
                v-else-if="isUploadedVideo(activeComposeAttachment)"
                :src="activeComposeAttachment.media_url"
                :poster="resolveAttachmentPoster(activeComposeAttachment)"
                controls
                playsinline
                preload="metadata"
              />
              <img
                v-else-if="resolveAttachmentPreviewImage(activeComposeAttachment)"
                :src="resolveAttachmentPreviewImage(activeComposeAttachment)"
                alt="Video thumbnail preview"
              />
              <div v-else class="post-media-unavailable">Generating thumbnail preview...</div>
            </div>
          </Transition>
          <button
            type="button"
            class="carousel-nav carousel-nav-next"
            aria-label="Next attachment"
            @click="showNextAttachment"
          >
            ›
          </button>
          <div class="carousel-dots">
            <button
              v-for="(attachment, index) in attachmentItems"
              :key="`compose-dot-${attachment.preview_url}-${index}`"
              type="button"
              class="carousel-dot"
              :class="{ active: index === composeCarouselIndex }"
              :aria-label="`Go to attachment ${index + 1}`"
              @click="
                composeCarouselDirection = index >= composeCarouselIndex ? 'next' : 'prev';
                composeCarouselIndex = index;
              "
            />
          </div>
        </div>
        <p v-if="isUploadingMedia" class="inline-upload-status">
          <span class="inline-spinner" />
          <span>Uploading media...</span>
        </p>
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
