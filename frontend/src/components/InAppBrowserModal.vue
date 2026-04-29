<script setup lang="ts">
import { computed, onUnmounted, ref, watch } from "vue";

const props = defineProps<{
  modelValue: boolean;
  initialUrl: string;
  title?: string;
}>();

const emit = defineEmits<{
  "update:modelValue": [value: boolean];
}>();

const iframeRef = ref<HTMLIFrameElement | null>(null);
const iframeKey = ref(0);
const currentUrl = ref("");
const iframeSrc = ref("");
const historyStack = ref<string[]>([]);
const historyIndex = ref(0);
const shareFeedback = ref("");
let shareFeedbackTimer: ReturnType<typeof setTimeout> | null = null;

function closeModal() {
  emit("update:modelValue", false);
}

function syncCurrentUrlFromFrame(): string {
  const frameWindow = iframeRef.value?.contentWindow;
  if (!frameWindow) {
    return "";
  }
  try {
    const frameLocation = String(frameWindow.location.href || "");
    if (frameLocation) {
      return frameLocation;
    }
  } catch {
    // Cross-origin frame location cannot be read.
  }
  return "";
}

function replaceCurrentUrl(url: string) {
  const normalized = String(url || "").trim();
  if (!normalized) {
    return;
  }
  currentUrl.value = normalized;
  if (!historyStack.value.length) {
    historyStack.value = [normalized];
    historyIndex.value = 0;
    return;
  }
  const nextStack = [...historyStack.value];
  nextStack[historyIndex.value] = normalized;
  historyStack.value = nextStack;
}

function pushUrlToHistory(url: string) {
  const normalized = String(url || "").trim();
  if (!normalized) {
    return;
  }
  const currentHistoryUrl = historyStack.value[historyIndex.value] || "";
  if (currentHistoryUrl === normalized) {
    currentUrl.value = normalized;
    return;
  }
  const nextStack = historyStack.value.slice(0, historyIndex.value + 1);
  nextStack.push(normalized);
  historyStack.value = nextStack;
  historyIndex.value = nextStack.length - 1;
  currentUrl.value = normalized;
}

function onFrameLoad() {
  const frameUrl = syncCurrentUrlFromFrame();
  if (frameUrl) {
    pushUrlToHistory(frameUrl);
    return;
  }
  replaceCurrentUrl(String(iframeSrc.value || ""));
}

function navigateBack() {
  const frameWindow = iframeRef.value?.contentWindow;
  if (!frameWindow) {
    return;
  }
  try {
    history.back();
  } catch {
    // Ignore cross-origin restrictions.
  }
}

function navigateForward() {
  const frameWindow = iframeRef.value?.contentWindow;
  if (!frameWindow) {
    return;
  }
  try {
    history.forward();
  } catch {
    // Ignore cross-origin restrictions.
  }
}

function refreshFrame() {
  const frameWindow = iframeRef.value?.contentWindow;
  if (!frameWindow) {
    return;
  }
  try {
    location.reload();
  } catch {
    // Ignore cross-origin restrictions.
  }
}

async function shareCurrentLink() {
  const url = String(currentUrl.value || props.initialUrl || "").trim();
  if (!url) {
    return;
  }
  if (typeof navigator !== "undefined" && typeof navigator.share === "function") {
    try {
      await navigator.share({ url });
      shareFeedback.value = "Shared";
      resetShareFeedbackLater();
      return;
    } catch {
      // Fall back to clipboard.
    }
  }
  if (typeof navigator !== "undefined" && navigator.clipboard?.writeText) {
    try {
      await navigator.clipboard.writeText(url);
      shareFeedback.value = "Copied link";
      resetShareFeedbackLater();
      return;
    } catch {
      // Ignore clipboard failures.
    }
  }
  shareFeedback.value = "Unable to share";
  resetShareFeedbackLater();
}

function resetShareFeedbackLater() {
  if (shareFeedbackTimer) {
    clearTimeout(shareFeedbackTimer);
  }
  shareFeedbackTimer = setTimeout(() => {
    shareFeedback.value = "";
    shareFeedbackTimer = null;
  }, 1600);
}

function openExternal() {
  const url = String(currentUrl.value || props.initialUrl || "").trim();
  if (!url) {
    return;
  }
  window.open(url, "_blank", "noopener,noreferrer");
}

const urlDisplayText = computed(() => String(currentUrl.value || props.initialUrl || "").trim());

watch(
  () => props.modelValue,
  (isOpen) => {
    document.body.style.overflow = isOpen ? "hidden" : "";
    if (isOpen) {
      const initial = String(props.initialUrl || "").trim();
      currentUrl.value = initial;
      historyStack.value = initial ? [initial] : [];
      historyIndex.value = 0;
      iframeSrc.value = initial;
      shareFeedback.value = "";
      iframeKey.value += 1;
    }
  },
);

watch(
  () => props.initialUrl,
  (nextUrl) => {
    if (!props.modelValue) {
      return;
    }
    const normalized = String(nextUrl || "").trim();
    currentUrl.value = normalized;
    historyStack.value = normalized ? [normalized] : [];
    historyIndex.value = 0;
    iframeSrc.value = normalized;
    shareFeedback.value = "";
    iframeKey.value += 1;
  },
);

onUnmounted(() => {
  if (shareFeedbackTimer) {
    clearTimeout(shareFeedbackTimer);
    shareFeedbackTimer = null;
  }
});
</script>

