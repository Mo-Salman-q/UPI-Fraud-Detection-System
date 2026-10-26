/**
 * Sentinel AI Fraud Operations Console — Application Logic
 * Vanilla JavaScript SPA with Chart.js Integration
 * Connects to FastAPI backend via relative URLs
 */

// ── Configuration & State ───────────────────────────────────────────────────

const STATE = {
  token: localStorage.getItem("sentinel_admin_token") || null,
  user: JSON.parse(localStorage.getItem("sentinel_admin_user") || "null"),
  currentTab: "alerts",
  refreshInterval: null,
  countdownSecs: 4,
  autoRefreshEnabled: true,
  charts: {},
  graphData: null,
};

// ── DOM References ──────────────────────────────────────────────────────────

const loginOverlay = document.getElementById("login-overlay");
const currentUserLabel = document.getElementById("current-user-upi");
const currentRoleBadge = document.getElementById("current-role-badge");
const countdownEl = document.getElementById("refresh-countdown");

// ── API Helper (Relative URLs) ──────────────────────────────────────────────

async function adminApi(endpoint, method = "GET", body = null) {
  const headers = { "Content-Type": "application/json" };
  if (STATE.token) {
    headers["Authorization"] = `Bearer ${STATE.token}`;
  }

  const options = { method, headers };
  if (body) {
    options.body = JSON.stringify(body);
  }

  try {
    const res = await fetch(endpoint, options);
    if (res.status === 401) {
      if (endpoint === "/auth/login") {
        throw new Error("Invalid UPI ID or password.");
      }
      showLoginModal();
      throw new Error("Session expired. Please log in again.");
    }
    if (res.status === 403) {
      throw new Error("Access forbidden. This action requires Administrator privileges.");
    }
    if (res.status === 204) {
      return null;
    }
    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
      throw new Error(data.detail || `Request failed with status ${res.status}`);
    }
    return data;
  } catch (err) {
    console.error(`API Error on ${endpoint}:`, err);
    throw err;
  }
}

// ── Authentication & Session ────────────────────────────────────────────────

function showLoginModal() {
  if (loginOverlay) loginOverlay.classList.add("active");
}

function hideLoginModal() {
  if (loginOverlay) loginOverlay.classList.remove("active");
}

async function performLogin(upi_id, password) {
  try {
    const data = await adminApi("/auth/login", "POST", { upi_id, password });
    if (data.role !== "admin" && data.role !== "analyst") {
      alert("Access denied: You must be an analyst or admin to access this console.");
      return;
    }

    STATE.token = data.access_token;
    STATE.user = { upi_id, role: data.role };

    localStorage.setItem("sentinel_admin_token", STATE.token);
    localStorage.setItem("sentinel_admin_user", JSON.stringify(STATE.user));

    updateUserUI();
    hideLoginModal();
    loadCurrentTab();
    startAutoRefresh();
  } catch (err) {
    alert("Authentication failed: " + err.message);
  }
}

function performLogout() {
  STATE.token = null;
  STATE.user = null;
  localStorage.removeItem("sentinel_admin_token");
  localStorage.removeItem("sentinel_admin_user");
  stopAutoRefresh();
  showLoginModal();
}

function updateUserUI() {
  if (!STATE.user) return;
  if (currentUserLabel) currentUserLabel.textContent = STATE.user.upi_id;
  if (currentRoleBadge) {
    currentRoleBadge.textContent = STATE.user.role.toUpperCase();
    currentRoleBadge.className = `role-tag ${STATE.user.role}`;
  }

  // Hide admin-only elements if user is analyst
  const isAdmin = STATE.user.role === "admin";
  document.querySelectorAll(".admin-only").forEach((el) => {
    el.style.display = isAdmin ? "" : "none";
  });
}

// ── Navigation & Tabs ───────────────────────────────────────────────────────

