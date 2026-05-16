# Automated Instagram Poster — Technical Specification

## 1. Purpose

A scheduled, multi-channel Instagram content publisher. Posts one image (or, in future iterations, Reels/carousels) per channel per day from a queue, using Instagram's Graph API. Designed to run as scheduled jobs in GitHub Actions, with media stored in this same private GitHub repository.

This document is the source of truth for implementation. Build to this spec.

---

## 2. Functional requirements

1. **Per-channel scheduled posting**: each channel posts on its own cron schedule, independent of other channels.
2. **Folder-driven queue**: posts are picked from a per-channel `queue/` folder by alphabetical order (oldest-first by filename).
3. **Caption resolution**: each post's caption comes from a per-channel `captions.json`, with a `default` fallback.
4. **State tracking**: after a successful post, the file is moved from `queue/` to `posted/`, and a record is appended to `posted.json` with timestamp + Instagram media ID.
5. **Idempotency**: a re-run within the same day must not produce a duplicate post. The first successful publish "claims" the post; the file move + commit acts as the lock.
6. **Failure isolation**: if one channel's post fails, other channels' workflows must continue to run on schedule unaffected.
7. **Token refresh**: long-lived Instagram tokens (60-day TTL) must be refreshed automatically before expiry via a separate scheduled job.
8. **Multi-channel scaling**: adding a new channel requires only (a) a new `channels/<id>/` folder with config and content, (b) new GitHub Secrets, (c) a new workflow file. No code changes.

---

## 3. Architecture

### 3.1 Runtime

GitHub Actions, free-tier. Each channel has its own workflow file that runs on a cron schedule. The workflow:

1. Checks out the repo
2. Installs Python dependencies
3. Runs `python src/post.py --channel <channel-id>`
4. The script may push commits back (for the queue → posted move and posted.json update)

### 3.2 Storage

The same private GitHub repo holds both the code and the media. Images live under `channels/<channel-id>/queue/`. To serve them to Meta's API (which requires a public URL), the script uses GitHub's Contents API to generate temporary signed download URLs:

```
GET https://api.github.com/repos/{owner}/{repo}/contents/{path}
Authorization: token {GITHUB_TOKEN}
Accept: application/vnd.github.v3+json
```

The response JSON contains a `download_url` field — a `raw.githubusercontent.com` URL with an embedded short-lived token. This URL is what gets passed to Meta's `image_url` parameter. Meta typically fetches the file within seconds during container creation, well within the URL's ~5-minute validity.

### 3.3 Authentication

| Credential                       | Source                                              | Used for                                      |
|----------------------------------|-----------------------------------------------------|-----------------------------------------------|
| `GITHUB_TOKEN`                   | Auto-injected by Actions, with `contents: write`    | GitHub Contents API + git push back           |
| `<PREFIX>_IG_ACCESS_TOKEN`       | GitHub Secret, per channel                          | Instagram Graph API publish calls             |
| `<PREFIX>_IG_USER_ID`            | GitHub Secret, per channel                          | Instagram User ID for `/media` endpoint       |
| `<PREFIX>_IG_APP_ID`             | GitHub Secret, per channel                          | Token refresh (currently unused for publish)  |
| `<PREFIX>_IG_APP_SECRET`         | GitHub Secret, per channel                          | Token refresh                                 |

`<PREFIX>` is defined per channel in its `config.yml` (see § 5.2). Different channels can share or differ in their `IG_APP_ID` / `IG_APP_SECRET` — the script does not assume one Meta app.

---

## 4. Repository layout

