import os
import secrets
import uuid
import json
import hashlib
import hmac
import logging
import requests
from datetime import datetime, timezone
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse, RedirectResponse
from starlette.middleware.sessions import SessionMiddleware
from google.oauth2.credentials import Credentials
from googleapiclient.errors import HttpError
from google.auth.transport.requests import Request as GoogleRequest
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session
from data_connection.db import SessionLocal, get_db
from data_connection.db_models import (
    Agent,
    AgentDriveSource,
    Company,
    DriveConnection,
    WhatsAppConnection,
)
from data_connection.secret_encryption import decrypt_secret, encrypt_secret
from rag.services.rag_service import RAGService

from data_connection.google_drive import (
    Oauth,
    SCOPES,
    decrypt_refresh_token,
    encrypt_refresh_token,
    get_account_email,
    get_drive_service,
    list_files,
    oauth_flows,
)

load_dotenv()
logger = logging.getLogger(__name__)

@asynccontextmanager
async def lifespan(app: FastAPI):
    service = RAGService()
    service.start()
    app.state.rag_service = service
    try:
        yield
    finally:
        service.stop()


app = FastAPI(title="Support Agent Platform API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.add_middleware(
    SessionMiddleware,
    secret_key=os.environ["SESSION_SECRET"],
    same_site="lax",
    https_only=False,  # Local development only
)

@app.get("/")
def home():
    return {"message": "Google Drive API is running"}


@app.get("/google/login")
def google_login(request: Request, db: Session = Depends(get_db)):
    _workspace_for_request(request, db)
    # Create an identifier for this browser session.
    if "session_id" not in request.session:
        request.session["session_id"] = secrets.token_urlsafe(32)

    authorization_url, state = Oauth()

    # Associate the OAuth state with this browser session.
    request.session["oauth_state"] = state

    return RedirectResponse(authorization_url)


@app.get("/google/callback")
def google_callback(request: Request, db: Session = Depends(get_db)):
    state = request.query_params.get("state")
    code = request.query_params.get("code")
    error = request.query_params.get("error")

    if error:
        raise HTTPException(
            status_code=400,
            detail=f"Google authorization failed: {error}",
        )

    if not state or not code:
        raise HTTPException(
            status_code=400,
            detail="Missing OAuth state or authorization code",
        )

    session_state = request.session.get("oauth_state")
    session_id = request.session.get("session_id")

    if not session_id or state != session_state:
        raise HTTPException(
            status_code=400,
            detail="Invalid OAuth state. Start login again.",
        )

    flow = oauth_flows.pop(state, None)

    if flow is None:
        raise HTTPException(
            status_code=400,
            detail="OAuth flow expired. Start login again.",
        )

    try:
        flow.fetch_token(code=code)
        credentials = flow.credentials
        if not credentials.refresh_token:
            raise ValueError("Google did not return a refresh token; reconnect and grant offline access.")

        workspace = _workspace_for_request(request, db)
        account_email = get_account_email(credentials)
        connection = db.scalar(
            select(DriveConnection).where(DriveConnection.company_id == workspace.id)
        )
        if connection is None:
            connection = DriveConnection(
                company_id=workspace.id,
                google_account_email=account_email,
                refresh_token=encrypt_refresh_token(credentials.refresh_token),
                status="connected",
            )
            db.add(connection)
        else:
            connection.google_account_email = account_email
            connection.refresh_token = encrypt_refresh_token(credentials.refresh_token)
            connection.status = "connected"
        db.commit()
        request.session.pop("oauth_state", None)

        return RedirectResponse(
            url="http://localhost:5173/?connected=true",
            status_code=303,
        )

    except Exception as exc:
        print(f"OAuth callback error: {type(exc).__name__}: {exc}")
        raise HTTPException(
            status_code=400,
            detail="Failed to exchange Google authorization code",
        )


