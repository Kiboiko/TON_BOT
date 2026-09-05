/**
 * B4. Проект «Свой код» — отдельный тип сайта, а не блок внутри другого проекта.
 *
 * Страница целиком собирается из HTML/CSS/JS пользователя. Тип доступен только
 * по активной подписке: без неё backend отвечает 402, и экран показывает, что
 * нужно оформить тариф. Превью рендерится в изолированном iframe.
 */
import { useEffect, useMemo, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { ApiError } from "../../api/client";
import { sitesApi } from "../../api/endpoints";
import type { CustomCode, Site } from "../../api/types";
import { Badge, Button, Loading, Notice, Segmented } from "../../components/ui";
import { useAppStore } from "../../store/app";
import { showBackButton } from "../../telegram/webapp";
import { renderCustomCode } from "../preview/render";

type CodeTab = "html" | "css" | "js";

/** Лёгкий редактор кода: моноширинный ввод с сохранением табов и отступов. */
function CodeArea({
  value,
  onChange,
  language,
}: {
  value: string;
  onChange: (value: string) => void;
  language: string;
}) {
  return (
    <div className="code-editor">
      <span className="code-lang">{language}</span>
      <textarea
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
  const [tab, setTab] = useState<CodeTab>("html");
  const [code, setCode] = useState<CustomCode>({ html: "", css: "", js: "" });
  const [saving, setSaving] = useState(false);
  // подписка кончилась, пока экран был открыт, — backend скажет об этом на сохранении
  const [locked, setLocked] = useState(false);

  useEffect(() => showBackButton(() => navigate(`/sites/${siteId}`)), [navigate, siteId]);

  useEffect(() => {
    sitesApi
      .get(siteId)
      .then(({ site: loaded }) => {
        setSite(loaded);
        if (loaded.custom_code) setCode(loaded.custom_code);
      })
      .catch(toastError);
  }, [siteId, toastError]);

  const previewHtml = useMemo(
    () =>
      `<!DOCTYPE html><html><head><meta charset="utf-8"><style>body{margin:0;background:#fff}</style></head><body>${renderCustomCode(
        code,
      )}</body></html>`,
    [code],
  );

  async function save(): Promise<void> {
    setSaving(true);
    try {
      await sitesApi.setCustomCode(siteId, code);
      setLocked(false);
      toast(t("common.saved"), "success");
    } catch (error) {
      if (error instanceof ApiError && error.code === "SUBSCRIPTION_REQUIRED") {
        setLocked(true);
        return;
      }
      toastError(error);
    } finally {
      setSaving(false);
    }
  }

  if (!site) return <Loading text={t("common.loading")} />;

  return (
    <div className="page">
      <div className="page-header">
        <div className="grow">
          <h1>{t("customCode.title")}</h1>
          <div className="page-subtitle">{site.title}</div>
        </div>
        {locked ? <Badge kind="danger">🔒</Badge> : null}
      </div>

      <Notice>{t("customCode.description")}</Notice>

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
        language={tab.toUpperCase()}
        value={code[tab]}
        onChange={(value) => setCode((prev) => ({ ...prev, [tab]: value }))}
      />

      <div className="field-label">{t("preview.title")}</div>
      <iframe
        title="custom-code-preview"
        className="preview-frame"
        style={{ height: 220 }}
        srcDoc={previewHtml}
        sandbox="allow-scripts"
      />

      <Button variant="primary" block loading={saving} onClick={() => void save()}>
        {t("customCode.save")}
      </Button>
    </div>
  );
}
