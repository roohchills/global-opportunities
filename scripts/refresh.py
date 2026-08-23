#!/usr/bin/env python3
"""Daily refresh: verify links, merge curated seed jobs + live discovered PM/ops/founding roles."""

import csv
import json
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
JOBS_FILE = DATA / "jobs.json"
SEED_FILE = DATA / "seed-jobs.json"
HELPERS_FILE = DATA / "helpers.json"
META_FILE = DATA / "meta.json"
CSV_FILE = ROOT / "jobs.csv"

BROWSER_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

PM_KEYWORDS = re.compile(
    r"product\s*manager|product\s*owner|chief\s*of\s*staff|founding\s*pm|"
    r"product\s*lead|group\s*pm|head\s*of\s*product|operations\s*manager|"
    r"bizops|biz\s*ops|program\s*manager|strategy\s*&?\s*ops|general\s*manager",
    re.I,
)

REGION_MAP = {
    "london": "London",
    "uk": "London",
    "united kingdom": "London",
    "england": "London",
    "berlin": "Europe",
    "munich": "Europe",
    "amsterdam": "Europe",
    "netherlands": "Europe",
    "zurich": "Europe",
    "switzerland": "Europe",
    "geneva": "Europe",
    "stockholm": "Europe",
    "sweden": "Europe",
    "paris": "Europe",
    "france": "Europe",
    "copenhagen": "Europe",
    "denmark": "Europe",
    "germany": "Europe",
    "dublin": "Europe",
    "ireland": "Europe",
    "barcelona": "Europe",
    "spain": "Europe",
    "lisbon": "Europe",
    "portugal": "Europe",
    "dubai": "Dubai",
    "uae": "Dubai",
    "abu dhabi": "Dubai",
    "san francisco": "US",
    "seattle": "US",
    "mountain view": "US",
    "menlo park": "US",
    "new york": "US",
    "united states": "US",
    "usa": "US",
    "remote": "Remote",
}

VISA_LABEL = {
    "sponsors": "Sponsors visa",
    "likely": "Likely / check",
    "check": "Confirm w/ company",
    "eu": "EU permit needed",
}

GREENHOUSE_BOARDS = [
    ("Monzo", "monzo", "London"),
    ("Deliveroo", "deliveroo", "London"),
    ("N26", "n26", "Europe"),
    ("Careem", "careem", "Dubai"),
]

MAX_DISCOVERED = 80
DISCOVERED_TTL_DAYS = 7


def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def save_json(path: Path, data):
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def check_url(url: str, session: requests.Session) -> str:
    if not url or not url.startswith("http"):
        return "unknown"
    try:
        r = session.head(url, allow_redirects=True, timeout=12)
        if r.status_code >= 400:
            r = session.get(url, allow_redirects=True, timeout=12, stream=True)
            r.close()
        if r.status_code < 400:
            return "ok"
        if r.status_code in (404, 410):
            return "stale"
        return "unknown"
    except requests.RequestException:
        return "unknown"


def infer_region(location: str) -> str:
    loc = (location or "").lower()
    for key, region in REGION_MAP.items():
        if key in loc:
            return region
    return "Europe"


def infer_type(title: str) -> str:
    t = title.lower()
    if "chief of staff" in t or "founding" in t or "founder" in t or "co-founder" in t:
        return "Founding"
    if "operations" in t or "bizops" in t or "strategy" in t or "program manager" in t:
        return "Ops"
    return "Product"


def dedupe_key(job: dict) -> str:
    co = re.sub(r"\s+", " ", job.get("co", "").lower()).strip()
    role = re.sub(r"\s+", " ", job.get("role", "").lower()).strip()
    return f"{co}|{role}"


def make_job(
    *,
    co: str,
    role: str,
    city: str,
    apply: str,
    source: str,
    note: str,
    visa: str = "check",
    region=None,
    careers: str = "",
) -> dict:
    return {
        "co": co[:80],
        "role": role[:120],
        "type": infer_type(role),
        "city": city[:80] or "See listing",
        "region": region or infer_region(city),
        "visa": visa,
        "salary": "",
        "careers": careers or apply,
        "apply": apply,
        "contact": "",
        "note": note,
        "source": source,
        "autoDiscovered": True,
        "curated": False,
    }


