from pathlib import Path
from rag.managers.document_registry import DocumentRegistry
from rag.utils.file_fingerprint import calculate_file_fingerprint


from .file_scanner import FileScanner
from .documentProcessor import DocumentProcessor



registry = DocumentRegistry()
scanner = FileScanner()
processor = DocumentProcessor()

BASE_DIR = Path(__file__).resolve().parent.parent
INGEST_ROOT = (BASE_DIR / "uploads").resolve()
PACK_ROOT = (INGEST_ROOT / "Offline_RAG_Complete_Testing_Pack").resolve()


def get_document_id(file_path: Path) -> str:
    path_obj = Path(file_path).resolve()
    try:
        return path_obj.relative_to(PACK_ROOT).as_posix()
    except ValueError:
        try:
            return path_obj.relative_to(INGEST_ROOT).as_posix()
        except ValueError:
            return Path(file_path).name


def get_files_to_process(files):
    files_to_process = []

    for file_path in files:

        file_path = Path(file_path)

        document_id = get_document_id(file_path)

        fingerprint = calculate_file_fingerprint(
            file_path
        )

        existing_document = registry.get_document(
            document_id
        )

        if existing_document is None:
            print(
                f"New document: {document_id}"
            )

            files_to_process.append(
                (
                    file_path,
                    document_id,
                    fingerprint
                )
            )

        elif existing_document["fingerprint"] != fingerprint:
            print(
                f"Changed document: {document_id}"
            )

            files_to_process.append(
                (
                    file_path,
                    document_id,
                    fingerprint
                )
            )

        else:
            print(
                f"Skipping unchanged document: "
                f"{document_id}"
            )

    return files_to_process





def get_deleted_documents(files):
    current_document_ids = set()

    for file_path in files:
        file_path = Path(file_path)
        document_id = get_document_id(file_path)
        current_document_ids.add(document_id)

    registered_documents = registry.get_all_documents()

    deleted_documents = []

    
    for document in registered_documents:
        document_id = document["document_id"]

        # Google Drive IDs are namespaced as <agent-id>:gdrive:<file-id>.
        # Local scans must never delete those documents from Chroma.
        if ":gdrive:" in document_id or document_id.startswith("gdrive:"):
            continue

        if document_id not in current_document_ids:
            deleted_documents.append(document_id)


    return deleted_documents








def normalize(file_path, result):
    file_path = Path(file_path)

    file_type = file_path.suffix.lower().replace(".", "")
    source_file = file_path.name

    # Stable identity for the logical document
    document_id = get_document_id(file_path)

    normalized_data = []

    # PDF
    if file_type == "pdf":
        for item in result:
            normalized_data.append({
                "text": item["text"],
                "metadata": {
                    "document_id": document_id,
                    "source_file": source_file,
                    "file_type": file_type,
                    "page": item.get("page"),
                    "source": item.get("source", "pdf")
                }
            })

    # DOCX
    elif file_type == "docx":
        for item in result:
            normalized_data.append({
                "text": item["text"],
                "metadata": {
                    "document_id": document_id,
                    "source_file": source_file,
                    "file_type": file_type,
                    "page": None,
                    "item_index": item.get("item_index"),
                    "source": "docx"
                }
            })

    # TXT
    elif file_type == "txt":
        for item in result:
            normalized_data.append({
                "text": item["text"],
                "metadata": {
                    "document_id": document_id,
                    "source_file": source_file,
                    "file_type": file_type,
                    "page": None,
                    "source": "txt"
                }
            })

    # Images processed through OCR
    elif file_type in {"png", "jpg", "jpeg"}:
        text = "\n".join(result)

        normalized_data.append({
            "text": text,
            "metadata": {
                "document_id": document_id,
                "source_file": source_file,
                "file_type": file_type,
                "page": None,
                "source": "ocr"
            }
        })

    else:
        raise ValueError(f"Unsupported file type: {file_type}")

    return normalized_data



def normalized_data():

    files = scanner.scan(INGEST_ROOT)

    deleted_documents = get_deleted_documents(files)

    print("Deleted documents:", deleted_documents)

    files_to_process = get_files_to_process(files)

    processed_documents = []


    for file_path, document_id, fingerprint in files_to_process:

        print(f"Parsing: {document_id}")

        result = processor.parse(file_path)

        normalized = normalize(
            file_path,
            result
        )

        processed_documents.append({
            "document_id": document_id,
            "fingerprint": fingerprint,
            "file_path": str(file_path),
            "data": normalized
        })

    return processed_documents, deleted_documents


