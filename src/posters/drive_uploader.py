"""
drive_uploader.py — Uploads all generated content to Google Drive for manual posting.

Uses a Google service account (GOOGLE_SERVICE_ACCOUNT_JSON env var — full JSON string).
Folder layout inside GOOGLE_DRIVE_FOLDER_ID:

  [root folder] /
    └── YYYY-MM-DD /
          ├── youtube /
          │     ├── long_form.mp4
          │     ├── short_hook.mp4
          │     ├── short_dry_run.mp4
          │     ├── short_code.mp4
          │     ├── short_dialogue.mp4
          │     ├── thumbnail.jpg
          │     └── metadata.json   ← titles, descriptions, tags
          ├── instagram /
          │     ├── short_hook.mp4
          │     ├── short_dry_run.mp4
          │     ├── short_code.mp4
          │     ├── short_dialogue.mp4
          │     ├── caption_hook.txt
          │     ├── caption_dry_run.txt
          │     ├── caption_code.txt
          │     └── caption_dialogue.txt
          └── linkedin /
                ├── carousel.pdf
                └── caption.txt
"""

import io
import json
import os
import re
from pathlib import Path

DRIVE_FOLDER_ID       = lambda: os.environ.get("GOOGLE_DRIVE_FOLDER_ID", "")
SERVICE_ACCOUNT_JSON  = lambda: os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON", "")


def _extract_folder_id(value: str) -> str:
    """
    Accept either a raw Drive folder ID or a full Drive URL.
    Returns normalized folder ID.
    """
    raw = (value or "").strip()
    if not raw:
        return ""

    # Already an ID in most cases.
    if "/" not in raw and "?" not in raw:
        return raw

    # Common Drive URL forms:
    # - https://drive.google.com/drive/folders/<ID>
    # - https://drive.google.com/open?id=<ID>
    m = re.search(r"/folders/([A-Za-z0-9_-]+)", raw)
    if m:
        return m.group(1)

    m = re.search(r"[?&]id=([A-Za-z0-9_-]+)", raw)
    if m:
        return m.group(1)

    return raw


def _root_folder_id() -> str:
    folder_id = _extract_folder_id(DRIVE_FOLDER_ID())
    if not folder_id:
        raise RuntimeError("GOOGLE_DRIVE_FOLDER_ID env var is not set")
    return folder_id


def _get_drive_service():
    """Build an authenticated Drive v3 service from the service account JSON."""
    from google.oauth2 import service_account
    from googleapiclient.discovery import build

    sa_info = json.loads(SERVICE_ACCOUNT_JSON())
    creds = service_account.Credentials.from_service_account_info(
        sa_info,
        # Use full Drive scope so service account can access explicitly shared folders.
        scopes=["https://www.googleapis.com/auth/drive"],
    )
    return build("drive", "v3", credentials=creds, cache_discovery=False)


def _service_account_email() -> str:
    try:
        return json.loads(SERVICE_ACCOUNT_JSON()).get("client_email", "service-account")
    except Exception:
        return "service-account"


def _assert_root_access(service, root_id: str) -> None:
    """Validate that service account can read the configured root folder."""
    try:
        service.files().get(
            fileId=root_id,
            fields="id,name",
            supportsAllDrives=True,
        ).execute()
    except Exception as e:
        email = _service_account_email()
        raise RuntimeError(
            "Google Drive root folder not accessible. "
            f"Share folder '{root_id}' with service account '{email}' "
            "as Editor (or place it in a shared drive where this account has access). "
            f"Original error: {e}"
        ) from e


def _get_or_create_folder(service, name: str, parent_id: str) -> str:
    """Return the id of a named folder inside parent_id, creating it if absent."""
    query = (
        f"name='{name}' and mimeType='application/vnd.google-apps.folder' "
        f"and '{parent_id}' in parents and trashed=false"
    )
    results = service.files().list(
        q=query,
        fields="files(id)",
        supportsAllDrives=True,
        includeItemsFromAllDrives=True,
    ).execute()
    files = results.get("files", [])
    if files:
        return files[0]["id"]

    meta = {
        "name": name,
        "mimeType": "application/vnd.google-apps.folder",
        "parents": [parent_id],
    }
    folder = service.files().create(
        body=meta,
        fields="id",
        supportsAllDrives=True,
    ).execute()
    return folder["id"]


def _share_anyone(service, file_id: str):
    """Grant read access to anyone with the link."""
    service.permissions().create(
        fileId=file_id,
        body={"type": "anyone", "role": "reader"},
        supportsAllDrives=True,
    ).execute()


