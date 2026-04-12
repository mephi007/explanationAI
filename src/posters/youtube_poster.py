"""
youtube_poster.py — Uploads videos to YouTube via Data API v3.
Uses resumable upload for large files (long-form).
Handles: Shorts (<60s) and long-form (10-15 min) with chapters.
"""

import os
import time
import requests

YT_CLIENT_ID     = lambda: os.environ["YOUTUBE_CLIENT_ID"]
YT_CLIENT_SECRET = lambda: os.environ["YOUTUBE_CLIENT_SECRET"]
YT_REFRESH_TOKEN = lambda: os.environ["YOUTUBE_REFRESH_TOKEN"]


def _get_access_token() -> str:
    resp = requests.post("https://oauth2.googleapis.com/token", data={
        "client_id":     YT_CLIENT_ID(),
        "client_secret": YT_CLIENT_SECRET(),
        "refresh_token": YT_REFRESH_TOKEN(),
        "grant_type":    "refresh_token",
    })
    resp.raise_for_status()
    return resp.json()["access_token"]


def _headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def post_youtube_video(video_path: str, metadata: dict,
                       thumbnail_path: str = None) -> dict:
    """
    Upload a video to YouTube with full metadata.
    metadata keys: title, description, tags, category_id
    Returns dict with video_id and url.
    """
    token = _get_access_token()
    file_size = os.path.getsize(video_path)

    title       = metadata.get("title", "DSA Interview Question")[:100]
    description = metadata.get("description", "")[:5000]
    tags        = metadata.get("tags", [])
    category_id = metadata.get("category_id", "27")  # Education

    # Determine if Short based on filename or metadata hint
    is_short = "short" in video_path.lower() or metadata.get("is_short", False)

    # Append #Shorts to title for Shorts (helps YouTube classify)
    if is_short and "#Shorts" not in title:
        title = (title[:90] + " #Shorts") if len(title) > 90 else title + " #Shorts"
        if "#Shorts" not in description:
            description = "#Shorts\n\n" + description

    # ── 1. Init resumable upload ──────────────────────────────────────
    init_resp = requests.post(
        "https://www.googleapis.com/upload/youtube/v3/videos"
        "?uploadType=resumable&part=snippet,status",
        headers={
            **_headers(token),
            "Content-Type": "application/json",
            "X-Upload-Content-Type": "video/mp4",
            "X-Upload-Content-Length": str(file_size),
        },
        json={
            "snippet": {
                "title": title,
                "description": description,
                "tags": tags[:500],  # total tag chars limit
                "categoryId": category_id,
                "defaultLanguage": "en",
            },
            "status": {
                "privacyStatus": "public",
                "selfDeclaredMadeForKids": False,
                "madeForKids": False,
            },
        }
    )
    init_resp.raise_for_status()
    upload_url = init_resp.headers["Location"]

    # ── 2. Upload in chunks (5MB) ─────────────────────────────────────
    chunk_size = 5 * 1024 * 1024
    uploaded = 0
    video_id = None

    print(f"[youtube] Uploading {file_size/1024/1024:.1f}MB: {title[:50]}")

    with open(video_path, "rb") as f:
        while uploaded < file_size:
            chunk = f.read(chunk_size)
            end = uploaded + len(chunk) - 1

            upload_resp = requests.put(
                upload_url,
                headers={
                    **_headers(token),
                    "Content-Length": str(len(chunk)),
                    "Content-Range": f"bytes {uploaded}-{end}/{file_size}",
                    "Content-Type": "video/mp4",
                },
                data=chunk
            )

            if upload_resp.status_code in (200, 201):
                video_id = upload_resp.json().get("id")
                print(f"[youtube] Upload complete: {video_id}")
                break
            elif upload_resp.status_code == 308:
                range_header = upload_resp.headers.get("Range", f"bytes=0-{end}")
                uploaded = int(range_header.split("-")[1]) + 1
                pct = uploaded / file_size * 100
                print(f"[youtube] Progress: {pct:.0f}%")
            else:
                raise RuntimeError(
                    f"YouTube upload error {upload_resp.status_code}: {upload_resp.text[:200]}"
                )

    if not video_id:
        raise RuntimeError("YouTube upload completed but no video_id returned")

    # ── 3. Set thumbnail ──────────────────────────────────────────────
    if thumbnail_path and os.path.exists(thumbnail_path) and not is_short:
        try:
            token = _get_access_token()  # refresh in case it expired
            thumb_resp = requests.post(
                f"https://www.googleapis.com/upload/youtube/v3/thumbnails/set"
                f"?videoId={video_id}&uploadType=media",
                headers={**_headers(token), "Content-Type": "image/jpeg"},
                data=open(thumbnail_path, "rb").read()
            )
            if thumb_resp.ok:
                print(f"[youtube] Thumbnail set")
        except Exception as e:
            print(f"[youtube] Thumbnail failed (non-fatal): {e}")

    url = f"https://youtu.be/{video_id}"
    print(f"[youtube] Published: {url}")
    return {"status": "success", "video_id": video_id, "url": url}


def add_to_playlist(video_id: str, playlist_id: str):
    """Add video to a playlist (e.g. 'Two Pointer Series')."""
    token = _get_access_token()
    resp = requests.post(
        "https://www.googleapis.com/youtube/v3/playlistItems?part=snippet",
        headers={**_headers(token), "Content-Type": "application/json"},
        json={
            "snippet": {
                "playlistId": playlist_id,
                "resourceId": {"kind": "youtube#video", "videoId": video_id},
            }
        }
    )
    if resp.ok:
        print(f"[youtube] Added to playlist {playlist_id}")
    else:
        print(f"[youtube] Playlist add failed (non-fatal): {resp.text[:100]}")
