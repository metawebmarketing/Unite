<script setup lang="ts">
import { reactive, ref } from "vue";

import { requestPasswordReset } from "../api/auth";

const form = reactive({
  email: "",
});
const statusMessage = ref("");
const errorMessage = ref("");

async function onSubmit() {
  errorMessage.value = "";
  statusMessage.value = "";
  try {
    const response = await requestPasswordReset({ email: form.email });
    statusMessage.value = response.message;
  } catch {
    errorMessage.value = "Unable to submit password reset request.";
  }
}
</script>

<template>
  <section class="auth-card">
    <h1>Forgot Password</h1>
    <form @submit.prevent="onSubmit" class="stack">
      <input v-model="form.email" type="email" placeholder="Email" required />
      <button type="submit">Send reset instructions</button>
      <p v-if="statusMessage">{{ statusMessage }}</p>
      <p v-if="errorMessage">{{ errorMessage }}</p>
    </form>
  </section>
</template>
