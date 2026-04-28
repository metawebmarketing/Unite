import { defineStore } from "pinia";

interface ErrorModalState {
  isOpen: boolean;
  title: string;
  message: string;
}

export const useErrorModalStore = defineStore("error-modal", {
  state: (): ErrorModalState => ({
    isOpen: false,
    title: "Error",
    message: "",
  }),
  actions: {
    showError(message: string, title = "Error") {
      const normalizedMessage = String(message || "").trim();
      if (!normalizedMessage) {
        return;
      }
      this.title = String(title || "Error").trim() || "Error";
      this.message = normalizedMessage;
      this.isOpen = true;
    },
    closeError() {
      this.isOpen = false;
    },
  },
});
