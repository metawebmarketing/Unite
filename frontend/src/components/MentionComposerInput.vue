<script setup lang="ts">
import { onMounted, onUnmounted, ref, watch } from "vue";

import { fetchDMUserSuggestions, type DMUserSuggestion } from "../api/messages";

const props = defineProps<{
  modelValue: string;
  taggedUserIds: number[];
  placeholder?: string;
  required?: boolean;
}>();

const emit = defineEmits<{
  "update:modelValue": [value: string];
  "update:taggedUserIds": [value: number[]];
}>();

const editorRef = ref<HTMLElement | null>(null);
const wrapRef = ref<HTMLElement | null>(null);
const showMentionSuggestionBox = ref(false);
const mentionSuggestions = ref<DMUserSuggestion[]>([]);
const activeTokenRange = ref<Range | null>(null);
const mentionQuery = ref("");
let mentionFetchTimer: ReturnType<typeof setTimeout> | null = null;
let isApplyingExternalValue = false;

function createMentionElement(suggestion: DMUserSuggestion) {
  const element = document.createElement("a");
  element.className = "mention-tag-link";
  element.href = "#";
  element.dataset.userId = String(suggestion.user_id);
  element.dataset.username = String(suggestion.username || "");
  element.textContent = `@${suggestion.username}`;
  element.setAttribute("contenteditable", "false");
  return element;
}

function editorText() {
  if (!editorRef.value) {
    return "";
  }
  return String(editorRef.value.innerText || "")
    .replace(/\u00A0/g, " ")
    .replace(/\r/g, "");
}

function emitCurrentState() {
  const editor = editorRef.value;
  if (!editor) {
    emit("update:modelValue", "");
    emit("update:taggedUserIds", []);
    return;
  }
  const modelValue = editorText();
  const taggedUserIds: number[] = [];
  const mentionNodes = Array.from(editor.querySelectorAll(".mention-tag-link"));
  for (const mentionNode of mentionNodes) {
    const userId = Number((mentionNode as HTMLElement).dataset.userId || 0);
    if (Number.isInteger(userId) && userId > 0 && !taggedUserIds.includes(userId)) {
      taggedUserIds.push(userId);
    }
  }
  emit("update:modelValue", modelValue);
  emit("update:taggedUserIds", taggedUserIds);
}

function setEditorText(value: string) {
  const editor = editorRef.value;
  if (!editor) {
    return;
  }
  isApplyingExternalValue = true;
  editor.innerHTML = "";
  const textNode = document.createTextNode(String(value || ""));
  editor.appendChild(textNode);
  isApplyingExternalValue = false;
}

function closeSuggestionBox() {
  showMentionSuggestionBox.value = false;
  mentionSuggestions.value = [];
  mentionQuery.value = "";
  activeTokenRange.value = null;
}

function textRangeFromCharacterOffsets(root: Node, startOffset: number, endOffset: number): Range | null {
  const range = document.createRange();
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
  let currentOffset = 0;
  let startNode: Node | null = null;
  let endNode: Node | null = null;
  let startNodeOffset = 0;
  let endNodeOffset = 0;
  while (walker.nextNode()) {
    const currentNode = walker.currentNode;
    const nodeText = String(currentNode.nodeValue || "");
    const nextOffset = currentOffset + nodeText.length;
    if (!startNode && startOffset >= currentOffset && startOffset <= nextOffset) {
      startNode = currentNode;
      startNodeOffset = Math.max(0, Math.min(nodeText.length, startOffset - currentOffset));
    }
    if (!endNode && endOffset >= currentOffset && endOffset <= nextOffset) {
      endNode = currentNode;
      endNodeOffset = Math.max(0, Math.min(nodeText.length, endOffset - currentOffset));
    }
    currentOffset = nextOffset;
    if (startNode && endNode) {
      break;
    }
  }
  if (!startNode || !endNode) {
    return null;
  }
  range.setStart(startNode, startNodeOffset);
  range.setEnd(endNode, endNodeOffset);
  return range;
}

