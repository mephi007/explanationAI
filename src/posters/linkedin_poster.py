"""
linkedin_poster.py — Posts to LinkedIn via official UGC Posts API v2.
Supports: Document post (carousel PDF) + Video post (long-form).
"""

import os
import time
import requests

TOKEN = lambda: os.environ["LINKEDIN_ACCESS_TOKEN"]
URN   = lambda: os.environ["LINKEDIN_PERSON_URN"]  # urn:li:person:XXXXX

BASE = "https://api.linkedin.com/v2"
HEADERS = lambda: {
    "Authorization": f"Bearer {TOKEN()}",
    "Content-Type": "application/json",
    "X-Restli-Protocol-Version": "2.0.0",
    "LinkedIn-Version": "202401",
}


def _ugc_post(payload: dict) -> dict:
    resp = requests.post(f"{BASE}/ugcPosts", headers=HEADERS(), json=payload)
    if not resp.ok:
        raise RuntimeError(f"LinkedIn UGC post failed {resp.status_code}: {resp.text[:300]}")
    post_id = resp.headers.get("x-restli-id", "unknown")
    return {"status": "success", "id": post_id,
            "url": f"https://www.linkedin.com/feed/update/{post_id}/"}


def _register_upload(file_type: str) -> tuple[str, str]:
    """Register upload for video or document. Returns (upload_url, asset_urn)."""
    recipe_map = {
        "video":    "urn:li:digitalmediaRecipe:feedshare-video",
        "document": "urn:li:digitalmediaRecipe:feedshare-document",
    }
    payload = {
        "registerUploadRequest": {
            "owner": URN(),
            "recipes": [recipe_map[file_type]],
            "serviceRelationships": [{
                "identifier": "urn:li:userGeneratedContent",
                "relationshipType": "OWNER",
            }],
            "supportedUploadMechanism": ["SYNCHRONOUS_UPLOAD"],
        }
    }
    resp = requests.post(f"{BASE}/assets?action=registerUpload",
                         headers=HEADERS(), json=payload)
    resp.raise_for_status()
    data = resp.json()["value"]
    upload_url = data["uploadMechanism"]["com.linkedin.digitalmedia.uploading.MediaUploadHttpRequest"]["uploadUrl"]
    asset = data["asset"]
    return upload_url, asset


def _upload_file(upload_url: str, file_path: str, content_type: str):
    with open(file_path, "rb") as f:
        resp = requests.put(upload_url, data=f, headers={
            "Authorization": f"Bearer {TOKEN()}",
            "Content-Type": content_type,
        })
    if not resp.ok:
        raise RuntimeError(f"Upload failed {resp.status_code}: {resp.text[:200]}")


def post_linkedin_carousel(pdf_path: str, caption: str) -> dict:
    """
    Upload carousel PDF as LinkedIn Document post.
    This renders as a swipeable carousel in the feed.
    """
    print(f"[linkedin] Uploading carousel PDF: {pdf_path}")

    # 1. Register
    upload_url, asset = _register_upload("document")

    # 2. Upload PDF
    _upload_file(upload_url, pdf_path, "application/pdf")
    time.sleep(3)  # Let LinkedIn process

    # 3. Post
    payload = {
        "author": URN(),
        "lifecycleState": "PUBLISHED",
        "specificContent": {
            "com.linkedin.ugc.ShareContent": {
                "shareCommentary": {"text": caption},
                "shareMediaCategory": "DOCUMENT",
                "media": [{"status": "READY", "media": asset}],
            }
        },
        "visibility": {"com.linkedin.ugc.MemberNetworkVisibility": "PUBLIC"},
    }
    result = _ugc_post(payload)
    print(f"[linkedin] Carousel posted: {result.get('url','')}")
    return result


def post_linkedin_video(video_path: str, caption: str) -> dict:
    """Upload and post a video (long-form or short)."""
    print(f"[linkedin] Uploading video: {video_path}")

    upload_url, asset = _register_upload("video")
    _upload_file(upload_url, video_path, "video/mp4")
    time.sleep(8)  # LinkedIn needs time to process video

    payload = {
        "author": URN(),
        "lifecycleState": "PUBLISHED",
        "specificContent": {
            "com.linkedin.ugc.ShareContent": {
                "shareCommentary": {"text": caption},
                "shareMediaCategory": "VIDEO",
                "media": [{"status": "READY", "media": asset}],
            }
        },
        "visibility": {"com.linkedin.ugc.MemberNetworkVisibility": "PUBLIC"},
    }
    result = _ugc_post(payload)
    print(f"[linkedin] Video posted: {result.get('url','')}")
    return result


def post_linkedin_text(text: str) -> dict:
    """Text-only post (fallback if PDF/video upload fails)."""
    payload = {
        "author": URN(),
        "lifecycleState": "PUBLISHED",
        "specificContent": {
            "com.linkedin.ugc.ShareContent": {
                "shareCommentary": {"text": text},
                "shareMediaCategory": "NONE",
            }
        },
        "visibility": {"com.linkedin.ugc.MemberNetworkVisibility": "PUBLIC"},
    }
    return _ugc_post(payload)
