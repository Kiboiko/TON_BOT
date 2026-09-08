/**
 * B2. Ядро конструктора: список блоков с добавлением/удалением/перемещением,
 * оформление сайта, автосохранение черновика, undo/redo и живой предпросмотр.
 */
import { useEffect, useMemo, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { sitesApi } from "../../api/endpoints";
import type { BlockType, SiteContent, ThemePreset } from "../../api/types";
import {
  Badge,
  Button,
  Empty,
  Field,
  Input,
  LoadFailed,
  Loading,
  Notice,
  PageHead,
  Segmented,
  Sheet,
  Textarea,
} from "../../components/ui";
import {
  ACCENT_COLORS,
  BLOCK_CATALOG,
  BLOCK_SPECS,
  THEME_PRESET_LIST,
} from "../../templates/catalog";
import { useAppStore } from "../../store/app";
import { useEditorStore } from "../../store/editor";
import { haptic, showBackButton } from "../../telegram/webapp";
import { BlockEditor, ImageUpload } from "./BlockEditor";
import { renderSite } from "../preview/render";

type Tab = "blocks" | "design";

export function EditorPage() {
  const { siteId = "" } = useParams();
  const navigate = useNavigate();
  const { t, i18n } = useTranslation();
  const lang = i18n.language.startsWith("en") ? "en" : "ru";
  const toastError = useAppStore((s) => s.toastError);

  const editor = useEditorStore();
  const [tab, setTab] = useState<Tab>("blocks");
  const [adding, setAdding] = useState(false);
  const [loading, setLoading] = useState(true);
  const [failed, setFailed] = useState(false);
  // предпросмотр по требованию: постоянный iframe перерисовывался на каждый
  // введённый символ и тормозил ввод на телефоне
  const [previewOpen, setPreviewOpen] = useState(false);

  useEffect(() => showBackButton(() => navigate("/sites")), [navigate]);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    sitesApi
      .get(siteId)
      .then(({ site }) => {
        if (cancelled) return;
        // «Свой код» — проект без блоков, его редактируют на отдельном экране
        if (site.type === "custom_code") {
          navigate(`/sites/${siteId}/custom-code`, { replace: true });
          return;
        }
        editor.load(site);
        setLoading(false);
      })
      .catch((error) => {
        if (cancelled) return;
        toastError(error);
        setFailed(true);
        setLoading(false);
      });
    return () => {
      cancelled = true;
      void editor.saveNow();
      editor.reset();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [siteId]);

  const content = editor.content;
  const selected = useMemo(
    () => content?.blocks.find((b) => b.id === editor.selectedBlockId) ?? null,
    [content, editor.selectedBlockId],
  );

  // содержимое iframe пересобираем не чаще раза в 400 мс и только когда
  // предпросмотр открыт: иначе каждая буква перезагружала страницу целиком
  const previewSource = useMemo(
    () =>
      content && previewOpen
        ? renderSite(content, {
            title: editor.title,
            domain: editor.site?.domain ?? null,
            customCode: editor.site?.custom_code ?? null,
            emptyHint: t("preview.emptySite"),
            draftHints: BLOCK_TITLES(lang, t("editor.blockEmpty")),
          })
        : "",
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [content, editor.title, editor.site, previewOpen, lang, t],
  );
  const previewHtml = useDebounced(previewSource, 400);

  if (failed || (!loading && !content))
    return (
      <LoadFailed
        title={t("editor.siteMissing")}
        onBack={() => navigate("/sites")}
        backLabel={t("editor.backToSites")}
      />
    );
  if (loading || !content) return <Loading text={t("common.loading")} />;

  const patchContent = (patch: Partial<SiteContent>) =>
    editor.updateContent((current) => ({ ...current, ...patch }));

  const saveBadge = {
    idle: null,
    dirty: <Badge>{t("common.unsaved")}</Badge>,
    saving: <Badge kind="accent">{t("common.saving")}</Badge>,
    saved: <Badge kind="success">{t("common.saved")}</Badge>,
    error: <Badge kind="danger">{t("common.error")}</Badge>,
  }[editor.saveState];

  return (
    <div className="page">
      {editor.siteMissing ? (
        <Notice kind="danger">
          <div>
            {t("editor.siteMissing")}
            <div style={{ marginTop: 8 }}>
              <Button size="sm" variant="primary" onClick={() => navigate("/sites")}>
                {t("editor.backToSites")}
              </Button>
            </div>
          </div>
        </Notice>
      ) : editor.saveState === "error" ? (
        <Notice kind="danger">{t("editor.saveFailed", { reason: editor.saveError ?? "" })}</Notice>
      ) : null}

      <PageHead
        title={editor.title || t("editor.title")}
        subtitle={editor.site?.domain ?? t("editor.title")}
        onBack={() => navigate("/sites")}
        extra={saveBadge}
      />

      <div className="row">
        <Button size="sm" disabled={!editor.canUndo()} onClick={editor.undo} title={t("editor.undo")}>
          ↶
        </Button>
        <Button size="sm" disabled={!editor.canRedo()} onClick={editor.redo} title={t("editor.redo")}>
          ↷
        </Button>
        <div className="grow" />
        <Button size="sm" onClick={() => navigate(`/sites/${siteId}/preview`)}>
          👁 {t("editor.preview")}
        </Button>
        <Button
          size="sm"
          variant="primary"
          onClick={async () => {
            await editor.saveNow();
            navigate(`/sites/${siteId}/publish`);
          }}
        >
          {t("editor.publish")}
        </Button>
      </div>

      <button
        type="button"
        className={previewOpen ? "preview-toggle open" : "preview-toggle"}
        onClick={() => setPreviewOpen((open) => !open)}
      >
        <span>👁 {previewOpen ? t("editor.hidePreview") : t("editor.showPreview")}</span>
        <span className="chevron">▾</span>
      </button>

      {previewOpen ? (
        <div className="live-preview" style={{ height: 260 }} aria-label={t("preview.title")}>
          <iframe title="live-preview" srcDoc={previewHtml} sandbox="allow-scripts" />
        </div>
      ) : null}

      <Segmented<Tab>
        value={tab}
        onChange={setTab}
        options={[
          { value: "blocks", label: t("editor.blocks") },
          { value: "design", label: t("editor.design") },
        ]}
      />

      {tab === "blocks" ? (
        <>
          <Field label={t("editor.siteTitle")}>
            <Input value={editor.title} onChange={editor.setTitle} />
          </Field>

          {content.blocks.length === 0 ? (
            <Empty icon="🧩" title={t("editor.noBlocks")} />
          ) : (
            <div className="list">
              {content.blocks.map((block, index) => {
                const spec = BLOCK_SPECS[block.type];
                return (
                  <div
                    key={block.id}
                    className={block.hidden ? "block-item hidden-block" : "block-item"}
                  >
                    <div className="block-icon">{spec?.icon ?? "🧩"}</div>
                    <div
                      className="grow"
                      style={{ cursor: "pointer" }}
                      onClick={() => {
                        haptic.selection();
                        editor.select(block.id);
                      }}
                    >
                      <div className="card-title">{spec?.title[lang] ?? block.type}</div>
                      <div className="card-sub">{spec?.hint[lang]}</div>
                    </div>
                    <div className="block-actions">
                      <button
                        disabled={index === 0}
                        title={t("editor.up")}
                        onClick={() => editor.moveBlock(block.id, -1)}
                      >
                        ↑
                      </button>
                      <button
                        disabled={index === content.blocks.length - 1}
                        title={t("editor.down")}
                        onClick={() => editor.moveBlock(block.id, 1)}
                      >
                        ↓
                      </button>
                      <button
                        title={block.hidden ? t("editor.show") : t("editor.hide")}
                        onClick={() => editor.toggleBlock(block.id)}
                      >
                        {block.hidden ? "🙈" : "👁"}
                      </button>
                      <button title={t("common.delete")} onClick={() => editor.removeBlock(block.id)}>
                        ✕
                      </button>
                    </div>
                  </div>
                );
              })}
            </div>
          )}

          <Button block onClick={() => setAdding(true)}>
            + {t("editor.addBlock")}
          </Button>
        </>
      ) : (
        <>
          <Field label={t("editor.pageTitle")}>
            <Input
              value={content.meta.title ?? ""}
              onChange={(value) => patchContent({ meta: { ...content.meta, title: value } })}
            />
          </Field>
          <Field label={t("editor.pageDescription")}>
            <Textarea
              value={content.meta.description ?? ""}
              onChange={(value) => patchContent({ meta: { ...content.meta, description: value } })}
            />
          </Field>

          <div className="field-label">{t("editor.theme")}</div>
          <div className="swatches">
            {THEME_PRESET_LIST.map((preset) => (
              <div key={preset.value}>
                <div
                  className={content.theme.preset === preset.value ? "swatch active" : "swatch"}
                  style={{ background: preset.swatch }}
                  onClick={() => {
                    haptic.selection();
                    patchContent({
                      theme: { ...content.theme, preset: preset.value as ThemePreset },
                    });
                  }}
                />
                <div className="swatch-label">{preset.label}</div>
              </div>
            ))}
          </div>

          <div className="field-label">{t("editor.accent")}</div>
          <div className="row wrap">
            {ACCENT_COLORS.map((color) => (
              <div
                key={color}
                className={content.theme.accent === color ? "color-dot active" : "color-dot"}
                style={{ background: color }}
                onClick={() => patchContent({ theme: { ...content.theme, accent: color } })}
              />
            ))}
          </div>

          <div className="field-label">{t("editor.backgroundPhoto")}</div>
          {content.theme.background_image ? (
            <>
              <div className="bg-preview">
                <img src={content.theme.background_image} alt="" />
                <Button
                  size="sm"
                  variant="danger"
                  onClick={() =>
                    patchContent({
                      theme: { ...content.theme, background_image: "", background_dim: 0 },
                    })
                  }
                >
                  {t("editor.removePhoto")}
                </Button>
              </div>
              <Field label={t("editor.backgroundDim")} hint={t("editor.backgroundDimHint")}>
                <div className="row">
                  <input
                    className="range"
                    type="range"
                    min={0}
                    max={90}
                    step={5}
                    value={content.theme.background_dim ?? 0}
                    onChange={(e) =>
                      patchContent({
                        theme: { ...content.theme, background_dim: Number(e.target.value) },
                      })
                    }
                  />
                  <span className="card-sub">{content.theme.background_dim ?? 0}%</span>
                </div>
              </Field>
            </>
          ) : (
            <>
              <div className="card-sub">{t("editor.backgroundPhotoHint")}</div>
              <ImageUpload
                onUploaded={(url) =>
                  // сразу приглушаем фото: без затемнения текст на светлом снимке не читается
                  patchContent({
                    theme: { ...content.theme, background_image: url, background_dim: 35 },
                  })
                }
              />
            </>
          )}

          <Field label={t("editor.background")} hint={t("editor.backgroundHint")}>
            <Input
              value={content.theme.background ?? ""}
              onChange={(value) => patchContent({ theme: { ...content.theme, background: value } })}
            />
          </Field>
        </>
      )}

      {/* редактор выбранного блока */}
      <Sheet
        open={Boolean(selected)}
        title={selected ? BLOCK_SPECS[selected.type]?.title[lang] : t("editor.blockSettings")}
        onClose={() => editor.select(null)}
      >
        {selected ? (
          <BlockEditor
            block={selected}
            onChange={(props) => editor.updateBlock(selected.id, props)}
          />
        ) : null}
        <div style={{ marginTop: 14 }}>
          <Button block variant="primary" onClick={() => editor.select(null)}>
            {t("common.done")}
          </Button>
        </div>
      </Sheet>

      {/* добавление блока */}
      <Sheet open={adding} title={t("editor.addBlock")} onClose={() => setAdding(false)}>
        <div className="list">
          {BLOCK_CATALOG.map((spec) => (
            <div
              key={spec.type}
              className="block-item clickable"
              onClick={() => {
                editor.addBlock(spec.type as BlockType);
                setAdding(false);
              }}
            >
              <div className="block-icon">{spec.icon}</div>
              <div>
                <div className="card-title">{spec.title[lang]}</div>
                <div className="card-sub">{spec.hint[lang]}</div>
              </div>
            </div>
          ))}
        </div>
      </Sheet>
    </div>
  );
}

/** Значение, обновляемое не чаще, чем раз в `delay` мс. */
function useDebounced<T>(value: T, delay: number): T {
  const [debounced, setDebounced] = useState(value);
  useEffect(() => {
    const timer = setTimeout(() => setDebounced(value), delay);
    return () => clearTimeout(timer);
  }, [value, delay]);
  return debounced;
}

/**
 * Подписи для блоков, которые пока нечего показать.
 *
 * Пустой блок ссылок раньше рендерился в ничто, и пользователь видел на его
 * месте пустоту — было непонятно, добавился блок или нет.
 */
function BLOCK_TITLES(lang: "ru" | "en", hint: string): Record<string, string> {
  return Object.fromEntries(
    BLOCK_CATALOG.map((spec) => [spec.type, `${spec.icon} ${spec.title[lang]} — ${hint}`]),
  );
}
