"""
Google Drive helpers for purchase invoice storage.
Used by account analysis API and the upload_data1_to_drive CLI.
"""
import mimetypes
import os
import uuid
from io import BytesIO
from pathlib import Path
from typing import Iterable, Optional, Tuple

from dotenv import load_dotenv
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload, MediaIoBaseDownload, MediaIoBaseUpload

SCOPES = ["https://www.googleapis.com/auth/drive.file"]
BASE_DIR = Path(__file__).resolve().parent.parent
TOKEN_FILE = BASE_DIR / "google_drive_token.json"
PURCHASE_INVOICE_FOLDER_NAME = "Purchase_invoice"


def _first_env(*keys: str, default: str = "") -> str:
    for key in keys:
        value = os.getenv(key)
        if value:
            return value.strip()
    return default


def get_drive_service():
    load_dotenv(BASE_DIR / ".env")

    client_id = _first_env("GOOGLE_CLIENT_ID", "client_ID", "CLIENT_ID")
    client_secret = _first_env("GOOGLE_CLIENT_SECRET", "Client_Secret", "CLIENT_SECRET")

    if not client_id or not client_secret:
        raise RuntimeError(
            "Missing Google credentials in .env. Set GOOGLE_CLIENT_ID/GOOGLE_CLIENT_SECRET "
            "(or existing client_ID/Client_Secret)."
        )

    creds = None
    if TOKEN_FILE.exists():
        creds = Credentials.from_authorized_user_file(str(TOKEN_FILE), SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            raise RuntimeError(
                "Google Drive is not authorized. Run: python upload_data1_to_drive.py "
                "(from the backend folder) once to create google_drive_token.json."
            )
        TOKEN_FILE.write_text(creds.to_json(), encoding="utf-8")

    return build("drive", "v3", credentials=creds)


def authorize_drive_interactive() -> None:
    """First-time OAuth (browser). Used by upload_data1_to_drive.py CLI only."""
    load_dotenv(BASE_DIR / ".env")
    client_id = _first_env("GOOGLE_CLIENT_ID", "client_ID", "CLIENT_ID")
    client_secret = _first_env("GOOGLE_CLIENT_SECRET", "Client_Secret", "CLIENT_SECRET")
    if not client_id or not client_secret:
        raise RuntimeError(
            "Missing Google credentials in .env. Set GOOGLE_CLIENT_ID/GOOGLE_CLIENT_SECRET."
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
    TOKEN_FILE.write_text(creds.to_json(), encoding="utf-8")


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