```
automated-instagram-poster/
├── .github/
│   └── workflows/
│       ├── post-drifted-lines.yml         # one per channel
│       ├── refresh-tokens.yml             # weekly token refresh, all channels
│       └── ci.yml                         # optional: lint/test on PR
├── channels/
│   └── drifted-lines/
│       ├── config.yml                     # channel-specific config
│       ├── captions.json                  # caption map: filename → text
│       ├── posted.json                    # log of successful posts
│       ├── queue/                         # media awaiting posting
│       │   ├── 001.jpg
│       │   ├── 002.jpg
│       │   └── ...
│       └── posted/                        # archive of posted media
├── src/
│   ├── __init__.py
│   ├── post.py                            # main entry point
│   ├── instagram.py                       # Instagram Graph API client
│   ├── github_storage.py                  # GitHub Contents API + git ops
│   ├── config.py                          # channel config + env loader
│   ├── content.py                         # picks next file, resolves captions
│   ├── token_refresh.py                   # entry point for refresh workflow
│   └── exceptions.py                      # custom exception classes
├── tests/
│   ├── test_content.py
│   ├── test_instagram.py
│   └── fixtures/
├── requirements.txt
├── spec.md                                # this file
├── README.md                              # human-facing docs
└── .gitignore                             # must include .env, __pycache__, etc.
```

### 4.1 Adding a new channel

1. Create `channels/<new-channel-id>/` with `config.yml`, empty `captions.json` (`{"default": "..."}`), empty `posted.json` (`[]`), empty `queue/`, empty `posted/`.
2. Add the four GitHub Secrets prefixed per `secret_prefix` in config.
3. Copy `post-drifted-lines.yml` to `post-<new-channel-id>.yml` and edit channel name + cron.

No code changes required.

---

## 5. Configuration

### 5.1 Channel config schema (`channels/<id>/config.yml`)

```yaml
channel_id: drifted-lines              # must match folder name; used in CLI args
display_name: "Drifted Lines"          # for logs and notifications
secret_prefix: DRIFTED_LINES           # prefix for env vars; uppercase, underscores

content:
  media_types: [image]                 # MVP: just image. Future: image, reel, carousel
  default_caption_key: default         # key in captions.json used as fallback
  
posting:
  enabled: true                        # script no-ops if false (kill switch)
  min_queue_warning: 14                # log warning if fewer than N items in queue
```

### 5.2 Secret naming

For each channel, four secrets are defined in GitHub Secrets, named as:

```
{SECRET_PREFIX}_IG_ACCESS_TOKEN
{SECRET_PREFIX}_IG_USER_ID
{SECRET_PREFIX}_IG_APP_ID
{SECRET_PREFIX}_IG_APP_SECRET
```

Example for `secret_prefix: DRIFTED_LINES`:

```
DRIFTED_LINES_IG_ACCESS_TOKEN
DRIFTED_LINES_IG_USER_ID
DRIFTED_LINES_IG_APP_ID
DRIFTED_LINES_IG_APP_SECRET
```

The script resolves these at runtime via `os.environ[f"{prefix}_IG_ACCESS_TOKEN"]` etc. Missing secrets must raise a clear, actionable error before any API calls are made.

### 5.3 captions.json schema

```json
{
  "default": "Fallback caption with hashtags.\n\n#tag1 #tag2",
  "001.jpg": "Custom caption for image 001.\n\n#tag1 #tag2",
  "002.jpg": "Custom caption for image 002.\n\n#tag1 #tag2"
}
```

- `default` is required.
- Per-file entries are optional; missing entries fall back to `default`.
- Keys must match filenames in `queue/` exactly (case-sensitive).
- Captions can include `\n` for line breaks; Instagram preserves them.

### 5.4 posted.json schema

Append-only array, ordered chronologically:

```json
[
  {
    "filename": "001.jpg",
    "ig_media_id": "17912345678901234",
    "caption_used": "Some days you're the lighthouse...",
    "posted_at_utc": "2026-05-10T13:00:42Z",
    "permalink": "https://www.instagram.com/p/Cxyz.../"
  }
]
```

---

## 6. Core script: `src/post.py`

### 6.1 Invocation

```bash
python src/post.py --channel <channel-id> [--dry-run]
```

**Arguments**:
- `--channel` (required): channel ID matching a folder in `channels/`.
- `--dry-run` (optional): runs all logic except the publish API call and the git push. Logs what it *would* do.

**Exit codes**:
- `0`: success (post published, or no-op due to disabled/empty queue).
- `1`: configuration error (missing config, missing secrets).
- `2`: API error (Instagram or GitHub).
- `3`: unexpected error.

