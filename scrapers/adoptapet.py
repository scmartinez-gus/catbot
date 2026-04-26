"""Scraper for Adopt-a-Pet cat listings."""

from __future__ import annotations

import html as html_unescape
import logging
import re
from typing import Any

import requests
from bs4 import BeautifulSoup
from bs4.element import Tag
from playwright.sync_api import sync_playwright

from config import ADOPTAPET_SEARCH_URL, EMBED_DESCRIPTION_MAX, breed_is_target

logger = logging.getLogger(__name__)

# Confirmed 2026-04: list markup is in client-rendered cards; use DevTools to re-check if parsing breaks.
USER_AGENT: str = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)


def _extract_numeric_id(listing_url: str) -> str:
    """Build adoptapet_* id from the numeric part of /pet/<id>-... in the listing URL."""
    match = re.search(r"/pet/(\d+)", listing_url)
    if match:
        return f"adoptapet_{match.group(1)}"
    fallback = re.sub(r"[^a-zA-Z0-9]", "_", listing_url).strip("_")
    return f"adoptapet_{fallback}"


def _trunc(text: str, max_len: int) -> str:
    """Shorten a string to `max_len` with an ellipsis, trimming whitespace."""
    t = re.sub(r"\s+", " ", (text or "").strip())
    if len(t) <= max_len:
        return t
    return t[: max_len - 1].rstrip() + "…"


def _parse_pet_card(card: Tag) -> dict[str, Any]:
    """Parse a single `div.pet-card--component` (search results) into fields."""
    # TODO(DevTools): Re-open a breed search, inspect one card. Confirm: root
    # `div.pet-card--component`, link `a[href*="/pet/"]`, `p.name`, `p.breed`, `img.pet-image`, `div.sex`.
    link_el = card.select_one("a[href*='/pet/']")
    if not link_el or not link_el.get("href"):
        raise ValueError("Adopt-a-Pet card missing /pet/ link")
    listing_url = str(link_el["href"]).split("?", maxsplit=1)[0]
    name_el = card.select_one("p.name")
    breed_el = card.select_one("p.breed")
    img_el = card.select_one("img.pet-image")
    # Age / life stage: compact row under breed (e.g. "Male, 1 Yr 6 Mos" or "Female, young").
    sex_div = card.select_one("div.sex")
    age_guess = sex_div.get_text(" ", strip=True) if sex_div else "Unknown"
    breed = breed_el.get_text(strip=True) if breed_el else "Unknown"
    return {
        "id": _extract_numeric_id(listing_url),
        "name": name_el.get_text(strip=True) if name_el else "Unknown",
        "breed": breed,
        "age": age_guess,
        "photo_url": (img_el.get("src", "") or "").strip() if img_el else "",
        "listing_url": listing_url,
        "source": "Adopt-a-Pet",
        "is_target_breed": breed_is_target(breed),
    }


def _enrich_from_detail_listing_page(row: dict[str, Any]) -> None:
    """
    In-place: fetch the pet’s profile and add `description` and `location` (best-effort).

    Primary copy comes from `og:description` (e.g. “… for adoption in City, ST who needs…”).
    """
    url = str(row.get("listing_url", "")).strip()
    if not url:
        return
    try:
        r = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=30)
        r.raise_for_status()
    except requests.RequestException:
        logger.debug("Adopt-a-Pet detail fetch failed for %s", url, exc_info=True)
        return
    soup = BeautifulSoup(r.text, "html.parser")
    og = soup.find("meta", property="og:description")
    raw = (og and (og.get("content") or "").strip()) or ""
    if not raw:
        return
    desc = html_unescape.unescape(_trunc(raw, EMBED_DESCRIPTION_MAX))
    if desc:
        row["description"] = desc
    # “… for adoption in Napa, CA who needs a loving home.”
    m = re.search(r"for adoption in\s+(.+?)\s+who needs", desc, re.I)
    if m:
        row["location"] = m.group(1).strip()


def _listings_from_soup(soup: BeautifulSoup) -> list[dict[str, Any]]:
    """Extract all pet cards from already-parsed search HTML (all breeds; target breeds flagged)."""
    out: list[dict[str, Any]] = []
    for card in soup.select("div.pet-card--component"):
        try:
            out.append(_parse_pet_card(card))
        except Exception:
            logger.exception("Failed to parse one Adopt-a-Pet listing card")
    return out


def _fetch_html_with_requests(url: str) -> str:
    """Return raw HTML for a search URL (often missing cards; site is JS-heavy)."""
    r = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=30)
    r.raise_for_status()
    return r.text


def _fetch_html_with_playwright(url: str) -> str:
    """Option B: load search in headless Chromium so `pet-card` nodes exist in the DOM."""
    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=["--disable-blink-features=AutomationControlled"],
        )
        try:
            page = browser.new_page(
                user_agent=USER_AGENT,
                viewport={"width": 1280, "height": 900},
            )
            # TODO(DevTools): If cards fail to load, record Network tab: note XHRs and min wait time.
            page.goto(url, wait_until="load", timeout=90_000)
            page.wait_for_selector("div.pet-card--component", timeout=60_000)
            return page.content()
        finally:
            browser.close()


def _parse_search_page(url: str) -> list[dict[str, Any]]:
    """
    Get listings for one search URL: try requests+BS, then Playwright+BS if no cards.
    Deduplicate by `id` (search UI duplicates links inside the same card).
    """
    html: str
    try:
        html = _fetch_html_with_requests(url)
    except requests.RequestException:
        logger.exception("Adopt-a-Pet requests failed for %s", url)
        return []

    soup = BeautifulSoup(html, "html.parser")
    rows = _listings_from_soup(soup)
    if not rows and not soup.select("div.pet-card--component"):
        logger.info("Adopt-a-Pet: no pet cards in static HTML; using Playwright for %s", url)
        try:
            html = _fetch_html_with_playwright(url)
        except Exception:
            logger.exception("Adopt-a-Pet Playwright failed for %s", url)
            return []
        soup = BeautifulSoup(html, "html.parser")
        rows = _listings_from_soup(soup)

    seen: set[str] = set()
    deduped: list[dict[str, Any]] = []
    for r in rows:
        pid = str(r["id"])
        if pid in seen:
            continue
        seen.add(pid)
        deduped.append(r)

    for row in deduped:
        _enrich_from_detail_listing_page(row)
    return deduped


def fetch_adoptapet_listings() -> list[dict[str, Any]]:
    """
    Fetch one Adopt-a-Pet search (all cat breeds in configured location).

    Every card is included; `is_target_breed` is set for Siberian / Russian Blue / Balinese.
    Each listing is enriched from the public profile (og:description, location in-text).
    """
    return _parse_search_page(ADOPTAPET_SEARCH_URL)
