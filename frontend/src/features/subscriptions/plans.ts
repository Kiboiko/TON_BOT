/**
 * Группировка витрины: тарифы с одинаковым названием — это один тариф
 * с разными сроками оплаты. Срок выбирается переключателем, поэтому в списке
 * остаются только сами тарифы, а не все их комбинации со сроками.
 */
import type { Tariff, TariffDuration, TariffKind } from "../../api/types";

/** Порядок сроков из ТЗ: 1, 3, 6, 12 месяцев и навсегда. */
export const DURATION_ORDER: TariffDuration[] = [
  "month",
  "3month",
  "6month",
  "12month",
  "forever",
];

export const DURATION_MONTHS: Partial<Record<TariffDuration, number>> = {
  month: 1,
  "3month": 3,
  "6month": 6,
  "12month": 12,
};

export interface Plan {
  name: string;
  description: string | null;
  sites_limit: number;
  kind: TariffKind;
  options: Partial<Record<TariffDuration, Tariff>>;
}

export function groupPlans(tariffs: Tariff[]): Plan[] {
  const plans = new Map<string, Plan>();
  for (const tariff of tariffs) {
    let plan = plans.get(tariff.name);
    if (!plan) {
      plan = {
        name: tariff.name,
        description: tariff.description,
        sites_limit: tariff.sites_limit,
        kind: tariff.kind,
        options: {},
      };
      plans.set(tariff.name, plan);
    }
    plan.options[tariff.duration] = tariff;
    plan.sites_limit = Math.max(plan.sites_limit, tariff.sites_limit);
    if (!plan.description) plan.description = tariff.description;
  }
  return [...plans.values()].sort((a, b) => a.sites_limit - b.sites_limit);
}

/** Сроки, которые реально есть хотя бы у одного тарифа — под переключатель. */
export function availableDurations(plans: Plan[]): TariffDuration[] {
  return DURATION_ORDER.filter((duration) => plans.some((plan) => plan.options[duration]));
}

/** Скидка длинного срока относительно помесячной оплаты, в процентах. */
export function discountPercent(plan: Plan, duration: TariffDuration): number {
  const months = DURATION_MONTHS[duration];
  const monthly = plan.options.month;
  const option = plan.options[duration];
  if (!months || months < 2 || !monthly || !option) return 0;
  const full = Number(monthly.price_ton) * months;
  if (!full) return 0;
  return Math.round((1 - Number(option.price_ton) / full) * 100);
}
