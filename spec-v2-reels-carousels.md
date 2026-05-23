# Specification v2 — Extending to Reels and Carousels

## Context

This document extends `spec.md` (v1) to support Reels (single video posts) and Carousels (2–10 mixed-media slideshows) alongside the existing single-image posting. Read `spec.md` first; this is a delta, not a replacement.

The v1 system is currently in production. Implementations of v2 must preserve backward compatibility: existing image posts in any channel's `queue/` must continue to work without changes to their files or captions.

---

## 1. New media types

| Type     | Identified by                                    | API media_type   |
|----------|--------------------------------------------------|------------------|
| Image    | File ending `.jpg`, `.jpeg`, `.png`              | `IMAGE` (default; param can be omitted) |
| Reel     | File ending `.mp4`, `.mov`                       | `REELS`          |
| Carousel | A **subdirectory** under `queue/` containing 2–10 image/video files | `CAROUSEL`       |

Detection is purely by what exists in `queue/`. A file → single-media post (image or reel). A folder → carousel.

Both image and Reel detection are case-insensitive on the extension.

---

## 2. File and folder conventions

### 2.1 Updated `queue/` layout

```
channels/drifted-lines/queue/
├── 001.jpg                  # image post (existing, unchanged)
├── 002.png                  # image post
├── 003.mp4                  # reel post
├── 004/                     # carousel post
│   ├── 01.jpg
│   ├── 02.jpg
│   └── 03.mp4
├── 005.mov                  # reel post
└── 006/                     # another carousel
    ├── 01.png
    └── 02.png
```

### 2.2 Sort order

`pick_next_item` lists everything in `queue/` (files and folders), sorts alphabetically by name (the part before the extension for files, the full name for folders), and returns the first entry as a structured object describing what was found.

Zero-padding rules from v1 (`001`, `002`, …) apply identically to carousel folder names.

### 2.3 Carousel internal ordering

Files inside a carousel folder are sorted alphabetically and added to the parent container's `children` parameter in that order. Instagram displays carousel slides in the order children are provided.

**Recommended naming inside carousel folders**: `01.jpg`, `02.jpg`, … (two-digit zero-padded). Carousels max out at 10 items so two digits suffice.

### 2.4 captions.json schema (no breaking change)

The keys map to whatever `pick_next_item` returns as the identifier:

- Single-media post: key is the **filename including extension** (e.g., `"003.mp4"`, `"001.jpg"`)
- Carousel: key is the **folder name** (e.g., `"004"`, no extension)

```json
{
  "default": "✨\n\n#quotes #poetry #driftedlines",
  "001.jpg": "Image caption...",
  "002.png": "Image caption...",
  "003.mp4": "Reel caption with the same hashtag block conventions...",
  "004": "Carousel caption that applies to all slides...",
  "005.mov": "Another reel caption..."
}
```

---

## 3. Media constraints

Implementations must enforce these before attempting to publish. Validation failures surface a clear error and abort the run without consuming the queue item.

### 3.1 Reels

- **Format**: MP4 (preferred) or MOV
- **Duration**: 3–90 seconds. Outside this range, Instagram either rejects or publishes as a regular video (not surfacing in the Reels tab). The script must reject videos outside 3–90s with a clear error.
- **Aspect ratio**: 9:16 strongly preferred. Other ratios may be cropped or letterboxed. Script logs a warning but does not block.
- **File size**: keep under 100 MB to stay well within GitHub's soft repo size limits. The script logs a warning above 100 MB and a hard error above 500 MB.
- **Codec**: H.264 video, AAC audio. Not enforced by script (Meta will reject if non-compliant); document this in README.

### 3.2 Carousels

- **Item count**: 2–10. Folders with 0, 1, or 11+ items must produce an error.
- **Per-child duration** (videos): up to 60 seconds (Instagram limit for carousel video items, distinct from Reels).
- **Mixed types**: a single carousel can contain any mix of images and videos.
- **Aspect ratio**: Instagram crops to whatever the first item's aspect is. Document this in README; do not block in script.

### 3.3 Use ffprobe for video validation

