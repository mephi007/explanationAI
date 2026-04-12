"""
staggered_poster.py — Posts content pieces at staggered times.
Called by 6 separate GitHub Actions cron jobs (not all at once).

Posting schedule (IST):
  06:00 — YouTube long-form
  07:00 — YouTube Short 1 (hook)   + Drive upload for IG Short 1
  08:00 — LinkedIn carousel
  12:30 — YouTube Short 2 (dry_run) + Drive upload for IG Short 2
  17:30 — YouTube Short 3 (code)   + Drive upload for IG Short 3
  21:00 — YouTube Short 4 (dialogue) + Drive upload for IG Short 4

Instagram is NOT auto-posted. Videos + captions are uploaded to Google Drive
(GOOGLE_DRIVE_FOLDER_ID) for manual review and posting.

PLATFORM_SLOT env var tells this script which slot to run.
"""

import os
import sys
import json
import time
from pathlib import Path
from datetime import date
import db
import telegram_bot as tg

sys.path.insert(0, str(Path(__file__).parent.parent))

# Importing platform-specific posters
from posters.linkedin_poster import post_linkedin_carousel
from posters.drive_uploader import upload_instagram_content
from posters.youtube_poster import post_youtube_video

TODAY = os.environ.get("OVERRIDE_DATE", date.today().isoformat())
SLOT = os.environ.get("PLATFORM_SLOT", "all")  # morning|linkedin|noon|afternoon|evening|all


def post_slot(slot: str, question: dict, part: dict, video_paths: dict,
              copy_paths: dict, carousel_paths: dict) -> dict:
    """Post content for the given time slot."""
    results = {}
    cal_date = TODAY

    if slot in ("morning", "all"):
        # 06:00 — YouTube long-form
        yt_long_path = video_paths.get("long")
        if yt_long_path and Path(yt_long_path).exists():
            yt_meta = _load_yt_meta(copy_paths.get("youtube"), "long")
            result = _safe_post(post_youtube_video, yt_long_path, yt_meta,
                               video_paths.get("thumbnail"), "youtube_long")
            results["yt_long"] = result
            db.log_post(cal_date, question["slug"], part["part_number"],
                       "youtube_long", result.get("status", "error"),
                       result.get("video_id"), result.get("error"))

        # 07:00 — YouTube Short 1 + Instagram Short 1
        _post_short_pair("hook", question, part, video_paths, copy_paths, results, cal_date)

    if slot in ("linkedin", "all"):
        # 08:00 — LinkedIn carousel
        pdf_path = carousel_paths.get("pdf")
        li_caption = _load_text(copy_paths.get("linkedin"))
        if pdf_path and Path(pdf_path).exists():
            result = _safe_post(post_linkedin_carousel, pdf_path, li_caption, "linkedin_carousel")
            results["linkedin"] = result
            db.log_post(cal_date, question["slug"], part["part_number"],
                       "linkedin_carousel", result.get("status", "error"),
                       result.get("id"), result.get("error"))

    if slot in ("noon", "all"):
        # 12:30 — YouTube Short 2 + Instagram Short 2
        _post_short_pair("dry_run", question, part, video_paths, copy_paths, results, cal_date)

    if slot in ("afternoon", "all"):
        # 17:30 — YouTube Short 3 + Instagram Short 3
        _post_short_pair("code", question, part, video_paths, copy_paths, results, cal_date)

    if slot in ("evening", "all"):
        # 21:00 — YouTube Short 4 + Instagram Short 4
        _post_short_pair("dialogue", question, part, video_paths, copy_paths, results, cal_date)

    return results


def _post_short_pair(short_type: str, question: dict, part: dict,
                     video_paths: dict, copy_paths: dict, results: dict, cal_date: str):
    """Post one short to both YouTube and Instagram."""
    portrait_path = video_paths.get(f"short_{short_type}_portrait")
    ig_caption = _load_text(copy_paths.get("instagram", {}).get(short_type, ""))
    yt_meta = _load_yt_meta(copy_paths.get("youtube"), f"short_{short_type}")

    # YouTube Short
    if portrait_path and Path(portrait_path).exists():
        result = _safe_post(post_youtube_video, portrait_path, yt_meta, None, f"yt_short_{short_type}")
        results[f"yt_short_{short_type}"] = result
        db.log_post(cal_date, question["slug"], part["part_number"],
                   f"youtube_short_{short_type}", result.get("status", "error"),
                   result.get("video_id"), result.get("error"))
        if result.get("status") == "success":
            tg.send_post_result(f"YT Short {short_type}", "success", result.get("url", ""))

    # Instagram → Google Drive (manual posting)
    reel_path = video_paths.get(f"short_{short_type}_portrait")  # same file, square or portrait
    if reel_path and Path(reel_path).exists():
        result = _safe_post(
            upload_instagram_content,
            short_type, reel_path, ig_caption, cal_date,
            f"drive_ig_{short_type}",  # platform label for _safe_post
        )
        results[f"drive_ig_{short_type}"] = result
        db.log_post(cal_date, question["slug"], part["part_number"],
                   f"instagram_{short_type}", result.get("status", "error"),
                   result.get("video_link"), result.get("error"))
        if result.get("status") == "success":
            tg.send_post_result(
                f"IG {short_type} → Drive ✅",
                "success",
                result.get("folder_link", ""),
            )
        elif result.get("status") == "error":
            tg.send_error_alert(f"Drive upload {short_type}", result.get("error", ""), cal_date)


def _safe_post(fn, *args, **kwargs) -> dict:
    """Call posting function with retry on transient errors."""
    platform = args[-1] if args else "unknown"  # last arg is platform name
    for attempt in range(3):
        try:
            result = fn(*args[:-1])  # don't pass platform name to actual function
            return result
        except Exception as e:
            err = str(e)
            print(f"  [{platform}] Attempt {attempt+1}/3 failed: {err[:100]}")
            if attempt < 2:
                wait = [30, 120][attempt]
                print(f"  [{platform}] Retrying in {wait}s...")
                time.sleep(wait)
    return {"status": "error", "error": f"All 3 attempts failed"}


def _load_text(path: str) -> str:
    if path and Path(path).exists():
        return open(path).read()
    return ""


def _load_yt_meta(yt_path: str, video_type: str) -> dict:
    if yt_path and Path(yt_path).exists():
        data = json.load(open(yt_path))
        return data.get(video_type, data) if isinstance(data, dict) else {}
    return {}


def post_all_staggered(question: dict, part: dict, cal_date: str,
                        video_paths: dict, copy_paths: dict, carousel_paths: dict) -> dict:
    """Called from main.py in 'all' mode (dev/test). In production, each slot runs separately."""
    slot = os.environ.get("PLATFORM_SLOT", "all")
    return post_slot(slot, question, part, video_paths, copy_paths, carousel_paths)