function detectActiveMentionToken() {
  const editor = editorRef.value;
  if (!editor) {
    return null;
  }
  const selection = window.getSelection();
  if (!selection || selection.rangeCount === 0) {
    return null;
  }
  const caretRange = selection.getRangeAt(0);
  if (!caretRange.collapsed) {
    return null;
  }
  if (!editor.contains(caretRange.startContainer)) {
    return null;
  }
  const probeRange = caretRange.cloneRange();
  probeRange.selectNodeContents(editor);
  probeRange.setEnd(caretRange.startContainer, caretRange.startOffset);
  const leadingText = String(probeRange.toString() || "");
  const match = leadingText.match(/(^|\s)@([a-zA-Z0-9_]*)$/);
  if (!match) {
    return null;
  }
  const query = String(match[2] || "").trim();
  const tokenStart = leadingText.length - query.length - 1;
  const tokenEnd = leadingText.length;
  const tokenRange = textRangeFromCharacterOffsets(editor, tokenStart, tokenEnd);
  if (!tokenRange) {
    return null;
  }
  return { query, tokenRange };
}

function scheduleSuggestionLookup(query: string) {
  if (mentionFetchTimer) {
    clearTimeout(mentionFetchTimer);
    mentionFetchTimer = null;
  }
  mentionFetchTimer = setTimeout(async () => {
    try {
      mentionSuggestions.value = await fetchDMUserSuggestions(query, 50);
      showMentionSuggestionBox.value = mentionSuggestions.value.length > 0;
    } catch {
      mentionSuggestions.value = [];
      showMentionSuggestionBox.value = false;
    }
  }, 140);
}

function refreshMentionSuggestions() {
  const token = detectActiveMentionToken();
  if (!token) {
    closeSuggestionBox();
    return;
  }
  mentionQuery.value = token.query;
  activeTokenRange.value = token.tokenRange;
  scheduleSuggestionLookup(token.query);
}

function placeCursorAfter(node: Node) {
  const selection = window.getSelection();
  if (!selection) {
    return;
  }
  const range = document.createRange();
  range.setStartAfter(node);
  range.collapse(true);
  selection.removeAllRanges();
  selection.addRange(range);
}

function placeCursorAtTextOffset(node: Text, offset: number) {
  const selection = window.getSelection();
  if (!selection) {
    return;
  }
  const range = document.createRange();
  range.setStart(node, Math.max(0, Math.min(offset, node.length)));
  range.collapse(true);
  selection.removeAllRanges();
  selection.addRange(range);
}

function convertMentionToEditableToken(mentionElement: HTMLElement): Text {
  const tokenText = String(mentionElement.textContent || "").trim();
  const replacement = document.createTextNode(tokenText);
  mentionElement.replaceWith(replacement);
  return replacement;
}

function selectMentionSuggestion(suggestion: DMUserSuggestion) {
  const editor = editorRef.value;
  if (!editor) {
    return;
  }
  if (!activeTokenRange.value) {
    return;
  }
  const mentionElement = createMentionElement(suggestion);
  const spacer = document.createTextNode(" ");
  const tokenRange = activeTokenRange.value;
  tokenRange.deleteContents();
  tokenRange.insertNode(spacer);
  tokenRange.insertNode(mentionElement);
  placeCursorAfter(spacer);
  closeSuggestionBox();
  emitCurrentState();
}

function maybeActivateMentionForReplace(event: MouseEvent) {
  const target = event.target as HTMLElement | null;
  if (!target) {
    return false;
  }
  const mentionElement = target.closest(".mention-tag-link") as HTMLElement | null;
  if (!mentionElement) {
    return false;
  }
  event.preventDefault();
  const replacementToken = convertMentionToEditableToken(mentionElement);
  placeCursorAtTextOffset(replacementToken, replacementToken.length);
  const range = document.createRange();
  range.setStart(replacementToken, 0);
  range.setEnd(replacementToken, replacementToken.length);
  activeTokenRange.value = range;
  mentionQuery.value = String(replacementToken.nodeValue || "").replace(/^@/, "").trim();
  emitCurrentState();
  scheduleSuggestionLookup(mentionQuery.value);
  return true;
}

