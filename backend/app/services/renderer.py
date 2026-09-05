"""A4 (часть 1). Генерация статического HTML/CSS/JS из content_json.

Схема content_json — общий контракт с Разработчиком B, описана в docs/content_json.md.
Кратко:

    {
      "version": 1,
      "meta":  { "title": str, "description": str, "lang": "ru"|"en" },
      "theme": { "preset": str, "accent": "#rrggbb", "background": str, "font": str },
      "blocks": [ { "id": str, "type": str, "props": {...} }, ... ]
    }

Тип сайта (visitka/links/landing/portfolio/events/ton_project) задаёт лишь набор
блоков по умолчанию — рендер блоков общий, поэтому конструктор у B остаётся гибким.

Безопасность: весь пользовательский текст экранируется, ссылки пропускаются только
с разрешёнными схемами, а премиум-блок «Свой код» изолируется в sandbox-iframe и
никогда не исполняется в контексте страницы-хоста (требование раздела 8 ТЗ).
"""
from __future__ import annotations

import json
import re
from typing import Any, Callable
from urllib.parse import urlparse

from markupsafe import Markup, escape

ALLOWED_URL_SCHEMES = {"http", "https", "mailto", "tel", "tg", "ton"}

THEME_PRESETS: dict[str, dict[str, str]] = {
    "light": {"bg": "#f6f7fb", "surface": "#ffffff", "text": "#12151c", "muted": "#6b7280"},
    "dark": {"bg": "#0f1115", "surface": "#181b22", "text": "#f3f4f6", "muted": "#9aa3b2"},
    "aurora": {
        "bg": "linear-gradient(160deg,#0f2027 0%,#203a43 50%,#2c5364 100%)",
        "surface": "rgba(255,255,255,.07)",
        "text": "#eaf2ff",
        "muted": "#a9bcd0",
    },
    "sunrise": {
        "bg": "linear-gradient(160deg,#ff9a9e 0%,#fad0c4 50%,#fbc2eb 100%)",
        "surface": "rgba(255,255,255,.55)",
        "text": "#2b1c26",
        "muted": "#6c5560",
    },
    "mint": {
        "bg": "linear-gradient(160deg,#d3f4e8 0%,#e8f7ef 100%)",
        "surface": "#ffffff",
        "text": "#12261f",
        "muted": "#5d7a70",
    },
    "ton": {
        "bg": "linear-gradient(160deg,#0098ea 0%,#0f172a 100%)",
        "surface": "rgba(255,255,255,.08)",
        "text": "#f0f9ff",
        "muted": "#b8d8ee",
    },
}

DEFAULT_BLOCKS: dict[str, list[str]] = {
    "visitka": ["hero", "text", "buttons", "socials", "contacts"],
    "links": ["hero", "links", "socials"],
    "landing": ["hero", "features", "product", "cta", "contacts"],
    "portfolio": ["hero", "text", "gallery", "contacts"],
    "events": ["hero", "event_info", "schedule", "cta", "contacts"],
    "ton_project": ["hero", "text", "ton_info", "jetton", "links", "socials"],
    # «Свой код» — страница целиком из HTML/CSS/JS пользователя, блоков нет
    "custom_code": [],
}


def safe_url(value: Any) -> str:
    """Пропускает только ссылки с разрешённой схемой; всё прочее — пустая строка."""
    if not isinstance(value, str):
        return ""
    value = value.strip()
    if not value:
        return ""
    if value.startswith("/") or value.startswith("#"):
        return value
    parsed = urlparse(value)
    if parsed.scheme and parsed.scheme.lower() in ALLOWED_URL_SCHEMES:
        return value
    if not parsed.scheme and "." in value:
        return f"https://{value}"
    return ""


def safe_color(value: Any, fallback: str = "") -> str:
    if isinstance(value, str) and re.fullmatch(r"#[0-9a-fA-F]{3,8}|rgba?\([\d\s.,%]+\)", value.strip()):
        return value.strip()
    return fallback


def _txt(value: Any) -> Markup:
    return escape(str(value)) if value is not None else Markup("")


