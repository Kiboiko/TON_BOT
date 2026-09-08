/**
 * B3. Каталог блоков и шесть типов шаблонов.
 *
 * Структура повторяет docs/content_json.md — тот же словарь блоков, что понимает
 * backend-рендер. Поля описаны декларативно (FieldSpec), поэтому редактор блока
 * строится автоматически, а новый блок добавляется одной записью здесь.
 */
import type { Block, BlockType, SiteContent, SiteType } from "../api/types";

export type FieldKind = "text" | "textarea" | "url" | "image" | "select";

export interface FieldSpec {
  key: string;
  label: { ru: string; en: string };
  kind: FieldKind;
  placeholder?: string;
  options?: { value: string; label: { ru: string; en: string } }[];
}

export interface BlockSpec {
  type: BlockType;
  icon: string;
  title: { ru: string; en: string };
  hint: { ru: string; en: string };
  fields: FieldSpec[];
  /** Поля повторяющегося элемента: блок становится списком с добавлением строк. */
  itemFields?: FieldSpec[];
  itemLabel?: { ru: string; en: string };
}

const f = (
  key: string,
  ru: string,
  en: string,
  kind: FieldKind = "text",
  placeholder?: string,
): FieldSpec => ({ key, label: { ru, en }, kind, placeholder });

