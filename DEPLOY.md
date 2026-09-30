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
| `IM_GOOGLE_SERVICE_ACCOUNT_FILE` etc. | Optional Google Sheets export (see README) |

```bash
railway variables --service investor-match --set "ANTHROPIC_API_KEY=sk-ant-..."   # rotate / replace a key
railway variables --service investor-match --set "TEN_APP_PASSWORD=..."           # change the password
railway variables --service investor-match --set "RESEND_API_KEY=re_..."            # replace the Resend key
```

Changing a variable redeploys the service.

## Deploy an update

```bash
pytest                                     # all tests must pass
railway up --service investor-match --ci --no-gitignore   # build + deploy (includes built-in lists)
railway logs --service investor-match      # runtime logs
```

## Built-in investor lists

`data/investor_lists/` holds the trusted TEN Capital investor lists offered in the app. They are excluded from Git
(`.gitignore`) but deployed with the app (`.railwayignore` / `.dockerignore` re-include them), so always deploy with
`--no-gitignore`; without it the lists are left out and the app falls back to uploads. A deploy triggered from the
GitHub repo also has no lists. To add or replace a list, put the file in `data/investor_lists/`, run
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