function onEditorKeydown(event: KeyboardEvent) {
  if (event.key !== "Backspace") {
    return;
  }
  const editor = editorRef.value;
  const selection = window.getSelection();
  if (!editor || !selection || selection.rangeCount === 0) {
    return;
  }
  const range = selection.getRangeAt(0);
  if (!range.collapsed || !editor.contains(range.startContainer)) {
    return;
  }
  let mentionElement: HTMLElement | null = null;
  if (range.startContainer.nodeType === Node.ELEMENT_NODE) {
    const elementNode = range.startContainer as Element;
    const previous = elementNode.childNodes[range.startOffset - 1] as HTMLElement | undefined;
    if (previous && previous.classList?.contains("mention-tag-link")) {
      mentionElement = previous;
    }
  } else if (range.startContainer.nodeType === Node.TEXT_NODE && range.startOffset === 0) {
    const previous = (range.startContainer.previousSibling as HTMLElement | null);
    if (previous && previous.classList?.contains("mention-tag-link")) {
      mentionElement = previous;
    }
  }
  if (!mentionElement) {
    return;
  }
  event.preventDefault();
  const replacementToken = convertMentionToEditableToken(mentionElement);
  const tokenValue = String(replacementToken.nodeValue || "");
  const nextTokenValue = tokenValue.length > 0 ? tokenValue.slice(0, -1) : "";
  replacementToken.nodeValue = nextTokenValue;
  placeCursorAtTextOffset(replacementToken, nextTokenValue.length);
  const tokenRange = document.createRange();
  tokenRange.setStart(replacementToken, 0);
  tokenRange.setEnd(replacementToken, nextTokenValue.length);
  activeTokenRange.value = tokenRange;
  mentionQuery.value = nextTokenValue.replace(/^@/, "").trim();
  emitCurrentState();
  if (nextTokenValue.includes("@")) {
    scheduleSuggestionLookup(mentionQuery.value);
  } else {
    closeSuggestionBox();
  }
}

function onEditorInput() {
  if (isApplyingExternalValue) {
    return;
  }
  emitCurrentState();
  refreshMentionSuggestions();
}

function onEditorClick(event: MouseEvent) {
  if (maybeActivateMentionForReplace(event)) {
    return;
  }
  refreshMentionSuggestions();
}

function onDocumentPointerDown(event: MouseEvent) {
  const targetNode = event.target as Node | null;
  if (!targetNode) {
    return;
  }
  if (wrapRef.value && !wrapRef.value.contains(targetNode)) {
    closeSuggestionBox();
  }
}

onMounted(() => {
  setEditorText(props.modelValue || "");
  document.addEventListener("mousedown", onDocumentPointerDown);
});

onUnmounted(() => {
  document.removeEventListener("mousedown", onDocumentPointerDown);
  if (mentionFetchTimer) {
    clearTimeout(mentionFetchTimer);
    mentionFetchTimer = null;
  }
});

watch(
  () => props.modelValue,
  (nextValue) => {
    if (nextValue === editorText()) {
      return;
    }
    setEditorText(nextValue || "");
  },
);
</script>

<template>
  <div ref="wrapRef" class="message-input-wrap">
    <div
      ref="editorRef"
      class="mention-rich-input"
      :data-placeholder="placeholder || 'Write here...'"
      contenteditable="true"
      role="textbox"
      :aria-required="required ? 'true' : 'false'"
      @input="onEditorInput"
      @click="onEditorClick"
      @keyup="refreshMentionSuggestions"
      @keydown="onEditorKeydown"
    />
    <div v-if="showMentionSuggestionBox" class="suggestion-box mention-suggestion-box">
      <button
        v-for="suggestion in mentionSuggestions"
        :key="`mention-${suggestion.user_id}`"
        type="button"
        class="suggestion-item"
        @click="selectMentionSuggestion(suggestion)"
      >
        <img
          v-if="suggestion.profile_image_url"
          :src="suggestion.profile_image_url"
          alt="Profile"
          class="suggestion-avatar"
        />
        <span class="suggestion-text">
          <strong>@{{ suggestion.username }}</strong>
          <small>{{ suggestion.display_name }}</small>
        </span>
      </button>
    </div>
  </div>
</template>

<script lang="ts">
export default {
  name: "MentionComposerInput",
};
</script>
