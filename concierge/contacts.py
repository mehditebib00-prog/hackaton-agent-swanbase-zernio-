"""Extract real contact details (email, URL, @handle, phone) from free text."""

import re

EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
URL = re.compile(r"(?:https?://|www\.)[^\s<>\"']+|\b(?:linkedin\.com|lnkd\.in|github\.com|x\.com|twitter\.com)/[^\s<>\"']+", re.I)
HANDLE = re.compile(r"(?<![\w.])@[A-Za-z0-9_.]{2,30}\b")
PHONE = re.compile(r"\+?\d[\d\s().-]{7,}\d")


def extract(text: str) -> list[str]:
    """Return contact items found in `text`, in order, without duplicates."""
    text = text or ""
    found: list[str] = []
    emails = EMAIL.findall(text)
    for pattern in (EMAIL, URL, HANDLE, PHONE):
        for m in pattern.findall(text):
            item = m.rstrip(".,;:!?)")
            # an @handle inside an email address is not a separate handle
            if pattern is HANDLE and any(item in e for e in emails):
                continue
            if item not in found:
                found.append(item)
    return found


def is_valid(contact: str | None) -> bool:
    return bool(contact) and bool(extract(contact or ""))
