"""Scraper for SF SPCA cat listings with requests first, Playwright fallback."""

from __future__ import annotations

import html as html_unescape
import logging
import re
from typing import Any

import requests
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright

from config import EMBED_DESCRIPTION_MAX, SFSPCA_URL, breed_is_target

logger = logging.getLogger(__name__)

# Match network requests used elsewhere; confirmed detail pages return 200 with this UA in testing.
USER_AGENT: str = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)


def _extract_sfspca_id(listing_url: str) -> str:
    """Extract a stable id from an SF SPCA pet URL: .../sfspca-adoption/<id>/."""
    match = re.search(r"/sfspca-adoption/(\d+)", listing_url, re.I)
    if match:
        return f"sfspca_{match.group(1)}"
    fallback = re.sub(r"[^a-zA-Z0-9]", "_", listing_url).strip("_")
    return f"sfspca_{fallback}"


def _trunc(text: str, max_len: int) -> str:
    """Shorten a string to `max_len` with an ellipsis."""
    t = re.sub(r"\s+", " ", (text or "").strip())
    if len(t) <= max_len:
        return t
    return t[: max_len - 1].rstrip() + "…"


def _parse_adoption_facts_text(facts: str) -> tuple[str, str]:
    """
    Return (age, breed) from `div.adoptionFacts__div` text.

    Example: Age: 5 y, 2 m Weight: ... Gender: ... Breed: Domestic Shorthair
    """
    text = re.sub(r"\s+", " ", facts.strip())
    age_m = re.search(r"Age:\s*(.+?)(?=\s*Weight:|\Z)", text, re.I)
    breed_m = re.search(r"Breed:\s*(.+)$", text, re.I)
    age = age_m.group(1).strip() if age_m else "Unknown"
    breed = breed_m.group(1).strip() if breed_m else "Unknown"
    return age, breed


def _parse_weight_gender(facts: str) -> tuple[str, str]:
    """Return (weight, gender) from the same compact facts line."""
    text = re.sub(r"\s+", " ", facts.strip())
    w = re.search(r"Weight:\s*(.+?)(?=\s*Gender:|\Z)", text, re.I)
    g = re.search(r"Gender:\s*(.+?)(?=\s*Breed:|\Z)", text, re.I)
    return (w.group(1).strip() if w else ""), (g.group(1).strip() if g else "")


def _enrich_from_detail_sfsa(listing_url: str, headers: dict[str, str]) -> dict[str, str]:
    """
    Load a pet page and return name, age, breed, long description, weight, and gender.
    """
    r = requests.get(listing_url, headers=headers, timeout=30)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")
    h1 = soup.select_one("h1")
    name = h1.get_text(strip=True) if h1 else "Unknown"
    raw_og = soup.find("meta", property="og:description")
    og0 = (raw_og and (raw_og.get("content") or "").strip()) or ""
    og0 = html_unescape.unescape(og0)
    desc = _trunc(og0, EMBED_DESCRIPTION_MAX) if og0 and len(og0) > 20 else ""
    if not desc or "Join our community" in desc:
        for p in soup.find_all("p"):
            t = p.get_text(" ", strip=True)
            if len(t) < 80 or "Join our community" in t or "gform" in t.lower():
                continue
            if re.search(r"\bMeet\b", t):
                desc = _trunc(t, EMBED_DESCRIPTION_MAX)
                break
    facts_el = soup.select_one("div.adoptionFacts__div")
    age, breed = "Unknown", "Unknown"
    w_str, g_str = "", ""
    if facts_el:
        ft = facts_el.get_text(" ", strip=True)
        age, breed = _parse_adoption_facts_text(ft)
        w_str, g_str = _parse_weight_gender(ft)
    return {
        "name": name,
        "age": age,
        "breed": breed,
        "description": desc,
        "weight": w_str,
        "gender": g_str,
    }


