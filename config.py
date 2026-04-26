"""Configuration values for catbot scrapers and filters."""

from __future__ import annotations

# Breeds that get the `is_target_breed` flag in alerts (substring match, case-insensitive).
TARGET_BREEDS: list[str] = ["Siberian", "Russian Blue", "Balinese"]
# Kept for backward compatibility; same as TARGET_BREEDS.
BREEDS: list[str] = TARGET_BREEDS


def breed_is_target(breed: str) -> bool:
    """Return True if `breed` text matches a configured target breed (substring, lowercased)."""
    if not breed or not str(breed).strip():
        return False
    bl = breed.lower()
    return any(t.lower() in bl for t in TARGET_BREEDS)


# Milo Foundation — public cats gallery (ShelterLuv iframe, cats only, Bay Area org).
MILO_CATS_GALLERY_URL: str = "https://www.milofoundation.org/cats-for-adoption/"
# Used only if the iframe is not found on the gallery page; must match the site’s org embed.
MILO_SHELTERLUV_EMBED_FALLBACK: int = 11413

SFSPCA_URL: str = "https://www.sfspca.org/adoptions/cats/"

# Max body text for the Discord embed `description` (og: bio / first paragraph).
EMBED_DESCRIPTION_MAX: int = 500

# Embed “author” row: site name links here; small `icon_url` (Discord-friendly HTTPS).
SOURCE_BRANDING: dict[str, dict[str, str]] = {
    "Milo Foundation": {
        "author_url": "https://www.milofoundation.org/",
        "icon_url": "https://www.google.com/s2/favicons?domain=milofoundation.org&sz=64",
    },
    "SF SPCA": {
        "author_url": "https://www.sfspca.org/",
        "icon_url": "https://www.sfspca.org/favicon.ico",
    },
}
