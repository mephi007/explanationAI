"""
instagram_poster.py — Posts Reels to Instagram via Meta Graph API v19.
Videos must be at a public URL — we upload to GitHub Releases for free hosting.
"""

import os
import time
import requests

IG_TOKEN  = lambda: os.environ["INSTAGRAM_ACCESS_TOKEN"]
IG_ID     = lambda: os.environ["INSTAGRAM_BUSINESS_ACCOUNT_ID"]
GH_TOKEN  = lambda: os.environ.get("GITHUB_TOKEN", "")
GH_REPO   = lambda: os.environ.get("GITHUB_REPOSITORY", "")  # "owner/repo"

GRAPH_BASE = "https://graph.facebook.com/v19.0"


# ── GitHub Releases video hosting (free public URL) ──────────────────────────

def _get_or_create_release(tag: str = "daily-content") -> dict:
    """Get or create a GitHub release to host video files."""
    headers = {"Authorization": f"token {GH_TOKEN()}", "Accept": "application/vnd.github.v3+json"}
    repo = GH_REPO()

    # Try to get existing release
    resp = requests.get(
        f"https://api.github.com/repos/{repo}/releases/tags/{tag}",
        headers=headers
    )
    if resp.ok:
        return resp.json()

    # Create release
    resp = requests.post(
        f"https://api.github.com/repos/{repo}/releases",
        headers=headers,
        json={
            "tag_name": tag,
            "name": "Daily Content Assets",
            "body": "Auto-generated video assets for social media posting.",
            "draft": False,
            "prerelease": True,
        }
    )
    resp.raise_for_status()
    return resp.json()


def upload_to_github_release(file_path: str, filename: str) -> str:
    """Upload a file to GitHub Releases and return the public download URL."""
    if not GH_TOKEN() or not GH_REPO():
        raise RuntimeError("GITHUB_TOKEN and GITHUB_REPOSITORY must be set for video hosting")

    release = _get_or_create_release()
    upload_url = release["upload_url"].split("{")[0]  # strip {?name,label}

    # Delete existing asset with same name
    for asset in release.get("assets", []):
        if asset["name"] == filename:
            requests.delete(
                f"https://api.github.com/repos/{GH_REPO()}/releases/assets/{asset['id']}",
                headers={"Authorization": f"token {GH_TOKEN()}"}
            )
            break

    # Upload new asset
    with open(file_path, "rb") as f:
        resp = requests.post(
            f"{upload_url}?name={filename}",
            headers={
                "Authorization": f"token {GH_TOKEN()}",
                "Content-Type": "video/mp4",
            },
            data=f
        )
    resp.raise_for_status()
    url = resp.json()["browser_download_url"]
    print(f"[github] Video uploaded: {url}")
    return url


# ── Meta Graph API posting ────────────────────────────────────────────────────

def _poll_container(container_id: str, timeout_s: int = 600) -> bool:
    """Poll until video container is FINISHED processing."""
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        resp = requests.get(
            f"{GRAPH_BASE}/{container_id}",
            params={"fields": "status_code,status", "access_token": IG_TOKEN()}
        )
        resp.raise_for_status()
        data = resp.json()
        status = data.get("status_code", "")
        print(f"[instagram] Container status: {status}")
        if status == "FINISHED":
            return True
        if status in ("ERROR", "EXPIRED"):
            raise RuntimeError(f"Instagram container failed: {data.get('status', 'unknown')}")
        time.sleep(15)
    raise TimeoutError("Instagram video processing timed out after 10 minutes")


def post_instagram_reel(video_path: str, caption: str) -> dict:
    """
    Upload a Reel to Instagram.
    Flow: upload to GitHub Releases → create IG container → poll → publish.
    """
    import os as _os
    filename = f"reel_{int(time.time())}_{_os.path.basename(video_path)}"

    # 1. Get public URL
    print(f"[instagram] Uploading to GitHub Releases for public URL...")
    video_url = upload_to_github_release(video_path, filename)

    # 2. Create media container
    print(f"[instagram] Creating Reel container...")
    resp = requests.post(
        f"{GRAPH_BASE}/{IG_ID()}/media",
        params={
            "media_type": "REELS",
            "video_url": video_url,
            "caption": caption[:2200],  # IG caption limit
            "access_token": IG_TOKEN(),
        }
    )
    resp.raise_for_status()
    container_id = resp.json()["id"]
    print(f"[instagram] Container: {container_id}")

    # 3. Wait for processing
    _poll_container(container_id)

    # 4. Publish
    pub_resp = requests.post(
        f"{GRAPH_BASE}/{IG_ID()}/media_publish",
        params={"creation_id": container_id, "access_token": IG_TOKEN()}
    )
    pub_resp.raise_for_status()
    post_id = pub_resp.json()["id"]
    print(f"[instagram] Published: {post_id}")

    return {"status": "success", "id": post_id,
            "url": f"https://www.instagram.com/p/{post_id}/"}


def post_instagram_image(image_path: str, caption: str) -> dict:
    """Post a static image (for carousel cover if needed)."""
    filename = f"img_{int(time.time())}_{os.path.basename(image_path)}"
    image_url = upload_to_github_release(image_path, filename)

    resp = requests.post(
        f"{GRAPH_BASE}/{IG_ID()}/media",
        params={"image_url": image_url, "caption": caption[:2200], "access_token": IG_TOKEN()}
    )
    resp.raise_for_status()
    container_id = resp.json()["id"]
    time.sleep(5)

    pub = requests.post(
        f"{GRAPH_BASE}/{IG_ID()}/media_publish",
        params={"creation_id": container_id, "access_token": IG_TOKEN()}
    )
    pub.raise_for_status()
    post_id = pub.json()["id"]
    return {"status": "success", "id": post_id}
