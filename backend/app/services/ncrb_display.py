"""Display labels for NCRB crime heads (step 15b).

``ncrb_stats.offense_category`` keeps every crime head exactly as NCRB printed
it. A display label differs only for an evident printing error, and is used
for UI display only; the API returns the raw head next to it. Every override,
with its evidence, is listed in docs/analytics/NCRB_CORRECTION.md.
"""

from __future__ import annotations

# raw printed head -> display label
DISPLAY_OVERRIDES: dict[str, str] = {
    # PDF page 95 (table page 48). The State/UT-wise table was built from the City-wise one by replacing
    # "City" with "State/UT", including inside "Electricity". The City-wise Table 1A.4 in the same volume
    # (PDF page 207) prints "n) ElectriCity/Power Supply Disputes", the 2023 edition prints "Electricity/Power
    # Supply Disputes", and "ElectriState/UT" appears on no other page of the 604-page volume.
    "Rioting - n) ElectriState/UT/Power Supply Disputes": "Rioting - n) Electricity/Power Supply Disputes",
}


def display_offense_category(offense_category: str) -> str:
    return DISPLAY_OVERRIDES.get(offense_category, offense_category)
