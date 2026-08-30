/**
 * B4. Премиум-блок «Свой код».
 *
 * До подтверждённой оплаты редактор заблокирован — цена приходит из админки
 * вместе с транзакцией. После оплаты код сохраняется и показывается в превью
 * внутри изолированного iframe.
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
import { useTonPayment } from "../payments/useTonPayment";
import { renderCustomCode } from "../preview/render";

type CodeTab = "html" | "css" | "js";

/** Лёгкий редактор кода: моноширинный ввод с сохранением табов и отступов. */
function CodeArea({
  value,
  onChange,
  language,
  disabled,
}: {
  value: string;
  onChange: (value: string) => void;
  language: string;
  disabled?: boolean;
}) {
  return (
    <div className="code-editor">
      <span className="code-lang">{language}</span>
      <textarea
        value={value}
        disabled={disabled}
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
  const payment = useTonPayment();

  const [site, setSite] = useState<Site | null>(null);
  const [tab, setTab] = useState<CodeTab>("html");
  const [code, setCode] = useState<CustomCode>({ html: "", css: "", js: "" });
  const [saving, setSaving] = useState(false);

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

  async function buy(): Promise<void> {
    try {
      const { transaction, payment_id } = await sitesApi.customCodePurchase(siteId);
      const result = await payment.pay(transaction, (txHash) =>
        sitesApi.customCodeConfirm(siteId, { payment_id, tx_hash: txHash }),
      );
      if (result) {
        setSite((prev) => (prev ? { ...prev, custom_code_paid: true } : prev));
        toast(t("customCode.paid"), "success");
      }
    } catch (error) {
      if (error instanceof ApiError && error.code === "TARIFF_NOT_FOUND") {
        toast(t("customCode.notConfigured"), "error");
        return;
      }
      toastError(error);
    }
  }

  async function save(): Promise<void> {
    setSaving(true);
    try {
      await sitesApi.setCustomCode(siteId, code);
      toast(t("common.saved"), "success");
    } catch (error) {
      toastError(error);
    } finally {
      setSaving(false);
    }
  }

  if (!site) return <Loading text={t("common.loading")} />;

  const paid = site.custom_code_paid;

  return (
    <div className="page">
      <div className="page-header">
        <div className="grow">
          <h1>{t("customCode.title")}</h1>
          <div className="page-subtitle">{site.title}</div>
        </div>
        {paid ? <Badge kind="success">{t("customCode.paid")}</Badge> : <Badge>🔒</Badge>}
      </div>

      <Notice>{t("customCode.description")}</Notice>

      {!paid ? (
        <div className="card">
          <div className="card-title">{t("customCode.locked")}</div>
          <div className="card-sub" style={{ marginTop: 4 }}>
            {payment.stage === "confirming"
              ? t("tariffs.confirming")
              : payment.stage === "signing"
                ? t("tariffs.paying")
                : t("customCode.description")}
          </div>
          <div style={{ marginTop: 12 }}>
            {payment.isConnected ? (
              <Button
                variant="primary"
                block
                loading={payment.stage === "signing" || payment.stage === "confirming"}
                onClick={() => void buy()}
              >
                {t("customCode.buy", { price: "—" })}
              </Button>
            ) : (
              <Button variant="primary" block onClick={payment.connect}>
                {t("domain.connectWallet")}
              </Button>
            )}
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
        disabled={!paid}
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

      <Button variant="primary" block disabled={!paid} loading={saving} onClick={() => void save()}>
        {t("customCode.save")}
      </Button>
    </div>
  );
}