function switchTab(tabName) {
  STATE.currentTab = tabName;

  // Update navigation styles
  document.querySelectorAll(".nav-item").forEach((item) => {
    item.classList.toggle("active", item.getAttribute("data-tab") === tabName);
  });

  // Switch view panes
  document.querySelectorAll(".admin-view").forEach((view) => {
    view.classList.toggle("active", view.id === `view-${tabName}`);
  });

  // Update page title
  const titleEl = document.getElementById("page-title");
  const titles = {
    alerts: "Real-Time Alert Queue",
    txns: "Transaction Search & Forensics",
    graph: "Account Network Graph",
    config: "Decision Thresholds & Feature Toggles",
    rules: "Business Override Rules",
    metrics: "Operations & Fraud Analytics",
    drift: "Model & Data Drift Monitoring",
    audit: "Immutable Audit Log",
  };
  if (titleEl && titles[tabName]) {
    titleEl.textContent = titles[tabName];
  }

  loadCurrentTab();
}

function loadCurrentTab() {
  if (!STATE.token) return;

  switch (STATE.currentTab) {
    case "alerts":
      loadAlertQueue();
      break;
    case "txns":
      searchTransactions();
      break;
    case "graph":
      loadAccountGraph();
      break;
    case "config":
      loadConfig();
      break;
    case "rules":
      loadRules();
      break;
    case "metrics":
      loadMetrics();
      break;
    case "drift":
      loadDriftFrame();
      break;
    case "audit":
      loadAuditLog();
      break;
  }
}

// ── Auto-Refresh (Every 4 Seconds) ──────────────────────────────────────────

function startAutoRefresh() {
  stopAutoRefresh();
  STATE.countdownSecs = 4;

  STATE.refreshInterval = setInterval(() => {
    STATE.countdownSecs -= 1;
    if (countdownEl) {
      countdownEl.textContent = `${STATE.countdownSecs}s`;
    }

    if (STATE.countdownSecs <= 0) {
      STATE.countdownSecs = 4;
      if (STATE.autoRefreshEnabled && STATE.token) {
        // Auto-refresh the alert queue and update open badge
        loadAlertQueue(false);
      }
    }
  }, 1000);
}

function stopAutoRefresh() {
  if (STATE.refreshInterval) {
    clearInterval(STATE.refreshInterval);
    STATE.refreshInterval = null;
  }
}

// ── 1. Alert Queue ──────────────────────────────────────────────────────────

async function loadAlertQueue(showLoading = true) {
  const tbody = document.getElementById("alerts-table-body");
  const badgeEl = document.getElementById("open-alerts-badge");
  const filterSelect = document.getElementById("alert-status-filter");
  const statusFilter = filterSelect ? filterSelect.value : "";

  if (showLoading && tbody && tbody.children.length === 0) {
    tbody.innerHTML = `<tr><td colspan="7" style="text-align:center; padding:32px; color:var(--text-muted);">Loading alert queue...</td></tr>`;
  }

  try {
    const query = statusFilter ? `?status=${statusFilter}` : "";
    const alerts = await adminApi(`/admin/alerts${query}`);

    // Update live open badge count
    const openCount = alerts.filter((a) => a.status === "OPEN").length;
    if (badgeEl) {
      badgeEl.textContent = openCount;
      badgeEl.style.display = openCount > 0 ? "inline-block" : "none";
    }

    if (!tbody) return;

    if (alerts.length === 0) {
      tbody.innerHTML = `<tr><td colspan="7" style="text-align:center; padding:32px; color:var(--text-muted);">No alerts match the filter.</td></tr>`;
      return;
    }

    tbody.innerHTML = alerts
      .map((a) => {
        const score = a.risk_score !== null ? a.risk_score.toFixed(2) : "N/A";
        const scoreClass = a.risk_score >= 0.7 ? "score-high" : a.risk_score >= 0.3 ? "score-med" : "score-low";
        const statusBadgeClass = `badge-${a.status.toLowerCase()}`;
        const reasons = a.reasons && a.reasons.length > 0 ? a.reasons : ["Threshold exceedance"];
        const reasonsHtml = reasons.map((r) => `<span class="reason-tag">${r}</span>`).join("");
        const dateStr = a.created_at ? new Date(a.created_at).toLocaleTimeString() : "Recent";
        const amountStr = a.amount ? `₹${parseFloat(a.amount).toLocaleString("en-IN")}` : "—";

        const actionButtons =
          a.status === "OPEN"
            ? `
            <div class="btn-action-group">
              <button class="btn-resolve btn-approve" onclick="resolveAlert(${a.id}, 'APPROVED')" title="Approve & Release Funds">✓ Approve</button>
              <button class="btn-resolve btn-fraud" onclick="resolveAlert(${a.id}, 'CONFIRMED_FRAUD')" title="Confirm Fraud & Block Payee">✕ Fraud</button>
              <button class="btn-resolve btn-escalate" onclick="resolveAlert(${a.id}, 'ESCALATED')" title="Escalate to Senior Ops">⬆ Escalate</button>
            </div>
          `
            : `<span style="font-size:0.75rem; color:var(--text-muted);">Resolved (${a.status})</span>`;

        return `
          <tr>
            <td><strong>#${a.id}</strong></td>
            <td>
              <div style="font-weight:600;">${a.masked_sender_upi || "—"}</div>
              <div style="font-size:0.75rem; color:var(--text-muted);">→ ${a.masked_receiver_upi || "—"}</div>
            </td>
            <td><strong>${amountStr}</strong></td>
            <td><span class="risk-score-pill ${scoreClass}">${score}</span></td>
            <td><div class="reasons-tags-container">${reasonsHtml}</div></td>
            <td><span class="badge ${statusBadgeClass}">${a.status}</span></td>
            <td>${actionButtons}</td>
          </tr>
        `;
      })
      .join("");
  } catch (err) {
    if (tbody) {
      tbody.innerHTML = `<tr><td colspan="7" style="text-align:center; padding:20px; color:var(--rose);">Error loading alerts: ${err.message}</td></tr>`;
    }
  }
}

