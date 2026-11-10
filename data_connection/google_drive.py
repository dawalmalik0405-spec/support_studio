
import os
from dotenv import load_dotenv
from google_auth_oauthlib.flow import Flow
from cryptography.fernet import Fernet

from google.auth.transport.requests import Request
from googleapiclient.discovery import build
os.environ["OAUTHLIB_INSECURE_TRANSPORT"] = "1"


load_dotenv()

oauth_flows = {}

REDIRECT_URI = "http://localhost:8000/google/callback"

SCOPES = [
    "https://www.googleapis.com/auth/drive.file"
]


def encrypt_refresh_token(token: str) -> str:
    key = os.getenv("GOOGLE_TOKEN_ENCRYPTION_KEY")
    if not key:
        raise RuntimeError("GOOGLE_TOKEN_ENCRYPTION_KEY must be configured.")
    return Fernet(key.encode("ascii")).encrypt(token.encode("utf-8")).decode("ascii")


def decrypt_refresh_token(token: str) -> str:
    key = os.getenv("GOOGLE_TOKEN_ENCRYPTION_KEY")
    if not key:
        raise RuntimeError("GOOGLE_TOKEN_ENCRYPTION_KEY must be configured.")
    return Fernet(key.encode("ascii")).decrypt(token.encode("ascii")).decode("utf-8")


def Oauth():
    client_id = os.getenv("Client_ID")
    client_secret = os.getenv("Client_secret")

    if not client_id or not client_secret:
        raise ValueError(
            "Client_ID and Client_secret must be set in .env"
        )

    client_config = {
        "web": {
            "client_id": client_id,
            "client_secret": client_secret,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": [REDIRECT_URI],
        }
    }

    flow = Flow.from_client_config(
        client_config,
        scopes=SCOPES,
        redirect_uri=REDIRECT_URI,
    )

    authorization_url, state = flow.authorization_url(
        access_type="offline",
        prompt="consent",
        include_granted_scopes="true",
    )

    oauth_flows[state] = flow

    return authorization_url, state





def get_drive_service(credentials):
    """Create an authenticated Google Drive API client."""

    if not credentials.valid and credentials.refresh_token:
        credentials.refresh(Request())

    return build(
        "drive",
        "v3",
        credentials=credentials,
        cache_discovery=False,
    )


def get_account_email(credentials) -> str:
    service = get_drive_service(credentials)
    result = service.about().get(fields="user(emailAddress)").execute()
    return result.get("user", {}).get("emailAddress", "Google Drive account")


def list_files(credentials, folder_id=None, page_token=None):
    """List accessible files and folders."""

    service = get_drive_service(credentials)

    query = "trashed = false"

    if folder_id:
        escaped_id = folder_id.replace("\\", "\\\\").replace("'", "\\'")
        query += f" and '{escaped_id}' in parents"

    result = service.files().list(
        q=query,
        pageSize=100,
        pageToken=page_token,
        orderBy="name",
        fields=(
            "nextPageToken,"
            "files(id,name,mimeType,webViewLink,modifiedTime)"
        ),
    ).execute()

    return result

