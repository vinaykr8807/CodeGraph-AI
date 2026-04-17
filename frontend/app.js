const state = {
  owner: "",
  repo: "",
  repoUrl: "",
  activeView: "tree",
  selectedFilePath: "",
};

const els = {
  apiBase: document.querySelector("#apiBase"),
  repoUrl: document.querySelector("#repoUrl"),
  healthBtn: document.querySelector("#healthBtn"),
  ingestBtn: document.querySelector("#ingestBtn"),
  loadTreeBtn: document.querySelector("#loadTreeBtn"),
  loadPipelineBtn: document.querySelector("#loadPipelineBtn"),
  loadGraphBtn: document.querySelector("#loadGraphBtn"),
  treeReadmeToggle: document.querySelector("#treeReadmeToggle"),
  flowReadmeToggle: document.querySelector("#flowReadmeToggle"),
  graphReadmeToggle: document.querySelector("#graphReadmeToggle"),
  askBtn: document.querySelector("#askBtn"),
  ownerLabel: document.querySelector("#ownerLabel"),
  repoLabel: document.querySelector("#repoLabel"),
  statusText: document.querySelector("#statusText"),
  viewTitle: document.querySelector("#viewTitle"),
  healthPills: document.querySelector("#healthPills"),
  treeSvg: document.querySelector("#treeSvg"),
  treeList: document.querySelector("#treeList"),
  nodeDetail: document.querySelector("#nodeDetail"),
  pipelineDescription: document.querySelector("#pipelineDescription"),
  pipelineList: document.querySelector("#pipelineList"),
  architectureSvg: document.querySelector("#architectureSvg"),
  graphFilter: document.querySelector("#graphFilter"),
  graphSvg: document.querySelector("#graphSvg"),
  graphStats: document.querySelector("#graphStats"),
  questionInput: document.querySelector("#questionInput"),
  answerMode: document.querySelector("#answerMode"),
  filePathInput: document.querySelector("#filePathInput"),
  answerBox: document.querySelector("#answerBox"),
};

function defaultApiBase() {
  if (window.location.protocol === "file:") {
    return "http://localhost:8000";
  }
  return window.location.origin;
}

function apiBase() {
  return (els.apiBase.value.trim() || defaultApiBase()).replace(/\/$/, "");
}

