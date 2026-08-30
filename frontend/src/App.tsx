/** Каркас приложения: авторизация, тема, роутинг, нижняя навигация. */
import { useEffect } from "react";
import { NavLink, Navigate, Route, Routes } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { isMockEnabled } from "./api/client";
import { Button, Loading, Toasts } from "./components/ui";
import { AdminPage } from "./features/admin/AdminPage";
import { CustomCodePage } from "./features/editor/CustomCodePage";
import { EditorPage } from "./features/editor/EditorPage";
import { PreviewPage } from "./features/preview/PreviewPage";
import { PublishPage } from "./features/publish/PublishPage";
import { SettingsPage } from "./features/settings/SettingsPage";
import { SitesPage } from "./features/sites/SitesPage";
import { SubscriptionsPage } from "./features/subscriptions/SubscriptionsPage";
import { TariffsPage } from "./features/subscriptions/TariffsPage";
import { useAppStore } from "./store/app";
import { getTelegramTheme, initTelegram, isTelegram, onThemeChanged } from "./telegram/webapp";

function TabBar() {
  const { t } = useTranslation();
  const isAdmin = useAppStore((s) => s.user?.is_admin ?? false);

  const tabs = [
    { to: "/sites", icon: "🗂", label: t("nav.sites") },
    { to: "/subscriptions", icon: "💎", label: t("nav.subscriptions") },
    { to: "/settings", icon: "👤", label: t("nav.settings") },
    ...(isAdmin ? [{ to: "/admin", icon: "🛠", label: t("nav.admin") }] : []),
  ];

  return (
    <nav className="tabbar">
      {tabs.map((tab) => (
        <NavLink key={tab.to} to={tab.to} className={({ isActive }) => (isActive ? "active" : "")}>
          <span className="tab-icon">{tab.icon}</span>
          <span>{tab.label}</span>
        </NavLink>
      ))}
    </nav>
  );
}

export function App() {
  const { t } = useTranslation();
  const { user, loading, authError, auth, setTheme } = useAppStore();

  useEffect(() => {
    initTelegram();
    setTheme(getTelegramTheme(), false);
    void auth().catch(() => undefined);
    // тема Telegram может измениться на лету — следуем за ней, пока пользователь
    // не выбрал собственную в профиле
    return onThemeChanged(() => setTheme(getTelegramTheme(), false));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  if (loading) return <Loading text={t("auth.connecting")} />;

  if (!user) {
    return (
      <div className="page">
        <div className="empty">
          <div className="empty-icon">🔌</div>
          <div className="card-title">{t("auth.failed")}</div>
          <div className="card-sub">{authError}</div>
          <Button variant="primary" onClick={() => void auth().catch(() => undefined)}>
            {t("common.retry")}
          </Button>
        </div>
        <Toasts />
      </div>
    );
  }

  return (
    <div className="app">
      {isMockEnabled() && !isTelegram() ? (
        <div className="notice notice-warning" style={{ margin: 12 }}>
          <span>🧪</span>
          <div>{t("auth.outsideTelegram")}</div>
        </div>
      ) : null}

      <Routes>
        <Route path="/" element={<Navigate to="/sites" replace />} />
        <Route path="/sites" element={<SitesPage />} />
        <Route path="/sites/:siteId" element={<EditorPage />} />
        <Route path="/sites/:siteId/preview" element={<PreviewPage />} />
        <Route path="/sites/:siteId/publish" element={<PublishPage />} />
        <Route path="/sites/:siteId/custom-code" element={<CustomCodePage />} />
        <Route path="/tariffs" element={<TariffsPage />} />
        <Route path="/subscriptions" element={<SubscriptionsPage />} />
        <Route path="/settings" element={<SettingsPage />} />
        <Route path="/admin" element={<AdminPage />} />
        <Route path="*" element={<Navigate to="/sites" replace />} />
      </Routes>

      <TabBar />
      <Toasts />
    </div>
  );
}
