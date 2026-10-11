/** Return the numeric invoice summary consumed by the view. */
export function invoiceSummary(subtotal, tax) {
  return { total: subtotal + tax };
}
