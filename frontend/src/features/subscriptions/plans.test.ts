import { describe, expect, it } from "vitest";
import type { Tariff, TariffDuration } from "../../api/types";
import { availableDurations, discountPercent, groupPlans } from "./plans";

function tariff(
  name: string,
  duration: TariffDuration,
  price: string,
  sites = 5,
): Tariff {
  return {
    id: `${name}-${duration}`,
    name,
    description: `${name} desc`,
    sites_limit: sites,
    duration,
    price_ton: price,
    kind: "pro",
    is_active: true,
  };
}

const GRID: Tariff[] = [
  tariff("Basic", "month", "2", 1),
  tariff("Basic", "3month", "5", 1),
  tariff("Basic", "12month", "17", 1),
  tariff("Pro", "month", "7"),
  tariff("Pro", "6month", "35"),
  tariff("Pro", "12month", "60"),
  tariff("Business", "month", "25", 25),
];

describe("группировка тарифов", () => {
  it("схлопывает сроки одного тарифа в одну карточку", () => {
    const plans = groupPlans(GRID);
    expect(plans.map((p) => p.name)).toEqual(["Basic", "Pro", "Business"]);
    expect(Object.keys(plans[1].options).sort()).toEqual(["12month", "6month", "month"]);
  });

  it("сортирует тарифы по лимиту сайтов, а не по цене", () => {
    expect(groupPlans([...GRID].reverse()).map((p) => p.sites_limit)).toEqual([1, 5, 25]);
  });

  it("в переключателе только сроки, которые реально есть", () => {
    expect(availableDurations(groupPlans(GRID))).toEqual(["month", "3month", "6month", "12month"]);
  });

  it("считает скидку длинного срока относительно месячной цены", () => {
    const [, pro] = groupPlans(GRID);
    expect(discountPercent(pro, "12month")).toBe(29); // 60 вместо 84
    expect(discountPercent(pro, "6month")).toBe(17); // 35 вместо 42
    expect(discountPercent(pro, "month")).toBe(0);
  });

  it("не показывает скидку для «навсегда» — сравнивать не с чем", () => {
    const plans = groupPlans([...GRID, tariff("Pro", "forever", "175")]);
    expect(discountPercent(plans[1], "forever")).toBe(0);
  });

  it("не падает, если у тарифа нет помесячной оплаты", () => {
    const plans = groupPlans([tariff("Max", "12month", "500", 100)]);
    expect(discountPercent(plans[0], "12month")).toBe(0);
    expect(plans[0].options.month).toBeUndefined();
  });
});
