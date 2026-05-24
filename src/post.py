from __future__ import annotations

import argparse
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover - optional convenience only
    load_dotenv = None

try:
    from .config import ConfigError, load_channel_config, load_secrets
    from .content import QueueItem, count_queue_items, pick_next_item, resolve_caption
    from .exceptions import ContentValidationError, GitHubAPIError, InstagramAPIError
    from .github_storage import (
        append_to_posted_log,
        get_signed_download_url,
        git_move_and_commit,
        validate_posted_log,
    )
    from .instagram import InstagramClient
except ImportError:  # pragma: no cover - script execution fallback
    from config import ConfigError, load_channel_config, load_secrets
    from content import QueueItem, count_queue_items, pick_next_item, resolve_caption
    from exceptions import ContentValidationError, GitHubAPIError, InstagramAPIError
    from github_storage import (
        append_to_posted_log,
        get_signed_download_url,
        git_move_and_commit,
        validate_posted_log,
    )
    from instagram import InstagramClient


if load_dotenv is not None:
    load_dotenv()


def main() -> int:
    parser = argparse.ArgumentParser(description="Post the next queued Instagram item.")
    parser.add_argument("--channel", required=True, help="Channel ID to post.")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Resolve content and log actions without publishing or pushing.",
    )
    args = parser.parse_args()

    logger = configure_logging(args.channel)

    try:
        config = load_channel_config(args.channel)

        if not config.posting.enabled:
            logger.info("Posting is disabled in channel config.")
            return 0

        secrets = load_secrets(config.secret_prefix)
        queue_count = count_queue_items(
            config.channel_id,
            allowed_media_types=config.content.media_types,
        )
        item = pick_next_item(
            config.channel_id,
            allowed_media_types=config.content.media_types,
        )
        if item is None:
            logger.warning("Queue is empty; nothing eligible to post.")
            return 0

        if queue_count < config.posting.min_queue_warning:
            logger.warning(
                "Queue is below warning threshold: %s items remaining.",
                queue_count,
            )

        logger.info(
            "Picked %s (%s) from queue (%s items remaining after this post).",
            item.identifier,
            item.media_type,
            max(queue_count - 1, 0),
        )

        caption, caption_source = resolve_caption(
            config.channel_id,
            item.identifier,
            config.content.default_caption_key,
        )
        logger.info(
            "Resolved caption (length=%s, source=%s).",
            len(caption),
            caption_source,
        )

        validate_posted_log(config.channel_id)

        if args.dry_run:
            logger.info(
                "Dry run enabled. Would publish %s as a %s using %s asset(s).",
                item.identifier,
                item.media_type,
                len(item.paths),
            )
            return 0

        github_token = resolve_token()
        repo = require_env("GITHUB_REPOSITORY")
        client = InstagramClient(
            ig_user_id=secrets.ig_user_id,
            access_token=secrets.ig_access_token,
        )
        ig_media_id = publish_queue_item(
            root_dir=config.root_dir,
            item=item,
            caption=caption,
            repo=repo,
            github_token=github_token,
            client=client,
            logger=logger,
        )
        logger.info("Published: ig_media_id=%s", ig_media_id)

        permalink = client.get_permalink(ig_media_id)
        if permalink:
            logger.info("Permalink: %s", permalink)
        else:
            logger.warning("Permalink lookup failed; continuing without it.")

        posted_entry = {
            "filename": item.identifier,
            "media_type": item.media_type,
            "ig_media_id": ig_media_id,
            "caption_used": caption,
            "posted_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "permalink": permalink,
        }
        if item.media_type == "carousel":
            posted_entry["slide_count"] = len(item.paths)

        try:
            append_to_posted_log(config.channel_id, posted_entry)
            git_move_and_commit(
                config.channel_id,
                item.identifier,
                item.media_type == "carousel",
                ig_media_id,
                item.media_type,
            )
        except GitHubAPIError as exc:
            raise GitHubAPIError(
                "Post published to Instagram but repository state update failed. "
                f"Manual intervention is required to avoid a duplicate post. "
                f"ig_media_id={ig_media_id}. {exc}"
            ) from exc

        logger.info("Moved %s to posted/ and updated posted.json.", item.identifier)
        return 0

    except ConfigError as exc:
        emit_github_actions_error(str(exc))
        logger.error(str(exc))
        return 1
    except (ContentValidationError, GitHubAPIError, InstagramAPIError) as exc:
        emit_github_actions_error(str(exc))
        logger.error(str(exc))
        return 2
    except Exception:
        emit_github_actions_error("Unexpected error during posting.")
        logger.exception("Unexpected error during posting.")
        return 3


