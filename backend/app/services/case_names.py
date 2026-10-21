"""Case-name normalization for the answer model and citation validation.

Indian Kanoon case titles end with the decision date, for example
"Sri Tanay Das vs The State Of Tripura on 2 May, 2022". Models tend to drop
that suffix when they copy a case name into a citation, and the frozen
citation validator requires an exact match (step 11 live run P1). Prompt v2
and its validation therefore see the name without the suffix.

Rule: a trailing ``" on <day> <Month>, <year>"`` (day 1-2 digits, full or
three-letter English month name, optional comma, 4-digit year), at the very
end of the name, is removed. Nothing else changes, so a name without that
exact suffix is returned unchanged. Stored metadata is never modified; the UI
keeps showing the full title.
"""

from __future__ import annotations

import re
from typing import Any

_MONTHS = (
    "January|February|March|April|May|June|July|August|September|October|November|December"
    "|Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec"
)
DATE_SUFFIX = re.compile(rf"\s+on\s+\d{{1,2}}\s+(?:{_MONTHS})\.?,?\s+\d{{4}}\s*$", re.IGNORECASE)


def strip_date_suffix(name: str | None) -> str | None:
    """The case name without a trailing "on <day> <Month>, <year>"; other names unchanged."""
    if not name:
        return name
    stripped = DATE_SUFFIX.sub("", name)
    return stripped if stripped.strip() else name


def normalized_for_generation(retrieval: Any) -> Any:
    """A copy of a LegalRetrievalResult whose evidence case names have no date suffix.

    Used only for the prompt and citation validation; the original retrieval
    (full titles) is kept for precedents and the UI.
    """
    if retrieval is None:
        return None
    evidence = [
        item.model_copy(
            update={
                "case_name": strip_date_suffix(item.case_name),
                "citation_metadata": item.citation_metadata.model_copy(
                    update={"case_name": strip_date_suffix(item.citation_metadata.case_name)}
                ),
            }
        )
        for item in retrieval.evidence
    ]
    return retrieval.model_copy(update={"evidence": evidence})