function setStatus(message, isError = false) {
  els.statusText.textContent = message;
  els.statusText.style.color = isError ? "var(--red)" : "var(--muted)";
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function parseRepoUrl(value) {
  const cleaned = value.trim().replace(/\.git$/, "");
  if (!cleaned) {
    throw new Error("Enter a GitHub repository URL.");
  }
  if (cleaned.startsWith("git@github.com:")) {
    const [owner, repo] = cleaned.replace("git@github.com:", "").split("/");
    return { owner, repo };
  }
  const withProtocol = cleaned.startsWith("http") ? cleaned : `https://github.com/${cleaned}`;
  const url = new URL(withProtocol);
  const [owner, repo] = url.pathname.split("/").filter(Boolean);
  if (!owner || !repo) {
    throw new Error("Use a repository URL like https://github.com/owner/repo.");
  }
  return { owner, repo };
}

function rememberRepo() {
  const parsed = parseRepoUrl(els.repoUrl.value);
  state.owner = parsed.owner;
  state.repo = parsed.repo;
  state.repoUrl = els.repoUrl.value.trim();
  els.ownerLabel.textContent = state.owner;
  els.repoLabel.textContent = state.repo;
}

async function request(path, options = {}) {
  const response = await fetch(`${apiBase()}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  const text = await response.text();
  const data = text ? JSON.parse(text) : {};
  if (!response.ok) {
    throw new Error(data.detail || `Request failed with ${response.status}`);
  }
  return data;
}

function renderHealth(data) {
  const items = [
    { label: "Redis", good: data.redis_connected, value: data.redis_connected ? "OK" : "Off" },
    { label: "Neo4j", good: data.neo4j_connected, value: data.neo4j_connected ? "OK" : "Off" },
    { label: "GitHub", good: data.github_token_configured, value: data.github_token_configured ? "OK" : "Off" },
    { label: "Groq", good: data.groq_configured, value: data.groq_configured ? "OK" : "Off" },
    { label: "Chunks", good: Number(data.faiss_chunks ?? 0) > 0, value: String(data.faiss_chunks ?? 0) },
  ];
  els.healthPills.innerHTML = items
    .map((item) => `<span class="pill ${item.good ? "good" : "bad"}">${item.label}: ${item.value}</span>`)
    .join("");
}

async function checkHealth() {
  setStatus("Checking backend health...");
  const data = await request("/health");
  renderHealth(data);
  const neo4jNote = data.neo4j_connected ? "Neo4j connected" : `Neo4j offline: ${data.neo4j_error || "check .env credentials"}`;
  setStatus(`Backend OK. Redis ${data.redis_connected ? "connected" : "offline"}, ${neo4jNote}.`);
}

async function ingestRepo() {
  rememberRepo();
  setStatus("Analyzing repository. This can take a little while...");
  const data = await request("/ingest", {
    method: "POST",
    body: JSON.stringify({ repo_url: state.repoUrl }),
  });
  setStatus(`Processed ${data.files_processed} files, skipped ${data.files_skipped}, indexed ${data.repo_chunks ?? data.chunks_indexed ?? 0} chunks.`);
  try {
    renderHealth(await request("/health"));
  } catch {
    // Keep ingest success visible even if health refresh is unavailable.
  }
  await Promise.all([loadTree(), loadPipeline(), loadGraph()]);
}

function ensureRepo() {
  if (!state.owner || !state.repo) {
    rememberRepo();
  }
}

async function loadTree() {
  ensureRepo();
  const useReadme = els.treeReadmeToggle?.checked ? "true" : "false";
  setStatus(useReadme === "true" ? "Loading tree view with README context..." : "Loading tree view...");
  const data = await request(`/view/tree/${state.owner}/${state.repo}?use_readme=${useReadme}`);
  renderTree(data.flat_files || []);
  renderReadmeInsight(data.readme_insight, els.treeList);
  refreshHealthQuietly();
  setStatus(`Loaded ${data.total_files} files.`);
}

function renderTree(files) {
  if (!files.length) {
    els.treeSvg.innerHTML = "";
    els.treeList.className = "tree-list empty";
    els.treeList.textContent = "No files found.";
    return;
  }
  renderTreeDiagram(files);
  els.treeList.className = "tree-list";
  els.treeList.innerHTML = files
    .sort((a, b) => a.path.localeCompare(b.path))
    .map((file) => {
      const indent = Math.min(file.depth * 14, 56);
      return `
        <button class="tree-item" type="button" data-path="${escapeHtml(file.path)}" style="padding-left:${indent + 12}px">
          <span class="tree-name">
            ${escapeHtml(file.name)}
            <span class="tree-path">${escapeHtml(file.path)}</span>
          </span>
          <span class="badge">${escapeHtml(file.category || file.file_type)}</span>
        </button>
      `;
    })
    .join("");

  els.treeList.querySelectorAll(".tree-item").forEach((button) => {
    button.addEventListener("click", () => loadNode(button.dataset.path));
  });
}

function buildHierarchy(files) {
  const root = {
    id: "root",
    name: state.repo || "Repository",
    type: "folder",
    children: new Map(),
    depth: 0,
    path: "",
  };

  files.forEach((file) => {
    const parts = file.path.split("/");
    let current = root;
    parts.forEach((part, index) => {
      const isFile = index === parts.length - 1;
      const nodePath = parts.slice(0, index + 1).join("/");
      if (!current.children.has(part)) {
        current.children.set(part, {
          id: nodePath || part,
          name: part,
          type: isFile ? "file" : "folder",
          children: new Map(),
          depth: index + 1,
          path: nodePath,
          meta: isFile ? file : null,
        });
      }
      current = current.children.get(part);
    });
  });

  return root;
}

function flattenHierarchy(root) {
  const levels = [];
  const nodes = [];
  const edges = [];
  const queue = [root];

  while (queue.length) {
    const node = queue.shift();
    if (!levels[node.depth]) levels[node.depth] = [];
    levels[node.depth].push(node);
    nodes.push(node);

    const children = Array.from(node.children.values())
      .sort((a, b) => {
        if (a.type !== b.type) return a.type === "folder" ? -1 : 1;
        return a.name.localeCompare(b.name);
      })
      .slice(0, 12);

    children.forEach((child) => {
      edges.push({ source: node, target: child });
      queue.push(child);
    });
  }

  return { levels, nodes, edges };
}

function renderTreeDiagram(files) {
  const svg = els.treeSvg;
  const root = buildHierarchy(files);
  const { levels, nodes, edges } = flattenHierarchy(root);
  const levelGap = 280;
  const nodeGap = 104;
  const width = Math.max(1500, levels.length * levelGap + 220);
  const maxLevelSize = Math.max(...levels.map((level) => level.length));
  const height = Math.max(680, maxLevelSize * nodeGap + 160);
  const positions = new Map();

  svg.setAttribute("viewBox", `0 0 ${width} ${height}`);
  svg.innerHTML = "";

  levels.forEach((level, depth) => {
    const totalHeight = (level.length - 1) * nodeGap;
    const startY = height / 2 - totalHeight / 2;
    level.forEach((node, index) => {
      positions.set(node.id, {
        x: 110 + depth * levelGap,
        y: startY + index * nodeGap,
      });
    });
  });

  edges.forEach((edge) => {
    const source = positions.get(edge.source.id);
    const target = positions.get(edge.target.id);
    if (!source || !target) return;
    const path = document.createElementNS("http://www.w3.org/2000/svg", "path");
    const midX = (source.x + target.x) / 2;
    path.setAttribute("d", `M ${source.x + 82} ${source.y} C ${midX} ${source.y}, ${midX} ${target.y}, ${target.x - 82} ${target.y}`);
    path.setAttribute("class", "tree-edge");
    svg.appendChild(path);
  });

  nodes.forEach((node) => {
    const pos = positions.get(node.id);
    if (!pos) return;
    const group = document.createElementNS("http://www.w3.org/2000/svg", "g");
    group.setAttribute("class", `tree-node ${node.type}`);
    group.setAttribute("transform", `translate(${pos.x}, ${pos.y})`);

    if (node.type === "file") {
      group.addEventListener("click", () => loadNode(node.path));
    }

    const rect = document.createElementNS("http://www.w3.org/2000/svg", "rect");
    rect.setAttribute("x", "-82");
    rect.setAttribute("y", "-30");
    rect.setAttribute("width", "164");
    rect.setAttribute("height", "60");
    rect.setAttribute("rx", "8");

    const text = document.createElementNS("http://www.w3.org/2000/svg", "text");
    text.setAttribute("text-anchor", "middle");
    text.setAttribute("y", "5");
    text.textContent = node.name.length > 22 ? `${node.name.slice(0, 19)}...` : node.name;

    const label = document.createElementNS("http://www.w3.org/2000/svg", "title");
    label.textContent = node.path || node.name;

    group.append(rect, text, label);
    svg.appendChild(group);
  });
}

async function loadNode(path) {
  ensureRepo();
  state.selectedFilePath = path;
  setStatus(`Loading ${path}...`);
  const data = await request(`/view/node/${state.owner}/${state.repo}?file_path=${encodeURIComponent(path)}`);
  renderNode(data);
  setStatus(`Selected ${path}.`);
}

function renderNode(data) {
  const analysis = data.analysis || {};
  const outgoing = data.outgoing_relations || [];
  const incoming = data.incoming_relations || [];
  const lines = data.annotated_lines || [];

  els.nodeDetail.className = "detail";
  els.nodeDetail.innerHTML = `
    <div class="detail-grid">
      <section class="detail-block">
        <div class="detail-title-row">
          <h4>${escapeHtml(data.name)}</h4>
          <button id="explainCodeBtn" type="button" class="primary">Explain Code</button>
        </div>
        <p>${escapeHtml(analysis.role || "No summary available.")}</p>
        <span class="badge">${escapeHtml(analysis.category || data.file_type)}</span>
        <span class="badge">${escapeHtml(analysis.pipeline_stage || "unknown")}</span>
        <span class="badge">${escapeHtml(analysis.complexity || "low")}</span>
      </section>
      <section class="detail-block">
        <h4>Responsibilities</h4>
        <ul>${(analysis.key_responsibilities || []).map((item) => `<li>${escapeHtml(item)}</li>`).join("") || "<li>No responsibilities listed.</li>"}</ul>
      </section>
      <section class="detail-block">
        <h4>Relations</h4>
        <p>${outgoing.length} outgoing, ${incoming.length} incoming.</p>
        <p>${escapeHtml(outgoing.slice(0, 6).map((r) => `${r.relation} ${r.target}`).join(" | ") || "No outgoing relations.")}</p>
      </section>
      <section class="detail-block">
        <h4>Code</h4>
        <div class="code-list">
          ${lines.slice(0, 140).map((line) => `
            <div class="code-line">
              <span class="line-no">${line.line_number}</span>
              <code>${line.annotation ? `<mark>${escapeHtml(line.annotation.type)}</mark> ` : ""}${escapeHtml(line.code)}</code>
            </div>
          `).join("")}
        </div>
      </section>
      <section class="detail-block">
        <h4>Student Walkthrough</h4>
        <div id="explanationBox" class="explanation-box empty">Click Explain Code to get line-by-line guidance for this file.</div>
      </section>
    </div>
  `;

  document.querySelector("#explainCodeBtn")?.addEventListener("click", () => {
    loadFileExplanation(data.path).catch((err) => setStatus(err.message, true));
  });
}

async function loadFileExplanation(path) {
  ensureRepo();
  const box = document.querySelector("#explanationBox");
  if (!box) return;
  box.className = "explanation-box";
  box.textContent = "Generating student walkthrough...";
  setStatus(`Explaining ${path} with Groq...`);
  const data = await request(`/explain/file/${state.owner}/${state.repo}?file_path=${encodeURIComponent(path)}&max_lines=80`);
  renderFileExplanation(data);
  setStatus(`Walkthrough ready from ${data.source || "backend"}.`);
}

function renderFileExplanation(data) {
  const box = document.querySelector("#explanationBox");
  if (!box) return;
  const mainLogic = data.main_logic || [];
  const notes = data.line_notes || [];
  box.className = "explanation-box";
  box.innerHTML = `
    <div class="walkthrough-summary">
      <p>${escapeHtml(data.summary || "No summary available.")}</p>
      <span class="badge">${escapeHtml(data.source || "backend")}</span>
      ${data.fallback_reason ? `<span class="badge error-badge">Fallback: ${escapeHtml(data.fallback_reason.slice(0, 90))}</span>` : ""}
      <span class="badge">${notes.length} explained lines</span>
      <span class="badge">${data.limit || 0}/${data.total_lines || 0} lines scanned</span>
    </div>
    <div class="main-logic-list">
      <h5>Main Logic To Read First</h5>
      ${mainLogic.map((item) => `
        <button class="logic-card" type="button" data-line="${item.line_start}">
          <strong>${escapeHtml(item.name)}</strong>
          <span>Lines ${escapeHtml(item.line_start)}-${escapeHtml(item.line_end || item.line_start)} | ${escapeHtml(item.kind)}</span>
          <em>${escapeHtml(item.why_it_matters)}</em>
        </button>
      `).join("") || "<p>No main blocks detected.</p>"}
    </div>
    <div class="line-explanation-list">
      <h5>Line By Line Explanation</h5>
      ${notes.map((note) => `
        <article class="line-explanation" id="explain-line-${escapeHtml(note.line)}">
          <div class="line-explanation-code">
            <span>${escapeHtml(note.line)}</span>
            <code>${escapeHtml(note.code)}</code>
          </div>
          <p>${escapeHtml(note.explanation)}</p>
        </article>
      `).join("")}
    </div>
  `;

  box.querySelectorAll(".logic-card").forEach((card) => {
    card.addEventListener("click", () => {
      const target = box.querySelector(`#explain-line-${card.dataset.line}`);
      target?.scrollIntoView({ behavior: "smooth", block: "center" });
    });
  });
}