def _upload_binary(service, file_path: str, folder_id: str, mime_type: str) -> dict:
    """Upload a local file to Drive and return its file metadata dict."""
    from googleapiclient.http import MediaFileUpload

    meta = {"name": Path(file_path).name, "parents": [folder_id]}
    media = MediaFileUpload(file_path, mimetype=mime_type, resumable=True)
    uploaded = service.files().create(
        body=meta, media_body=media, fields="id,name,webViewLink", supportsAllDrives=True
    ).execute()
    _share_anyone(service, uploaded["id"])
    return uploaded


def _upload_text(service, content: str, filename: str, folder_id: str) -> dict:
    """Upload a UTF-8 string as a .txt file to Drive and return its metadata."""
    from googleapiclient.http import MediaIoBaseUpload

    meta = {"name": filename, "parents": [folder_id]}
    media = MediaIoBaseUpload(
        io.BytesIO(content.encode("utf-8")), mimetype="text/plain", resumable=False
    )
    uploaded = service.files().create(
        body=meta, media_body=media, fields="id,name,webViewLink", supportsAllDrives=True
    ).execute()
    _share_anyone(service, uploaded["id"])
    return uploaded


def upload_instagram_content(
    short_type: str,
    video_path: str,
    caption: str,
    date_str: str,
) -> dict:
    """
    Upload one short video + its Instagram caption to Google Drive.

    Files land at:  [GOOGLE_DRIVE_FOLDER_ID] / [date_str] / {short_type}.mp4
                                                            / ig_{short_type}_caption.txt

    Returns:
        {
            "status": "success",
            "short_type": ...,
            "video_link": <Drive view URL>,
            "caption_link": <Drive view URL>,
            "folder_link": <Drive folder URL>,
        }
    """
    root_id = _root_folder_id()
    if not SERVICE_ACCOUNT_JSON():
        raise RuntimeError("GOOGLE_SERVICE_ACCOUNT_JSON env var is not set")

    service = _get_drive_service()
    _assert_root_access(service, root_id)

    # Create/find the date sub-folder
    date_folder_id = _get_or_create_folder(service, date_str, root_id)

    # Upload MP4
    print(f"[drive] Uploading {short_type} video ({Path(video_path).name})...")
    video_file = _upload_binary(service, video_path, date_folder_id, "video/mp4")
    video_link = video_file.get("webViewLink", "")
    print(f"[drive] Video → {video_link}")

    # Upload caption .txt
    caption_filename = f"ig_{short_type}_caption.txt"
    caption_file = _upload_text(service, caption or "", caption_filename, date_folder_id)
    caption_link = caption_file.get("webViewLink", "")
    print(f"[drive] Caption → {caption_link}")

    folder_link = f"https://drive.google.com/drive/folders/{date_folder_id}"
    return {
        "status": "success",
        "short_type": short_type,
        "video_link": video_link,
        "caption_link": caption_link,
        "folder_link": folder_link,
    }


