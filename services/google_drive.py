"""
Google Drive helpers for purchase invoice storage.
Used by account analysis API and the upload_data1_to_drive CLI.

Token source: MongoDB collection  `google_drive_token`  (single document).
When the access token is refreshed the updated values are written back to
that same document so it stays current across restarts.
"""
import mimetypes
import os
import uuid
from datetime import datetime
from io import BytesIO
from pathlib import Path
from typing import Iterable, Optional, Tuple

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload, MediaIoBaseDownload, MediaIoBaseUpload

SCOPES = ["https://www.googleapis.com/auth/drive.file"]
BASE_DIR = Path(__file__).resolve().parent.parent
PURCHASE_INVOICE_FOLDER_NAME = "Purchase_invoice"
_MONGO_TOKEN_COLLECTION = "google_drive_token"


# ---------------------------------------------------------------------------
# MongoDB token helpers
# ---------------------------------------------------------------------------

def _load_token_from_mongo() -> Optional[dict]:
    """Return the first document from the google_drive_token collection, or None."""
    try:
        from mongodb_client import get_collection  # local import to avoid circular dep
        col = get_collection(_MONGO_TOKEN_COLLECTION)
        return col.find_one({}, {"_id": 0})
    except Exception as exc:
        raise RuntimeError(f"Could not read Google Drive token from MongoDB: {exc}") from exc


def _save_token_to_mongo(creds: Credentials) -> None:
    """Persist refreshed credentials back to the MongoDB token document."""
    try:
        from mongodb_client import get_collection
        col = get_collection(_MONGO_TOKEN_COLLECTION)
        expiry_str = (
            creds.expiry.strftime("%Y-%m-%dT%H:%M:%S.%f") + "Z"
            if creds.expiry
            else None
        )
        update_fields = {
            "token": creds.token,
            "refresh_token": creds.refresh_token,
            "token_uri": creds.token_uri,
            "client_id": creds.client_id,
            "client_secret": creds.client_secret,
            "scopes": list(creds.scopes) if creds.scopes else [],
            "expiry": expiry_str,
        }
        col.update_one({}, {"$set": update_fields}, upsert=True)
    except Exception as exc:
        # Non-fatal — the service call can still proceed with in-memory creds
        print(f"[google_drive] Warning: could not persist refreshed token to MongoDB: {exc}")


