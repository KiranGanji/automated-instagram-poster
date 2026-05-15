# Automated Instagram Poster

Automated Instagram Poster is a local-first Python project for scheduled Instagram publishing from a folder-based queue. Each channel owns its own queue, captions, config, and posting history so you can scale by copying channel folders and workflow files instead of changing application code.

## Repo layout

```text
automated-instagram-poster/
├── .github/
│   └── workflows/
│       ├── post-drifted-lines.yml
│       └── refresh-tokens.yml
├── channels/
│   └── drifted-lines/
│       ├── config.yml
│       ├── captions.json
│       ├── posted.json
│       ├── queue/
│       └── posted/
├── src/
│   ├── __init__.py
│   ├── post.py
│   ├── instagram.py
│   ├── github_storage.py
│   ├── config.py
│   ├── content.py
│   ├── token_refresh.py
│   └── exceptions.py
├── tests/
│   ├── __init__.py
│   ├── test_content.py
│   ├── test_instagram.py
│   ├── test_config.py
│   └── fixtures/
├── .env.example
├── .gitignore
├── README.md
├── requirements.txt
└── spec.md
```

`tools/build_captions.py` is included for re-importing caption data from the original CSV, but `tools/` is gitignored by default.

## Add a new channel

1. Create `channels/<new-channel-id>/` with `config.yml`, `captions.json`, `posted.json`, `queue/`, and `posted/`.
2. Set `channel_id`, `display_name`, and `secret_prefix` in the new `config.yml`.
3. Add the channel's media files to `queue/` and the caption map to `captions.json`.
4. Add the four GitHub Secrets matching the new `secret_prefix`.
5. Copy `post-drifted-lines.yml` to `post-<new-channel-id>.yml` and update the channel name, secrets, and cron.

## Authorize a new Instagram account

Create or reuse a Meta app, connect the Instagram professional account, complete the Instagram Login flow, exchange the short-lived token for a long-lived token, and store the resulting credentials in your per-channel secrets. The detailed Meta console walkthrough lives outside this repo; this project assumes those four values already exist.

## Local development

Copy `.env.example` to `.env` if you need a fresh template, fill in the `DRIFTED_LINES_*` values, then run:

```bash
python src/post.py --channel drifted-lines --dry-run
```

Dry runs resolve config, queue state, captions, and secret loading without publishing to Instagram or pushing git changes.

## Troubleshooting

| Code | Meaning | Fix |
| --- | --- | --- |
| 190 | Token expired or invalid | Refresh the long-lived token and update the channel secret. |
| 10 | Missing permission | Re-check the app scopes, account linkage, and publish permissions. |
| 4 | Rate limit hit | Wait for the retry window, reduce retries, and re-run later. |
