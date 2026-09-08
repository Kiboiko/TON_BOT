/**
 * Блок «Об авторе проекта» из ТЗ: отдельная страница со ссылкой.
 *
 * Текст и ссылку задаёт администратор, поэтому страница ничего не знает о
 * содержимом и просто показывает то, что вернул backend.
 */
import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { aboutApi } from "../../api/endpoints";
import type { About } from "../../api/types";
import { Button, LoadFailed, Loading, PageHead } from "../../components/ui";
import { useAppStore } from "../../store/app";
import { openLink, showBackButton } from "../../telegram/webapp";

export function AboutPage() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const toastError = useAppStore((s) => s.toastError);
  const [about, setAbout] = useState<About | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => showBackButton(() => navigate("/settings")), [navigate]);

  useEffect(() => {
    aboutApi
      .get()
      .then(setAbout)
      .catch((error) => {
        toastError(error);
        setFailed(true);
      });
  }, [toastError]);

  if (failed)
    return (
      <LoadFailed
        title={t("about.failed")}
        onBack={() => navigate("/settings")}
        backLabel={t("common.back")}
      />
    );
  if (!about) return <Loading text={t("common.loading")} />;

  return (
    <div className="page">
      <PageHead title={t("about.title")} onBack={() => navigate("/settings")} />

      <div className="card">
        <div className="card-title" style={{ fontSize: 18 }}>
          {about.title}
        </div>
        <p className="card-sub" style={{ marginTop: 8, whiteSpace: "pre-wrap" }}>
          {about.text}
        </p>
        {about.link_url ? (
          <div style={{ marginTop: 14 }}>
            <Button variant="primary" block onClick={() => openLink(about.link_url)}>
              {about.link_label || t("about.open")}
            </Button>
          </div>
        ) : null}
      </div>

      <div className="card-sub" style={{ textAlign: "center" }}>
        TON Site Builder · {t("settings.version")} 1.0.0
      </div>
    </div>
  );
}
