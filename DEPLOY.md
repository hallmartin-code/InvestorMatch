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

## Investor lists (Files API–connected only)

`data/investor_lists/` holds the trusted TEN Capital investor lists offered in the app. They are excluded from Git
(`.gitignore`) but deployed with the app (`.railwayignore` / `.dockerignore` re-include them), so always deploy with
`--no-gitignore`; without it the lists are left out and the app falls back to uploads. A deploy triggered from the
Only lists connected through the Files API are offered in the app (no investor-list uploads). To add or replace a list, put the file in `data/investor_lists/`, run
`python -m app.services.files_api` (uploads it to the Anthropic Files API and records its file ID in
`data/investor_lists/files_api.json`), then redeploy. File IDs work only with the same Anthropic organization's
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
