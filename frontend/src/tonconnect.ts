/**
 * Адрес манифеста TON Connect для кошельков.
 *
 * Кошелёк скачивает манифест сам, со своей стороны, поэтому адрес обязан быть
 * абсолютным. Относительный путь из .env (`/tonconnect-manifest.json`) кошелёк
 * разрешить не может: Tonkeeper отвечает «не удалось загрузить манифест», а
 * Telegram Wallet — «ошибка манифеста». Достраиваем адрес от домена, на котором
 * открыто приложение; полный адрес оставляем как есть.
 */
const DEFAULT_MANIFEST_PATH = "/tonconnect-manifest.json";

export function resolveManifestUrl(value: string | undefined, origin: string): string {
  return new URL(value?.trim() || DEFAULT_MANIFEST_PATH, origin).href;
}
