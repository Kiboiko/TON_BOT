/**
 * B6. Витрина тарифов и оплата подписки через TON Connect.
 *
 * Тарифов много (тариф × срок), поэтому плоский список не годится: срок вынесен
 * в переключатель сверху, а карточки показывают только сами тарифы. Так видны
 * все варианты, а на экране остаётся 4 компактные карточки вместо двух десятков.
 */
import { useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { billingApi } from "../../api/endpoints";
import type { Tariff, TariffDuration } from "../../api/types";
import { TonAmount } from "../../components/TonIcon";
import { Badge, Button, Empty, Loading, Notice } from "../../components/ui";
import { useAppStore } from "../../store/app";
import { useTonPayment } from "../payments/useTonPayment";
import { availableDurations, discountPercent, groupPlans } from "./plans";

export function TariffsPage() {
  const { t } = useTranslation();
  const toast = useAppStore((s) => s.toast);
  const toastError = useAppStore((s) => s.toastError);
  const payment = useTonPayment();

  const [tariffs, setTariffs] = useState<Tariff[] | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [duration, setDuration] = useState<TariffDuration>("month");

  useEffect(() => {
    billingApi
      .tariffs()
      .then(setTariffs)
      .catch((error) => {
        toastError(error);
        setTariffs([]);
      });
  }, [toastError]);

  const plans = useMemo(() => groupPlans(tariffs ?? []), [tariffs]);
  const durations = useMemo(() => availableDurations(plans), [plans]);

  // если помесячной оплаты нет вовсе — открываем первый доступный срок
  useEffect(() => {
    if (durations.length > 0 && !durations.includes(duration)) setDuration(durations[0]);
  }, [durations, duration]);

  async function buy(tariff: Tariff): Promise<void> {
    setBusyId(tariff.id);
    try {
      const { transaction, payment_id } = await billingApi.purchase({ tariff_id: tariff.id });
      const result = await payment.pay(transaction, (txHash) =>
        billingApi.confirm({ payment_id, tx_hash: txHash }),
      );
      if (result) toast(t("tariffs.success"), "success");
    } catch (error) {
      toastError(error);
    } finally {
      setBusyId(null);
    }
  }

  if (tariffs === null) return <Loading text={t("common.loading")} />;

  return (
    <div className="page">
      <div className="page-header">
        <div>
          <h1>{t("tariffs.title")}</h1>
          <div className="page-subtitle">{t("tariffs.subtitle")}</div>
        </div>
      </div>

      {!payment.isConnected ? (
        <div className="card">
          <div className="card-row">
            <div className="grow">
              <div className="card-title">{t("settings.wallet")}</div>
              <div className="card-sub">{t("settings.walletHint")}</div>
            </div>
            <Button variant="primary" size="sm" onClick={payment.connect}>
              {t("domain.connectWallet")}
            </Button>
          </div>
        </div>
      ) : null}

      {payment.stage === "signing" ? <Notice>{t("tariffs.paying")}</Notice> : null}
      {payment.stage === "confirming" ? <Notice>{t("tariffs.confirming")}</Notice> : null}

      {tariffs.length === 0 ? <Empty icon="🏷" title={t("tariffs.empty")} /> : null}

      {durations.length > 1 ? (
        <div className="duration-tabs" role="tablist" aria-label={t("admin.tariffs.duration")}>
          {durations.map((value) => (
            <button
              key={value}
              type="button"
              role="tab"
              aria-selected={value === duration}
              className={value === duration ? "duration-tab active" : "duration-tab"}
              onClick={() => setDuration(value)}
            >
              {t(`tariffs.durationShort.${value}`)}
            </button>
          ))}
        </div>
      ) : null}

      <div className="list">
        {plans.map((plan) => {
          const option = plan.options[duration];
          const discount = discountPercent(plan, duration);

          return (
            <div key={plan.name} className="card tariff-card">
              <div className="tariff">
                <div className="tariff-info">
                  <div className="tariff-name">{plan.name}</div>
                  {plan.description ? <div className="tariff-desc">{plan.description}</div> : null}
                </div>
                <div className="tariff-price">
                  {option ? (
                    <>
                      <TonAmount value={option.price_ton} size={15} className="tariff-price-value" />
                      <div className="tariff-price-note">{t(`tariffs.per.${duration}`)}</div>
                    </>
                  ) : (
                    <div className="tariff-price-note">{t("tariffs.noOption")}</div>
                  )}
                </div>
              </div>

              <div className="row wrap" style={{ marginTop: 4, padding: "0 14px 12px" }}>
                <Badge kind="accent">{t("tariffs.sitesLimit", { count: plan.sites_limit })}</Badge>
                {discount > 0 ? <span className="tariff-save">−{discount}%</span> : null}
                <div className="grow" />
                <Button
                  variant="primary"
                  size="sm"
                  disabled={!option}
                  loading={busyId === option?.id}
                  onClick={() => option && void buy(option)}
                >
                  {t("tariffs.buy")}
                </Button>
              </div>
            </div>
          );
        })}
      </div>

      {plans.length > 0 ? (
        <div className="card-sub">{t("tariffs.priceNote")}</div>
      ) : null}
    </div>
  );
}
