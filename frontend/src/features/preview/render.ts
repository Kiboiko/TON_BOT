/**
 * Клиентский рендер content_json (B5).
 *
 * Повторяет вывод backend-рендера (app/services/renderer.py), чтобы предпросмотр
 * в конструкторе был мгновенным и не требовал запроса на каждый ввод символа.
 * Перед публикацией страница всё равно рендерится backend-ом — он источник истины,
 * поэтому здесь так же строго экранируется текст и фильтруются ссылки.
 */
import type { Block, CustomCode, SiteContent, ThemePreset } from "../../api/types";

const ALLOWED_SCHEMES = ["http:", "https:", "mailto:", "tel:", "tg:", "ton:"];

export const THEME_PRESETS: Record<ThemePreset, { bg: string; surface: string; text: string; muted: string }> = {
  light: { bg: "#f6f7fb", surface: "#ffffff", text: "#12151c", muted: "#6b7280" },
  dark: { bg: "#0f1115", surface: "#181b22", text: "#f3f4f6", muted: "#9aa3b2" },
  aurora: {
    bg: "linear-gradient(160deg,#0f2027 0%,#203a43 50%,#2c5364 100%)",
    surface: "rgba(255,255,255,.07)",
    text: "#eaf2ff",
    muted: "#a9bcd0",
  },
  sunrise: {
    bg: "linear-gradient(160deg,#ff9a9e 0%,#fad0c4 50%,#fbc2eb 100%)",
    surface: "rgba(255,255,255,.55)",
    text: "#2b1c26",
    muted: "#6c5560",
  },
  mint: {
    bg: "linear-gradient(160deg,#d3f4e8 0%,#e8f7ef 100%)",
    surface: "#ffffff",
    text: "#12261f",
    muted: "#5d7a70",
  },
  ton: {
    bg: "linear-gradient(160deg,#0098ea 0%,#0f172a 100%)",
    surface: "rgba(255,255,255,.08)",
    text: "#f0f9ff",
    muted: "#b8d8ee",
  },
};

