import { createRouter, createWebHistory } from "vue-router";
import AdsLabView from "../views/AdsLabView.vue";
import AiAuditView from "../views/AiAuditView.vue";
import BookmarkedPostsView from "../views/BookmarkedPostsView.vue";
import ConnectionsListView from "../views/ConnectionsListView.vue";
import MessagesView from "../views/MessagesView.vue";
import MessageThreadView from "../views/MessageThreadView.vue";
import NotificationsView from "../views/NotificationsView.vue";
import PinnedPostsView from "../views/PinnedPostsView.vue";
import PolicyLabView from "../views/PolicyLabView.vue";
import PostDetailView from "../views/PostDetailView.vue";
import SearchView from "../views/SearchView.vue";
import UserProfileView from "../views/UserProfileView.vue";

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
      component: PolicyLabView,
      meta: { requiresAuth: true, requiresStaff: true },
    },
    {
      path: "/ads-lab",
      name: "ads-lab",
      component: AdsLabView,
      meta: { requiresAuth: true, requiresStaff: true },
    },
    {
      path: "/ai-audit",
      name: "ai-audit",
      component: AiAuditView,
      meta: { requiresAuth: true, requiresStaff: true },
    },
    {
      path: "/profile",
      name: "profile",
      component: () => import("../views/ProfileView.vue"),
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
    {
      path: "/post/:postId",
      name: "post-detail",
      component: PostDetailView,
      meta: { requiresAuth: true },
    },
    {
      path: "/users/:userId",
      name: "user-profile",
      component: UserProfileView,
      meta: { requiresAuth: true },
    },
    {
      path: "/connections",
      name: "my-connections",
      component: ConnectionsListView,
      meta: { requiresAuth: true },
    },
    {
      path: "/users/:userId/connections",
      name: "user-connections",
      component: ConnectionsListView,
      meta: { requiresAuth: true },
    },
    {
      path: "/bookmarks",
      name: "bookmarks",
      component: BookmarkedPostsView,
      meta: { requiresAuth: true },
    },
    {
      path: "/pinned",
      name: "pinned-posts",
      component: PinnedPostsView,
      meta: { requiresAuth: true },
    },
    {
      path: "/search",
      name: "search",
      component: SearchView,
      meta: { requiresAuth: true },
    },
    {
      path: "/messages",
      name: "messages",
      component: MessagesView,
      meta: { requiresAuth: true },
    },
    {
      path: "/messages/:threadId",
      name: "message-thread",
      component: MessageThreadView,
      meta: { requiresAuth: true },
    },
    {
      path: "/notifications",
      name: "notifications",
      component: NotificationsView,
      meta: { requiresAuth: true },
    },
  ],
});

export default router;
