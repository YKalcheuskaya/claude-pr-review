"""Small invoice-summary producer for the context-review demonstration."""


def invoice_summary(subtotal, tax):
    amount = subtotal + tax
    return {"total": amount}