def fetch_arbeitnow_api(session: requests.Session) -> list[dict]:
    found = []
    for page in range(1, 6):
        try:
            r = session.get(
                f"https://www.arbeitnow.com/api/job-board-api?page={page}",
                timeout=20,
            )
            r.raise_for_status()
            data = r.json().get("data") or []
            if not data:
                break
            for item in data:
                title = item.get("title") or ""
                if not PM_KEYWORDS.search(title):
                    continue
                loc = item.get("location") or ""
                tags = " ".join(item.get("tags") or []).lower()
                visa = "sponsors" if "visa" in tags or "relocation" in tags else "likely"
                slug = item.get("slug") or ""
                url = f"https://www.arbeitnow.com/jobs/{slug}" if slug else item.get("url", "")
                company = (item.get("company_name") or title.split(" at ")[-1]).strip()
                role = title.split(" at ")[0].strip() if " at " in title else title
                found.append(
                    make_job(
                        co=company,
                        role=role,
                        city=loc,
                        apply=url,
                        source="arbeitnow",
                        note="Live posting from Arbeitnow. Verify visa/relocation before applying.",
                        visa=visa,
                    )
                )
        except requests.RequestException as e:
            print(f"Arbeitnow API page {page} skipped: {e}", file=sys.stderr)
            break
    return found


def fetch_arbeitnow_visa_html(session: requests.Session) -> list[dict]:
    url = "https://www.arbeitnow.com/visa-sponsorship-jobs"
    found = []
    try:
        r = session.get(url, timeout=20)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "html.parser")
        for a in soup.select('a[href*="/jobs/"]'):
            title = a.get_text(strip=True)
            if not title or not PM_KEYWORDS.search(title):
                continue
            href = a.get("href", "")
            if not href.startswith("http"):
                href = urljoin("https://www.arbeitnow.com", href)
            if "/jobs/companies" in href or "/jobs/locations" in href:
                continue
            parent = a.find_parent(["article", "li", "div"])
            loc = ""
            if parent:
                loc_el = parent.find(
                    string=re.compile(
                        r"Berlin|London|Amsterdam|Munich|Remote|Dubai|Paris|Zurich",
                        re.I,
                    )
                )
                if loc_el:
                    loc = str(loc_el).strip()
            company = (
                title.split(" at ")[-1].split(" - ")[0].strip()
                if " at " in title
                else title.split("–")[0].strip()
            )
            role = title.split(" at ")[0].strip() if " at " in title else title
            found.append(
                make_job(
                    co=company,
                    role=role,
                    city=loc or "Germany/EU",
                    apply=href,
                    source="arbeitnow-visa",
                    note="Auto-discovered from Arbeitnow visa-sponsorship board.",
                    visa="sponsors",
                )
            )
    except requests.RequestException as e:
        print(f"Arbeitnow visa HTML skipped: {e}", file=sys.stderr)
    return found


def fetch_remotive(session: requests.Session) -> list[dict]:
    found = []
    try:
        r = session.get("https://remotive.com/api/remote-jobs?limit=100", timeout=20)
        r.raise_for_status()
        for item in r.json().get("jobs") or []:
            title = item.get("title") or ""
            if not PM_KEYWORDS.search(title):
                continue
            loc = item.get("candidate_required_location") or "Remote"
            if loc and loc.lower() not in ("worldwide", "anywhere", "") and "india" in loc.lower():
                continue
            url = item.get("url") or ""
            company = item.get("company_name") or "Unknown"
            found.append(
                make_job(
                    co=company,
                    role=title,
                    city=loc or "Remote",
                    apply=url,
                    source="remotive",
                    note="Remote role from Remotive. Confirm visa/relocation policy.",
                    visa="check",
                    region="Remote",
                )
            )
    except requests.RequestException as e:
        print(f"Remotive fetch skipped: {e}", file=sys.stderr)
    return found


