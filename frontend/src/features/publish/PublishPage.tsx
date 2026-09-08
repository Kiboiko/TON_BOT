/**
 * B6. Флоу публикации: домен → деплой зоны через TON Connect → публикация
 * с поллингом статуса → привязка bag id к домену.
 */
import { useCallback, useEffect, useRef, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { ApiError } from "../../api/client";
import { domainsApi, sitesApi } from "../../api/endpoints";
import type { DomainCheck, Site, SiteStatus } from "../../api/types";
import { Badge, Button, Field, Input, Loading, Notice, Segmented } from "../../components/ui";
import { useAppStore } from "../../store/app";
import { haptic, openLink, showBackButton } from "../../telegram/webapp";
import { useTonPayment } from "../payments/useTonPayment";

const DOMAIN_RE = /^[a-z0-9][a-z0-9-]{2,124}$/;
const POLL_INTERVAL = 2500;
// после этого времени «публикуется» перестаёт быть нормальным ожиданием:
// показываем причину и даём повторить, а не крутим спиннер бесконечно
const SLOW_AFTER_MS = 60_000;

export function PublishPage() {
  const { siteId = "" } = useParams();
  const navigate = useNavigate();
  const { t } = useTranslation();
  const toast = useAppStore((s) => s.toast);
  const toastError = useAppStore((s) => s.toastError);
  const payment = useTonPayment();

  const [site, setSite] = useState<Site | null>(null);
  const [status, setStatus] = useState<SiteStatus | null>(null);
  const [publishError, setPublishError] = useState<string | null>(null);
  const [bagId, setBagId] = useState<string | null>(null);
  const [publicUrl, setPublicUrl] = useState<string | null>(null);

  // ТЗ допускает и свой домен, и субдомен: «мини-сайты на доменах/субдоменах TON»
  const [mode, setMode] = useState<"subdomain" | "own">("subdomain");
  const [name, setName] = useState("");
  const [ownDomain, setOwnDomain] = useState("");
  const [attaching, setAttaching] = useState(false);
  // null — проверить не удалось; кнопку прячем только при явном true
  const [directReady, setDirectReady] = useState<boolean | null>(null);
  const [check, setCheck] = useState<DomainCheck | null>(null);
  const [checking, setChecking] = useState(false);
  const [publishing, setPublishing] = useState(false);
  const [slow, setSlow] = useState(false);

  const pollTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => showBackButton(() => navigate(`/sites/${siteId}`)), [navigate, siteId]);

  useEffect(() => {
    sitesApi
      .get(siteId)
      .then(({ site: loaded }) => {
        setSite(loaded);
        setStatus(loaded.status);
        setBagId(loaded.storage_bag_id);
        if (loaded.status === "published") {
          void sitesApi.publishStatus(siteId).then((s) => setPublicUrl(s.public_url));
        }
        if (loaded.domain) {
          setName(loaded.domain.split(".")[0]);
          // одна проверка при открытии: если домен уже направлен на сайт,
          // подпись повторно не предлагаем
          void sitesApi
            .dnsStatus(siteId)
            .then((s) => setDirectReady(s.direct))
            .catch(() => setDirectReady(null));
        }
        if (loaded.status === "publishing") startPolling();
      })
      .catch(toastError);
    return () => {
      if (pollTimer.current) clearTimeout(pollTimer.current);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [siteId]);

  const startPolling = useCallback(() => {
    if (pollTimer.current) clearTimeout(pollTimer.current);
    const startedAt = Date.now();
    const tick = async () => {
      try {
        const result = await sitesApi.publishStatus(siteId);
        setStatus(result.status);
        setBagId(result.storage_bag_id);
        setPublicUrl(result.public_url);
        setPublishError(result.error);
        if (result.status === "publishing") {
          setSlow(Date.now() - startedAt > SLOW_AFTER_MS);
          pollTimer.current = setTimeout(() => void tick(), POLL_INTERVAL);
        } else if (result.status === "published") {
          setSlow(false);
          haptic.success();
          toast(t("publish.published"), "success");
        } else if (result.status === "publish_error") {
          haptic.error();
        }
      } catch (error) {
        toastError(error);
      }
    };
    pollTimer.current = setTimeout(() => void tick(), POLL_INTERVAL);
  }, [siteId, t, toast, toastError]);

  const nameValid = DOMAIN_RE.test(name.trim().toLowerCase());

  async function checkDomain(): Promise<void> {
    if (!nameValid) return;
    setChecking(true);
    try {
      setCheck(await domainsApi.check(name.trim().toLowerCase()));
    } catch (error) {
      if (error instanceof ApiError && error.code === "ZONE_NOT_CONFIGURED") {
        toast(t("domain.zoneNotReady"), "error");
        return;
      }
      toastError(error);
    } finally {
      setChecking(false);
    }
  }

  async function attachOwnDomain(): Promise<void> {
    const domain = ownDomain.trim().toLowerCase();
    if (!domain.includes(".")) return;
    setAttaching(true);
    try {
      const result = await domainsApi.attach({ site_id: siteId, domain });
      toast(t("domain.attached"), "success");
      const { site: updated } = await sitesApi.get(siteId);
      setSite(updated);
      if (result.needs_publish) await publish();
    } catch (error) {
      toastError(error);
    } finally {
      setAttaching(false);
    }
  }

  async function attachDomain(): Promise<void> {
    try {
      const { transaction, domain, already_owned } = await domainsApi.claim({
        site_id: siteId,
        name: name.trim().toLowerCase(),
      });

      // Субдомен уже выпущен на этот кошелёк — платить второй раз не за что.
      // Так бывает, когда кошелёк отдал ошибку, хотя транзакция ушла.
      if (already_owned || !transaction) {
        toast(t("domain.attached"), "success");
        const { site: owned } = await sitesApi.get(siteId);
        setSite(owned);
        void checkDirect();
        return;
      }

      // домен закрепится за сайтом только после того, как backend увидит
      // выпущенный субдомен в блокчейне, поэтому передаём его явно
      const result = await payment.pay(transaction, (txHash) =>
        domainsApi.confirm({ site_id: siteId, tx_hash: txHash, domain }),
      );
      if (result && result.status === "pending") {
        // выпуск ещё не долетел до сети: оплата прошла, домен закрепится с
        // повторного нажатия — молча показывать успех здесь было бы враньём
        toast(t("domain.pending"), "info");
        return;
      }
      if (result) {
        toast(t("domain.attached"), "success");
        const { site: updated } = await sitesApi.get(siteId);
        setSite(updated);
        setStatus(updated.status);
        if (updated.status === "publishing") startPolling();
      }
    } catch (error) {
      if (error instanceof ApiError && error.code === "WALLET_NOT_CONNECTED") {
        payment.connect();
        return;
      }
      toastError(error);
    }
  }

  async function publish(): Promise<void> {
    setPublishing(true);
    setPublishError(null);
    setSlow(false);
    try {
      await sitesApi.publish(siteId);
      setStatus("publishing");
      startPolling();
    } catch (error) {
      if (error instanceof ApiError && error.isPaymentRelated) {
        toast(t("publish.subscriptionRequired"), "error");
        navigate("/tariffs");
        return;
      }
      toastError(error);
    } finally {
      setPublishing(false);
    }
  }

  // Единственный способ привязки: домен ведёт прямо на наш сервер. Раздача
  // через TON Storage зависит от публичных шлюзов, а они бэги новых сайтов не
  // отдают. Адрес прокси не меняется, поэтому подпись нужна один раз на домен.
  async function bindSite(): Promise<void> {
    try {
      const { transaction } = await sitesApi.siteBind(siteId);
      const result = await payment.pay(transaction, async () => ({ ok: true }));
      if (result) {
        toast(t("publish.bound"), "success");
        void checkDirect();
      }
    } catch (error) {
      toastError(error);
    }
  }

  async function checkDirect(): Promise<void> {
    try {
      setDirectReady((await sitesApi.dnsStatus(siteId)).direct);
    } catch {
      setDirectReady(null);
    }
  }

  if (!site) return <Loading text={t("common.loading")} />;

  return (
    <div className="page">
      <div className="page-header">
        <div className="grow">
          <h1>{t("publish.title")}</h1>
          <div className="page-subtitle">{site.title}</div>
        </div>
        {status ? (
          <Badge
            kind={
              status === "published"
                ? "success"
                : status === "publish_error"
                  ? "danger"
                  : status === "publishing"
                    ? "accent"
                    : "default"
            }
          >
            {t(`sites.status.${status}`)}
          </Badge>
        ) : null}
      </div>

      {/* --- домен --- */}
      <div className="card">
        <div className="card-title">{t("domain.title")}</div>
        <div className="card-sub" style={{ marginBottom: 10 }}>
          {t("domain.subtitle")}
        </div>

        {site.domain ? (
          <div className="row-between">
            <div>
              <div className="card-sub">{t("domain.current")}</div>
              <b>{site.domain}</b>
            </div>
            <Badge kind="success">✓</Badge>
          </div>
        ) : (
          <>
            <Segmented<"subdomain" | "own">
              value={mode}
              onChange={setMode}
              options={[
                { value: "subdomain", label: t("domain.modeSubdomain") },
                { value: "own", label: t("domain.modeOwn") },
              ]}
            />

            {mode === "own" ? (
              <div style={{ marginTop: 12 }}>
                <Field label={t("domain.ownLabel")} hint={t("domain.ownHint")}>
                  <Input
                    value={ownDomain}
                    onChange={(value) => setOwnDomain(value.toLowerCase())}
                    placeholder="mysite.ton"
                  />
                </Field>
                <div style={{ marginTop: 10 }}>
                  {payment.isConnected ? (
                    <Button
                      variant="primary"
                      block
                      loading={attaching}
                      disabled={!ownDomain.includes(".")}
                      onClick={() => void attachOwnDomain()}
                    >
                      {t("domain.attachOwn")}
                    </Button>
                  ) : (
                    <Button variant="primary" block onClick={payment.connect}>
                      {t("domain.connectWallet")}
                    </Button>
                  )}
                </div>
              </div>
            ) : (
              <>
            <Field error={name && !nameValid ? t("domain.invalid") : undefined}>
              <div className="row">
                <div className="grow">
                  <Input
                    value={name}
                    onChange={(value) => {
                      setName(value.toLowerCase());
                      setCheck(null);
                    }}
                    placeholder={t("domain.placeholder")}
                    invalid={Boolean(name) && !nameValid}
                  />
                </div>
                <span className="card-sub">.{check?.zone ?? t("domain.zoneSuffix")}</span>
                <Button size="sm" loading={checking} disabled={!nameValid} onClick={() => void checkDomain()}>
                  {t("domain.check")}
                </Button>
              </div>
            </Field>

            {check ? (
              <div style={{ marginTop: 8 }}>
                <Badge kind={check.available ? "success" : "danger"}>
                  {check.available ? t("domain.available") : t("domain.taken")}
                </Badge>
                <div className="mono" style={{ marginTop: 6 }}>
                  {check.domain}
                </div>
              </div>
            ) : null}

            <div style={{ marginTop: 12 }}>
              {payment.isConnected ? (
                <Button
                  variant="primary"
                  block
                  disabled={!check?.available}
                  loading={payment.stage === "signing" || payment.stage === "confirming"}
                  onClick={() => void attachDomain()}
                >
                  {t("domain.deploy")}
                </Button>
              ) : (
                <Button variant="primary" block onClick={payment.connect}>
                  {t("domain.connectWallet")}
                </Button>
              )}
            </div>
            {payment.stage === "confirming" ? <Notice>{t("domain.waiting")}</Notice> : null}
              </>
            )}
          </>
        )}
      </div>

      {/* --- публикация --- */}
      <div className="card">
        <div className="card-title">{t("publish.title")}</div>

        {status === "publishing" ? (
          <>
            <div className="center">
              <div className="spinner spinner-lg" />
              <div>{t("publish.publishing")}</div>
            </div>
            <div className="card-sub">{t("publish.publishingHint")}</div>
            {slow ? (
              <div style={{ marginTop: 12 }}>
                <Notice kind="warning">{t("publish.stuck")}</Notice>
                <Button block loading={publishing} onClick={() => void publish()}>
                  {t("publish.retry")}
                </Button>
              </div>
            ) : null}
          </>
        ) : null}

        {status === "published" ? (
          <>
            <div className="row" style={{ marginTop: 8 }}>
              <Badge kind="success">✓ {t("publish.published")}</Badge>
            </div>
            {site.published_at ? (
              <div className="card-sub" style={{ marginTop: 6 }}>
                {t("publish.publishedAt", {
                  date: new Date(site.published_at).toLocaleString(),
                })}
              </div>
            ) : null}
            {publicUrl ? (
              <div style={{ marginTop: 12 }}>
                <Button variant="primary" block onClick={() => openLink(publicUrl)}>
                  🌐 {t("publish.openSite")}
                </Button>
                <div
                  className="mono"
                  style={{ marginTop: 8, cursor: "pointer" }}
                  onClick={() => {
                    void navigator.clipboard?.writeText(publicUrl);
                    toast(t("common.copied"), "success");
                  }}
                >
                  {publicUrl}
                </div>
                <div className="card-sub" style={{ marginTop: 4 }}>
                  {t("publish.openHint")}
                </div>
              </div>
            ) : null}

            {bagId ? (
              <div style={{ marginTop: 12 }}>
                <div className="card-sub">{t("publish.bagId")}</div>
                <div className="mono">{bagId}</div>
              </div>
            ) : null}
            {site.domain ? (
              <div style={{ marginTop: 12 }}>
                {directReady === true ? (
                  <Notice kind="info">✅ {t("publish.domainReady")}</Notice>
                ) : (
                  <>
                    <div className="card-sub" style={{ marginBottom: 6 }}>
                      {t("publish.bindSiteHint")}
                    </div>
                    <Button block variant="primary" onClick={() => void bindSite()}>
                      🌐 {t("publish.bindSite")}
                    </Button>
                  </>
                )}
              </div>
            ) : null}
          </>
        ) : null}

        {status === "publish_error" ? (
          <Notice kind="danger">
            {t("publish.error")}
            {publishError ? <div className="mono">{publishError}</div> : null}
          </Notice>
        ) : null}

        {status !== "publishing" ? (
          <div style={{ marginTop: 12 }}>
            <Button variant="primary" block loading={publishing} onClick={() => void publish()}>
              {status === "published" || status === "publish_error"
                ? t("publish.retry")
                : t("editor.publish")}
            </Button>
          </div>
        ) : null}
      </div>

      <Notice>{t("publish.trialNotice")}</Notice>
    </div>
  );
}
