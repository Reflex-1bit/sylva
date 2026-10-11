"""Remove contact details (email addresses, mailto links, corresponding-author clauses) from harvested free text."""

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from app.models.catalogue import EMAIL_RE, MAILTO_RE, OBFUSCATED_EMAIL_RE  # noqa: E402

# "Correspondence to: ...", "Corresponding author(s): ...", "*Corresponding author ..." up to the
# end of that sentence or the end of the line. A sentence ends at a full stop that follows two
# lower-case letters, digits or a closing bracket and precedes white space, so initials such as
# "Dr A. Smith" do not end it.
CORRESPONDENCE_RE = re.compile(
    r"\*?[ \t]*\b(?:correspondence[ \t]+to|corresponding[ \t]+author(?:s|\(s\))?)\b[^\n]*?"
    r"(?:(?<=[a-z0-9)\]]{2})\.(?=\s)|$)",
    re.I | re.M,
)
# Placeholder left by e-mail obfuscation on harvested web pages.
EMAIL_PLACEHOLDER_RE = re.compile(r"\[\s*email[ \t]+protected\s*\]", re.I)


def scrub_contacts(text: str) -> str:
    """Delete corresponding-author clauses, mailto links, plain and obfuscated emails and placeholders."""
    for rx in (CORRESPONDENCE_RE, MAILTO_RE, EMAIL_RE, OBFUSCATED_EMAIL_RE, EMAIL_PLACEHOLDER_RE):
        text = rx.sub("", text)
    text = re.sub(r"\(\s*\)|\[\s*\]", "", text)  # brackets left empty by the removal
    text = re.sub(r"\s+([.,;:])", r"\1", text)
    text = re.sub(r"[ \t]{2,}", " ", text)
    return text.strip()
