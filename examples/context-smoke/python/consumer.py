"""Render the summary contract as an invoice label."""
from producer import invoice_summary


def invoice_label(subtotal, tax):
    summary = invoice_summary(subtotal, tax)
    return f"Invoice total: ${summary['total']:.2f}"