def _grid_rows_from_soup(
    html: str,
) -> list[tuple[str, str, str, str]]:
    """
    Parse the adoption grid: (listing_url, name_from_card, photo_url, place_subtitle or "").

    TODO(DevTools): Open /adoptions/cats/, confirm `div.adoption__item--location` and media link.
    """
    soup = BeautifulSoup(html, "html.parser")
    rows: list[tuple[str, str, str, str]] = []
    for item in soup.select("div.adoption__item"):
        link = item.select_one("a[href*='/sfspca-adoption/']")
        if not link or not link.get("href"):
            continue
        listing_url = str(link["href"]).split("?", maxsplit=1)[0]
        name_a = item.select_one("a.userContent__permalink, div.adoption__item--name a")
        name = name_a.get_text(strip=True) if name_a else "Unknown"
        place_el = item.select_one("div.adoption__item--location")
        place = place_el.get_text(" ", strip=True) if place_el else ""
        photo = ""
        media = item.select_one("div.adoption__media a[style*='background-image']")
        if media and media.get("style"):
            m = re.search(
                r"background-image:\s*url\(\s*['\"]?([^'\")]+)['\"]?\s*\)",
                media["style"],
                re.I,
            )
            if m:
                photo = m.group(1).strip()
        if not photo:
            im = item.select_one("img")
            if im and im.get("src"):
                photo = (im.get("src") or "").strip()
        rows.append((listing_url, name, photo, place))
    return rows


def _sfspca_grid_to_listings(html: str) -> list[dict[str, Any]]:
    """Build listing dicts: all cats, with detail enrichment and `is_target_breed`."""
    headers = {"User-Agent": USER_AGENT}
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for listing_url, grid_name, photo, place in _grid_rows_from_soup(html):
        try:
            lid = _extract_sfspca_id(listing_url)
            if lid in seen:
                continue
            seen.add(lid)
            d = _enrich_from_detail_sfsa(listing_url, headers=headers)
            name = d["name"]
            if name == "Unknown" and grid_name != "Unknown":
                name = grid_name
            breed = d["breed"]
            out.append(
                {
                    "id": lid,
                    "name": name,
                    "breed": breed,
                    "age": d["age"],
                    "description": d.get("description", ""),
                    "photo_url": photo,
                    "listing_url": listing_url,
                    "source": "SF SPCA",
                    "is_target_breed": breed_is_target(breed),
                    "location": place,
                    "organization": "San Francisco SPCA",
                    "weight": d.get("weight", ""),
                    "gender": d.get("gender", ""),
                }
            )
        except Exception:
            logger.exception("Failed SF SPCA listing for %s", listing_url)
    return out


def _fetch_option_a_requests() -> list[dict[str, Any]]:
    """Option A: requests + BeautifulSoup: grid is usually empty in first response (no JS)."""
    response = requests.get(
        SFSPCA_URL, headers={"User-Agent": USER_AGENT}, timeout=30
    )
    response.raise_for_status()
    return _sfspca_grid_to_listings(response.text)


def _fetch_option_b_playwright() -> list[dict[str, Any]]:
    """Option B: render `userContent` grid in headless Chromium, then same enrichment."""
    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=["--disable-blink-features=AutomationControlled"],
        )
        try:
            page = browser.new_page(
                user_agent=USER_AGENT, viewport={"width": 1280, "height": 900}
            )
            page.goto(SFSPCA_URL, wait_until="load", timeout=90_000)
            page.wait_for_selector("div.adoption__item", timeout=60_000)
            html = page.content()
        finally:
            browser.close()
    return _sfspca_grid_to_listings(html)


def fetch_sfspca_listings() -> list[dict[str, Any]]:
    """Fetch SF SPCA: try static HTML, then Playwright if no adoption grid rows."""
    try:
        listings = _fetch_option_a_requests()
        if listings:
            return listings
        logger.info("SF SPCA Option A: no grid rows; trying Playwright.")
    except Exception:
        logger.exception("SF SPCA Option A failed; trying Playwright fallback.")

    try:
        return _fetch_option_b_playwright()
    except Exception:
        logger.exception("SF SPCA Option B failed.")
        return []
