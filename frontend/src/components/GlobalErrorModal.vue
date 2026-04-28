<script setup lang="ts">
import { computed } from "vue";

import { useErrorModalStore } from "../stores/error-modal";

const errorModalStore = useErrorModalStore();
const isOpen = computed(() => errorModalStore.isOpen);
const title = computed(() => errorModalStore.title || "Error");
const message = computed(() => errorModalStore.message);

function closeModal() {
  errorModalStore.closeError();
}
</script>

<template>
  <div v-if="isOpen" class="modal-overlay global-error-overlay" @click.self="closeModal">
    <section class="auth-card modal-card global-error-card">
      <h2>{{ title }}</h2>
      <p>{{ message }}</p>
      <div class="modal-actions">
        <button type="button" @click="closeModal">Close</button>
      </div>
    </section>
  </div>
</template>