@app.get("/google/status")
def google_status(request: Request, db: Session = Depends(get_db)):
    workspace = _workspace_for_request(request, db)
    connection = db.scalar(
        select(DriveConnection).where(DriveConnection.company_id == workspace.id)
    )

    if not connection or connection.status != "connected":
        return {
            "connected": False,
            "message": "Connect Google Drive first",
        }

    return {
        "connected": True,
        "google_account_email": connection.google_account_email,
        "has_refresh_token": bool(connection.refresh_token),
    }




@app.get("/google/files")
def google_files(
    request: Request,
    folder_id: str | None = None,
    page_token: str | None = None,
    db: Session = Depends(get_db),
):
    connection, credentials = _drive_connection_for_request(request, db)

    try:
        result = list_files(
            credentials,
            folder_id=folder_id,
            page_token=page_token,
        )

        _persist_rotated_refresh_token(connection, credentials, db)
        connection.status = "connected"
        db.commit()

        return {
            "files": result.get("files", []),
            "next_page_token": result.get("nextPageToken"),
        }

    except HttpError as exc:
        if exc.resp.status == 401:
            raise HTTPException(
                status_code=401,
                detail="Google authorization expired. Reconnect Drive.",
            )

        if exc.resp.status == 403:
            raise HTTPException(
                status_code=403,
                detail=(
                    "Google denied access. Check the Drive scope "
                    "and the files authorized for this app."
                ),
            )

        raise HTTPException(
            status_code=502,
            detail=f"Google Drive API error: HTTP {exc.resp.status}",
        )




@app.get("/google/picker-token")
def google_picker_token(request: Request, db: Session = Depends(get_db)):
    connection, credentials = _drive_connection_for_request(request, db)

    try:
        if not credentials.valid:
            if not credentials.refresh_token:
                raise HTTPException(
                    status_code=401,
                    detail="Reconnect Google Drive"
                )
            credentials.refresh(GoogleRequest())

        _persist_rotated_refresh_token(connection, credentials, db)

        # Return only the short-lived access token, never the refresh token.
        return {"access_token": credentials.token}

    except HTTPException:
        raise
    except Exception:
        raise HTTPException(
            status_code=401,
            detail="Could not obtain a Google access token. Reconnect Drive."
        )




class IndexDriveRequest(BaseModel):
    agent_id: str
    selected_items: list[dict]


class AgentCreateRequest(BaseModel):
    name: str
    description: str = ""
    instructions: str = ""
    tone: str = "helpful"


class AgentUpdateRequest(BaseModel):
    name: str | None = None
    description: str | None = None
    instructions: str | None = None
    tone: str | None = None
class AgentChatRequest(BaseModel):
    message: str


class WhatsAppConfigRequest(BaseModel):
    agent_id: str
    phone_number_id: str
    access_token: str = ""
    app_secret: str = ""
    verify_token: str = ""


def _workspace_for_request(request: Request, db: Session) -> Company:
    """Resolve the prototype workspace associated with this signed browser session."""
    workspace_id = request.session.get("workspace_id")
    if workspace_id:
        try:
            workspace = db.get(Company, uuid.UUID(str(workspace_id)))
        except (ValueError, TypeError, AttributeError):
            workspace = None
        if workspace:
            return workspace

    workspace = Company(company="My Workspace")
    db.add(workspace)
    db.commit()
    db.refresh(workspace)
    request.session["workspace_id"] = str(workspace.id)
    return workspace


def _drive_connection_for_request(request: Request, db: Session):
    workspace = _workspace_for_request(request, db)
    connection = db.scalar(
        select(DriveConnection).where(DriveConnection.company_id == workspace.id)
    )
    if not connection or connection.status != "connected":
        raise HTTPException(status_code=401, detail="Connect Google Drive first.")

    try:
        refresh_token = decrypt_refresh_token(connection.refresh_token)
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail="Could not decrypt the saved Google connection. Reconnect Drive.",
        ) from exc

    credentials = Credentials(
        token=None,
        refresh_token=refresh_token,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=os.getenv("Client_ID"),
        client_secret=os.getenv("Client_secret"),
        scopes=SCOPES,
    )
    return connection, credentials