async function loadPipeline() {
  ensureRepo();
  const useReadme = els.flowReadmeToggle?.checked ? "true" : "false";
  setStatus(useReadme === "true" ? "Generating architecture flow with README context..." : "Generating architecture flow with Groq...");
  const data = await request(`/view/architecture-diagram/${state.owner}/${state.repo}?use_readme=${useReadme}`);
  els.pipelineDescription.textContent = data.summary || "";
  renderArchitectureDiagram(data);
  renderPipelineLegend(data);
  renderReadmeInsight(data.readme_insight, els.pipelineList);
  refreshHealthQuietly();
  setStatus(`Architecture flow ready from ${data.source || "backend"}.`);
}

function renderPipelineLegend(data) {
  const nodes = data.nodes || [];
  if (!nodes.length) {
    els.pipelineList.className = "pipeline-list empty";
    els.pipelineList.textContent = "No architecture nodes found.";
    return;
  }
  els.pipelineList.className = "pipeline-list";
  els.pipelineList.innerHTML = nodes.map((node) => {
    const items = uniqueItems(node.items || []).filter(Boolean);
    const visibleItems = items.slice(0, 4);
    const extraCount = Math.max(items.length - visibleItems.length, 0);
    return `
    <section class="stage">
      <div class="stage-head">
        <h4>${escapeHtml(node.label)}</h4>
        <span class="badge">${escapeHtml(node.type || node.group || "component")}</span>
      </div>
      <p>${escapeHtml(node.description || node.group || "Architecture component")}</p>
      <div class="stage-chips">
        ${visibleItems.map((item) => `<span title="${escapeHtml(item)}">${escapeHtml(truncateMiddle(item, 28))}</span>`).join("") || "<span>component</span>"}
        ${extraCount ? `<em>+${extraCount} more</em>` : ""}
      </div>
    </section>
  `;
  }).join("");
}

function uniqueItems(items) {
  const seen = new Set();
  const result = [];
  items.forEach((item) => {
    const value = String(item || "").trim();
    const key = value.toLowerCase();
    if (!value || seen.has(key)) return;
    seen.add(key);
    result.push(value);
  });
  return result;
}

function architectureColor(node) {
  const group = String(node.group || "").toLowerCase();
  if (group.includes("input") || node.type === "input") return "#dbeafe";
  if (group.includes("api") || node.type === "api") return "#cffafe";
  if (group.includes("core") || node.type === "processor" || node.type === "model") return "#dcfce7";
  if (group.includes("data") || node.type === "database") return "#fee2e2";
  if (group.includes("output") || node.type === "output") return "#fef3c7";
  return "#f3e8ff";
}

function edgeColor(kind) {
  const colors = {
    input: "#d97706",
    data_flow: "#2563eb",
    query: "#7c3aed",
    response: "#be185d",
    storage: "#dc2626",
    feedback: "#059669",
  };
  return colors[kind] || "#64748b";
}

function layoutArchitecture(nodes) {
  const groupOrder = [
    "User/Input",
    "Interface/API",
    "Core Intelligence",
    "Data/Storage",
    "Output/Reporting",
    "Utilities",
  ];
  const columns = groupOrder.map((group) => ({
    group,
    nodes: nodes.filter((node) => node.group === group),
  }));
  nodes.forEach((node) => {
    if (!groupOrder.includes(node.group)) {
      let fallback = columns.find((column) => column.group === "Utilities");
      fallback.nodes.push(node);
    }
  });
  return columns.filter((column) => column.nodes.length);
}

function renderArchitectureDiagram(data) {
  const svg = els.architectureSvg;
  const nodes = (data.nodes || []).slice(0, 12);
  const edges = data.edges || [];
  svg.innerHTML = "";

  if (!nodes.length) {
    svg.setAttribute("viewBox", "0 0 1000 420");
    svg.innerHTML = `<text x="30" y="54" fill="#65676b">No architecture diagram available.</text>`;
    return;
  }

  const columns = layoutArchitecture(nodes);
  const colGap = 300;
  const rowGap = 150;
  const boxW = 220;
  const boxH = 86;
  const width = Math.max(1100, columns.length * colGap + 140);
  const height = Math.max(620, Math.max(...columns.map((col) => col.nodes.length)) * rowGap + 180);
  const positions = new Map();

  svg.setAttribute("viewBox", `0 0 ${width} ${height}`);

  const defs = document.createElementNS("http://www.w3.org/2000/svg", "defs");
  const marker = document.createElementNS("http://www.w3.org/2000/svg", "marker");
  marker.setAttribute("id", "arrowHead");
  marker.setAttribute("markerWidth", "12");
  marker.setAttribute("markerHeight", "12");
  marker.setAttribute("refX", "10");
  marker.setAttribute("refY", "6");
  marker.setAttribute("orient", "auto");
  const arrowPath = document.createElementNS("http://www.w3.org/2000/svg", "path");
  arrowPath.setAttribute("d", "M 0 0 L 12 6 L 0 12 z");
  arrowPath.setAttribute("fill", "#64748b");
  marker.appendChild(arrowPath);
  defs.appendChild(marker);
  svg.appendChild(defs);

  columns.forEach((column, colIndex) => {
    const x = 90 + colIndex * colGap;
    const totalHeight = (column.nodes.length - 1) * rowGap;
    const startY = height / 2 - totalHeight / 2;

    const groupLabel = document.createElementNS("http://www.w3.org/2000/svg", "text");
    groupLabel.setAttribute("x", x + boxW / 2);
    groupLabel.setAttribute("y", 48);
    groupLabel.setAttribute("text-anchor", "middle");
    groupLabel.setAttribute("class", "architecture-group-label");
    groupLabel.textContent = column.group;
    svg.appendChild(groupLabel);

    column.nodes.forEach((node, rowIndex) => {
      positions.set(node.id, {
        x,
        y: startY + rowIndex * rowGap,
      });
    });
  });

  const labelBudget = new Set();
  edges.slice(0, 14).forEach((edge) => {
    const source = positions.get(edge.source);
    const target = positions.get(edge.target);
    if (!source || !target) return;
    const sx = source.x + boxW;
    const sy = source.y + boxH / 2;
    const tx = target.x;
    const ty = target.y + boxH / 2;
    const midX = (sx + tx) / 2;
    const color = edgeColor(edge.kind);

    const path = document.createElementNS("http://www.w3.org/2000/svg", "path");
    path.setAttribute("d", `M ${sx} ${sy} C ${midX} ${sy}, ${midX} ${ty}, ${tx} ${ty}`);
    path.setAttribute("class", "architecture-edge");
    path.setAttribute("stroke", color);
    path.setAttribute("marker-end", "url(#arrowHead)");
    svg.appendChild(path);

    const labelText = edge.label || edge.kind || "";
    if (!labelText || labelBudget.has(labelText) || labelBudget.size >= 5) return;
    labelBudget.add(labelText);
    const label = document.createElementNS("http://www.w3.org/2000/svg", "text");
    label.setAttribute("x", midX);
    label.setAttribute("y", (sy + ty) / 2 - 8);
    label.setAttribute("text-anchor", "middle");
    label.setAttribute("class", "architecture-edge-label");
    label.textContent = truncateMiddle(labelText, 18);
    svg.appendChild(label);
  });

  nodes.forEach((node) => {
    const pos = positions.get(node.id);
    if (!pos) return;
    const group = document.createElementNS("http://www.w3.org/2000/svg", "g");
    group.setAttribute("class", "architecture-node");
    group.setAttribute("transform", `translate(${pos.x}, ${pos.y})`);

    const rect = document.createElementNS("http://www.w3.org/2000/svg", "rect");
    rect.setAttribute("width", boxW);
    rect.setAttribute("height", boxH);
    rect.setAttribute("rx", "8");
    rect.setAttribute("fill", architectureColor(node));

    const title = document.createElementNS("http://www.w3.org/2000/svg", "text");
    title.setAttribute("x", boxW / 2);
    title.setAttribute("y", 28);
    title.setAttribute("text-anchor", "middle");
    title.setAttribute("class", "architecture-node-title");
    title.textContent = truncateMiddle(node.label, 22);

    const desc = document.createElementNS("http://www.w3.org/2000/svg", "text");
    desc.setAttribute("x", boxW / 2);
    desc.setAttribute("y", 54);
    desc.setAttribute("text-anchor", "middle");
    desc.setAttribute("class", "architecture-node-desc");
    const description = node.description || node.type || "";
    desc.textContent = truncateMiddle(description, 32);

    const badge = document.createElementNS("http://www.w3.org/2000/svg", "text");
    badge.setAttribute("x", boxW / 2);
    badge.setAttribute("y", 74);
    badge.setAttribute("text-anchor", "middle");
    badge.setAttribute("class", "architecture-node-badge");
    badge.textContent = node.type || "component";

    group.append(rect, title, desc, badge);
    svg.appendChild(group);
  });
}

