import { defineStore } from "pinia";

interface RouteLoadingState {
  isRouteChanging: boolean;
}

export const useRouteLoadingStore = defineStore("route-loading", {
  state: (): RouteLoadingState => ({
    isRouteChanging: false,
  }),
  actions: {
    startNavigation() {
      this.isRouteChanging = true;
    },
    finishNavigation() {
      this.isRouteChanging = false;
    },
    resetNavigation() {
      this.isRouteChanging = false;
    },
  },
});
