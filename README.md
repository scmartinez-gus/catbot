# catbot

Scrapes **The Milo Foundation** ([cats gallery](https://www.milofoundation.org/cats-for-adoption/)) and **SF SPCA** cats, dedupes in SQLite, and posts new listings to a **Discord** webhook. Target breeds (Siberian, Russian Blue, Balinese) are flagged in each embed; all cats are still alerted.

## Setup

```bash
pip install -r requirements.txt
playwright install chromium
cp .env.example .env
# set DISCORD_WEBHOOK_URL in .env
python main.py
```

## Sources

- **Milo Foundation** — ShelterLuv embed on the public cats page; cats only, local org.
- **SF SPCA** — [Cats adoptions](https://www.sfspca.org/adoptions/cats/) (grid + per-pet details).

(Adopt-a-Pet was removed; it mixed species/geographies.)

## GitHub Actions

Repository secret: **`DISCORD_WEBHOOK_URL`**.  
Workflow: `.github/workflows/catbot.yml` (scheduled + manual). The SQLite file is **uploaded/restored as an artifact** so CI dedupes across runs.  
**Don’t** also run the same job on a schedule on your laptop unless you want duplicate logic (two different DBs).

## Cron (local)

See the comment at the bottom of `main.py`.
