# Daily auto-refresh setup (free)

Your site at **https://helpful-platypus-9b3541.netlify.app/** can refresh **once a day at 6:00 AM IST** automatically.

## What happens daily

1. A **GitHub Action** runs at 6:00 AM IST (00:30 UTC)
2. `scripts/refresh.py`:
   - Re-checks every job link (marks stale ones ⚠️)
   - Discovers new PM/ops roles from [Arbeitnow visa-sponsor board](https://www.arbeitnow.com/visa-sponsorship-jobs)
   - Updates `data/jobs.json`, `data/meta.json`, and `jobs.csv`
3. Changes are **committed to GitHub** and **deployed to Netlify**
4. The site shows **🔄 Last refreshed: …** in the header

---

## One-time setup (~10 minutes)

### Step 1 — Create a GitHub repo

1. Go to [github.com/new](https://github.com/new)
2. Name it e.g. `global-opportunities` (public repo is fine — no secrets in the code)
3. Do **not** add README/license (we already have files)

In Terminal, from this folder:

```bash
cd "/Users/ruchilsharma/Desktop/Different Opportunities"
git init
git add .
git commit -m "Initial job board with daily refresh"
git branch -M main
git remote add origin https://github.com/YOUR_USERNAME/global-opportunities.git
git push -u origin main
```

### Step 2 — Get Netlify credentials

**Site ID**

1. [app.netlify.com](https://app.netlify.com/) → your site **helpful-platypus-9b3541**
2. **Site configuration → General → Site details → Site ID** (copy it)

**Auth token**

1. **User settings → Applications → Personal access tokens → New access token**
2. Name it `daily-refresh`, copy the token (shown once)

### Step 3 — Add GitHub secrets

Repo → **Settings → Secrets and variables → Actions → New repository secret**

| Secret name | Value |
|-------------|--------|
| `NETLIFY_AUTH_TOKEN` | Token from Step 2 |
| `NETLIFY_SITE_ID` | Site ID from Step 2 |

### Step 4 — Redeploy once with the new structure

Drag the updated folder to [Netlify Drop](https://app.netlify.com/drop) **or** run locally:

```bash
npx netlify-cli deploy --prod --dir="."
```

(First time: `npx netlify-cli login`)

**Important:** The new site loads jobs from `/data/jobs.json`. You must deploy the **`data/` folder** too — not just `index.html`.

### Step 5 — Test the refresh manually

GitHub repo → **Actions** → **Daily site refresh** → **Run workflow**

After ~2 minutes:

- Check **Actions** tab for a green checkmark
- Open your site — header should show a new **Last refreshed** time
- Netlify **Deploys** tab should show a new deploy

---

## Schedule

| When | What |
|------|------|
| **6:00 AM IST** every day | Automatic refresh + deploy |
| Any time | **Actions → Run workflow** for manual refresh |

To change the time, edit `.github/workflows/daily-refresh.yml` cron line:

```yaml
- cron: "30 0 * * *"   # 6:00 AM IST
```

Use [crontab.guru](https://crontab.guru/) to pick another UTC time.

---

## Cost

| Service | Cost |
|---------|------|
| Netlify | **Free** (static hosting) |
| GitHub Actions | **Free** (2,000 min/month on free plan — this job uses ~2 min/day) |

**Total: $0/month**

---

## Troubleshooting

**Site shows “Could not load job data”**

- The `data/` folder wasn’t deployed. Redeploy the full folder including `data/jobs.json`.

**GitHub Action fails on “Deploy to Netlify”**

- Check `NETLIFY_AUTH_TOKEN` and `NETLIFY_SITE_ID` secrets are set correctly.

**No new jobs appearing**

- The script only adds PM/ops/founding roles from Arbeitnow that aren’t already listed. Curated roles stay; new ones get a **✨ New today** badge.

**Want to add more sources later**

- Edit `scripts/refresh.py` and add fetchers for other boards (Relocate.me, Lenny's, etc.).