async function resolveAlert(alertId, action) {
  const notes = prompt(`Enter resolution notes for Alert #${alertId} (${action}):`, `Analyst verified via Sentinel Ops`);
  if (notes === null) return; // user cancelled

  try {
    const res = await adminApi(`/admin/alerts/${alertId}/resolve`, "POST", { action, notes });
    alert(`Alert #${alertId} updated: ${res.status}`);
    loadAlertQueue(false);
  } catch (err) {
    alert("Resolution error: " + err.message);
  }
}

// ── 2. Transaction Search ───────────────────────────────────────────────────

async function searchTransactions() {
  const tbody = document.getElementById("txns-table-body");
  const upiQuery = document.getElementById("search-txn-upi")?.value.trim() || "";
  const statusFilter = document.getElementById("filter-txn-status")?.value || "";

  if (tbody) {
    tbody.innerHTML = `<tr><td colspan="8" style="text-align:center; padding:24px; color:var(--text-muted);">Searching ledger...</td></tr>`;
  }

  try {
    const params = new URLSearchParams();
    if (upiQuery) params.append("upi_id", upiQuery);
    if (statusFilter) params.append("status", statusFilter);

    const txns = await adminApi(`/admin/transactions?${params.toString()}`);
    if (!tbody) return;

    if (txns.length === 0) {
      tbody.innerHTML = `<tr><td colspan="8" style="text-align:center; padding:24px; color:var(--text-muted);">No transactions match the criteria.</td></tr>`;
      return;
    }

    tbody.innerHTML = txns
      .map((t) => {
        const score = t.risk_score !== null ? t.risk_score.toFixed(2) : "—";
        const scoreClass = t.risk_score >= 0.7 ? "score-high" : t.risk_score >= 0.3 ? "score-med" : "score-low";
        const dateStr = t.created_at ? new Date(t.created_at).toLocaleString() : "—";

        return `
          <tr>
            <td><strong>#${t.id}</strong></td>
            <td>${dateStr}</td>
            <td>${t.sender_upi || "—"}</td>
            <td>${t.receiver_upi || "—"}</td>
            <td><strong>₹${parseFloat(t.amount).toLocaleString("en-IN")}</strong></td>
            <td><span class="risk-score-pill ${scoreClass}">${score}</span></td>
            <td><strong>${t.decision || "—"}</strong></td>
            <td><span class="badge badge-${t.status.toLowerCase()}">${t.status}</span></td>
          </tr>
        `;
      })
      .join("");
  } catch (err) {
    if (tbody) {
      tbody.innerHTML = `<tr><td colspan="8" style="text-align:center; padding:20px; color:var(--rose);">Error: ${err.message}</td></tr>`;
    }
  }
}

