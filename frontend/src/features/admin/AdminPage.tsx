/**
 * B7. Админ-панель: доступна только при is_admin.
 * Разделы: статистика, пользователи (с карточкой и выдачей доступа), тарифы, домены.
 */
import { useCallback, useEffect, useState } from "react";
import { Navigate } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { adminApi } from "../../api/endpoints";
import type {
  AdminDomainItem,
  AdminStats,
  AdminUserDetail,
  AdminUserListItem,
  Tariff,
  TariffDuration,
  TariffKind,
} from "../../api/types";
import {
  Badge,
  Button,
  Empty,
  Field,
  Input,
  Loading,
  Segmented,
  Select,
  Sheet,
  Skeletons,
} from "../../components/ui";
import { useAppStore } from "../../store/app";
import { showConfirm } from "../../telegram/webapp";

type Tab = "stats" | "users" | "tariffs" | "domains";

const DURATIONS: TariffDuration[] = ["month", "3month", "6month", "12month", "forever"];
const KINDS: TariffKind[] = ["base", "pro", "custom_code"];

export function AdminPage() {
  const { t } = useTranslation();
  const user = useAppStore((s) => s.user);
  const [tab, setTab] = useState<Tab>("stats");

  if (user && !user.is_admin) return <Navigate to="/sites" replace />;

  return (
    <div className="page">
      <div className="page-header">
        <h1>{t("admin.title")}</h1>
        <Badge kind="accent">admin</Badge>
      </div>

      <Segmented<Tab>
        value={tab}
        onChange={setTab}
        options={[
          { value: "stats", label: t("admin.tabs.stats") },
          { value: "users", label: t("admin.tabs.users") },
          { value: "tariffs", label: t("admin.tabs.tariffs") },
          { value: "domains", label: t("admin.tabs.domains") },
        ]}
      />

      {tab === "stats" ? <StatsTab /> : null}
      {tab === "users" ? <UsersTab /> : null}
      {tab === "tariffs" ? <TariffsTab /> : null}
      {tab === "domains" ? <DomainsTab /> : null}
    </div>
  );
}

function StatsTab() {
  const { t } = useTranslation();
  const toastError = useAppStore((s) => s.toastError);
  const [stats, setStats] = useState<AdminStats | null>(null);

  useEffect(() => {
    adminApi.stats().then(setStats).catch(toastError);
  }, [toastError]);

  if (!stats) return <Loading />;

  const cells: [string, string | number][] = [
    [t("admin.stats.users"), stats.total_users],
    [t("admin.stats.sites"), stats.total_sites],
    [t("admin.stats.published"), stats.published_sites],
    [t("admin.stats.subscriptions"), stats.active_subscriptions],
    [t("admin.stats.revenue"), stats.revenue],
    [t("admin.stats.revenue30"), stats.revenue_last_30d],
    [t("admin.stats.payments"), stats.payments_confirmed],
  ];

  return (
    <div className="stat-grid">
      {cells.map(([label, value]) => (
        <div className="stat" key={label}>
          <div className="stat-value">{value}</div>
          <div className="stat-label">{label}</div>
        </div>
      ))}
    </div>
  );
}

