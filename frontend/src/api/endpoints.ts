/** Обёртки над эндпоинтами раздела 4 ТЗ — ровно те пути, что реализует backend. */
import { api, uploadFile } from "./client";
import type {
  AdminDomainItem,
  AdminStats,
  AdminUserDetail,
  AdminUsersResponse,
  AuthResponse,
  CustomCode,
  DomainCheck,
  Language,
  PublishStatus,
  Site,
  SiteContent,
  SiteListItem,
  SiteType,
  Subscription,
  Tariff,
  TariffDuration,
  TariffKind,
  Theme,
  TonConnectTransaction,
  User,
  Zone,
} from "./types";

// --- пользователь и кошелёк ---
export const userApi = {
  auth: () => api.post<AuthResponse>("/user/auth", {}),
  me: () => api.get<User>("/user/me"),
  tonProofPayload: () => api.get<{ payload: string; expires_at: string }>("/user/ton-proof-payload"),
  connectWallet: (body: {
    wallet_address: string;
    ton_proof: {
      timestamp: number;
      domain: { lengthBytes: number; value: string };
      signature: string;
      payload: string;
      state_init?: string;
    };
  }) => api.post<{ success: boolean; wallet_address: string }>("/user/connect-wallet", body),
  updateSettings: (body: { language?: Language; theme?: Theme }) =>
    api.patch<{ success: boolean }>("/user/settings", body),
};

// --- сайты ---
export const sitesApi = {
  list: () => api.get<SiteListItem[]>("/sites"),
  create: (body: { type: SiteType; title: string; content_json?: SiteContent }) =>
    api.post<{ site: Site }>("/sites", body),
  get: (id: string) => api.get<{ site: Site }>(`/sites/${id}`),
  update: (id: string, body: { title?: string; content_json?: SiteContent }) =>
    api.patch<{ site: Site }>(`/sites/${id}`, body),
  remove: (id: string) => api.delete<{ success: boolean }>(`/sites/${id}`),
  preview: (id: string) => api.post<{ preview_html: string }>(`/sites/${id}/preview`),
  publish: (id: string) => api.post<{ status: string; job_id: string }>(`/sites/${id}/publish`),
  publishStatus: (id: string) => api.get<PublishStatus>(`/sites/${id}/publish-status`),
  dnsBind: (id: string) => api.post<{ transaction: TonConnectTransaction }>(`/sites/${id}/dns-bind`),

  // премиум-блок «Свой код»
  customCodePurchase: (id: string) =>
    api.post<{ transaction: TonConnectTransaction; payment_id: string }>(
      `/sites/${id}/custom-code/purchase`,
    ),
  customCodeConfirm: (id: string, body: { payment_id: string; tx_hash: string }) =>
    api.post<{ success: boolean }>(`/sites/${id}/custom-code/confirm`, body),
  setCustomCode: (id: string, body: CustomCode) =>
    api.post<{ success: boolean }>(`/sites/${id}/custom-code`, body),
};

// --- загрузка картинок ---
export const uploadsApi = {
  image: (file: File) => uploadFile<{ url: string; size: number; mime: string }>("/uploads", file),
};

// --- домены ---
export const domainsApi = {
  check: (name: string) => api.get<DomainCheck>("/domains/check", { name }),
  claim: (body: { site_id: string; name: string }) =>
    api.post<{ transaction: TonConnectTransaction; domain: string }>("/domains/claim", body),
  // привязка домена .ton, которым пользователь уже владеет
  attach: (body: { site_id: string; domain: string }) =>
    api.post<{ domain: string; item_address: string | null; needs_publish: boolean }>(
      "/domains/attach",
      body,
    ),
  confirm: (body: { site_id: string; tx_hash: string }) =>
    api.post<{ status: string; domain: string | null }>("/domains/confirm", body),
};

// --- тарифы и подписки ---
export const billingApi = {
  tariffs: () => api.get<Tariff[]>("/tariffs"),
  purchase: (body: { tariff_id: string; site_id?: string }) =>
    api.post<{ transaction: TonConnectTransaction; payment_id: string }>(
      "/subscriptions/purchase",
      body,
    ),
  confirm: (body: { payment_id: string; tx_hash: string }) =>
    api.post<{ subscription: Subscription }>("/subscriptions/confirm", body),
  subscriptions: () => api.get<Subscription[]>("/subscriptions"),
};

// --- админка ---
export const adminApi = {
  users: (params: { search?: string; page?: number; per_page?: number }) =>
    api.get<AdminUsersResponse>("/admin/users", params),
  user: (id: string) => api.get<AdminUserDetail>(`/admin/users/${id}`),
  grantAccess: (
    id: string,
    body: {
      tariff_id?: string;
      duration?: TariffDuration;
      site_id?: string;
      sites_limit?: number;
      comment?: string;
    },
  ) => api.post<{ subscription: Subscription }>(`/admin/users/${id}/grant-access`, body),
  revokeAccess: (id: string, subscription_id: string) =>
    api.post<{ success: boolean }>(`/admin/users/${id}/revoke-access`, { subscription_id }),

  tariffs: () => api.get<Tariff[]>("/admin/tariffs"),
  createTariff: (body: {
    name: string;
    description?: string;
    sites_limit: number;
    duration: TariffDuration;
    price_ton: string;
    kind: TariffKind;
    is_active: boolean;
  }) => api.post<Tariff>("/admin/tariffs", body),
  updateTariff: (id: string, body: Partial<Omit<Tariff, "id">>) =>
    api.patch<Tariff>(`/admin/tariffs/${id}`, body),
  deleteTariff: (id: string) => api.delete<{ success: boolean }>(`/admin/tariffs/${id}`),

  domains: () => api.get<AdminDomainItem[]>("/admin/domains"),

  zone: () => api.get<Zone>("/admin/zone"),
  updateZone: (body: Partial<Omit<Zone, "configured" | "deployable">>) =>
    api.patch<Zone>("/admin/zone", body),
  deployZone: () =>
    api.post<{ transaction: TonConnectTransaction; domain: string }>("/admin/zone/deploy"),
  stats: () => api.get<AdminStats>("/admin/stats"),
};