// ── 3. Account Network Graph ────────────────────────────────────────────────

async function loadAccountGraph() {
  const upiInput = document.getElementById("graph-target-upi");
  const targetUpi = (upiInput ? upiInput.value.trim() : "") || "customer1@sentinel";
  const hops = document.getElementById("graph-hops-select")?.value || "2";

  const canvas = document.getElementById("graph-canvas");
  if (!canvas) return;
  const ctx = canvas.getContext("2d");

  // Set canvas resolution for crisp DPI
  canvas.width = canvas.parentElement.clientWidth * window.devicePixelRatio;
  canvas.height = canvas.parentElement.clientHeight * window.devicePixelRatio;
  ctx.scale(window.devicePixelRatio, window.devicePixelRatio);

  const width = canvas.parentElement.clientWidth;
  const height = canvas.parentElement.clientHeight;

  ctx.clearRect(0, 0, width, height);
  ctx.fillStyle = "#94a3b8";
  ctx.font = "14px Plus Jakarta Sans";
  ctx.textAlign = "center";
  ctx.fillText(`Loading network graph around ${targetUpi}...`, width / 2, height / 2);

  try {
    const res = await adminApi(`/admin/graph/${targetUpi}?hops=${hops}`);
    STATE.graphData = res;
    renderGraph(res, targetUpi, width, height);
  } catch (err) {
    ctx.clearRect(0, 0, width, height);
    ctx.fillStyle = "#f43f5e";
    ctx.fillText(`Graph query failed: ${err.message}`, width / 2, height / 2);
  }
}

function renderGraph(data, targetUpi, width, height) {
  const canvas = document.getElementById("graph-canvas");
  if (!canvas) return;
  const ctx = canvas.getContext("2d");

  ctx.clearRect(0, 0, width, height);

  if (!data.nodes || data.nodes.length === 0) {
    ctx.fillStyle = "#94a3b8";
    ctx.font = "14px Plus Jakarta Sans";
    ctx.textAlign = "center";
    ctx.fillText(`No transaction edges found around ${targetUpi}`, width / 2, height / 2);
    return;
  }

  // Layout node positions
  const centerX = width / 2;
  const centerY = height / 2;
  const nodePositions = {};

  // Center node
  nodePositions[targetUpi] = { x: centerX, y: centerY, isCenter: true };

  // Other nodes around circle
  const otherNodes = data.nodes.filter((n) => n.id !== targetUpi);
  const radius = Math.min(width, height) * 0.35;
  const step = (2 * Math.PI) / Math.max(otherNodes.length, 1);

  otherNodes.forEach((node, i) => {
    const angle = i * step;
    nodePositions[node.id] = {
      x: centerX + radius * Math.cos(angle),
      y: centerY + radius * Math.sin(angle),
      isCenter: false,
    };
  });

  // Draw Edges
  data.edges.forEach((edge) => {
    const p1 = nodePositions[edge.source];
    const p2 = nodePositions[edge.target];
    if (!p1 || !p2) return;

    ctx.beginPath();
    ctx.moveTo(p1.x, p1.y);
    ctx.lineTo(p2.x, p2.y);

    const isFraud = edge.decision === "HOLD";
    ctx.strokeStyle = isFraud ? "#f43f5e" : edge.decision === "STEP_UP" ? "#f59e0b" : "#10b981";
    ctx.lineWidth = isFraud ? 2.5 : 1.5;
    ctx.stroke();

    // Draw amount label on edge midpoint
    const midX = (p1.x + p2.x) / 2;
    const midY = (p1.y + p2.y) / 2;
    ctx.fillStyle = "#f8fafc";
    ctx.font = "11px JetBrains Mono";
    ctx.fillText(`₹${Math.round(edge.amount || 0)}`, midX, midY - 4);
  });

  // Draw Nodes
  data.nodes.forEach((node) => {
    const pos = nodePositions[node.id];
    if (!pos) return;

    // Node Circle
    ctx.beginPath();
    ctx.arc(pos.x, pos.y, pos.isCenter ? 24 : 16, 0, 2 * Math.PI);
    ctx.fillStyle = pos.isCenter ? "#6366f1" : "#1e293b";
    ctx.fill();
    ctx.strokeStyle = pos.isCenter ? "#a5b4fc" : "#475569";
    ctx.lineWidth = pos.isCenter ? 3 : 1.5;
    ctx.stroke();

    // Node Label
    ctx.fillStyle = "#f8fafc";
    ctx.font = pos.isCenter ? "bold 12px Plus Jakarta Sans" : "11px Plus Jakarta Sans";
    ctx.textAlign = "center";
    ctx.fillText(node.label || node.id, pos.x, pos.y + (pos.isCenter ? 36 : 28));
  });
}

