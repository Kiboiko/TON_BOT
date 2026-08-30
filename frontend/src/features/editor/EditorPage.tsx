/**
 * B2. Ядро конструктора: список блоков с добавлением/удалением/перемещением,
 * оформление сайта, автосохранение черновика, undo/redo и живой предпросмотр.
 */
import { useEffect, useMemo, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { sitesApi } from "../../api/endpoints";
import type { BlockType, SiteContent, ThemePreset } from "../../api/types";
import { Badge, Button, Empty, Field, Input, Loading, Segmented, Sheet, Textarea } from "../../components/ui";
import {
  ACCENT_COLORS,
  BLOCK_CATALOG,
  BLOCK_SPECS,
  THEME_PRESET_LIST,
} from "../../templates/catalog";
import { useAppStore } from "../../store/app";
import { useEditorStore } from "../../store/editor";
import { haptic, showBackButton } from "../../telegram/webapp";
import { BlockEditor } from "./BlockEditor";
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

  useEffect(() => showBackButton(() => navigate("/sites")), [navigate]);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    sitesApi
      .get(siteId)
      .then(({ site }) => {
        if (!cancelled) {
          editor.load(site);
          setLoading(false);
        }
      })
      .catch((error) => {
        toastError(error);
        navigate("/sites");
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

  const previewHtml = useMemo(
    () =>
      content
        ? renderSite(content, {
            title: editor.title,
            domain: editor.site?.domain ?? null,
            customCode: editor.site?.custom_code_paid ? editor.site.custom_code : null,
            emptyHint: t("preview.emptySite"),
          })
        : "",
    [content, editor.title, editor.site, t],
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
      <div className="page-header">
        <div className="grow">
          <h1>{editor.title || t("editor.title")}</h1>
          <div className="page-subtitle">{editor.site?.domain ?? t("editor.title")}</div>
        </div>
        {saveBadge}
      </div>

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

      <div
        className="preview-frame"
        style={{ height: 260, overflow: "hidden", borderRadius: 16 }}
        aria-label={t("preview.title")}
      >
        <iframe
          title="live-preview"
          srcDoc={previewHtml}
          sandbox="allow-scripts"
          style={{ width: "100%", height: "100%", border: 0, borderRadius: 16 }}
        />
      </div>

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

          <Button block onClick={() => navigate(`/sites/${siteId}/custom-code`)}>
            ⌨️ {t("editor.customCode")}
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
