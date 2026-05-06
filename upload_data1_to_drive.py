import mimetypes
import os
from pathlib import Path
from typing import Iterable

from dotenv import load_dotenv
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload


SCOPES = ["https://www.googleapis.com/auth/drive.file"]
BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data1"
TOKEN_FILE = BASE_DIR / "google_drive_token.json"

# All uploads go under this folder (created in Drive if missing).
PURCHASE_INVOICE_FOLDER_NAME = "Purchase_invoice"


def _first_env(*keys: str, default: str = "") -> str:
    for key in keys:
        value = os.getenv(key)
        if value:
            return value.strip()
    return default


def _iter_files(directory: Path) -> Iterable[Path]:
    for path in directory.rglob("*"):
        if path.is_file():
            yield path


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
            client_config = {
                "installed": {
                    "client_id": client_id,
                    "client_secret": client_secret,
                    "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                    "token_uri": "https://oauth2.googleapis.com/token",
                    # FIX: run_local_server always uses "http://localhost:<port>/" (trailing slash, no path).
                    # These must exactly match what's registered in Google Cloud Console.
                    "redirect_uris": [
                        "http://localhost:8080/",
                        "http://localhost",
                    ],
                }
            }
            flow = InstalledAppFlow.from_client_config(client_config, SCOPES)
            # FIX: run_local_server sends redirect_uri = http://localhost:8080/ automatically.
            # Do NOT pass a custom redirect_uri — let the library handle it.
            creds = flow.run_local_server(
                host="localhost",
                port=8080,
                authorization_prompt_message="Open this URL in your browser: {url}",
                success_message="Authentication complete. You can close this tab.",
            )

        TOKEN_FILE.write_text(creds.to_json(), encoding="utf-8")

    return build("drive", "v3", credentials=creds)


def _escape_drive_query_literal(value: str) -> str:
    return value.replace("\\", "\\\\").replace("'", "\\'")


def get_or_create_purchase_invoice_folder(service) -> str:
    """
    Return folder id for PURCHASE_INVOICE_FOLDER_NAME under My Drive root only
    (single folder, no nesting inside GOOGLE_DRIVE_FOLDER_ID).
    """
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


def upload_data1_files():
    if not DATA_DIR.exists():
        raise FileNotFoundError(f"Folder not found: {DATA_DIR}")

    service = get_drive_service()
    folder_id = get_or_create_purchase_invoice_folder(service)
    print(
        f"Target Drive folder: {PURCHASE_INVOICE_FOLDER_NAME} "
        f"(https://drive.google.com/drive/folders/{folder_id})"
    )

    uploaded = 0
    for file_path in _iter_files(DATA_DIR):
        mime_type, _ = mimetypes.guess_type(str(file_path))
        media = MediaFileUpload(str(file_path), mimetype=mime_type, resumable=True)
        metadata = {"name": file_path.name, "parents": [folder_id]}

        response = (
            service.files()
            .create(body=metadata, media_body=media, fields="id,name,webViewLink")
            .execute()
        )
        uploaded += 1
        print(f"Uploaded: {response.get('name')} | id={response.get('id')}")
        if response.get("webViewLink"):
            print(f"Link: {response['webViewLink']}")

    if uploaded == 0:
        print(f"No files found in: {DATA_DIR}")
    else:
        print(f"Done. Uploaded {uploaded} file(s) from {DATA_DIR}")


if __name__ == "__main__":
    upload_data1_files()