def _multiline(value: Any) -> Markup:
    if value is None:
        return Markup("")
    return Markup("<br>").join(escape(line) for line in str(value).split("\n"))


def _img(src: Any, alt: Any = "", cls: str = "") -> Markup:
    url = safe_url(src)
    if not url:
        return Markup("")
    return Markup('<img class="{}" src="{}" alt="{}" loading="lazy">').format(cls, url, str(alt or ""))


# ------------------------------------------------------------------ блоки
def _block_hero(p: dict[str, Any]) -> Markup:
    avatar = _img(p.get("image") or p.get("avatar"), p.get("title", ""), "hero-img")
    parts = [Markup('<section class="block hero">')]
    if avatar:
        parts.append(Markup('<div class="hero-avatar">{}</div>').format(avatar))
    if p.get("title"):
        parts.append(Markup("<h1>{}</h1>").format(_txt(p["title"])))
    if p.get("subtitle"):
        parts.append(Markup('<p class="subtitle">{}</p>').format(_multiline(p["subtitle"])))
    parts.append(Markup("</section>"))
    return Markup("").join(parts)


def _block_text(p: dict[str, Any]) -> Markup:
    parts = [Markup('<section class="block card">')]
    if p.get("title"):
        parts.append(Markup("<h2>{}</h2>").format(_txt(p["title"])))
    if p.get("text"):
        parts.append(Markup("<p>{}</p>").format(_multiline(p["text"])))
    parts.append(Markup("</section>"))
    return Markup("").join(parts)


def _block_links(p: dict[str, Any]) -> Markup:
    items = p.get("items") or p.get("links") or []
    rows: list[Markup] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        url = safe_url(item.get("url"))
        if not url:
            continue
        icon = _txt(item.get("icon", ""))
        rows.append(
            Markup('<a class="link-row" href="{}" target="_blank" rel="noopener noreferrer">'
                   '<span class="link-icon">{}</span><span class="link-body"><span class="link-title">{}</span>'
                   '{}</span></a>').format(
                url,
                icon,
                _txt(item.get("title") or url),
                Markup('<span class="link-sub">{}</span>').format(_txt(item["subtitle"]))
                if item.get("subtitle")
                else Markup(""),
            )
        )
    if not rows:
        return Markup("")
    head = Markup("<h2>{}</h2>").format(_txt(p["title"])) if p.get("title") else Markup("")
    return Markup('<section class="block links">{}{}</section>').format(head, Markup("").join(rows))


def _block_buttons(p: dict[str, Any]) -> Markup:
    items = p.get("items") or p.get("buttons") or []
    btns: list[Markup] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        url = safe_url(item.get("url"))
        if not url:
            continue
        style = "btn-secondary" if item.get("style") == "secondary" else "btn-primary"
        btns.append(
            Markup('<a class="btn {}" href="{}" target="_blank" rel="noopener noreferrer">{}</a>').format(
                style, url, _txt(item.get("title") or "Открыть")
            )
        )
    if not btns:
        return Markup("")
    return Markup('<section class="block buttons">{}</section>').format(Markup("").join(btns))


def _block_socials(p: dict[str, Any]) -> Markup:
    items = p.get("items") or p.get("socials") or []
    icons: list[Markup] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        url = safe_url(item.get("url"))
        if not url:
            continue
        label = item.get("network") or item.get("title") or "link"
        icons.append(
            Markup('<a class="social" href="{}" target="_blank" rel="noopener noreferrer" '
                   'title="{}">{}</a>').format(url, _txt(label), _txt(item.get("icon") or label))
        )
    if not icons:
        return Markup("")
    return Markup('<section class="block socials">{}</section>').format(Markup("").join(icons))


def _block_contacts(p: dict[str, Any]) -> Markup:
    rows: list[Markup] = []
    for item in p.get("items") or []:
        if not isinstance(item, dict):
            continue
        value = item.get("value")
        if not value:
            continue
        url = safe_url(item.get("url") or "")
        label = _txt(item.get("label") or "")
        val = (
            Markup('<a href="{}" target="_blank" rel="noopener noreferrer">{}</a>').format(url, _txt(value))
            if url
            else _txt(value)
        )
        rows.append(Markup('<div class="contact-row"><span>{}</span><b>{}</b></div>').format(label, val))
    if not rows:
        return Markup("")
    head = Markup("<h2>{}</h2>").format(_txt(p.get("title") or "Контакты"))
    return Markup('<section class="block card contacts">{}{}</section>').format(head, Markup("").join(rows))