def upload_all_to_drive(
    question: dict,
    part: dict,
    cal_date: str,
    video_paths: dict,
    copy_paths: dict,
    carousel_paths: dict,
) -> dict:
    """
    Upload all generated content to Google Drive organised by platform.

    Returns:
        {
            "status": "success" | "partial",
            "date_folder_link": ...,
            "youtube_folder_link": ...,
            "instagram_folder_link": ...,
            "linkedin_folder_link": ...,
            "uploaded": [list of relative paths uploaded],
            "errors": [list of error strings],
        }
    """
    root_id = _root_folder_id()
    if not SERVICE_ACCOUNT_JSON():
        raise RuntimeError("GOOGLE_SERVICE_ACCOUNT_JSON env var is not set")

    from googleapiclient.http import MediaFileUpload

    service = _get_drive_service()
    _assert_root_access(service, root_id)
    uploaded = []
    errors = []

    # ── Root date folder ─────────────────────────────────────────────
    date_folder_id = _get_or_create_folder(service, cal_date, root_id)
    date_folder_link = f"https://drive.google.com/drive/folders/{date_folder_id}"
    print(f"[drive] Date folder: {date_folder_link}")

    # ── YouTube ──────────────────────────────────────────────────────
    yt_folder_id = _get_or_create_folder(service, "youtube", date_folder_id)
    yt_folder_link = f"https://drive.google.com/drive/folders/{yt_folder_id}"

    yt_videos = {
        "long_form.mp4":        video_paths.get("long"),
        "short_hook.mp4":       video_paths.get("short_hook_portrait"),
        "short_dry_run.mp4":    video_paths.get("short_dry_run_portrait"),
        "short_code.mp4":       video_paths.get("short_code_portrait"),
        "short_dialogue.mp4":   video_paths.get("short_dialogue_portrait"),
    }
    for dest_name, src_path in yt_videos.items():
        if src_path and Path(src_path).exists():
            try:
                meta = {"name": dest_name, "parents": [yt_folder_id]}
                media = MediaFileUpload(src_path, mimetype="video/mp4", resumable=True)
                f = service.files().create(
                    body=meta, media_body=media, fields="id", supportsAllDrives=True
                ).execute()
                _share_anyone(service, f["id"])
                uploaded.append(f"youtube/{dest_name}")
                print(f"[drive] youtube/{dest_name} ✓")
            except Exception as e:
                errors.append(f"youtube/{dest_name}: {e}")

    thumb_path = video_paths.get("thumbnail")
    if thumb_path and Path(thumb_path).exists():
        try:
            meta = {"name": "thumbnail.jpg", "parents": [yt_folder_id]}
            media = MediaFileUpload(thumb_path, mimetype="image/jpeg", resumable=False)
            f = service.files().create(
                body=meta, media_body=media, fields="id", supportsAllDrives=True
            ).execute()
            _share_anyone(service, f["id"])
            uploaded.append("youtube/thumbnail.jpg")
        except Exception as e:
            errors.append(f"youtube/thumbnail: {e}")

    yt_meta_path = copy_paths.get("youtube")
    if yt_meta_path and Path(yt_meta_path).exists():
        try:
            meta = {"name": "metadata.json", "parents": [yt_folder_id]}
            media = MediaFileUpload(yt_meta_path, mimetype="application/json", resumable=False)
            f = service.files().create(
                body=meta, media_body=media, fields="id", supportsAllDrives=True
            ).execute()
            _share_anyone(service, f["id"])
            uploaded.append("youtube/metadata.json")
        except Exception as e:
            errors.append(f"youtube/metadata.json: {e}")

    # ── Instagram ────────────────────────────────────────────────────
    ig_folder_id = _get_or_create_folder(service, "instagram", date_folder_id)
    ig_folder_link = f"https://drive.google.com/drive/folders/{ig_folder_id}"
    ig_captions = copy_paths.get("instagram", {})

    for short_type in ["hook", "dry_run", "code", "dialogue"]:
        src_path = video_paths.get(f"short_{short_type}_portrait")
        if src_path and Path(src_path).exists():
            try:
                dest_name = f"short_{short_type}.mp4"
                meta = {"name": dest_name, "parents": [ig_folder_id]}
                media = MediaFileUpload(src_path, mimetype="video/mp4", resumable=True)
                f = service.files().create(
                    body=meta, media_body=media, fields="id", supportsAllDrives=True
                ).execute()
                _share_anyone(service, f["id"])
                uploaded.append(f"instagram/{dest_name}")
                print(f"[drive] instagram/{dest_name} ✓")
            except Exception as e:
                errors.append(f"instagram/short_{short_type}.mp4: {e}")

        cap_path = ig_captions.get(short_type, "")
        if cap_path and Path(cap_path).exists():
            try:
                caption_text = open(cap_path).read()
                _upload_text(service, caption_text, f"caption_{short_type}.txt", ig_folder_id)
                uploaded.append(f"instagram/caption_{short_type}.txt")
            except Exception as e:
                errors.append(f"instagram/caption_{short_type}.txt: {e}")

    # ── LinkedIn ─────────────────────────────────────────────────────
    li_folder_id = _get_or_create_folder(service, "linkedin", date_folder_id)
    li_folder_link = f"https://drive.google.com/drive/folders/{li_folder_id}"

    pdf_path = carousel_paths.get("pdf")
    if pdf_path and Path(pdf_path).exists():
        try:
            meta = {"name": "carousel.pdf", "parents": [li_folder_id]}
            media = MediaFileUpload(pdf_path, mimetype="application/pdf", resumable=False)
            f = service.files().create(
                body=meta, media_body=media, fields="id", supportsAllDrives=True
            ).execute()
            _share_anyone(service, f["id"])
            uploaded.append("linkedin/carousel.pdf")
            print(f"[drive] linkedin/carousel.pdf ✓")
        except Exception as e:
            errors.append(f"linkedin/carousel.pdf: {e}")

    li_cap_path = copy_paths.get("linkedin")
    if li_cap_path and Path(li_cap_path).exists():
        try:
            _upload_text(service, open(li_cap_path).read(), "caption.txt", li_folder_id)
            uploaded.append("linkedin/caption.txt")
        except Exception as e:
            errors.append(f"linkedin/caption.txt: {e}")

    status = "partial" if errors else "success"
    print(f"[drive] Done — {len(uploaded)} files uploaded, {len(errors)} errors")
    return {
        "status": status,
        "date_folder_link": date_folder_link,
        "youtube_folder_link": yt_folder_link,
        "instagram_folder_link": ig_folder_link,
        "linkedin_folder_link": li_folder_link,
        "uploaded": uploaded,
        "errors": errors,
    }
