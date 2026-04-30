<script setup lang="ts">
import { reactive, ref } from "vue";
import { useRouter } from "vue-router";

import { fetchProfile } from "../api/profile";
import { useAuthStore } from "../stores/auth";

const router = useRouter();
const authStore = useAuthStore();
const isBusy = ref(false);
const form = reactive({
  username: "",
  password: "",
});

async function onSubmit() {
  isBusy.value = true;
  try {
    await authStore.loginUser(form);
    try {
      const profile = await fetchProfile();
      if (profile.algorithm_profile_status === "ready") {
        await router.push("/");
        return;
      }
    } catch {
      // Fall through to progress screen.
    }
    await router.push("/profile-generation?next=/");
  } finally {
    isBusy.value = false;
  }
}
</script>

<template>
  <section class="auth-card">
    <h1>Log in</h1>
    <form @submit.prevent="onSubmit" class="stack">
      <input v-model="form.username" placeholder="Username" required />
      <input v-model="form.password" type="password" placeholder="Password" required />
      <button type="submit">{{ isBusy ? "Signing in..." : "Log in" }}</button>
      <div v-if="isBusy" class="progress-track"><div class="progress-fill progress-indeterminate" /></div>
      <router-link to="/forgot-password">Forgot password?</router-link>
      <router-link to="/signup">Need an account? Register</router-link>
    </form>
    <div v-if="isBusy" class="loading-overlay">
      <div class="spinner" />
    </div>
  </section>
</template>
