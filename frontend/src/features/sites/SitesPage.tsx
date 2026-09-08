/** Список сайтов и создание нового по одному из шести шаблонов (B1/B3). */
import { useCallback, useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { ApiError } from "../../api/client";
import { sitesApi } from "../../api/endpoints";
import type { SiteListItem, SiteStatus, SiteType } from "../../api/types";
import { Badge, Button, Empty, Field, Input, Sheet, Skeletons } from "../../components/ui";
import { TEMPLATES } from "../../templates/catalog";
import { useAppStore } from "../../store/app";
import { useEditorStore } from "../../store/editor";
import { haptic, showConfirm } from "../../telegram/webapp";

const STATUS_KIND: Record<SiteStatus, "default" | "success" | "warning" | "danger" | "accent"> = {
  draft: "default",
  publishing: "accent",
  published: "success",
  publish_error: "danger",
  expired: "warning",
};

export function SitesPage() {
  const { t, i18n } = useTranslation();
  const navigate = useNavigate();
  const language = i18n.language.startsWith("en") ? "en" : "ru";
  const toast = useAppStore((s) => s.toast);
  const toastError = useAppStore((s) => s.toastError);

  const [sites, setSites] = useState<SiteListItem[] | null>(null);
  const [creating, setCreating] = useState(false);
  const [template, setTemplate] = useState<SiteType | null>(null);
  const [title, setTitle] = useState("");
  const [busy, setBusy] = useState(false);
  const [limitReached, setLimitReached] = useState(false);

  const load = useCallback(async () => {
    try {
      setSites(await sitesApi.list());
    } catch (error) {
      toastError(error);
      setSites([]);
    }
  }, [toastError]);

  useEffect(() => {
    void load();
  }, [load]);

  async function create(): Promise<void> {
    if (!template || !title.trim()) return;
    setBusy(true);
    try {
      const { site } = await sitesApi.create({ type: template, title: title.trim() });
      haptic.success();
      setCreating(false);
      setTitle("");
      setTemplate(null);
      navigate(`/sites/${site.id}`);
    } catch (error) {
      if (error instanceof ApiError && error.code === "LIMIT_EXCEEDED") {
        setLimitReached(true);
        setCreating(false);
      }
      // тип «Свой код» открывает подписка — ведём на тарифы, а не просто ругаемся
      if (error instanceof ApiError && error.code === "SUBSCRIPTION_REQUIRED") {
        setCreating(false);
        toastError(error);
        navigate("/tariffs");
        return;
      }
      toastError(error);
    } finally {
      setBusy(false);
    }
  }

  async function remove(site: SiteListItem): Promise<void> {
    const confirmed = await showConfirm(t("sites.deleteConfirm", { title: site.title }));
    if (!confirmed) return;
    try {
      await sitesApi.remove(site.id);
      // гасим редактор этого сайта: иначе отложенное автосохранение уйдёт в удалённый id
      useEditorStore.getState().discardIfLoaded(site.id);
      setSites((prev) => (prev ?? []).filter((s) => s.id !== site.id));
      setLimitReached(false);
      toast(t("common.done"), "success");
    } catch (error) {
      toastError(error);
    }
  }

  return (
    <div className="page">
      <div className="page-header">
        <h1>{t("sites.title")}</h1>
        <Button variant="primary" size="sm" onClick={() => setCreating(true)}>
          + {t("sites.create")}
        </Button>
      </div>

      {limitReached ? (
        <div className="notice notice-warning">
          <span>⚠️</span>
          <div>
            <div>{t("sites.limitReached")}</div>
            <Button variant="ghost" size="sm" onClick={() => navigate("/tariffs")}>
              {t("sites.upgrade")} →
            </Button>
          </div>
        </div>
      ) : null}

      {sites === null ? <Skeletons /> : null}

      {sites?.length === 0 ? (
        <Empty
          icon="🌐"
          title={t("sites.empty")}
          hint={t("sites.emptyHint")}
          action={
            <Button variant="primary" onClick={() => setCreating(true)}>
              {t("sites.create")}
            </Button>
          }
        />
      ) : null}

      <div className="list">
        {sites?.map((site) => {
          const template = TEMPLATES.find((tpl) => tpl.type === site.type);
          return (
            <div key={site.id} className="card clickable" onClick={() => navigate(`/sites/${site.id}`)}>
              <div className="card-row">
                <div style={{ fontSize: 26 }}>{template?.icon ?? "📄"}</div>
                <div className="grow">
                  <div className="card-title">{site.title}</div>
                  <div className="card-sub">
                    {site.domain ?? template?.title[language] ?? site.type}
                  </div>
                </div>
                <Badge kind={STATUS_KIND[site.status]}>{t(`sites.status.${site.status}`)}</Badge>
              </div>
              {/* карточка сама по себе кликабельна: без остановки всплытия
                  «Удалить» заодно открывало редактор удаляемого сайта */}
              <div
                className="row"
                style={{ marginTop: 10 }}
                onClick={(event) => event.stopPropagation()}
              >
                <Button size="sm" onClick={() => navigate(`/sites/${site.id}`)}>
                  {t("common.edit")}
                </Button>
                <Button size="sm" onClick={() => navigate(`/sites/${site.id}/preview`)}>
                  {t("editor.preview")}
                </Button>
                <div className="grow" />
                <Button size="sm" variant="danger" onClick={() => void remove(site)}>
                  {t("common.delete")}
                </Button>
              </div>
            </div>
          );
        })}
      </div>

      <Sheet open={creating} title={t("sites.chooseTemplate")} onClose={() => setCreating(false)}>
        <div className="list">
          {TEMPLATES.map((tpl) => (
            <div
              key={tpl.type}
              className="card clickable"
              style={{
                borderLeft: `3px solid ${tpl.type === template ? "var(--accent)" : "transparent"}`,
              }}
              onClick={() => {
                haptic.selection();
                setTemplate(tpl.type);
                if (!title) setTitle(tpl.title[language]);
              }}
            >
              <div className="card-row">
                <div style={{ fontSize: 24 }}>{tpl.icon}</div>
                <div className="grow">
                  <div className="card-title">{tpl.title[language]}</div>
                  <div className="card-sub">{tpl.description[language]}</div>
                </div>
                {tpl.subscriptionOnly ? <Badge kind="accent">{t("sites.subscriptionOnly")}</Badge> : null}
              </div>
            </div>
          ))}
        </div>

        <div style={{ marginTop: 14 }}>
          <Field label={t("sites.namePlaceholder")} hint={t("sites.nameHint")}>
            <Input value={title} onChange={setTitle} placeholder={t("sites.namePlaceholder")} />
          </Field>
        </div>

        <div style={{ marginTop: 14 }}>
          <Button
            variant="primary"
            block
            loading={busy}
            disabled={!template || !title.trim()}
            onClick={() => void create()}
          >
            {t("common.create")}
          </Button>
        </div>
      </Sheet>
    </div>
  );
}
