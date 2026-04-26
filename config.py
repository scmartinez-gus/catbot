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


# All cats (speciesId=1) near San Francisco — no breed filter; target breeds are flagged in app code.
ADOPTAPET_SEARCH_URL: str = (
    "https://www.adoptapet.com/pet-search?speciesId=1&city=San+Francisco&state=CA"
)

SFSPCA_URL: str = "https://www.sfspca.org/adoptions/cats/"

# Max body text for the Discord embed `description` (og: bio / first paragraph).
EMBED_DESCRIPTION_MAX: int = 500

# Embed “author” row: site name links here; small `icon_url` (Discord-friendly HTTPS).
SOURCE_BRANDING: dict[str, dict[str, str]] = {
    "Adopt-a-Pet": {
        "author_url": "https://www.adoptapet.com/",
        "icon_url": "https://www.adoptapet.com/favicon.ico",
    },
    "SF SPCA": {
        "author_url": "https://www.sfspca.org/",
        "icon_url": "https://www.sfspca.org/favicon.ico",
    },
}