def _creds_from_mongo_doc(doc: dict) -> Credentials:
    """Build a google.oauth2.credentials.Credentials object from a MongoDB token doc."""
    expiry = None
    if doc.get("expiry"):
        try:
            expiry_str = doc["expiry"].rstrip("Z")
            # Google auth library compares expiry against offset-naive utcnow(),
            # so we must store it as naive UTC (no tzinfo).
            expiry = datetime.fromisoformat(expiry_str).replace(tzinfo=None)
        except ValueError:
            pass

    return Credentials(
        token=doc.get("token"),
        refresh_token=doc.get("refresh_token"),
        token_uri=doc.get("token_uri", "https://oauth2.googleapis.com/token"),
        client_id=doc.get("client_id"),
        client_secret=doc.get("client_secret"),
        scopes=doc.get("scopes", SCOPES),
        expiry=expiry,
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def get_drive_service():
    """Return an authorised Google Drive v3 service using credentials from MongoDB."""
    doc = _load_token_from_mongo()
    if not doc:
        raise RuntimeError(
            "No Google Drive token document found in MongoDB collection "
            f"'{_MONGO_TOKEN_COLLECTION}'. Please insert the token document first."
        )

    creds = _creds_from_mongo_doc(doc)

    if not creds.valid:
        if creds.expired and creds.refresh_token:
            creds.refresh(Request())
            _save_token_to_mongo(creds)
        else:
            raise RuntimeError(
                "Google Drive credentials are invalid and cannot be refreshed. "
                "Please update the token document in MongoDB."
            )

    return build("drive", "v3", credentials=creds)


def authorize_drive_interactive() -> None:
    """First-time OAuth (browser). Saves resulting token to MongoDB."""
    doc = _load_token_from_mongo()
    client_id = (doc or {}).get("client_id", "")
    client_secret = (doc or {}).get("client_secret", "")

    if not client_id or not client_secret:
        raise RuntimeError(
            "client_id / client_secret not found in MongoDB token document."
        )

    client_config = {
        "installed": {
            "client_id": client_id,
            "client_secret": client_secret,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": ["http://localhost:8080/", "http://localhost"],
        }
    }
    flow = InstalledAppFlow.from_client_config(client_config, SCOPES)
    creds = flow.run_local_server(
        host="localhost",
        port=8080,
        authorization_prompt_message="Open this URL in your browser: {url}",
        success_message="Authentication complete. You can close this tab.",
    )
    _save_token_to_mongo(creds)


def _escape_drive_query_literal(value: str) -> str:
    return value.replace("\\", "\\\\").replace("'", "\\'")


def get_or_create_purchase_invoice_folder(service) -> str:
    """Return folder id for PURCHASE_INVOICE_FOLDER_NAME under My Drive root."""
    parent = "root"
    safe_name = _escape_drive_query_literal(PURCHASE_INVOICE_FOLDER_NAME)
    q = (
        "mimeType = 'application/vnd.google-apps.folder' "
        f"and name = '{safe_name}' "
        "and trashed = false "
        f"and '{parent}' in parents"
    )
    results = (
        service.files()
        .list(q=q, spaces="drive", fields="files(id, name)", pageSize=5)
        .execute()
    )
    found = results.get("files") or []
    if found:
        return found[0]["id"]

    body = {
        "name": PURCHASE_INVOICE_FOLDER_NAME,
        "mimeType": "application/vnd.google-apps.folder",
        "parents": [parent],
    }
    created = service.files().create(body=body, fields="id").execute()
    return created["id"]


def _ensure_anyone_with_link_reader(service, file_id: str) -> None:
    """Allow opening webViewLink without Google sign-in."""
    service.permissions().create(
        fileId=file_id,
        body={"type": "anyone", "role": "reader"},
        fields="id",
    ).execute()


def upload_invoice_bytes(
    data: bytes,
    filename: str,
    mime_type: str,
    *,
    drive_display_name: Optional[str] = None,
) -> dict:
    """
    Upload invoice bytes to the Purchase_invoice Drive folder.
    Returns dict with file_id, webViewLink, name.
    """
    service = get_drive_service()
    folder_id = get_or_create_purchase_invoice_folder(service)
    name = drive_display_name or filename
    media = MediaIoBaseUpload(BytesIO(data), mimetype=mime_type, resumable=True)
    metadata = {"name": name, "parents": [folder_id]}
    response = (
        service.files()
        .create(body=metadata, media_body=media, fields="id,name,webViewLink")
        .execute()
    )
    file_id = response["id"]
    _ensure_anyone_with_link_reader(service, file_id)
    refreshed = (
        service.files().get(fileId=file_id, fields="id,name,webViewLink").execute()
    )
    return {
        "file_id": file_id,
        "webViewLink": refreshed.get("webViewLink") or response.get("webViewLink"),
        "name": refreshed.get("name") or name,
    }


def build_drive_invoice_name(record_date: str, company_index: int, safe_filename: str) -> str:
    """Unique Drive object name to avoid collisions."""
    token = uuid.uuid4().hex[:8]
    return f"{record_date}_c{company_index}_{token}_{safe_filename}"


def download_drive_file(file_id: str) -> Tuple[bytes, str]:
    """Download file content from Drive by file id."""
    service = get_drive_service()
    request = service.files().get_media(fileId=file_id)
    buf = BytesIO()
    downloader = MediaIoBaseDownload(buf, request)
    done = False
    while not done:
        _, done = downloader.next_chunk()
    meta = service.files().get(fileId=file_id, fields="mimeType,name").execute()
    mime = meta.get("mimeType") or "application/octet-stream"
    return buf.getvalue(), mime


def iter_data1_files(data_dir: Path) -> Iterable[Path]:
    for path in data_dir.rglob("*"):
        if path.is_file():
            yield path


def upload_file_from_path(file_path: Path, folder_id: str, service) -> dict:
    """Upload a single local file (CLI batch helper)."""
    mime_type, _ = mimetypes.guess_type(str(file_path))
    media = MediaFileUpload(str(file_path), mimetype=mime_type, resumable=True)
    metadata = {"name": file_path.name, "parents": [folder_id]}
    response = (
        service.files()
        .create(body=metadata, media_body=media, fields="id,name,webViewLink")
        .execute()
    )
    file_id = response.get("id")
    if file_id:
        try:
            _ensure_anyone_with_link_reader(service, file_id)
            response = (
                service.files()
                .get(fileId=file_id, fields="id,name,webViewLink")
                .execute()
            )
        except Exception:
            pass
    return response