async function loadGraph() {
  ensureRepo();
  const useReadme = els.graphReadmeToggle?.checked ? "true" : "false";
  setStatus(useReadme === "true" ? "Generating presentation graph with README context..." : "Generating presentation graph...");
  const filter = els.graphFilter.value;
  if (filter === "presentation") {
    const data = await request(`/view/presentation-graph/${state.owner}/${state.repo}?use_readme=${useReadme}`);
    renderPresentationGraph(data);
    els.graphStats.innerHTML = `
      <span>${escapeHtml(data.nodes?.length || 0)} components, ${escapeHtml(data.edges?.length || 0)} relationships. Source: ${escapeHtml(data.source || "backend")}.</span>
      ${renderReadmeInsightMarkup(data.readme_insight)}
    `;
    refreshHealthQuietly();
    setStatus("Presentation graph ready.");
    return;
  }
  const data = await request(`/view/graph/${state.owner}/${state.repo}?filter_type=${encodeURIComponent(filter)}&use_readme=${useReadme}`);
  renderGraph(data.nodes || [], data.edges || []);
  els.graphStats.innerHTML = `
    <span>${escapeHtml(data.node_count)} raw nodes, ${escapeHtml(data.edge_count)} raw edges.</span>
    ${renderReadmeInsightMarkup(data.readme_insight)}
  `;
  refreshHealthQuietly();
  setStatus("Graph loaded.");
}

async function refreshHealthQuietly() {
  try {
    renderHealth(await request("/health"));
  } catch {
    // Visual views should remain usable if health refresh fails.
  }
}

function renderReadmeInsightMarkup(insight) {
  if (!insight || !insight.available) return "";
  return `
    <article class="readme-insight">
      <div class="readme-insight-head">
        <strong>${escapeHtml(insight.title || "README Context")}</strong>
        ${(insight.key_terms || []).length ? `<span>${escapeHtml(insight.key_terms.slice(0, 5).join(" | "))}</span>` : ""}
      </div>
      <p>${escapeHtml(insight.summary || "")}</p>
    </article>
  `;
}

function renderReadmeInsight(insight, container) {
  if (!container || !insight || !insight.available) return;
  container.insertAdjacentHTML("afterbegin", renderReadmeInsightMarkup(insight));
}

function presentationGraphColor(node) {
  const type = String(node.type || "").toLowerCase();
  const layer = String(node.layer || "").toLowerCase();
  if (type.includes("database") || type.includes("dataset") || layer.includes("data")) return "#fed7aa";
  if (type.includes("api") || layer.includes("api")) return "#bae6fd";
  if (type.includes("ui") || layer.includes("frontend")) return "#fecaca";
  if (type.includes("service") || type.includes("module") || layer.includes("core")) return "#e9d5ff";
  if (type.includes("output") || layer.includes("output")) return "#99f6e4";
  return "#dcfce7";
}

function presentationEdgeColor(kind) {
  const colors = {
    imports: "#7c3aed",
    calls: "#2563eb",
    data: "#ea580c",
    storage: "#dc2626",
    api: "#0891b2",
    output: "#0f766e",
    dependency: "#64748b",
  };
  return colors[kind] || "#64748b";
}

function renderWrappedSvgText(parent, text, x, y, maxChars, className) {
  const words = String(text || "").split(/\s+/);
  const lines = [];
  let line = "";
  words.forEach((word) => {
    const next = line ? `${line} ${word}` : word;
    if (next.length > maxChars && line) {
      lines.push(line);
      line = word;
    } else {
      line = next;
    }
  });
  if (line) lines.push(line);

  lines.slice(0, 2).forEach((textLine, index) => {
    const tspan = document.createElementNS("http://www.w3.org/2000/svg", "text");
    tspan.setAttribute("x", x);
    tspan.setAttribute("y", y + index * 18);
    tspan.setAttribute("text-anchor", "middle");
    tspan.setAttribute("class", className);
    tspan.textContent = textLine;
    parent.appendChild(tspan);
  });
}

