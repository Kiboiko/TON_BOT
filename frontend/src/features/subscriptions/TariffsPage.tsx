/** B6. Витрина тарифов и оплата подписки через TON Connect. */
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { billingApi } from "../../api/endpoints";
import type { Tariff } from "../../api/types";
import { Badge, Button, Empty, Loading, Notice } from "../../components/ui";
import { useAppStore } from "../../store/app";
import { useTonPayment } from "../payments/useTonPayment";

export function TariffsPage() {
  const { t } = useTranslation();
  const toast = useAppStore((s) => s.toast);
  const toastError = useAppStore((s) => s.toastError);
  const payment = useTonPayment();

  const [tariffs, setTariffs] = useState<Tariff[] | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);

  useEffect(() => {
    billingApi
      .tariffs()
      .then(setTariffs)
      .catch((error) => {
        toastError(error);
        setTariffs([]);
      });
  }, [toastError]);

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

      <div className="list">
        {tariffs.map((tariff) => (
          <div key={tariff.id} className="card">
            <div className="card-row">
              <div className="grow">
                <div className="card-title">{tariff.name}</div>
                <div className="card-sub">{tariff.description}</div>
              </div>
              <div style={{ textAlign: "right" }}>
                <div style={{ fontSize: 22, fontWeight: 700 }}>{tariff.price_ton} TON</div>
                <div className="card-sub">/ {t(`tariffs.duration.${tariff.duration}`)}</div>
              </div>
            </div>
            <div className="row" style={{ marginTop: 10 }}>
              <Badge kind="accent">
                {t("tariffs.sitesLimit", { count: tariff.sites_limit })}
              </Badge>
              {tariff.kind === "pro" ? <Badge>PRO</Badge> : null}
              <div className="grow" />
              <Button
                variant="primary"
                size="sm"
                loading={busyId === tariff.id}
                onClick={() => void buy(tariff)}
              >
                {t("tariffs.buy")}
              </Button>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