def publish_queue_item(
    root_dir: Path,
    item: QueueItem,
    caption: str,
    repo: str,
    github_token: str,
    client: InstagramClient,
    logger: logging.LoggerAdapter,
) -> str:
    if item.media_type == "image":
        image_url = _get_signed_url(root_dir, item.paths[0], repo, github_token)
        container_id = client.create_image_container(image_url=image_url, caption=caption)
        logger.info("Image container created: %s", container_id)
        client.poll_container_status(container_id, max_wait_seconds=600, poll_interval=5)
        logger.info("Image container finished processing: %s", container_id)
        return client.publish_container(container_id)

    if item.media_type == "reel":
        video_url = _get_signed_url(root_dir, item.paths[0], repo, github_token)
        container_id = client.create_reel_container(video_url=video_url, caption=caption)
        logger.info("Reel container created: %s", container_id)
        client.poll_container_status(container_id, max_wait_seconds=600, poll_interval=5)
        logger.info("Reel container finished processing: %s", container_id)
        return client.publish_container(container_id)

    child_ids: list[str] = []
    for path in item.paths:
        media_url = _get_signed_url(root_dir, path, repo, github_token)
        is_video = _is_video_path(path)
        child_id = client.create_carousel_child_container(media_url=media_url, is_video=is_video)
        logger.info("Carousel child container created for %s: %s", path.name, child_id)
        child_ids.append(child_id)

    parent_id = client.create_carousel_parent_container(child_ids, caption)
    logger.info("Carousel parent container created: %s", parent_id)
    client.poll_container_status(parent_id, max_wait_seconds=600, poll_interval=5)
    logger.info("Carousel parent container finished processing: %s", parent_id)
    return client.publish_container(parent_id)


def configure_logging(channel_id: str) -> logging.LoggerAdapter:
    log_level_name = os.getenv("LOG_LEVEL", "INFO").upper()
    log_level = getattr(logging, log_level_name, logging.INFO)
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s %(levelname)s [%(channel)s] %(message)s",
        force=True,
    )

    class ChannelFilter(logging.Filter):
        def filter(self, record: logging.LogRecord) -> bool:
            if not hasattr(record, "channel"):
                record.channel = channel_id
            return True

    root_logger = logging.getLogger()
    for handler in root_logger.handlers:
        handler.addFilter(ChannelFilter())

    return logging.LoggerAdapter(logging.getLogger("post"), {"channel": channel_id})


def require_env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise ConfigError(
            f"Missing required environment variable: {name}. "
            "GitHub Actions provides this automatically; set it manually for local live runs."
        )
    return value


def resolve_token() -> str:
    token = os.getenv("TOKEN", "").strip()
    if token:
        return token
    return require_env("GITHUB_TOKEN")


def emit_github_actions_error(message: str) -> None:
    if os.getenv("GITHUB_ACTIONS") != "true":
        return
    escaped = (
        message.replace("%", "%25")
        .replace("\r", "%0D")
        .replace("\n", "%0A")
    )
    print(f"::error::{escaped}", file=sys.stderr)


def _get_signed_url(
    root_dir: Path,
    path: Path,
    repo: str,
    github_token: str,
) -> str:
    media_path = _to_repo_path(root_dir, path)
    url = get_signed_download_url(repo, media_path, github_token)
    logging.getLogger("post").info("Generated signed download URL for %s.", media_path)
    return url


def _to_repo_path(root_dir: Path, path: Path) -> str:
    return path.relative_to(root_dir).as_posix()


def _is_video_path(path: Path) -> bool:
    return path.suffix.lower() in {".mp4", ".mov"}


if __name__ == "__main__":
    raise SystemExit(main())
