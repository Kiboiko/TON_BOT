/**
 * Мок-сервер API-контракта (раздел 7 ТЗ, «День 1»).
 *
 * Реализует те же пути, что и backend, поэтому Mini App полностью работоспособен
 * без сервера: демонстрация, разработка UI, отладка вёрстки. Включается флагом
 * VITE_USE_MOCK=1 или автоматически, если backend не отвечает на /user/auth.
 */
import { ApiError, useMockTransport } from "./client";
import type { Method, RequestOptions } from "./client";
import { defaultContentFor } from "../templates/catalog";
import { renderSite } from "../features/preview/render";
import type {
  AdminUserListItem,
  Payment,
  Site,
  SiteListItem,
  SiteType,
  Subscription,
  Tariff,
  TonConnectTransaction,
  User,
} from "./types";

const STORAGE_KEY = "tsb-mock-state-v1";

interface MockState {
  user: User;
  sites: Site[];
  tariffs: Tariff[];
  subscriptions: Subscription[];
  payments: Payment[];
  users: AdminUserListItem[];
}

function uuid(): string {
  return crypto.randomUUID();
}

function now(): string {
  return new Date().toISOString();
}

function seed(): MockState {
  const user: User = {
    id: uuid(),
    telegram_id: 777000,
    username: "demo",
    first_name: "Demo",
    wallet_address: null,
    language: "ru",
    theme: "light",
    is_admin: true,
    created_at: now(),
  };
  const tariffs: Tariff[] = [
    {
      id: uuid(),
      name: "Базовый",
      description: "1 сайт, публикация на домене .ton",
      sites_limit: 1,
      duration: "month",
      price_ton: "2",
      kind: "base",
      is_active: true,
    },
    {
      id: uuid(),
      name: "PRO 5",
      description: "До 5 сайтов",
      sites_limit: 5,
      duration: "month",
      price_ton: "7",
      kind: "pro",
      is_active: true,
    },
    {
      id: uuid(),
      name: "PRO 25",
      description: "До 25 сайтов",
      sites_limit: 25,
      duration: "month",
      price_ton: "25",
      kind: "pro",
      is_active: true,
    },
    {
      id: uuid(),
      name: "Свой код",
      description: "Премиум-блок HTML/CSS/JS",
      sites_limit: 1,
      duration: "forever",
      price_ton: "5",
      kind: "custom_code",
      is_active: true,
    },
  ];
  return {
    user,
    sites: [],
    tariffs,
    subscriptions: [],
    payments: [],
    users: [
      {
        id: user.id,
        telegram_id: user.telegram_id,
        username: user.username,
        wallet_address: null,
        is_admin: true,
        is_blocked: false,
        created_at: user.created_at,
        sites_count: 0,
        active_subscriptions: 0,
      },
    ],
  };
}

function load(): MockState {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (raw) return JSON.parse(raw) as MockState;
  } catch {
    /* повреждённое состояние просто пересоздаём */
  }
  const fresh = seed();
  save(fresh);
  return fresh;
}

function save(state: MockState): void {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(state));
  } catch {
    /* приватный режим браузера — работаем в памяти */
  }
}

let state = load();

function fail(status: number, code: string, message: string): never {
  throw new ApiError(status, { code, message });
}

function sitesLimit(): number {
  const active = state.subscriptions.filter(
    (s) => s.status !== "expired" && (!s.expires_at || new Date(s.expires_at) > new Date()),
  );
  return Math.max(1, ...active.map((s) => s.tariff?.sites_limit ?? 1));
}

function toListItem(site: Site): SiteListItem {
  const { id, type, title, domain, status, published_at, created_at, updated_at } = site;
  return { id, type, title, domain, status, published_at, created_at, updated_at };
}

function fakeTransaction(amountTon: string): TonConnectTransaction {
  return {
    validUntil: Math.floor(Date.now() / 1000) + 600,
    messages: [
      {
        address: "0:0000000000000000000000000000000000000000000000000000000000000000",
        amount: String(Math.round(Number(amountTon) * 1e9)),
        payload: "te6ccgEBAQEAAgAAAA==",
      },
    ],
  };
}

function findSite(id: string): Site {
  const site = state.sites.find((s) => s.id === id);
  if (!site) fail(404, "SITE_NOT_FOUND", "Сайт не найден");
  return site;
}

