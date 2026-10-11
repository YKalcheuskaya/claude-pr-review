import { invoiceSummary } from './producer.mjs';

export function invoiceLabel(subtotal, tax) {
  const summary = invoiceSummary(subtotal, tax);
  return `Invoice total: $${summary.total.toFixed(2)}`;
}