function UsersTab() {
  const { t } = useTranslation();
  const toast = useAppStore((s) => s.toast);
  const toastError = useAppStore((s) => s.toastError);

  const [search, setSearch] = useState("");
  const [page, setPage] = useState(1);
  const [data, setData] = useState<{ users: AdminUserListItem[]; total: number } | null>(null);
  const [detail, setDetail] = useState<AdminUserDetail | null>(null);
  const [granting, setGranting] = useState(false);
  const [tariffs, setTariffs] = useState<Tariff[]>([]);
  const [grantForm, setGrantForm] = useState<{
    tariff_id: string;
    duration: TariffDuration;
    sites_limit: string;
    comment: string;
  }>({ tariff_id: "", duration: "month", sites_limit: "5", comment: "" });

  const load = useCallback(async () => {
    try {
      setData(await adminApi.users({ search, page, per_page: 20 }));
    } catch (error) {
      toastError(error);
    }
  }, [search, page, toastError]);

  useEffect(() => {
    const timer = setTimeout(() => void load(), 300);
    return () => clearTimeout(timer);
  }, [load]);

  useEffect(() => {
    adminApi.tariffs().then(setTariffs).catch(() => undefined);
  }, []);

  async function openUser(id: string): Promise<void> {
    try {
      setDetail(await adminApi.user(id));
    } catch (error) {
      toastError(error);
    }
  }

  async function grant(): Promise<void> {
    if (!detail) return;
    try {
      await adminApi.grantAccess(detail.user.id, {
        tariff_id: grantForm.tariff_id || undefined,
        duration: grantForm.duration,
        sites_limit: grantForm.tariff_id ? undefined : Number(grantForm.sites_limit),
        comment: grantForm.comment || undefined,
      });
      toast(t("admin.users.granted"), "success");
      setGranting(false);
      await openUser(detail.user.id);
      await load();
    } catch (error) {
      toastError(error);
    }
  }

  async function revoke(subscriptionId: string): Promise<void> {
    if (!detail) return;
    const confirmed = await showConfirm(t("admin.users.revoke") + "?");
    if (!confirmed) return;
    try {
      await adminApi.revokeAccess(detail.user.id, subscriptionId);
      toast(t("admin.users.revoked"), "success");
      await openUser(detail.user.id);
    } catch (error) {
      toastError(error);
    }
  }

  return (
    <>
      <Input value={search} onChange={(value) => { setSearch(value); setPage(1); }} placeholder={t("admin.users.search")} />

      {!data ? <Skeletons /> : null}
      {data?.users.length === 0 ? <Empty icon="🔍" title={t("admin.users.empty")} /> : null}

      <div className="list">
        {data?.users.map((item) => (
          <div key={item.id} className="card clickable" onClick={() => void openUser(item.id)}>
            <div className="card-row">
              <div className="grow">
                <div className="card-title">
                  {item.username ? `@${item.username}` : `id ${item.telegram_id}`}
                </div>
                <div className="card-sub">
                  {item.sites_count} {t("admin.users.sites")} · {item.active_subscriptions}{" "}
                  {t("admin.users.subs")}
                </div>
              </div>
              {item.is_admin ? <Badge kind="accent">admin</Badge> : null}
              {item.is_blocked ? <Badge kind="danger">blocked</Badge> : null}
            </div>
          </div>
        ))}
      </div>

      {data && data.total > 20 ? (
        <div className="row">
          <Button size="sm" disabled={page === 1} onClick={() => setPage((p) => p - 1)}>
            ←
          </Button>
          <span className="card-sub">
            {page} / {Math.ceil(data.total / 20)}
          </span>
          <Button
            size="sm"
            disabled={page >= Math.ceil(data.total / 20)}
            onClick={() => setPage((p) => p + 1)}
          >
            →
          </Button>
        </div>
      ) : null}

      <Sheet
        open={Boolean(detail)}
        title={detail?.user.username ? `@${detail.user.username}` : t("admin.tabs.users")}
        onClose={() => setDetail(null)}
      >
        {detail ? (
          <div className="list">
            <div className="card">
              <div className="card-sub">{t("admin.users.wallet")}</div>
              <div className="mono">{detail.user.wallet_address ?? "—"}</div>
              <div className="card-sub" style={{ marginTop: 8 }}>
                {t("admin.users.registered")}: {new Date(detail.user.created_at).toLocaleDateString()}
              </div>
            </div>

            <Button variant="primary" block onClick={() => setGranting(true)}>
              {t("admin.users.grant")}
            </Button>

            <div className="field-label">{t("subscriptions.title")}</div>
            {detail.subscriptions.length === 0 ? (
              <div className="card-sub">{t("subscriptions.empty")}</div>
            ) : null}
            {detail.subscriptions.map((sub) => (
              <div key={sub.id} className="card">
                <div className="card-row">
                  <div className="grow">
                    <div className="card-title">{sub.tariff?.name ?? t("subscriptions.trial")}</div>
                    <div className="card-sub">
                      {sub.is_forever
                        ? t("subscriptions.forever")
                        : sub.expires_at
                          ? new Date(sub.expires_at).toLocaleDateString()
                          : "—"}
                    </div>
                  </div>
                  <Badge kind={sub.status === "expired" ? "danger" : "success"}>
                    {t(`subscriptions.status.${sub.status}`)}
                  </Badge>
                </div>
                {sub.status !== "expired" ? (
                  <div style={{ marginTop: 8 }}>
                    <Button size="sm" variant="danger" onClick={() => void revoke(sub.id)}>
                      {t("admin.users.revoke")}
                    </Button>
                  </div>
                ) : null}
              </div>
            ))}

            <div className="field-label">{t("admin.users.payments")}</div>
            {detail.payments.length === 0 ? (
              <div className="card-sub">{t("admin.users.noPayments")}</div>
            ) : null}
            {detail.payments.map((payment) => (
              <div key={payment.id} className="card">
                <div className="card-row">
                  <div className="grow">
                    <div className="card-title">{payment.amount} TON</div>
                    <div className="card-sub">
                      {payment.purpose} · {new Date(payment.created_at).toLocaleDateString()}
                    </div>
                  </div>
                  <Badge kind={payment.status === "confirmed" ? "success" : "warning"}>
                    {payment.status}
                  </Badge>
                </div>
              </div>
            ))}
          </div>
        ) : null}
      </Sheet>

      <Sheet open={granting} title={t("admin.grant.title")} onClose={() => setGranting(false)}>
        <div className="list">
          <Field label={t("admin.grant.tariff")}>
            <Select
              value={grantForm.tariff_id}
              onChange={(value) => setGrantForm((f) => ({ ...f, tariff_id: value }))}
              options={[
                { value: "", label: t("admin.grant.manual") },
                ...tariffs.map((tariff) => ({
                  value: tariff.id,
                  label: `${tariff.name} · ${tariff.sites_limit}`,
                })),
              ]}
            />
          </Field>

          {!grantForm.tariff_id ? (
            <Field label={t("admin.grant.sitesLimit")}>
              <Input
                value={grantForm.sites_limit}
                onChange={(value) => setGrantForm((f) => ({ ...f, sites_limit: value }))}
                inputMode="numeric"
              />
            </Field>
          ) : null}

          <Field label={t("admin.grant.duration")}>
            <Select
              value={grantForm.duration}
              onChange={(value) => setGrantForm((f) => ({ ...f, duration: value }))}
              options={DURATIONS.map((duration) => ({
                value: duration,
                label: t(`tariffs.duration.${duration}`),
              }))}
            />
          </Field>

          <Field label={t("admin.grant.comment")}>
            <Input
              value={grantForm.comment}
              onChange={(value) => setGrantForm((f) => ({ ...f, comment: value }))}
            />
          </Field>

          <Button variant="primary" block onClick={() => void grant()}>
            {t("admin.grant.submit")}
          </Button>
        </div>
      </Sheet>
    </>
  );
}