async function handler(method: Method, path: string, options: RequestOptions): Promise<unknown> {
  await new Promise((resolve) => setTimeout(resolve, 120)); // имитация сети
  const body = (options.body ?? {}) as Record<string, unknown>;
  const query = options.query ?? {};
  const route = `${method} ${path}`;

  // --- пользователь ---
  if (route === "POST /user/auth") return { user: state.user, is_admin: state.user.is_admin };
  if (route === "GET /user/me") return state.user;
  if (route === "GET /user/ton-proof-payload")
    return { payload: uuid().replace(/-/g, ""), expires_at: new Date(Date.now() + 600_000).toISOString() };
  if (route === "POST /user/connect-wallet") {
    state.user.wallet_address = (body as { wallet_address: string }).wallet_address;
    save(state);
    return { success: true, wallet_address: state.user.wallet_address };
  }
  if (route === "PATCH /user/settings") {
    Object.assign(state.user, body);
    save(state);
    return { success: true };
  }

  // --- сайты ---
  if (route === "GET /sites") return state.sites.map(toListItem);
  if (route === "POST /sites") {
    if (state.sites.length >= sitesLimit()) {
      fail(403, "LIMIT_EXCEEDED", `Достигнут лимит сайтов (${sitesLimit()})`);
    }
    const input = body as unknown as { type: SiteType; title: string };
    const site: Site = {
      id: uuid(),
      type: input.type,
      title: input.title,
      content_json: defaultContentFor(input.type, input.title),
      custom_code: null,
      custom_code_paid: false,
      domain: null,
      dns_item_address: null,
      collection_address: null,
      status: "draft",
      storage_bag_id: null,
      published_at: null,
      created_at: now(),
      updated_at: now(),
    };
    state.sites.unshift(site);
    save(state);
    return { site };
  }

  const siteMatch = /^\/sites\/([^/]+)(\/.*)?$/.exec(path);
  if (siteMatch) {
    const site = findSite(siteMatch[1]);
    const tail = siteMatch[2] ?? "";

    if (method === "GET" && !tail) return { site };
    if (method === "PATCH" && !tail) {
      Object.assign(site, body, { updated_at: now() });
      save(state);
      return { site };
    }
    if (method === "DELETE" && !tail) {
      state.sites = state.sites.filter((s) => s.id !== site.id);
      save(state);
      return { success: true };
    }
    if (tail === "/preview") {
      return {
        preview_html: renderSite(site.content_json, {
          title: site.title,
          domain: site.domain,
          customCode: site.custom_code_paid ? site.custom_code : null,
        }),
      };
    }
    if (tail === "/publish") {
      site.status = "publishing";
      save(state);
      // публикация завершается «в фоне», как и на реальном backend
      setTimeout(() => {
        site.status = "published";
        site.storage_bag_id = uuid().replace(/-/g, "").toUpperCase();
        site.published_at = now();
        save(state);
      }, 2500);
      return { status: "publishing", job_id: uuid() };
    }
    if (tail === "/publish-status") {
      return {
        status: site.status,
        storage_bag_id: site.storage_bag_id,
        published_at: site.published_at,
        error: null,
        public_url: site.status === "published" ? `${window.location.origin}/s/${site.id}` : null,
      };
    }
    if (tail === "/dns-bind") return { transaction: fakeTransaction("0.05") };
    if (tail === "/custom-code/purchase") {
      const tariff = state.tariffs.find((t) => t.kind === "custom_code");
      if (!tariff) fail(404, "TARIFF_NOT_FOUND", "Тариф не настроен");
      const payment: Payment = {
        id: uuid(),
        tx_hash: null,
        amount: tariff.price_ton,
        purpose: "custom_code",
        related_id: site.id,
        status: "pending",
        created_at: now(),
        confirmed_at: null,
      };
      state.payments.push(payment);
      save(state);
      return { transaction: fakeTransaction(tariff.price_ton), payment_id: payment.id };
    }
    if (tail === "/custom-code/confirm") {
      site.custom_code_paid = true;
      const payment = state.payments.find((p) => p.id === (body as { payment_id: string }).payment_id);
      if (payment) {
        payment.status = "confirmed";
        payment.confirmed_at = now();
      }
      save(state);
      return { success: true };
    }
    if (tail === "/custom-code") {
      if (!site.custom_code_paid) fail(402, "CUSTOM_CODE_NOT_PAID", "Блок не оплачен");
      site.custom_code = body as unknown as Site["custom_code"];
      save(state);
      return { success: true };
    }
  }

  // --- домены ---
  if (route === "GET /domains/check") {
    const name = String(query.name ?? "");
    const available = !name.toLowerCase().startsWith("taken");
    return {
      available,
      status: available ? "free" : "taken",
      domain: `${name}.${query.tld ?? "ton"}`,
      dns_item_address: "0:" + "1".repeat(64),
      collection_address: "0:" + "2".repeat(64),
      owner: available ? null : "0:" + "9".repeat(64),
    };
  }
  if (route === "POST /domains/deploy-zone") {
    const input = body as unknown as { site_id: string; domain: string; tld: string };
    const site = findSite(input.site_id);
    site.domain = `${input.domain}.${input.tld}`;
    site.dns_item_address = "0:" + "1".repeat(64);
    save(state);
    return { transaction: fakeTransaction("0.5") };
  }
  if (route === "POST /domains/confirm") return { status: "publishing" };

  // --- тарифы и подписки ---
  if (route === "GET /tariffs") return state.tariffs.filter((t) => t.is_active && t.kind !== "custom_code");
  if (route === "POST /subscriptions/purchase") {
    const tariff = state.tariffs.find((t) => t.id === (body as { tariff_id: string }).tariff_id);
    if (!tariff) fail(404, "TARIFF_NOT_FOUND", "Тариф не найден");
    const payment: Payment = {
      id: uuid(),
      tx_hash: null,
      amount: tariff.price_ton,
      purpose: "subscription",
      related_id: tariff.id,
      status: "pending",
      created_at: now(),
      confirmed_at: null,
    };
    state.payments.push(payment);
    save(state);
    return { transaction: fakeTransaction(tariff.price_ton), payment_id: payment.id };
  }
  if (route === "POST /subscriptions/confirm") {
    const payment = state.payments.find((p) => p.id === (body as { payment_id: string }).payment_id);
    if (!payment) fail(404, "PAYMENT_NOT_FOUND", "Платёж не найден");
    payment.status = "confirmed";
    payment.confirmed_at = now();
    const tariff = state.tariffs.find((t) => t.id === payment.related_id) ?? null;
    const subscription: Subscription = {
      id: uuid(),
      tariff,
      site_id: null,
      starts_at: now(),
      expires_at: new Date(Date.now() + 30 * 864e5).toISOString(),
      is_forever: tariff?.duration === "forever",
      is_trial: false,
      status: "active",
      granted_by_admin: false,
    };
    state.subscriptions.unshift(subscription);
    save(state);
    return { subscription };
  }
  if (route === "GET /subscriptions") return state.subscriptions;

  // --- админка ---
  if (route === "GET /admin/users") {
    const search = String(query.search ?? "").toLowerCase();
    const filtered = state.users.filter(
      (u) => !search || (u.username ?? "").toLowerCase().includes(search) || String(u.telegram_id).includes(search),
    );
    return { users: filtered, total: filtered.length, page: 1, per_page: 20 };
  }
  const adminUserMatch = /^\/admin\/users\/([^/]+)(\/.*)?$/.exec(path);
  if (adminUserMatch) {
    const tail = adminUserMatch[2] ?? "";
    if (method === "GET" && !tail) {
      return {
        user: state.user,
        sites: state.sites.map(toListItem),
        subscriptions: state.subscriptions,
        payments: state.payments,
      };
    }
    if (tail === "/grant-access") {
      const input = body as unknown as { tariff_id?: string; sites_limit?: number };
      const tariff =
        state.tariffs.find((t) => t.id === input.tariff_id) ??
        ({
          id: uuid(),
          name: `Manual ${input.sites_limit ?? 1} sites`,
          description: null,
          sites_limit: input.sites_limit ?? 1,
          duration: "month",
          price_ton: "0",
          kind: "base",
          is_active: false,
        } as Tariff);
      const subscription: Subscription = {
        id: uuid(),
        tariff,
        site_id: null,
        starts_at: now(),
        expires_at: new Date(Date.now() + 30 * 864e5).toISOString(),
        is_forever: false,
        is_trial: false,
        status: "manual",
        granted_by_admin: true,
      };
      state.subscriptions.unshift(subscription);
      save(state);
      return { subscription };
    }
    if (tail === "/revoke-access") {
      const id = (body as { subscription_id: string }).subscription_id;
      state.subscriptions = state.subscriptions.map((s) =>
        s.id === id ? { ...s, status: "expired" as const } : s,
      );
      save(state);
      return { success: true };
    }
  }
  if (route === "GET /admin/tariffs") return state.tariffs;
  if (route === "POST /admin/tariffs") {
    const tariff = { id: uuid(), ...(body as unknown as Omit<Tariff, "id">) };
    state.tariffs.push(tariff);
    save(state);
    return tariff;
  }
  const tariffMatch = /^\/admin\/tariffs\/([^/]+)$/.exec(path);
  if (tariffMatch) {
    const tariff = state.tariffs.find((t) => t.id === tariffMatch[1]);
    if (!tariff) fail(404, "TARIFF_NOT_FOUND", "Тариф не найден");
    if (method === "PATCH") {
      Object.assign(tariff, body);
      save(state);
      return tariff;
    }
    if (method === "DELETE") {
      state.tariffs = state.tariffs.filter((t) => t.id !== tariff.id);
      save(state);
      return { success: true };
    }
  }
  if (route === "GET /admin/domains") {
    return state.sites
      .filter((s) => s.domain)
      .map((s) => ({
        domain: s.domain,
        status: s.status,
        site_id: s.id,
        site_title: s.title,
        user_id: state.user.id,
        telegram_id: state.user.telegram_id,
        published_at: s.published_at,
      }));
  }
  if (route === "GET /admin/stats") {
    const revenue = state.payments
      .filter((p) => p.status === "confirmed")
      .reduce((sum, p) => sum + Number(p.amount), 0);
    return {
      total_users: state.users.length,
      total_sites: state.sites.length,
      published_sites: state.sites.filter((s) => s.status === "published").length,
      active_subscriptions: state.subscriptions.filter((s) => s.status !== "expired").length,
      revenue: String(revenue),
      revenue_last_30d: String(revenue),
      payments_confirmed: state.payments.filter((p) => p.status === "confirmed").length,
    };
  }

  fail(404, "NOT_FOUND", `Мок не знает маршрут ${route}`);
}

export function enableMock(): void {
  state = load();
  useMockTransport(handler);
}

export function resetMock(): void {
  localStorage.removeItem(STORAGE_KEY);
  state = load();
}
