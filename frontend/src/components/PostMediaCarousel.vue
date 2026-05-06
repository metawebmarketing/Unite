<script setup lang="ts">
import Hls from "hls.js";
import { computed, onBeforeUnmount, ref, watch } from "vue";
import type { PostAttachment } from "../api/posts";

const props = defineProps<{
  attachments: PostAttachment[];
}>();

const mediaVideoRef = ref<HTMLVideoElement | null>(null);
const activeIndex = ref(0);
const activeHls = ref<Hls | null>(null);
const generatedPosterByUrl = ref<Record<string, string>>({});
const carouselDirection = ref<"next" | "prev">("next");
const carouselTransitionName = computed(() =>
  carouselDirection.value === "next" ? "post-media-slide-next" : "post-media-slide-prev",
);
let posterGenerationToken = 0;

const visibleAttachments = computed(() => (Array.isArray(props.attachments) ? props.attachments.slice(0, 20) : []));
const activeAttachment = computed(() => visibleAttachments.value[activeIndex.value] || null);
const hasMultipleAttachments = computed(() => visibleAttachments.value.length > 1);
const isActiveVideo = computed(() => activeAttachment.value?.media_type === "video");
const activeVideoStatus = computed(() => String(activeAttachment.value?.processing_status || "ready").toLowerCase());
const canPlayActiveVideo = computed(
  () => isActiveVideo.value && (activeVideoStatus.value === "ready" || activeVideoStatus.value === "processing"),
);
const activeVideoPoster = computed(() => {
  if (!isActiveVideo.value) {
    return undefined;
  }
  const explicitPoster = String(activeAttachment.value?.thumbnail_url || "").trim();
  if (explicitPoster) {
    return explicitPoster;
  }
  const mediaUrl = String(activeAttachment.value?.media_url || "").trim();
  if (!mediaUrl) {
    return undefined;
  }
  return generatedPosterByUrl.value[mediaUrl] || undefined;
});

function teardownHlsPlayer() {
  if (activeHls.value) {
    activeHls.value.destroy();
    activeHls.value = null;
  }
}

function syncHlsPlayer() {
  teardownHlsPlayer();
  const currentAttachment = activeAttachment.value;
  const playerElement = mediaVideoRef.value;
  if (!currentAttachment || currentAttachment.media_type !== "video" || !playerElement || !canPlayActiveVideo.value) {
    return;
  }
  const mediaUrl = String(currentAttachment.media_url || "").trim();
  if (mediaUrl) {
    playerElement.src = mediaUrl;
  }
  const hlsManifestUrl = String(currentAttachment.hls_manifest_url || "").trim();
  if (!hlsManifestUrl) {
    return;
  }
  if (playerElement.canPlayType("application/vnd.apple.mpegurl")) {
    playerElement.src = hlsManifestUrl;
    return;
  }
  if (!Hls.isSupported()) {
    return;
  }
  const player = new Hls({
    enableWorker: true,
    lowLatencyMode: false,
    maxBufferLength: 30,
    maxMaxBufferLength: 60,
    backBufferLength: 30,
  });
  player.on(Hls.Events.ERROR, (_event, data) => {
    if (!data?.fatal) {
      return;
    }
    teardownHlsPlayer();
    if (mediaUrl) {
      playerElement.src = mediaUrl;
      playerElement.load();
    }
  });
  player.loadSource(hlsManifestUrl);
  player.attachMedia(playerElement);
  activeHls.value = player;
}

function showPreviousAttachment() {
  if (!visibleAttachments.value.length) {
    return;
  }
  carouselDirection.value = "prev";
  activeIndex.value =
    activeIndex.value <= 0 ? visibleAttachments.value.length - 1 : Math.max(0, activeIndex.value - 1);
}