// ── 4. Config (Thresholds & Toggles) ─────────────────────────────────────────

async function loadConfig() {
  try {
    const config = await adminApi("/admin/config");

    // Thresholds
    const holdInput = document.getElementById("conf-t-hold");
    const stepInput = document.getElementById("conf-t-step");
    const holdVal = document.getElementById("val-t-hold");
    const stepVal = document.getElementById("val-t-step");

    if (holdInput && config.thresholds?.T_hold !== undefined) {
      holdInput.value = config.thresholds.T_hold;
      if (holdVal) holdVal.textContent = config.thresholds.T_hold.toFixed(2);
    }
    if (stepInput && config.thresholds?.T_step !== undefined) {
      stepInput.value = config.thresholds.T_step;
      if (stepVal) stepVal.textContent = config.thresholds.T_step.toFixed(2);
    }

    // Feature Toggles
    const netToggle = document.getElementById("toggle-network-features");
    const devToggle = document.getElementById("toggle-device-features");

    if (netToggle && config.feature_toggles) {
      netToggle.checked = !!config.feature_toggles.use_network_features;
    }
    if (devToggle && config.feature_toggles) {
      devToggle.checked = !!config.feature_toggles.use_device_features;
    }
  } catch (err) {
    alert("Error loading configuration: " + err.message);
  }
}

async function saveConfig() {
  const hold = parseFloat(document.getElementById("conf-t-hold")?.value || "0.70");
  const step = parseFloat(document.getElementById("conf-t-step")?.value || "0.30");
  const use_network_features = document.getElementById("toggle-network-features")?.checked ?? true;
  const use_device_features = document.getElementById("toggle-device-features")?.checked ?? true;

  if (step >= hold) {
    alert("Invalid Thresholds: T_step (medium risk) must be strictly less than T_hold (high risk).");
    return;
  }

  const payload = {
    thresholds: { T_hold: hold, T_step: step },
    feature_toggles: { use_network_features, use_device_features },
  };

  try {
    await adminApi("/admin/config", "PUT", payload);
    alert("Configuration updated and audit entry recorded!");
    loadConfig();
  } catch (err) {
    alert("Failed to save config: " + err.message);
  }
}

// ── 5. Business Rules ───────────────────────────────────────────────────────

