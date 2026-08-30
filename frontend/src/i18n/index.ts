/** i18n RU/EN (B1). Переключение языка синхронизируется с настройкой пользователя. */
import i18n from "i18next";
import { initReactI18next } from "react-i18next";
import { getTelegramLanguage } from "../telegram/webapp";
import { ru } from "./ru";
import { en } from "./en";

void i18n.use(initReactI18next).init({
  resources: {
    ru: { translation: ru },
    en: { translation: en },
  },
  lng: getTelegramLanguage(),
  fallbackLng: "ru",
  interpolation: { escapeValue: false },
});

export default i18n;