def fetch_yc_startups(session: requests.Session) -> list[dict]:
    found = []
    try:
        r = session.get(
            "https://www.workatastartup.com/jobs",
            headers={"Accept": "text/html", "User-Agent": BROWSER_UA},
            timeout=25,
        )
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "html.parser")
        for card in soup.select("a[href*='/jobs/']"):
            text = card.get_text(" ", strip=True)
            if not text or not PM_KEYWORDS.search(text):
                continue
            href = card.get("href", "")
            if not href.startswith("http"):
                href = urljoin("https://www.workatastartup.com", href)
            parts = re.split(r"\s+at\s+", text, maxsplit=1)
            role = parts[0].strip()
            company = parts[1].strip() if len(parts) > 1 else "YC Startup"
            found.append(
                make_job(
                    co=company[:80],
                    role=role[:120],
                    city="Remote / US",
                    apply=href,
                    source="yc",
                    note="YC Work at a Startup listing. Often founding-adjacent roles.",
                    visa="check",
                    region="Remote",
                )
            )
    except requests.RequestException as e:
        print(f"YC fetch skipped: {e}", file=sys.stderr)
    return found


def fetch_greenhouse(session: requests.Session) -> list[dict]:
    found = []
    for display, board, default_region in GREENHOUSE_BOARDS:
        try:
            r = session.get(
                f"https://boards-api.greenhouse.io/v1/boards/{board}/jobs",
                timeout=20,
            )
            r.raise_for_status()
            for item in r.json().get("jobs") or []:
                title = item.get("title") or ""
                if not PM_KEYWORDS.search(title):
                    continue
                loc_obj = item.get("location") or {}
                loc = loc_obj.get("name") if isinstance(loc_obj, dict) else str(loc_obj)
                url = item.get("absolute_url") or ""
                found.append(
                    make_job(
                        co=display,
                        role=title,
                        city=loc or default_region,
                        apply=url,
                        source="greenhouse",
                        note=f"Live Greenhouse posting at {display}. Check listing for visa/relocation.",
                        visa="likely" if display in ("Monzo", "Deliveroo", "Careem") else "check",
                        region=infer_region(loc or default_region),
                        careers=f"https://boards.greenhouse.io/{board}",
                    )
                )
        except requests.RequestException as e:
            print(f"Greenhouse {board} skipped: {e}", file=sys.stderr)
    return found


def discover_jobs(session: requests.Session) -> list[dict]:
    all_found = []
    fetchers = [
        fetch_arbeitnow_api,
        fetch_arbeitnow_visa_html,
        fetch_remotive,
        fetch_yc_startups,
        fetch_greenhouse,
    ]
    seen = set()
    for fn in fetchers:
        batch = fn(session)
        print(f"  {fn.__name__}: {len(batch)} roles", file=sys.stderr)
        for job in batch:
            key = dedupe_key(job)
            if key in seen:
                continue
            seen.add(key)
            all_found.append(job)
    return all_found[:MAX_DISCOVERED]


def load_seed_jobs() -> list[dict]:
    if SEED_FILE.exists():
        jobs = load_json(SEED_FILE)
    else:
        jobs = load_json(JOBS_FILE)
    for j in jobs:
        j["curated"] = True
        j.pop("autoDiscovered", None)
        j.pop("isNewToday", None)
        j.pop("source", None)
    return jobs


def prune_stale_discovered(jobs: list[dict], today: str) -> list[dict]:
    cutoff = datetime.strptime(today, "%Y-%m-%d") - timedelta(days=DISCOVERED_TTL_DAYS)
    kept = []
    for j in jobs:
        if j.get("curated"):
            kept.append(j)
            continue
        added = j.get("discoveredOn") or j.get("lastVerified") or today
        try:
            if datetime.strptime(added[:10], "%Y-%m-%d") >= cutoff:
                kept.append(j)
        except ValueError:
            kept.append(j)
    return kept