async function loadRules() {
  const tbody = document.getElementById("rules-table-body");
  if (tbody) {
    tbody.innerHTML = `<tr><td colspan="6" style="text-align:center; padding:24px; color:var(--text-muted);">Loading business rules...</td></tr>`;
  }

  try {
    const rules = await adminApi("/admin/rules");
    if (!tbody) return;

    if (rules.length === 0) {
      tbody.innerHTML = `<tr><td colspan="6" style="text-align:center; padding:24px; color:var(--text-muted);">No rules defined.</td></tr>`;
      return;
    }

    tbody.innerHTML = rules
      .map((r) => {
        const condStr = JSON.stringify(r.condition_json);
        const actionBadge = `<span class="badge badge-${r.action === "ALLOW" ? "approved" : r.action === "HOLD" ? "fraud" : "open"}">${r.action}</span>`;
        const toggleChecked = r.enabled ? "checked" : "";

        return `
          <tr>
            <td><strong>#${r.id}</strong></td>
            <td><strong>${r.name}</strong></td>
            <td><code style="font-family:var(--font-mono); font-size:0.75rem; color:#a5b4fc;">${condStr}</code></td>
            <td>${actionBadge}</td>
            <td>
              <input type="checkbox" ${toggleChecked} onchange="toggleRuleEnabled(${r.id}, this.checked)" title="Toggle Enabled">
            </td>
            <td>
              <button class="btn-resolve btn-fraud" onclick="deleteRule(${r.id})">Delete</button>
            </td>
          </tr>
        `;
      })
      .join("");
  } catch (err) {
    if (tbody) {
      tbody.innerHTML = `<tr><td colspan="6" style="text-align:center; padding:20px; color:var(--rose);">Error loading rules: ${err.message}</td></tr>`;
    }
  }
}

async function createNewRule() {
  const name = document.getElementById("rule-name-input")?.value.trim();
  const feature = document.getElementById("rule-feature-select")?.value;
  const op = document.getElementById("rule-op-select")?.value;
  const valRaw = document.getElementById("rule-val-input")?.value.trim();
  const action = document.getElementById("rule-action-select")?.value;

  if (!name || !valRaw) {
    alert("Please fill all required rule fields");
    return;
  }

  const value = isNaN(Number(valRaw)) ? (valRaw === "true" ? true : valRaw === "false" ? false : valRaw) : Number(valRaw);

  const payload = {
    name,
    condition_json: { feature, op, value },
    action,
    enabled: true,
  };

  try {
    await adminApi("/admin/rules", "POST", payload);
    alert(`Rule "${name}" created successfully!`);
    closeModal("modal-create-rule");
    loadRules();
  } catch (err) {
    alert("Error creating rule: " + err.message);
  }
}

async function toggleRuleEnabled(ruleId, enabled) {
  try {
    const rules = await adminApi("/admin/rules");
    const rule = rules.find((r) => r.id === ruleId);
    if (!rule) return;

    rule.enabled = enabled;
    await adminApi(`/admin/rules/${ruleId}`, "PUT", {
      name: rule.name,
      condition_json: rule.condition_json,
      action: rule.action,
      enabled: enabled,
    });
  } catch (err) {
    alert("Toggle rule error: " + err.message);
    loadRules();
  }
}

async function deleteRule(ruleId) {
  if (!confirm(`Are you sure you want to delete Rule #${ruleId}?`)) return;

  try {
    await adminApi(`/admin/rules/${ruleId}`, "DELETE");
    loadRules();
  } catch (err) {
    alert("Delete rule error: " + err.message);
  }
}

// ── 6. Metrics & Charts (Chart.js) ──────────────────────────────────────────

async function loadMetrics() {
  try {
    const data = await adminApi("/admin/metrics");

    // KPI Cards
    const totalTxnEl = document.getElementById("metric-total-txns");
    const totalHeldEl = document.getElementById("metric-total-held");
    const fraudRateEl = document.getElementById("metric-fraud-rate");

    if (totalTxnEl) totalTxnEl.textContent = (data.total_transactions || 0).toLocaleString();
    if (totalHeldEl) totalHeldEl.textContent = (data.total_held || 0).toLocaleString();

    const rate = data.total_transactions > 0 ? ((data.total_held / data.total_transactions) * 100).toFixed(1) : "0.0";
    if (fraudRateEl) fraudRateEl.textContent = `${rate}%`;

    // 1. Daily Alerts Bar Chart
    renderDailyAlertsChart(data.alerts_per_day || []);

    // 2. Outcomes Doughnut Chart
    renderOutcomesChart(data.review_outcome_counts || {});
  } catch (err) {
    console.error("Error loading metrics:", err);
  }
}

