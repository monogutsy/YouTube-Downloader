"""Display formatting shared by the desktop views."""

from datetime import datetime


def duration_text(seconds: float | None) -> str:
    if seconds is None:
        return ""
    hours, remainder = divmod(max(0, int(seconds)), 3600)
    minutes, seconds = divmod(remainder, 60)
    return f"{hours}:{minutes:02d}:{seconds:02d}" if hours else f"{minutes}:{seconds:02d}"


def size_text(size: float | None) -> str:
    if size is None:
        return ""
    value = float(size)
    for unit in ("B", "KiB", "MiB", "GiB"):
        if value < 1024 or unit == "GiB":
            return f"{value:,.0f} {unit}" if unit == "B" else f"{value:,.1f} {unit}"
        value /= 1024
    return ""


def one_line(value: str, limit: int) -> str:
    text = " ".join(value.split())
    return text if len(text) <= limit else f"{text[:limit - 1].rstrip()}…"


def history_time(date: str) -> str:
    try:
        return datetime.fromisoformat(date).astimezone().strftime("%b %d, %H:%M")
    except ValueError:
        return ""
