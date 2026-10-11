"""Small invoice-summary producer for the context-review demonstration."""


def invoice_summary(subtotal, tax):
    total = subtotal + tax
    return {"total": total}
