/**
 * Официальный символ Toncoin (бренд-ассет из @tonconnect/ui) вместо эмодзи 💎.
 * Одна path с fill-rule=evenodd: круг с вырезанным ромбом, поэтому иконка
 * красится через currentColor и одинаково хорошо смотрится в обеих темах.
 */
const TON_PATH =
  "M28 14.001C28 21.733 21.732 28.001 14 28.001C6.26801 28.001 0 21.733 0 14.001C0 6.26899 " +
  "6.26801 0.000976562 14 0.000976562C21.732 0.000976562 28 6.26899 28 14.001ZM9.21931 " +
  "8.00098H18.7801H18.7813C20.538 8.00098 21.6522 9.89966 20.7691 11.4302L14.8672 " +
  "21.6576C14.4822 22.3254 13.5172 22.3254 13.1322 21.6576L7.23158 11.4302C6.34721 9.89726 " +
  "7.4614 8.00098 9.21931 8.00098ZM13.1262 18.5882V9.74806H9.21811C8.78976 9.74806 8.53708 " +
  "10.2029 8.74163 10.5578L11.8423 16.1035L13.1262 18.5882ZM16.1559 16.1047L19.2554 " +
  "10.5566C19.4599 10.2017 19.2073 9.74685 18.7789 9.74685H14.8709V18.5906L16.1559 16.1047Z";

export function TonIcon({ size = 16, className }: { size?: number; className?: string }) {
  return (
    <svg
      className={className}
      width={size}
      height={size}
      viewBox="0 0 28 28"
      fill="none"
      aria-hidden="true"
      focusable="false"
    >
      <path fillRule="evenodd" clipRule="evenodd" d={TON_PATH} fill="currentColor" />
    </svg>
  );
}

/** Цена: логотип TON + число. Текстовое «TON» больше не дублируем. */
export function TonAmount({
  value,
  size = 16,
  className,
}: {
  value: string | number;
  size?: number;
  className?: string;
}) {
  return (
    <span className={className ? `ton-amount ${className}` : "ton-amount"}>
      <TonIcon size={size} className="ton-amount-icon" />
      {value}
    </span>
  );
}
