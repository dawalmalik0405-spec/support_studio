# Support Studio

Support Studio is a local-first support-agent demo. It connects Google Drive, parses and chunks selected documents, stores embeddings in a local Chroma database, and uses local Qwen GGUF models for retrieval and answers. A configured WhatsApp Cloud API test number can route incoming text messages to a selected agent.

This guide describes the current single-workspace development setup on Windows. It is not a production deployment guide. Google OAuth and Meta credentials belong to the developer running the app; WhatsApp currently uses a Meta test number and a temporary access token.

## Requirements

- Windows 10/11 and PowerShell
- Python 3.11 (the current app has been used with Python 3.11)
- Node.js with npm
- PostgreSQL database reachable from this computer (a hosted PostgreSQL database also works)
- A public HTTPS tunnel to port 8000 for Meta webhooks
- Several GB of free disk space for the local GGUF models

## Quick start

Run commands from the repository root (`D:\csagent` in the examples).

### 1. Get the project and install Python dependencies

```powershell
git clone <repository-url> csagent
cd csagent
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

If PowerShell prevents activating the environment, allow scripts for this terminal only, then activate it:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy RemoteSigned
.\.venv\Scripts\Activate.ps1
```

### 2. Install frontend dependencies

Open another PowerShell terminal at the project root:

```powershell
cd frontend
npm install
```

### 3. Download the local LLM runtime and models