def _block_features(p: dict[str, Any]) -> Markup:
    cards: list[Markup] = []
    for item in p.get("items") or []:
        if not isinstance(item, dict):
            continue
        cards.append(
            Markup('<div class="feature"><div class="feature-icon">{}</div><h3>{}</h3><p>{}</p></div>').format(
                _txt(item.get("icon") or "✦"), _txt(item.get("title") or ""), _multiline(item.get("text") or "")
            )
        )
    if not cards:
        return Markup("")
    head = Markup("<h2>{}</h2>").format(_txt(p["title"])) if p.get("title") else Markup("")
    return Markup('<section class="block features">{}<div class="feature-grid">{}</div></section>').format(
        head, Markup("").join(cards)
    )


def _block_product(p: dict[str, Any]) -> Markup:
    price = p.get("price")
    return Markup(
        '<section class="block card product">{}{}{}{}{}</section>'
    ).format(
        _img(p.get("image"), p.get("title", ""), "product-img"),
        Markup("<h2>{}</h2>").format(_txt(p["title"])) if p.get("title") else Markup(""),
        Markup("<p>{}</p>").format(_multiline(p["description"])) if p.get("description") else Markup(""),
        Markup('<div class="price">{}</div>').format(_txt(price)) if price else Markup(""),
        Markup('<a class="btn btn-primary" href="{}" target="_blank" rel="noopener noreferrer">{}</a>').format(
            safe_url(p.get("button_url")), _txt(p.get("button_title") or "Купить")
        )
        if safe_url(p.get("button_url"))
        else Markup(""),
    )


def _block_cta(p: dict[str, Any]) -> Markup:
    url = safe_url(p.get("url"))
    return Markup('<section class="block cta">{}{}{}</section>').format(
        Markup("<h2>{}</h2>").format(_txt(p["title"])) if p.get("title") else Markup(""),
        Markup("<p>{}</p>").format(_multiline(p["text"])) if p.get("text") else Markup(""),
        Markup('<a class="btn btn-primary" href="{}" target="_blank" rel="noopener noreferrer">{}</a>').format(
            url, _txt(p.get("button_title") or "Оставить заявку")
        )
        if url
        else Markup(""),
    )


def _block_gallery(p: dict[str, Any]) -> Markup:
    cells: list[Markup] = []
    for item in p.get("items") or []:
        if isinstance(item, str):
            item = {"image": item}
        if not isinstance(item, dict):
            continue
        img = _img(item.get("image"), item.get("title", ""), "gallery-img")
        if not img:
            continue
        caption = (
            Markup('<figcaption>{}</figcaption>').format(_txt(item["title"])) if item.get("title") else Markup("")
        )
        cells.append(Markup("<figure>{}{}</figure>").format(img, caption))
    if not cells:
        return Markup("")
    head = Markup("<h2>{}</h2>").format(_txt(p["title"])) if p.get("title") else Markup("")
    return Markup('<section class="block gallery">{}<div class="gallery-grid">{}</div></section>').format(
        head, Markup("").join(cells)
    )


def _block_event_info(p: dict[str, Any]) -> Markup:
    rows: list[Markup] = []
    for key, label in (("date", "Дата"), ("time", "Время"), ("place", "Место"), ("address", "Адрес")):
        if p.get(key):
            rows.append(
                Markup('<div class="contact-row"><span>{}</span><b>{}</b></div>').format(label, _txt(p[key]))
            )
    if not rows and not p.get("poster"):
        return Markup("")
    return Markup('<section class="block card event">{}{}{}</section>').format(
        _img(p.get("poster"), p.get("title", ""), "poster"),
        Markup("<h2>{}</h2>").format(_txt(p["title"])) if p.get("title") else Markup(""),
        Markup("").join(rows),
    )


