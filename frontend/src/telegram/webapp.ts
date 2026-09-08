/**
 * Обёртка над Telegram Web App SDK (B1).
 *
 * Приложение должно работать и вне Telegram (в браузере при разработке),
 * поэтому каждый вызов SDK защищён проверкой доступности.
 */
import WebApp from "@twa-dev/sdk";

let available = false;
try {
  available = typeof window !== "undefined" && Boolean(window.Telegram?.WebApp?.initData !== undefined);
} catch {
  available = false;
}

export function isTelegram(): boolean {
  return available;
}

export function initTelegram(): void {
  applyViewportHeight();
  window.addEventListener("resize", applyViewportHeight);
  if (!available) return;
  WebApp.ready();
  WebApp.expand();
  WebApp.enableClosingConfirmation();
  try {
    WebApp.setHeaderColor("secondary_bg_color");
  } catch {
    /* старые клиенты не поддерживают — не критично */
  }
  // Свайп вниз внутри приложения закрывает Mini App и «дёргает» вёрстку при
  // скролле длинных списков. Метод появился в Bot API 7.7 — старые клиенты
  // просто его не знают.
  try {
    (WebApp as unknown as { disableVerticalSwipes?: () => void }).disableVerticalSwipes?.();
  } catch {
    /* не критично */
  }
  WebApp.onEvent("viewportChanged", applyViewportHeight);
  applyViewportHeight();
}

/**
 * Высота приложения в CSS-переменной `--app-height`.
 *
 * На Android клавиатура и «схлопывание» шапки меняют видимую высоту, а
 * position:fixed продолжает считать от старой — из-за этого нижняя навигация
 * уезжала за экран и её приходилось искать скроллом. Держим точную высоту
 * сами и делаем каркас flex-колонкой без fixed-элементов.
 */
function applyViewportHeight(): void {
  const reported = available
    ? WebApp.viewportStableHeight || WebApp.viewportHeight || 0
    : 0;
  // берём меньшее: Telegram на Android отдаёт высоту видимой части, а окно
  // webview выше неё; при открытой клавиатуре наоборот меньше окажется окно
  const height = reported ? Math.min(reported, window.innerHeight) : window.innerHeight;
  if (!height) return;
  document.documentElement.style.setProperty("--app-height", `${Math.round(height)}px`);
}

export function getInitData(): string {
  if (!available) return "";
  return WebApp.initData ?? "";
}

/** Тема самого Telegram — используется как значение по умолчанию. */
export function getTelegramTheme(): "light" | "dark" {
  if (!available) {
    const prefersDark = window.matchMedia?.("(prefers-color-scheme: dark)").matches;
    return prefersDark ? "dark" : "light";
  }
  return WebApp.colorScheme === "dark" ? "dark" : "light";
}

export function getTelegramLanguage(): "ru" | "en" {
  const code = available ? WebApp.initDataUnsafe?.user?.language_code : navigator.language;
  return (code ?? "ru").toLowerCase().startsWith("ru") ? "ru" : "en";
}

export function onThemeChanged(handler: () => void): () => void {
  if (!available) return () => undefined;
  WebApp.onEvent("themeChanged", handler);
  return () => WebApp.offEvent("themeChanged", handler);
}

// --- главная кнопка ---
export function showMainButton(text: string, onClick: () => void): () => void {
  if (!available) return () => undefined;
  WebApp.MainButton.setText(text);
  WebApp.MainButton.show();
  WebApp.MainButton.onClick(onClick);
  return () => {
    WebApp.MainButton.offClick(onClick);
    WebApp.MainButton.hide();
  };
}

export function setMainButtonProgress(active: boolean): void {
  if (!available) return;
  if (active) WebApp.MainButton.showProgress(false);
  else WebApp.MainButton.hideProgress();
}

export function setMainButtonEnabled(enabled: boolean): void {
  if (!available) return;
  if (enabled) WebApp.MainButton.enable();
  else WebApp.MainButton.disable();
}

// --- кнопка «назад» ---
export function showBackButton(onClick: () => void): () => void {
  if (!available) return () => undefined;
  WebApp.BackButton.show();
  WebApp.BackButton.onClick(onClick);
  return () => {
    WebApp.BackButton.offClick(onClick);
    WebApp.BackButton.hide();
  };
}

// --- haptic feedback ---
export const haptic = {
  light(): void {
    if (available) WebApp.HapticFeedback.impactOccurred("light");
  },
  medium(): void {
    if (available) WebApp.HapticFeedback.impactOccurred("medium");
  },
  success(): void {
    if (available) WebApp.HapticFeedback.notificationOccurred("success");
  },
  error(): void {
    if (available) WebApp.HapticFeedback.notificationOccurred("error");
  },
  selection(): void {
    if (available) WebApp.HapticFeedback.selectionChanged();
  },
};

export function showConfirm(message: string): Promise<boolean> {
  if (!available) return Promise.resolve(window.confirm(message));
  return new Promise((resolve) => WebApp.showConfirm(message, resolve));
}

export function openLink(url: string): void {
  if (available) WebApp.openLink(url);
  else window.open(url, "_blank", "noopener");
}

declare global {
  interface Window {
    Telegram?: { WebApp?: { initData?: string } };
  }
}