export const BLOCK_CATALOG: BlockSpec[] = [
  {
    type: "hero",
    icon: "👋",
    title: { ru: "Обложка", en: "Hero" },
    hint: { ru: "Имя, описание и фото", en: "Name, description and photo" },
    fields: [
      f("title", "Заголовок", "Title"),
      f("subtitle", "Описание", "Subtitle", "textarea"),
      f("image", "Фото", "Photo", "image"),
    ],
  },
  {
    type: "text",
    icon: "📝",
    title: { ru: "Текст", en: "Text" },
    hint: { ru: "Абзац текста с заголовком", en: "Paragraph with a heading" },
    fields: [f("title", "Заголовок", "Title"), f("text", "Текст", "Text", "textarea")],
  },
  {
    type: "links",
    icon: "🔗",
    title: { ru: "Ссылки", en: "Links" },
    hint: { ru: "Список ссылок — сколько нужно", en: "As many links as you need" },
    fields: [f("title", "Заголовок", "Title")],
    itemLabel: { ru: "Ссылка", en: "Link" },
    itemFields: [
      f("title", "Название", "Title"),
      f("url", "Ссылка", "URL", "url", "https://t.me/..."),
      f("subtitle", "Подпись", "Subtitle"),
      f("icon", "Иконка", "Icon", "text", "🔗"),
    ],
  },
  {
    type: "buttons",
    icon: "🔘",
    title: { ru: "Кнопки", en: "Buttons" },
    hint: { ru: "Кнопки связи и действий", en: "Contact and action buttons" },
    fields: [],
    itemLabel: { ru: "Кнопка", en: "Button" },
    itemFields: [
      f("title", "Текст", "Label"),
      f("url", "Ссылка", "URL", "url"),
      {
        key: "style",
        label: { ru: "Стиль", en: "Style" },
        kind: "select",
        options: [
          { value: "primary", label: { ru: "Заливка", en: "Filled" } },
          { value: "secondary", label: { ru: "Спокойная", en: "Soft" } },
          { value: "outline", label: { ru: "Контур", en: "Outline" } },
        ],
      },
      {
        key: "size",
        label: { ru: "Размер", en: "Size" },
        kind: "select",
        options: [
          { value: "md", label: { ru: "Обычный", en: "Medium" } },
          { value: "sm", label: { ru: "Маленький", en: "Small" } },
          { value: "lg", label: { ru: "Крупный", en: "Large" } },
        ],
      },
      {
        key: "color",
        label: { ru: "Цвет", en: "Colour" },
        kind: "select",
        options: [
          { value: "accent", label: { ru: "Акцент сайта", en: "Site accent" } },
          { value: "dark", label: { ru: "Тёмный", en: "Dark" } },
          { value: "light", label: { ru: "Светлый", en: "Light" } },
          { value: "green", label: { ru: "Зелёный", en: "Green" } },
          { value: "red", label: { ru: "Красный", en: "Red" } },
          { value: "orange", label: { ru: "Оранжевый", en: "Orange" } },
          { value: "purple", label: { ru: "Фиолетовый", en: "Purple" } },
          { value: "pink", label: { ru: "Розовый", en: "Pink" } },
        ],
      },
    ],
  },
  {
    type: "socials",
    icon: "💬",
    title: { ru: "Соцсети", en: "Socials" },
    hint: { ru: "Круглые иконки соцсетей", en: "Round social icons" },
    fields: [],
    itemLabel: { ru: "Соцсеть", en: "Social" },
    itemFields: [
      f("network", "Название", "Network", "text", "Telegram"),
      f("icon", "Иконка", "Icon", "text", "✈️"),
      f("url", "Ссылка", "URL", "url"),
    ],
  },
  {
    type: "contacts",
    icon: "📇",
    title: { ru: "Контакты", en: "Contacts" },
    hint: { ru: "Почта, телефон, адрес", en: "Email, phone, address" },
    fields: [f("title", "Заголовок", "Title")],
    itemLabel: { ru: "Контакт", en: "Contact" },
    itemFields: [
      f("label", "Подпись", "Label", "text", "Почта"),
      f("value", "Значение", "Value"),
      f("url", "Ссылка", "URL", "url", "mailto:..."),
    ],
  },
  {
    type: "features",
    icon: "✨",
    title: { ru: "Преимущества", en: "Features" },
    hint: { ru: "Плитки с иконкой и текстом", en: "Tiles with icon and text" },
    fields: [f("title", "Заголовок", "Title")],
    itemLabel: { ru: "Преимущество", en: "Feature" },
    itemFields: [
      f("icon", "Иконка", "Icon", "text", "✦"),
      f("title", "Название", "Title"),
      f("text", "Описание", "Text", "textarea"),
    ],
  },
  {
    type: "product",
    icon: "🛍",
    title: { ru: "Товар / услуга", en: "Product" },
    hint: { ru: "Карточка с ценой и кнопкой", en: "Card with price and button" },
    fields: [
      f("title", "Название", "Title"),
      f("description", "Описание", "Description", "textarea"),
      f("price", "Цена", "Price", "text", "3 000 ₽"),
      f("image", "Изображение", "Image", "image"),
      f("button_title", "Текст кнопки", "Button label"),
      f("button_url", "Ссылка кнопки", "Button URL", "url"),
    ],
  },
  {
    type: "cta",
    icon: "🎯",
    title: { ru: "Призыв к действию", en: "Call to action" },
    hint: { ru: "Блок с кнопкой заявки", en: "Block with an action button" },
    fields: [
      f("title", "Заголовок", "Title"),
      f("text", "Текст", "Text", "textarea"),
      f("button_title", "Текст кнопки", "Button label"),
      f("url", "Ссылка", "URL", "url"),
    ],
  },
  {
    type: "gallery",
    icon: "🖼",
    title: { ru: "Галерея", en: "Gallery" },
    hint: { ru: "Сетка работ или фото", en: "Grid of works or photos" },
    fields: [f("title", "Заголовок", "Title")],
    itemLabel: { ru: "Работа", en: "Work" },
    itemFields: [f("image", "Изображение", "Image", "image"), f("title", "Подпись", "Caption")],
  },
  {
    type: "event_info",
    icon: "📅",
    title: { ru: "О событии", en: "Event info" },
    hint: { ru: "Афиша, дата, место", en: "Poster, date, place" },
    fields: [
      f("title", "Название", "Title"),
      f("poster", "Афиша", "Poster", "image"),
      f("date", "Дата", "Date", "text", "12 июня"),
      f("time", "Время", "Time", "text", "19:00"),
      f("place", "Место", "Place"),
      f("address", "Адрес", "Address"),
    ],
  },
  {
    type: "schedule",
    icon: "🗓",
    title: { ru: "Программа", en: "Schedule" },
    hint: { ru: "Расписание по времени", en: "Timed programme" },
    fields: [f("title", "Заголовок", "Title")],
    itemLabel: { ru: "Пункт", en: "Item" },
    itemFields: [
      f("time", "Время", "Time", "text", "19:00"),
      f("title", "Что", "What"),
      f("text", "Описание", "Details", "textarea"),
    ],
  },
  {
    type: "ton_info",
    icon: "💎",
    title: { ru: "О TON-проекте", en: "TON project" },
    hint: { ru: "Тикер, контракт, сеть", en: "Ticker, contract, network" },
    fields: [
      f("title", "Заголовок", "Title"),
      f("ticker", "Тикер", "Ticker", "text", "MJT"),
      f("contract_address", "Адрес контракта", "Contract address", "text", "EQ..."),
      f("network", "Сеть", "Network", "text", "mainnet"),
      f("supply", "Эмиссия", "Supply"),
    ],
  },
  {
    type: "jetton",
    icon: "🪙",
    title: { ru: "Jetton", en: "Jetton" },
    hint: { ru: "Адрес жетона и ссылки", en: "Jetton address and links" },
    fields: [
      f("title", "Заголовок", "Title"),
      f("jetton_address", "Адрес jetton", "Jetton address", "text", "EQ..."),
      f("dex_url", "Ссылка на DEX", "DEX URL", "url"),
      f("explorer_url", "Explorer", "Explorer", "url"),
    ],
  },
  {
    type: "image",
    icon: "📷",
    title: { ru: "Картинка", en: "Image" },
    hint: { ru: "Изображение во всю ширину", en: "Full-width image" },
    fields: [f("image", "Изображение", "Image", "image"), f("alt", "Описание", "Alt text")],
  },
  {
    type: "divider",
    icon: "➖",
    title: { ru: "Разделитель", en: "Divider" },
    hint: { ru: "Тонкая линия между блоками", en: "Thin line between blocks" },
    fields: [],
  },
];

export const BLOCK_SPECS: Record<string, BlockSpec> = Object.fromEntries(
  BLOCK_CATALOG.map((spec) => [spec.type, spec]),
);