function renderDailyAlertsChart(dailyData) {
  const ctx = document.getElementById("chart-daily-alerts")?.getContext("2d");
  if (!ctx || typeof Chart === "undefined") return;

  if (STATE.charts.daily) {
    STATE.charts.daily.destroy();
  }

  const labels = dailyData.map((d) => d.day);
  const counts = dailyData.map((d) => d.count);

  STATE.charts.daily = new Chart(ctx, {
    type: "bar",
    data: {
      labels: labels.length > 0 ? labels : ["No Recent Alerts"],
      datasets: [
        {
          label: "Alerts Triggered",
          data: counts.length > 0 ? counts : [0],
          backgroundColor: "rgba(99, 102, 241, 0.7)",
          borderColor: "#6366f1",
          borderRadius: 6,
        },
      ],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: { display: false },
      },
      scales: {
        y: { beginAtZero: true, grid: { color: "rgba(255, 255, 255, 0.05)" } },
        x: { grid: { display: false } },
      },
    },
  });
}

function renderOutcomesChart(outcomes) {
  const ctx = document.getElementById("chart-outcomes")?.getContext("2d");
  if (!ctx || typeof Chart === "undefined") return;

  if (STATE.charts.outcomes) {
    STATE.charts.outcomes.destroy();
  }

  const labels = Object.keys(outcomes);
  const dataVals = Object.values(outcomes);

  const colors = {
    APPROVED: "#10b981",
    CONFIRMED_FRAUD: "#f43f5e",
    ESCALATED: "#a855f7",
    OPEN: "#f59e0b",
  };

  STATE.charts.outcomes = new Chart(ctx, {
    type: "doughnut",
    data: {
      labels: labels.length > 0 ? labels : ["No Outcomes Yet"],
      datasets: [
        {
          data: dataVals.length > 0 ? dataVals : [1],
          backgroundColor: labels.length > 0 ? labels.map((l) => colors[l] || "#64748b") : ["#334155"],
          borderWidth: 2,
          borderColor: "#131b2e",
        },
      ],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: { position: "right", labels: { color: "#94a3b8", font: { size: 12 } } },
      },
    },
  });
}

// ── 7. Drift Report Page ────────────────────────────────────────────────────

function loadDriftFrame() {
  const frame = document.getElementById("drift-iframe");
  if (frame) {
    frame.src = "/admin/drift";
  }
}

// ── 8. Audit Log ────────────────────────────────────────────────────────────

async function loadAuditLog() {
  const tbody = document.getElementById("audit-table-body");
  if (tbody) {
    tbody.innerHTML = `<tr><td colspan="5" style="text-align:center; padding:24px; color:var(--text-muted);">Fetching immutable audit trail...</td></tr>`;
  }

  try {
    const entries = await adminApi("/admin/audit");
    if (!tbody) return;

    if (entries.length === 0) {
      tbody.innerHTML = `<tr><td colspan="5" style="text-align:center; padding:24px; color:var(--text-muted);">No audit entries found.</td></tr>`;
      return;
    }

    tbody.innerHTML = entries
      .map((e) => {
        const dateStr = new Date(e.ts).toLocaleString();
        const payloadStr = JSON.stringify(e.after_json || e.before_json || {});

        return `
          <tr>
            <td><strong>#${e.id}</strong></td>
            <td>${dateStr}</td>
            <td><strong>${e.action}</strong></td>
            <td><code>${e.target}</code></td>
            <td><code style="font-family:var(--font-mono); font-size:0.75rem; color:#94a3b8;">${payloadStr}</code></td>
          </tr>
        `;
      })
      .join("");
  } catch (err) {
    if (tbody) {
      tbody.innerHTML = `<tr><td colspan="5" style="text-align:center; padding:20px; color:var(--rose);">Error loading audit log: ${err.message}</td></tr>`;
    }
  }
}

// ── 9. Reset Demo Data ──────────────────────────────────────────────────────

async function resetDemoData() {
  if (
    !confirm(
      "⚠️ DANGER: Reset Demo Data?\n\nThis will clear all transactions and alerts, restore all user accounts to ₹50,000.00 initial balance, and log the reset action in the audit trail.\n\nProceed?"
    )
  ) {
    return;
  }

  try {
    const res = await adminApi("/admin/reset-demo", "POST");
    alert(res.message);
    loadCurrentTab();
  } catch (err) {
    alert("Reset failed: " + err.message);
  }
}

