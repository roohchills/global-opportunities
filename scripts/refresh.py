#!/usr/bin/env python3
"""Daily refresh: verify links, discover new visa-sponsor PM/ops roles, update meta + CSV."""

import csv
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
JOBS_FILE = DATA / "jobs.json"
HELPERS_FILE = DATA / "helpers.json"
META_FILE = DATA / "meta.json"
CSV_FILE = ROOT / "jobs.csv"

PM_KEYWORDS = re.compile(
    r"product\s*manager|product\s*owner|chief\s*of\s*staff|founding\s*pm|"
    r"product\s*lead|group\s*pm|operations\s*manager|bizops|biz\s*ops|"
    r"program\s*manager|strategy\s*&?\s*ops",
    re.I,
)

REGION_MAP = {
    "london": "London",
    "uk": "London",
    "united kingdom": "London",
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
    "dubai": "Dubai",
    "uae": "Dubai",
    "san francisco": "US",
    "seattle": "US",
    "mountain view": "US",
    "menlo park": "US",
    "united states": "US",
    "remote": "Remote",
}

VISA_LABEL = {
    "sponsors": "Sponsors visa",
    "likely": "Likely / check",
    "check": "Confirm w/ company",
    "eu": "EU permit needed",
}


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
    if "chief of staff" in t or "founding" in t or "founder" in t:
        return "Founding"
    if "operations" in t or "bizops" in t or "strategy" in t:
        return "Ops"
    return "Product"


def job_key(job: dict) -> str:
    return f"{job.get('co','').lower()}|{job.get('role','').lower()}|{job.get('apply','').lower()}"


def fetch_arbeitnow(session: requests.Session) -> list[dict]:
    """Discover PM/ops roles with visa sponsorship from Arbeitnow."""
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
            # skip nav links
            if "/jobs/companies" in href or "/jobs/locations" in href:
                continue
            parent = a.find_parent(["article", "li", "div"])
            loc = ""
            if parent:
                loc_el = parent.find(string=re.compile(r"Berlin|London|Amsterdam|Munich|Remote", re.I))
                if loc_el:
                    loc = str(loc_el).strip()
            company = title.split(" at ")[-1].split(" - ")[0].strip() if " at " in title else title.split("–")[0].strip()
            role = title
            if " at " in title:
                role = title.split(" at ")[0].strip()
            found.append({
                "co": company[:80],
                "role": role[:120],
                "type": infer_type(title),
                "city": loc or "Germany/EU",
                "region": infer_region(loc or "germany"),
                "visa": "sponsors",
                "salary": "",
                "careers": href,
                "apply": href,
                "contact": "",
                "note": "Auto-discovered from Arbeitnow visa-sponsorship board. Verify listing before applying.",
                "autoDiscovered": True,
                "source": "arbeitnow",
            })
    except requests.RequestException as e:
        print(f"Arbeitnow fetch skipped: {e}", file=sys.stderr)
    return found


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
            li = f"https://www.linkedin.com/search/results/people/?keywords={requests.utils.quote(co + ' ' + role_q)}"
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
    session.headers.update({
        "User-Agent": "RuchilOpportunityBoard/1.0 (daily refresh; contact: personal job board)",
    })

    jobs = load_json(JOBS_FILE)
    meta = load_json(META_FILE) if META_FILE.exists() else {}
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    now_iso = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")

    # Verify existing apply links
    for j in jobs:
        status = check_url(j.get("apply") or j.get("careers", ""), session)
        j["linkStatus"] = status
        j["lastVerified"] = today

    # Merge newly discovered roles
    existing = {job_key(j) for j in jobs}
    new_count = 0
    for candidate in fetch_arbeitnow(session):
        k = job_key(candidate)
        if k not in existing:
            candidate["linkStatus"] = check_url(candidate.get("apply", ""), session)
            candidate["lastVerified"] = today
            jobs.append(candidate)
            existing.add(k)
            new_count += 1

    meta.update({
        "lastRefreshed": now_iso,
        "refreshSchedule": "Daily at 6:00 AM IST",
        "totalJobs": len(jobs),
        "newJobsToday": new_count,
        "siteUrl": meta.get("siteUrl", "https://helpful-platypus-9b3541.netlify.app/"),
    })

    save_json(JOBS_FILE, jobs)
    save_json(META_FILE, meta)
    write_csv(jobs)

    print(f"Refresh complete: {len(jobs)} jobs ({new_count} new), lastRefreshed={now_iso}")


if __name__ == "__main__":
    main()