def _block_schedule(p: dict[str, Any]) -> Markup:
    rows: list[Markup] = []
    for item in p.get("items") or []:
        if not isinstance(item, dict):
            continue
        rows.append(
            Markup('<div class="schedule-row"><span class="time">{}</span>'
                   '<span class="what"><b>{}</b>{}</span></div>').format(
                _txt(item.get("time") or ""),
                _txt(item.get("title") or ""),
                Markup("<p>{}</p>").format(_multiline(item["text"])) if item.get("text") else Markup(""),
            )
        )
    if not rows:
        return Markup("")
    head = Markup("<h2>{}</h2>").format(_txt(p.get("title") or "Программа"))
    return Markup('<section class="block card schedule">{}{}</section>').format(head, Markup("").join(rows))


def _block_ton_info(p: dict[str, Any]) -> Markup:
    rows: list[Markup] = []
    for key, label in (
        ("ticker", "Тикер"),
        ("contract_address", "Контракт"),
        ("network", "Сеть"),
        ("supply", "Эмиссия"),
    ):
        if p.get(key):
            rows.append(
                Markup('<div class="contact-row"><span>{}</span><b class="mono">{}</b></div>').format(
                    label, _txt(p[key])
                )
            )
    if not rows:
        return Markup("")
    head = Markup("<h2>{}</h2>").format(_txt(p.get("title") or "О проекте"))
    return Markup('<section class="block card ton-info">{}{}</section>').format(head, Markup("").join(rows))


def _block_jetton(p: dict[str, Any]) -> Markup:
    rows: list[Markup] = []
    for key, label in (("jetton_address", "Jetton"), ("dex_url", "DEX"), ("explorer_url", "Explorer")):
        value = p.get(key)
        if not value:
            continue
        url = safe_url(value)
        body = (
            Markup('<a class="mono" href="{}" target="_blank" rel="noopener noreferrer">{}</a>').format(url, _txt(value))
            if url
            else Markup('<b class="mono">{}</b>').format(_txt(value))
        )
        rows.append(Markup('<div class="contact-row"><span>{}</span>{}</div>').format(label, body))
    if not rows:
        return Markup("")
    head = Markup("<h2>{}</h2>").format(_txt(p.get("title") or "Jetton"))
    return Markup('<section class="block card jetton">{}{}</section>').format(head, Markup("").join(rows))


def _block_image(p: dict[str, Any]) -> Markup:
    img = _img(p.get("image") or p.get("url"), p.get("alt", ""), "wide-img")
    if not img:
        return Markup("")
    return Markup('<section class="block image">{}</section>').format(img)


def _block_divider(_: dict[str, Any]) -> Markup:
    return Markup('<hr class="divider">')


BLOCK_RENDERERS: dict[str, Callable[[dict[str, Any]], Markup]] = {
    "hero": _block_hero,
    "text": _block_text,
    "about": _block_text,
    "links": _block_links,
    "buttons": _block_buttons,
    "socials": _block_socials,
    "contacts": _block_contacts,
    "features": _block_features,
    "advantages": _block_features,
    "product": _block_product,
    "cta": _block_cta,
    "gallery": _block_gallery,
    "works": _block_gallery,
    "event_info": _block_event_info,
    "schedule": _block_schedule,
    "ton_info": _block_ton_info,
    "jetton": _block_jetton,
    "image": _block_image,
    "divider": _block_divider,
}

