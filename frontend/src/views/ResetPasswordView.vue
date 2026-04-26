<script setup lang="ts">
import { reactive, ref } from "vue";
import { useRoute, useRouter } from "vue-router";

import { confirmPasswordReset } from "../api/auth";

const route = useRoute();
const router = useRouter();
const form = reactive({
  newPassword: "",
});
const statusMessage = ref("");
const errorMessage = ref("");

async function onSubmit() {
  errorMessage.value = "";
  statusMessage.value = "";
  const uid = String(route.query.uid || "");
  const token = String(route.query.token || "");
  if (!uid || !token) {
    errorMessage.value = "Reset link is invalid or incomplete.";
    return;
  }
  try {
    const response = await confirmPasswordReset({
      uid,
      token,
      new_password: form.newPassword,
    });
    statusMessage.value = response.message;
    await router.push("/login");
  } catch {
    errorMessage.value = "Unable to reset password with this link.";
  }
}
</script>

<template>
  <section class="auth-card">
    <h1>Reset Password</h1>
    <form @submit.prevent="onSubmit" class="stack">
      <input v-model="form.newPassword" type="password" placeholder="New password" required />
      <button type="submit">Reset password</button>
      <p v-if="statusMessage">{{ statusMessage }}</p>
      <p v-if="errorMessage">{{ errorMessage }}</p>
    </form>
  </section>
</template>