def _persist_rotated_refresh_token(connection, credentials, db: Session):
    if not credentials.refresh_token:
        return
    current = decrypt_refresh_token(connection.refresh_token)
    if credentials.refresh_token != current:
        connection.refresh_token = encrypt_refresh_token(credentials.refresh_token)
        db.commit()


def _agent_payload(agent: Agent) -> dict:
    return {
        "id": str(agent.id),
        "name": agent.name,
        "description": agent.description,
        "instructions": agent.instructions,
        "tone": agent.tone,
        "status": agent.status,
        "created_at": agent.created_at.isoformat(),
        "updated_at": agent.updated_at.isoformat(),
    }


@app.get("/agents")
def list_agents(request: Request, db: Session = Depends(get_db)):
    workspace = _workspace_for_request(request, db)
    agents = db.scalars(
        select(Agent).where(Agent.company_id == workspace.id).order_by(Agent.created_at)
    ).all()
    return {"agents": [_agent_payload(agent) for agent in agents]}


@app.post("/agents", status_code=201)
def create_agent(
    body: AgentCreateRequest,
    request: Request,
    db: Session = Depends(get_db),
):
    name = body.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="Agent name is required.")

    workspace = _workspace_for_request(request, db)
    agent = Agent(
        company_id=workspace.id,
        name=name,
        description=body.description.strip(),
        instructions=body.instructions.strip(),
        tone=body.tone.strip() or "helpful",
        status="draft",
    )
    db.add(agent)
    db.commit()
    db.refresh(agent)
    return {"agent": _agent_payload(agent)}


@app.delete("/agents/{agent_id}")
def delete_agent(
    agent_id: str,
    request: Request,
    db: Session = Depends(get_db),
):
    agent = _agent_for_request(agent_id, request, db)
    rag_service = getattr(request.app.state, "rag_service", None)
    if rag_service is None:
        raise HTTPException(status_code=503, detail="RAG service is starting.")

    try:
        deleted_chunks = rag_service.delete_agent(agent.id)
    except Exception as exc:
        logger.exception("Could not remove the agent's indexed documents.")
        raise HTTPException(
            status_code=500,
            detail="Could not remove the agent's indexed documents.",
        ) from exc

    sources = db.scalars(
        select(AgentDriveSource).where(AgentDriveSource.agent_id == agent.id)
    ).all()
    whatsapp_connection = db.scalar(
        select(WhatsAppConnection).where(WhatsAppConnection.agent_id == agent.id)
    )
    if whatsapp_connection:
        db.delete(whatsapp_connection)
    for source in sources:
        db.delete(source)
    db.delete(agent)
    db.commit()
    return {"deleted": True, "agent_id": agent_id, "chunks_deleted": deleted_chunks}