CSS = """
*{box-sizing:border-box}
body{margin:0;padding:0;background:var(--bg);color:var(--text);min-height:100vh;
  font-family:var(--font);-webkit-font-smoothing:antialiased;line-height:1.5}
.page{max-width:640px;margin:0 auto;padding:28px 18px 64px;display:flex;flex-direction:column;gap:18px}
h1{font-size:28px;margin:0 0 6px;letter-spacing:-.02em}
h2{font-size:19px;margin:0 0 12px;letter-spacing:-.01em}
h3{font-size:16px;margin:0 0 6px}
p{margin:0 0 8px;color:var(--muted)}
a{color:var(--accent)}
.block{animation:fade .4s ease both}
@keyframes fade{from{opacity:0;transform:translateY(6px)}to{opacity:1;transform:none}}
.card{background:var(--surface);border-radius:18px;padding:18px;
  box-shadow:0 1px 2px rgba(0,0,0,.05),0 8px 24px rgba(0,0,0,.06)}
.hero{text-align:center;padding-top:12px}
.hero-avatar{margin-bottom:14px}
.hero-img{width:112px;height:112px;border-radius:50%;object-fit:cover;
  box-shadow:0 10px 30px rgba(0,0,0,.18)}
.subtitle{color:var(--muted);margin:0 auto;max-width:34ch}
.links{display:flex;flex-direction:column;gap:10px}
.link-row{display:flex;align-items:center;gap:12px;background:var(--surface);border-radius:14px;
  padding:14px 16px;text-decoration:none;color:var(--text);transition:transform .15s ease,box-shadow .15s ease;
  box-shadow:0 1px 2px rgba(0,0,0,.05)}
.link-row:hover{transform:translateY(-1px);box-shadow:0 6px 18px rgba(0,0,0,.12)}
.link-icon{font-size:20px;min-width:24px;text-align:center}
.link-title{display:block;font-weight:600}
.link-sub{display:block;font-size:13px;color:var(--muted)}
.buttons{display:flex;flex-direction:column;gap:10px}
.btn{display:block;text-align:center;padding:14px 18px;border-radius:14px;font-weight:600;
  text-decoration:none;transition:opacity .15s ease}
.btn:hover{opacity:.88}
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
@media(max-width:420px){.page{padding:20px 14px 48px}h1{font-size:24px}}
"""

PAGE_TEMPLATE = """<!DOCTYPE html>
<html lang="{lang}">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<title>{title}</title>
<meta name="description" content="{description}">
<meta property="og:title" content="{title}">
<meta property="og:description" content="{description}">
<meta property="og:type" content="website">
<style>:root{{--bg:{bg};--surface:{surface};--text:{text};--muted:{muted};--accent:{accent};--font:{font}}}
{css}</style>
</head>
<body>
<div class="page">
{body}
<div class="footer">{footer}</div>
</div>
</body>
</html>
"""

DEFAULT_FONT = (
    "-apple-system,BlinkMacSystemFont,'SF Pro Display','Segoe UI',Roboto,Inter,system-ui,sans-serif"
)


def render_custom_code(custom_code: dict[str, Any] | None) -> Markup:
    """Премиум-блок «Свой код» — только внутри sandbox-iframe.

    Скрипт пользователя выполняется в изолированном origin: у него нет доступа
    ни к DOM страницы, ни к её storage, ни к куки платформы.
    """
    if not custom_code:
        return Markup("")
    html = str(custom_code.get("html") or "")
    css = str(custom_code.get("css") or "")
    js = str(custom_code.get("js") or "")
    if not (html or css or js):
        return Markup("")

    doc = (
        "<!DOCTYPE html><html><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width,initial-scale=1'>"
        f"<style>body{{margin:0;font-family:{DEFAULT_FONT}}}{css}</style></head>"
        f"<body>{html}<script>{js}</script></body></html>"
    )
    return Markup(
        '<section class="block custom"><iframe class="custom-frame" sandbox="allow-scripts" '
        'referrerpolicy="no-referrer" srcdoc="{}"></iframe></section>'
    ).format(doc)


def render_blocks(content: dict[str, Any]) -> Markup:
    blocks = content.get("blocks")
    if not isinstance(blocks, list):
        return Markup("")
    out: list[Markup] = []
    for block in blocks:
        if not isinstance(block, dict):
            continue
        if block.get("hidden"):
            continue
        btype = str(block.get("type") or "")
        renderer = BLOCK_RENDERERS.get(btype)
        if renderer is None:
            continue
        props = block.get("props")
        if not isinstance(props, dict):
            props = {k: v for k, v in block.items() if k not in {"id", "type", "hidden"}}
        try:
            out.append(renderer(props))
        except Exception:  # noqa: BLE001 - битый блок не должен ронять весь сайт
            continue
    return Markup("\n").join(out)


