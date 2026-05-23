# New Channel Checklist

Use this checklist whenever you add a new Instagram account/channel to this repo.

## 1. Create the channel folder

Create:

```text
channels/<channel-id>/
├── config.yml
├── captions.json
├── posted.json
├── queue/
└── posted/
```

Initialize:

- `posted.json` with `[]`
- `captions.json` with at least a `default` key
- `queue/` with the media you want to publish

## 2. Write `config.yml`

Example:

```yaml
channel_id: new-channel
display_name: "New Channel"
secret_prefix: NEW_CHANNEL

content:
  media_types: [image, reel, carousel]
  default_caption_key: default

posting:
  enabled: true
  min_queue_warning: 14
```

Notes:

- `channel_id` must match the folder name exactly.
- `secret_prefix` must be uppercase with underscores.
- Use `media_types: [image]` if the channel should ignore reels/carousels.

## 3. Prepare the queue and captions

Supported queue entries:

- Image post: `001.jpg`, `002.png`
- Reel post: `003.mp4`, `004.mov`
- Carousel post: `005/` containing `01.jpg`, `02.jpg`, `03.mp4`

Rules:

- Top-level queue entries are processed alphabetically.
- Carousel slides are processed alphabetically within the folder.
- Carousel folders must contain 2-10 supported files.
- Reel files must be 3-90 seconds.

`captions.json` keys must match the queue identifier:

- Image/Reel: full filename such as `"003.mp4"`
- Carousel: folder name such as `"005"`

Example:

```json
{
  "default": "Fallback caption",
  "001.jpg": "Image caption",
  "003.mp4": "Reel caption",
  "005": "Carousel caption"
}
```

## 4. Add GitHub secrets

Create these repository secrets using the channel's `secret_prefix`:

- `<PREFIX>_IG_ACCESS_TOKEN`
- `<PREFIX>_IG_USER_ID`
- `<PREFIX>_IG_APP_ID`
- `<PREFIX>_IG_APP_SECRET`

Example for `secret_prefix: NEW_CHANNEL`:

- `NEW_CHANNEL_IG_ACCESS_TOKEN`
- `NEW_CHANNEL_IG_USER_ID`
- `NEW_CHANNEL_IG_APP_ID`
- `NEW_CHANNEL_IG_APP_SECRET`

If workflow pushes cannot use the default GitHub token, also ensure repo secret `TOKEN` is set.

## 5. Create a post workflow

Copy [.github/workflows/post-drifted-lines.yml](/Users/kiranganji/InstagramAutomation/automated-instagram-poster/.github/workflows/post-drifted-lines.yml:1) to:

```text
.github/workflows/post-<channel-id>.yml
```

Update:

- Workflow `name`
- `concurrency.group`
- Cron schedule
- All `DRIFTED_LINES_*` env vars to the new prefix
- `run: python src/post.py --channel <channel-id>`

No extra v2 steps are needed for reels/carousels. The same workflow command works for all supported media types.

## 6. Update the token refresh workflow

Edit [.github/workflows/refresh-tokens.yml](/Users/kiranganji/InstagramAutomation/automated-instagram-poster/.github/workflows/refresh-tokens.yml:1).

Update:

- Add the new channel to `matrix.channel`
- Add the new channel's `env` secrets to the refresh step

This repo's refresh workflow currently lists each channel's secrets explicitly, so adding a channel is not just a matrix change.

## 7. Update local env files if needed

If you want to dry-run locally for the new channel, add the new secret keys to:

- `.env.example`
- `.env`

## 8. Verify before enabling cron

Run a local dry-run:

```bash
python src/post.py --channel <channel-id> --dry-run
```

Then:

1. Push the branch.
2. Trigger `post-<channel-id>.yml` manually with `workflow_dispatch`.
3. Confirm the item moves from `queue/` to `posted/`.
4. Confirm `posted.json` is updated.
5. Confirm the post appears correctly on Instagram.

## 9. Common mistakes

- Folder name and `channel_id` do not match
- `captions.json` key does not match the filename/folder name exactly
- Missing `default` caption
- Missing GitHub secrets for the new prefix
- Forgetting to create the per-channel post workflow
- Forgetting to update `refresh-tokens.yml`
