# Cloudflare Pages + GitHub — Auto-Updating Setup

This is the recommended path. Cloudflare hosts and serves the site
(fast CDN, custom domain), GitHub stores the files and runs a bot that
checks Makkah Newspaper every Friday morning. New articles appear on
the site automatically with zero manual work after initial setup.

## How the pieces fit together

```
   ┌──────────────────────────────────────────────────────┐
   │ GitHub repository                                    │
   │  ├─ index.html, articles.json, articles_ar.json      │
   │  └─ Friday 09:00 AST: bot scrapes Makkah Newspaper,  │
   │     updates JSON, commits to repo                    │
   └────────────────────────┬─────────────────────────────┘
                            │ (Cloudflare watches the repo)
                            ▼
   ┌──────────────────────────────────────────────────────┐
   │ Cloudflare Pages                                     │
   │  Auto-rebuilds the site within 30 seconds of any     │
   │  GitHub commit. Serves at your-name.pages.dev or     │
   │  your custom domain via Cloudflare's global CDN.     │
   └──────────────────────────────────────────────────────┘
```

## Files in this bundle

| File | Purpose |
|---|---|
| `index.html` | The website |
| `articles.json` | English article database (130) |
| `articles_ar.json` | Arabic article database (133) |
| `scrape_makkah.py` | The bot that checks for new articles |
| `.github/workflows/update-articles.yml` | Friday 09:00 AST schedule |

## Setup (10 minutes total)

### Part 1 — GitHub (5 minutes)

1. Go to **github.com** → sign up if you don't have an account.
2. Click **+** (top right) → **New repository**:
   - Name: `nabilalhakamy-publications` (or anything you like)
   - Public
   - Don't add README
   - **Create repository**
3. On the empty repo page, click **"uploading an existing file"** link.
4. Drag ALL files from this folder (including the `.github` folder) into
   the upload area.
   - If `.github` won't drag, upload the rest first, then click
     **"Add file" → "Create new file"**, type `.github/workflows/update-articles.yml`
     in the filename (the slashes create folders), paste the workflow
     contents, commit.
5. Scroll down → **Commit changes**.
6. **Settings** tab → **Actions** → **General** → scroll to
   **Workflow permissions** → select **"Read and write permissions"** → **Save**.
   (This lets the Friday bot commit updates.)

### Part 2 — Cloudflare (5 minutes)

1. Go to **dash.cloudflare.com** → sign up if needed (free tier works).
2. Left sidebar → **Workers & Pages** → **Create** → **Pages** tab →
   **Connect to Git**.
3. Authorize Cloudflare to access your GitHub account → select the repo
   you just created.
4. Build settings:
   - Framework preset: **None**
   - Build command: leave **blank**
   - Build output directory: leave as **`/`**
5. **Save and Deploy**.
6. After ~30 seconds, your site is live at:
   `https://<repo-name>.pages.dev`

### Part 3 — Test the Friday bot (1 minute)

1. Back to GitHub → your repo → **Actions** tab.
2. Click **"Update articles weekly"** in the left sidebar.
3. Right side → **"Run workflow"** dropdown → green **"Run workflow"** button.
4. Watch the run. Three possible outcomes:
   - **Green check + "No new articles"** → perfect, nothing was new this minute, automation works
   - **Green check + a new commit** → the bot found and added new articles already
   - **Red X** → the parser needs a tweak; copy the error log and ping me, fixable in one message

After this manual test passes, **the workflow runs every Friday at 09:00
Saudi time forever.** New Makkah articles appear on your Cloudflare site
within a minute of the bot finding them.

## Custom domain (optional, ~5 minutes)

If you own a domain (e.g., `nabilalhakamy.com`):

1. Cloudflare Pages → your project → **Custom domains** → **Set up a custom domain**.
2. Type your domain → follow the DNS steps shown.
3. SSL is automatic and free.

## What if I want to change the schedule?

Edit `.github/workflows/update-articles.yml` in your repo. The line
`cron: "0 6 * * 5"` means "minute 0, hour 6, Friday, UTC". Some examples:

- Every Friday morning Saudi time: `0 6 * * 5` (current — 09:00 AST)
- Every day at midnight Saudi: `0 21 * * *` (21:00 UTC = 00:00 AST next day)
- Twice a week (Mon and Fri): `0 6 * * 1,5`

Commit the change and Cloudflare auto-redeploys. The new schedule applies
immediately.

## Troubleshooting

**Cloudflare deploy failed.** Check the deployment log in the Cloudflare
dashboard. Most common cause: build settings filled in by accident — they
should all be blank/default for a static site.

**Friday workflow ran but nothing changed on the site.** Two checks:
1. Did Cloudflare deploy? (Cloudflare Pages → your project → check the
   latest deployment timestamp)
2. Did the bot find new articles? (GitHub → Actions → click the latest run
   → check the log)

**I want to manually add an article without waiting for Friday.** Edit
`articles.json` (or `articles_ar.json`) directly in GitHub's web UI, add
your entry at the top of the array, commit. Cloudflare auto-deploys.