function renderPresentationGraph(data) {
  const svg = els.graphSvg;
  const nodes = (data.nodes || []).slice(0, 10);
  const edges = data.edges || [];
  svg.innerHTML = "";

  if (!nodes.length) {
    svg.setAttribute("viewBox", "0 0 1100 560");
    svg.innerHTML = `<text x="30" y="54" fill="#65676b">No presentation graph available.</text>`;
    return;
  }

  const boxW = 260;
  const boxH = 212;
  const marginX = 64;
  const mainY = 126;
  const dataY = 440;
  const dataGapY = 246;
  const isDataNode = (node) => {
    const type = String(node.type || "").toLowerCase();
    const layer = String(node.layer || "").toLowerCase();
    return type.includes("dataset") || type.includes("database") || layer.includes("data asset");
  };
  const mainNodes = nodes
    .filter((node) => !isDataNode(node))
    .sort((a, b) => (a.level ?? 0) - (b.level ?? 0));
  const dataNodes = nodes
    .filter(isDataNode)
    .sort((a, b) => (a.level ?? 0) - (b.level ?? 0));
  const mainCount = Math.max(mainNodes.length, 1);
  const width = Math.max(1320, marginX * 2 + mainCount * 288);
  const dataRows = Math.ceil(dataNodes.length / Math.max(Math.floor((width - marginX * 2) / 288), 1));
  const height = Math.max(720, dataNodes.length ? dataY + dataRows * dataGapY + 80 : 420);
  const positions = new Map();

  svg.setAttribute("viewBox", `0 0 ${width} ${height}`);

  const defs = document.createElementNS("http://www.w3.org/2000/svg", "defs");
  const marker = document.createElementNS("http://www.w3.org/2000/svg", "marker");
  marker.setAttribute("id", "graphArrowHead");
  marker.setAttribute("markerWidth", "12");
  marker.setAttribute("markerHeight", "12");
  marker.setAttribute("refX", "10");
  marker.setAttribute("refY", "6");
  marker.setAttribute("orient", "auto");
  const arrowPath = document.createElementNS("http://www.w3.org/2000/svg", "path");
  arrowPath.setAttribute("d", "M 0 0 L 12 6 L 0 12 z");
  arrowPath.setAttribute("fill", "#64748b");
  marker.appendChild(arrowPath);
  defs.appendChild(marker);
  svg.appendChild(defs);

  const mainBand = document.createElementNS("http://www.w3.org/2000/svg", "rect");
  mainBand.setAttribute("x", 24);
  mainBand.setAttribute("y", 48);
  mainBand.setAttribute("width", width - 48);
  mainBand.setAttribute("height", 260);
  mainBand.setAttribute("rx", "8");
  mainBand.setAttribute("class", "presentation-layer-box");
  svg.appendChild(mainBand);

  const mainTitle = document.createElementNS("http://www.w3.org/2000/svg", "text");
  mainTitle.setAttribute("x", 42);
  mainTitle.setAttribute("y", 82);
  mainTitle.setAttribute("class", "presentation-layer-title");
  mainTitle.textContent = "Main Architecture";
  svg.appendChild(mainTitle);

  if (dataNodes.length) {
    const dataBand = document.createElementNS("http://www.w3.org/2000/svg", "rect");
    dataBand.setAttribute("x", 24);
    dataBand.setAttribute("y", 358);
    dataBand.setAttribute("width", width - 48);
    dataBand.setAttribute("height", height - 396);
    dataBand.setAttribute("rx", "8");
    dataBand.setAttribute("class", "presentation-layer-box");
    svg.appendChild(dataBand);

    const dataTitle = document.createElementNS("http://www.w3.org/2000/svg", "text");
    dataTitle.setAttribute("x", 42);
    dataTitle.setAttribute("y", 392);
    dataTitle.setAttribute("class", "presentation-layer-title");
    dataTitle.textContent = "Data & Supporting Assets";
    svg.appendChild(dataTitle);
  }

  mainNodes.forEach((node, index) => {
    const gap = (width - marginX * 2 - boxW) / Math.max(mainNodes.length - 1, 1);
    positions.set(node.id, {
      x: marginX + index * gap,
      y: mainY,
      row: "main",
      index,
    });
  });

  const dataColumns = Math.max(Math.floor((width - marginX * 2) / 288), 1);
  dataNodes.forEach((node, index) => {
    const col = index % dataColumns;
    const row = Math.floor(index / dataColumns);
    const available = width - marginX * 2 - boxW;
    const gap = available / Math.max(Math.min(dataNodes.length, dataColumns) - 1, 1);
    positions.set(node.id, {
      x: marginX + col * gap,
      y: dataY + row * dataGapY,
      row: "data",
      index,
    });
  });

  const visibleEdges = edges
    .filter((edge) => positions.has(edge.source) && positions.has(edge.target))
    .slice(0, 16);
  const labelBudget = new Set();
  visibleEdges.forEach((edge) => {
    const source = positions.get(edge.source);
    const target = positions.get(edge.target);
    if (!source || !target) return;
    const sourceIsLeft = source.x <= target.x;
    const sx = sourceIsLeft ? source.x + boxW : source.x;
    const tx = sourceIsLeft ? target.x : target.x + boxW;
    const sy = source.row === "data" ? source.y : source.y + boxH / 2;
    const ty = target.row === "data" ? target.y : target.y + boxH / 2;
    const midX = (sx + tx) / 2;
    const bend = source.row === target.row ? 0 : -54;
    const color = presentationEdgeColor(edge.kind);

    const path = document.createElementNS("http://www.w3.org/2000/svg", "path");
    path.setAttribute("d", `M ${sx} ${sy} C ${midX} ${sy + bend}, ${midX} ${ty + bend}, ${tx} ${ty}`);
    path.setAttribute("class", "presentation-edge");
    path.setAttribute("stroke", color);
    path.setAttribute("marker-end", "url(#graphArrowHead)");
    svg.appendChild(path);

    const labelKey = edge.label || edge.kind || "";
    if (labelKey && !labelBudget.has(labelKey)) {
      labelBudget.add(labelKey);
      const tooltip = document.createElementNS("http://www.w3.org/2000/svg", "title");
      tooltip.textContent = labelKey;
      path.appendChild(tooltip);
    }
  });

  nodes.forEach((node) => {
    const pos = positions.get(node.id);
    if (!pos) return;
    const group = document.createElementNS("http://www.w3.org/2000/svg", "g");
    group.setAttribute("class", "presentation-node");
    group.setAttribute("transform", `translate(${pos.x}, ${pos.y})`);

    const tooltip = document.createElementNS("http://www.w3.org/2000/svg", "title");
    tooltip.textContent = `${node.label || node.id}\n${node.description || ""}\n${(node.items || []).join(", ")}`;

    const rect = document.createElementNS("http://www.w3.org/2000/svg", "rect");
    rect.setAttribute("width", boxW);
    rect.setAttribute("height", boxH);
    rect.setAttribute("rx", "8");
    rect.setAttribute("fill", presentationGraphColor(node));

    const title = document.createElementNS("http://www.w3.org/2000/svg", "text");
    title.setAttribute("x", boxW / 2);
    title.setAttribute("y", 32);
    title.setAttribute("text-anchor", "middle");
    title.setAttribute("class", "presentation-node-title");
    title.textContent = truncateMiddle(node.label, 24);

    group.append(tooltip, rect, title);
    renderWrappedSvgText(group, node.description || node.type || "", boxW / 2, 58, 30, "presentation-node-desc");

    const itemStartY = 104;
    (node.items || []).slice(0, 4).forEach((item, index) => {
      const itemLabel = compactGraphItemLabel(item);
      const itemBox = document.createElementNS("http://www.w3.org/2000/svg", "rect");
      itemBox.setAttribute("x", "18");
      itemBox.setAttribute("y", itemStartY + index * 24 - 16);
      itemBox.setAttribute("width", boxW - 36);
      itemBox.setAttribute("height", "20");
      itemBox.setAttribute("rx", "5");
      itemBox.setAttribute("class", "presentation-item-box");
      const itemText = document.createElementNS("http://www.w3.org/2000/svg", "text");
      itemText.setAttribute("x", boxW / 2);
      itemText.setAttribute("y", itemStartY + index * 24);
      itemText.setAttribute("text-anchor", "middle");
      itemText.setAttribute("class", "presentation-item-text");
      itemText.textContent = itemLabel;
      group.append(itemBox, itemText);
    });

    svg.appendChild(group);
  });
}

function compactGraphItemLabel(value) {
  const text = String(value || "");
  const parts = text.split("/").filter(Boolean);
  const label = parts.length >= 2 ? parts.slice(-2).join("/") : text;
  return truncateMiddle(label, 34);
}