function showNextAttachment() {
  if (!visibleAttachments.value.length) {
    return;
  }
  carouselDirection.value = "next";
  activeIndex.value =
    activeIndex.value >= visibleAttachments.value.length - 1 ? 0 : Math.min(visibleAttachments.value.length - 1, activeIndex.value + 1);
}

async function generatePosterFromVideoUrl(videoUrl: string): Promise<string> {
  return await new Promise((resolve) => {
    let hasResolved = false;
    const sourceVideo = document.createElement("video");
    sourceVideo.preload = "metadata";
    sourceVideo.muted = true;
    sourceVideo.playsInline = true;
    sourceVideo.crossOrigin = "anonymous";
    sourceVideo.src = videoUrl;
    const resolveOnce = (value: string) => {
      if (hasResolved) {
        return;
      }
      hasResolved = true;
      resolve(value);
    };
    const captureFrame = () => {
      try {
        const canvas = document.createElement("canvas");
        canvas.width = sourceVideo.videoWidth || 640;
        canvas.height = sourceVideo.videoHeight || 360;
        const context = canvas.getContext("2d");
        if (!context) {
          resolveOnce("");
          return;
        }
        context.drawImage(sourceVideo, 0, 0, canvas.width, canvas.height);
        resolveOnce(canvas.toDataURL("image/jpeg", 0.82));
      } catch {
        resolveOnce("");
      }
    };
    const onFailure = () => resolveOnce("");
    const onLoadedMetadata = () => {
      const duration = Number(sourceVideo.duration || 0);
      const seekTargetSeconds =
        Number.isFinite(duration) && duration > 0
          ? Math.min(Math.max(1.5, duration * 0.25), Math.max(0.15, duration - 0.2))
          : 0.15;
      try {
        sourceVideo.currentTime = seekTargetSeconds;
      } catch {
        // Fallback to current frame if seek fails.
        captureFrame();
      }
    };
    const onSeeked = () => captureFrame();
    const onLoadedData = () => {
      // Fallback path: if seeked has not fired yet.
      captureFrame();
    };

    sourceVideo.onloadedmetadata = onLoadedMetadata;
    sourceVideo.onseeked = onSeeked;
    sourceVideo.onloadeddata = onLoadedData;
    sourceVideo.onerror = onFailure;
    window.setTimeout(() => resolveOnce(""), 15000);
  });
}

async function ensurePosterForActiveVideo() {
  if (!isActiveVideo.value) {
    return;
  }
  const explicitPoster = String(activeAttachment.value?.thumbnail_url || "").trim();
  if (explicitPoster) {
    return;
  }
  const mediaUrl = String(activeAttachment.value?.media_url || "").trim();
  if (!mediaUrl || generatedPosterByUrl.value[mediaUrl]) {
    return;
  }
  const generationId = ++posterGenerationToken;
  const generatedPoster = await generatePosterFromVideoUrl(mediaUrl);
  if (generationId !== posterGenerationToken || !generatedPoster) {
    return;
  }
  generatedPosterByUrl.value = {
    ...generatedPosterByUrl.value,
    [mediaUrl]: generatedPoster,
  };
}

watch(
  () => visibleAttachments.value.length,
  (nextLength) => {
    if (nextLength <= 0) {
      activeIndex.value = 0;
      teardownHlsPlayer();
      return;
    }
    if (activeIndex.value >= nextLength) {
      activeIndex.value = 0;
    }
  },
  { immediate: true },
);

watch(
  activeAttachment,
  () => {
    syncHlsPlayer();
    void ensurePosterForActiveVideo();
  },
  { immediate: true },
);

onBeforeUnmount(() => {
  teardownHlsPlayer();
});
</script>

