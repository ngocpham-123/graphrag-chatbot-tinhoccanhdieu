// ── State ──
let currentConversationId = null;
let conversations = {}; // { id: { title, messages: [{role, content}] } }

// ── DOM refs ──
const sidebar = document.getElementById("sidebar");
const sidebarToggle = document.getElementById("sidebar-toggle");
const newChatBtn = document.getElementById("new-chat-btn");
const conversationList = document.getElementById("conversation-list");
const messagesContainer = document.getElementById("messages");
const chatForm = document.getElementById("chat-form");
const userInput = document.getElementById("user-input");
const sendBtn = document.getElementById("send-btn");
const chatTitle = document.getElementById("chat-title");
const sparqlInput = document.getElementById("sparql-input");
const sparqlRunBtn = document.getElementById("sparql-run-btn");
const graphOverlay = document.getElementById("graph-overlay");
const graphCloseBtn = document.getElementById("graph-close-btn");
const graphContainer = document.getElementById("graph-container");
const graphError = document.getElementById("graph-error");
const imageInput = document.getElementById("image-input");
const attachBtn = document.getElementById("attach-btn");
const imagePreview = document.getElementById("image-preview");
const imagePreviewImg = document.getElementById("image-preview-img");
const imageRemoveBtn = document.getElementById("image-remove-btn");

// Holds the currently attached image as a base64 data URL (or null)
let selectedImage = null;

attachBtn.addEventListener("click", () => imageInput.click());

imageInput.addEventListener("change", () => {
  const file = imageInput.files && imageInput.files[0];
  if (!file) return;
  const reader = new FileReader();
  reader.onload = () => {
    selectedImage = reader.result; // data URL
    imagePreviewImg.src = selectedImage;
    imagePreview.classList.remove("hidden");
  };
  reader.readAsDataURL(file);
});

imageRemoveBtn.addEventListener("click", clearSelectedImage);

function clearSelectedImage() {
  selectedImage = null;
  imageInput.value = "";
  imagePreviewImg.removeAttribute("src");
  imagePreview.classList.add("hidden");
}

// ── Sidebar toggle ──
sidebarToggle.addEventListener("click", () => {
  sidebar.classList.toggle("hidden");
});

// ── Auto-resize textarea ──
userInput.addEventListener("input", () => {
  userInput.style.height = "auto";
  userInput.style.height = Math.min(userInput.scrollHeight, 200) + "px";
});

// ── Submit on Enter (Shift+Enter for newline) ──
userInput.addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey) {
    e.preventDefault();
    chatForm.dispatchEvent(new Event("submit"));
  }
});

// ── New chat ──
newChatBtn.addEventListener("click", () => startNewChat());

function startNewChat() {
  currentConversationId = null;
  chatTitle.textContent = "New Chat";
  messagesContainer.innerHTML = `
    <div class="welcome">
      <h2>GraphRAG Chatbot</h2>
      <p>Ask anything about Tin Học Cánh Diều. Your questions are answered using a knowledge graph + ChatGPT.</p>
    </div>`;
  renderConversationList();
  userInput.focus();
}

// ── Render sidebar conversations ──
function renderConversationList() {
  conversationList.innerHTML = "";
  const ids = Object.keys(conversations).reverse();
  for (const id of ids) {
    const conv = conversations[id];
    const item = document.createElement("div");
    item.className =
      "conversation-item" + (id === currentConversationId ? " active" : "");

    const titleSpan = document.createElement("span");
    titleSpan.textContent = conv.title || "New Chat";
    titleSpan.style.overflow = "hidden";
    titleSpan.style.textOverflow = "ellipsis";
    titleSpan.style.flex = "1";
    item.appendChild(titleSpan);

    const deleteBtn = document.createElement("button");
    deleteBtn.className = "delete-btn";
    deleteBtn.textContent = "✕";
    deleteBtn.addEventListener("click", (e) => {
      e.stopPropagation();
      deleteConversation(id);
    });
    item.appendChild(deleteBtn);

    item.addEventListener("click", () => loadConversation(id));
    conversationList.appendChild(item);
  }
}

