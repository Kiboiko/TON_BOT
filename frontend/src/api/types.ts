/**
 * Типы API-контракта (раздел 4 ТЗ).
 * Источник истины — docs/openapi.json, сгенерированный backend-ом.
 */

export type Language = "ru" | "en";
export type Theme = "light" | "dark";

export type SiteType =
  | "visitka"
  | "links"
  | "landing"
  | "portfolio"
  | "events"
  | "ton_project"
  | "custom_code";

export type SiteStatus =
  | "draft"
  | "publishing"
  | "published"
  | "publish_error"
  | "expired";

export type TariffDuration = "month" | "3month" | "6month" | "12month" | "forever";
export type TariffKind = "base" | "pro" | "custom_code";
export type SubscriptionStatus = "active" | "expiring_soon" | "expired" | "manual";
export type PaymentPurpose = "subscription" | "custom_code" | "domain";
export type PaymentStatus = "pending" | "confirmed" | "failed";

export interface User {
  id: string;
  telegram_id: number;
  username: string | null;
  first_name: string | null;
  wallet_address: string | null;
  language: Language;
  theme: Theme;
  is_admin: boolean;
  created_at: string;
}

export interface AuthResponse {
  user: User;
  is_admin: boolean;
}

/** Блок конструктора. Структура согласована в docs/content_json.md. */
export interface Block {
  id: string;
  type: BlockType;
  props: Record<string, unknown>;
  hidden?: boolean;
}

export type BlockType =
  | "hero"
  | "text"
  | "links"
  | "buttons"
  | "socials"
  | "contacts"
  | "features"
  | "product"
  | "cta"
  | "gallery"
  | "event_info"
  | "schedule"
  | "ton_info"
  | "jetton"
  | "image"
  | "divider";

export type ThemePreset = "light" | "dark" | "aurora" | "sunrise" | "mint" | "ton";

export interface SiteContent {
  version: number;
  meta: { title?: string; description?: string; lang?: Language };
  theme: {
    preset: ThemePreset;
    accent: string;
    /** свой CSS-фон: цвет или градиент */
    background?: string;
    /** ссылка на загруженную фотографию фона */
    background_image?: string;
    /** затемнение фотографии, 0–90 % — чтобы текст читался */
    background_dim?: number;
  };
  blocks: Block[];
}

export interface Site {
  id: string;
  type: SiteType;
  title: string;
  content_json: SiteContent;
  custom_code: CustomCode | null;
  /** возможность своего кода оплачена для этого сайта (разовый платёж) */
  custom_code_paid: boolean;
  domain: string | null;
  dns_item_address: string | null;
  collection_address: string | null;
  status: SiteStatus;
  storage_bag_id: string | null;
  published_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface SiteListItem {
  id: string;
  type: SiteType;
  title: string;
  domain: string | null;
  status: SiteStatus;
  published_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface CustomCode {
  html: string;
  css: string;
  js: string;
}

export interface TonConnectMessage {
  address: string;
  amount: string;
  payload?: string | null;
  stateInit?: string | null;
}

export interface TonConnectTransaction {
  validUntil: number;
  messages: TonConnectMessage[];
  network?: string | null;
}

export interface DomainCheck {
  available: boolean;
  status: string; // free / taken / unknown
  domain: string; // полный адрес: имя.зона.ton
  zone: string;
  item_address: string | null;
  owner: string | null;
}

export interface Zone {
  domain: string;
  dns_item_address: string;
  collection_address: string;
  mode: "proxy" | "sbt";
  configured: boolean;
  deployable: boolean;
}

/** Блок «Об авторе проекта»: текст и ссылка задаются в админке. */
export interface About {
  title: string;
  text: string;
  link_url: string;
  link_label: string;
}

export interface Tariff {
  id: string;
  name: string;
  description: string | null;
  sites_limit: number;
  duration: TariffDuration;
  price_ton: string;
  kind: TariffKind;
  is_active: boolean;
}

export interface Subscription {
  id: string;
  tariff: Tariff | null;
  site_id: string | null;
  starts_at: string;
  expires_at: string | null;
  is_forever: boolean;
  is_trial: boolean;
  status: SubscriptionStatus;
  granted_by_admin: boolean;
}

export interface Payment {
  id: string;
  tx_hash: string | null;
  amount: string;
  purpose: PaymentPurpose;
  related_id: string | null;
  status: PaymentStatus;
  created_at: string;
  confirmed_at: string | null;
}

export interface PublishStatus {
  status: SiteStatus;
  storage_bag_id: string | null;
  published_at: string | null;
  error: string | null;
  /** http-ссылка на опубликованный сайт — работает и до привязки домена .ton */
  public_url: string | null;
}

export interface AdminUserListItem {
  id: string;
  telegram_id: number;
  username: string | null;
  wallet_address: string | null;
  is_admin: boolean;
  is_blocked: boolean;
  created_at: string;
  sites_count: number;
  active_subscriptions: number;
}

export interface AdminUsersResponse {
  users: AdminUserListItem[];
  total: number;
  page: number;
  per_page: number;
}

export interface AdminUserDetail {
  user: User;
  sites: SiteListItem[];
  subscriptions: Subscription[];
  payments: Payment[];
}

export interface AdminDomainItem {
  domain: string;
  status: SiteStatus;
  site_id: string;
  site_title: string;
  user_id: string;
  telegram_id: number;
  published_at: string | null;
}

export interface AdminStats {
  total_users: number;
  total_sites: number;
  published_sites: number;
  active_subscriptions: number;
  revenue: string;
  revenue_last_30d: string;
  payments_confirmed: number;
}

/** Единый формат ошибки: { error: { code, message } } */
export interface ApiErrorBody {
  code: string;
  message: string;
  details?: Record<string, unknown>;
}
