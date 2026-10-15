#!/usr/bin/env python3
"""Track live occupancy for two Stanford gym fitness centers.

Data source
-----------
rec.stanford.edu embeds a Connect2Concepts widget as an iframe:

    https://www.connect2mycloud.com/Widgets/Data/locationCount
        ?type=circle&key=9f320719-e415-46d7-b233-a89d85ba6d97

That widget is an empty shell; it fills itself in from a JSON API, using the
`key` from its own query string as the account API key:

    https://goboardapi.azurewebsites.net/api/FacilityCount/GetCountsByAccount
        ?AccountAPIKey=<key>

We call that JSON API directly, so no browser is needed at run time.

Derived fields
--------------
The API's own `PercetageCapacity` field is always 0, so the widget computes the
percentage client-side. We mirror its logic exactly:

    percent_full = round(LastCount / TotalCapacity * 100)   # "NA" when closed

`LastUpdatedDateAndTime` carries no timezone suffix, so the widget's JavaScript
`new Date(...)` parses it as local time -- i.e. it is already Pacific wall-clock
time as a Stanford visitor sees it. We treat it that way and attach the Pacific
zone to it rather than converting.
"""

from __future__ import annotations

import csv
import re
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

ACCOUNT_API_KEY = "9f320719-e415-46d7-b233-a89d85ba6d97"
API_URL = (
    "https://goboardapi.azurewebsites.net/api/FacilityCount/GetCountsByAccount"
    f"?AccountAPIKey={ACCOUNT_API_KEY}"
)

# Exact LocationName values we care about, as they appear in the feed.
FACILITIES = ("AOERC - Fitness Center", "ACSR - Fitness Center")

PACIFIC = ZoneInfo("America/Los_Angeles")

CSV_PATH = Path(__file__).parent / "data" / "counts.csv"

FIELDNAMES = [
    "checked_at",      # when this script ran (Pacific, ISO 8601)
    "day_of_week",     # e.g. "Wednesday" -- of checked_at
    "hour",            # 0-23 -- of checked_at
    "facility",        # e.g. "AOERC - Fitness Center"
    "status",          # "Open" or "Closed"
    "last_count",      # people currently counted
    "percent_full",    # 0-100, or blank when closed (widget shows "NA")
    "capacity",        # TotalCapacity, for context
    "updated",         # as displayed: "MM/DD/YYYY hh:mm AM/PM"
    "updated_raw",     # raw API timestamp -- the de-duplication key
]

# "2026-10-14T17:52:13.873" / "2026-10-14 09:16:53.99" -- fraction ignored.
TIMESTAMP_RE = re.compile(r"(\d{4})-(\d{2})-(\d{2})[T ](\d{2}):(\d{2})")

REQUEST_TIMEOUT = 30
USER_AGENT = "stanford-gym-tracker (+https://github.com/allmankm/gym-tracker)"


def fetch_locations() -> list[dict]:
    """Return the raw list of location dicts from the GoBoard API."""
    resp = requests.get(
        API_URL, timeout=REQUEST_TIMEOUT, headers={"User-Agent": USER_AGENT}
    )
    resp.raise_for_status()
    data = resp.json()
    if not isinstance(data, list):
        raise ValueError(f"expected a JSON list, got {type(data).__name__}")
    return data


def format_updated(raw: str) -> str:
    """Render the API timestamp the way the widget displays it.

    "2026-10-14T17:52:13.873" -> "10/14/2026 05:52 PM"

    We pull the fields out with a regex rather than `datetime.fromisoformat`,
    because the feed is inconsistent about fractional seconds -- it emits both
    ".873" and ".99", and `fromisoformat` rejects anything other than 3 or 6
    digits on Python < 3.11. Only the minute matters here anyway.
    """
    match = TIMESTAMP_RE.match(raw.strip()) if raw else None
    if not match:
        return raw or ""  # keep whatever the API gave us rather than losing it
    year, month, day, hour, minute = (int(g) for g in match.groups())
    meridiem = "AM" if hour < 12 else "PM"
    hour12 = hour % 12 or 12
    return f"{month:02d}/{day:02d}/{year} {hour12:02d}:{minute:02d} {meridiem}"


def build_row(loc: dict, checked: datetime) -> dict:
    """Turn one API location dict into a CSV row."""
    is_closed = bool(loc.get("IsClosed"))
    last_count = loc.get("LastCount") or 0
    capacity = loc.get("TotalCapacity") or 0

    if is_closed or not capacity:
        percent = ""  # widget renders "NA"; blank keeps the column numeric
    else:
        percent = round(last_count / capacity * 100)

    raw_updated = loc.get("LastUpdatedDateAndTime") or ""

    return {
        "checked_at": checked.isoformat(timespec="seconds"),
        "day_of_week": checked.strftime("%A"),
        "hour": checked.hour,
        "facility": loc.get("LocationName", ""),
        "status": "Closed" if is_closed else "Open",
        "last_count": last_count,
        "percent_full": percent,
        "capacity": capacity,
        "updated": format_updated(raw_updated),
        "updated_raw": raw_updated,
    }


def last_seen_updates(path: Path) -> dict[str, str]:
    """Map facility -> the most recent `updated_raw` already stored for it."""
    if not path.exists():
        return {}
    seen: dict[str, str] = {}
    with path.open(newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            facility = row.get("facility")
            if facility:
                # later rows overwrite earlier ones, so we end up with the last
                seen[facility] = row.get("updated_raw", "")
    return seen


def append_rows(path: Path, rows: list[dict]) -> None:
    """Append rows, writing a header first if the file is new."""
    path.parent.mkdir(parents=True, exist_ok=True)
    write_header = not path.exists() or path.stat().st_size == 0
    with path.open("a", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=FIELDNAMES)
        if write_header:
            writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    checked = datetime.now(PACIFIC)

    try:
        locations = fetch_locations()
    except Exception as exc:
        print(f"ERROR: could not fetch the counts API: {exc}", file=sys.stderr)
        return 1

    by_name = {loc.get("LocationName"): loc for loc in locations}

    missing = [name for name in FACILITIES if name not in by_name]
    if missing:
        print(
            f"ERROR: these facilities were not in the feed: {missing}\n"
            f"Feed currently has: {sorted(n for n in by_name if n)}",
            file=sys.stderr,
        )
        return 1

    already = last_seen_updates(CSV_PATH)
    new_rows = []

    for name in FACILITIES:
        row = build_row(by_name[name], checked)
        if row["updated_raw"] and row["updated_raw"] == already.get(name):
            print(f"  skip  {name}: unchanged (Updated {row['updated']})")
            continue
        new_rows.append(row)
        print(
            f"  ADD   {name}: {row['status']}, count={row['last_count']}, "
            f"{row['percent_full'] or 'NA'}% full, Updated {row['updated']}"
        )

    if not new_rows:
        print("No new readings; CSV left untouched.")
        return 0

    append_rows(CSV_PATH, new_rows)
    print(f"Wrote {len(new_rows)} row(s) to {CSV_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
