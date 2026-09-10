/** Манифест TON Connect: кошелёк должен получить абсолютный адрес. */
import { describe, expect, it } from "vitest";
import { resolveManifestUrl } from "./tonconnect";

const ORIGIN = "https://app.example.com";

describe("resolveManifestUrl", () => {
  it("достраивает относительный путь до полного адреса", () => {
    // именно это значение стоит в .env.example и в инструкции
    expect(resolveManifestUrl("/tonconnect-manifest.json", ORIGIN)).toBe(
      "https://app.example.com/tonconnect-manifest.json",
    );
  });

  it("оставляет полный адрес без изменений", () => {
    expect(resolveManifestUrl("https://cdn.example.org/manifest.json", ORIGIN)).toBe(
      "https://cdn.example.org/manifest.json",
    );
  });

  it("без значения берёт манифест с домена приложения", () => {
    expect(resolveManifestUrl(undefined, ORIGIN)).toBe(
      "https://app.example.com/tonconnect-manifest.json",
    );
    expect(resolveManifestUrl("  ", ORIGIN)).toBe(
      "https://app.example.com/tonconnect-manifest.json",
    );
  });
});