The app runs `llama-server.exe` locally. Download a Windows CPU build of [llama.cpp](https://github.com/ggml-org/llama.cpp/releases), extract it, and copy the contents of its `bin` folder into `rag/runtime/`. Keep the DLL files next to `llama-server.exe`. Confirm this file exists:

```text
rag/runtime/llama-server.exe
```

Download these GGUF model files into `rag/models/` with the exact filenames shown. They are large files and are intentionally excluded from Git.

```powershell
New-Item -ItemType Directory -Force rag\models | Out-Null
Invoke-WebRequest -Uri "https://huggingface.co/Qwen/Qwen3-4B-GGUF/resolve/main/Qwen3-4B-Q4_K_M.gguf" -OutFile "rag\models\Qwen3-4B-Q4_K_M.gguf"
Invoke-WebRequest -Uri "https://huggingface.co/Qwen/Qwen3-Embedding-0.6B-GGUF/resolve/main/Qwen3-Embedding-0.6B-Q8_0.gguf" -OutFile "rag\models\Qwen3-Embedding-0.6B-Q8_0.gguf"
```

Expected paths:

```text
rag/runtime/llama-server.exe
rag/models/Qwen3-4B-Q4_K_M.gguf
rag/models/Qwen3-Embedding-0.6B-Q8_0.gguf
```

At startup the app runs the embedding model on `127.0.0.1:8081` and the chat model on `127.0.0.1:8080`. The local Chroma database is stored under `rag/data/chroma/` and is excluded from Git.

### 4. Configure environment variables

Create a `.env` file in the repository root. Do not commit it. Fill in the database and Google OAuth values using the following keys:

```dotenv
DATABASE_URI=postgresql+psycopg://USER:PASSWORD@HOST:5432/DATABASE?sslmode=require
SESSION_SECRET=replace_with_a_long_random_secret
GOOGLE_TOKEN_ENCRYPTION_KEY=replace_with_a_fernet_key

Client_ID=your_google_oauth_web_client_id
Client_secret=your_google_oauth_web_client_secret
```

Generate the two random secrets from the activated virtual environment:

```powershell
python -c "import secrets; print(secrets.token_urlsafe(48))"
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

Use the first output for `SESSION_SECRET` and the second for `GOOGLE_TOKEN_ENCRYPTION_KEY`. Keep the encryption key stable: the database stores Google refresh tokens and WhatsApp secrets encrypted with it, and they cannot be decrypted if this key is lost or changed. URL-encode special characters in the database username or password if needed.

Create `frontend/.env` with the Google Picker configuration and API address:

```dotenv
VITE_API_BASE_URL=http://localhost:8000
VITE_GOOGLE_API_KEY=your_google_api_key
VITE_GOOGLE_APP_ID=your_google_cloud_project_number
```

Vite reads these values when it starts, so restart the frontend after changing this file.

### 5. Start the app

Terminal 1, from the repository root with `.venv` activated:

```powershell
uvicorn app:app --host localhost --port 8000
```

Startup loads both local models and connects to PostgreSQL. Wait for `Application startup complete` and `Qwen3 model is ready`.

Terminal 2:

```powershell
cd frontend
npm run dev
```

Open the Vite URL printed in the terminal (normally `http://localhost:5173`). Use the same hostname consistently: the Google OAuth redirect is registered for `localhost`, and the frontend API URL above also uses `localhost`.

The interactive API reference is at `http://localhost:8000/docs`.

## Google Drive authentication setup

Google Drive connection uses OAuth. The user signs in through Google once; the app saves an encrypted refresh token in PostgreSQL so it can access Drive later. The app requests the `drive.file` scope.

1. In [Google Cloud Console](https://console.cloud.google.com/), create or select a project.
2. Enable **Google Drive API** and **Google Picker API** for that project.
3. Configure the OAuth consent screen. While the app is in testing mode, add the Google account you will use as a test user.
4. Create an OAuth client ID with application type **Web application**.
5. Add this exact **Authorized redirect URI**:

   ```text
   http://localhost:8000/google/callback
   ```

6. Add this **Authorized JavaScript origin** for local development:

   ```text
   http://localhost:5173
   ```

7. Put the OAuth client ID and client secret in root `.env` as `Client_ID` and `Client_secret`.
8. Create a Google API key for Picker, restrict it to the Google Picker API (and the APIs required by your project), and restrict its website referrer to `http://localhost:5173/*`. Set it as `VITE_GOOGLE_API_KEY` in `frontend/.env`.
9. Copy the Google Cloud project **number** (not its name) into `VITE_GOOGLE_APP_ID`.
10. Restart the frontend, open Support Studio, and choose **Connect Google Drive**. Complete the Google consent flow.

After connecting, select Drive files or folders for an agent and choose **Index**. Drive changes are synchronized manually using **Sync changes**. The original Drive files are not copied into the repository; extracted content is chunked and embedded into Chroma, with source metadata tracked in PostgreSQL.

## WhatsApp test-number connection

The current integration is for the developer's own Meta app and test number. It is not Embedded Signup and does not onboard other businesses. The access token from Meta's API Setup is temporary and must be replaced when it expires.

### Set up the Meta app

1. In [Meta for Developers](https://developers.facebook.com/), create/select your app and add the **Connect with customers through WhatsApp** use case.
2. Open the WhatsApp **API Setup** page. Use the provided test WhatsApp Business Account and test phone number for this demo.
3. Add and verify your own WhatsApp number as an allowed recipient in Meta's test-number setup. Record the **Phone Number ID** shown on API Setup.
4. Generate a temporary access token from the same Meta app and WhatsApp account.
5. In Meta **App settings → Basic**, copy the **App Secret**. This is used to validate webhook signatures; it is not the access token.

### Expose the webhook and configure Meta

Meta needs a public HTTPS URL to send webhook events to your local app. Keep Uvicorn running on port 8000 and use a trusted development tunnel to forward public HTTPS traffic to local port `8000`. Configure the tunnel's visibility so Meta can reach it. Do not expose the local model ports 8080 or 8081.

In the Meta app's WhatsApp webhook configuration, enter:

- **Callback URL:** `https://YOUR-PUBLIC-TUNNEL/whatsapp/webhook`
- **Verify token:** create any private string and enter the exact same value in Meta and the Support Studio WhatsApp settings
- Subscribe to the **messages** webhook field

Use the public tunnel hostname only for the webhook. Google OAuth should continue using its localhost callback.

### Save the connection in Support Studio

1. In the app, create/select the agent that should answer WhatsApp messages.
2. Open **WhatsApp setup** and enter the selected agent, Phone Number ID, temporary access token, Meta App Secret, and webhook verify token.
3. Save the settings. The backend encrypts the token, App Secret, and verify token before saving them to PostgreSQL.
4. In Meta, verify the webhook callback and subscribe to `messages`.
5. Send a WhatsApp message from the allowed recipient number to the Meta test number. The webhook queues the incoming text for the selected agent; the agent retrieves context from indexed sources, then the backend sends its answer using the WhatsApp Cloud API.

The backend validates `X-Hub-Signature-256` using the Meta App Secret. A `401 Unauthorized` on webhook POSTs usually means the saved App Secret is not the one for the Meta app delivering the event. A webhook verification failure usually means the verify-token strings do not match. Meta also sends non-message notifications; those receive an OK response and do not cause an agent reply.

The Meta temporary access token expires. Generate a replacement token from Meta API Setup and save it in WhatsApp setup. A permanent/production token and public deployment are outside this local demo setup.

## Local models and document processing

- `rag/managers/llm_manager.py` starts the Qwen3 chat GGUF through `llama-server.exe` on port 8080.
- `rag/managers/embeddings_manager.py` starts the Qwen3 embedding GGUF on port 8081. Embeddings are generated locally through the OpenAI-compatible local endpoint; no OpenAI API key is used.
- `rag/document_parsing/` contains file parsing, chunking, and Google Drive ingestion code.
- `rag/managers/vector_store.py` stores and removes document chunks in the persistent Chroma collection.
- `rag/services/rag_service.py` wires retrieval, embeddings, vector storage, and local generation together.

The app needs enough RAM for the chosen quantized models; startup errors about missing files usually mean the runtime or GGUF filenames do not match the paths above. The model weights and runtime are not included in a fresh clone.

## Data and troubleshooting

- PostgreSQL stores workspace, agent, Drive connection, selected-source, and WhatsApp connection metadata.
- `rag/data/chroma/` stores embeddings and chunk text locally. It persists across application restarts and is ignored by Git.
- `.env`, `frontend/.env`, model files, runtime binaries, and local databases must not be committed.
- If Google login fails, check that you are using `http://localhost:5173`, the redirect URI is exactly `http://localhost:8000/google/callback`, and your account is an OAuth test user if the app is in testing mode.
- If Google Picker does not open, check the browser API key, project number, enabled Picker API, referrer restriction, and restart Vite after editing `frontend/.env`.
- If WhatsApp webhook POSTs return `401`, verify the saved App Secret against the Meta app's current App Secret. If the subscription handshake fails, verify the callback URL and matching verify-token value.
- If a WhatsApp message receives no answer, check Uvicorn logs, ensure the webhook tunnel is still running, the sender is an allowed test recipient, the correct phone-number ID is saved, and the selected agent has any required Drive sources indexed.
- A missing `llama-server.exe` or GGUF file prevents the API from completing startup. Check the exact file locations and filenames before starting Uvicorn.

## Repository notes

- `app.py` contains the FastAPI routes and starts/stops the RAG service with the application lifecycle.
- `frontend/src/App.jsx` contains the React dashboard, agent management, Drive indexing, chat testing, and WhatsApp setup pages.
- `data_connection/db_models.py` contains the PostgreSQL models. Tables are created on startup with SQLAlchemy `create_all`; this project does not currently include a database migration system.
- `rag/main.py` is a terminal-only RAG test harness. For the platform, start the API with `uvicorn app:app --host localhost --port 8000`.
