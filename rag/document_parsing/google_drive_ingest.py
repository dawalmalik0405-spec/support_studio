
import hashlib
import tempfile
from pathlib import Path

from data_connection.google_drive import get_drive_service
from rag.document_parsing.ingest import processor, registry


SUPPORTED_EXTENSIONS = {".pdf", ".docx", ".txt", ".png", ".jpg", ".jpeg"}
FOLDER_MIME_TYPE = "application/vnd.google-apps.folder"


def _fingerprint(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _list_children(service, folder_id: str):
    files = []
    page_token = None

    while True:
        result = service.files().list(
            q=f"'{folder_id}' in parents and trashed = false",
            pageSize=1000,
            pageToken=page_token,
            fields="nextPageToken,files(id,name,mimeType,modifiedTime,size)",
        ).execute()

        files.extend(result.get("files", []))
        page_token = result.get("nextPageToken")

        if not page_token:
            break

    return files


def _expand_selections(service, selected_items):
    """Expand selected folders recursively without processing unsupported files."""
    expanded = {}
    visited_folders = set()
    errors = []
    root_sources = []
    unavailable_ids = []

    def visit(item, root_folder_id=None, is_root=False):
        item_id = item.get("id")
        if not item_id:
            errors.append("Skipped a selection without a file ID.")
            return

        try:
            metadata = service.files().get(
                fileId=item_id,
                fields="id,name,mimeType,modifiedTime,size",
            ).execute()

            if metadata["mimeType"] == FOLDER_MIME_TYPE:
                if is_root:
                    root_sources.append(metadata)
                if item_id in visited_folders:
                    return

                visited_folders.add(item_id)

                for child in _list_children(service, item_id):
                    visit(child, root_folder_id or item_id)
                return

            if is_root:
                root_sources.append(metadata)
            suffix = Path(metadata["name"]).suffix.lower()
            if suffix not in SUPPORTED_EXTENSIONS:
                metadata["sync_status"] = "unsupported"
                errors.append(f"{metadata['name']}: unsupported file type.")
                return

            folder_ids = set(expanded.get(item_id, {}).get("root_folder_ids", []))
            if root_folder_id:
                folder_ids.add(root_folder_id)
            metadata["root_folder_ids"] = sorted(folder_ids)
            metadata["root_folder_id"] = next(iter(sorted(folder_ids)), None)
            expanded[item_id] = metadata

        except Exception as exc:
            unavailable_ids.append(item_id)
            errors.append(
                f"{item.get('name', item_id)}: {type(exc).__name__}"
            )

    for item in selected_items:
        visit(item, is_root=True)

    return list(expanded.values()), errors, root_sources, unavailable_ids


def _normalize(agent_id, file_id, name, result):
    suffix = Path(name).suffix.lower()
    file_type = suffix.removeprefix(".")
    document_id = f"{agent_id}:gdrive:{file_id}"
    normalized = []

    if suffix == ".pdf":
        for item in result:
            normalized.append({
                "text": item["text"],
                "metadata": {
                    "document_id": document_id,
                    "agent_id": str(agent_id),
                    "source": "google_drive",
                    "source_file": name,
                    "file_type": file_type,
                    "page": item.get("page"),
                    "parser_source": item.get("source", "pdf"),
                },
            })

    elif suffix == ".docx":
        for item in result:
            normalized.append({
                "text": item["text"],
                "metadata": {
                    "document_id": document_id,
                    "agent_id": str(agent_id),
                    "source": "google_drive",
                    "source_file": name,
                    "file_type": file_type,
                    "page": None,
                    "item_index": item.get("item_index"),
                },
            })

    elif suffix == ".txt":
        for item in result:
            normalized.append({
                "text": item["text"],
                "metadata": {
                    "document_id": document_id,
                    "agent_id": str(agent_id),
                    "source": "google_drive",
                    "source_file": name,
                    "file_type": file_type,
                    "page": None,
                },
            })

    elif suffix in {".png", ".jpg", ".jpeg"}:
        text = "\n".join(result)
        normalized.append({
            "text": text,
            "metadata": {
                "document_id": document_id,
                "agent_id": str(agent_id),
                "source": "google_drive",
                "source_file": name,
                "file_type": file_type,
                "page": None,
                "parser_source": "ocr",
            },
        })

    return normalized


def normalized_drive_data(credentials, selected_items, agent_id, known_versions=None):
    service = get_drive_service(credentials)
    metadata_list, errors, root_sources, unavailable_ids = _expand_selections(
        service, selected_items
    )
    known_versions = known_versions or {}

    documents = []
    skipped = 0
    discovered_files = []

    for metadata in metadata_list:
        file_id = metadata["id"]
        name = metadata["name"]
        document_id = f"{agent_id}:gdrive:{file_id}"
        metadata["fingerprint"] = None
        metadata["sync_status"] = "indexed"
        discovered_files.append(metadata)

        try:
            if (
                metadata.get("modifiedTime")
                and known_versions.get(file_id) == metadata["modifiedTime"]
            ):
                skipped += 1
                metadata["sync_status"] = "unchanged"
                continue

            content = service.files().get_media(
                fileId=file_id
            ).execute()

            fingerprint = _fingerprint(content)
            metadata["fingerprint"] = fingerprint
            existing = registry.get_document(document_id)

            if existing and existing["fingerprint"] == fingerprint:
                skipped += 1
                metadata["sync_status"] = "unchanged"
                continue

            suffix = Path(name).suffix.lower()

            # Temporary file only: removed even if parsing fails.
            with tempfile.TemporaryDirectory(prefix="rag_drive_") as temp_dir:
                temp_path = Path(temp_dir) / f"source{suffix}"
                temp_path.write_bytes(content)
                result = processor.parse(temp_path)

            data = _normalize(agent_id, file_id, name, result)

            if not data:
                errors.append(f"{name}: parser returned no content.")
                metadata["sync_status"] = "error"
                continue

            documents.append({
                "document_id": document_id,
                "fingerprint": fingerprint,
                "file_path": f"google-drive://{file_id}",
                "data": data,
            })

        except Exception as exc:
            metadata["sync_status"] = "error"
            errors.append(f"{name}: {type(exc).__name__}: {exc}")

    return documents, {
        "skipped": skipped,
        "unsupported_or_inaccessible": errors,
        "files": discovered_files,
        "root_sources": root_sources,
        "unavailable_ids": unavailable_ids,
    }
