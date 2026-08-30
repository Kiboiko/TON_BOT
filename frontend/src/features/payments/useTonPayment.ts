/**
 * B6. Общий флоу оплаты через TON Connect.
 *
 * Один и тот же сценарий у подписки, премиум-блока и деплоя домена:
 *   backend отдаёт транзакцию → кошелёк её подписывает → мы сообщаем backend-у
 *   хэш → backend проверяет платёж в блокчейне и только потом активирует покупку.
 *
 * Кошелёк возвращает BOC подписанного сообщения — его и передаём как tx_hash,
 * backend ищет платёж по своему комментарию-нонсу, так что этого достаточно.
 */
import { useCallback, useState } from "react";
import { useTonConnectUI, useTonWallet } from "@tonconnect/ui-react";
import type { TonConnectTransaction } from "../../api/types";
import { ApiError } from "../../api/client";
import { useAppStore } from "../../store/app";
import { haptic } from "../../telegram/webapp";

export type PaymentStage = "idle" | "signing" | "confirming" | "done" | "error";

const CONFIRM_RETRIES = 5;
const CONFIRM_DELAY = 4000;

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

export function useTonPayment() {
  const [tonConnectUI] = useTonConnectUI();
  const wallet = useTonWallet();
  const [stage, setStage] = useState<PaymentStage>("idle");
  const toastError = useAppStore((s) => s.toastError);

  const connect = useCallback(() => {
    void tonConnectUI.openModal();
  }, [tonConnectUI]);

  /**
   * Подписывает транзакцию и подтверждает её на backend.
   * `confirm` вызывается с хэшем/BOC; повторяется, пока платёж не увидят в сети.
   */
  const pay = useCallback(
    async <T,>(
      transaction: TonConnectTransaction,
      confirm: (txHash: string) => Promise<T>,
    ): Promise<T | null> => {
      if (!wallet) {
        connect();
        return null;
      }

      setStage("signing");
      let boc: string;
      try {
        const result = await tonConnectUI.sendTransaction({
          validUntil: transaction.validUntil,
          messages: transaction.messages.map((message) => ({
            address: message.address,
            amount: message.amount,
            payload: message.payload ?? undefined,
            stateInit: message.stateInit ?? undefined,
          })),
        });
        boc = result.boc;
      } catch (error) {
        setStage("idle"); // пользователь закрыл кошелёк — это не ошибка
        if (error instanceof Error && /reject|cancel|abort/i.test(error.message)) return null;
        toastError(error);
        setStage("error");
        return null;
      }

      setStage("confirming");
      for (let attempt = 0; attempt < CONFIRM_RETRIES; attempt++) {
        try {
          const result = await confirm(boc);
          haptic.success();
          setStage("done");
          return result;
        } catch (error) {
          const notYetOnChain =
            error instanceof ApiError && error.code === "PAYMENT_NOT_CONFIRMED";
          if (notYetOnChain && attempt < CONFIRM_RETRIES - 1) {
            await sleep(CONFIRM_DELAY);
            continue;
          }
          toastError(error);
          setStage("error");
          return null;
        }
      }
      setStage("error");
      return null;
    },
    [connect, toastError, tonConnectUI, wallet],
  );

  return {
    pay,
    connect,
    stage,
    walletAddress: wallet?.account.address ?? null,
    isConnected: Boolean(wallet),
    reset: () => setStage("idle"),
  };
}
