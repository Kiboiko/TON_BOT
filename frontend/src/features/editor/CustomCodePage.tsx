/**
 * B4. Проект «Свой код» — отдельный тип сайта, а не блок внутри другого проекта.
 *
 * Страница целиком собирается из HTML/CSS/JS пользователя. Тип доступен только
 * по активной подписке: без неё backend отвечает 402, и экран показывает, что
 * нужно оформить тариф. Превью рендерится в изолированном iframe.
 */
import { useEffect, useMemo, useRef, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { ApiError } from "../../api/client";
import { billingApi, sitesApi, uploadsApi } from "../../api/endpoints";
import type { CustomCode, Site, Subscription } from "../../api/types";
import {
  Badge,
  Button,
  LoadFailed,
  Loading,
  Notice,
  PageHead,
  Segmented,
} from "../../components/ui";
import { useAppStore } from "../../store/app";
import { showBackButton } from "../../telegram/webapp";
import { renderCustomCode } from "../preview/render";

type CodeTab = "html" | "css" | "js";

/** Лёгкий редактор кода: моноширинный ввод с сохранением табов и отступов. */
function CodeArea({
  value,
  onChange,
  language,
  areaRef,
}: {
  value: string;
  onChange: (value: string) => void;
  language: string;
  areaRef: React.RefObject<HTMLTextAreaElement>;
}) {
  return (
    <div className="code-editor">
      <span className="code-lang">{language}</span>
      <textarea
        ref={areaRef}
        value={value}
        spellCheck={false}
        onChange={(e) => onChange(e.target.value)}
        onKeyDown={(e) => {
          if (e.key !== "Tab") return;
          e.preventDefault();
          const target = e.currentTarget;
          const { selectionStart: start, selectionEnd: end } = target;
          const next = `${value.slice(0, start)}  ${value.slice(end)}`;
          onChange(next);
          requestAnimationFrame(() => {
            target.selectionStart = target.selectionEnd = start + 2;
          });
        }}
      />
    </div>
  );
}

export function CustomCodePage() {
  const { siteId = "" } = useParams();
  const navigate = useNavigate();
  const { t } = useTranslation();
  const toast = useAppStore((s) => s.toast);
  const toastError = useAppStore((s) => s.toastError);

  const [site, setSite] = useState<Site | null>(null);
  const [failed, setFailed] = useState(false);
  const [tab, setTab] = useState<CodeTab>("html");
  const [code, setCode] = useState<CustomCode>({ html: "", css: "", js: "" });
  const [saving, setSaving] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [previewOpen, setPreviewOpen] = useState(false);
  // подписка кончилась, пока экран был открыт, — backend скажет об этом на сохранении
  const [locked, setLocked] = useState(false);
  // подписка, которая и открывает этот тип проекта: без неё непонятно, за что
  // платил пользователь и до какого числа код доступен
  const [subscription, setSubscription] = useState<Subscription | null>(null);
  const [subsLoaded, setSubsLoaded] = useState(false);

  const areaRef = useRef<HTMLTextAreaElement>(null);
  const fileRef = useRef<HTMLInputElement>(null);

  useEffect(() => showBackButton(() => navigate(`/sites/${siteId}`)), [navigate, siteId]);

  useEffect(() => {
    let cancelled = false;
    sitesApi
      .get(siteId)
      .then(({ site: loaded }) => {
        if (cancelled) return;
        setSite(loaded);
        if (loaded.custom_code) setCode(loaded.custom_code);
      })
      .catch((error) => {
        if (cancelled) return;
        toastError(error);
        setFailed(true);
      });
    return () => {
      cancelled = true;
    };
  }, [siteId, toastError]);

  useEffect(() => {
    billingApi
      .subscriptions()
      .then((subs) => {
        // «Свой код» открывает любая платная подписка, но не пробный период
        const paid = subs.filter((s) => !s.is_trial && s.status !== "expired");
        setSubscription(paid[0] ?? null);
      })
      .catch(() => setSubscription(null))
      .finally(() => setSubsLoaded(true));
  }, []);

  const previewHtml = useMemo(
    () =>
      previewOpen
        ? `<!DOCTYPE html><html><head><meta charset="utf-8"><style>body{margin:0;background:#fff}</style></head><body>${renderCustomCode(
            code,
          )}</body></html>`
        : "",
    [code, previewOpen],
  );

  /** Вставляет ссылку на загруженный файл в текущую вкладку прямо под курсор. */
  function insertAtCursor(snippet: string): void {
    const area = areaRef.current;
    const current = code[tab];
    const start = area?.selectionStart ?? current.length;
    const end = area?.selectionEnd ?? current.length;
    const next = `${current.slice(0, start)}${snippet}${current.slice(end)}`;
    setCode((prev) => ({ ...prev, [tab]: next }));
    requestAnimationFrame(() => {
      area?.focus();
      const caret = start + snippet.length;
      area?.setSelectionRange(caret, caret);
    });
  }

  async function upload(file: File | undefined): Promise<void> {
    if (!file) return;
    setUploading(true);
    try {
      const { url } = await uploadsApi.image(file);
      insertAtCursor(
        tab === "html"
          ? `<img src="${url}" alt="">`
          : tab === "css"
            ? `url("${url}")`
            : `"${url}"`,
      );
      toast(t("customCode.imageInserted"), "success");
    } catch (error) {
      toastError(error);
    } finally {
      setUploading(false);
      if (fileRef.current) fileRef.current.value = "";
    }
  }

  async function save(): Promise<boolean> {
    setSaving(true);
    try {
      await sitesApi.setCustomCode(siteId, code);
      setLocked(false);
      toast(t("common.saved"), "success");
      return true;
    } catch (error) {
      if (error instanceof ApiError && error.code === "SUBSCRIPTION_REQUIRED") {
        setLocked(true);
        return false;
      }
      toastError(error);
      return false;
    } finally {
      setSaving(false);
    }
  }

  if (failed)
    return (
      <LoadFailed
        title={t("editor.siteMissing")}
        onBack={() => navigate("/sites")}
        backLabel={t("editor.backToSites")}
      />
    );
  if (!site) return <Loading text={t("common.loading")} />;

  const expires = subscription?.is_forever
    ? t("subscriptions.forever")
    : subscription?.expires_at
      ? new Date(subscription.expires_at).toLocaleDateString()
      : "";

  return (
    <div className="page">
      <PageHead
        title={t("customCode.title")}
        subtitle={site.title}
        onBack={() => navigate("/sites")}
        extra={locked ? <Badge kind="danger">🔒</Badge> : null}
      />

      {/* публикация и предпросмотр — те же экраны, что у обычных сайтов:
          без них проект «Свой код» невозможно было выложить на домен */}
      <div className="row">
        <Button size="sm" onClick={() => navigate(`/sites/${siteId}/preview`)}>
          👁 {t("editor.preview")}
        </Button>
        <div className="grow" />
        <Button
          size="sm"
          variant="primary"
          loading={saving}
          onClick={async () => {
            if (await save()) navigate(`/sites/${siteId}/publish`);
          }}
        >
          {t("editor.publish")}
        </Button>
      </div>

      <Notice>{t("customCode.description")}</Notice>

      {/* состояние подписки: этот тип проекта живёт только пока она активна */}
      {subsLoaded ? (
        <div className="card">
          <div className="card-row">
            <div className="grow">
              <div className="card-title">{t("customCode.subscription")}</div>
              <div className="card-sub">
                {subscription
                  ? `${subscription.tariff?.name ?? t("subscriptions.trial")}${
                      expires ? ` · ${t("subscriptions.until", { date: expires })}` : ""
                    }`
                  : t("customCode.subscriptionHint")}
              </div>
            </div>
            {subscription ? (
              <Badge kind={subscription.status === "expiring_soon" ? "warning" : "success"}>
                {t(`subscriptions.status.${subscription.status}`)}
              </Badge>
            ) : (
              <Button size="sm" variant="primary" onClick={() => navigate("/tariffs")}>
                {t("sites.upgrade")}
              </Button>
            )}
          </div>
          <div style={{ marginTop: 10 }}>
            <Button size="sm" onClick={() => navigate("/subscriptions")}>
              {t("subscriptions.title")} →
            </Button>
          </div>
        </div>
      ) : null}

      {locked ? (
        <div className="card">
          <div className="card-title">{t("customCode.locked")}</div>
          <div className="card-sub" style={{ marginTop: 4 }}>
            {t("customCode.subscriptionHint")}
          </div>
          <div style={{ marginTop: 12 }}>
            <Button variant="primary" block onClick={() => navigate("/tariffs")}>
              {t("sites.upgrade")}
            </Button>
          </div>
        </div>
      ) : null}

      <Notice kind="warning">{t("customCode.warning")}</Notice>

      <Segmented<CodeTab>
        value={tab}
        onChange={setTab}
        options={[
          { value: "html", label: t("customCode.html") },
          { value: "css", label: t("customCode.css") },
          { value: "js", label: t("customCode.js") },
        ]}
      />

      <CodeArea
        areaRef={areaRef}
        language={tab.toUpperCase()}
        value={code[tab]}
        onChange={(value) => setCode((prev) => ({ ...prev, [tab]: value }))}
      />

      {/* картинку негде взять «снаружи»: загружаем её на сервер проекта и
          вставляем готовую ссылку прямо в код */}
      <div className="row">
        <input
          ref={fileRef}
          type="file"
          accept="image/png,image/jpeg,image/gif,image/webp"
          style={{ display: "none" }}
          onChange={(e) => void upload(e.target.files?.[0])}
        />
        <Button size="sm" loading={uploading} onClick={() => fileRef.current?.click()}>
          📷 {t("customCode.uploadImage")}
        </Button>
        <span className="field-hint">{t("customCode.uploadHint")}</span>
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
        <iframe
          title="custom-code-preview"
          className="preview-frame"
          style={{ height: 220 }}
          srcDoc={previewHtml}
          sandbox="allow-scripts"
        />
      ) : null}

      <Button variant="primary" block loading={saving} onClick={() => void save()}>
        {t("customCode.save")}
      </Button>
    </div>
  );
}
