"""Milo Foundation (Point Richmond) cat listings — ShelterLuv embed on the gallery page."""

from __future__ import annotations

import html as html_unescape
import logging
import re
from typing import Any

import requests
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright

from config import EMBED_DESCRIPTION_MAX, MILO_CATS_GALLERY_URL, MILO_SHELTERLUV_EMBED_FALLBACK, breed_is_target

logger = logging.getLogger(__name__)

USER_AGENT: str = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)


def _milo_listing_id(animal_code: str) -> str:
    """Stable id for SQLite + Discord: milo_MILO-A-####."""
    code = re.sub(r"[^A-Za-z0-9-]", "", animal_code)
    return f"milo_{code}"


def _animal_code_from_url(url: str) -> str:
    """Return e.g. MILO-A-10000 from a ShelterLuv animal URL."""
    m = re.search(r"/embed/animal/((?:[A-Z]+-)+[A-Z0-9-]+)", url, re.I)
    if m:
        return m.group(1).upper()
    return re.sub(r"[^A-Za-z0-9-]", "-", url).strip("-")


def _collect_shelterluv_frame_html() -> str:
    """
    Open the public cats gallery, wait for the ShelterLuv iframe, and return its HTML.

    The gallery is https://www.milofoundation.org/cats-for-adoption/ and loads cats
    (Bay Area / Point Richmond) only; species=Cat excludes dogs.
    """
    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=["--disable-blink-features=AutomationControlled"],
        )
        try:
            page = browser.new_page(
                user_agent=USER_AGENT,
                viewport={"width": 1280, "height": 2400},
            )
            # TODO(DevTools): If iframe id changes, confirm `shelterluv.com/embed/...&species=Cat` in the Network tab.
            page.goto(
                MILO_CATS_GALLERY_URL, wait_until="load", timeout=90_000
            )
            page.wait_for_timeout(5_000)
            for fr in page.frames:
                u = fr.url
                if "shelterluv.com/embed" in u and "Cat" in u and "matchme" not in u:
                    fr.wait_for_timeout(15_000)
                    return fr.content()
            # Fallback: direct org embed (same org id Milo uses on site: 11413)
            direct = (
                f"https://www.shelterluv.com/embed/{MILO_SHELTERLUV_EMBED_FALLBACK}"
                "?species=Cat"
            )
            logger.info("Milo: no cat-count iframe on gallery; using direct embed %s", direct)
            page.goto(direct, wait_until="load", timeout=90_000)
            page.wait_for_timeout(15_000)
            return page.content()
        finally:
            browser.close()


def _parse_embed_animal_hrefs(html: str) -> list[str]:
    """Collect unique ShelterLuv per-cat profile URLs from iframe HTML."""
    found = re.findall(
        r'(https://www\.shelterluv\.com/embed/animal/[^\s"\'&<>#]+)', html, re.I
    )
    out: list[str] = []
    seen: set[str] = set()
    for h in found:
        h = h.rstrip(".,);")
        if h not in seen:
            seen.add(h)
            out.append(h)
    return out


def _enrich_animal_url(listing_url: str) -> dict[str, str]:
    """
    Fetch a single `embed/animal/...` page and pull fields for alerts.

    Uses og tags + a small regex for `primary_breed` in the HTML payload.
    """
    r = requests.get(
        listing_url, headers={"User-Agent": USER_AGENT}, timeout=30
    )
    r.raise_for_status()
    text = r.text
    soup = BeautifulSoup(text, "html.parser")
    ogd = soup.find("meta", property="og:description")
    ogt = soup.find("meta", property="og:title")
    ogi = soup.find("meta", property="og:image")
    desc = ""
    if ogd and ogd.get("content"):
        desc = html_unescape.unescape(ogd["content"].strip())
        if len(desc) > EMBED_DESCRIPTION_MAX:
            desc = desc[: EMBED_DESCRIPTION_MAX - 1].rstrip() + "…"
    name = "Unknown"
    if ogt and ogt.get("content"):
        title = html_unescape.unescape(ogt["content"].strip())
        m = re.match(r"^(.+?)\s+is available for adoption", title, re.I)
        if m:
            name = m.group(1).strip()
        else:
            name = title.split("|")[0].split("-")[0].strip() or title
    photo = (ogi.get("content") or "").strip() if ogi else ""
    b = re.search(r"&quot;primary_breed&quot;:&quot;([^&]+)&quot", text) or re.search(
        r"primary_breed['\"]:\s*['\"]([^'\"]+)['\"]", text, re.I
    )
    breed = b.group(1).strip() if b else "Unknown"
    return {
        "name": name,
        "breed": breed,
        "description": desc,
        "photo_url": photo,
        "age": "Unknown",
    }


def fetch_milo_listings() -> list[dict[str, Any]]:
    """
    Scrape the Milo Foundation cats-for-adoption gallery (cats only, local org).

    Listings are loaded inside a ShelterLuv `embed` (species=Cat). Each card links to
    `shelterluv.com/embed/animal/MILO-A-...`; we then enrich with `requests` to that URL.
    """
    try:
        frame_html = _collect_shelterluv_frame_html()
    except Exception:
        logger.exception("Milo: Playwright failed to load the gallery or embed")
        return []

    hrefs = _parse_embed_animal_hrefs(frame_html)
    if not hrefs:
        logger.warning("Milo: no embed/animal links found; site markup may have changed")
        return []

    listings: list[dict[str, Any]] = []
    for url in hrefs:
        try:
            code = _animal_code_from_url(url)
            lid = _milo_listing_id(code)
            extra = _enrich_animal_url(url)
            listings.append(
                {
                    "id": lid,
                    "name": extra["name"],
                    "breed": extra["breed"],
                    "age": extra["age"],
                    "description": extra["description"],
                    "photo_url": extra["photo_url"],
                    "listing_url": url,
                    "source": "Milo Foundation",
                    "is_target_breed": breed_is_target(extra["breed"]),
                    "location": "Milo Point Richmond, CA (Bay Area)",
                    "organization": "The Milo Foundation",
                }
            )
        except Exception:
            logger.exception("Milo: failed to enrich %s", url)
    return listings
