/** Небольшой UI-кит: всё, что переиспользуется между экранами. */
import type { ChangeEvent, ReactNode } from "react";
import { useEffect } from "react";
import { useAppStore } from "../store/app";
import { haptic } from "../telegram/webapp";

export function Spinner({ large = false }: { large?: boolean }) {
  return <div className={large ? "spinner spinner-lg" : "spinner"} aria-label="loading" />;
}

export function Loading({ text }: { text?: string }) {
  return (
    <div className="center">
      <Spinner large />
      {text ? <span>{text}</span> : null}
    </div>
  );
}

/**
 * Шапка экрана со стрелкой «назад».
 *
 * Одной кнопки Telegram недостаточно: на Android аппаратная «назад» просто
 * перезапускает Mini App, поэтому выход с вложенного экрана должен быть виден
 * прямо на странице.
 */
export function PageHead({
  title,
  subtitle,
  onBack,
  extra,
}: {
  title: string;
  subtitle?: string;
  onBack?: () => void;
  extra?: ReactNode;
}) {
  return (
    <div className="page-header">
      {onBack ? (
        <button
          type="button"
          className="back-btn"
          aria-label="←"
          onClick={() => {
            haptic.light();
            onBack();
          }}
        >
          ←
        </button>
      ) : null}
      <div className="grow" style={{ minWidth: 0 }}>
        <h1>{title}</h1>
        {subtitle ? <div className="page-subtitle ellipsis">{subtitle}</div> : null}
      </div>
      {extra}
    </div>
  );
}

/** Экран не смог загрузиться: вместо вечного спиннера — причина и выход. */
export function LoadFailed({
  title,
  hint,
  onRetry,
  retryLabel,
  onBack,
  backLabel,
}: {
  title: string;
  hint?: string;
  onRetry?: () => void;
  retryLabel?: string;
  onBack?: () => void;
  backLabel?: string;
}) {
  return (
    <div className="page">
      <Empty
        icon="🚧"
        title={title}
        hint={hint}
        action={
          <div className="row" style={{ marginTop: 4 }}>
            {onRetry ? (
              <Button size="sm" onClick={onRetry}>
                {retryLabel}
              </Button>
            ) : null}
            {onBack ? (
              <Button size="sm" variant="primary" onClick={onBack}>
                {backLabel}
              </Button>
            ) : null}
          </div>
        }
      />
    </div>
  );
}

export function Skeletons({ count = 3 }: { count?: number }) {
  return (
    <div className="list">
      {Array.from({ length: count }, (_, i) => (
        <div key={i} className="skeleton" />
      ))}
    </div>
  );
}

export function Empty({
  icon = "✨",
  title,
  hint,
  action,
}: {
  icon?: ReactNode;
  title: string;
  hint?: string;
  action?: ReactNode;
}) {
  return (
    <div className="empty">
      <div className="empty-icon">{icon}</div>
      <div className="card-title">{title}</div>
      {hint ? <div className="card-sub">{hint}</div> : null}
      {action}
    </div>
  );
}

interface ButtonProps {
  children: ReactNode;
  onClick?: () => void;
  variant?: "primary" | "default" | "danger" | "ghost";
  size?: "md" | "sm";
  block?: boolean;
  disabled?: boolean;
  loading?: boolean;
  type?: "button" | "submit";
  title?: string;
}

export function Button({
  children,
  onClick,
  variant = "default",
  size = "md",
  block,
  disabled,
  loading,
  type = "button",
  title,
}: ButtonProps) {
  const classes = [
    "btn",
    variant === "primary" ? "btn-primary" : "",
    variant === "danger" ? "btn-danger" : "",
    variant === "ghost" ? "btn-ghost" : "",
    size === "sm" ? "btn-sm" : "",
    block ? "btn-block" : "",
  ]
    .filter(Boolean)
    .join(" ");

  return (
    <button
      type={type}
      className={classes}
      title={title}
      disabled={disabled || loading}
      onClick={() => {
        haptic.light();
        onClick?.();
      }}
    >
      {loading ? <Spinner /> : null}
      {children}
    </button>
  );
}

