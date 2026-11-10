import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import "./App.css";

const API = import.meta.env.VITE_API_BASE_URL;
const API_KEY = import.meta.env.VITE_GOOGLE_API_KEY;
const APP_ID = import.meta.env.VITE_GOOGLE_APP_ID;

function AgentAvatar({ name, small = false }) {
  const initials = name
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((part) => part[0].toUpperCase())
    .join("");
  return <span className={`avatar${small ? " avatar-small" : ""}`}>{initials || "A"}</span>;
}

export default function App() {
  const [connected, setConnected] = useState(false);
  const [message, setMessage] = useState("Checking connection...");
  const [selectedFiles, setSelectedFiles] = useState([]);
  const [agents, setAgents] = useState([]);
  const [selectedAgentId, setSelectedAgentId] = useState("");
  const [agentSources, setAgentSources] = useState([]);
  const [agentName, setAgentName] = useState("");
  const [agentDescription, setAgentDescription] = useState("");
  const [agentInstructions, setAgentInstructions] = useState("");
  const [agentTone, setAgentTone] = useState("helpful");
  const [agentCreating, setAgentCreating] = useState(false);
  const [agentCreateFeedback, setAgentCreateFeedback] = useState("");
  const [agentCreateFailed, setAgentCreateFailed] = useState(false);
  const [page, setPage] = useState("dashboard");
  const [messagesByAgent, setMessagesByAgent] = useState({});
  const [chatInput, setChatInput] = useState("");
  const [sending, setSending] = useState(false);
  const [chatError, setChatError] = useState("");
  const [whatsappAgentId, setWhatsappAgentId] = useState("");
  const [whatsappPhoneNumberId, setWhatsappPhoneNumberId] = useState("");
  const [whatsappAccessToken, setWhatsappAccessToken] = useState("");
  const [whatsappAppSecret, setWhatsappAppSecret] = useState("");
  const [whatsappVerifyToken, setWhatsappVerifyToken] = useState("");
  const [whatsappConfigured, setWhatsappConfigured] = useState(false);
  const [whatsappSaving, setWhatsappSaving] = useState(false);
  const [whatsappMessage, setWhatsappMessage] = useState("");
  const [whatsappError, setWhatsappError] = useState("");
  const [dashboardSourceCounts, setDashboardSourceCounts] = useState({});
  const chatEndRef = useRef(null);

  const selectedAgent = useMemo(
    () => agents.find((agent) => agent.id === selectedAgentId),
    [agents, selectedAgentId],
  );
  const chatMessages = useMemo(
    () => messagesByAgent[selectedAgentId] || [],
    [messagesByAgent, selectedAgentId],
  );
  const indexedDocumentCount = Object.values(dashboardSourceCounts).reduce(
    (sum, count) => sum + count,
    0,
  );
  const setupSteps = [
    { title: "Create an agent", description: "Set its support scope and response style.", done: agents.length > 0, page: "knowledge" },
    { title: "Connect Google Drive", description: "Choose the documents your agent can use.", done: connected, page: "knowledge" },
    { title: "Index knowledge", description: "Make Drive documents searchable in RAG.", done: indexedDocumentCount > 0, page: "knowledge" },
    { title: "Connect WhatsApp", description: "Route messages to your selected agent.", done: whatsappConfigured, page: "whatsapp" },
  ];

  const loadAgentSources = useCallback(async (agentId) => {
    if (!agentId) {
      setAgentSources([]);
      return;
    }
    try {
      const response = await fetch(`${API}/agents/${agentId}/sources`, {
        credentials: "include",
      });
      if (!response.ok) throw new Error("Could not load Drive sources.");
      const data = await response.json();
      setAgentSources(data.sources || []);
    } catch {
      setAgentSources([]);
    }
  }, []);

  const loadAgents = useCallback(async () => {
    try {
      const response = await fetch(`${API}/agents`, { credentials: "include" });
      if (!response.ok) throw new Error("Could not load agents.");
      const data = await response.json();
      const loadedAgents = data.agents || [];
      setAgents(loadedAgents);
      setSelectedAgentId((current) =>
        loadedAgents.some((agent) => agent.id === current)
          ? current
          : loadedAgents[0]?.id || "",
      );
      if (loadedAgents[0]?.id) loadAgentSources(loadedAgents[0].id);
    } catch {
      setMessage("Could not load agents. Check that the API is running.");
    }
  }, [loadAgentSources]);

  const checkConnection = useCallback(async () => {
    try {
      const response = await fetch(`${API}/google/status`, {
        credentials: "include",
      });
      const data = await response.json();
      setConnected(data.connected === true);
      setMessage(
        data.connected
          ? "Google Drive is connected."
          : "Connect your Google account to add knowledge.",
      );
    } catch {
      setConnected(false);
      setMessage("Could not reach the FastAPI backend.");
    }
  }, []);

  useEffect(() => {
    // Load initial API state for this browser session on mount.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    checkConnection();
    loadAgents();

    if (!window.gapi) {
      const script = document.createElement("script");
      script.src = "https://apis.google.com/js/api.js";
      script.async = true;
      document.body.appendChild(script);
    }
  }, [checkConnection, loadAgents]);

  useEffect(() => {
    if (page !== "whatsapp" && page !== "dashboard") return;
    let cancelled = false;
    (async () => {
      setWhatsappError("");
      try {
        const response = await fetch(`${API}/whatsapp/config`, { credentials: "include" });
        const data = await response.json();
        if (!response.ok) throw new Error(data.detail || "Could not load WhatsApp settings.");
        if (cancelled) return;
        setWhatsappConfigured(data.configured === true);
        setWhatsappAgentId(data.agent_id || selectedAgentId || agents[0]?.id || "");
        setWhatsappPhoneNumberId(data.phone_number_id || "");
      } catch (error) {
        if (!cancelled) setWhatsappError(error.message || "Could not load WhatsApp settings.");
      }
    })();
    return () => { cancelled = true; };
  }, [page, selectedAgentId, agents]);

  useEffect(() => {
    if (page !== "dashboard") return;
    let cancelled = false;
    (async () => {
      const results = await Promise.all(agents.map(async (agent) => {
        try {
          const response = await fetch(`${API}/agents/${agent.id}/sources`, { credentials: "include" });
          if (!response.ok) return [agent.id, 0];
          const data = await response.json();
          const count = (data.sources || []).filter(
            (source) => source.item_type === "file" && ["indexed", "unchanged"].includes(source.sync_status),
          ).length;
          return [agent.id, count];
        } catch {
          return [agent.id, 0];
        }
      }));
      if (!cancelled) setDashboardSourceCounts(Object.fromEntries(results));
    })();
    return () => { cancelled = true; };
  }, [page, agents]);

  useEffect(() => {
    chatEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [chatMessages, sending]);

  function chooseAgent(agentId) {
    setSelectedAgentId(agentId);
    setChatError("");
    loadAgentSources(agentId);
  }

  async function createAgent(event) {
    event.preventDefault();
    setAgentCreateFeedback("");
    setAgentCreateFailed(false);
    if (!agentName.trim()) {
      setAgentCreateFailed(true);
      setAgentCreateFeedback("Enter an agent name.");
      return;
    }
    setAgentCreating(true);
    try {
      const response = await fetch(`${API}/agents`, {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          name: agentName.trim(),
          description: agentDescription,
          instructions: agentInstructions,
          tone: agentTone,
        }),
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(data.detail || "Could not create agent.");
      setAgents((current) => [...current, data.agent]);
      chooseAgent(data.agent.id);
      setAgentName("");
      setAgentDescription("");
      setAgentInstructions("");
      setAgentTone("helpful");
      setAgentCreateFeedback(`“${data.agent.name}” was created.`);
    } catch (error) {
      setAgentCreateFailed(true);
      setAgentCreateFeedback(error.message || "Could not create agent.");
    } finally {
      setAgentCreating(false);
    }
  }

  async function deleteAgent(agent) {
    const confirmed = window.confirm(
      `Delete "${agent.name}"? This removes the agent, its indexed chunks and source records, and its WhatsApp connection if one is assigned. The original Google Drive files will not be deleted.`,
    );
    if (!confirmed) return;

    try {
      const response = await fetch(`${API}/agents/${agent.id}`, {
        method: "DELETE",
        credentials: "include",
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || "Could not delete agent.");

      const remainingAgents = agents.filter((item) => item.id !== agent.id);
      setAgents(remainingAgents);
      setMessagesByAgent((current) => {
        const next = { ...current };
        delete next[agent.id];
        return next;
      });
      if (selectedAgentId === agent.id) {
        setSelectedAgentId(remainingAgents[0]?.id || "");
        setAgentSources([]);
      }
      if (whatsappAgentId === agent.id) {
        setWhatsappAgentId(remainingAgents[0]?.id || "");
        setWhatsappConfigured(false);
      }
      setMessage(`Deleted ${agent.name} and ${data.chunks_deleted} indexed chunk(s).`);
    } catch (error) {
      setMessage(error.message || "Could not delete agent.");
    }
  }

  function connectGoogleDrive() {
    window.location.href = `${API}/google/login`;
  }

  async function selectFiles() {
    try {
      if (!API_KEY || !APP_ID) {
        setMessage("Configure the Google API key and project number in frontend/.env, then restart Vite.");
        return;
      }

      setMessage("Opening Google Picker...");
      const tokenResponse = await fetch(`${API}/google/picker-token`, {
        credentials: "include",
      });
      if (!tokenResponse.ok) throw new Error("Could not get an access token. Reconnect Drive.");
      const { access_token } = await tokenResponse.json();

      if (!window.gapi) {
        await new Promise((resolve, reject) => {
          let attempts = 0;
          const timer = setInterval(() => {
            attempts++;
            if (window.gapi) {
              clearInterval(timer);
              resolve();
            } else if (attempts >= 50) {
              clearInterval(timer);
              reject(new Error("Google Picker library failed to load."));
            }
          }, 100);
        });
      }

      window.gapi.load("picker", () => {
        const view = new window.google.picker.DocsView(window.google.picker.ViewId.DOCS);
        view.setIncludeFolders(true);
        view.setSelectFolderEnabled(true);
        const picker = new window.google.picker.PickerBuilder()
          .setDeveloperKey(API_KEY)
          .setAppId(APP_ID)
          .setOAuthToken(access_token)
          .addView(view)
          .enableFeature(window.google.picker.Feature.MULTISELECT_ENABLED)
          .setCallback((data) => {
            if (data.action === window.google.picker.Action.PICKED) {
              const files = data.docs.map((doc) => ({
                id: doc.id,
                name: doc.name,
                mimeType: doc.mimeType,
              }));
              setSelectedFiles(files);
              setMessage(`Selected ${files.length} item(s).`);
            } else if (data.action === window.google.picker.Action.CANCEL) {
              setMessage("File selection cancelled.");
            }
          })
          .build();
        picker.setVisible(true);
      });
    } catch (error) {
      setMessage(error.message || "Could not open Google Picker.");
    }
  }

  async function indexSelectedFiles() {
    if (!selectedAgentId) {
      setMessage("Create or select an agent before indexing Drive files.");
      return;
    }
    if (selectedFiles.length === 0) {
      setMessage("Select at least one file or folder first.");
      return;
    }
    try {
      setMessage("Indexing selected Google Drive files...");
      const response = await fetch(`${API}/google/index`, {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          agent_id: selectedAgentId,
          selected_items: selectedFiles.map(({ id, name, mimeType }) => ({ id, name, mimeType })),
        }),
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || "Indexing failed.");
      setMessage(`Indexing finished. Indexed: ${data.indexed}, unchanged: ${data.skipped}, issues: ${data.errors?.length ?? 0}.`);
      if (data.errors?.length) console.warn("Google Drive ingestion issues:", data.errors);
      await loadAgentSources(selectedAgentId);
    } catch (error) {
      setMessage(error.message || "Google Drive indexing failed.");
    }
  }

  async function syncAgentSources() {
    if (!selectedAgentId) return;
    try {
      setMessage("Checking saved Google Drive sources for changes...");
      const response = await fetch(`${API}/agents/${selectedAgentId}/sources/sync`, {
        method: "POST",
        credentials: "include",
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || "Drive sync failed.");
      setMessage(`Sync finished. Indexed: ${data.indexed}, unchanged: ${data.skipped}, issues: ${data.errors?.length ?? 0}.`);
      await loadAgentSources(selectedAgentId);
    } catch (error) {
      setMessage(error.message || "Drive sync failed.");
    }
  }

  async function removeAgentSource(source) {
    if (!selectedAgentId) return;
    try {
      const response = await fetch(
        `${API}/agents/${selectedAgentId}/sources/${encodeURIComponent(source.drive_item_id)}`,
        { method: "DELETE", credentials: "include" },
      );
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || "Could not remove source.");
      setMessage(data.still_included_by_folder
        ? `Removed the direct selection for ${data.source}; it remains included by its selected folder.`
        : `Removed ${data.source} from this agent. Its indexed chunks were deleted.`);
      await loadAgentSources(selectedAgentId);
    } catch (error) {
      setMessage(error.message || "Could not remove source.");
    }
  }

  async function sendChatMessage(event) {
    event.preventDefault();
    const question = chatInput.trim();
    if (!question || !selectedAgentId || sending) return;

    const userMessage = { id: crypto.randomUUID(), role: "user", content: question };
    setMessagesByAgent((current) => ({
      ...current,
      [selectedAgentId]: [...(current[selectedAgentId] || []), userMessage],
    }));
    setChatInput("");
    setChatError("");
    setSending(true);
    const requestAgentId = selectedAgentId;

    try {
      const response = await fetch(`${API}/agents/${requestAgentId}/chat`, {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message: question }),
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || `Chat request failed (${response.status}).`);
      setMessagesByAgent((current) => ({
        ...current,
        [requestAgentId]: [
          ...(current[requestAgentId] || []),
          {
            id: crypto.randomUUID(),
            role: "assistant",
            content: data.answer || "The agent returned an empty answer.",
            sources: data.sources || [],
          },
        ],
      }));
    } catch (error) {
      setChatError(error.message || "Could not send the message.");
    } finally {
      setSending(false);
    }
  }

  function clearCurrentChat() {
    setMessagesByAgent((current) => ({ ...current, [selectedAgentId]: [] }));
    setChatError("");
  }

  async function saveWhatsappSettings(event) {
    event.preventDefault();
    setWhatsappSaving(true);
    setWhatsappMessage("");
    setWhatsappError("");
    try {
      const response = await fetch(`${API}/whatsapp/config`, {
        method: "PUT",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          agent_id: whatsappAgentId,
          phone_number_id: whatsappPhoneNumberId,
          access_token: whatsappAccessToken,
          app_secret: whatsappAppSecret,
          verify_token: whatsappVerifyToken,
        }),
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || "Could not save WhatsApp settings.");
      setWhatsappConfigured(true);
      setWhatsappAgentId(data.agent_id);
      setWhatsappPhoneNumberId(data.phone_number_id);
      setWhatsappAccessToken("");
      setWhatsappAppSecret("");
      setWhatsappVerifyToken("");
      setWhatsappMessage("WhatsApp settings saved. Credentials are encrypted in the database.");
    } catch (error) {
      setWhatsappError(error.message || "Could not save WhatsApp settings.");
    } finally {
      setWhatsappSaving(false);
    }
  }

  return (
    <div className="app-shell">
      <header className="topbar">
        <a className="brand" href="#home" onClick={(event) => { event.preventDefault(); setPage("dashboard"); }}>
          <span className="brand-mark">S</span>
          <span>support<span className="brand-light">studio</span></span>
        </a>
        <nav className="main-nav" aria-label="Main navigation">
          <button className={page === "dashboard" ? "nav-link active" : "nav-link"} onClick={() => setPage("dashboard")}>Dashboard</button>
          <button className={page === "agents" ? "nav-link active" : "nav-link"} onClick={() => setPage("agents")}>Agents</button>
          <button className={page === "knowledge" ? "nav-link active" : "nav-link"} onClick={() => setPage("knowledge")}>Knowledge</button>
          <button className={page === "whatsapp" ? "nav-link active" : "nav-link"} onClick={() => setPage("whatsapp")}>WhatsApp</button>
        </nav>
        <div className="topbar-status"><span className={`status-dot ${connected ? "online" : ""}`} />{connected ? "Drive connected" : "Drive not connected"}</div>
      </header>

      <main className="main-content">
        {page === "dashboard" ? (
          <>
            <section className="dashboard-hero">
              <div>
                <div className="eyebrow">SUPPORT STUDIO</div>
                <h1>Your support workspace</h1>
                <p>Manage your knowledge, test your support agents, and monitor your WhatsApp setup.</p>
              </div>
              <div className="dashboard-hero-actions">
                <button className="button button-primary" onClick={() => setPage("agents")}>Open agent chat <span aria-hidden="true">↗</span></button>
                <button className="button button-secondary" onClick={() => setPage("knowledge")}>Manage knowledge</button>
              </div>
            </section>

            <section className="dashboard-stats" aria-label="Workspace overview">
              <article className="dashboard-stat"><span className="dashboard-stat-icon green">✦</span><div><small>Support agents</small><strong>{agents.length}</strong><span>In your workspace</span></div></article>
              <article className="dashboard-stat"><span className="dashboard-stat-icon blue">▤</span><div><small>Indexed documents</small><strong>{Object.values(dashboardSourceCounts).reduce((sum, count) => sum + count, 0)}</strong><span>Across all agents</span></div></article>
              <article className="dashboard-stat"><span className="dashboard-stat-icon gold">G</span><div><small>Google Drive</small><strong>{connected ? "Connected" : "Not connected"}</strong><span>{connected ? "Knowledge source ready" : "Connect to add documents"}</span></div><i className={`dashboard-status-dot ${connected ? "ok" : "pending"}`} /></article>
              <article className="dashboard-stat"><span className="dashboard-stat-icon whatsapp">◉</span><div><small>WhatsApp</small><strong>{whatsappConfigured ? "Configured" : "Not connected"}</strong><span>{whatsappConfigured ? `Agent: ${agents.find((agent) => agent.id === whatsappAgentId)?.name || "Selected"}` : "Connect your test number"}</span></div><i className={`dashboard-status-dot ${whatsappConfigured ? "ok" : "pending"}`} /></article>
            </section>

            <section className="dashboard-content-grid">
              <section className="dashboard-panel dashboard-agents-panel">
                <div className="dashboard-panel-heading"><div><div className="eyebrow">WORKSPACE</div><h2>Your agents</h2></div><button className="text-button" onClick={() => setPage("knowledge")}>Create agent <span aria-hidden="true">→</span></button></div>
                {agents.length === 0 ? (
                  <div className="dashboard-empty"><span className="welcome-icon">✦</span><strong>No agents yet</strong><p>Create your first support agent and connect it to your knowledge.</p><button className="button button-primary" onClick={() => setPage("knowledge")}>Create an agent</button></div>
                ) : (
                  <div className="dashboard-agent-list">
                    {agents.map((agent) => (
                      <article className="dashboard-agent-row" key={agent.id}>
                        <AgentAvatar name={agent.name} />
                        <div className="dashboard-agent-copy"><strong>{agent.name}</strong><span>{agent.description || `${agent.tone || "Helpful"} support agent`}</span></div>
                        <span className="dashboard-agent-sources">{dashboardSourceCounts[agent.id] ?? 0} docs</span>
                        <button className="button button-secondary dashboard-row-action" onClick={() => { chooseAgent(agent.id); setPage("agents"); }}>Test agent</button>
                      </article>
                    ))}
                  </div>
                )}
                {selectedAgent && (
                  <div className="dashboard-agent-spotlight">
                    <div className="dashboard-spotlight-heading"><span>SELECTED AGENT</span><span className="dashboard-spotlight-tone">{selectedAgent.tone || "helpful"} tone</span></div>
                    <div className="dashboard-spotlight-main"><AgentAvatar name={selectedAgent.name} /><div><strong>{selectedAgent.name}</strong><p>{selectedAgent.description || "Ready to answer questions using its instructions and indexed knowledge."}</p></div></div>
                    <div className="dashboard-spotlight-footer"><span>{dashboardSourceCounts[selectedAgent.id] ?? 0} indexed documents</span><span className={whatsappAgentId === selectedAgent.id && whatsappConfigured ? "assigned" : "unassigned"}>{whatsappAgentId === selectedAgent.id && whatsappConfigured ? "WhatsApp assigned" : "WhatsApp not assigned"}</span><button className="text-button" onClick={() => setPage("agents")}>Open chat →</button></div>
                  </div>
                )}
              </section>

              <section className="dashboard-panel dashboard-setup-panel">
                <div className="dashboard-panel-heading"><div><div className="eyebrow">QUICK ACCESS</div><h2>Keep building</h2></div></div>
                <button className="dashboard-action" onClick={() => setPage("knowledge")}><span className="dashboard-action-icon">▤</span><span><strong>Manage knowledge</strong><small>Choose Drive files and sync updates</small></span><b>→</b></button>
                <button className="dashboard-action" onClick={() => setPage("agents")}><span className="dashboard-action-icon">✦</span><span><strong>Test an agent</strong><small>Try questions against its indexed sources</small></span><b>→</b></button>
                <button className="dashboard-action" onClick={() => setPage("whatsapp")}><span className="dashboard-action-icon whatsapp">◉</span><span><strong>WhatsApp setup</strong><small>{whatsappConfigured ? "Review the connected agent" : "Connect a test number"}</small></span><b>→</b></button>
              </section>
            </section>

            <section className="dashboard-panel dashboard-checklist-panel">
              <div className="dashboard-panel-heading"><div><div className="eyebrow">SETUP PROGRESS</div><h2>Build your support workflow</h2></div><span className="checklist-count">{setupSteps.filter((step) => step.done).length} of {setupSteps.length} complete</span></div>
              <div className="dashboard-checklist-grid">
                {setupSteps.map((step, index) => (
                  <article className={`checklist-step${step.done ? " complete" : ""}`} key={step.title}>
                    <span className="checklist-step-number">{step.done ? "✓" : `0${index + 1}`}</span>
                    <div><strong>{step.title}</strong><p>{step.description}</p><button className="text-button" onClick={() => setPage(step.page)}>{step.done ? "Review" : "Set up"} <span aria-hidden="true">→</span></button></div>
                  </article>
                ))}
              </div>
            </section>
          </>
        ) : page === "agents" ? (
          <>
            <section className="page-heading">
              <div>
                <div className="eyebrow">AGENT WORKSPACE</div>
                <h1>Test your support agents</h1>
                <p>Chat with an agent to check its knowledge, instructions, and tone.</p>
              </div>
              <button className="button button-secondary" onClick={() => setPage("knowledge")}>Manage knowledge <span aria-hidden="true">↗</span></button>
            </section>

            <section className="agent-workspace">
              <aside className="agent-sidebar">
                <div className="sidebar-heading"><span>Your agents</span><span className="agent-count">{agents.length}</span></div>
                {agents.length === 0 ? (
                  <div className="empty-agents"><p>No agents yet.</p><button className="text-button" onClick={() => setPage("knowledge")}>Create your first agent</button></div>
                ) : (
                  <div className="agent-list">
                    {agents.map((agent) => (
                      <button
                        key={agent.id}
                        className={`agent-option${selectedAgentId === agent.id ? " selected" : ""}`}
                        onClick={() => chooseAgent(agent.id)}
                      >
                        <AgentAvatar name={agent.name} small />
                        <span className="agent-option-copy"><strong>{agent.name}</strong><small>{agent.description || "Support agent"}</small></span>
                        <span className={`agent-status ${agent.status === "live" ? "live" : "draft"}`}>{agent.status}</span>
                      </button>
                    ))}
                  </div>
                )}
                <div className="sidebar-footnote">Each agent has its own knowledge and configuration.</div>
              </aside>

              <section className="chat-panel" aria-label="Agent test chat">
                {selectedAgent ? (
                  <>
                    <div className="chat-header">
                      <div className="chat-agent-info">
                        <AgentAvatar name={selectedAgent.name} />
                        <div><h2>{selectedAgent.name}</h2><p>{selectedAgent.description || "Support agent"}</p></div>
                      </div>
                      <div className="chat-header-actions">
                        <span className="configuration-chip">{selectedAgent.tone || "helpful"} tone</span>
                        <button className="icon-button" onClick={clearCurrentChat} aria-label="Clear this conversation" title="Clear conversation">↻</button>
                      </div>
                    </div>

                    <div className="chat-messages" aria-live="polite">
                      {chatMessages.length === 0 ? (
                        <div className="chat-welcome">
                          <div className="welcome-icon">✦</div>
                          <h3>Test {selectedAgent.name}</h3>
                          <p>Ask a question to see how this agent responds using its instructions and connected knowledge.</p>
                          <div className="suggestion-list">
                            <button onClick={() => setChatInput("What can you help me with?")}>What can you help me with?</button>
                            <button onClick={() => setChatInput("Answer a question using the connected documents.")}>Ask about connected documents</button>
                          </div>
                        </div>
                      ) : chatMessages.map((entry) => (
                        <article className={`message-row ${entry.role}`} key={entry.id}>
                          {entry.role === "assistant" && <AgentAvatar name={selectedAgent.name} small />}
                          <div className="message-content">
                            <div className="message-bubble">{entry.content}</div>
                            {entry.sources?.length > 0 && (
                              <div className="message-sources">
                                <span className="sources-label">SOURCES</span>
                                {entry.sources.map((source, index) => (
                                  <span className="source-chip" key={`${source.document_id || source.source_file || index}-${index}`}>
                                    <span aria-hidden="true">▤</span> {source.source_file || source.document_id || `Source ${source.source_id}`}{source.page != null ? ` · p. ${source.page}` : ""}
                                  </span>
                                ))}
                              </div>
                            )}
                          </div>
                        </article>
                      ))}
                      {sending && <div className="message-row assistant"><AgentAvatar name={selectedAgent.name} small /><div className="typing-indicator"><i /><i /><i /></div></div>}
                      <div ref={chatEndRef} />
                    </div>

                    {chatError && <div className="chat-error" role="alert">{chatError}</div>}
                    <form className="chat-composer" onSubmit={sendChatMessage}>
                      <textarea
                        aria-label="Message the selected agent"
                        placeholder={`Message ${selectedAgent.name}...`}
                        value={chatInput}
                        onChange={(event) => setChatInput(event.target.value)}
                        onKeyDown={(event) => {
                          if (event.key === "Enter" && !event.shiftKey) {
                            event.preventDefault();
                            event.currentTarget.form.requestSubmit();
                          }
                        }}
                        rows={1}
                        disabled={sending}
                      />
                      <button className="send-button" type="submit" disabled={!chatInput.trim() || sending} aria-label="Send message">↑</button>
                      <div className="composer-hint">Enter to send · Shift + Enter for a new line</div>
                    </form>
                  </>
                ) : (
                  <div className="no-agent"><div className="welcome-icon">✦</div><h2>Select an agent to start testing</h2><p>Choose an agent from the list or create one in Knowledge.</p><button className="button button-primary" onClick={() => setPage("knowledge")}>Create an agent</button></div>
                )}
              </section>
            </section>
          </>
        ) : page === "knowledge" ? (
          <>
            <section className="page-heading">
              <div><div className="eyebrow">SETUP</div><h1>Agents & knowledge</h1><p>Create an agent and connect the Drive content it should use.</p></div>
              <button className="button button-secondary" onClick={() => setPage("agents")}>← Back to test chat</button>
            </section>
            <div className="setup-grid">
              <section className="setup-card">
                <div className="card-title"><div><div className="eyebrow">CONFIGURATION</div><h2>Create a support agent</h2></div><span className="card-icon">✦</span></div>
                <form onSubmit={createAgent} className="agent-form">
                  <label>Agent name<input required value={agentName} onChange={(event) => setAgentName(event.target.value)} placeholder="e.g. Customer support" /></label>
                  <label>What does this agent support?<input value={agentDescription} onChange={(event) => setAgentDescription(event.target.value)} placeholder="Describe what it helps customers with" /></label>
                  <label>Instructions<textarea rows={4} value={agentInstructions} onChange={(event) => setAgentInstructions(event.target.value)} placeholder="Give the agent specific guidance..." /></label>
                  <label>Tone<select value={agentTone} onChange={(event) => setAgentTone(event.target.value)}><option value="helpful">Helpful</option><option value="friendly">Friendly</option><option value="professional">Professional</option><option value="concise">Concise</option></select></label>
                  <button className="button button-primary" type="submit" disabled={agentCreating}>{agentCreating ? "Creating agent..." : "Create draft agent"}</button>
                </form>
                {agentCreateFeedback && <p className={`agent-form-feedback${agentCreateFailed ? " error" : " success"}`} role={agentCreateFailed ? "alert" : "status"}>{agentCreateFeedback}</p>}
                {agents.length > 0 && <div className="existing-agents"><div className="sidebar-heading"><span>Existing agents</span><span className="agent-count">{agents.length}</span></div>{agents.map((agent) => <div className="existing-agent-row" key={agent.id}><button className={`existing-agent${selectedAgentId === agent.id ? " selected" : ""}`} onClick={() => chooseAgent(agent.id)}><AgentAvatar name={agent.name} small /><span><strong>{agent.name}</strong><small>{agent.status} · {agent.tone} tone</small></span>{selectedAgentId === agent.id && <span className="selected-check">✓</span>}</button><button className="delete-agent-button" type="button" title={`Delete ${agent.name}`} aria-label={`Delete ${agent.name}`} onClick={() => deleteAgent(agent)}>×</button></div>)}</div>}
              </section>

              <section className="setup-card knowledge-card">
                <div className="card-title"><div><div className="eyebrow">GOOGLE DRIVE</div><h2>Agent knowledge</h2><p className="card-description">Choose Drive files to add to the selected agent.</p></div><span className="drive-icon">G</span></div>
                {!connected ? <div className="connect-box"><span className="drive-icon">G</span><div><strong>Connect your Google Drive</strong><p>Pick documents and folders for this agent to learn from.</p></div><button className="button button-secondary" onClick={connectGoogleDrive}>Connect Drive</button></div> : <div className="drive-connected"><span className="status-dot online" /><span>Google Drive connected</span><button className="text-button" onClick={checkConnection}>Check status</button></div>}

                <div className="sources-heading"><div><h3>Sources{selectedAgent ? ` · ${selectedAgent.name}` : ""}</h3><p>Files currently available to this agent</p></div>{agentSources.length > 0 && <span className="agent-count">{agentSources.length}</span>}</div>
                {!selectedAgent ? <div className="empty-state compact">Create or select an agent to manage its sources.</div> : agentSources.length === 0 ? <div className="empty-state compact"><span className="empty-file">▤</span><strong>No sources added yet</strong><p>Select files from Drive, then index them for this agent.</p></div> : <div className="source-list">{agentSources.map((source) => <div className="source-row" key={source.drive_item_id}><span className="file-icon">{source.item_type === "folder" ? "▰" : "▤"}</span><div className="source-copy"><strong>{source.name}</strong><small>{source.item_type} · {source.sync_status}{source.last_synced_at ? ` · synced ${new Date(source.last_synced_at).toLocaleString()}` : ""}</small></div>{source.is_selected && <button className="remove-source" onClick={() => removeAgentSource(source)} aria-label={`Remove ${source.name}`} title="Remove source">×</button>}</div>)}</div>}

                {connected && <div className="drive-actions"><button className="button button-secondary" onClick={selectFiles} disabled={!selectedAgentId}>Select files or folders</button>{selectedAgentId && agentSources.some((source) => source.is_selected) && <button className="button button-quiet" onClick={syncAgentSources}>Sync changes</button>}</div>}
                {selectedFiles.length > 0 && <div className="pending-files"><strong>Ready to index</strong>{selectedFiles.map((file) => <span key={file.id}>▤ {file.name}</span>)}<button className="button button-primary" onClick={indexSelectedFiles} disabled={!selectedAgentId}>Index for {selectedAgent?.name || "agent"}</button></div>}
                {message && <p className="status-message" role="status">{message}</p>}
              </section>
            </div>
          </>
        ) : (
          <>
            <section className="page-heading">
              <div><div className="eyebrow">CHANNEL SETUP</div><h1>WhatsApp connection</h1><p>Choose which support agent answers messages sent to your WhatsApp test number.</p></div>
              <span className={`connection-pill ${whatsappConfigured ? "connected" : "disconnected"}`}><i />{whatsappConfigured ? "Configured" : "Not configured"}</span>
            </section>
            <div className="whatsapp-layout">
              <section className="setup-card whatsapp-card">
                <div className="card-title"><div><div className="eyebrow">WHATSAPP CLOUD API</div><h2>Connect your test number</h2><p className="card-description">Credentials are encrypted before being saved. They are never shown again after saving.</p></div><span className="whatsapp-icon">◉</span></div>
                <form className="agent-form" onSubmit={saveWhatsappSettings}>
                  <label>Agent<select required value={whatsappAgentId} onChange={(event) => setWhatsappAgentId(event.target.value)}><option value="" disabled>Select an agent</option>{agents.map((agent) => <option key={agent.id} value={agent.id}>{agent.name}</option>)}</select></label>
                  <label>Phone Number ID<input required value={whatsappPhoneNumberId} onChange={(event) => setWhatsappPhoneNumberId(event.target.value)} placeholder="From Meta → WhatsApp → API Setup" /></label>
                  <label>Access token<input type="password" autoComplete="new-password" value={whatsappAccessToken} onChange={(event) => setWhatsappAccessToken(event.target.value)} placeholder={whatsappConfigured ? "Saved; enter a new token only to rotate it" : "Temporary token from Meta API Setup"} /></label>
                  <label>Meta App Secret<input type="password" autoComplete="new-password" value={whatsappAppSecret} onChange={(event) => setWhatsappAppSecret(event.target.value)} placeholder={whatsappConfigured ? "Saved; enter a new secret only to rotate it" : "App settings → Basic → App Secret"} /></label>
                  <label>Webhook verify token<input type="password" autoComplete="new-password" value={whatsappVerifyToken} onChange={(event) => setWhatsappVerifyToken(event.target.value)} placeholder={whatsappConfigured ? "Saved; leave blank to keep it" : "The same private value entered in Meta"} /></label>
                  <button className="button button-primary" type="submit" disabled={whatsappSaving || agents.length === 0}>{whatsappSaving ? "Saving…" : whatsappConfigured ? "Save WhatsApp settings" : "Connect WhatsApp"}</button>
                </form>
                {whatsappError && <p className="whatsapp-feedback error" role="alert">{whatsappError}</p>}
                {whatsappMessage && <p className="whatsapp-feedback success" role="status">{whatsappMessage}</p>}
              </section>
            </div>
          </>
        )}
      </main>
      <footer className="app-footer"><span>Support Studio</span><span>Local support agent workspace</span></footer>
    </div>
  );
}