<template>
  <div v-if="modelValue" class="in-app-browser-overlay" @click.self="closeModal">
    <section class="in-app-browser-modal">
      <header class="in-app-browser-header">
        <button type="button" class="icon-action-button" @click="closeModal" title="Close" aria-label="Close">
          <svg viewBox="0 0 24 24" class="icon"><path d="M20.7457 3.32851C20.3552 2.93798 19.722 2.93798 19.3315 3.32851L12.0371 10.6229L4.74275 3.32851C4.35223 2.93798 3.71906 2.93798 3.32854 3.32851C2.93801 3.71903 2.93801 4.3522 3.32854 4.74272L10.6229 12.0371L3.32856 19.3314C2.93803 19.722 2.93803 20.3551 3.32856 20.7457C3.71908 21.1362 4.35225 21.1362 4.74277 20.7457L12.0371 13.4513L19.3315 20.7457C19.722 21.1362 20.3552 21.1362 20.7457 20.7457C21.1362 20.3551 21.1362 19.722 20.7457 19.3315L13.4513 12.0371L20.7457 4.74272C21.1362 4.3522 21.1362 3.71903 20.7457 3.32851Z" fill="currentColor"/></svg>
        </button>
        <strong class="in-app-browser-url">{{ urlDisplayText }}</strong>
      </header>

      <iframe
        ref="iframeRef"
        :key="`${iframeKey}-${iframeSrc}`"
        :src="iframeSrc"
        class="in-app-browser-frame"
        title="Website viewer"
        @load="onFrameLoad"
      />

      <footer class="in-app-browser-footer">
        <div class="in-app-browser-feedback-row">
          <span class="in-app-browser-feedback">{{ shareFeedback }}</span>
        </div>
        <div class="in-app-browser-controls-row">
          <button type="button" class="icon-action-button" @click="navigateBack" title="Back" aria-label="Back">
            <svg viewBox="0 0 16 16" class="icon"><path d="M5 1H4L0 5L4 9H5V6H11C12.6569 6 14 7.34315 14 9C14 10.6569 12.6569 12 11 12H4V14H11C13.7614 14 16 11.7614 16 9C16 6.23858 13.7614 4 11 4H5V1Z" fill="currentColor"/></svg>
          </button>
          <button type="button" class="icon-action-button" @click="navigateForward" title="Forward" aria-label="Forward">
            <svg viewBox="0 0 16 16" class="icon"><path d="M11 1H12L16 5L12 9H11V6H5C3.34315 6 2 7.34315 2 9C2 10.6569 3.34315 12 5 12H12V14H5C2.23858 14 0 11.7614 0 9C0 6.23858 2.23858 4 5 4H11V1Z" fill="currentColor"/></svg>
          </button>
          <button type="button" class="icon-action-button" @click="refreshFrame" title="Refresh" aria-label="Refresh">
            <svg viewBox="0 0 24 24" class="icon"><path d="M4.06189 13C4.02104 12.6724 4 12.3387 4 12C4 7.58172 7.58172 4 12 4C14.5006 4 16.7332 5.14727 18.2002 6.94416M19.9381 11C19.979 11.3276 20 11.6613 20 12C20 16.4183 16.4183 20 12 20C9.61061 20 7.46589 18.9525 6 17.2916M9 17H6V17.2916M18.2002 4V6.94416M18.2002 6.94416V6.99993L15.2002 7M6 20V17.2916" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg>
          </button>
          <button type="button" class="icon-action-button" @click="shareCurrentLink" title="Share" aria-label="Share">
            <svg viewBox="0 0 24 24" class="icon"><path d="M12 16V4m0 0-4 4m4-4 4 4M5 14v5h14v-5" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/></svg>
          </button>
          <button type="button" class="icon-action-button" @click="openExternal" title="Open external" aria-label="Open external">
            <svg viewBox="0 0 52 52" class="icon"><path d="M48.7,2H29.6C28.8,2,28,2.5,28,3.3v3C28,7.1,28.7,8,29.6,8h7.9c0.9,0,1.4,1,0.7,1.6l-17,17c-0.6,0.6-0.6,1.5,0,2.1l2.1,2.1c0.6,0.6,1.5,0.6,2.1,0l17-17c0.6-0.6,1.6-0.2,1.6,0.7v7.9c0,0.8,0.8,1.7,1.6,1.7h2.9c0.8,0,1.5-0.9,1.5-1.7v-19C50,2.5,49.5,2,48.7,2z" fill="currentColor"/><path d="M36.3,25.5L32.9,29c-0.6,0.6-0.9,1.3-0.9,2.1v11.4c0,0.8-0.7,1.5-1.5,1.5h-21C8.7,44,8,43.3,8,42.5v-21C8,20.7,8.7,20,9.5,20H21c0.8,0,1.6-0.3,2.1-0.9l3.4-3.4c0.6-0.6,0.2-1.7-0.7-1.7H6c-2.2,0-4,1.8-4,4v28c0,2.2,1.8,4,4,4h28c2.2,0,4-1.8,4-4V26.2C38,25.3,36.9,24.9,36.3,25.5z" fill="currentColor"/></svg>
          </button>
        </div>
      </footer>
    </section>
  </div>
</template>

<script lang="ts">
export default {
  name: "InAppBrowserModal",
};
</script>