### 6.2 Execution flow

```
1.  Parse args. Load channels/<channel>/config.yml.
2.  If posting.enabled is false → log and exit 0.
3.  Resolve secrets from environment using config.secret_prefix.
    Fail fast (exit 1) if any required secret is missing.
4.  List files in channels/<channel>/queue/ via local filesystem.
    Filter to supported extensions (.jpg, .jpeg, .png for image type).
    Sort alphabetically. Pick the first file.
    If queue is empty → log warning and exit 0.
    If len(queue) < config.posting.min_queue_warning → log warning, continue.
5.  Load channels/<channel>/captions.json.
    Resolve caption: captions[filename] if present, else captions[default_caption_key].
6.  If --dry-run: log resolved values and exit 0.
7.  Get signed download URL for the image via GitHub Contents API.
8.  Call Instagram create-container endpoint with image_url + caption.
    Receive container_id.
9.  (Image only — skip status polling. For Reels in future, poll status_code until FINISHED.)
10. Call Instagram media_publish endpoint with creation_id=container_id.
    Receive ig_media_id.
11. (Optional) Call /{ig_media_id}?fields=permalink to capture the post URL.
12. Append entry to channels/<channel>/posted.json.
13. Move file: queue/<filename> → posted/<filename> via git mv.
14. Commit and push: "post: drifted-lines 001.jpg → 17912345678901234".
15. Log success and exit 0.
```

### 6.3 Logging

Use Python's `logging` module. INFO level by default, DEBUG when env var `LOG_LEVEL=DEBUG` is set. Every log line should include the channel ID. Example:

```
2026-05-10 13:00:00 INFO  [drifted-lines] Picked 001.jpg from queue (99 items remaining)
2026-05-10 13:00:01 INFO  [drifted-lines] Resolved caption (length=87, source=custom)
2026-05-10 13:00:01 INFO  [drifted-lines] Generated signed download URL (expires in ~5 min)
2026-05-10 13:00:02 INFO  [drifted-lines] Container created: 17841201234567890
2026-05-10 13:00:03 INFO  [drifted-lines] Published: ig_media_id=17912345678901234
2026-05-10 13:00:04 INFO  [drifted-lines] Permalink: https://instagram.com/p/Cxyz...
2026-05-10 13:00:05 INFO  [drifted-lines] Moved 001.jpg → posted/, committed, pushed
```

---

## 7. Module specifications

### 7.1 `src/instagram.py`

A thin wrapper around the Instagram Graph API. All requests use the `graph.instagram.com` host (Instagram Login flow).

**Class: `InstagramClient`**

```python
class InstagramClient:
    def __init__(self, ig_user_id: str, access_token: str, api_version: str = "v21.0"):
        ...
    
    def create_image_container(self, image_url: str, caption: str) -> str:
        """POST /{ig_user_id}/media with media_type=IMAGE.
        Returns container_id."""
    
    def publish_container(self, container_id: str) -> str:
        """POST /{ig_user_id}/media_publish with creation_id=container_id.
        Returns ig_media_id."""
    
    def get_permalink(self, ig_media_id: str) -> str | None:
        """GET /{ig_media_id}?fields=permalink. Returns URL or None on failure
        (non-fatal — failure here should NOT roll back the post)."""
    
    # Future:
    def create_reel_container(self, video_url: str, caption: str, 
                              cover_url: str | None = None,
                              share_to_feed: bool = True) -> str:
        ...
    
    def poll_container_status(self, container_id: str, 
                              max_wait_seconds: int = 300, 
                              poll_interval: int = 5) -> str:
        """Used for Reels. Polls GET /{container_id}?fields=status_code 
        until status_code == FINISHED, IN_PROGRESS errors out, EXPIRED, ERROR.
        Returns final status."""
```

**Error handling**: every API call must check HTTP status. On non-2xx, raise `InstagramAPIError` (custom, defined in `exceptions.py`) with the response body included in the message. Specific cases:

