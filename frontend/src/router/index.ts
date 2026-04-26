import { createRouter, createWebHistory } from "vue-router";

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: "/", name: "feed", component: () => import("../views/FeedView.vue"), meta: { requiresAuth: true } },
    { path: "/install", name: "install", component: () => import("../views/InstallView.vue") },
    { path: "/login", name: "login", component: () => import("../views/LoginView.vue") },
    {
      path: "/forgot-password",
      name: "forgot-password",
      component: () => import("../views/ForgotPasswordView.vue"),
    },
    { path: "/reset-password", name: "reset-password", component: () => import("../views/ResetPasswordView.vue") },
    { path: "/signup", name: "signup", component: () => import("../views/SignupView.vue") },
    {
      path: "/onboarding",
      name: "onboarding",
      component: () => import("../views/OnboardingView.vue"),
      meta: { requiresAuth: true },
    },
    {
      path: "/profile-generation",
      name: "profile-generation",
      component: () => import("../views/ProfileGenerationView.vue"),
      meta: { requiresAuth: true },
    },
    {
      path: "/policy-lab",
      name: "policy-lab",
      component: () => import("../views/PolicyLabView.vue"),
      meta: { requiresAuth: true, requiresStaff: true },
    },
    {
      path: "/ads-lab",
      name: "ads-lab",
      component: () => import("../views/AdsLabView.vue"),
      meta: { requiresAuth: true, requiresStaff: true },
    },
    {
      path: "/ai-audit",
      name: "ai-audit",
      component: () => import("../views/AiAuditView.vue"),
      meta: { requiresAuth: true, requiresStaff: true },
    },
    {
      path: "/profile",
      name: "profile",
      redirect: { name: "feed", query: { modal: "profile" } },
      meta: { requiresAuth: true },
    },
    {
      path: "/compose",
      name: "compose",
      redirect: { name: "feed", query: { modal: "compose" } },
      meta: { requiresAuth: true },
    },
    {
      path: "/theme-studio",
      name: "theme-studio",
      redirect: { name: "feed", query: { modal: "theme-studio" } },
      meta: { requiresAuth: true },
    },
  ],
});

export default router;
