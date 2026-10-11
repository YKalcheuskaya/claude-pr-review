/** Return the numeric invoice summary consumed by the view. */
export function invoiceSummary(subtotal, tax) {
  const total = subtotal + tax;
  return { total };
}