export function escapeHtml(value: unknown): string {
  if (value === null || value === undefined) return "";
  return String(value)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

function multiline(value: unknown): string {
  return escapeHtml(value).replace(/\n/g, "<br>");
}

export function safeUrl(value: unknown): string {
  if (typeof value !== "string") return "";
  const raw = value.trim();
  if (!raw) return "";
  if (raw.startsWith("/") || raw.startsWith("#")) return raw;
  try {
    const parsed = new URL(raw);
    return ALLOWED_SCHEMES.includes(parsed.protocol) ? raw : "";
  } catch {
    return raw.includes(".") ? `https://${raw}` : "";
  }
}

function img(src: unknown, alt: unknown = "", cls = ""): string {
  const url = safeUrl(src);
  if (!url) return "";
  return `<img class="${cls}" src="${escapeHtml(url)}" alt="${escapeHtml(alt)}" loading="lazy">`;
}

function list(props: Record<string, unknown>, ...keys: string[]): Record<string, unknown>[] {
  for (const key of keys) {
    const value = props[key];
    if (Array.isArray(value)) return value.filter((i) => typeof i === "object" && i !== null) as Record<string, unknown>[];
  }
  return [];
}

const renderers: Record<string, (p: Record<string, unknown>) => string> = {
  hero: (p) => {
    const avatar = img(p.image ?? p.avatar, p.title, "hero-img");
    return `<section class="block hero">${avatar ? `<div class="hero-avatar">${avatar}</div>` : ""}${
      p.title ? `<h1>${escapeHtml(p.title)}</h1>` : ""
    }${p.subtitle ? `<p class="subtitle">${multiline(p.subtitle)}</p>` : ""}</section>`;
  },
  text: (p) =>
    `<section class="block card">${p.title ? `<h2>${escapeHtml(p.title)}</h2>` : ""}${
      p.text ? `<p>${multiline(p.text)}</p>` : ""
    }</section>`,
  links: (p) => {
    const rows = list(p, "items", "links")
      .map((item) => {
        const url = safeUrl(item.url);
        if (!url) return "";
        return `<a class="link-row" href="${escapeHtml(url)}" target="_blank" rel="noopener noreferrer">
          <span class="link-icon">${escapeHtml(item.icon ?? "")}</span>
          <span class="link-body"><span class="link-title">${escapeHtml(item.title ?? url)}</span>${
            item.subtitle ? `<span class="link-sub">${escapeHtml(item.subtitle)}</span>` : ""
          }</span></a>`;
      })
      .join("");
    if (!rows) return "";
    return `<section class="block links">${p.title ? `<h2>${escapeHtml(p.title)}</h2>` : ""}${rows}</section>`;
  },
  buttons: (p) => {
    const btns = list(p, "items", "buttons")
      .map((item) => {
        const url = safeUrl(item.url);
        if (!url) return "";
        const style = item.style === "secondary" ? "btn-secondary" : "btn-primary";
        return `<a class="btn ${style}" href="${escapeHtml(url)}" target="_blank" rel="noopener noreferrer">${escapeHtml(
          item.title ?? "Открыть",
        )}</a>`;
      })
      .join("");
    return btns ? `<section class="block buttons">${btns}</section>` : "";
  },
  socials: (p) => {
    const icons = list(p, "items", "socials")
      .map((item) => {
        const url = safeUrl(item.url);
        if (!url) return "";
        const label = item.network ?? item.title ?? "link";
        return `<a class="social" href="${escapeHtml(url)}" target="_blank" rel="noopener noreferrer" title="${escapeHtml(
          label,
        )}">${escapeHtml(item.icon ?? label)}</a>`;
      })
      .join("");
    return icons ? `<section class="block socials">${icons}</section>` : "";
  },
  contacts: (p) => {
    const rows = list(p, "items")
      .map((item) => {
        if (!item.value) return "";
        const url = safeUrl(item.url ?? "");
        const value = url
          ? `<a href="${escapeHtml(url)}" target="_blank" rel="noopener noreferrer">${escapeHtml(item.value)}</a>`
          : escapeHtml(item.value);
        return `<div class="contact-row"><span>${escapeHtml(item.label ?? "")}</span><b>${value}</b></div>`;
      })
      .join("");
    if (!rows) return "";
    return `<section class="block card contacts"><h2>${escapeHtml(p.title ?? "Контакты")}</h2>${rows}</section>`;
  },
  features: (p) => {
    const cards = list(p, "items")
      .map(
        (item) =>
          `<div class="feature"><div class="feature-icon">${escapeHtml(item.icon ?? "✦")}</div><h3>${escapeHtml(
            item.title ?? "",
          )}</h3><p>${multiline(item.text ?? "")}</p></div>`,
      )
      .join("");
    if (!cards) return "";
    return `<section class="block features">${p.title ? `<h2>${escapeHtml(p.title)}</h2>` : ""}<div class="feature-grid">${cards}</div></section>`;
  },
  product: (p) => {
    const url = safeUrl(p.button_url);
    return `<section class="block card product">${img(p.image, p.title, "product-img")}${
      p.title ? `<h2>${escapeHtml(p.title)}</h2>` : ""
    }${p.description ? `<p>${multiline(p.description)}</p>` : ""}${
      p.price ? `<div class="price">${escapeHtml(p.price)}</div>` : ""
    }${
      url
        ? `<a class="btn btn-primary" href="${escapeHtml(url)}" target="_blank" rel="noopener noreferrer">${escapeHtml(
            p.button_title ?? "Купить",
          )}</a>`
        : ""
    }</section>`;
  },
  cta: (p) => {
    const url = safeUrl(p.url);
    return `<section class="block cta">${p.title ? `<h2>${escapeHtml(p.title)}</h2>` : ""}${
      p.text ? `<p>${multiline(p.text)}</p>` : ""
    }${
      url
        ? `<a class="btn btn-primary" href="${escapeHtml(url)}" target="_blank" rel="noopener noreferrer">${escapeHtml(
            p.button_title ?? "Оставить заявку",
          )}</a>`
        : ""
    }</section>`;
  },
  gallery: (p) => {
    const cells = list(p, "items")
      .map((item) => {
        const image = img(item.image, item.title, "gallery-img");
        if (!image) return "";
        return `<figure>${image}${item.title ? `<figcaption>${escapeHtml(item.title)}</figcaption>` : ""}</figure>`;
      })
      .join("");
    if (!cells) return "";
    return `<section class="block gallery">${p.title ? `<h2>${escapeHtml(p.title)}</h2>` : ""}<div class="gallery-grid">${cells}</div></section>`;
  },
  event_info: (p) => {
    const rows = (
      [
        ["date", "Дата"],
        ["time", "Время"],
        ["place", "Место"],
        ["address", "Адрес"],
      ] as const
    )
      .filter(([key]) => p[key])
      .map(([key, label]) => `<div class="contact-row"><span>${label}</span><b>${escapeHtml(p[key])}</b></div>`)
      .join("");
    if (!rows && !p.poster) return "";
    return `<section class="block card event">${img(p.poster, p.title, "poster")}${
      p.title ? `<h2>${escapeHtml(p.title)}</h2>` : ""
    }${rows}</section>`;
  },
  schedule: (p) => {
    const rows = list(p, "items")
      .map(
        (item) =>
          `<div class="schedule-row"><span class="time">${escapeHtml(item.time ?? "")}</span><span class="what"><b>${escapeHtml(
            item.title ?? "",
          )}</b>${item.text ? `<p>${multiline(item.text)}</p>` : ""}</span></div>`,
      )
      .join("");
    if (!rows) return "";
    return `<section class="block card schedule"><h2>${escapeHtml(p.title ?? "Программа")}</h2>${rows}</section>`;
  },
  ton_info: (p) => {
    const rows = (
      [
        ["ticker", "Тикер"],
        ["contract_address", "Контракт"],
        ["network", "Сеть"],
        ["supply", "Эмиссия"],
      ] as const
    )
      .filter(([key]) => p[key])
      .map(
        ([key, label]) => `<div class="contact-row"><span>${label}</span><b class="mono">${escapeHtml(p[key])}</b></div>`,
      )
      .join("");
    if (!rows) return "";
    return `<section class="block card ton-info"><h2>${escapeHtml(p.title ?? "О проекте")}</h2>${rows}</section>`;
  },
  jetton: (p) => {
    const rows = (
      [
        ["jetton_address", "Jetton"],
        ["dex_url", "DEX"],
        ["explorer_url", "Explorer"],
      ] as const
    )
      .filter(([key]) => p[key])
      .map(([key, label]) => {
        const url = safeUrl(p[key]);
        const body = url
          ? `<a class="mono" href="${escapeHtml(url)}" target="_blank" rel="noopener noreferrer">${escapeHtml(p[key])}</a>`
          : `<b class="mono">${escapeHtml(p[key])}</b>`;
        return `<div class="contact-row"><span>${label}</span>${body}</div>`;
      })
      .join("");
    if (!rows) return "";
    return `<section class="block card jetton"><h2>${escapeHtml(p.title ?? "Jetton")}</h2>${rows}</section>`;
  },
  image: (p) => {
    const image = img(p.image ?? p.url, p.alt, "wide-img");
    return image ? `<section class="block image">${image}</section>` : "";
  },
  divider: () => `<hr class="divider">`,
};

const ALIASES: Record<string, string> = { about: "text", advantages: "features", works: "gallery" };

const CSS = `
*{box-sizing:border-box}
body{margin:0;padding:0;background:var(--bg);color:var(--text);font-family:var(--font);
  -webkit-font-smoothing:antialiased;line-height:1.5}
.page{max-width:640px;margin:0 auto;padding:28px 18px 64px;display:flex;flex-direction:column;gap:18px}
h1{font-size:28px;margin:0 0 6px;letter-spacing:-.02em}
h2{font-size:19px;margin:0 0 12px;letter-spacing:-.01em}
h3{font-size:16px;margin:0 0 6px}
p{margin:0 0 8px;color:var(--muted)}
a{color:var(--accent)}
.card{background:var(--surface);border-radius:18px;padding:18px;
  box-shadow:0 1px 2px rgba(0,0,0,.05),0 8px 24px rgba(0,0,0,.06)}
.hero{text-align:center;padding-top:12px}
.hero-avatar{margin-bottom:14px}
.hero-img{width:112px;height:112px;border-radius:50%;object-fit:cover;box-shadow:0 10px 30px rgba(0,0,0,.18)}
.subtitle{color:var(--muted);margin:0 auto;max-width:34ch}
.links{display:flex;flex-direction:column;gap:10px}
.link-row{display:flex;align-items:center;gap:12px;background:var(--surface);border-radius:14px;padding:14px 16px;
  text-decoration:none;color:var(--text);box-shadow:0 1px 2px rgba(0,0,0,.05);transition:transform .15s ease}
.link-row:hover{transform:translateY(-1px)}
.link-icon{font-size:20px;min-width:24px;text-align:center}
.link-title{display:block;font-weight:600}
.link-sub{display:block;font-size:13px;color:var(--muted)}
.buttons{display:flex;flex-direction:column;gap:10px}
.btn{display:block;text-align:center;padding:14px 18px;border-radius:14px;font-weight:600;text-decoration:none}
.btn-primary{background:var(--accent);color:#fff}
.btn-secondary{background:var(--surface);color:var(--text);border:1px solid rgba(127,127,127,.25)}
.socials{display:flex;gap:10px;justify-content:center;flex-wrap:wrap}
.social{width:44px;height:44px;border-radius:50%;display:flex;align-items:center;justify-content:center;
  background:var(--surface);text-decoration:none;font-size:18px}
.contact-row,.schedule-row{display:flex;justify-content:space-between;gap:12px;padding:8px 0;
  border-bottom:1px solid rgba(127,127,127,.15)}
.contact-row:last-child,.schedule-row:last-child{border-bottom:0}
.contact-row span{color:var(--muted)}
.feature-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px}
.feature{background:var(--surface);border-radius:16px;padding:16px}
.feature-icon{font-size:22px;margin-bottom:6px}
.gallery-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(150px,1fr));gap:10px}
.gallery-grid figure{margin:0}
.gallery-img,.wide-img,.poster,.product-img{width:100%;border-radius:14px;object-fit:cover;display:block}
figcaption{font-size:13px;color:var(--muted);padding:6px 2px}
.price{font-size:22px;font-weight:700;margin:8px 0}
.cta{background:var(--surface);border-radius:18px;padding:22px;text-align:center}
.mono{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:13px;word-break:break-all}
.divider{border:0;border-top:1px solid rgba(127,127,127,.2);margin:6px 0}
.custom-frame{width:100%;border:0;border-radius:16px;background:var(--surface);min-height:120px}
.footer{text-align:center;color:var(--muted);font-size:12px;padding-top:12px}
.empty-hint{text-align:center;color:var(--muted);padding:40px 12px;font-size:14px}
`;

const FONT =
  "-apple-system,BlinkMacSystemFont,'SF Pro Display','Segoe UI',Roboto,Inter,system-ui,sans-serif";

function isSafeBackground(value: string): boolean {
  const lowered = value.trim().toLowerCase();
  if (!lowered || lowered.length > 300) return false;
  if (["javascript:", "expression(", "</", "@import", "\\"].some((bad) => lowered.includes(bad))) return false;
  if (lowered.startsWith("url(")) return Boolean(safeUrl(value.slice(4, -1).replace(/['"]/g, "").trim()));
  return /^[#\w\s(),.%-]+$/.test(value.trim());
}

function safeColor(value: unknown, fallback: string): string {
  if (typeof value === "string" && /^(#[0-9a-fA-F]{3,8}|rgba?\([\d\s.,%]+\))$/.test(value.trim())) {
    return value.trim();
  }
  return fallback;
}

export function renderBlocks(blocks: Block[] | undefined): string {
  if (!Array.isArray(blocks)) return "";
  return blocks
    .filter((block) => block && !block.hidden)
    .map((block) => {
      const type = ALIASES[block.type] ?? block.type;
      const renderer = renderers[type];
      if (!renderer) return "";
      try {
        return renderer((block.props ?? {}) as Record<string, unknown>);
      } catch {
        return "";
      }
    })
    .join("\n");
}

export function renderCustomCode(code: CustomCode | null | undefined): string {
  if (!code) return "";
  const { html = "", css = "", js = "" } = code;
  if (!html && !css && !js) return "";
  const doc = `<!DOCTYPE html><html><head><meta charset='utf-8'>
<meta name='viewport' content='width=device-width,initial-scale=1'>
<style>body{margin:0;font-family:${FONT}}${css}</style></head>
<body>${html}<script>${js}<\/script></body></html>`;
  return `<section class="block custom"><iframe class="custom-frame" sandbox="allow-scripts" referrerpolicy="no-referrer" srcdoc="${escapeHtml(
    doc,
  )}"></iframe></section>`;
}

export interface RenderOptions {
  title?: string;
  domain?: string | null;
  customCode?: CustomCode | null;
  emptyHint?: string;
}

/** Собирает полную HTML-страницу сайта — то же, что отдаст backend при публикации. */
export function renderSite(content: SiteContent | undefined, options: RenderOptions = {}): string {
  const meta = content?.meta ?? {};
  const theme = content?.theme ?? { preset: "light" as ThemePreset, accent: "#0098ea" };
  const preset = THEME_PRESETS[theme.preset] ?? THEME_PRESETS.light;
  const background =
    theme.background && isSafeBackground(theme.background) ? theme.background : preset.bg;

  let body = renderBlocks(content?.blocks) + renderCustomCode(options.customCode);
  if (!body.trim() && options.emptyHint) {
    body = `<div class="empty-hint">${escapeHtml(options.emptyHint)}</div>`;
  }

  return `<!DOCTYPE html>
<html lang="${escapeHtml(meta.lang ?? "ru")}">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<title>${escapeHtml(meta.title || options.title || "TON Site")}</title>
<meta name="description" content="${escapeHtml(meta.description ?? "")}">
<style>:root{--bg:${background};--surface:${preset.surface};--text:${preset.text};--muted:${preset.muted};--accent:${safeColor(
    theme.accent,
    "#0098ea",
  )};--font:${FONT}}
${CSS}</style>
</head>
<body>
<div class="page">
${body}
<div class="footer">${escapeHtml(options.domain ?? "")}</div>
</div>
</body>
</html>`;
}
