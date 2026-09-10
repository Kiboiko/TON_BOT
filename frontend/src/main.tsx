/**
 * Точка входа Mini App.
 *
 * Если backend недоступен (или включён VITE_USE_MOCK), приложение поднимается
 * против встроенного мока контракта — так UI можно смотреть и без сервера.
 */
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import { TonConnectUIProvider } from "@tonconnect/ui-react";
import { App } from "./App";
import { enableMock } from "./api/mock";
import { getInitData, isTelegram } from "./telegram/webapp";
import { resolveManifestUrl } from "./tonconnect";
import "./i18n";
import "./styles/index.css";

const MANIFEST_URL = resolveManifestUrl(
  import.meta.env.VITE_TONCONNECT_MANIFEST,
  window.location.origin,
);

/**
 * Куда кошелёк возвращает пользователя после подписи.
 *
 * Внутри Telegram это обязательный параметр: без него кошелёк не знает, как
 * вернуть управление в Mini App, и подтверждение зависает на бесконечной
 * загрузке. Значение — ссылка на бота, из которого открыто приложение.
 */
const TWA_RETURN_URL = import.meta.env.VITE_TWA_RETURN_URL as
  | `${string}://${string}`
  | undefined;

async function backendAvailable(): Promise<boolean> {
  try {
    const base = (import.meta.env.VITE_API_BASE ?? "").replace(/\/$/, "");
    const response = await fetch(`${base}/api/health`, {
      headers: { "X-Telegram-Init-Data": getInitData() },
    });
    return response.ok;
  } catch {
    return false;
  }
}

/**
 * Когда включать мок:
 *   VITE_USE_MOCK=1 — всегда, VITE_USE_MOCK=0 — никогда (явный отказ),
 *   не задан — если мы вне Telegram (настоящий backend всё равно отклонит запрос
 *   без подписанного initData) или backend не отвечает.
 */
async function shouldUseMock(): Promise<boolean> {
  const flag = import.meta.env.VITE_USE_MOCK;
  if (flag === "1") return true;
  if (flag === "0") return false;
  if (!isTelegram()) return true;
  return !(await backendAvailable());
}

async function bootstrap(): Promise<void> {
  if (await shouldUseMock()) enableMock();

  createRoot(document.getElementById("root")!).render(
    <StrictMode>
      <TonConnectUIProvider
        manifestUrl={MANIFEST_URL}
        actionsConfiguration={TWA_RETURN_URL ? { twaReturnUrl: TWA_RETURN_URL } : undefined}
      >
        <BrowserRouter>
          <App />
        </BrowserRouter>
      </TonConnectUIProvider>
    </StrictMode>,
  );
}

void bootstrap();
