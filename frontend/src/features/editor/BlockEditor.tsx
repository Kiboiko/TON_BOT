/**
 * B2. Редактор одного блока: поля строятся по описанию из каталога,
 * списки (ссылки, кнопки, работы) поддерживают произвольное число элементов.
 */
import { useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { uploadsApi } from "../../api/endpoints";
import type { Block } from "../../api/types";
import { Button, Field, Input, Select, Textarea } from "../../components/ui";
import { useAppStore } from "../../store/app";
import { BLOCK_SPECS, type FieldSpec } from "../../templates/catalog";
import { haptic } from "../../telegram/webapp";

type Lang = "ru" | "en";

function FieldInput({
  spec,
  value,
  onChange,
  lang,
}: {
  spec: FieldSpec;
  value: unknown;
  onChange: (value: string) => void;
  lang: Lang;
}) {
  const stringValue = typeof value === "string" ? value : "";
  const label = spec.label[lang];

  if (spec.kind === "textarea") {
    return (
      <Field label={label}>
        <Textarea value={stringValue} onChange={onChange} placeholder={spec.placeholder} />
      </Field>
    );
  }
  if (spec.kind === "select") {
    return (
      <Field label={label}>
        <Select
          value={stringValue || (spec.options?.[0]?.value ?? "")}
          onChange={onChange}
          options={spec.options ?? []}
        />
      </Field>
    );
  }
  if (spec.kind === "image") {
    return (
      <Field label={label} hint={stringValue ? undefined : "https://…"}>
        <Input value={stringValue} onChange={onChange} placeholder="https://…" inputMode="url" />
        <ImageUpload onUploaded={onChange} />
        {stringValue ? (
          <img
            src={stringValue}
            alt=""
            style={{
              marginTop: 8,
              width: "100%",
              maxHeight: 160,
              objectFit: "cover",
              borderRadius: 12,
            }}
            onError={(e) => {
              (e.currentTarget as HTMLImageElement).style.display = "none";
            }}
          />
        ) : null}
      </Field>
    );
  }
  return (
    <Field label={label}>
      <Input
        value={stringValue}
        onChange={onChange}
        placeholder={spec.placeholder}
        inputMode={spec.kind === "url" ? "url" : "text"}
      />
    </Field>
  );
}

/** Загрузка картинки с устройства: ссылка подставляется в поле блока. */
export function ImageUpload({ onUploaded }: { onUploaded: (url: string) => void }) {
  const { t } = useTranslation();
  const inputRef = useRef<HTMLInputElement>(null);
  const [busy, setBusy] = useState(false);
  const toastError = useAppStore((s) => s.toastError);

  async function pick(file: File | undefined): Promise<void> {
    if (!file) return;
    setBusy(true);
    try {
      const { url } = await uploadsApi.image(file);
      onUploaded(url);
    } catch (error) {
      toastError(error);
    } finally {
      setBusy(false);
      if (inputRef.current) inputRef.current.value = "";
    }
  }

  return (
    <div style={{ marginTop: 6 }}>
      <input
        ref={inputRef}
        type="file"
        accept="image/png,image/jpeg,image/gif,image/webp"
        style={{ display: "none" }}
        onChange={(e) => void pick(e.target.files?.[0])}
      />
      <Button size="sm" loading={busy} onClick={() => inputRef.current?.click()}>
        📷 {t("editor.uploadImage")}
      </Button>
    </div>
  );
}

export function BlockEditor({
  block,
  onChange,
}: {
  block: Block;
  onChange: (props: Record<string, unknown>) => void;
}) {
  const { t, i18n } = useTranslation();
  const lang: Lang = i18n.language.startsWith("en") ? "en" : "ru";
  const spec = BLOCK_SPECS[block.type];
  if (!spec) return null;

  const props = block.props ?? {};
  const items = Array.isArray(props.items) ? (props.items as Record<string, unknown>[]) : [];

  const setItems = (next: Record<string, unknown>[]) => onChange({ items: next });

  return (
    <div className="list">
      {spec.fields.map((field) => (
        <FieldInput
          key={field.key}
          spec={field}
          lang={lang}
          value={props[field.key]}
          onChange={(value) => onChange({ [field.key]: value })}
        />
      ))}

      {spec.itemFields ? (
        <>
          {items.length ? <div className="field-label">{t("editor.items")}</div> : null}

          {items.map((item, index) => (
            <div className="item-card" key={index}>
              <div className="row-between">
                <b style={{ fontSize: 13 }}>
                  {t("editor.itemNumber", {
                    label: spec.itemLabel?.[lang] ?? "",
                    number: index + 1,
                  })}
                </b>
                <div className="row">
                  <Button
                    size="sm"
                    disabled={index === 0}
                    onClick={() => {
                      const next = [...items];
                      [next[index - 1], next[index]] = [next[index], next[index - 1]];
                      setItems(next);
                    }}
                  >
                    ↑
                  </Button>
                  <Button
                    size="sm"
                    disabled={index === items.length - 1}
                    onClick={() => {
                      const next = [...items];
                      [next[index + 1], next[index]] = [next[index], next[index + 1]];
                      setItems(next);
                    }}
                  >
                    ↓
                  </Button>
                  <Button
                    size="sm"
                    variant="danger"
                    onClick={() => setItems(items.filter((_, i) => i !== index))}
                  >
                    ✕
                  </Button>
                </div>
              </div>

              {spec.itemFields?.map((field) => (
                <FieldInput
                  key={field.key}
                  spec={field}
                  lang={lang}
                  value={item[field.key]}
                  onChange={(value) =>
                    setItems(items.map((it, i) => (i === index ? { ...it, [field.key]: value } : it)))
                  }
                />
              ))}
            </div>
          ))}

          <Button
            block
            onClick={() => {
              haptic.light();
              setItems([...items, {}]);
            }}
          >
            + {t("editor.addItem", { label: spec.itemLabel?.[lang] ?? "" })}
          </Button>
        </>
      ) : null}
    </div>
  );
}