function renderGraph(nodes, edges) {
  const svg = els.graphSvg;
  if (els.graphFilter.value === "files_only") {
    renderFilesOnlyGraph(nodes);
    return;
  }
  if (els.graphFilter.value === "full") {
    renderAggregatedRawGraph(nodes, edges);
    return;
  }
  const width = Math.max(svg.clientWidth || 1200, 1200);
  const height = 760;
  svg.setAttribute("viewBox", `0 0 ${width} ${height}`);
  svg.innerHTML = "";

  if (!nodes.length) {
    svg.innerHTML = `<text x="24" y="40" fill="#65676b">No graph data yet.</text>`;
    return;
  }

  const degree = new Map();
  edges.forEach((edge) => {
    degree.set(edge.source, (degree.get(edge.source) || 0) + 1);
    degree.set(edge.target, (degree.get(edge.target) || 0) + 1);
  });

  const typeRank = {
    file: 0,
    dataset: 1,
    class: 2,
    function: 3,
    library: 4,
    tag: 5,
  };
  const visibleNodes = [...nodes]
    .sort((a, b) => {
      const rankA = typeRank[a.node_type] ?? 9;
      const rankB = typeRank[b.node_type] ?? 9;
      if (rankA !== rankB) return rankA - rankB;
      return (degree.get(b.id) || 0) - (degree.get(a.id) || 0);
    })
    .slice(0, 72);
  const visibleIds = new Set(visibleNodes.map((node) => node.id));
  const visibleEdges = edges
    .filter((edge) => visibleIds.has(edge.source) && visibleIds.has(edge.target))
    .slice(0, 140);

  const lanes = [
    {
      label: "Files & Data",
      types: new Set(["file", "dataset"]),
      nodes: [],
    },
    {
      label: "Code Symbols",
      types: new Set(["class", "function"]),
      nodes: [],
    },
    {
      label: "External & Tags",
      types: new Set(["library", "tag"]),
      nodes: [],
    },
    {
      label: "Other",
      types: new Set(),
      nodes: [],
    },
  ];
  visibleNodes.forEach((node) => {
    const lane = lanes.find((item) => item.types.has(node.node_type)) || lanes[lanes.length - 1];
    lane.nodes.push(node);
  });
  const activeLanes = lanes.filter((lane) => lane.nodes.length);
  const positions = new Map();

  const laneGap = width / Math.max(activeLanes.length, 1);
  activeLanes.forEach((lane, laneIndex) => {
    const x = laneGap * laneIndex + laneGap / 2;
    const top = 92;
    const bottom = height - 84;
    const rowGap = (bottom - top) / Math.max(lane.nodes.length - 1, 1);

    const title = document.createElementNS("http://www.w3.org/2000/svg", "text");
    title.setAttribute("x", x);
    title.setAttribute("y", 42);
    title.setAttribute("text-anchor", "middle");
    title.setAttribute("class", "graph-lane-title");
    title.textContent = `${lane.label} (${lane.nodes.length})`;
    svg.appendChild(title);

    const laneLine = document.createElementNS("http://www.w3.org/2000/svg", "line");
    laneLine.setAttribute("x1", x);
    laneLine.setAttribute("y1", 64);
    laneLine.setAttribute("x2", x);
    laneLine.setAttribute("y2", height - 46);
    laneLine.setAttribute("class", "graph-lane-line");
    svg.appendChild(laneLine);

    lane.nodes.forEach((node, index) => {
      const offset = lane.nodes.length > 12 ? ((index % 2) ? 18 : -18) : 0;
      positions.set(node.id, {
        x: x + offset,
        y: top + index * rowGap,
        laneIndex,
        lanePosition: index,
        laneSize: lane.nodes.length,
      });
    });
  });

  visibleEdges.forEach((edge) => {
    const source = positions.get(edge.source);
    const target = positions.get(edge.target);
    if (!source || !target) return;
    const path = document.createElementNS("http://www.w3.org/2000/svg", "path");
    const midX = (source.x + target.x) / 2;
    path.setAttribute("d", `M ${source.x} ${source.y} C ${midX} ${source.y}, ${midX} ${target.y}, ${target.x} ${target.y}`);
    path.setAttribute("class", "graph-edge");
    svg.appendChild(path);
  });

  visibleNodes.forEach((node) => {
    positions.set(node.id, {
      ...positions.get(node.id),
    });
  });

  visibleNodes.forEach((node) => {
    const pos = positions.get(node.id);
    if (!pos) return;
    const group = document.createElementNS("http://www.w3.org/2000/svg", "g");
    group.setAttribute("class", "graph-node");
    group.addEventListener("click", () => {
      if (node.node_type === "file") {
        showView("tree");
        loadNode(node.id);
      }
    });

    const circle = document.createElementNS("http://www.w3.org/2000/svg", "circle");
    circle.setAttribute("cx", pos.x);
    circle.setAttribute("cy", pos.y);
    circle.setAttribute("r", node.node_type === "file" ? 16 : 11);
    circle.setAttribute("fill", node.color || "#2563eb");
    circle.setAttribute("stroke", "#fff");
    circle.setAttribute("stroke-width", "2");

    const tooltip = document.createElementNS("http://www.w3.org/2000/svg", "title");
    tooltip.textContent = `${node.label || node.id}\n${node.node_type || "node"}\n${node.role || ""}`;

    const label = document.createElementNS("http://www.w3.org/2000/svg", "text");
    label.setAttribute("x", pos.x + 20);
    label.setAttribute("y", pos.y + 4);
    label.setAttribute("class", "graph-label");
    const labelLimit = node.node_type === "file" || node.node_type === "dataset" ? 14 : 7;
    const shouldLabel = pos.laneSize <= labelLimit || pos.lanePosition < labelLimit;
    label.textContent = shouldLabel ? truncateMiddle(node.label || node.id, 30) : "";

    group.append(circle, tooltip, label);
    svg.appendChild(group);
  });

  if (nodes.length > visibleNodes.length || edges.length > visibleEdges.length) {
    const note = document.createElementNS("http://www.w3.org/2000/svg", "text");
    note.setAttribute("x", 24);
    note.setAttribute("y", height - 24);
    note.setAttribute("class", "graph-note");
    note.textContent = `Showing ${visibleNodes.length}/${nodes.length} nodes and ${visibleEdges.length}/${edges.length} relationships. Use Files Only or Presentation for a cleaner summary.`;
    svg.appendChild(note);
  }
}