// ── Load a conversation ──
function loadConversation(id) {
  currentConversationId = id;
  const conv = conversations[id];
  chatTitle.textContent = conv.title || "New Chat";
  messagesContainer.innerHTML = "";
  for (const msg of conv.messages) {
    if (msg.role === "assistant" && msg.sparql_query) {
      appendSparqlBadge(msg.sparql_query);
    }
    appendMessage(msg.role, msg.content, msg.figure_paths, msg.image);
  }
  renderConversationList();
  scrollToBottom();
}

// ── Delete conversation ──
async function deleteConversation(id) {
  delete conversations[id];
  if (currentConversationId === id) {
    startNewChat();
  } else {
    renderConversationList();
  }
  try {
    await fetch(`/api/chat/${id}`, { method: "DELETE" });
  } catch (_) {
    // ignore
  }
}

// ── Append message to DOM ──
function appendMessage(role, content, figurePaths, imageDataUrl) {
  // Remove welcome message if present
  const welcome = messagesContainer.querySelector(".welcome");
  if (welcome) welcome.remove();

  const row = document.createElement("div");
  row.className = "message-row";

  const msgDiv = document.createElement("div");
  msgDiv.className = `message ${role}`;
  msgDiv.innerHTML = formatContent(content);

  // Show an attached image (user-sent) above the text
  if (imageDataUrl) {
    const img = document.createElement("img");
    img.className = "message-image";
    img.src = imageDataUrl;
    img.alt = "attached image";
    img.addEventListener("click", () => window.open(img.src, "_blank"));
    msgDiv.insertBefore(img, msgDiv.firstChild);
  }

  // Append figure images if present
  if (figurePaths && figurePaths.length > 0) {
    const gallery = document.createElement("div");
    gallery.className = "figure-gallery";
    for (const path of figurePaths) {
      const src = path.startsWith("/") || path.startsWith("http") ? path : `/figures/${path}`;
      const img = document.createElement("img");
      img.className = "figure-image";
      img.src = src;
      img.alt = path;
      img.loading = "lazy";
      img.addEventListener("click", () => window.open(img.src, "_blank"));
      gallery.appendChild(img);
    }
    msgDiv.appendChild(gallery);
  }

  row.appendChild(msgDiv);
  messagesContainer.appendChild(row);
}

