<script setup lang="ts">
import { computed } from "vue";

interface MentionSegment {
  kind: "text" | "mention";
  value: string;
  userId: number | null;
}

const props = defineProps<{
  content: string;
  taggedUserIds?: number[];
}>();

const emit = defineEmits<{
  mentionClick: [userId: number];
}>();

const segments = computed<MentionSegment[]>(() => {
  const text = String(props.content || "");
  const taggedUserIds = Array.isArray(props.taggedUserIds) ? props.taggedUserIds : [];
  const result: MentionSegment[] = [];
  const regex = /@([a-zA-Z0-9_]+)/g;
  let cursor = 0;
  let mentionIndex = 0;
  let match = regex.exec(text);
  while (match) {
    const start = Number(match.index || 0);
    const mentionText = String(match[0] || "");
    if (start > cursor) {
      result.push({ kind: "text", value: text.slice(cursor, start), userId: null });
    }
    const mappedUserId = Number(taggedUserIds[mentionIndex] || 0);
    result.push({
      kind: "mention",
      value: mentionText,
      userId: Number.isInteger(mappedUserId) && mappedUserId > 0 ? mappedUserId : null,
    });
    mentionIndex += 1;
    cursor = start + mentionText.length;
    match = regex.exec(text);
  }
  if (cursor < text.length) {
    result.push({ kind: "text", value: text.slice(cursor), userId: null });
  }
  if (!result.length) {
    result.push({ kind: "text", value: "", userId: null });
  }
  return result;
});

function onMentionClick(userId: number | null) {
  if (!userId) {
    return;
  }
  emit("mentionClick", userId);
}
</script>

<template>
  <p class="post-content-link mention-content-wrap">
    <span v-for="(segment, index) in segments" :key="`segment-${index}-${segment.kind}`">
      <span v-if="segment.kind === 'text'">{{ segment.value }}</span>
      <button v-else type="button" class="mention-inline-link" @click.stop="onMentionClick(segment.userId)">
        {{ segment.value }}
      </button>
    </span>
  </p>
</template>

<script lang="ts">
export default {
  name: "MentionTextContent",
};
</script>