export interface TemplateSpec {
  type: SiteType;
  icon: string;
  title: { ru: string; en: string };
  description: { ru: string; en: string };
  blocks: BlockType[];
  /** Возможность оплачивается разово на каждый сайт, а не подпиской. */
  paidOnce?: boolean;
}

/** Шесть шаблонов из ТЗ плюс «Свой код». Набор блоков совпадает с backend. */
export const TEMPLATES: TemplateSpec[] = [
  {
    type: "visitka",
    icon: "🪪",
    title: { ru: "Визитка", en: "Business card" },
    description: { ru: "Имя, описание, кнопки связи, соцсети, фото", en: "Name, bio, contacts, socials" },
    blocks: ["hero", "text", "buttons", "socials", "contacts"],
  },
  {
    type: "links",
    icon: "🔗",
    title: { ru: "Ссылки", en: "Links page" },
    description: { ru: "Обложка, список ссылок, контакты", en: "Cover, link list, contacts" },
    blocks: ["hero", "links", "socials"],
  },
  {
    type: "landing",
    icon: "🚀",
    title: { ru: "Лендинг", en: "Landing" },
    description: { ru: "Обложка, преимущества, товар, CTA", en: "Cover, features, product, CTA" },
    blocks: ["hero", "features", "product", "cta", "contacts"],
  },
  {
    type: "portfolio",
    icon: "🎨",
    title: { ru: "Портфолио", en: "Portfolio" },
    description: { ru: "Галерея работ, описание, контакты", en: "Works gallery, about, contacts" },
    blocks: ["hero", "text", "gallery", "contacts"],
  },
  {
    type: "events",
    icon: "🎪",
    title: { ru: "События", en: "Events" },
    description: { ru: "Афиша, дата, место, программа", en: "Poster, date, place, programme" },
    blocks: ["hero", "event_info", "schedule", "cta", "contacts"],
  },
  {
    type: "ton_project",
    icon: "💎",
    title: { ru: "TON-проект", en: "TON project" },
    description: { ru: "Тикер, контракт, jetton, ссылки", en: "Ticker, contract, jetton, links" },
    blocks: ["hero", "text", "ton_info", "jetton", "links", "socials"],
  },
  {
    // страница целиком из своего кода: блоков нет, редактируется на отдельном экране
    type: "custom_code",
    icon: "⌨️",
    title: { ru: "Свой код", en: "Custom code" },
    description: {
      ru: "Страница целиком на своём HTML, CSS и JS",
      en: "A whole page of your own HTML, CSS and JS",
    },
    blocks: [],
    paidOnce: true,
  },
];

export function blockId(): string {
  return `b${Math.random().toString(36).slice(2, 9)}`;
}

/** Значения по умолчанию для новой строки блока-списка. */
export const ITEM_DEFAULTS: Partial<Record<BlockType, Record<string, unknown>>> = {
  buttons: { style: "primary", size: "md", color: "accent" },
};

/**
 * Пустой блок нужного типа.
 *
 * У блока-списка сразу заводим одну строку: с пустым `items` блок ничего не
 * рендерил, и добавленные ссылки выглядели так, будто конструктор их потерял —
 * на месте блока оставалась пустота.
 */
export function createBlock(type: BlockType, title = ""): Block {
  const spec = BLOCK_SPECS[type];
  const props: Record<string, unknown> = {};
  if (spec?.itemFields) props.items = [{ ...(ITEM_DEFAULTS[type] ?? {}) }];
  if (type === "hero") {
    props.title = title || "";
    props.subtitle = "";
    props.image = "";
  }
  return { id: blockId(), type, props };
}

/** Скелет content_json нового сайта — та же структура, что создаёт backend. */
export function defaultContentFor(siteType: SiteType, title = ""): SiteContent {
  const template = TEMPLATES.find((t) => t.type === siteType) ?? TEMPLATES[0];
  return {
    version: 1,
    meta: { title, description: "", lang: "ru" },
    theme: {
      preset: siteType === "ton_project" ? "ton" : "light",
      accent: "#0098ea",
      background: "",
      background_image: "",
      background_dim: 0,
    },
    blocks: template.blocks.map((type) => createBlock(type, type === "hero" ? title : "")),
  };
}

export const THEME_PRESET_LIST: { value: SiteContent["theme"]["preset"]; label: string; swatch: string }[] = [
  { value: "light", label: "Светлая", swatch: "#f6f7fb" },
  { value: "dark", label: "Тёмная", swatch: "#0f1115" },
  { value: "aurora", label: "Aurora", swatch: "linear-gradient(160deg,#0f2027,#2c5364)" },
  { value: "sunrise", label: "Sunrise", swatch: "linear-gradient(160deg,#ff9a9e,#fbc2eb)" },
  { value: "mint", label: "Mint", swatch: "linear-gradient(160deg,#d3f4e8,#e8f7ef)" },
  { value: "ton", label: "TON", swatch: "linear-gradient(160deg,#0098ea,#0f172a)" },
];

export const ACCENT_COLORS = ["#0098ea", "#7c5cff", "#ff5c8a", "#12b981", "#f59e0b", "#111827"];