// ── Basic markdown-like formatting ──
function formatContent(text) {
  return text
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/```(\w*)\n([\s\S]*?)```/g, "<pre><code>$2</code></pre>")
    .replace(/`([^`]+)`/g, "<code>$1</code>")
    .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
    .replace(/\n/g, "<br>");
}

// ── SPARQL badge ──
function appendSparqlBadge(query) {
  const row = document.createElement("div");
  row.className = "message-row";

  const badge = document.createElement("div");
  badge.className = "sparql-badge";

  const header = document.createElement("div");
  header.className = "sparql-badge-header";
  header.innerHTML =
    `<span>SPARQL Query Executed</span>` +
    `<span class="sparql-actions">` +
    `<button class="sparql-toggle">Show</button>` +
    `<button class="sparql-graph-toggle">Show graph</button>` +
    `</span>`;
  badge.appendChild(header);

  const codeBlock = document.createElement("pre");
  codeBlock.className = "sparql-code hidden";
  codeBlock.textContent = query;
  badge.appendChild(codeBlock);

  const graphBox = document.createElement("div");
  graphBox.className = "sparql-graph hidden";
  badge.appendChild(graphBox);

  header.querySelector(".sparql-toggle").addEventListener("click", (e) => {
    const isHidden = codeBlock.classList.toggle("hidden");
    e.target.textContent = isHidden ? "Show" : "Hide";
  });

  let graphRendered = false;
  header.querySelector(".sparql-graph-toggle").addEventListener("click", async (e) => {
    const btn = e.target;
    if (graphRendered) {
      const isHidden = graphBox.classList.toggle("hidden");
      btn.textContent = isHidden ? "Show graph" : "Hide graph";
      return;
    }
    btn.disabled = true;
    btn.textContent = "Loading…";
    graphBox.classList.remove("hidden");
    graphBox.textContent = "";
    try {
      const res = await fetch("/api/chat/sparql", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ query }),
      });
      if (!res.ok) {
        const err = await res.json();
        throw new Error(err.detail || "Query failed");
      }
      const data = await res.json();
      if (!data.rows || data.rows.length === 0) {
        graphBox.textContent = "Query returned no results.";
      } else {
        await renderGraphInto(graphBox, data.columns, data.rows);
      }
      graphRendered = true;
      btn.textContent = "Hide graph";
    } catch (err) {
      graphBox.textContent = `Error: ${err.message}`;
      graphRendered = true;
      btn.textContent = "Hide graph";
    } finally {
      btn.disabled = false;
    }
  });

  row.appendChild(badge);
  messagesContainer.appendChild(row);
}

// ── Typing indicator ──
function showTypingIndicator() {
  const row = document.createElement("div");
  row.className = "message-row";
  row.id = "typing-row";

  const msgDiv = document.createElement("div");
  msgDiv.className = "message assistant";
  msgDiv.innerHTML = `<div class="typing-indicator"><span></span><span></span><span></span></div>`;
  row.appendChild(msgDiv);

  messagesContainer.appendChild(row);
  scrollToBottom();
}

function removeTypingIndicator() {
  const el = document.getElementById("typing-row");
  if (el) el.remove();
}

function scrollToBottom() {
  messagesContainer.scrollTop = messagesContainer.scrollHeight;
}

// ── Form submit ──
chatForm.addEventListener("submit", async (e) => {
  e.preventDefault();
  const message = userInput.value.trim();
  if (!message && !selectedImage) return;
  const imageToSend = selectedImage;

  // Display user message
  appendMessage("user", message, null, imageToSend);
  clearSelectedImage();
  userInput.value = "";
  userInput.style.height = "auto";
  sendBtn.disabled = true;
  scrollToBottom();

  // Show typing indicator
  showTypingIndicator();

  try {
    const res = await fetch("/api/chat/", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        message,
        conversation_id: currentConversationId,
        image: imageToSend || null,
      }),
    });

    if (!res.ok) {
      const err = await res.json();
      throw new Error(err.detail || "Server error");
    }

    const data = await res.json();
    removeTypingIndicator();

    // Update conversation
    currentConversationId = data.conversation_id;
    if (!conversations[currentConversationId]) {
      conversations[currentConversationId] = {
        title: message.slice(0, 40) + (message.length > 40 ? "…" : ""),
        messages: [],
      };
    }
    const conv = conversations[currentConversationId];
    conv.messages.push({ role: "user", content: message, image: imageToSend });
    conv.messages.push({
      role: "assistant",
      content: data.reply,
      sparql_query: data.sparql_query,
      figure_paths: data.figure_paths,
    });

    chatTitle.textContent = conv.title;

    // Show SPARQL query if one was executed
    if (data.sparql_query) {
      appendSparqlBadge(data.sparql_query);
    }
    appendMessage("assistant", data.reply, data.figure_paths);
    renderConversationList();
  } catch (err) {
    removeTypingIndicator();
    appendMessage("assistant", `⚠️ Error: ${err.message}`);
  } finally {
    sendBtn.disabled = false;
    scrollToBottom();
    userInput.focus();
  }
});

// ── SPARQL editor & graph visualization ─────────────────────────

// Close graph overlay
graphCloseBtn.addEventListener("click", () => {
  graphOverlay.classList.add("hidden");
});
graphOverlay.addEventListener("click", (e) => {
  if (e.target === graphOverlay) graphOverlay.classList.add("hidden");
});

// ── Figure manifest: basename-without-extension → filename ──
let figureManifest = null;

async function loadFigureManifest() {
  if (figureManifest) return figureManifest;
  figureManifest = new Map();
  try {
    const res = await fetch("/figures/manifest");
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    for (const filename of data.figures || []) {
      const base = filename.replace(/\.[^.]+$/, "");
      figureManifest.set(base, filename);
    }
  } catch (err) {
    console.warn("Could not load figure manifest:", err);
  }
  return figureManifest;
}

// If a URI's local name matches an image in the assets folder,
// return its serveable URL; otherwise null.
function figureUrlForValue(value) {
  if (!value || !figureManifest) return null;
  const filename = figureManifest.get(localName(value));
  return filename ? `/figures/${encodeURIComponent(filename)}` : null;
}

// Extract local name from a URI
function localName(uri) {
  if (!uri) return uri;
  const hashIdx = uri.lastIndexOf("#");
  if (hashIdx !== -1) return uri.substring(hashIdx + 1);
  const slashIdx = uri.lastIndexOf("/");
  if (slashIdx !== -1) return uri.substring(slashIdx + 1);
  return uri;
}

// Execute SPARQL
sparqlRunBtn.addEventListener("click", async () => {
  const query = sparqlInput.value.trim();
  if (!query) return;

  sparqlRunBtn.disabled = true;
  sparqlRunBtn.textContent = "Running…";
  graphError.classList.add("hidden");

  try {
    const res = await fetch("/api/chat/sparql", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ query }),
    });

    if (!res.ok) {
      const err = await res.json();
      throw new Error(err.detail || "Query failed");
    }

    const data = await res.json();
    console.log("SPARQL response:", data);
    console.log("Columns:", data.columns, "Rows:", data.rows.length);
    await renderGraph(data.columns, data.rows);
  } catch (err) {
    graphError.textContent = err.message;
    graphError.classList.remove("hidden");
    graphOverlay.classList.remove("hidden");
  } finally {
    sparqlRunBtn.disabled = false;
    sparqlRunBtn.textContent = "Execute";
  }
});

// Detect if result columns follow s/p/o triple pattern
function isTriplePattern(columns) {
  if (columns.length !== 3) return false;
  const names = columns.map((c) => c.toLowerCase());
  const tripleNames = [
    ["s", "p", "o"],
    ["subject", "predicate", "object"],
    ["sub", "pred", "obj"],
  ];
  return tripleNames.some(
    (t) => names[0].includes(t[0]) && names[1].includes(t[1]) && names[2].includes(t[2])
  );
}

// Build vis-network graph from SPARQL results
// Build a vis-network graph from SPARQL results into the given container.
async function renderGraphInto(container, columns, rows) {
  await loadFigureManifest();

  const nodesMap = new Map(); // id -> { label, type, imageUrl }
  const edges = [];

  if (isTriplePattern(columns)) {
    for (const row of rows) {
      const subjectUri = row[0];
      const predicateUri = row[1];
      const objectUri = row[2];
      const predName = localName(predicateUri);

      if (!nodesMap.has(subjectUri)) {
        const subjFigureUrl = figureUrlForValue(subjectUri);
        nodesMap.set(subjectUri, {
          label: localName(subjectUri),
          type: subjFigureUrl ? "image" : "subject",
          imageUrl: subjFigureUrl,
        });
      }
      const figureUrl = figureUrlForValue(objectUri);
      if (!nodesMap.has(objectUri)) {
        nodesMap.set(objectUri, {
          label: localName(objectUri),
          type: figureUrl ? "image" : "object",
          imageUrl: figureUrl,
        });
      }
      edges.push({ from: subjectUri, to: objectUri, label: predName });
    }
  } else {
    const propertyCols = columns.slice(1);
    for (let rowIdx = 0; rowIdx < rows.length; rowIdx++) {
      const row = rows[rowIdx];
      const subjectUri = row[0];
      const subjectId = `${subjectUri}_row${rowIdx}`;
      if (!nodesMap.has(subjectId)) {
        const subjFigureUrl = figureUrlForValue(subjectUri);
        nodesMap.set(subjectId, {
          label: localName(subjectUri),
          type: subjFigureUrl ? "image" : "subject",
          imageUrl: subjFigureUrl,
        });
      }
      for (let colIdx = 0; colIdx < propertyCols.length; colIdx++) {
        const colName = propertyCols[colIdx];
        const value = row[colIdx + 1];
        if (!value) continue;
        const valueId = `${subjectId}_${colName}_${value}`;
        const valueLabel = localName(value);
        const figureUrl = figureUrlForValue(value);
        const displayLabel =
          valueLabel.length > 60 ? valueLabel.substring(0, 57) + "…" : valueLabel;
        if (!nodesMap.has(valueId)) {
          nodesMap.set(valueId, {
            label: displayLabel,
            type: figureUrl ? "image" : "property",
            imageUrl: figureUrl,
          });
        }
        edges.push({ from: subjectId, to: valueId, label: colName });
      }
    }
  }

  const nodeColors = {
    subject: { background: "#10a37f", border: "#0d8c6d" },
    object: { background: "#4a90d9", border: "#3a7bc8" },
    property: { background: "#8b5cf6", border: "#7c3aed" },
  };

  const nodeEntries = [];
  let nodeId = 0;
  const idLookup = new Map();
  for (const [uri, info] of nodesMap) {
    nodeId++;
    idLookup.set(uri, nodeId);
    const colors = nodeColors[info.type] || nodeColors.object;
    if (info.type === "image" && info.imageUrl) {
      nodeEntries.push({
        id: nodeId, label: info.label, shape: "image", image: info.imageUrl,
        size: 50, borderWidth: 3,
        color: { border: "#10a37f", background: "#1a1a1a" },
        shapeProperties: { useBorderWithImage: true, useImageSize: false },
        font: { color: "#ececec", size: 12, vadjust: 8 },
      });
    } else {
      nodeEntries.push({
        id: nodeId, label: info.label,
        color: { background: colors.background, border: colors.border },
        font: { color: "#ececec", size: info.type === "subject" ? 15 : 13 },
        shape: info.type === "subject" ? "dot" : "box",
        size: info.type === "subject" ? 22 : 12, borderWidth: 2,
      });
    }
  }

  const edgeEntries = edges.map((e) => ({
    from: idLookup.get(e.from), to: idLookup.get(e.to), label: e.label,
    arrows: "to", color: { color: "#666", highlight: "#aaa" },
    font: { color: "#a0a0a0", size: 11, strokeWidth: 0 },
  }));

  if (typeof vis === "undefined") {
    console.error("vis-network library not loaded!");
    return;
  }
  const visData = {
    nodes: new vis.DataSet(nodeEntries),
    edges: new vis.DataSet(edgeEntries),
  };
  const options = {
    physics: {
      solver: "forceAtlas2Based",
      forceAtlas2Based: { gravitationalConstant: -40, centralGravity: 0.005, springLength: 150, springConstant: 0.04 },
      stabilization: { iterations: 150 },
    },
    interaction: { hover: true, tooltipDelay: 200, zoomView: true, dragView: true },
    layout: { improvedLayout: true },
  };
  const network = new vis.Network(container, visData, options);
  network.on("stabilizationIterationsDone", () => network.fit());
}

// Overlay path: validate, show overlay, then render into the overlay container.
async function renderGraph(columns, rows) {
  graphError.classList.add("hidden");
  if (!rows || rows.length === 0) {
    graphError.textContent = "Query returned no results.";
    graphError.classList.remove("hidden");
    graphOverlay.classList.remove("hidden");
    return;
  }
  graphOverlay.classList.remove("hidden");
  setTimeout(() => renderGraphInto(graphContainer, columns, rows), 100);
}
