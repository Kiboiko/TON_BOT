/**
 * B5. Предпросмотр сайта до публикации — в мобильном и десктопном виде.
 *
 * Быстрый режим рендерит страницу локально (мгновенно), серверный запрашивает
 * /api/sites/{id}/preview — тот самый HTML, который уйдёт в TON Storage.
 */
import { useCallback, useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { sitesApi } from "../../api/endpoints";
import type { Site } from "../../api/types";
import { Button, Loading, Segmented } from "../../components/ui";
import { useAppStore } from "../../store/app";
import { showBackButton } from "../../telegram/webapp";
import { renderSite } from "./render";

type Device = "mobile" | "desktop";
type Source = "local" | "server";

export function PreviewPage() {
  const { siteId = "" } = useParams();
  const navigate = useNavigate();
  const { t } = useTranslation();
  const toastError = useAppStore((s) => s.toastError);

  const [site, setSite] = useState<Site | null>(null);
  const [html, setHtml] = useState("");
  const [device, setDevice] = useState<Device>("mobile");
  const [source, setSource] = useState<Source>("local");
  const [busy, setBusy] = useState(false);

  useEffect(() => showBackButton(() => navigate(`/sites/${siteId}`)), [navigate, siteId]);

  const loadLocal = useCallback((loaded: Site) => {
    setHtml(
      renderSite(loaded.content_json, {
        title: loaded.title,
        domain: loaded.domain,
        customCode: loaded.custom_code,
      }),
    );
  }, []);

  const loadServer = useCallback(async () => {
    setBusy(true);
    try {
      const { preview_html } = await sitesApi.preview(siteId);
      setHtml(preview_html);
    } catch (error) {
      toastError(error);
    } finally {
      setBusy(false);
    }
  }, [siteId, toastError]);

  useEffect(() => {
    sitesApi
      .get(siteId)
      .then(({ site: loaded }) => {
        setSite(loaded);
        loadLocal(loaded);
      })
      .catch(toastError);
  }, [siteId, loadLocal, toastError]);

  useEffect(() => {
    if (source === "server") void loadServer();
    else if (site) loadLocal(site);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [source]);

  if (!site) return <Loading text={t("common.loading")} />;

  return (
    <div className="page">
      <div className="page-header">
        <div>
          <h1>{t("preview.title")}</h1>
          <div className="page-subtitle">{t("preview.hint")}</div>
        </div>
      </div>

      <Segmented<Device>
        value={device}
        onChange={setDevice}
        options={[
          { value: "mobile", label: `📱 ${t("preview.mobile")}` },
          { value: "desktop", label: `🖥 ${t("preview.desktop")}` },
        ]}
      />

      <Segmented<Source>
        value={source}
        onChange={setSource}
        options={[
          { value: "local", label: t("preview.localRender") },
          { value: "server", label: t("preview.serverRender") },
        ]}
      />

      {busy ? (
        <Loading />
      ) : (
        <div className={device === "mobile" ? "preview-phone" : "preview-desktop"}>
          <iframe
            title="site-preview"
            className="preview-frame"
            srcDoc={html}
            sandbox="allow-scripts allow-popups"
          />
        </div>
      )}

      <div className="row">
        <Button block onClick={() => navigate(`/sites/${siteId}`)}>
          {t("common.edit")}
        </Button>
        <Button block variant="primary" onClick={() => navigate(`/sites/${siteId}/publish`)}>
          {t("editor.publish")}
        </Button>
      </div>
    </div>
  );
}