`ffmpeg`/`ffprobe` is preinstalled on `ubuntu-latest` runners. Use it in `src/content.py` to check duration and dimensions for `.mp4`/`.mov` files. If `ffprobe` is unavailable locally, the script can skip validation with a logged warning (don't hard-fail on dev machines that lack it).

---

## 4. Module updates

### 4.1 `src/instagram.py` — new methods

Replace the v1 stubs from `spec.md` § 7.1 with full implementations.

```python
class InstagramClient:
    # Existing methods unchanged: create_image_container, publish_container, get_permalink
    
    def create_reel_container(
        self,
        video_url: str,
        caption: str,
        cover_url: str | None = None,
        share_to_feed: bool = True,
    ) -> str:
        """POST /{ig_user_id}/media with media_type=REELS.
        Returns container_id. Caller must poll status before publishing."""
    
    def create_carousel_child_container(
        self,
        media_url: str,
        is_video: bool,
    ) -> str:
        """POST /{ig_user_id}/media with is_carousel_item=true.
        If is_video, media_type=VIDEO and video_url=media_url.
        Else, image_url=media_url (no media_type needed).
        Returns child container_id."""
    
    def create_carousel_parent_container(
        self,
        children: list[str],
        caption: str,
    ) -> str:
        """POST /{ig_user_id}/media with media_type=CAROUSEL and 
        children=comma-separated child IDs. Returns parent container_id."""
    
    def poll_container_status(
        self,
        container_id: str,
        max_wait_seconds: int = 600,
        poll_interval: int = 5,
    ) -> None:
        """GET /{container_id}?fields=status_code repeatedly until status_code
        is 'FINISHED'. Raises InstagramAPIError on 'ERROR' or 'EXPIRED'.
        Raises InstagramTimeoutError if max_wait_seconds elapses while 
        still 'IN_PROGRESS'. Logs progress every poll."""
```

**Status codes returned by GET /{container_id}**:

| Code           | Meaning                                              | Script behavior          |
|----------------|------------------------------------------------------|--------------------------|
| `IN_PROGRESS`  | Meta still processing the media                      | Wait and poll again       |
| `FINISHED`     | Ready to publish                                     | Stop polling, publish     |
| `ERROR`        | Processing failed (bad codec, corrupt file, etc.)    | Abort, raise error        |
| `EXPIRED`      | Container older than 24h, no longer usable           | Abort, raise error        |
| `PUBLISHED`    | Already published (shouldn't occur in our flow)      | Treat as success, log it  |

### 4.2 `src/content.py` — refactored item picker

Rename `pick_next_image` to `pick_next_item`. New return shape:

```python
@dataclass
class QueueItem:
    identifier: str           # filename ("003.mp4") or folder name ("004")
    media_type: Literal["image", "reel", "carousel"]
    paths: list[Path]         # always a list; length 1 for image/reel, 2-10 for carousel
                              # for carousels, sorted alphabetically (slide order)
```

```python
def pick_next_item(channel_id: str) -> QueueItem | None:
    """Lists all top-level entries in queue/. Files = single-media. 
    Folders = carousels. Returns the alphabetically-first entry as a QueueItem,
    or None if queue is empty.
    
    Sorting: compare full names case-sensitively. Folders and files sort 
    together (Python's default Path sort).
    
    Validation:
    - Image files: extension in {.jpg, .jpeg, .png}
    - Video files: extension in {.mp4, .mov}
    - Carousel folders: must contain 2-10 image/video files (raises ValueError 
      with a descriptive message if not)
    - Files with unsupported extensions are skipped with a warning
    - Hidden files/folders (starting with .) are ignored
    """
```

`resolve_caption` is unchanged; the caller passes `item.identifier` as the lookup key.

### 4.3 `src/post.py` — branched flow

Replace the linear flow from `spec.md` § 6.2 with a branched version. Pseudocode:

```
1.  Parse args. Load config. Resolve secrets. (unchanged from v1)
2.  item = pick_next_item(channel)
    If item is None → log empty queue, exit 0
3.  caption = resolve_caption(channel, item.identifier, default_key)
4.  If --dry-run → log resolved values + planned action, exit 0
5.  Branch on item.media_type:

    IMAGE:
      url = github.get_signed_url(item.paths[0])
      container = ig.create_image_container(url, caption)
      ig_media_id = ig.publish_container(container)
    
    REEL:
      url = github.get_signed_url(item.paths[0])
      container = ig.create_reel_container(url, caption)
      ig.poll_container_status(container)         # NEW: required for video
      ig_media_id = ig.publish_container(container)
    
    CAROUSEL:
      child_ids = []
      for p in item.paths:
          url = github.get_signed_url(p)
          is_video = p.suffix.lower() in {'.mp4', '.mov'}
          child = ig.create_carousel_child_container(url, is_video)
          child_ids.append(child)
      
      parent = ig.create_carousel_parent_container(child_ids, caption)
      
      # If any child is video, parent also needs polling
      if any(p.suffix.lower() in {'.mp4', '.mov'} for p in item.paths):
          ig.poll_container_status(parent)
      
      ig_media_id = ig.publish_container(parent)

6.  permalink = ig.get_permalink(ig_media_id)
7.  Append to posted.json (entry includes media_type field — see § 5)
8.  Move item from queue/ to posted/ (file or folder)
9.  Git commit + push
10. Log success + permalink, exit 0
```

### 4.4 `src/github_storage.py` — folder-aware move

Update `git_move_and_commit` to handle both file and directory moves:

```python
def git_move_and_commit(
    channel_id: str,
    identifier: str,        # filename or folder name
    is_directory: bool,
    ig_media_id: str,
    media_type: str,
) -> None:
    """Move queue/<identifier> → posted/<identifier> via git mv.
    Works for files (image, reel) and directories (carousel).
    Commit message: 'post: <channel> <type> <identifier> → <ig_media_id>'"""
```

`git mv` natively handles directory moves on all platforms, so no special-casing needed beyond verifying the source path before invoking.

`get_signed_download_url` is unchanged — the GitHub Contents API endpoint works the same for any path.

---

## 5. posted.json schema update

Add `media_type` and (for carousels) `slide_count`. Backward compatible: old entries without these fields are valid.

```json
[
  {
    "filename": "001.jpg",
    "media_type": "image",
    "ig_media_id": "17912345678901234",
    "caption_used": "...",
    "posted_at_utc": "2026-05-10T13:00:42Z",
    "permalink": "https://www.instagram.com/p/Cxyz.../"
  },
  {
    "filename": "003.mp4",
    "media_type": "reel",
    "ig_media_id": "17912345678901235",
    "caption_used": "...",
    "posted_at_utc": "2026-05-11T13:00:30Z",
    "permalink": "https://www.instagram.com/reel/Cxyz.../"
  },
  {
    "filename": "004",
    "media_type": "carousel",
    "slide_count": 3,
    "ig_media_id": "17912345678901236",
    "caption_used": "...",
    "posted_at_utc": "2026-05-12T13:00:55Z",
    "permalink": "https://www.instagram.com/p/Cxyz.../"
  }
]
```

The `filename` field keeps its name for continuity even though it can now also hold a folder name.

---

## 6. Error handling additions

| Scenario                                              | Behavior                                                         |
|-------------------------------------------------------|------------------------------------------------------------------|
| Reel < 3s or > 90s                                    | Reject with clear error; do not move file; exit 2                |
| Reel file > 500 MB                                    | Reject; exit 2                                                   |
| Carousel folder with 0, 1, or 11+ items               | Reject; exit 2                                                   |
| Carousel folder contains an unsupported file type     | Reject listing the offending file(s); exit 2                     |
| Container status returns `ERROR`                      | Log Meta's error reason from `status` or `error` field; exit 2   |
| Container status returns `EXPIRED`                    | Log; exit 2 (shouldn't happen — we publish within minutes)       |
| `poll_container_status` hits `max_wait_seconds`       | Log; exit 2 with note that the container may eventually succeed and need manual cleanup |
| `ffprobe` not available locally                       | Log warning, skip duration validation, continue                  |

The "succeeded on Instagram but git push failed" critical case from v1 § 9.1 applies identically and is even more important for carousels (where the parent and all children consumed quota).

---

## 7. Channel config update

`config.yml` gains explicit media_types control:

```yaml
content:
  media_types: [image, reel, carousel]   # was: [image]
  default_caption_key: default
```

The script filters discovered items by this list. If `media_types: [image]`, video files and folders in `queue/` are skipped with a warning rather than processed — useful for channels that should only post one media type. Existing channels with `media_types: [image]` continue to behave exactly as before.

For drifted-lines specifically, update to `[image, reel, carousel]` when ready to accept all types.

---

## 8. Workflow file updates

None. The `.github/workflows/post-*.yml` files do not change between v1 and v2. Same cron, same env block, same `python src/post.py --channel ...` command.

The only operational change is install-time: `ffprobe` is preinstalled on Ubuntu runners, so no `apt install` step needed. Document this in README.

---

## 9. requirements.txt

No new Python dependencies needed for v2. `ffprobe` is a binary, not a pip package. Continue to use `subprocess` to invoke it.

---

## 10. Testing additions

### Unit tests

- `test_content.py`:
  - `pick_next_item` returns image, reel, carousel correctly based on queue contents
  - Sort order is preserved across mixed types
  - Carousel with 0/1/11 items raises
  - Unsupported extensions are skipped, not raised
  - Hidden files (`.DS_Store`) are ignored

- `test_instagram.py`:
  - `create_reel_container` sends `media_type=REELS` and `video_url`
  - `create_carousel_child_container` sends `is_carousel_item=true`
  - `create_carousel_parent_container` sends `children` as comma-separated string
  - `poll_container_status` handles all five status codes correctly
  - Polling respects `max_wait_seconds` and raises `InstagramTimeoutError`

### Manual verification

For each new media type, do one end-to-end test before relying on cron:

1. **Reel**: drop a 10-second 9:16 MP4 (named with the next available number, e.g., `097.mp4`) into `queue/`, add caption to `captions.json`, push, trigger workflow manually, verify Reel appears under the Reels tab on Instagram and `posted.json` shows `"media_type": "reel"`.

2. **Carousel**: create `queue/098/` with 3 images named `01.jpg`, `02.jpg`, `03.jpg`, add caption under key `"098"` in `captions.json`, push, trigger, verify carousel appears with 3 slides in order and `posted.json` shows `"media_type": "carousel"` and `"slide_count": 3`.

Verify the queue→posted move handled the folder cleanly for the carousel (the entire `098/` directory should now live under `posted/`).

---

## 11. README updates

Add to the README:

1. **Media types section** describing the three supported types and how each is detected from `queue/`.
2. **Examples** of each: a single image file, a single video file, a folder for carousel.
3. **Constraints** table: duration, file size, aspect ratio recommendations.
4. **ffprobe note**: pre-installed in CI; install locally for dev (`brew install ffmpeg` or `apt install ffmpeg`).

---

## 12. Acceptance criteria for v2

System is considered v2-complete when:

1. ✅ All v1 acceptance criteria continue to pass.
2. ✅ A queue containing a mix of images, reels, and a carousel folder publishes them in alphabetical order across consecutive runs.
3. ✅ Reel container polling waits correctly through `IN_PROGRESS` and proceeds at `FINISHED`.
4. ✅ Carousel with 3 mixed images publishes with correct slide ordering.
5. ✅ Channel config `media_types: [image]` continues to skip videos and folders, preserving v1 behavior.
6. ✅ posted.json entries include `media_type` for all new posts.
7. ✅ All new unit tests pass.

---

## 13. Out of scope for v2 (do not build)

- **Per-slide carousel captions**: Instagram doesn't support these via API.
- **Custom audio for Reels**: Possible via `audio_name` parameter but adds complexity; skip for now.
- **Reel cover image upload**: Auto-generated from first frame is good enough for MVP. Document the optional `cover_url` parameter in code comments for future use.
- **Stories**: Different API, different flow. Out of scope.
- **Analytics fetching**: Same as v1 § 12.4 — future work.
