"""Remove contact details (emails, mailto links, corresponding-author clauses, phone/fax numbers) from harvested free text."""

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
# "Tel: +90 232 352 40 40", "Tel. 0161-275", "Fax: 91-891-2790032", "Telephone (+34) 91 ..." : the label and
# the whole number run (digits, spaces, + ( ) . - /), ending on a digit. The clause ends with the number, so
# abstract text after a number that has no full stop ("Fax: 0161-275 4939 Manuscript received ...") is kept.
PHONE_RE = re.compile(
    r"\b(?:tel(?:ephone)?|phone|fax)\b\.?[ \t]*(?:no\.?|number)?[ \t]*:?[ \t]*\+?[ \t]*\(?\+?\d[\d \t().\-/]*\d",
    re.I,
)
# An "E-mail:" / "Email:" label whose address was removed (or was never there): the label is a stub.
# "IndiaEmail:" (glued to the previous word) counts; "voicemail:" does not.
EMAIL_STUB_RE = re.compile(r"\*?(?:(?<=[a-z])E|(?<![A-Za-z])[Ee])-?mail[ \t]*:[ \t]*[,;]?")


def scrub_contacts(text: str) -> str:
    """Delete corresponding-author clauses, mailto links, emails, placeholders, phone/fax numbers and stubs."""
    for rx in (CORRESPONDENCE_RE, MAILTO_RE, EMAIL_RE, OBFUSCATED_EMAIL_RE, EMAIL_PLACEHOLDER_RE, PHONE_RE,
               EMAIL_STUB_RE):
        text = rx.sub("", text)
    text = re.sub(r"(?:[ \t]+-){2,}(?=[ \t.]|$)", " -", text)  # "Turkey - - - ." left by the removal
    text = re.sub(r"[ \t]+-[ \t]*(?=\.)|[ \t]*[,;]+[ \t]*(?=\.)", "", text)
    text = re.sub(r"\(\s*\)|\[\s*\]", "", text)  # brackets left empty by the removal
    text = re.sub(r"\s+([.,;:])", r"\1", text)
    text = re.sub(r"[ \t]{2,}", " ", text)
    return text.strip()