function renderFilesOnlyGraph(nodes) {
  const svg = els.graphSvg;
  const files = nodes
    .filter((node) => node.node_type === "file" || node.node_type === "dataset")
    .slice(0, 80);
  const groups = new Map();
  files.forEach((node) => {
    const folder = node.id.includes("/") ? node.id.split("/").slice(0, -1).join("/") : "root";
    const key = folder || node.category || "root";
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key).push(node);
  });

  const groupEntries = Array.from(groups.entries()).slice(0, 12);
  const cardW = 250;
  const cardH = 178;
  const gapX = 28;
  const gapY = 30;
  const cols = Math.max(3, Math.floor((svg.clientWidth || 1200) / (cardW + gapX)));
  const width = Math.max(1180, cols * (cardW + gapX) + 80);
  const rows = Math.ceil(groupEntries.length / cols);
  const height = Math.max(620, rows * (cardH + gapY) + 120);
  svg.setAttribute("viewBox", `0 0 ${width} ${height}`);
  svg.innerHTML = "";

  const title = document.createElementNS("http://www.w3.org/2000/svg", "text");
  title.setAttribute("x", 42);
  title.setAttribute("y", 48);
  title.setAttribute("class", "graph-lane-title");
  title.textContent = `Files grouped by folder (${files.length})`;
  svg.appendChild(title);

  groupEntries.forEach(([folder, groupFiles], index) => {
    const col = index % cols;
    const row = Math.floor(index / cols);
    const x = 42 + col * (cardW + gapX);
    const y = 82 + row * (cardH + gapY);
    const group = document.createElementNS("http://www.w3.org/2000/svg", "g");
    group.setAttribute("class", "file-group-card");
    group.setAttribute("transform", `translate(${x}, ${y})`);

    const rect = document.createElementNS("http://www.w3.org/2000/svg", "rect");
    rect.setAttribute("width", cardW);
    rect.setAttribute("height", cardH);
    rect.setAttribute("rx", "8");

    const heading = document.createElementNS("http://www.w3.org/2000/svg", "text");
    heading.setAttribute("x", 14);
    heading.setAttribute("y", 28);
    heading.setAttribute("class", "file-group-title");
    heading.textContent = truncateMiddle(folder, 32);

    group.append(rect, heading);
    groupFiles.slice(0, 5).forEach((file, fileIndex) => {
      const pill = document.createElementNS("http://www.w3.org/2000/svg", "rect");
      pill.setAttribute("x", "14");
      pill.setAttribute("y", 48 + fileIndex * 22);
      pill.setAttribute("width", cardW - 28);
      pill.setAttribute("height", "17");
      pill.setAttribute("rx", "5");
      pill.setAttribute("class", "file-group-pill");

      const text = document.createElementNS("http://www.w3.org/2000/svg", "text");
      text.setAttribute("x", 24);
      text.setAttribute("y", 61 + fileIndex * 22);
      text.setAttribute("class", "file-group-text");
      text.textContent = truncateMiddle(file.label || file.id, 30);

      const tooltip = document.createElementNS("http://www.w3.org/2000/svg", "title");
      tooltip.textContent = `${file.id}\n${file.role || ""}`;
      pill.appendChild(tooltip);
      group.append(pill, text);
    });

    if (groupFiles.length > 5) {
      const more = document.createElementNS("http://www.w3.org/2000/svg", "text");
      more.setAttribute("x", 14);
      more.setAttribute("y", 166);
      more.setAttribute("class", "file-group-more");
      more.textContent = `+${groupFiles.length - 5} more`;
      group.appendChild(more);
    }

    svg.appendChild(group);
  });
}

function truncateMiddle(value, maxLength) {
  const text = String(value || "");
  if (text.length <= maxLength) return text;
  const keep = Math.floor((maxLength - 3) / 2);
  return `${text.slice(0, keep)}...${text.slice(-keep)}`;
}

function renderAggregatedRawGraph(nodes, edges) {
  const svg = els.graphSvg;
  const width = Math.max(svg.clientWidth || 1200, 1200);
  const height = 720;
  svg.setAttribute("viewBox", `0 0 ${width} ${height}`);
  svg.innerHTML = "";

  const files = nodes.filter((node) => node.node_type === "file" || node.node_type === "dataset").slice(0, 18);
  const fileIds = new Set(files.map((node) => node.id));
  const symbolCounts = new Map();
  const externalCounts = new Map();

  edges.forEach((edge) => {
    if (!fileIds.has(edge.source)) return;
    if (edge.target_type === "function" || edge.target_type === "class") {
      const current = symbolCounts.get(edge.source) || { function: 0, class: 0 };
      current[edge.target_type] = (current[edge.target_type] || 0) + 1;
      symbolCounts.set(edge.source, current);
    } else if (edge.target_type === "library" || edge.target_type === "tag") {
      externalCounts.set(edge.source, (externalCounts.get(edge.source) || 0) + 1);
    }
  });

  const positions = new Map();
  const leftX = 210;
  const midX = width / 2;
  const rightX = width - 250;
  const top = 100;
  const rowGap = Math.min(64, (height - 160) / Math.max(files.length - 1, 1));

  [
    { x: leftX, title: `Files & Data (${files.length})` },
    { x: midX, title: "Symbols grouped by file" },
    { x: rightX, title: "External/Tags grouped" },
  ].forEach((lane) => {
    const title = document.createElementNS("http://www.w3.org/2000/svg", "text");
    title.setAttribute("x", lane.x);
    title.setAttribute("y", 44);
    title.setAttribute("text-anchor", "middle");
    title.setAttribute("class", "graph-lane-title");
    title.textContent = lane.title;
    svg.appendChild(title);
  });

  const aggregateNodes = [];
  files.forEach((file, index) => {
    const y = top + index * rowGap;
    positions.set(file.id, { x: leftX, y });
    const symbols = symbolCounts.get(file.id);
    if (symbols && (symbols.function || symbols.class)) {
      const id = `symbols:${file.id}`;
      aggregateNodes.push({
        id,
        label: `${(symbols.function || 0) + (symbols.class || 0)} symbols`,
        sublabel: `${symbols.function || 0} fn, ${symbols.class || 0} class`,
        color: "#f59e0b",
      });
      positions.set(id, { x: midX, y });
    }
    const external = externalCounts.get(file.id) || 0;
    if (external) {
      const id = `external:${file.id}`;
      aggregateNodes.push({
        id,
        label: `${external} external/tag`,
        sublabel: "imports or tags",
        color: "#64748b",
      });
      positions.set(id, { x: rightX, y });
    }
  });

  aggregateNodes.forEach((node) => {
    const sourceId = node.id.split(":").slice(1).join(":");
    const source = positions.get(sourceId);
    const target = positions.get(node.id);
    if (!source || !target) return;
    const path = document.createElementNS("http://www.w3.org/2000/svg", "path");
    const mx = (source.x + target.x) / 2;
    path.setAttribute("d", `M ${source.x + 18} ${source.y} C ${mx} ${source.y}, ${mx} ${target.y}, ${target.x - 18} ${target.y}`);
    path.setAttribute("class", "graph-edge");
    svg.appendChild(path);
  });

  files.forEach((file) => drawRawGraphNode(svg, positions.get(file.id), file.label || file.id, file.file_type || file.node_type, file.color || "#2563eb"));
  aggregateNodes.forEach((node) => drawRawGraphNode(svg, positions.get(node.id), node.label, node.sublabel, node.color));

  const note = document.createElementNS("http://www.w3.org/2000/svg", "text");
  note.setAttribute("x", 24);
  note.setAttribute("y", height - 24);
  note.setAttribute("class", "graph-note");
  note.textContent = `Raw Full grouped ${nodes.length} nodes into readable file-level summaries. Use Raw With Functions for individual symbols.`;
  svg.appendChild(note);
}

function drawRawGraphNode(svg, pos, label, sublabel, color) {
  if (!pos) return;
  const group = document.createElementNS("http://www.w3.org/2000/svg", "g");
  group.setAttribute("class", "graph-node");

  const circle = document.createElementNS("http://www.w3.org/2000/svg", "circle");
  circle.setAttribute("cx", pos.x);
  circle.setAttribute("cy", pos.y);
  circle.setAttribute("r", "15");
  circle.setAttribute("fill", color || "#2563eb");
  circle.setAttribute("stroke", "#fff");
  circle.setAttribute("stroke-width", "2");

  const title = document.createElementNS("http://www.w3.org/2000/svg", "title");
  title.textContent = `${label}\n${sublabel || ""}`;

  const text = document.createElementNS("http://www.w3.org/2000/svg", "text");
  text.setAttribute("x", pos.x + 22);
  text.setAttribute("y", pos.y - 2);
  text.setAttribute("class", "graph-label");
  text.textContent = truncateMiddle(label, 28);

  const small = document.createElementNS("http://www.w3.org/2000/svg", "text");
  small.setAttribute("x", pos.x + 22);
  small.setAttribute("y", pos.y + 14);
  small.setAttribute("class", "graph-sublabel");
  small.textContent = truncateMiddle(sublabel || "", 24);

  group.append(circle, title, text, small);
  svg.appendChild(group);
}

