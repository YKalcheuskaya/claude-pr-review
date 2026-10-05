"""Small demonstration target; no requests, sleeping or retry execution."""


def should_retry(status: int, completed: int, maximum: int) -> bool:
    """Completed includes the failed request; never exceed maximum attempts."""
    if any(type(value) is not int for value in (status, completed, maximum)):
        raise ValueError("integer inputs required")
    if not 100 <= status <= 599 or completed < 1 or maximum < 1:
        raise ValueError("invalid status or attempt count")
    return (status == 429 or 500 <= status <= 599) and completed < maximum
