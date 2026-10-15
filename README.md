# Stanford gym tracker

Logs how busy two Stanford fitness centers are, every 15 minutes, into a CSV —
so you can work out when they're actually quiet.

Tracked facilities:

- **AOERC - Fitness Center** (capacity 150)
- **ACSR - Fitness Center** (capacity 125)

## Where the data comes from

`rec.stanford.edu` embeds a Connect2Concepts widget in an iframe:

```
https://www.connect2mycloud.com/Widgets/Data/locationCount?type=circle&key=9f320719-e415-46d7-b233-a89d85ba6d97
```

That iframe is just an empty shell. Its JavaScript takes the `key` from its own
query string and calls a public JSON API, which is what actually holds the
counts:

```
https://goboardapi.azurewebsites.net/api/FacilityCount/GetCountsByAccount?AccountAPIKey=9f320719-e415-46d7-b233-a89d85ba6d97
```

`scrape.py` calls that JSON API directly, so the scheduled job needs no browser
and takes about a second.

Two details worth knowing, both copied from the widget's own JavaScript:

- The API's `PercetageCapacity` field (sic) is always `0`. The widget computes
  the real figure itself as `round(LastCount / TotalCapacity * 100)`, so we do
  the same.
- `LastUpdatedDateAndTime` has no timezone suffix, so the widget's `new Date()`
  reads it as local time. It is already Pacific wall-clock time, and we treat it
  as such rather than converting it.

Both were verified against the live rendered widget — see
`discover_widget_api.py`, which drives the real page in headless Chromium,
prints the data URL it requests, and dumps the rendered cards so you can check
our numbers still match.

## The CSV

Rows land in `data/counts.csv`:

| column | meaning |
| --- | --- |
| `checked_at` | when the script ran (Pacific, ISO 8601) |
| `day_of_week` | e.g. `Wednesday` |
| `hour` | `0`–`23`, for grouping by time of day |
| `facility` | `AOERC - Fitness Center` or `ACSR - Fitness Center` |
| `status` | `Open` or `Closed` |
| `last_count` | people counted |
| `percent_full` | `0`–`100`; **blank when closed** (the widget shows `NA`) |
| `capacity` | the facility's total capacity |
| `updated` | reading time as the widget displays it, `MM/DD/YYYY hh:mm AM/PM` |
| `updated_raw` | raw API timestamp — the de-duplication key |

**No duplicate rows.** The turnstile counts refresh far less often than every
15 minutes, so most runs have nothing new to say. A row is written only when a
facility's `updated_raw` differs from the last row stored for that facility,
and the two facilities are tracked independently — if AOERC posts a new reading
and ACSR doesn't, only AOERC gets a row.

## Running it yourself

```bash
pip install -r requirements.txt
python scrape.py
```

It prints what it did and appends to `data/counts.csv`.

To re-check the widget (optional, needs a browser download):

```bash
pip install playwright && python -m playwright install chromium
python discover_widget_api.py
```

## The schedule

`.github/workflows/scrape.yml` runs every 15 minutes, and commits
`data/counts.csv` only when it actually changed. You can also trigger it by
hand from the repo's **Actions** tab via **Run workflow**.

Two things to expect from GitHub's scheduled runs:

- Scheduled jobs are best-effort and run on a shared queue, so they often fire
  several minutes late and occasionally get skipped under load. That's fine
  here — a missed run just means a reading gets picked up by the next one.
- **GitHub disables scheduled workflows after 60 days with no repo activity.**
  Since this repo commits to itself whenever counts change, that clock keeps
  resetting on its own. If the gyms ever go quiet for two months, re-enable it
  from the Actions tab.
