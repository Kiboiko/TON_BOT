/** Глобальное состояние приложения: пользователь, тема, язык, тосты. */
import { create } from "zustand";
import { ApiError } from "../api/client";
import { userApi } from "../api/endpoints";
import type { Language, Theme, User } from "../api/types";
import { getTelegramLanguage, getTelegramTheme, haptic } from "../telegram/webapp";
import i18n from "../i18n";

export interface Toast {
  id: number;
  text: string;
  kind: "info" | "success" | "error";
}

interface AppState {
  user: User | null;
  loading: boolean;
  authError: string | null;
  theme: Theme;
  language: Language;
  toasts: Toast[];

  auth: () => Promise<void>;
  setTheme: (theme: Theme, persist?: boolean) => void;
  setLanguage: (language: Language, persist?: boolean) => void;
  setWallet: (address: string | null) => void;
  toast: (text: string, kind?: Toast["kind"]) => void;
  dismissToast: (id: number) => void;
  toastError: (error: unknown) => void;
}

function applyTheme(theme: Theme): void {
  document.documentElement.dataset.theme = theme;
}

let toastSeq = 0;

export const useAppStore = create<AppState>((set, get) => ({
  user: null,
  loading: true,
  authError: null,
  theme: getTelegramTheme(),
  language: getTelegramLanguage(),
  toasts: [],

  async auth() {
    set({ loading: true, authError: null });
    try {
      const { user } = await userApi.auth();
      get().setTheme(user.theme, false);
      get().setLanguage(user.language, false);
      set({ user, loading: false });
    } catch (error) {
      const message =
        error instanceof ApiError ? error.message : "Не удалось подключиться к серверу";
      set({ loading: false, authError: message });
      throw error;
    }
  },

  setTheme(theme, persist = true) {
    applyTheme(theme);
    set({ theme });
    if (persist) {
      set((s) => (s.user ? { user: { ...s.user, theme } } : {}));
      void userApi.updateSettings({ theme }).catch(() => undefined);
    }
  },

  setLanguage(language, persist = true) {
    void i18n.changeLanguage(language);
    set({ language });
    if (persist) {
      set((s) => (s.user ? { user: { ...s.user, language } } : {}));
      void userApi.updateSettings({ language }).catch(() => undefined);
    }
  },

  setWallet(address) {
    set((s) => (s.user ? { user: { ...s.user, wallet_address: address } } : {}));
  },

  toast(text, kind = "info") {
    const id = ++toastSeq;
    if (kind === "error") haptic.error();
    if (kind === "success") haptic.success();
    set((s) => ({ toasts: [...s.toasts, { id, text, kind }] }));
    setTimeout(() => get().dismissToast(id), 4000);
  },

  dismissToast(id) {
    set((s) => ({ toasts: s.toasts.filter((t) => t.id !== id) }));
  },

  toastError(error) {
    if (error instanceof ApiError) {
      get().toast(error.message, "error");
    } else if (error instanceof Error) {
      get().toast(error.message, "error");
    } else {
      get().toast("Что-то пошло не так", "error");
    }
  },
}));