- `(#190)` → `InstagramTokenError` (subclass), suggests refresh.
- `(#10)` permission denied → `InstagramPermissionError`, suggests re-checking scopes.
- `(#4)` rate limit → `InstagramRateLimitError`, with `Retry-After` if present.
- Any other 4xx/5xx → generic `InstagramAPIError`.

**API endpoints reference** (Instagram Login flow, host = `graph.instagram.com`, API version `v21.0`):

```
# Create image container
POST https://graph.instagram.com/v21.0/{ig_user_id}/media
  Body (form-urlencoded or JSON):
    image_url: <signed github URL>
    caption: <text>
    access_token: <token>
  Response: { "id": "<container_id>" }

# Publish
POST https://graph.instagram.com/v21.0/{ig_user_id}/media_publish
  Body:
    creation_id: <container_id>
    access_token: <token>
  Response: { "id": "<ig_media_id>" }

# Get permalink
GET https://graph.instagram.com/v21.0/{ig_media_id}?fields=permalink&access_token=<token>
  Response: { "id": "...", "permalink": "https://www.instagram.com/p/..." }

# Refresh token
GET https://graph.instagram.com/refresh_access_token?grant_type=ig_refresh_token&access_token=<long_lived_token>
  Response: { "access_token": "<new_token>", "token_type": "bearer", "expires_in": 5184000 }
```

### 7.2 `src/github_storage.py`

**Function: `get_signed_download_url(repo: str, path: str, github_token: str) -> str`**

Calls GitHub Contents API and returns the `download_url` field. Raises `GitHubAPIError` on failure.

`repo` is in `owner/repo` form. `path` is the path within the repo (no leading slash).

**Function: `git_move_and_commit(channel_id: str, filename: str, ig_media_id: str) -> None`**

Performs:
1. `git mv channels/<channel_id>/queue/<filename> channels/<channel_id>/posted/<filename>`
2. `git add channels/<channel_id>/posted.json` (assumes caller has already updated the file)
3. `git commit -m "post: <channel_id> <filename> → <ig_media_id>"`
4. `git push`

Uses `subprocess` with `check=True`. Configures git user.email and user.name from env vars `GIT_USER_EMAIL` and `GIT_USER_NAME` (with sensible defaults like `github-actions[bot]@users.noreply.github.com`).

**Function: `append_to_posted_log(channel_id: str, entry: dict) -> None`**

Reads `channels/<channel_id>/posted.json`, appends the entry, writes back. Atomic where possible.

### 7.3 `src/config.py`

**Function: `load_channel_config(channel_id: str) -> ChannelConfig`**

Loads `channels/<channel_id>/config.yml` into a typed dataclass (`ChannelConfig`). Validates required fields. Raises `ConfigError` on missing/malformed config.

**Function: `load_secrets(secret_prefix: str) -> ChannelSecrets`**