<template>
  <div v-if="visibleAttachments.length" class="post-media-carousel">
    <div class="post-media-stage">
      <button
        v-if="hasMultipleAttachments"
        type="button"
        class="carousel-nav carousel-nav-prev"
        aria-label="Previous media"
        @click="showPreviousAttachment"
      >
        ‹
      </button>
      <div class="post-media-frame">
        <Transition :name="carouselTransitionName" mode="out-in">
          <img
            v-if="activeAttachment?.media_type === 'image'"
            :key="`image-${activeIndex}-${activeAttachment.media_url}`"
            :src="activeAttachment.media_url"
            alt="Post media"
            class="post-media-element"
          />
          <video
            v-else-if="canPlayActiveVideo"
            :key="`video-${activeIndex}-${activeAttachment?.media_url || ''}-${activeAttachment?.hls_manifest_url || ''}`"
            ref="mediaVideoRef"
            :src="activeAttachment.media_url"
            :poster="activeVideoPoster"
            controls
            playsinline
            preload="metadata"
            class="post-media-element"
          />
          <img
            v-else-if="isActiveVideo && activeVideoPoster"
            :key="`poster-${activeIndex}-${activeAttachment?.media_url || ''}`"
            :src="activeVideoPoster"
            alt="Video thumbnail"
            class="post-media-element"
          />
          <div v-else-if="isActiveVideo" :key="`unavailable-${activeIndex}`" class="post-media-unavailable">
            Video is not ready for playback.
          </div>
        </Transition>
      </div>
      <button
        v-if="hasMultipleAttachments"
        type="button"
        class="carousel-nav carousel-nav-next"
        aria-label="Next media"
        @click="showNextAttachment"
      >
        ›
      </button>
    </div>
    <p v-if="isActiveVideo && activeVideoStatus === 'processing'" class="video-processing-note">
      Video is processing. Playback quality may improve shortly.
    </p>
    <p v-else-if="isActiveVideo && activeVideoStatus === 'failed'" class="video-processing-note">
      Video processing failed. Please retry upload.
    </p>
    <div v-if="hasMultipleAttachments" class="carousel-dots">
      <button
        v-for="(_, index) in visibleAttachments"
        :key="index"
        type="button"
        class="carousel-dot"
        :class="{ active: activeIndex === index }"
        :aria-label="`Go to media ${index + 1}`"
        @click="
          carouselDirection = index >= activeIndex ? 'next' : 'prev';
          activeIndex = index;
        "
      />
    </div>
  </div>
</template>

<style scoped>
.post-media-carousel { width: 100%; }
.post-media-stage { position: relative; width: 100%; display: flex; align-items: center; justify-content: center; }
.post-media-frame { width: 100%; }
.post-media-element { display: block; width: 100%; height: auto; max-height: 70vh; border-radius: 14px; }
.post-media-unavailable { width: 100%; min-height: 220px; display: flex; align-items: center; justify-content: center; border-radius: 14px; opacity: 0.85; }
.carousel-nav { position: absolute; top: 50%; transform: translateY(-50%); border: 0; border-radius: 999px; width: 30px; height: 30px; cursor: pointer; }
.carousel-nav-prev { left: 8px; }
.carousel-nav-next { right: 8px; }
.carousel-dots { display: flex; justify-content: center; gap: 6px; margin-top: 8px; }
.carousel-dot { width: 8px; height: 8px; border-radius: 999px; border: 0; opacity: 0.45; cursor: pointer; }
.carousel-dot.active { opacity: 1; }
.video-processing-note { margin-top: 6px; font-size: 12px; opacity: 0.9; }
.post-media-slide-next-enter-active,
.post-media-slide-next-leave-active,
.post-media-slide-prev-enter-active,
.post-media-slide-prev-leave-active { transition: opacity 240ms ease, transform 240ms ease; }

.post-media-slide-next-enter-from { opacity: 0.2; transform: translateX(26px); }
.post-media-slide-next-leave-to { opacity: 0.2; transform: translateX(-26px); }

.post-media-slide-prev-enter-from { opacity: 0.2; transform: translateX(-26px); }
.post-media-slide-prev-leave-to { opacity: 0.2; transform: translateX(26px); }
</style>
