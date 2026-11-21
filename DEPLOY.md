# Deploying to Railway

The app runs as one Streamlit web service built from the `Dockerfile` (Python 3.12, OCR libraries and
LibreOffice for legacy `.ppt`). Railway injects `$PORT` and the secrets at runtime; **no credential is
baked into the image or stored in the repository** (`.env` is excluded by `.gitignore`, `.railwayignore`
and `.dockerignore`).

Current deployment: project **investor-match**, service **investor-match**,
<https://investor-match-production.up.railway.app> (health: `/_stcore/health`).

## Variables

| Variable | Value |
|---|---|
| `ANTHROPIC_API_KEY` | Key from <https://console.anthropic.com/settings/keys> |
| `IM_LLM_ENABLED` | `true` |
| `IM_LLM_MODEL` | `claude-opus-5-5` |
| `TEN_APP_PASSWORD` | Optional access password shown before the app loads. Currently **not set** (the app is public); anyone with the URL can run analyses on your API keys, so keep spend limits on the keys. |
| `RESEND_API_KEY` | Resend key from <https://resend.com/api-keys> (sending access) |
| `IM_NOTIFY_TO` | `Info@tencapital.group` (comma-separated for several) |
| `IM_NOTIFY_FROM` | Default `TEN Capital Investor Match <reports@tencapital.group>` — domain must be verified in Resend |
| `IM_GOOGLE_SERVICE_ACCOUNT_JSON` | Google service-account key **content** (JSON) for Sheets export — set from the key file via stdin, never on the command line |
| `IM_GOOGLE_DRIVE_FOLDER_ID` | `0AEWCMgOR3jJtUk9PVA` — the *TEN Capital AI Documents* Shared Drive (service accounts cannot create files in My Drive) |
| `IM_GOOGLE_SHARE_WITH` | `hallmartin@tencapital.group` |

```bash
railway variables --service investor-match --set "ANTHROPIC_API_KEY=sk-ant-..."   # rotate / replace a key
railway variables --service investor-match --set "TEN_APP_PASSWORD=..."           # change the password
railway variables --service investor-match --set "RESEND_API_KEY=re_..."            # replace the Resend key
railway variables --service investor-match --set-from-stdin IM_GOOGLE_SERVICE_ACCOUNT_JSON < im-sheets.json   # replace the Google key
```

Changing a variable redeploys the service.

## Services

| Project / service | URL | Source |
|---|---|---|
| `investor-match` / `investor-match` | <https://investor-match-production.up.railway.app> | CLI uploads from this folder |
| `precious-celebration` / `web` | <https://web-production-a9900.up.railway.app> | CLI uploads from this folder (GitHub auto-deploy disconnected on 2026-09-30, because GitHub builds cannot include the built-in lists) |

Pushing to the GitHub repo no longer deploys anything. To update `precious-celebration`:

```bash
railway up --project e0c7aff5-77d8-4510-8383-121abb005775 --environment production --service web --ci --no-gitignore
```

## Deploy an update

```bash
pytest                                     # all tests must pass
railway up --service investor-match --ci --no-gitignore   # build + deploy (includes built-in lists)
railway logs --service investor-match      # runtime logs
```

## Run history (Postgres)

Every completed run is saved with its PDF and workbook, listed under **Run history** on the first screen
(download again or delete). It is on whenever `DATABASE_URL` is set; without it the app works as before.

One-time setup (needs `railway login`):

```sh
railway add --database postgres                      # adds a "Postgres" service to the project
railway variables --service investor-match --set 'DATABASE_URL=${{Postgres.DATABASE_URL}}'
railway variables --service web --set 'DATABASE_URL=${{Postgres.DATABASE_URL}}'
```

The `${{Postgres.DATABASE_URL}}` reference keeps the password inside Railway (never in the repo). The app
creates its table (`im_runs`) on first use. Re-running the same analysis updates its row; "Finalize & email"
records when it was emailed. `IM_HISTORY_MAX_RUNS` (default 500, 0 = unlimited) deletes the oldest runs
beyond that count — a run is roughly 0.1 MB (PDF) + up to ~8 MB (workbook), so watch the Postgres volume.
If the database is down, matching still works and the panel says history is unavailable.

## Investor lists (built-in only)

`data/investor_lists/` holds the trusted TEN Capital investor lists offered in the app. They are excluded from Git
(`.gitignore`) but deployed with the app (`.railwayignore` / `.dockerignore` re-include them), so always deploy with
`--no-gitignore`; without it the lists are left out and the app falls back to uploads. A deploy triggered from the
Every list in `data/investor_lists/` is offered in the app (no investor-list uploads). To add or replace a list, put
the file in `data/investor_lists/` and redeploy. Give each list a display name and status in
`data/investor_lists/catalog.json` — `recommended` (the official list, shown first with a badge and pre-selected),
`current`, or `archived` (grouped under "Archived versions") — plus a one-line note, its `date` and, until it is
synced, its `contacts` count. When `ANTHROPIC_API_KEY` works, also run `python -m app.services.files_api` (uploads the
list to the Anthropic Files API and records its file ID and investor count in `data/investor_lists/files_api.json`);
only Claude's review of held contacts needs the upload, and it skips lists without one. File IDs work only with the same Anthropic organization's
API key; if you change `ANTHROPIC_API_KEY` to a key from another organization, run the sync again.

## Cost and safety

* Each analysis makes **one** Claude call on the deck text (Opus 5.5, effort `medium`); screening, scoring
  and document generation run in Python and cost nothing.
* Set a monthly spend limit on the API key in the Claude Console. The app currently has no password; set `TEN_APP_PASSWORD` to require one.
* Treat any key that has appeared in chat, email or screenshots as exposed: create a new key, set it with
  the command above, and delete the old one in the Console.

## First-time setup (already done for this project)

```bash
railway init --name investor-match
railway add --service investor-match
railway variables --service investor-match --set ...   # as above
railway up --service investor-match --ci
railway domain --service investor-match
```
