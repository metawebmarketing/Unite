import { defineStore } from "pinia";

interface RouteLoadingState {
  pendingNavigations: number;
  isRouteChanging: boolean;
}

export const useRouteLoadingStore = defineStore("route-loading", {
  state: (): RouteLoadingState => ({
    pendingNavigations: 0,
    isRouteChanging: false,
  }),
  actions: {
    startNavigation() {
      this.pendingNavigations += 1;
      this.isRouteChanging = true;
    },
    finishNavigation() {
      this.pendingNavigations = Math.max(0, this.pendingNavigations - 1);
      this.isRouteChanging = this.pendingNavigations > 0;
    },
    resetNavigation() {
      this.pendingNavigations = 0;
      this.isRouteChanging = false;
    },
  },
});