def render_site(
    content_json: dict[str, Any] | None,
    *,
    title: str = "",
    custom_code: dict[str, Any] | None = None,
    domain: str | None = None,
    site_type: str | None = None,
) -> str:
    """Собирает готовую самодостаточную HTML-страницу сайта."""
    content = content_json if isinstance(content_json, dict) else {}
    meta = content.get("meta") if isinstance(content.get("meta"), dict) else {}
    theme = content.get("theme") if isinstance(content.get("theme"), dict) else {}

    preset = THEME_PRESETS.get(str(theme.get("preset") or "light"), THEME_PRESETS["light"])
    accent = safe_color(theme.get("accent"), "#0098ea")
    bg = page_background(theme, preset)

    page_title = str(meta.get("title") or title or domain or "TON Site")
    body = render_blocks(content) + render_custom_code(custom_code)
    footer = escape(domain or "")

    return PAGE_TEMPLATE.format(
        lang=escape(str(meta.get("lang") or "ru")),
        title=escape(page_title),
        description=escape(str(meta.get("description") or "")),
        bg=bg,
        surface=preset["surface"],
        text=preset["text"],
        muted=preset["muted"],
        accent=accent,
        font=DEFAULT_FONT,
        css=CSS,
        body=body,
        footer=footer,
    )


def clamp_dim(value: Any) -> int:
    """Затемнение фотофона в процентах: за пределами 0..90 смысла нет."""
    try:
        dim = int(float(value))
    except (TypeError, ValueError):
        return 0
    return max(0, min(dim, 90))


def page_background(theme: dict[str, Any], preset: dict[str, str]) -> str:
    """CSS-фон страницы: пресет, свой CSS или загруженная фотография.

    Фото ложится слоем поверх пресета (он остаётся запасным цветом, если
    картинка не загрузится), а сверху — затемнение: без него светлый текст
    на светлой фотографии не читается.
    """
    custom = theme.get("background")
    base = custom if isinstance(custom, str) and _is_safe_css_bg(custom) else preset["bg"]

    image = safe_url(theme.get("background_image"))
    # кавычки и скобки закрыли бы url(...) и позволили дописать свой CSS
    if not image or any(ch in image for ch in "'\"()") or any(ch.isspace() for ch in image):
        return base

    layers = []
    dim = clamp_dim(theme.get("background_dim"))
    if dim:
        shade = f"rgba(0,0,0,{dim / 100:.2f})"
        layers.append(f"linear-gradient({shade},{shade})")
    layers.append(f"url('{image}') center / cover no-repeat")
    layers.append(base)
    return ", ".join(layers)


def _is_safe_css_bg(value: str) -> bool:
    """Фон приходит от пользователя — не пускаем в CSS ничего исполняемого."""
    value = value.strip()
    if len(value) > 300:
        return False
    lowered = value.lower()
    if any(bad in lowered for bad in ("javascript:", "expression(", "</", "@import", "\\")):
        return False
    if lowered.startswith("url("):
        inner = value[4:-1].strip("'\" ")
        return bool(safe_url(inner))
    return bool(re.fullmatch(r"[#\w\s(),.%-]+", value))


def default_content_for(site_type: str, title: str = "") -> dict[str, Any]:
    """Скелет content_json для нового сайта — общая точка соглашения A и B."""
    blocks = []
    for btype in DEFAULT_BLOCKS.get(site_type, ["hero", "text"]):
        props: dict[str, Any] = {}
        if btype == "hero":
            props = {"title": title or "Название", "subtitle": "", "image": ""}
        elif btype in {"links", "buttons", "socials", "features", "gallery", "schedule", "contacts"}:
            props = {"items": []}
        blocks.append({"id": btype, "type": btype, "props": props})
    return {
        "version": 1,
        "meta": {"title": title, "description": "", "lang": "ru"},
        "theme": {
            "preset": "light",
            "accent": "#0098ea",
            "background": "",
            "background_image": "",
            "background_dim": 0,
        },
        "blocks": blocks,
    }


def content_size(content: dict[str, Any] | None) -> int:
    if not content:
        return 0
    return len(json.dumps(content, ensure_ascii=False).encode())