// ── Modal Helper ────────────────────────────────────────────────────────────

function openModal(id) {
  const m = document.getElementById(id);
  if (m) m.classList.add("open");
}

function closeModal(id) {
  const m = document.getElementById(id);
  if (m) m.classList.remove("open");
}

// ── Initialization ──────────────────────────────────────────────────────────

document.addEventListener("DOMContentLoaded", () => {
  // Check auth session
  if (STATE.token && STATE.user) {
    updateUserUI();
    hideLoginModal();
    switchTab("alerts");
    startAutoRefresh();
  } else {
    showLoginModal();
  }

  // Sidebar Tab Navigation
  document.querySelectorAll(".nav-item").forEach((btn) => {
    btn.addEventListener("click", () => {
      const tab = btn.getAttribute("data-tab");
      if (tab) switchTab(tab);
    });
  });

  // Quick Credential Login Buttons
  const adminCredBtn = document.getElementById("btn-quick-admin");
  if (adminCredBtn) {
    adminCredBtn.addEventListener("click", () => performLogin("admin@sentinel", "AdminPass123!"));
  }

  const analystCredBtn = document.getElementById("btn-quick-analyst");
  if (analystCredBtn) {
    analystCredBtn.addEventListener("click", () => performLogin("analyst1@sentinel", "Analyst1234!"));
  }

  // Custom Login Form Submit
  const loginForm = document.getElementById("admin-login-form");
  if (loginForm) {
    loginForm.addEventListener("submit", (e) => {
      e.preventDefault();
      const upi = document.getElementById("admin-login-upi")?.value.trim();
      const pass = document.getElementById("admin-login-pass")?.value.trim();
      if (upi && pass) performLogin(upi, pass);
    });
  }

  // Sign out
  const logoutBtn = document.getElementById("btn-admin-logout");
  if (logoutBtn) logoutBtn.addEventListener("click", performLogout);

  // Reset Demo Data Button
  const resetBtn = document.getElementById("btn-reset-demo-action");
  if (resetBtn) resetBtn.addEventListener("click", resetDemoData);

  // Alert Filters
  const alertFilter = document.getElementById("alert-status-filter");
  if (alertFilter) {
    alertFilter.addEventListener("change", () => loadAlertQueue(true));
  }

  // Transaction Search Actions
  const txnSearchBtn = document.getElementById("btn-search-txns");
  if (txnSearchBtn) txnSearchBtn.addEventListener("click", searchTransactions);

  // Graph Search Actions
  const graphQueryBtn = document.getElementById("btn-query-graph");
  if (graphQueryBtn) graphQueryBtn.addEventListener("click", loadAccountGraph);

  // Config Sliders & Save
  const holdSlider = document.getElementById("conf-t-hold");
  const stepSlider = document.getElementById("conf-t-step");
  if (holdSlider) {
    holdSlider.addEventListener("input", (e) => {
      document.getElementById("val-t-hold").textContent = parseFloat(e.target.value).toFixed(2);
    });
  }
  if (stepSlider) {
    stepSlider.addEventListener("input", (e) => {
      document.getElementById("val-t-step").textContent = parseFloat(e.target.value).toFixed(2);
    });
  }

  const saveConfigBtn = document.getElementById("btn-save-config");
  if (saveConfigBtn) saveConfigBtn.addEventListener("click", saveConfig);

  // Rules Modal & Submission
  const openRuleModalBtn = document.getElementById("btn-open-create-rule");
  if (openRuleModalBtn) {
    openRuleModalBtn.addEventListener("click", () => openModal("modal-create-rule"));
  }

  const submitRuleBtn = document.getElementById("btn-submit-create-rule");
  if (submitRuleBtn) submitRuleBtn.addEventListener("click", createNewRule);

  // Modal Close Buttons
  document.querySelectorAll(".btn-close-modal").forEach((btn) => {
    btn.addEventListener("click", () => {
      const modal = btn.closest(".modal-backdrop");
      if (modal) modal.classList.remove("open");
    });
  });
});
