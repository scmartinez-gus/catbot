"""Discord webhook notification logic for new cat listings."""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import Any

import requests

from config import SOURCE_BRANDING

logger = logging.getLogger(__name__)

# Discord embed `fields[].value` max length; keep a margin.
_FIELD_VALUE_MAX: int = 1000


def _trunc_field(value: str) -> str:
    """Shorten a field `value` for Discord (max ~1024)."""
    t = re.sub(r"\s+", " ", (value or "").strip())
    if len(t) <= _FIELD_VALUE_MAX:
        return t
    return t[: _FIELD_VALUE_MAX - 1].rstrip() + "…"


def _author_for_source(source: str | None) -> dict[str, str] | None:
    """Build embed `author` (name, optional url, optional icon) from `SOURCE_BRANDING`."""
    if not source or source not in SOURCE_BRANDING:
        return None
    b = SOURCE_BRANDING[source]
    author: dict[str, str] = {"name": str(source)}
    u = b.get("author_url", "").strip()
    if u:
        author["url"] = u
    icon = b.get("icon_url", "").strip()
    if icon:
        author["icon_url"] = icon
    return author


def send_alert(webhook_url: str, listing: dict[str, Any]) -> None:
    """Send one Discord embed for a single cat listing."""
    priority = listing.get("is_target_breed")
    flag_label = "Yes" if priority is True else "No" if priority is False else "?"
    src = listing.get("source")
    desc_raw = (listing.get("description") or "").strip()
    loc_raw = (listing.get("location") or "").strip()
    org_raw = (listing.get("organization") or "").strip()

    fields: list[dict[str, Any]] = [
        {"name": "Age", "value": _trunc_field(str(listing.get("age", "Unknown"))), "inline": True},
        {
            "name": "Target breed (Siberian / Russian Blue / Balinese)",
            "value": flag_label,
            "inline": True,
        },
    ]
    if loc_raw:
        fields.append(
            {
                "name": "Location / status",
                "value": _trunc_field(loc_raw),
                "inline": False,
            }
        )
    if org_raw:
        fields.append(
            {
                "name": "Organization",
                "value": _trunc_field(org_raw),
                "inline": True,
            }
        )
    g = (listing.get("gender") or "").strip()
    w = (listing.get("weight") or "").strip()
    if g or w:
        size_line = " · ".join(x for x in (g, w) if x)
        fields.append(
            {"name": "Gender & weight", "value": _trunc_field(size_line), "inline": True}
        )

    embed: dict[str, Any] = {
        "title": f"{listing.get('name', 'Unknown Cat')} ({listing.get('breed', 'Unknown Breed')})",
        "url": listing.get("listing_url"),
        "thumbnail": {"url": listing.get("photo_url")} if listing.get("photo_url") else None,
        "color": 0xE67E22 if priority is True else None,
        "fields": fields,
        "footer": {"text": f"UTC {datetime.now(timezone.utc).isoformat()}"},
    }
    if desc_raw:
        d = re.sub(r"\s+", " ", desc_raw)
        if len(d) > 4096:
            d = d[:4095].rstrip() + "…"
        embed["description"] = d
    author = _author_for_source(str(src) if src else None)
    if author:
        embed["author"] = author

    # Remove keys with None values to keep payload clean (and skip color for non-priority).
    clean_embed = {key: value for key, value in embed.items() if value is not None}
    payload = {"embeds": [clean_embed]}

    response = requests.post(webhook_url, json=payload, timeout=30)
    if response.status_code not in (200, 204):
        logger.warning(
            "Discord webhook failed with status=%s body=%s",
            response.status_code,
            response.text[:500],
        )
