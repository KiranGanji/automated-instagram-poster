from __future__ import annotations

import argparse
import logging
import os
from datetime import datetime, timezone

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover - optional convenience only
    load_dotenv = None

try:
    from .config import ConfigError, load_channel_config, load_secrets
    from .content import list_queue_images, resolve_caption
    from .exceptions import GitHubAPIError, InstagramAPIError
    from .github_storage import append_to_posted_log, get_signed_download_url, git_move_and_commit
    from .instagram import InstagramClient
except ImportError:  # pragma: no cover - script execution fallback
    from config import ConfigError, load_channel_config, load_secrets
    from content import list_queue_images, resolve_caption
    from exceptions import GitHubAPIError, InstagramAPIError
    from github_storage import append_to_posted_log, get_signed_download_url, git_move_and_commit
    from instagram import InstagramClient


if load_dotenv is not None:
    load_dotenv()


def main() -> int:
    parser = argparse.ArgumentParser(description="Post the next queued Instagram image.")
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
        queue_files = list_queue_images(config.channel_id)
        if not queue_files:
            logger.warning("Queue is empty; nothing to post.")
            return 0

        if len(queue_files) < config.posting.min_queue_warning:
            logger.warning(
                "Queue is below warning threshold: %s items remaining.",
                len(queue_files),
            )

        filename = queue_files[0]
        logger.info(
            "Picked %s from queue (%s items remaining after this post).",
            filename,
            len(queue_files) - 1,
        )

        caption, caption_source = resolve_caption(
            config.channel_id,
            filename,
            config.content.default_caption_key,
        )
        logger.info(
            "Resolved caption (length=%s, source=%s).",
            len(caption),
            caption_source,
        )

        if args.dry_run:
            logger.info("Dry run enabled. Would publish %s with the resolved caption.", filename)
            return 0

        github_token = require_env("GITHUB_TOKEN")
        repo = require_env("GITHUB_REPOSITORY")
        media_path = f"channels/{config.channel_id}/queue/{filename}"
        image_url = get_signed_download_url(repo, media_path, github_token)
        logger.info("Generated signed download URL for %s.", filename)

        client = InstagramClient(
            ig_user_id=secrets.ig_user_id,
            access_token=secrets.ig_access_token,
        )
        container_id = client.create_image_container(image_url=image_url, caption=caption)
        logger.info("Container created: %s", container_id)

        ig_media_id = client.publish_container(container_id)
        logger.info("Published: ig_media_id=%s", ig_media_id)

        permalink = client.get_permalink(ig_media_id)
        if permalink:
            logger.info("Permalink: %s", permalink)
        else:
            logger.warning("Permalink lookup failed; continuing without it.")

        posted_entry = {
            "filename": filename,
            "ig_media_id": ig_media_id,
            "caption_used": caption,
            "posted_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "permalink": permalink,
        }

        try:
            append_to_posted_log(config.channel_id, posted_entry)
            git_move_and_commit(config.channel_id, filename, ig_media_id)
        except GitHubAPIError as exc:
            raise GitHubAPIError(
                "Post published to Instagram but repository state update failed. "
                f"Manual intervention is required to avoid a duplicate post. "
                f"ig_media_id={ig_media_id}. {exc}"
            ) from exc

        logger.info("Moved %s to posted/ and updated posted.json.", filename)
        return 0

    except ConfigError as exc:
        logger.error(str(exc))
        return 1
    except (GitHubAPIError, InstagramAPIError) as exc:
        logger.error(str(exc))
        return 2
    except Exception:
        logger.exception("Unexpected error during posting.")
        return 3


def configure_logging(channel_id: str) -> logging.LoggerAdapter:
    log_level_name = os.getenv("LOG_LEVEL", "INFO").upper()
    log_level = getattr(logging, log_level_name, logging.INFO)
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s %(levelname)s [%(channel)s] %(message)s",
        force=True,
    )
    return logging.LoggerAdapter(logging.getLogger("post"), {"channel": channel_id})


def require_env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise ConfigError(
            f"Missing required environment variable: {name}. "
            "GitHub Actions provides this automatically; set it manually for local live runs."
        )
    return value


if __name__ == "__main__":
    raise SystemExit(main())