async function askQuestion() {
  ensureRepo();
  const mode = els.answerMode.value;
  const rawQuestion = els.questionInput.value.trim();
  if (!rawQuestion) {
    setStatus("Ask a question first.", true);
    return;
  }
  setStatus("Reading README, code map, tree, flow, and graph context...");
  els.answerBox.className = "answer";
  els.answerBox.textContent = "Thinking...";
  const payload = {
    repo_url: state.repoUrl,
    question: rawQuestion,
    answer_mode: mode,
    file_path: els.filePathInput.value.trim() || null,
  };
  const data = await request("/query", {
    method: "POST",
    body: JSON.stringify(payload),
  });
  renderAskAnswer(data);
  setStatus("Answer ready.");
}

function renderAskAnswer(data) {
  const answer = data.structured_answer || {
    headline: "Answer",
    short_answer: data.answer || "",
    key_points: [],
    important_files: [],
    logic_flow: [],
    code_pointers: [],
    next_steps: [],
  };
  const treeItems = answer.tree_view || [];
  const flowItems = (answer.flow_view || []).length ? answer.flow_view : (answer.logic_flow || []);
  const graph = answer.graph_view || {};
  const graphNodes = graph.nodes || [];
  const graphEdges = graph.edges || [];
  els.answerBox.className = "answer answer-card";
  els.answerBox.innerHTML = `
    <section class="answer-hero">
      <span class="badge">${escapeHtml(answer.answer_type || "answer")}</span>
      <h4>${escapeHtml(answer.headline || "Codebase Answer")}</h4>
      <p>${escapeHtml(answer.short_answer || data.answer || "")}</p>
    </section>

    <section class="answer-section">
      <h5>Key Points</h5>
      <ul>${(answer.key_points || []).map((point) => `<li>${escapeHtml(point)}</li>`).join("") || "<li>No key points returned.</li>"}</ul>
    </section>

    ${treeItems.length ? `
      <section class="answer-section">
        <h5>Tree View</h5>
        <div class="answer-tree">
          ${treeItems.map((item) => `
            <article class="answer-tree-item">
              <strong>${escapeHtml(item.path || item.folder || "root")}</strong>
              <span>${escapeHtml(item.role || item.reason || "")}</span>
              ${(item.files || []).length ? `<em>${escapeHtml(item.files.join(", "))}</em>` : ""}
            </article>
          `).join("")}
        </div>
      </section>
    ` : ""}

    ${flowItems.length ? `
      <section class="answer-section">
        <h5>Flow View</h5>
        <div class="flow-steps">
          ${flowItems.map((step, index) => `
            <article class="flow-step">
              <span>${escapeHtml(step.step || index + 1)}</span>
              <div>
                <strong>${escapeHtml(step.title || step.stage || "Step")}</strong>
                <em>${escapeHtml(Array.isArray(step.files) ? step.files.join(" -> ") : (step.file || step.files || ""))}</em>
                <p>${escapeHtml(step.explanation || step.action || "")}</p>
              </div>
            </article>
          `).join("")}
        </div>
      </section>
    ` : ""}

    ${graphNodes.length || graphEdges.length ? `
      <section class="answer-section">
        <h5>Graph View</h5>
        <div class="answer-graph-grid">
          <div>
            <strong>Nodes</strong>
            ${(graphNodes || []).map((node) => `
              <article class="file-chip">
                <strong>${escapeHtml(node.label || node.id || node.file)}</strong>
                <span>${escapeHtml(node.type || node.kind || "")}</span>
                <p>${escapeHtml(node.reason || node.role || "")}</p>
              </article>
            `).join("") || "<p>No nodes returned.</p>"}
          </div>
          <div>
            <strong>Edges</strong>
            ${(graphEdges || []).map((edge) => `
              <article class="file-chip">
                <strong>${escapeHtml(edge.source || edge.from)} -> ${escapeHtml(edge.target || edge.to)}</strong>
                <span>${escapeHtml(edge.relation || edge.label || "")}</span>
                <p>${escapeHtml(edge.reason || "")}</p>
              </article>
            `).join("") || "<p>No edges returned.</p>"}
          </div>
        </div>
      </section>
    ` : ""}

    <section class="answer-grid">
      <div class="answer-section">
        <h5>Important Files</h5>
        ${(answer.important_files || []).map((file) => `
          <article class="file-chip">
            <strong>${escapeHtml(file.path)}</strong>
            <span>${escapeHtml(file.stage || "")}</span>
            <p>${escapeHtml(file.why || "")}</p>
            ${(file.symbols || []).length ? `<em>${escapeHtml(file.symbols.join(", "))}</em>` : ""}
          </article>
        `).join("") || "<p>No files returned.</p>"}
      </div>

      <div class="answer-section">
        <h5>Code Pointers</h5>
        ${(answer.code_pointers || []).map((pointer) => `
          <article class="file-chip">
            <strong>${escapeHtml(pointer.symbol || pointer.file)}</strong>
            <span>${escapeHtml(pointer.file || "")}</span>
            <p>${escapeHtml(pointer.reason || "")}</p>
          </article>
        `).join("") || "<p>No code pointers returned.</p>"}
      </div>
    </section>

    <section class="answer-section">
      <h5>Next Steps</h5>
      <ul>${(answer.next_steps || []).map((step) => `<li>${escapeHtml(step)}</li>`).join("") || "<li>Ask a more specific follow-up question.</li>"}</ul>
    </section>

    <section class="answer-sources">
      <h5>Retrieved Sources</h5>
      ${(data.sources || []).map((source) => `<span class="badge">${escapeHtml(source)}</span>`).join("") || "<span class=\"badge\">none</span>"}
    </section>
  `;
}

function showView(view) {
  state.activeView = view;
  document.querySelectorAll(".tab").forEach((tab) => {
    tab.classList.toggle("active", tab.dataset.view === view);
  });
  document.querySelectorAll(".view").forEach((panel) => {
    panel.classList.remove("active");
  });
  document.querySelector(`#${view}View`).classList.add("active");
  const titles = {
    tree: "Hierarchical Tree",
    pipeline: "Architecture Flow",
    graph: "Dependency Graph",
    query: "Ask The Codebase",
  };
  els.viewTitle.textContent = titles[view];
}

function bindEvents() {
  els.healthBtn.addEventListener("click", () => checkHealth().catch((err) => setStatus(err.message, true)));
  els.ingestBtn.addEventListener("click", () => ingestRepo().catch((err) => setStatus(err.message, true)));
  els.loadTreeBtn.addEventListener("click", () => loadTree().catch((err) => setStatus(err.message, true)));
  els.loadPipelineBtn.addEventListener("click", () => loadPipeline().catch((err) => setStatus(err.message, true)));
  els.loadGraphBtn.addEventListener("click", () => loadGraph().catch((err) => setStatus(err.message, true)));
  els.askBtn.addEventListener("click", () => askQuestion().catch((err) => {
    els.answerBox.textContent = err.message;
    setStatus(err.message, true);
  }));
  els.answerMode.addEventListener("change", () => {
    if (!els.questionInput.value.trim()) return;
    const label = els.answerMode.options[els.answerMode.selectedIndex]?.textContent || "mode";
    els.answerBox.className = "answer empty";
    els.answerBox.textContent = `Mode changed to ${label}. Click Ask to generate a fresh ${label} answer.`;
    setStatus(`Mode changed to ${label}. Ask again to refresh the answer.`);
  });
  document.querySelectorAll(".tab").forEach((tab) => {
    tab.addEventListener("click", () => showView(tab.dataset.view));
  });
  els.repoUrl.addEventListener("change", () => {
    try {
      rememberRepo();
    } catch (err) {
      setStatus(err.message, true);
    }
  });
}

els.apiBase.value = defaultApiBase();
bindEvents();
checkHealth().catch(() => setStatus("Start the backend, then check health."));
