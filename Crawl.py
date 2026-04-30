"""
NBA Player Stats Scraper
"""
from __future__ import annotations
import argparse
import csv
import json
import sys
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Tuple
from urllib import request, parse, error


STATS_ENDPOINT = "https://stats.nba.com/stats/leaguedashplayerstats"

# Default headers that mimic a real browser; stats.nba.com rejects bare clients.
DEFAULT_HEADERS = {
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Connection": "keep-alive",
    "Host": "stats.nba.com",
    "Origin": "https://www.nba.com",
    "Referer": "https://www.nba.com/",
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Sec-Fetch-Site": "same-site",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Dest": "empty",
}


def guess_default_season(today: datetime | None = None) -> str:
    d = today or datetime.now(timezone.utc)
    y = d.year
    if d.month >= 8:
        start = y
        end = (y + 1) % 100
    else:
        start = y - 1
        end = y % 100
    return f"{start}-{end:02d}"


def build_params(
    season: str,
    season_type: str = "Regular Season",
    per_mode: str = "PerGame",
    measure_type: str = "Base",
    league_id: str = "00",
) -> Dict[str, str]:
    return {
        "MeasureType": measure_type,
        "PerMode": per_mode,
        "PlusMinus": "Y",
        "PaceAdjust": "N",
        "Rank": "N",
        "LeagueID": league_id,
        "Season": season,
        "SeasonType": season_type,
        "PORound": "0",
        "Outcome": "",
        "Location": "",
        "Month": "0",
        "SeasonSegment": "",
        "DateFrom": "",
        "DateTo": "",
        "OpponentTeamID": "0",
        "VsConference": "",
        "VsDivision": "",
        "TeamID": "0",
        "Conference": "",
        "Division": "",
        "GameSegment": "",
        "Period": "0",
        "ShotClockRange": "",
        "LastNGames": "0",
        "TwoWay": "0",
        "GameScope": "",
        "PlayerExperience": "",
        "PlayerPosition": "",
        "StarterBench": "",
        "DraftYear": "",
        "DraftPick": "",
        "College": "",
        "Country": "",
        "Height": "",
        "Weight": "",
    }


def fetch_with_retries(
    url: str,
    params: Dict[str, str],
    headers: Dict[str, str] | None = None,
    max_retries: int = 5,
    backoff_base: float = 1.2,
    timeout: int = 20,
    quiet: bool = False,
) -> Dict[str, Any]:
    q = parse.urlencode(params)
    full_url = f"{url}?{q}"
    hdrs = headers or DEFAULT_HEADERS

    last_exc: Exception | None = None
    for attempt in range(1, max_retries + 1):
        try:
            req = request.Request(full_url, headers=hdrs, method="GET")
            with request.urlopen(req, timeout=timeout) as resp:
                status = resp.getcode()
                if status != 200:
                    raise RuntimeError(f"HTTP {status} from server")
                raw = resp.read()
                data = json.loads(raw.decode("utf-8"))
                return data
        except (error.HTTPError, error.URLError, TimeoutError, json.JSONDecodeError, RuntimeError) as e:
            last_exc = e
            if not quiet:
                print(f"[warn] Attempt {attempt}/{max_retries} failed: {e}", file=sys.stderr)
            if attempt < max_retries:
                sleep_s = backoff_base ** attempt
                time.sleep(sleep_s)
            continue

    raise RuntimeError(f"Failed to fetch data after {max_retries} attempts. Last error: {last_exc}")


def extract_table(data: Dict[str, Any]) -> Tuple[List[str], List[List[Any]]]:
    if "resultSets" in data and data["resultSets"]:
        rs = data["resultSets"][0]
        headers = rs.get("headers", [])
        rows = rs.get("rowSet", [])
    elif "resultSet" in data:
        rs = data["resultSet"]
        headers = rs.get("headers", [])
        rows = rs.get("rowSet", [])
    else:
        raise ValueError("Unexpected JSON structure: no resultSets/resultSet found.")
    if not headers or not rows:
        raise ValueError("No headers or rows returned from API.")
    return headers, rows


def write_csv(
    headers: List[str],
    rows: List[List[Any]],
    out_path: str,
    include_metadata: bool = True,
) -> None:
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        if include_metadata:
            writer.writerow(
                [f"# source={STATS_ENDPOINT} generated_at={datetime.now(timezone.utc).isoformat()}Z"]
            )
        writer.writerow(headers)
        for r in rows:
            writer.writerow(r)


def validate_dataset(headers: List[str], rows: List[List[Any]]) -> None:
    if len(headers) < 5:
        raise ValueError(f"Dataset has only {len(headers)} columns; need >= 5.")
    if len(rows) < 150:
        raise ValueError(f"Dataset has only {len(rows)} rows; need >= 150.")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Scrape NBA per-player season stats from stats.nba.com and save to CSV."
    )
    parser.add_argument(
        "--season",
        type=str,
        default=guess_default_season(),
        help='Season string like "2025-26" (default: auto-guessed by current date)',
    )
    parser.add_argument(
        "--season_type",
        type=str,
        default="Regular Season",
        choices=["Regular Season", "Playoffs", "Pre Season"],
        help='Season type (default: "Regular Season")',
    )
    parser.add_argument(
        "--per_mode",
        type=str,
        default="PerGame",
        choices=["PerGame", "Per36", "Per100Poss"],
        help='Per-mode aggregation (default: "PerGame")',
    )
    parser.add_argument(
        "--measure_type",
        type=str,
        default="Base",
        choices=["Base", "Advanced", "Misc", "Scoring", "Usage", "Four Factors"],
        help='Measure type group (default: "Base")',
    )
    parser.add_argument(
        "-o", "--output",
        type=str,
        default=None,
        help="Output CSV path (default: auto derive from season & per_mode)",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Reduce console output.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    safe_season = args.season.replace(" ", "").replace("/", "-")
    safe_season_type = args.season_type.replace(" ", "")
    safe_per = args.per_mode
    default_out = f"nba_player_stats_{safe_season}_{safe_season_type}_{safe_per}.csv"
    out_path = args.output or default_out

    if not args.quiet:
        print(f"[info] Fetching NBA player stats: season={args.season}, season_type={args.season_type}, per_mode={args.per_mode}, measure={args.measure_type}")
        print(f"[info] Output CSV: {out_path}")

    params = build_params(
        season=args.season,
        season_type=args.season_type,
        per_mode=args.per_mode,
        measure_type=args.measure_type,
    )

    try:
        data = fetch_with_retries(
            STATS_ENDPOINT,
            params=params,
            headers=DEFAULT_HEADERS,
            max_retries=6,
            backoff_base=1.6,
            timeout=25,
            quiet=args.quiet,
        )
        headers, rows = extract_table(data)
        validate_dataset(headers, rows)
        write_csv(headers, rows, out_path)
        if not args.quiet:
            print(f"[ok] Wrote {len(rows)} rows × {len(headers)} columns to {out_path}")
            print("[ok] Done.")
        return 0
    except Exception as e:
        print(f"[error] {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
