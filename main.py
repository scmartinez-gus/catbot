"""Main runner for catbot scraping and Discord notifications."""

from __future__ import annotations

import logging
import os
from typing import Any

from dotenv import load_dotenv

from db import is_new, mark_seen, setup_db
from discord_notify import send_alert
from scrapers.adoptapet import fetch_adoptapet_listings
from scrapers.sfspca import fetch_sfspca_listings


def configure_logging() -> None:
    """Configure process logging for console and cron output."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )


def run() -> None:
    """Run one full scrape-notify-dedupe cycle."""
    load_dotenv()
    configure_logging()
    logger = logging.getLogger(__name__)

    webhook_url = os.getenv("DISCORD_WEBHOOK_URL", "").strip()
    if not webhook_url:
        logger.error("Missing DISCORD_WEBHOOK_URL in environment.")
        return

    setup_db()
    logger.info("Starting catbot scrape run.")

    adoptapet_listings: list[dict[str, Any]] = fetch_adoptapet_listings()
    sfspca_listings: list[dict[str, Any]] = fetch_sfspca_listings()
    all_listings = adoptapet_listings + sfspca_listings

    new_count = 0
    new_target = 0
    for listing in all_listings:
        listing_id = str(listing.get("id", "")).strip()
        source = str(listing.get("source", "unknown")).strip()
        if not listing_id:
            logger.warning("Skipping listing without id: %s", listing)
            continue

        if is_new(listing_id):
            send_alert(webhook_url, listing)
            mark_seen(listing_id, source)
            new_count += 1
            if listing.get("is_target_breed") is True:
                new_target += 1

    logger.info(
        "Run complete. Total fetched=%s, total new=%s (target-breed new=%s)",
        len(all_listings),
        new_count,
        new_target,
    )


if __name__ == "__main__":
    run()

# Cron (every 4 hours):
# 0 */4 * * * cd /path/to/catbot && /usr/bin/python3 main.py >> logs/catbot.log 2>&1
