/**
 * Слой API-клиента (B1): один транспорт, одна обработка ошибок.
 *
 * Каждый запрос несёт заголовок X-Telegram-Init-Data — это схема авторизации,
 * зафиксированная в разделе 4 ТЗ. Любая ошибка backend-а приходит в едином
 * формате { error: { code, message } } и превращается здесь в ApiError, чтобы
 * UI работал с кодами, а не парсил тексты.
 */
import type { ApiErrorBody } from "./types";
import { getInitData } from "../telegram/webapp";

export class ApiError extends Error {
  readonly code: string;
  readonly status: number;
  readonly details?: Record<string, unknown>;

  constructor(status: number, body: ApiErrorBody) {
    super(body.message);
    this.name = "ApiError";
    this.code = body.code;
    this.status = status;
    this.details = body.details;
  }

  /** Ошибки, которые UI показывает как «нужна подписка / оплата». */
  get isPaymentRelated(): boolean {
    return (
      this.code === "SUBSCRIPTION_REQUIRED" ||
      this.code === "CUSTOM_CODE_NOT_PAID" ||
      this.code === "LIMIT_EXCEEDED" ||
      this.status === 402
    );
  }

  get isAuthError(): boolean {
    return this.status === 401;
  }
}

type Method = "GET" | "POST" | "PATCH" | "DELETE";

interface RequestOptions {
  query?: Record<string, string | number | boolean | undefined>;
  body?: unknown;
  signal?: AbortSignal;
}

const API_BASE = (import.meta.env.VITE_API_BASE ?? "").replace(/\/$/, "");

let mockHandler: ((method: Method, path: string, options: RequestOptions) => Promise<unknown>) | null =
  null;

/** Включает мок-режим: те же пути контракта обслуживаются локально. */
export function useMockTransport(
  handler: (method: Method, path: string, options: RequestOptions) => Promise<unknown>,
): void {
  mockHandler = handler;
}

export function isMockEnabled(): boolean {
  return mockHandler !== null;
}

function buildUrl(path: string, query?: RequestOptions["query"]): string {
  const url = `${API_BASE}/api${path}`;
  if (!query) return url;
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(query)) {
    if (value !== undefined && value !== "") params.set(key, String(value));
  }
  const qs = params.toString();
  return qs ? `${url}?${qs}` : url;
}

async function request<T>(method: Method, path: string, options: RequestOptions = {}): Promise<T> {
  if (mockHandler) {
    return (await mockHandler(method, path, options)) as T;
  }

  let response: Response;
  try {
    response = await fetch(buildUrl(path, options.query), {
      method,
      headers: {
        "Content-Type": "application/json",
        "X-Telegram-Init-Data": getInitData(),
      },
      body: options.body === undefined ? undefined : JSON.stringify(options.body),
      signal: options.signal,
    });
  } catch (cause) {
    if ((cause as Error)?.name === "AbortError") throw cause;
    throw new ApiError(0, {
      code: "NETWORK_ERROR",
      message: "Не удалось связаться с сервером",
    });
  }

  if (response.status === 204) return undefined as T;

  const text = await response.text();
  let payload: unknown = null;
  if (text) {
    try {
      payload = JSON.parse(text);
    } catch {
      payload = null;
    }
  }

  if (!response.ok) {
    const error = (payload as { error?: ApiErrorBody } | null)?.error;
    throw new ApiError(
      response.status,
      error ?? { code: "UNKNOWN_ERROR", message: `Ошибка ${response.status}` },
    );
  }

  return payload as T;
}

/** Загрузка файла: multipart, поэтому мимо JSON-обёртки. */
export async function uploadFile<T>(path: string, file: File): Promise<T> {
  if (mockHandler) {
    // в демо-режиме сервера нет — отдаём картинку как data-URL
    const url = await new Promise<string>((resolve, reject) => {
      const reader = new FileReader();
      reader.onload = () => resolve(String(reader.result));
      reader.onerror = () => reject(new Error("read failed"));
      reader.readAsDataURL(file);
    });
    return { url, size: file.size, mime: file.type } as T;
  }

  const form = new FormData();
  form.append("file", file);

  let response: Response;
  try {
    response = await fetch(buildUrl(path), {
      method: "POST",
      headers: { "X-Telegram-Init-Data": getInitData() },
      body: form,
    });
  } catch {
    throw new ApiError(0, { code: "NETWORK_ERROR", message: "Не удалось связаться с сервером" });
  }

  const text = await response.text();
  const payload = text ? JSON.parse(text) : null;
  if (!response.ok) {
    const error = (payload as { error?: ApiErrorBody } | null)?.error;
    throw new ApiError(response.status, error ?? { code: "UNKNOWN_ERROR", message: "Ошибка" });
  }
  return payload as T;
}

export const api = {
  get: <T>(path: string, query?: RequestOptions["query"], signal?: AbortSignal) =>
    request<T>("GET", path, { query, signal }),
  post: <T>(path: string, body?: unknown) => request<T>("POST", path, { body }),
  patch: <T>(path: string, body?: unknown) => request<T>("PATCH", path, { body }),
  delete: <T>(path: string) => request<T>("DELETE", path),
};

export type { Method, RequestOptions };
