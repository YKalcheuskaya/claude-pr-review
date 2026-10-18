from .contract import summarize


def display_total(value):
    return summarize(value)["total"]
