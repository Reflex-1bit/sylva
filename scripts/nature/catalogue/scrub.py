"""Remove contact details (email addresses, mailto links) from harvested free text."""

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from app.models.catalogue import EMAIL_RE, MAILTO_RE, OBFUSCATED_EMAIL_RE  # noqa: E402


def scrub_contacts(text: str) -> str:
    """Delete mailto links, plain emails and obfuscated 'name [at] domain [dot] org' forms."""
    for rx in (MAILTO_RE, EMAIL_RE, OBFUSCATED_EMAIL_RE):
        text = rx.sub("", text)
    text = re.sub(r"\(\s*\)|\[\s*\]", "", text)  # brackets left empty by the removal
    text = re.sub(r"\s+([.,;:])", r"\1", text)
    text = re.sub(r"[ \t]{2,}", " ", text)
    return text.strip()
