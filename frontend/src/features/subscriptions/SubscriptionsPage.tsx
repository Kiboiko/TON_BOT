/** B6. Экран «Мои подписки»: сроки, статусы, продление и напоминание о триале. */
import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { billingApi } from "../../api/endpoints";
import type { Subscription, SubscriptionStatus } from "../../api/types";
import { TonIcon } from "../../components/TonIcon";
import { Badge, Button, Empty, Loading, Notice } from "../../components/ui";
import { useAppStore } from "../../store/app";

const STATUS_KIND: Record<SubscriptionStatus, "success" | "warning" | "danger" | "accent"> = {
  active: "success",
  expiring_soon: "warning",
  expired: "danger",
  manual: "accent",
};

function formatDate(value: string | null): string {
  return value ? new Date(value).toLocaleDateString() : "";
}

export function SubscriptionsPage() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const toastError = useAppStore((s) => s.toastError);
  const [subs, setSubs] = useState<Subscription[] | null>(null);

  useEffect(() => {
    billingApi
      .subscriptions()
      .then(setSubs)
      .catch((error) => {
        toastError(error);
        setSubs([]);
      });
  }, [toastError]);

  if (subs === null) return <Loading text={t("common.loading")} />;

  const expiring = subs.find((s) => s.status === "expiring_soon");
  const expired = subs.find((s) => s.status === "expired");

  return (
    <div className="page">
      <div className="page-header">
        <h1>{t("subscriptions.title")}</h1>
        <Button size="sm" variant="primary" onClick={() => navigate("/tariffs")}>
          {t("tariffs.title")}
        </Button>
      </div>

      {expiring ? (
        <Notice kind="warning">
          {t("subscriptions.expiringNotice", { date: formatDate(expiring.expires_at) })}
        </Notice>
      ) : null}
      {!expiring && expired ? <Notice kind="danger">{t("subscriptions.expiredNotice")}</Notice> : null}

      {subs.length === 0 ? (
        <Empty
          icon={<TonIcon size={40} />}
          title={t("subscriptions.empty")}
          hint={t("tariffs.subtitle")}
          action={
            <Button variant="primary" onClick={() => navigate("/tariffs")}>
              {t("tariffs.title")}
            </Button>
          }
        />
      ) : null}

      <div className="list">
        {subs.map((sub) => (
          <div key={sub.id} className="card">
            <div className="card-row">
              <div className="grow">
                <div className="card-title">
                  {sub.tariff?.name ?? (sub.is_trial ? t("subscriptions.trial") : "—")}
                </div>
                <div className="card-sub">
                  {sub.is_forever
                    ? t("subscriptions.forever")
                    : t("subscriptions.until", { date: formatDate(sub.expires_at) })}
                </div>
              </div>
              <Badge kind={STATUS_KIND[sub.status]}>{t(`subscriptions.status.${sub.status}`)}</Badge>
            </div>

            <div className="row" style={{ marginTop: 10 }}>
              {sub.is_trial ? <Badge>{t("subscriptions.trial")}</Badge> : null}
              {sub.granted_by_admin ? <Badge kind="accent">{t("subscriptions.manual")}</Badge> : null}
              {sub.tariff ? (
                <Badge>{t("tariffs.sitesLimit", { count: sub.tariff.sites_limit })}</Badge>
              ) : null}
              <div className="grow" />
              {sub.status !== "active" || sub.is_trial ? (
                <Button size="sm" variant="primary" onClick={() => navigate("/tariffs")}>
                  {t("subscriptions.renew")}
                </Button>
              ) : null}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