Reads four env vars based on prefix. Returns a typed dataclass. Raises `ConfigError` listing all missing secrets (don't fail on the first one — collect them so the user can fix all at once).

### 7.4 `src/content.py`

**Function: `pick_next_image(channel_id: str) -> str | None`**

Lists files in `channels/<channel_id>/queue/`, filters to image extensions, sorts alphabetically. Returns the filename (not full path) of the first item, or `None` if the queue is empty.

**Function: `resolve_caption(channel_id: str, filename: str, default_key: str) -> tuple[str, str]`**

Loads `channels/<channel_id>/captions.json`. Returns `(caption_text, source)` where `source` is `"custom"` if the filename had a specific entry, else `"default"`.

### 7.5 `src/token_refresh.py`

Standalone entry point for the weekly refresh workflow.

```bash
python src/token_refresh.py --channel <channel-id>
```

Calls Instagram's refresh endpoint, gets a new token. **Updates the GitHub Secret** via the GitHub API (uses libsodium for encryption — see GitHub docs on creating/updating secrets via API). The workflow's `GITHUB_TOKEN` needs `secrets: write` permission, which requires using a fine-grained PAT stored as a separate secret (`SECRETS_WRITE_PAT`) — the auto-injected `GITHUB_TOKEN` cannot write secrets.

If updating fails, log loudly (the post workflow will start failing in ~10 days when the token expires; we want maximum warning).

---

## 8. GitHub Actions workflows

### 8.1 Per-channel posting workflow

Filename: `.github/workflows/post-<channel-id>.yml`

Template (drifted-lines example):

```yaml
name: Post — Drifted Lines

on:
  schedule:
    - cron: '30 3 * * *'   # 03:30 UTC = 09:00 IST
    - cron: '30 15 * * *'  # 15:30 UTC = 21:00 IST
  workflow_dispatch:        # allow manual runs

permissions:
  contents: write           # to push the queue → posted commit

concurrency:
  group: post-drifted-lines
  cancel-in-progress: false

jobs:
  post:
    runs-on: ubuntu-latest
    timeout-minutes: 10
    steps:
      - uses: actions/checkout@v4
        with:
          token: ${{ secrets.GITHUB_TOKEN }}
      
      - uses: actions/setup-python@v5
        with:
          python-version: '3.12'
          cache: 'pip'
      
      - run: pip install -r requirements.txt
      
      - name: Run posting script
        env:
          GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}
          DRIFTED_LINES_IG_ACCESS_TOKEN: ${{ secrets.DRIFTED_LINES_IG_ACCESS_TOKEN }}
          DRIFTED_LINES_IG_USER_ID: ${{ secrets.DRIFTED_LINES_IG_USER_ID }}
          DRIFTED_LINES_IG_APP_ID: ${{ secrets.DRIFTED_LINES_IG_APP_ID }}
          DRIFTED_LINES_IG_APP_SECRET: ${{ secrets.DRIFTED_LINES_IG_APP_SECRET }}
        run: python src/post.py --channel drifted-lines
```

### 8.2 Token refresh workflow

Filename: `.github/workflows/refresh-tokens.yml`

```yaml
name: Refresh Instagram tokens

on:
  schedule:
    - cron: '0 6 * * 0'    # Sundays 06:00 UTC, every week
  workflow_dispatch:

permissions:
  contents: read

jobs:
  refresh:
    runs-on: ubuntu-latest
    strategy:
      fail-fast: false       # one channel's failure shouldn't block others
      matrix:
        channel: [drifted-lines]   # add new channels here
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: '3.12'
      - run: pip install -r requirements.txt
      - name: Refresh token for ${{ matrix.channel }}
        env:
          GITHUB_TOKEN: ${{ secrets.SECRETS_WRITE_PAT }}
          # Pass all per-channel secrets; the script picks the right ones from matrix.channel
          DRIFTED_LINES_IG_ACCESS_TOKEN: ${{ secrets.DRIFTED_LINES_IG_ACCESS_TOKEN }}
          DRIFTED_LINES_IG_APP_SECRET: ${{ secrets.DRIFTED_LINES_IG_APP_SECRET }}
        run: python src/token_refresh.py --channel ${{ matrix.channel }}
```

When new channels are added, append to the `matrix.channel` list and add the corresponding secrets to the env block.

---

## 9. Error handling & observability

### 9.1 Failure modes the script must handle gracefully

| Scenario                                 | Behavior                                                          |
|------------------------------------------|-------------------------------------------------------------------|
| Empty queue                              | Log warning, exit 0 (not a failure)                              |
| `posting.enabled: false`                 | Log info, exit 0                                                  |
| Missing secret                           | Exit 1 with all missing secrets listed                            |
| GitHub API 401/403                       | Exit 2 with explicit "check GITHUB_TOKEN permissions"             |
| Instagram token expired (#190)           | Exit 2; refresh job should have caught this, log loudly           |
| Instagram permission error (#10)         | Exit 2; suggest checking `instagram_business_content_publish`     |
| Instagram rate limit (#4 or 429)         | Exit 2 with retry-after; do not retry within the same run        |
| Image URL fetch fails on Meta's side     | Surface Meta's error code in logs; exit 2                         |
| Network error during git push            | Retry up to 3 times with exponential backoff before exiting 2     |
| Post succeeded but git push failed       | **Critical**: log error with the ig_media_id, exit 2. The post  |
|                                          | exists on Instagram but the queue file wasn't moved — manual     |
|                                          | intervention needed to avoid a duplicate next run.                |

### 9.2 Notifications (post-MVP, document but don't build yet)

Future: on failure, send a webhook to Slack or email via SMTP. Add `SLACK_WEBHOOK_URL` env var. Skip implementation for v1.

---

## 10. Dependencies

`requirements.txt`:

```
requests>=2.31,<3
PyYAML>=6.0,<7
PyNaCl>=1.5,<2          # for encrypting secret values when calling GitHub Secrets API in token_refresh.py
```

No `boto3`, no cloud SDKs. Keep it lean.

Python version: 3.12 (as pinned in workflow).

---

## 11. Testing

### 11.1 Unit tests (in `tests/`)

- `test_content.py`: `pick_next_image` returns correct file under various queue states (empty, single file, sorting edge cases). `resolve_caption` falls back correctly.
- `test_instagram.py`: mock `requests` calls, verify request shapes (URLs, params, headers). Test error mapping (190 → `InstagramTokenError`, etc.).
- `test_config.py`: missing secrets reported correctly.

Use `pytest`. Run via `pytest tests/` in CI.

### 11.2 Manual verification flow for the first channel

1. Set up `channels/drifted-lines/` per § 4.
2. Add at least one image (`001.jpg`) and one caption to `captions.json`.
3. Add all four secrets to GitHub.
4. Trigger the workflow manually via `workflow_dispatch`.
5. Verify on Instagram that the post appeared.
6. Verify in the repo: `001.jpg` moved to `posted/`, `posted.json` updated, commit pushed by the bot.

### 11.3 Dry-run for ongoing safety

Before any major change, run `python src/post.py --channel drifted-lines --dry-run` locally with secrets in a `.env` to confirm logic without publishing.

---

## 12. Future extensions (do not build now, but design must accommodate)

### 12.1 Reels

Same flow with two changes:
- `media_type=REELS` in container creation; pass `video_url`, optional `cover_url`, `share_to_feed`.
- Must poll container status (`status_code`) until `FINISHED` before publishing — videos take 10s to several minutes to process.

The `InstagramClient` already has stubs for `create_reel_container` and `poll_container_status` per § 7.1. Add `.mp4` to allowed extensions in `pick_next_image` when `media_types` includes `reel`.

### 12.2 Carousels

Two-step container creation: create child containers for each item, then create a parent carousel container with `children=<comma-separated IDs>`, then publish. Carousels count as one post against the 100/day limit.

### 12.3 Multiple posts per day per channel

Extend cron to multiple times in the workflow file, or add a queue index to allow batched posting. Not needed at MVP.

### 12.4 Analytics

Post-publish, fetch insights via `GET /{ig_media_id}/insights?metric=reach,likes,comments,saves`. Log to a separate `analytics.json` per channel. Insights only available for accounts with 1,000+ followers.

---

## 13. Open questions / explicit non-goals

- **No web UI** for queue management. Editing `captions.json` and dropping files in `queue/` happens via git.
- **No image editing** (resizing, watermarking) in this script. Images are assumed to be Instagram-ready before being committed.
- **No content moderation or pre-flight checks** beyond file existence and extension. Caller is responsible for queue contents.
- **Single time zone for cron**: all schedules are UTC. Convert mentally for IST (+5:30) when authoring workflow files.

---

## 14. Acceptance criteria for v1

The system is considered complete when:

1. ✅ `python src/post.py --channel drifted-lines --dry-run` succeeds locally with valid secrets in a `.env`.
2. ✅ A manually-triggered GitHub Actions run posts a real image to drifted_lines, moves the file to `posted/`, updates `posted.json`, and pushes the commit.
3. ✅ The scheduled cron triggers at the configured time and produces a post.
4. ✅ Token refresh workflow updates the secret successfully.
5. ✅ Adding a hypothetical second channel (creating folder, secrets, workflow file) requires zero code changes.
6. ✅ All unit tests pass.
7. ✅ README documents how to add a new channel and how to authorize a new Instagram account with Meta.