function TariffsTab() {
  const { t } = useTranslation();
  const toast = useAppStore((s) => s.toast);
  const toastError = useAppStore((s) => s.toastError);

  const [tariffs, setTariffs] = useState<Tariff[] | null>(null);
  const [editing, setEditing] = useState<Partial<Tariff> | null>(null);

  const load = useCallback(async () => {
    try {
      setTariffs(await adminApi.tariffs());
    } catch (error) {
      toastError(error);
    }
  }, [toastError]);

  useEffect(() => {
    void load();
  }, [load]);

  async function save(): Promise<void> {
    if (!editing) return;
    try {
      if (editing.id) {
        await adminApi.updateTariff(editing.id, {
          name: editing.name,
          description: editing.description,
          sites_limit: editing.sites_limit,
          duration: editing.duration,
          price_ton: editing.price_ton,
          kind: editing.kind,
          is_active: editing.is_active,
        });
      } else {
        await adminApi.createTariff({
          name: editing.name ?? "",
          description: editing.description ?? undefined,
          sites_limit: Number(editing.sites_limit ?? 1),
          duration: (editing.duration ?? "month") as TariffDuration,
          price_ton: String(editing.price_ton ?? "0"),
          kind: (editing.kind ?? "base") as TariffKind,
          is_active: editing.is_active ?? true,
        });
      }
      toast(t("admin.tariffs.saved"), "success");
      setEditing(null);
      await load();
    } catch (error) {
      toastError(error);
    }
  }

  async function remove(tariff: Tariff): Promise<void> {
    const confirmed = await showConfirm(t("admin.tariffs.deleteConfirm", { name: tariff.name }));
    if (!confirmed) return;
    try {
      await adminApi.deleteTariff(tariff.id);
      await load();
    } catch (error) {
      toastError(error);
    }
  }

  if (!tariffs) return <Skeletons />;

  return (
    <>
      <Button
        variant="primary"
        block
        onClick={() =>
          setEditing({ name: "", sites_limit: 1, duration: "month", price_ton: "1", kind: "base", is_active: true })
        }
      >
        + {t("admin.tariffs.create")}
      </Button>

      <div className="list">
        {tariffs.map((tariff) => (
          <div key={tariff.id} className="card">
            <div className="card-row">
              <div className="grow">
                <div className="card-title">{tariff.name}</div>
                <div className="card-sub">
                  {tariff.price_ton} TON · {t(`tariffs.duration.${tariff.duration}`)} ·{" "}
                  {tariff.sites_limit}
                </div>
              </div>
              <Badge kind={tariff.is_active ? "success" : "default"}>
                {tariff.is_active ? t("admin.tariffs.active") : t("admin.tariffs.inactive")}
              </Badge>
            </div>
            <div className="row" style={{ marginTop: 8 }}>
              <Button size="sm" onClick={() => setEditing(tariff)}>
                {t("common.edit")}
              </Button>
              <Button size="sm" variant="danger" onClick={() => void remove(tariff)}>
                {t("common.delete")}
              </Button>
            </div>
          </div>
        ))}
      </div>

      <Sheet
        open={Boolean(editing)}
        title={editing?.id ? t("common.edit") : t("admin.tariffs.create")}
        onClose={() => setEditing(null)}
      >
        {editing ? (
          <div className="list">
            <Field label={t("admin.tariffs.name")}>
              <Input
                value={editing.name ?? ""}
                onChange={(value) => setEditing({ ...editing, name: value })}
              />
            </Field>
            <Field label={t("admin.tariffs.description")}>
              <Input
                value={editing.description ?? ""}
                onChange={(value) => setEditing({ ...editing, description: value })}
              />
            </Field>
            <Field label={t("admin.tariffs.price")}>
              <Input
                value={String(editing.price_ton ?? "")}
                onChange={(value) => setEditing({ ...editing, price_ton: value })}
                inputMode="decimal"
              />
            </Field>
            <Field label={t("admin.tariffs.sitesLimit")}>
              <Input
                value={String(editing.sites_limit ?? "")}
                onChange={(value) => setEditing({ ...editing, sites_limit: Number(value) || 1 })}
                inputMode="numeric"
              />
            </Field>
            <Field label={t("admin.tariffs.duration")}>
              <Select
                value={(editing.duration ?? "month") as TariffDuration}
                onChange={(value) => setEditing({ ...editing, duration: value })}
                options={DURATIONS.map((duration) => ({
                  value: duration,
                  label: t(`tariffs.duration.${duration}`),
                }))}
              />
            </Field>
            <Field label={t("admin.tariffs.kind")}>
              <Select
                value={(editing.kind ?? "base") as TariffKind}
                onChange={(value) => setEditing({ ...editing, kind: value })}
                options={KINDS.map((kind) => ({ value: kind, label: kind }))}
              />
            </Field>
            <Field label={t("admin.tariffs.active")}>
              <Select
                value={editing.is_active === false ? "0" : "1"}
                onChange={(value) => setEditing({ ...editing, is_active: value === "1" })}
                options={[
                  { value: "1", label: t("admin.tariffs.active") },
                  { value: "0", label: t("admin.tariffs.inactive") },
                ]}
              />
            </Field>

            <Button variant="primary" block onClick={() => void save()}>
              {t("common.save")}
            </Button>
          </div>
        ) : null}
      </Sheet>
    </>
  );
}

function DomainsTab() {
  const { t } = useTranslation();
  const toastError = useAppStore((s) => s.toastError);
  const [domains, setDomains] = useState<AdminDomainItem[] | null>(null);

  useEffect(() => {
    adminApi.domains().then(setDomains).catch(toastError);
  }, [toastError]);

  if (!domains) return <Skeletons />;
  if (!domains.length) return <Empty icon="🌐" title={t("admin.domains.empty")} />;

  return (
    <div className="list">
      {domains.map((item) => (
        <div key={item.site_id} className="card">
          <div className="card-row">
            <div className="grow">
              <div className="card-title">{item.domain}</div>
              <div className="card-sub">
                {item.site_title} · {t("admin.domains.owner")}: id {item.telegram_id}
              </div>
            </div>
            <Badge kind={item.status === "published" ? "success" : "default"}>
              {t(`sites.status.${item.status}`)}
            </Badge>
          </div>
        </div>
      ))}
    </div>
  );
}
