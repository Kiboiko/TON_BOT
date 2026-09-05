/**
 * Профиль: кошелёк (TON Connect + ton_proof), язык, тема.
 *
 * Владение кошельком подтверждается серверу: берём одноразовый payload,
 * просим TON Connect подписать его и отправляем доказательство на backend.
 */
import { useEffect, useRef, useState } from "react";
import { useTonConnectUI, useTonWallet } from "@tonconnect/ui-react";
import { useTranslation } from "react-i18next";
import { isMockEnabled } from "../../api/client";
import { userApi } from "../../api/endpoints";
import type { Language, Theme } from "../../api/types";
import { Badge, Button, Segmented } from "../../components/ui";
import { resetMock } from "../../api/mock";
import { useAppStore } from "../../store/app";

export function SettingsPage() {
  const { t } = useTranslation();
  const [tonConnectUI] = useTonConnectUI();
  const wallet = useTonWallet();

  const user = useAppStore((s) => s.user);
  const theme = useAppStore((s) => s.theme);
  const language = useAppStore((s) => s.language);
  const setTheme = useAppStore((s) => s.setTheme);
  const setLanguage = useAppStore((s) => s.setLanguage);
  const setWallet = useAppStore((s) => s.setWallet);
  const toast = useAppStore((s) => s.toast);
  const toastError = useAppStore((s) => s.toastError);

  const [proofPending, setProofPending] = useState(false);
  const [proofFailed, setProofFailed] = useState(false);
  // счётчик повторов: менять ref недостаточно, эффект должен перезапуститься
  const [retry, setRetry] = useState(0);
  // адреса, для которых доказательство уже отправляли: повтор только по кнопке,
  // иначе ошибка проверки уводит эффект в бесконечный цикл
  const attempted = useRef<Set<string>>(new Set());

  // Запрашиваем nonce заранее: кошелёк должен подписать именно серверный payload.
  useEffect(() => {
    if (wallet) return;
    tonConnectUI.setConnectRequestParameters({ state: "loading" });
    userApi
      .tonProofPayload()
      .then(({ payload }) =>
        tonConnectUI.setConnectRequestParameters({
          state: "ready",
          value: { tonProof: payload },
        }),
      )
      .catch(() => tonConnectUI.setConnectRequestParameters(null));
  }, [tonConnectUI, wallet]);

  // Как только кошелёк подключился с доказательством — отправляем его на backend.
  useEffect(() => {
    if (!wallet || proofPending) return;
    const address = wallet.account.address;
    if (attempted.current.has(address)) return;

    const proof = wallet.connectItems?.tonProof;
    if (!proof || !("proof" in proof)) {
      setWallet(address);
      return;
    }

    attempted.current.add(address);
    setProofFailed(false);
    setProofPending(true);
    userApi
      .connectWallet({
        wallet_address: address,
        ton_proof: {
          timestamp: proof.proof.timestamp,
          domain: proof.proof.domain,
          signature: proof.proof.signature,
          payload: proof.proof.payload,
          state_init: wallet.account.walletStateInit,
        },
      })
      .then(({ wallet_address }) => {
        setWallet(wallet_address);
        toast(t("common.done"), "success");
      })
      .catch((error) => {
        // отметку не снимаем: иначе эффект пойдёт на новый круг и завалит экран
        setProofFailed(true);
        toastError(error);
      })
      .finally(() => setProofPending(false));
  }, [wallet, proofPending, retry, setWallet, t, toast, toastError]);

  const address = user?.wallet_address ?? wallet?.account.address ?? null;

  return (
    <div className="page">
      <div className="page-header">
        <h1>{t("settings.title")}</h1>
        {user?.is_admin ? <Badge kind="accent">admin</Badge> : null}
      </div>

      <div className="card">
        <div className="card-row">
          <div className="grow">
            <div className="card-title">{t("settings.wallet")}</div>
            <div className="card-sub">{t("settings.walletHint")}</div>
          </div>
          {wallet ? (
            <Button size="sm" onClick={() => void tonConnectUI.disconnect()}>
              {t("common.delete")}
            </Button>
          ) : (
            <Button size="sm" variant="primary" onClick={() => void tonConnectUI.openModal()}>
              {t("domain.connectWallet")}
            </Button>
          )}
        </div>
        <div className="mono" style={{ marginTop: 8 }}>
          {proofPending ? t("common.loading") : (address ?? t("settings.notConnected"))}
        </div>

        {proofFailed ? (
          <div style={{ marginTop: 10 }}>
            <div className="field-error">{t("settings.proofFailed")}</div>
            <Button
              size="sm"
              onClick={() => {
                attempted.current.clear();
                setProofFailed(false);
                setRetry((n) => n + 1); // перезапускаем эффект, иначе повтора не будет
              }}
            >
              {t("common.retry")}
            </Button>
          </div>
        ) : null}
      </div>

      <div className="card">
        <div className="card-title" style={{ marginBottom: 8 }}>
          {t("settings.language")}
        </div>
        <Segmented<Language>
          value={language}
          onChange={(value) => setLanguage(value)}
          options={[
            { value: "ru", label: "Русский" },
            { value: "en", label: "English" },
          ]}
        />
      </div>

      <div className="card">
        <div className="card-title" style={{ marginBottom: 8 }}>
          {t("settings.theme")}
        </div>
        <Segmented<Theme>
          value={theme}
          onChange={(value) => setTheme(value)}
          options={[
            { value: "light", label: `☀️ ${t("settings.themeLight")}` },
            { value: "dark", label: `🌙 ${t("settings.themeDark")}` },
          ]}
        />
      </div>

      <div className="card">
        <div className="card-row">
          <div className="grow">
            <div className="card-title">{t("settings.about")}</div>
            <div className="card-sub">TON Site Builder · {t("settings.version")} 1.0.0</div>
          </div>
          {isMockEnabled() ? <Badge kind="warning">{t("auth.mockBadge")}</Badge> : null}
        </div>
        {isMockEnabled() ? (
          <div style={{ marginTop: 10 }}>
            <Button
              size="sm"
              variant="danger"
              onClick={() => {
                resetMock();
                window.location.reload();
              }}
            >
              {t("settings.resetDemo")}
            </Button>
          </div>
        ) : null}
      </div>
    </div>
  );
}
