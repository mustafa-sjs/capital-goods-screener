# Deployment — exact steps (all free tiers)

Everything below is copy-paste level. Total time ≈ 20 minutes. Verify each
service's current free-tier terms at signup — do not add a payment method
anywhere; every step works without one.

## 1. GitHub (code + scheduling) — ~5 min

1. Sign in at github.com → **New repository**.
2. Name: `capital-goods-screener` · visibility: **Private** · no README (we have one). Create.
3. In Terminal:
   ```bash
   cd /Users/Mustafa/capital-goods-dashboard
   git remote add origin https://github.com/<YOUR_USERNAME>/capital-goods-screener.git
   git push -u origin main
   ```
   (GitHub will prompt for login; use the browser flow.)
4. Repo → **Settings → Actions → General**: confirm "Allow all actions" and
   *Workflow permissions = Read and write* (the daily refresh commits data back).
5. Free-tier note: private-repo Actions include 2,000 min/month at the time
   of writing (verify at github.com/pricing). This platform uses ~150.

## 2. Supabase (production database) — ~5 min

1. supabase.com → Sign up (GitHub login is easiest) → **New project**.
2. Name `capital-goods` · **Free** plan · pick an EU region · set a strong
   database password (save it).
3. Project → **Connect** (top bar) → *Connection string* → **URI**, mode
   **Session pooler**. Copy it; replace `[YOUR-PASSWORD]` with your password.
   This is your `DATABASE_URL`.
4. Migrate the data (from your Mac):
   ```bash
   ./.venv/bin/python scripts/migrate_database.py --db-url 'postgresql://...'
   ```
   It creates the schema, copies every table from local DuckDB, and prints
   row-count comparisons — confirm they match.
5. GitHub repo → Settings → **Secrets and variables → Actions → New repository
   secret**: name `DATABASE_URL`, value = the URI. 
6. Free-tier notes (verify at supabase.com/pricing): ~500 MB database, and
   **free projects pause after ~1 week of inactivity** — the daily Actions
   refresh writing to it keeps it awake on weekdays, which is sufficient.

## 3. Streamlit Community Cloud (remote app) — ~5 min

1. share.streamlit.io → **Sign in with GitHub** → authorize (grant access to
   the private repo when asked).
2. **Create app** → repo `capital-goods-screener` · branch `main` · main file
   `app/Home.py`.
3. **Advanced settings → Secrets**, paste:
   ```toml
   DATABASE_URL = "postgresql://...same URI..."
   ```
4. Deploy. The URL is stable (`https://<something>.streamlit.app`).
5. Privacy: the app is only listed for you; on the free Community tier make
   it explicitly private via app **Settings → Sharing → viewers = invited
   emails only** (invite your own email). Verify this option exists on the
   current tier — if sharing controls are ever removed from the free tier,
   the fallback documented in `docs/architecture.md` is: keep the app
   local-only (`streamlit run`) and rely on the repo+Supabase for persistence.
   Do NOT move to paid hosting automatically.

## 4. First production run — ~2 min

GitHub repo → **Actions** → `daily-refresh` → **Run workflow**. Watch it go
green, then open the Streamlit URL: Home shows the new refresh, Admin shows
`Supabase Postgres` and the run record.

## What is deliberately NOT automated

- FactIQ fundamentals: interactive MCP auth only → refresh via a Claude Code
  session in this project (say "run the quarterly FactIQ refresh").
- The local launchd agent (`com.mustafa.capitalgoods.refresh`) still runs
  weekdays 22:12 as a belt-and-braces local refresh; it is idempotent
  alongside the cloud one. Disable it if you prefer:
  `launchctl unload ~/Library/LaunchAgents/com.mustafa.capitalgoods.refresh.plist`
