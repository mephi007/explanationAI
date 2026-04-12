"""
drive_uploader.py — Uploads Instagram content to Google Drive for manual posting.

Uses a Google service account (GOOGLE_SERVICE_ACCOUNT_JSON env var — full JSON string).
Folder layout inside GOOGLE_DRIVE_FOLDER_ID:
  [root folder] / [YYYY-MM-DD] / short_{type}.mp4
                               / ig_{type}_caption.txt
"""

import io
import json
import os
from pathlib import Path

DRIVE_FOLDER_ID       = lambda: os.environ.get("GOOGLE_DRIVE_FOLDER_ID", "")
SERVICE_ACCOUNT_JSON  = lambda: os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON", "")


def _get_drive_service():
    """Build an authenticated Drive v3 service from the service account JSON."""
    from google.oauth2 import service_account
    from googleapiclient.discovery import build

    sa_info = json.loads(SERVICE_ACCOUNT_JSON())
    creds = service_account.Credentials.from_service_account_info(
        sa_info,
        scopes=["https://www.googleapis.com/auth/drive.file"],
    )
    return build("drive", "v3", credentials=creds, cache_discovery=False)


def _get_or_create_folder(service, name: str, parent_id: str) -> str:
    """Return the id of a named folder inside parent_id, creating it if absent."""
    query = (
        f"name='{name}' and mimeType='application/vnd.google-apps.folder' "
        f"and '{parent_id}' in parents and trashed=false"
    )
    results = service.files().list(q=query, fields="files(id)").execute()
    files = results.get("files", [])
    if files:
        return files[0]["id"]

    meta = {
        "name": name,
        "mimeType": "application/vnd.google-apps.folder",
        "parents": [parent_id],
    }
    folder = service.files().create(body=meta, fields="id").execute()
    return folder["id"]


def _share_anyone(service, file_id: str):
    """Grant read access to anyone with the link."""
    service.permissions().create(
        fileId=file_id,
        body={"type": "anyone", "role": "reader"},
    ).execute()


def _upload_binary(service, file_path: str, folder_id: str, mime_type: str) -> dict:
    """Upload a local file to Drive and return its file metadata dict."""
    from googleapiclient.http import MediaFileUpload

    meta = {"name": Path(file_path).name, "parents": [folder_id]}
    media = MediaFileUpload(file_path, mimetype=mime_type, resumable=True)
    uploaded = service.files().create(
        body=meta, media_body=media, fields="id,name,webViewLink"
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
        body=meta, media_body=media, fields="id,name,webViewLink"
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
    if not DRIVE_FOLDER_ID():
        raise RuntimeError("GOOGLE_DRIVE_FOLDER_ID env var is not set")
    if not SERVICE_ACCOUNT_JSON():
        raise RuntimeError("GOOGLE_SERVICE_ACCOUNT_JSON env var is not set")

    service = _get_drive_service()

    # Create/find the date sub-folder
    date_folder_id = _get_or_create_folder(service, date_str, DRIVE_FOLDER_ID())

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
