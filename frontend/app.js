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
  chatTitle.textContent = "Cuộc trò chuyện mới";
  messagesContainer.innerHTML = `
    <div class="welcome">
      <h2>MMKG</h2>
      <p>Hãy hỏi bất cứ điều gì về Tin học THPT. Câu hỏi của bạn được trả lời dựa trên đồ thị tri thức.</p>
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
    titleSpan.textContent = conv.title || "Cuộc trò chuyện mới";
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
  chatTitle.textContent = conv.title || "Cuộc trò chuyện mới";
  messagesContainer.innerHTML = "";
  for (const msg of conv.messages) {
    if (msg.role === "assistant" && msg.sparql_query) {
      appendSparqlBadge(msg.sparql_query);
    }
    appendMessage(msg.role, msg.content, msg.figure_paths, msg.image);
    if (msg.role === "assistant" && msg.exercises) {
      appendExerciseOffer(msg.exercises);
    }
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
    img.alt = "ảnh đã đính kèm";
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

// ── Exercise offer (shown when an answer surfaced exercises) ──
function appendExerciseOffer(exercises) {
  if (!exercises || !exercises.length) return;
  const row = document.createElement("div");
  row.className = "message-row";

  const panel = document.createElement("div");
  panel.className = "ex-offer";
  panel.innerHTML =
    `<div class="ex-offer-q">Bạn có muốn thử làm các bài tập này không?</div>` +
    `<div class="ex-offer-actions">` +
    `<button class="ex-offer-yes">▶ Làm thử</button>` +
    `<button class="ex-offer-no">Bỏ qua</button>` +
    `</div><div class="ex-offer-mount"></div>`;

  panel.querySelector(".ex-offer-yes").addEventListener("click", () => {
    panel.querySelector(".ex-offer-actions").style.display = "none";
    panel.querySelector(".ex-offer-q").textContent = "Bài tập:";
    const mount = panel.querySelector(".ex-offer-mount");
    window.mountExerciseRunner(
      mount,
      exercises.map((e) => ({ id: e.id, title: e.title, text: e.text }))
    );
  });
  panel.querySelector(".ex-offer-no").addEventListener("click", () => row.remove());

  row.appendChild(panel);
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
    `<span>Đã thực thi truy vấn SPARQL</span>` +
    `<span class="sparql-actions">` +
    `<button class="sparql-toggle">Hiện</button>` +
    `<button class="sparql-graph-toggle">Hiện đồ thị</button>` +
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
    e.target.textContent = isHidden ? "Hiện" : "Ẩn";
  });

  let graphRendered = false;
  header.querySelector(".sparql-graph-toggle").addEventListener("click", async (e) => {
    const btn = e.target;
    if (graphRendered) {
      const isHidden = graphBox.classList.toggle("hidden");
      btn.textContent = isHidden ? "Hiện đồ thị" : "Ẩn đồ thị";
      return;
    }
    btn.disabled = true;
    btn.textContent = "Đang tải…";
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
        throw new Error(err.detail || "Truy vấn thất bại");
      }
      const data = await res.json();
      if (!data.rows || data.rows.length === 0) {
        graphBox.textContent = "Truy vấn không trả về kết quả nào.";
      } else {
        await renderGraphInto(graphBox, data);
      }
      graphRendered = true;
      btn.textContent = "Ẩn đồ thị";
    } catch (err) {
      graphBox.textContent = `Lỗi: ${err.message}`;
      graphRendered = true;
      btn.textContent = "Ẩn đồ thị";
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
      throw new Error(err.detail || "Lỗi máy chủ");
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
      exercises: data.exercises,
    });

    chatTitle.textContent = conv.title;

    // Show SPARQL query if one was executed
    if (data.sparql_query) {
      appendSparqlBadge(data.sparql_query);
    }
    appendMessage("assistant", data.reply, data.figure_paths);
    appendExerciseOffer(data.exercises);
    renderConversationList();
  } catch (err) {
    removeTypingIndicator();
    appendMessage("assistant", `⚠️ Lỗi: ${err.message}`);
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
  sparqlRunBtn.textContent = "Đang chạy…";
  graphError.classList.add("hidden");

  try {
    const res = await fetch("/api/chat/sparql", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ query }),
    });

    if (!res.ok) {
      const err = await res.json();
      throw new Error(err.detail || "Truy vấn thất bại");
    }

    const data = await res.json();
    console.log("SPARQL response:", data);
    console.log("Form:", data.query_form, "Columns:", data.columns, "Rows:", data.rows.length);
    await renderGraph(data);
  } catch (err) {
    graphError.textContent = err.message;
    graphError.classList.remove("hidden");
    graphOverlay.classList.remove("hidden");
  } finally {
    sparqlRunBtn.disabled = false;
    sparqlRunBtn.textContent = "Chạy truy vấn";
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

// ── GraphDB-style class palette ──────────────────────────────────
// GraphDB Workbench colours a node by its rdf:type. These are the classes this
// textbook ontology actually instantiates, matched to the shades the Workbench
// visual graph uses for them; any other class falls back to a hash so it still
// gets a stable, distinct pastel instead of blending into its neighbours.
const CLASS_COLORS = {
  KnowledgeConcept: "#7ec5db",
  DefinitionText: "#f4736f",
  Lesson: "#8b81c9",
  Topic: "#c9e265",
  GradeLevel: "#bda2e3",
  Textbook: "#6ede8b",
  Figure: "#f6c46a",
};

const FALLBACK_CLASS_COLORS = [
  "#8fd0c4", "#e9a1c8", "#a8c5ea", "#e6cf7e",
  "#b7d68c", "#d5a9e6", "#8dd6a8", "#eaa98c",
];

const UNTYPED_COLOR = "#cbd2d9";

// Predicates whose literal object is the node's caption rather than a fact
// about it — GraphDB shows these as the node's name, not as a separate node.
const LABEL_PREDICATES = new Set([
  "http://www.w3.org/2000/01/rdf-schema#label",
  "http://www.w3.org/2004/02/skos/core#prefLabel",
]);

function hashColor(name) {
  let hash = 0;
  for (let i = 0; i < name.length; i++) hash = (hash * 31 + name.charCodeAt(i)) >>> 0;
  return FALLBACK_CLASS_COLORS[hash % FALLBACK_CLASS_COLORS.length];
}

function colorForClass(classUri) {
  const name = localName(classUri || "");
  if (!name) return UNTYPED_COLOR;
  return CLASS_COLORS[name] || hashColor(name);
}

// rdf:type is the best thing to colour by, but a SELECT projecting only labels
// ("SELECT ?lessonLabel ?gradeLabel") has no type to offer, so those nodes fall
// back to a per-column colour assigned at build time — the nearest thing to
// colouring by class, instead of rendering the whole graph in one grey.
function nodeBackground(info) {
  if (info.classUri) return colorForClass(info.classUri);
  return info.fallbackColor || UNTYPED_COLOR;
}

// Built as an element, not an HTML string: captions and definition texts are
// arbitrary book content and must not be interpreted as markup.
function tooltipElement(lines) {
  const el = document.createElement("div");
  el.style.whiteSpace = "pre-line";
  el.style.maxWidth = "340px";
  el.textContent = lines.join("\n");
  return el;
}

// Build vis-network graph from SPARQL results
// Build a vis-network graph from SPARQL results into the given container.
// `data` is the /api/chat/sparql payload: columns, rows, term_types, node_meta.
async function renderGraphInto(container, data) {
  await loadFigureManifest();

  const columns = data.columns || [];
  const rows = data.rows || [];
  const termTypes = data.term_types || [];
  const nodeMeta = data.node_meta || {};
  const tripleMode = isTriplePattern(columns);

  const nodesMap = new Map(); // id -> { label, type, imageUrl }
  const edges = [];
  const seenEdges = new Set();
  const addEdge = (from, to, label) => {
    const key = `${from}|${to}|${label}`;
    if (seenEdges.has(key)) return;
    seenEdges.add(key);
    edges.push({ from, to, label });
  };

  if (tripleMode) {
    // GraphDB Workbench draws only resource-to-resource edges: a node's
    // rdfs:label becomes its caption and its other literals show on hover,
    // instead of every literal becoming a node of its own. Mirror that, or the
    // graph drowns in leaf nodes holding paragraphs of Vietnamese text.
    const captions = new Map(); // uri -> caption taken from the result itself
    const literals = new Map(); // uri -> [[predicateCaption, value], ...]
    const resources = new Set();

    // term_types is authoritative; the regex only covers a caller that did not
    // send it, and would otherwise mistake a literal holding a URL for a node.
    const isUri = (value, kind) =>
      kind ? kind === "uri" : /^https?:\/\//.test(value || "");

    // A predicate's own rdfs:label is why "belongsToGrade" reads as
    // "belongs to grade"; the ones the ontology never labelled keep their
    // local name, exactly as the Workbench shows them.
    const predicateCaption = (uri) =>
      (nodeMeta[uri] && nodeMeta[uri].label) || localName(uri);

    for (let i = 0; i < rows.length; i++) {
      const [subject, predicate, object] = rows[i];
      const kinds = termTypes[i] || [];
      if (!subject) continue;
      resources.add(subject);

      if (!isUri(object, kinds[2])) {
        if (LABEL_PREDICATES.has(predicate)) {
          if (!captions.has(subject)) captions.set(subject, object);
        } else {
          const list = literals.get(subject) || [];
          list.push([predicateCaption(predicate), object]);
          literals.set(subject, list);
        }
        continue;
      }

      resources.add(object);
      addEdge(subject, object, predicateCaption(predicate));
    }

    // Every resource mentioned gets a node, including one that only carried a
    // label: the Workbench shows those as isolated nodes rather than hiding
    // them, and silently dropping them would misrepresent the result.
    for (const uri of resources) {
      const meta = nodeMeta[uri] || {};
      const figureUrl = figureUrlForValue(uri);
      nodesMap.set(uri, {
        label: captions.get(uri) || meta.label || localName(uri),
        type: figureUrl ? "image" : "class",
        imageUrl: figureUrl,
        classUri: meta.type || "",
        columnKey: "",
        literals: literals.get(uri) || [],
        uri,
      });
    }
  } else {
    // Star/hierarchy mode. Subjects are keyed by VALUE (not per row) so the
    // same concept across rows merges into one node, and columns naming a
    // curriculum container (lesson/topic/grade) become a shared chain
    // subject -> lesson -> topic -> grade instead of flat leaves — the result
    // renders as one connected graph instead of per-row islands.
    const HIERARCHY = ["lesson", "topic", "grade"];
    const hierRank = (col) => HIERARCHY.findIndex((h) => col.toLowerCase().includes(h));

    // Reading term_types keeps localName() away from literals, which it would
    // otherwise chop at the last slash in a sentence. A projected URI shows its
    // stored label and carries a class to colour by; a literal is its own
    // caption and has none, so it is coloured by the column it came from.
    const isUri = (value, kind) =>
      kind ? kind === "uri" : /^https?:\/\//.test(value || "");
    const captionFor = (value, kind) => {
      if (!isUri(value, kind)) return value;
      const meta = nodeMeta[value];
      return (meta && meta.label) || localName(value);
    };
    const classFor = (value, kind) => {
      if (!isUri(value, kind)) return "";
      const meta = nodeMeta[value];
      return (meta && meta.type) || "";
    };
    // Literal columns have no rdf:type to colour by, so each column takes its
    // colour from its position in the projection: distinct by construction,
    // where hashing the column *name* collided and made ?topicLabel and
    // ?gradeLabel come out the same shade.
    const columnColor = new Map(
      columns.map((col, i) => [col, FALLBACK_CLASS_COLORS[i % FALLBACK_CLASS_COLORS.length]])
    );
    const makeNode = (value, kind, columnKey) => {
      const figureUrl = figureUrlForValue(value);
      return {
        label: captionFor(value, kind),
        type: figureUrl ? "image" : "class",
        imageUrl: figureUrl,
        classUri: classFor(value, kind),
        columnKey,
        fallbackColor: columnColor.get(columnKey),
        uri: value,
        literals: [],
      };
    };

    const propertyCols = columns.slice(1);
    for (let rowIdx = 0; rowIdx < rows.length; rowIdx++) {
      const row = rows[rowIdx];
      const kinds = termTypes[rowIdx] || [];
      const subjectValue = row[0];
      const subjectId = `subj_${subjectValue}`;
      if (!nodesMap.has(subjectId)) {
        nodesMap.set(subjectId, makeNode(subjectValue, kinds[0], columns[0]));
      }

      // Curriculum chain: child level links to the next present parent level.
      const hierCols = propertyCols
        .map((col, i) => ({ col, value: row[i + 1], kind: kinds[i + 1], rank: hierRank(col) }))
        .filter((c) => c.rank !== -1 && c.value)
        .sort((a, b) => a.rank - b.rank);
      let parentId = subjectId;
      for (const { col, value, kind, rank } of hierCols) {
        // Key each level by its ancestors too: "Chủ đề B" of Lớp 10 and the
        // identically-labeled "Chủ đề B" of Lớp 12 must stay separate nodes.
        const ancestors = hierCols
          .filter((h) => h.rank > rank)
          .map((h) => h.value)
          .join("|");
        const hierId = `hier_${col}_${ancestors}_${value}`;
        if (!nodesMap.has(hierId)) {
          nodesMap.set(hierId, makeNode(value, kind, col));
        }
        addEdge(parentId, hierId, col.replace(/_?label$/i, ""));
        parentId = hierId;
      }

      // Remaining columns stay as leaves on the subject.
      for (let colIdx = 0; colIdx < propertyCols.length; colIdx++) {
        const colName = propertyCols[colIdx];
        const value = row[colIdx + 1];
        if (!value || hierRank(colName) !== -1) continue;
        const valueId = `${subjectId}_${colName}_${value}`;
        if (!nodesMap.has(valueId)) {
          nodesMap.set(valueId, makeNode(value, kinds[colIdx + 1], colName));
        }
        addEdge(subjectId, valueId, colName);
      }
    }
  }

  // Degree drives hub sizing, and is counted the same way in both modes.
  const degreeById = new Map();
  for (const e of edges) {
    degreeById.set(e.from, (degreeById.get(e.from) || 0) + 1);
    degreeById.set(e.to, (degreeById.get(e.to) || 0) + 1);
  }

  const nodeEntries = [];
  let nodeId = 0;
  const idLookup = new Map();
  for (const [key, info] of nodesMap) {
    nodeId++;
    idLookup.set(key, nodeId);
    if (info.type === "image" && info.imageUrl) {
      nodeEntries.push({
        id: nodeId, label: info.label, shape: "image", image: info.imageUrl,
        size: 50, borderWidth: 3,
        color: { border: "#10a37f", background: "#1a1a1a" },
        shapeProperties: { useBorderWithImage: true, useImageSize: false },
        // The canvas is near-white and an image node's caption is drawn below
        // the image, on the canvas, so it needs dark text.
        font: { color: "#1f2933", size: 12, vadjust: 8 },
      });
      continue;
    }
    // A filled pastel circle with the caption wrapped inside it, coloured by
    // rdf:type — the Workbench's node style. "circle" sizes itself to the
    // caption, so widthConstraint is what wraps a long Vietnamese title
    // rather than stretching the node across the canvas.
    const background = nodeBackground(info);
    const hub = (degreeById.get(key) || 0) >= 4;
    const tooltip = [info.label];
    const typeName = localName(info.classUri || "");
    if (typeName) tooltip.push(typeName);
    else if (info.columnKey) tooltip.push(`?${info.columnKey}`);
    if (info.uri && info.uri !== info.label) tooltip.push(info.uri);
    for (const [name, value] of info.literals) {
      tooltip.push(`${name}: ${value.length > 200 ? value.slice(0, 197) + "…" : value}`);
    }
    // A "circle" grows to fit its caption, so a whole definition text would
    // either burst the node or wrap into an unreadable tower. Clip the caption
    // and keep the full value in the tooltip, as the Workbench does.
    const caption =
      info.label.length > 38 ? info.label.slice(0, 37) + "…" : info.label;
    nodeEntries.push({
      id: nodeId,
      label: caption,
      title: tooltipElement(tooltip),
      shape: "circle",
      color: {
        background,
        border: background,
        highlight: { background, border: "#52606d" },
      },
      font: { color: "#1f2933", size: hub ? 15 : caption.length > 18 ? 11 : 13 },
      borderWidth: hub ? 2 : 1,
      widthConstraint: { minimum: hub ? 54 : 38, maximum: 96 },
      margin: 10,
    });
  }

  const edgeEntries = edges.map((e) => ({
    from: idLookup.get(e.from), to: idLookup.get(e.to), label: e.label,
    arrows: { to: { scaleFactor: 0.65 } },
    color: { color: "#c5cbd3", highlight: "#7b8794" },
    // Captions sit on the line, so they get a halo in the canvas colour to stay
    // readable where an edge passes underneath them.
    font: { color: "#c2691d", size: 11, strokeWidth: 4, strokeColor: "#f8fafc" },
    smooth: { type: "continuous", roundness: 0.12 },
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
      // Long springs and overlap avoidance: every edge carries a caption
      // ("belongs to textbook"), and at tighter spacing those captions pile up
      // on each other and on the nodes.
      forceAtlas2Based: {
        gravitationalConstant: -95,
        centralGravity: 0.008,
        springLength: 240,
        springConstant: 0.05,
        avoidOverlap: 0.7,
      },
      stabilization: { iterations: 400 },
    },
    interaction: { hover: true, tooltipDelay: 200, zoomView: true, dragView: true },
    layout: { improvedLayout: true },
  };
  const network = new vis.Network(container, visData, options);
  // Freeze the layout once it settles, then frame it. Fitting while the
  // simulation is still expanding (long springs plus avoidOverlap keep pushing
  // nodes apart) leaves half the graph outside the viewport.
  network.once("stabilizationIterationsDone", () => {
    network.setOptions({ physics: false });
    network.fit({ animation: false });
  });
}

// Overlay path: validate, show overlay, then render into the overlay container.
async function renderGraph(data) {
  graphError.classList.add("hidden");
  if (!data.rows || data.rows.length === 0) {
    graphError.textContent = "Truy vấn không trả về kết quả nào.";
    graphError.classList.remove("hidden");
    graphOverlay.classList.remove("hidden");
    return;
  }
  graphOverlay.classList.remove("hidden");
  setTimeout(() => renderGraphInto(graphContainer, data), 100);
}
