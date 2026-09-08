/** Рендер должен обезвреживать пользовательский ввод так же, как backend. */
import { describe, expect, it } from "vitest";
import { clampDim, pageBackground, renderCustomCode, renderSite, safeUrl } from "./render";
import { TEMPLATES, defaultContentFor } from "../../templates/catalog";
import type { SiteContent } from "../../api/types";

const base: SiteContent = {
  version: 1,
  meta: { title: "Тест", lang: "ru" },
  theme: { preset: "light", accent: "#0098ea" },
  blocks: [],
};

describe("safeUrl", () => {
  it("пропускает разрешённые схемы", () => {
    expect(safeUrl("https://ton.org")).toBe("https://ton.org");
    expect(safeUrl("mailto:a@b.com")).toBe("mailto:a@b.com");
    expect(safeUrl("tel:+79000000000")).toBe("tel:+79000000000");
  });

  it("достраивает https для строки без схемы", () => {
    expect(safeUrl("t.me/durov")).toBe("https://t.me/durov");
  });

  it("отбрасывает javascript: и data:", () => {
    expect(safeUrl("javascript:alert(1)")).toBe("");
    expect(safeUrl("data:text/html;base64,PHNjcmlwdD4=")).toBe("");
    expect(safeUrl(42)).toBe("");
  });
});

describe("renderSite", () => {
  it("экранирует текст пользователя", () => {
    const html = renderSite({
      ...base,
      meta: { title: "<script>alert(1)</script>" },
      blocks: [
        { id: "1", type: "hero", props: { title: "<img src=x onerror=alert(1)>", subtitle: "ok" } },
      ],
    });
    expect(html).not.toContain("<script>alert(1)</script>");
    expect(html).not.toContain("<img src=x");
    expect(html).toContain("&lt;img src=x onerror=alert(1)&gt;");
  });

  it("не пускает javascript-ссылки в разметку", () => {
    const html = renderSite({
      ...base,
      blocks: [
        {
          id: "1",
          type: "links",
          props: {
            items: [
              { title: "bad", url: "javascript:alert(1)" },
              { title: "good", url: "https://ton.org" },
            ],
          },
        },
      ],
    });
    expect(html).not.toContain("javascript:");
    expect(html).toContain("https://ton.org");
  });

  it("блокирует инъекцию в CSS фона", () => {
    const html = renderSite({ ...base, theme: { preset: "light", accent: "#fff", background: "url(javascript:alert(1))" } });
    expect(html).not.toContain("javascript:");
  });

  // значения обязаны совпадать с page_background на backend: превью и
  // опубликованный сайт должны выглядеть одинаково
  it("кладёт фото фоном поверх пресета и затемняет его", () => {
    expect(pageBackground({ background_image: "/u/a.jpg", background_dim: 40 }, "#f6f7fb")).toBe(
      "linear-gradient(rgba(0,0,0,0.40),rgba(0,0,0,0.40)), url('/u/a.jpg') center / cover no-repeat, #f6f7fb",
    );
    expect(pageBackground({ background_image: "/u/a.jpg" }, "#f6f7fb")).toBe(
      "url('/u/a.jpg') center / cover no-repeat, #f6f7fb",
    );
  });

  it("не даёт ссылке на фото вырваться из url(...)", () => {
    for (const bad of ["/u/a.jpg') ;} body{display:none", "javascript:alert(1)", "/u/a b.jpg", "/u/a\".jpg"]) {
      expect(pageBackground({ background_image: bad }, "#f6f7fb")).toBe("#f6f7fb");
    }
  });

  it("ограничивает затемнение диапазоном 0–90", () => {
    expect(clampDim(200)).toBe(90);
    expect(clampDim(-5)).toBe(0);
    expect(clampDim("не число")).toBe(0);
    expect(clampDim(35)).toBe(35);
  });

  it("рендерит все шаблоны", () => {
    for (const template of TEMPLATES) {
      const html = renderSite(defaultContentFor(template.type, "Тест"), { title: "Тест" });
      expect(html.startsWith("<!DOCTYPE html>")).toBe(true);
      expect(html).toContain("Тест");
    }
  });

  it("показывает подсказку для пустого сайта", () => {
    const html = renderSite(base, { emptyHint: "Добавьте блоки" });
    expect(html).toContain("Добавьте блоки");
  });

  it("пропускает скрытые и неизвестные блоки", () => {
    const html = renderSite({
      ...base,
      blocks: [
        { id: "1", type: "hero", props: { title: "Видимый" } },
        { id: "2", type: "hero", props: { title: "Скрытый" }, hidden: true },
        { id: "3", type: "unknown" as never, props: { title: "Неизвестный" } },
      ],
    });
    expect(html).toContain("Видимый");
    expect(html).not.toContain("Скрытый");
    expect(html).not.toContain("Неизвестный");
  });
});

describe("renderCustomCode", () => {
  it("изолирует пользовательский код в sandbox-iframe", () => {
    const html = renderCustomCode({ html: "<b>hi</b>", css: "b{color:red}", js: "alert(1)" });
    expect(html).toContain("<iframe");
    expect(html).toContain('sandbox="allow-scripts"');
    expect(html).not.toContain("<script>alert(1)</script>");
  });

  it("ничего не рендерит для пустого кода", () => {
    expect(renderCustomCode({ html: "", css: "", js: "" })).toBe("");
    expect(renderCustomCode(null)).toBe("");
  });
});

describe("незаполненные блоки", () => {
  const withEmptyLinks: SiteContent = {
    ...base,
    blocks: [
      { id: "1", type: "image", props: { image: "https://ton.org/a.png" } },
      { id: "2", type: "links", props: { items: [{}] } },
    ],
  };

  it("в конструкторе показывает заглушку вместо пустоты", () => {
    // без заглушки блок ссылок сразу после фото исчезал, и пользователю
    // казалось, что конструктор его потерял
    const html = renderSite(withEmptyLinks, {
      draftHints: { links: "🔗 Ссылки — блок пока пустой" },
    });
    expect(html).toContain("block draft");
    expect(html).toContain("Ссылки — блок пока пустой");
  });

  it("в опубликованном сайте не оставляет следов", () => {
    const html = renderSite(withEmptyLinks);
    expect(html).not.toContain("block draft");
    expect(html).toContain("a.png");
  });
});

describe("стили кнопок", () => {
  const buttons = (items: Record<string, unknown>[]): string =>
    renderSite({ ...base, blocks: [{ id: "1", type: "buttons", props: { items } }] });

  it("применяет размер и цвет из палитры", () => {
    const html = buttons([{ title: "Купить", url: "https://ton.org", size: "lg", color: "green" }]);
    expect(html).toContain("btn-primary btn-l");
    expect(html).toContain("--btn-bg:#12b981");
  });

  it("поддерживает контурный стиль", () => {
    const html = buttons([{ title: "Связаться", url: "https://ton.org", style: "outline" }]);
    expect(html).toContain("btn-outline");
  });

  it("не пускает в inline-style произвольный цвет", () => {
    const html = buttons([
      { title: "Взлом", url: "https://ton.org", color: "red;} body{display:none" },
    ]);
    expect(html).not.toContain("display:none");
    expect(html).toContain('class="btn btn-primary"');
  });
});