def write_csv(jobs: list[dict]):
    fieldnames = [
        "Company", "Role", "Type", "City", "Region", "Visa", "Salary (est.)",
        "Careers / Apply URL", "Known Contact", "Find Recruiter (LinkedIn search)",
        "Notes", "Status", "Date Reached Out", "Recruiter Name", "Response", "Next Step",
        "Link Status", "Last Verified",
    ]
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    with CSV_FILE.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        for j in jobs:
            co = re.sub(r"\s*\(.*?\)\s*", " ", j.get("co", "")).strip()
            role_q = "operations recruiter" if j.get("type") == "Ops" else "product recruiter"
            li = (
                "https://www.linkedin.com/search/results/people/?keywords="
                + requests.utils.quote(co + " " + role_q)
            )
            w.writerow({
                "Company": j.get("co", ""),
                "Role": j.get("role", ""),
                "Type": j.get("type", ""),
                "City": j.get("city", ""),
                "Region": j.get("region", ""),
                "Visa": VISA_LABEL.get(j.get("visa", ""), j.get("visa", "")),
                "Salary (est.)": j.get("salary", ""),
                "Careers / Apply URL": j.get("apply", j.get("careers", "")),
                "Known Contact": j.get("contact", ""),
                "Find Recruiter (LinkedIn search)": li,
                "Notes": j.get("note", ""),
                "Status": "",
                "Date Reached Out": "",
                "Recruiter Name": "",
                "Response": "",
                "Next Step": "",
                "Link Status": j.get("linkStatus", ""),
                "Last Verified": j.get("lastVerified", today),
            })


def main():
    session = requests.Session()
    session.headers.update({"User-Agent": BROWSER_UA})

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    now_iso = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")

    curated = load_seed_jobs()
    previous = load_json(JOBS_FILE) if JOBS_FILE.exists() else []
    prev_discovered = {
        dedupe_key(j): j for j in previous if not j.get("curated") and j.get("autoDiscovered")
    }

    print("Discovering live roles...", file=sys.stderr)
    discovered = discover_jobs(session)

    merged = []
    seen = set()
    new_today = 0

    for j in curated:
        key = dedupe_key(j)
        if key in seen:
            continue
        seen.add(key)
        j["linkStatus"] = check_url(j.get("apply") or j.get("careers", ""), session)
        j["lastVerified"] = today
        j["isNewToday"] = False
        merged.append(j)

    for j in discovered:
        key = dedupe_key(j)
        if key in seen:
            continue
        seen.add(key)
        if key in prev_discovered:
            j = {**prev_discovered[key], **j}
            j["isNewToday"] = False
        else:
            j["discoveredOn"] = today
            j["isNewToday"] = True
            new_today += 1
        j["linkStatus"] = check_url(j.get("apply") or j.get("careers", ""), session)
        j["lastVerified"] = today
        merged.append(j)

    merged = prune_stale_discovered(merged, today)

    meta = load_json(META_FILE) if META_FILE.exists() else {}
    meta.update({
        "lastRefreshed": now_iso,
        "refreshSchedule": "Daily at 6:00 AM IST",
        "totalJobs": len(merged),
        "curatedJobs": sum(1 for j in merged if j.get("curated")),
        "discoveredJobs": sum(1 for j in merged if not j.get("curated")),
        "newJobsToday": new_today,
        "siteUrl": "https://roohchills.github.io/global-opportunities/",
    })

    save_json(JOBS_FILE, merged)
    save_json(META_FILE, meta)
    if not SEED_FILE.exists():
        save_json(SEED_FILE, curated)
    write_csv(merged)

    print(
        f"Refresh complete: {len(merged)} jobs "
        f"({meta['curatedJobs']} curated + {meta['discoveredJobs']} discovered, "
        f"{new_today} new today)",
        file=sys.stderr,
    )


if __name__ == "__main__":
    main()