export function Field({
  label,
  hint,
  error,
  children,
}: {
  label?: string;
  hint?: string;
  error?: string;
  children: ReactNode;
}) {
  return (
    <div className="field">
      {label ? <label className="field-label">{label}</label> : null}
      {children}
      {error ? <span className="field-error">{error}</span> : null}
      {hint && !error ? <span className="field-hint">{hint}</span> : null}
    </div>
  );
}

export function Input({
  value,
  onChange,
  placeholder,
  type = "text",
  invalid,
  autoFocus,
  inputMode,
}: {
  value: string;
  onChange: (value: string) => void;
  placeholder?: string;
  type?: string;
  invalid?: boolean;
  autoFocus?: boolean;
  inputMode?: "text" | "numeric" | "decimal" | "url";
}) {
  return (
    <input
      className={invalid ? "input input-error" : "input"}
      value={value}
      type={type}
      inputMode={inputMode}
      placeholder={placeholder}
      autoFocus={autoFocus}
      onChange={(e: ChangeEvent<HTMLInputElement>) => onChange(e.target.value)}
    />
  );
}

export function Textarea({
  value,
  onChange,
  placeholder,
  rows,
}: {
  value: string;
  onChange: (value: string) => void;
  placeholder?: string;
  rows?: number;
}) {
  return (
    <textarea
      className="textarea"
      value={value}
      rows={rows}
      placeholder={placeholder}
      onChange={(e: ChangeEvent<HTMLTextAreaElement>) => onChange(e.target.value)}
    />
  );
}

export function Select<T extends string>({
  value,
  onChange,
  options,
}: {
  value: T;
  onChange: (value: T) => void;
  options: { value: T; label: string }[];
}) {
  return (
    <select className="select" value={value} onChange={(e) => onChange(e.target.value as T)}>
      {options.map((option) => (
        <option key={option.value} value={option.value}>
          {option.label}
        </option>
      ))}
    </select>
  );
}

export function Segmented<T extends string>({
  value,
  onChange,
  options,
}: {
  value: T;
  onChange: (value: T) => void;
  options: { value: T; label: string }[];
}) {
  return (
    <div className="segmented">
      {options.map((option) => (
        <button
          key={option.value}
          className={option.value === value ? "active" : ""}
          onClick={() => {
            haptic.selection();
            onChange(option.value);
          }}
        >
          {option.label}
        </button>
      ))}
    </div>
  );
}

export function Sheet({
  open,
  title,
  onClose,
  children,
}: {
  open: boolean;
  title?: string;
  onClose: () => void;
  children: ReactNode;
}) {
  useEffect(() => {
    if (!open) return;
    const handler = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [open, onClose]);

  if (!open) return null;
  return (
    <div className="sheet-backdrop" onClick={onClose}>
      <div className="sheet" onClick={(e) => e.stopPropagation()}>
        <div className="sheet-handle" />
        {title ? <div className="sheet-title">{title}</div> : null}
        {children}
      </div>
    </div>
  );
}

export function Badge({
  children,
  kind = "default",
}: {
  children: ReactNode;
  kind?: "default" | "success" | "warning" | "danger" | "accent";
}) {
  return <span className={kind === "default" ? "badge" : `badge badge-${kind}`}>{children}</span>;
}

export function Notice({
  children,
  kind = "info",
}: {
  children: ReactNode;
  kind?: "info" | "warning" | "danger";
}) {
  const cls = kind === "info" ? "notice" : `notice notice-${kind}`;
  return (
    <div className={cls}>
      <span>{kind === "danger" ? "⚠️" : kind === "warning" ? "⏳" : "ℹ️"}</span>
      <div>{children}</div>
    </div>
  );
}

export function Toasts() {
  const toasts = useAppStore((s) => s.toasts);
  const dismiss = useAppStore((s) => s.dismissToast);
  if (!toasts.length) return null;
  return (
    <div className="toasts">
      {toasts.map((toast) => (
        <div
          key={toast.id}
          className={`toast toast-${toast.kind}`}
          style={{ pointerEvents: "auto" }}
          onClick={() => dismiss(toast.id)}
        >
          {toast.text}
        </div>
      ))}
    </div>
  );
}