@app.patch("/agents/{agent_id}")
def update_agent(
    agent_id: str,
    body: AgentUpdateRequest,
    request: Request,
    db: Session = Depends(get_db),
):
    workspace = _workspace_for_request(request, db)
    try:
        agent_uuid = uuid.UUID(agent_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Agent not found.")

    agent = db.scalar(
        select(Agent).where(
            Agent.id == agent_uuid,
            Agent.company_id == workspace.id,
        )
    )
    if agent is None:
        raise HTTPException(status_code=404, detail="Agent not found.")

    for field, value in body.model_dump(exclude_unset=True).items():
        if field == "name" and value is not None:
            value = value.strip()
            if not value:
                raise HTTPException(status_code=400, detail="Agent name is required.")
        if isinstance(value, str):
            value = value.strip()
        setattr(agent, field, value)

    db.commit()
    db.refresh(agent)
    return {"agent": _agent_payload(agent)}


def _agent_for_request(agent_id: str, request: Request, db: Session) -> Agent:
    workspace = _workspace_for_request(request, db)
    try:
        agent_uuid = uuid.UUID(agent_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="Agent not found.") from exc
    agent = db.scalar(
        select(Agent).where(
            Agent.id == agent_uuid,
            Agent.company_id == workspace.id,
        )
    )
    if agent is None:
        raise HTTPException(status_code=404, detail="Agent not found.")
    return agent


def _sync_agent_drive_sources(
    agent: Agent,
    selected_items: list[dict],
    request: Request,
    db: Session,
):
    connection, credentials = _drive_connection_for_request(request, db)
    existing_rows = db.scalars(
        select(AgentDriveSource).where(AgentDriveSource.agent_id == agent.id)
    ).all()
    existing_by_id = {row.drive_item_id: row for row in existing_rows}
    rag_service = getattr(request.app.state, "rag_service", None)
    if rag_service is None:
        raise HTTPException(status_code=503, detail="RAG service is starting.")

    known_versions = {
        row.drive_item_id: row.modified_time
        for row in existing_rows
        if row.item_type == "file"
        and row.modified_time
        and row.sync_status in {"indexed", "unchanged"}
        and rag_service.has_agent_document(agent.id, row.drive_item_id)
    }

    try:
        result = rag_service.index_google_drive(
            agent_id=str(agent.id),
            credentials=credentials,
            selected_items=selected_items,
            known_versions=known_versions,
        )
        _persist_rotated_refresh_token(connection, credentials, db)

        now = datetime.now(timezone.utc)
        root_ids = set()

        def save_source(
            metadata,
            *,
            item_type,
            is_selected,
            root_folder_id=None,
            default_status="indexed",
        ):
            item_id = metadata["id"]
            row = existing_by_id.get(item_id)
            if row is None:
                row = AgentDriveSource(
                    agent_id=agent.id,
                    drive_item_id=item_id,
                    name=metadata.get("name", item_id),
                    mime_type=metadata.get("mimeType", ""),
                    item_type=item_type,
                    sync_status=default_status,
                )
                db.add(row)
                existing_by_id[item_id] = row
            row.name = metadata.get("name", row.name)
            row.mime_type = metadata.get("mimeType", row.mime_type)
            row.item_type = item_type
            row.is_selected = is_selected
            folder_ids = metadata.get("root_folder_ids")
            if folder_ids is None:
                folder_ids = [root_folder_id] if root_folder_id else []
            row.root_folder_ids = sorted(set(folder_ids))
            row.root_folder_id = next(iter(row.root_folder_ids), None)
            row.modified_time = metadata.get("modifiedTime") or row.modified_time
            row.fingerprint = metadata.get("fingerprint") or row.fingerprint
            row.sync_status = metadata.get("sync_status", default_status)
            if row.sync_status in {"indexed", "unchanged"}:
                row.last_synced_at = now
            return row

        for root in result.get("root_sources", []):
            item_id = root["id"]
            root_ids.add(item_id)
            item_type = "folder" if root.get("mimeType") == "application/vnd.google-apps.folder" else "file"
            save_source(root, item_type=item_type, is_selected=True)

        discovered_by_root = {}
        for metadata in result.get("files", []):
            root_folder_id = metadata.get("root_folder_id")
            row = save_source(
                metadata,
                item_type="file",
                is_selected=metadata["id"] in root_ids,
                root_folder_id=root_folder_id,
            )
            for folder_id in row.root_folder_ids:
                discovered_by_root.setdefault(folder_id, set()).add(row.drive_item_id)

        for unavailable_id in result.get("unavailable_ids", []):
            unavailable_source = existing_by_id.get(unavailable_id)
            if unavailable_source:
                unavailable_source.sync_status = "unavailable"

        # Only treat missing folder children as deleted after a complete, error-free listing.
        if not result.get("errors"):
            for folder_id in root_ids:
                root_row = existing_by_id.get(folder_id)
                if not root_row or root_row.item_type != "folder":
                    continue
                current_ids = discovered_by_root.get(folder_id, set())
                stale_rows = [
                    row for row in existing_rows
                    if folder_id in row.root_folder_ids and row.drive_item_id not in current_ids
                ]
                for stale in stale_rows:
                    stale.root_folder_ids = [
                        item for item in stale.root_folder_ids if item != folder_id
                    ]
                    stale.root_folder_id = next(iter(stale.root_folder_ids), None)
                    if not stale.root_folder_ids and not stale.is_selected:
                        rag_service.remove_agent_document(agent.id, stale.drive_item_id)
                        db.delete(stale)

        db.commit()
        connection.status = "connected"
        db.commit()
        result.pop("root_sources", None)
        result.pop("files", None)
        result.pop("unavailable_ids", None)
        return result
    except Exception:
        db.rollback()
        raise


@app.post("/google/index")
def index_google_drive(
    body: IndexDriveRequest,
    request: Request,
    db: Session = Depends(get_db),
):
    if not body.selected_items:
        raise HTTPException(
            status_code=400,
            detail="Select at least one file or folder first.",
        )

    try:
        agent = _agent_for_request(body.agent_id, request, db)
        result = _sync_agent_drive_sources(agent, body.selected_items, request, db)

        return {
            "message": "Google Drive ingestion finished.",
            **result,
        }

    except HTTPException:
        raise
    except Exception as exc:
        print(f"Google Drive ingestion error: {type(exc).__name__}: {exc}")
        raise HTTPException(
            status_code=500,
            detail="Google Drive ingestion failed. Check the backend logs.",
        )


@app.get("/agents/{agent_id}/sources")
def list_agent_sources(
    agent_id: str,
    request: Request,
    db: Session = Depends(get_db),
):
    agent = _agent_for_request(agent_id, request, db)
    rows = db.scalars(
        select(AgentDriveSource)
        .where(AgentDriveSource.agent_id == agent.id)
        .order_by(AgentDriveSource.item_type, AgentDriveSource.name)
    ).all()
    return {
        "sources": [
            {
                "drive_item_id": row.drive_item_id,
                "root_folder_id": row.root_folder_id,
                "root_folder_ids": row.root_folder_ids,
                "name": row.name,
                "mime_type": row.mime_type,
                "item_type": row.item_type,
                "is_selected": row.is_selected,
                "modified_time": row.modified_time,
                "sync_status": row.sync_status,
                "last_synced_at": row.last_synced_at.isoformat() if row.last_synced_at else None,
            }
            for row in rows
        ]
    }


@app.post("/agents/{agent_id}/sources/sync")
def sync_agent_sources(
    agent_id: str,
    request: Request,
    db: Session = Depends(get_db),
):
    agent = _agent_for_request(agent_id, request, db)
    roots = db.scalars(
        select(AgentDriveSource).where(
            AgentDriveSource.agent_id == agent.id,
            AgentDriveSource.is_selected.is_(True),
        )
    ).all()
    if not roots:
        raise HTTPException(status_code=400, detail="This agent has no Drive sources yet.")
    items = [
        {"id": source.drive_item_id, "name": source.name, "mimeType": source.mime_type}
        for source in roots
    ]
    result = _sync_agent_drive_sources(agent, items, request, db)
    return {"message": "Drive sync finished.", **result}


@app.delete("/agents/{agent_id}/sources/{drive_item_id}")
def remove_agent_source(
    agent_id: str,
    drive_item_id: str,
    request: Request,
    db: Session = Depends(get_db),
):
    agent = _agent_for_request(agent_id, request, db)
    roots = db.scalars(
        select(AgentDriveSource).where(
            AgentDriveSource.agent_id == agent.id,
            AgentDriveSource.drive_item_id == drive_item_id,
        )
    ).all()
    if not roots:
        raise HTTPException(status_code=404, detail="Drive source not found.")

    source = roots[0]
    if source.item_type == "file" and source.root_folder_ids:
        selected_folders = db.scalars(
            select(AgentDriveSource).where(
                AgentDriveSource.agent_id == agent.id,
                AgentDriveSource.drive_item_id.in_(source.root_folder_ids),
                AgentDriveSource.item_type == "folder",
                AgentDriveSource.is_selected.is_(True),
            )
        ).all()
        if selected_folders:
            source.is_selected = False
            db.commit()
            return {
                "removed": True,
                "source": source.name,
                "items_removed": 0,
                "still_included_by_folder": [folder.name for folder in selected_folders],
            }

    rows_to_remove = [source]
    if source.item_type == "folder":
        possible_children = db.scalars(
            select(AgentDriveSource).where(
                AgentDriveSource.agent_id == agent.id,
            )
        ).all()
        children = [
            child for child in possible_children
            if source.drive_item_id in child.root_folder_ids
        ]
        for child in children:
            child.root_folder_ids = [
                folder_id for folder_id in child.root_folder_ids
                if folder_id != source.drive_item_id
            ]
            child.root_folder_id = next(iter(child.root_folder_ids), None)
            if child.root_folder_ids or child.is_selected:
                continue
            rows_to_remove.append(child)

    rag_service = getattr(request.app.state, "rag_service", None)
    if rag_service is None:
        raise HTTPException(status_code=503, detail="RAG service is starting.")
    for row in rows_to_remove:
        if row.item_type == "file":
            rag_service.remove_agent_document(agent.id, row.drive_item_id)
        db.delete(row)
    db.commit()
    return {"removed": True, "source": source.name, "items_removed": len(rows_to_remove)}


@app.post("/agents/{agent_id}/chat")
def chat_with_agent(
    agent_id: str,
    body: AgentChatRequest,
    request: Request,
    db: Session = Depends(get_db),
):
    agent = _agent_for_request(agent_id, request, db)
    question = body.message.strip()
    if not question:
        raise HTTPException(status_code=400, detail="Message cannot be empty.")
    rag_service = getattr(request.app.state, "rag_service", None)
    if rag_service is None:
        raise HTTPException(status_code=503, detail="RAG service is starting.")

    result = rag_service.ask_agent(
        agent_id=str(agent.id),
        question=question,
        agent_instructions=agent.instructions,
        agent_tone=agent.tone,
    )
    answer = "".join(result["answer"])
    return {"answer": answer, "sources": result["sources"]}


@app.get("/whatsapp/config")
def get_whatsapp_config(request: Request, db: Session = Depends(get_db)):
    workspace = _workspace_for_request(request, db)
    config = db.scalar(
        select(WhatsAppConnection).where(WhatsAppConnection.company_id == workspace.id)
    )

    # Move the existing single-demo .env setup into encrypted storage on first visit.
    if config is None:
        env_agent_id = os.getenv("WHATSAPP_AGENT_ID", "")
        env_phone_id = os.getenv("WHATSAPP_PHONE_NUMBER_ID", "")
        env_token = os.getenv("WHATSAPP_ACCESS_TOKEN", "")
        env_app_secret = os.getenv("META_APP_SECRET", "")
        env_verify_token = os.getenv("WHATSAPP_WEBHOOK_VERIFY_TOKEN", "")
        try:
            agent_uuid = uuid.UUID(env_agent_id)
        except ValueError:
            agent_uuid = None
        agent = db.scalar(
            select(Agent).where(
                Agent.id == agent_uuid,
                Agent.company_id == workspace.id,
            )
        ) if agent_uuid else None
        if agent and env_phone_id and env_token and env_app_secret and env_verify_token:
            config = WhatsAppConnection(
                company_id=workspace.id,
                agent_id=agent.id,
                phone_number_id=env_phone_id,
                encrypted_access_token=encrypt_secret(env_token),
                encrypted_app_secret=encrypt_secret(env_app_secret),
                encrypted_verify_token=encrypt_secret(env_verify_token),
            )
            db.add(config)
            db.commit()
            db.refresh(config)

    if config is None:
        return {"configured": False, "agent_id": "", "phone_number_id": ""}

    return {
        "configured": True,
        "agent_id": str(config.agent_id),
        "phone_number_id": config.phone_number_id,
        "access_token_saved": bool(config.encrypted_access_token),
        "app_secret_saved": bool(config.encrypted_app_secret),
        "verify_token_saved": bool(config.encrypted_verify_token),
    }


@app.put("/whatsapp/config")
def save_whatsapp_config(
    body: WhatsAppConfigRequest,
    request: Request,
    db: Session = Depends(get_db),
):
    workspace = _workspace_for_request(request, db)
    try:
        agent_uuid = uuid.UUID(body.agent_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Select a valid agent.") from exc

    agent = db.scalar(
        select(Agent).where(
            Agent.id == agent_uuid,
            Agent.company_id == workspace.id,
        )
    )
    if agent is None:
        raise HTTPException(status_code=404, detail="Agent not found in this workspace.")

    phone_number_id = body.phone_number_id.strip()
    if not phone_number_id:
        raise HTTPException(status_code=400, detail="Phone Number ID is required.")

    config = db.scalar(
        select(WhatsAppConnection).where(WhatsAppConnection.company_id == workspace.id)
    )
    if config is None:
        if not all((body.access_token.strip(), body.app_secret.strip(), body.verify_token.strip())):
            raise HTTPException(
                status_code=400,
                detail="Enter the access token, App Secret, and webhook verify token to connect.",
            )
        config = WhatsAppConnection(
            company_id=workspace.id,
            agent_id=agent.id,
            phone_number_id=phone_number_id,
            encrypted_access_token=encrypt_secret(body.access_token.strip()),
            encrypted_app_secret=encrypt_secret(body.app_secret.strip()),
            encrypted_verify_token=encrypt_secret(body.verify_token.strip()),
        )
        db.add(config)
    else:
        config.agent_id = agent.id
        config.phone_number_id = phone_number_id
        if body.access_token.strip():
            config.encrypted_access_token = encrypt_secret(body.access_token.strip())
        if body.app_secret.strip():
            config.encrypted_app_secret = encrypt_secret(body.app_secret.strip())
        if body.verify_token.strip():
            config.encrypted_verify_token = encrypt_secret(body.verify_token.strip())

    db.commit()
    return {"configured": True, "agent_id": str(agent.id), "phone_number_id": phone_number_id}


def _send_whatsapp_text(
    recipient: str, message: str, access_token: str, phone_number_id: str
) -> None:
    """Send a plain text reply using the saved WhatsApp Cloud API credentials."""
    api_version = os.getenv("WHATSAPP_GRAPH_API_VERSION", "v25.0")
    try:
        response = requests.post(
            f"https://graph.facebook.com/{api_version}/{phone_number_id}/messages",
            headers={"Authorization": f"Bearer {access_token}"},
            json={
                "messaging_product": "whatsapp",
                "recipient_type": "individual",
                "to": recipient,
                "type": "text",
                "text": {"preview_url": False, "body": message[:4096]},
            },
            timeout=20,
        )
        response.raise_for_status()
    except requests.RequestException as exc:
        # Avoid logging request headers or credentials.
        logger.exception("WhatsApp Cloud API failed to send a reply: %s", exc)


def _reply_to_whatsapp_message(connection_id: str, sender: str, message: str) -> None:
    """Run the same per-agent RAG path used by the platform's test chat."""
    db = SessionLocal()
    try:
        try:
            connection_uuid = uuid.UUID(connection_id)
        except ValueError:
            logger.error("WhatsApp reply skipped: saved connection ID is invalid.")
            return

        config = db.get(WhatsAppConnection, connection_uuid)
        if config is None:
            logger.error("WhatsApp reply skipped: saved connection was not found.")
            return
        agent = db.scalar(select(Agent).where(Agent.id == config.agent_id))
        if agent is None:
            logger.error("WhatsApp reply skipped: selected agent was not found.")
            return

        rag_service = getattr(app.state, "rag_service", None)
        if rag_service is None:
            logger.error("WhatsApp reply skipped: RAG service is not ready.")
            return

        result = rag_service.ask_agent(
            agent_id=str(agent.id),
            question=message,
            k=4,
            agent_instructions=agent.instructions,
            agent_tone=agent.tone,
            max_tokens=300,
        )
        answer = "".join(result.get("answer", [])).strip()
        if answer:
            _send_whatsapp_text(
                sender,
                answer,
                decrypt_secret(config.encrypted_access_token),
                config.phone_number_id,
            )
    except Exception:
        logger.exception("Could not process an incoming WhatsApp message.")
    finally:
        db.close()


@app.get("/whatsapp/webhook")
def verify_whatsapp_webhook(request: Request):
    """Meta webhook subscription handshake."""
    db = SessionLocal()
    try:
        config = db.scalar(
            select(WhatsAppConnection).order_by(WhatsAppConnection.updated_at.desc())
        )
        verify_token = (
            decrypt_secret(config.encrypted_verify_token)
            if config
            else os.getenv("WHATSAPP_WEBHOOK_VERIFY_TOKEN")
        )
    finally:
        db.close()
    if not verify_token:
        raise HTTPException(status_code=503, detail="WhatsApp webhook is not configured.")

    params = request.query_params
    if (
        params.get("hub.mode") == "subscribe"
        and hmac.compare_digest(params.get("hub.verify_token", ""), verify_token)
    ):
        return PlainTextResponse(params.get("hub.challenge", ""))
    raise HTTPException(status_code=403, detail="Webhook verification failed.")


@app.post("/whatsapp/webhook")
async def receive_whatsapp_webhook(request: Request, background_tasks: BackgroundTasks):
    """Validate Meta's signature and enqueue incoming text messages for its selected agent."""
    body = await request.body()
    try:
        payload = json.loads(body)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid webhook JSON.") from exc

    phone_number_id = next(
        (
            change.get("value", {}).get("metadata", {}).get("phone_number_id")
            for entry in payload.get("entry", [])
            for change in entry.get("changes", [])
            if change.get("value", {}).get("metadata", {}).get("phone_number_id")
        ),
        None,
    )
    if not phone_number_id:
        return {"status": "ok"}

    db = SessionLocal()
    try:
        config = db.scalar(
            select(WhatsAppConnection).where(
                WhatsAppConnection.phone_number_id == str(phone_number_id)
            )
        )
        if config is None:
            logger.warning("WhatsApp webhook received for an unconfigured phone number.")
            return {"status": "ok"}

        app_secret = decrypt_secret(config.encrypted_app_secret)
        signature = request.headers.get("X-Hub-Signature-256", "")
        expected = "sha256=" + hmac.new(
            app_secret.encode("utf-8"), body, hashlib.sha256
        ).hexdigest()
        if not hmac.compare_digest(signature, expected):
            raise HTTPException(status_code=401, detail="Invalid webhook signature.")
        connection_id = str(config.id)
    finally:
        db.close()

    # Acknowledge Meta quickly; message generation and delivery happen afterwards.
    for entry in payload.get("entry", []):
        for change in entry.get("changes", []):
            value = change.get("value", {})
            for message in value.get("messages", []):
                if message.get("type") != "text":
                    continue
                sender = message.get("from")
                text = (message.get("text") or {}).get("body", "").strip()
                if sender and text:
                    background_tasks.add_task(
                        _reply_to_whatsapp_message, connection_id, sender, text
                    )

    return {"status": "ok"}
