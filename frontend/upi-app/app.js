/**
 * Sentinel AI UPI Demo App — Application Logic
 * Pure Vanilla JavaScript (Client-side SPA)
 * Interacts with FastAPI backend via relative URLs
 */

// ── Configuration & State ───────────────────────────────────────────────────

const DEMO_PASSWORD = "Demo1234!";

const STATE = {
  token: localStorage.getItem("sentinel_customer_token") || null,
  user: JSON.parse(localStorage.getItem("sentinel_customer_user") || "null"),
  currentPayment: {
    receiver_upi: "",
    amount: "100",
    note: "",
    device_id: "phone-client-001",
    ip: "10.177.233.244",
    city: "Bengaluru",
    txn_id: null,
  },
  pin: "",
  balanceVisible: true,
  lastBalance: 50000.00,
};

// ── DOM Elements ────────────────────────────────────────────────────────────

const views = {
  login: document.getElementById("view-login"),
  home: document.getElementById("view-home"),
  pay: document.getElementById("view-pay"),
  pin: document.getElementById("view-pin"),
  completed: document.getElementById("view-result-completed"),
  stepup: document.getElementById("view-result-stepup"),
  hold: document.getElementById("view-result-hold"),
};

const loader = document.getElementById("loading-overlay");
const loaderText = document.getElementById("loading-text");
const loaderSubtext = document.getElementById("loading-subtext");

// ── View Management ─────────────────────────────────────────────────────────

function switchView(viewName) {
  Object.keys(views).forEach((name) => {
    if (views[name]) {
      views[name].classList.remove("active");
    }
  });

  const target = views[viewName];
  if (target) {
    target.classList.add("active");
    target.scrollTop = 0;
  }
}

function showLoader(title = "Processing...", subtitle = "Please wait a moment") {
  if (loader && loaderText && loaderSubtext) {
    loaderText.textContent = title;
    loaderSubtext.textContent = subtitle;
    loader.classList.add("active");
  }
}

function hideLoader() {
  if (loader) {
    loader.classList.remove("active");
  }
}

// ── API Helper (Relative URLs) ──────────────────────────────────────────────

async function apiRequest(endpoint, method = "GET", body = null) {
  const headers = {
    "Content-Type": "application/json",
  };

  if (STATE.token) {
    headers["Authorization"] = `Bearer ${STATE.token}`;
  }

  const options = { method, headers };
  if (body) {
    options.body = JSON.stringify(body);
  }

  try {
    const response = await fetch(endpoint, options);
    const data = await response.json().catch(() => ({}));

    if (!response.ok) {
      const errorMsg = data.detail || `Request failed with status ${response.status}`;
      throw new Error(errorMsg);
    }

    return data;
  } catch (err) {
    console.error(`API Error on ${endpoint}:`, err);
    throw err;
  }
}

// ── Authentication ──────────────────────────────────────────────────────────

async function performLogin(upi_id, password) {
  showLoader("Authenticating...", "Verifying credentials with Sentinel AI");

  try {
    const resp = await apiRequest("/auth/login", "POST", { upi_id, password });
    STATE.token = resp.access_token;
    STATE.user = { upi_id, role: resp.role };

    localStorage.setItem("sentinel_customer_token", STATE.token);
    localStorage.setItem("sentinel_customer_user", JSON.stringify(STATE.user));

    await loadUserData();
    switchView("home");
  } catch (err) {
    alert("Login failed: " + err.message);
  } finally {
    hideLoader();
  }
}

function performLogout() {
  STATE.token = null;
  STATE.user = null;
  localStorage.removeItem("sentinel_customer_token");
  localStorage.removeItem("sentinel_customer_user");
  switchView("login");
}

// ── Home & Data Loading ─────────────────────────────────────────────────────

async function loadUserData() {
  if (!STATE.user) return;

  // Update header and profile tags
  const nameEl = document.getElementById("profile-name");
  const upiEl = document.getElementById("profile-upi");
  const avatarEl = document.getElementById("profile-avatar-letter");

  const displayName = STATE.user.upi_id.split("@")[0].replace("_", " ");
  if (nameEl) nameEl.textContent = displayName.toUpperCase();
  if (upiEl) upiEl.textContent = STATE.user.upi_id;
  if (avatarEl) avatarEl.textContent = displayName.charAt(0).toUpperCase();

  await Promise.allSettled([fetchBalance(), fetchHistory()]);
}

async function fetchBalance() {
  try {
    const data = await apiRequest("/v1/payments/balance");
    STATE.lastBalance = parseFloat(data.balance);
    renderBalance();
  } catch (err) {
    // If balance endpoint fails or initial load, keep last balance
    renderBalance();
  }
}

function renderBalance() {
  const balEl = document.getElementById("display-balance");
  if (!balEl) return;

  if (STATE.balanceVisible) {
    balEl.textContent = `₹${STATE.lastBalance.toLocaleString("en-IN", {
      minimumFractionDigits: 2,
      maximumFractionDigits: 2,
    })}`;
  } else {
    balEl.textContent = "₹ ••••••";
  }
}

function toggleBalanceVisibility() {
  STATE.balanceVisible = !STATE.balanceVisible;
  const eyeBtn = document.getElementById("btn-toggle-eye");
  if (eyeBtn) {
    eyeBtn.textContent = STATE.balanceVisible ? "👁️" : "🔒";
  }
  renderBalance();
}

async function fetchHistory() {
  const container = document.getElementById("history-list-container");
  if (!container) return;

  try {
    const list = await apiRequest("/v1/payments/history?limit=10");
    if (!list || list.length === 0) {
      container.innerHTML = `
        <div style="text-align:center; padding:24px 10px; color:var(--text-muted); font-size:0.85rem;">
          No transactions yet.<br>Tap <strong>"Pay UPI ID"</strong> to test a transfer!
        </div>
      `;
      return;
    }

    container.innerHTML = list
      .map((item) => {
        const statusClass = (item.status || "completed").toLowerCase();
        const icon = statusClass === "completed" ? "✓" : statusClass === "held" ? "🛑" : "⚠️";
        const dateStr = new Date(item.created_at).toLocaleTimeString([], {
          hour: "2-digit",
          minute: "2-digit",
        });

        return `
          <div class="history-item">
            <div class="history-item-left">
              <div class="history-icon ${statusClass}">
                ${icon}
              </div>
              <div class="history-details">
                <h5>To: ${item.receiver_upi}</h5>
                <span>${dateStr} • ${item.city || "UPI Transfer"}</span>
              </div>
            </div>
            <div class="history-item-right">
              <div class="history-amount">-₹${parseFloat(item.amount).toLocaleString("en-IN")}</div>
              <span class="status-badge ${statusClass}">${item.status}</span>
            </div>
          </div>
        `;
      })
      .join("");
  } catch (err) {
    container.innerHTML = `
      <div style="text-align:center; padding:16px; color:var(--text-muted); font-size:0.8rem;">
        History unavailable
      </div>
    `;
  }
}

// ── Payment Initiation Flow ─────────────────────────────────────────────────

function startPaymentTo(receiver_upi = "") {
  const receiverInput = document.getElementById("input-payee-upi");
  const amountInput = document.getElementById("input-amount");

  if (receiverInput) receiverInput.value = receiver_upi;
  if (amountInput) amountInput.value = "500";

  switchView("pay");
}

function setQuickAmount(val) {
  const amountInput = document.getElementById("input-amount");
  if (amountInput) {
    amountInput.value = val;
  }
}

function proceedToPin() {
  const receiverInput = document.getElementById("input-payee-upi");
  const amountInput = document.getElementById("input-amount");
  const noteInput = document.getElementById("input-note");

  const deviceInput = document.getElementById("sim-device-id");
  const cityInput = document.getElementById("sim-city");
  const ipInput = document.getElementById("sim-ip");

  const receiver_upi = receiverInput ? receiverInput.value.trim() : "";
  const amount = amountInput ? amountInput.value.trim() : "";

  if (!receiver_upi || !receiver_upi.includes("@")) {
    alert("Please enter a valid receiver UPI ID (e.g. customer2@sentinel)");
    return;
  }

  const amtNum = parseFloat(amount);
  if (isNaN(amtNum) || amtNum <= 0) {
    alert("Please enter a valid payment amount greater than ₹0");
    return;
  }

  STATE.currentPayment = {
    receiver_upi,
    amount: amtNum.toString(),
    note: noteInput ? noteInput.value.trim() : "",
    device_id: deviceInput && deviceInput.value.trim() ? deviceInput.value.trim() : "phone-client-001",
    city: cityInput && cityInput.value.trim() ? cityInput.value.trim() : "Bengaluru",
    ip: ipInput && ipInput.value.trim() ? ipInput.value.trim() : "10.177.233.244",
    txn_id: null,
  };

  // Update PIN screen preview
  const pinPayeeEl = document.getElementById("pin-payee-display");
  const pinAmtEl = document.getElementById("pin-amount-display");
  if (pinPayeeEl) pinPayeeEl.textContent = `Paying ${receiver_upi}`;
  if (pinAmtEl) pinAmtEl.textContent = `₹${amtNum.toLocaleString("en-IN")}`;

  // Reset PIN
  STATE.pin = "";
  renderPinDots();

  switchView("pin");
}

// ── PIN Screen & Keypad ─────────────────────────────────────────────────────

function handlePinKey(digit) {
  if (STATE.pin.length < 4) {
    STATE.pin += digit;
    renderPinDots();

    // Auto submit upon reaching 4 digits
    if (STATE.pin.length === 4) {
      setTimeout(() => {
        executePayment();
      }, 250);
    }
  }
}

function handlePinBackspace() {
  if (STATE.pin.length > 0) {
    STATE.pin = STATE.pin.slice(0, -1);
    renderPinDots();
  }
}

function renderPinDots() {
  const dots = document.querySelectorAll(".pin-dot");
  dots.forEach((dot, index) => {
    if (index < STATE.pin.length) {
      dot.classList.add("filled");
    } else {
      dot.classList.remove("filled");
    }
  });
}

// ── Payment Submission & Result Handling ────────────────────────────────────

async function executePayment() {
  showLoader("Evaluating Risk...", "Sentinel AI scoring transaction & evaluating rules");

  const payload = {
    receiver_upi: STATE.currentPayment.receiver_upi,
    amount: parseFloat(STATE.currentPayment.amount),
    device_id: STATE.currentPayment.device_id,
    ip: STATE.currentPayment.ip,
    city: STATE.currentPayment.city,
  };

  try {
    const res = await apiRequest("/v1/payments", "POST", payload);
    STATE.currentPayment.txn_id = res.txn_id;

    hideLoader();

    if (res.decision === "ALLOW" || res.status === "COMPLETED") {
      showCompletedResult(res);
    } else if (res.decision === "STEP_UP" || res.status === "PENDING_CONFIRM") {
      showStepUpResult(res);
    } else if (res.decision === "HOLD" || res.status === "HELD") {
      showHoldResult(res);
    } else {
      alert(`Transaction response: ${res.status} (${res.message})`);
      switchView("home");
    }
  } catch (err) {
    hideLoader();
    alert("Payment Failed: " + err.message);
    switchView("pay");
  }
}

function showCompletedResult(res) {
  const amtEl = document.getElementById("res-completed-amt");
  const toEl = document.getElementById("res-completed-to");
  const idEl = document.getElementById("res-completed-id");
  const msgEl = document.getElementById("res-completed-msg");

  if (amtEl) amtEl.textContent = `₹${parseFloat(STATE.currentPayment.amount).toLocaleString("en-IN")}`;
  if (toEl) toEl.textContent = STATE.currentPayment.receiver_upi;
  if (idEl) idEl.textContent = `#${res.txn_id}`;
  if (msgEl) msgEl.textContent = res.message || "Payment processed successfully.";

  fetchBalance();
  fetchHistory();
  switchView("completed");
}

function showStepUpResult(res) {
  const amtEl = document.getElementById("res-stepup-amt");
  const toEl = document.getElementById("res-stepup-to");
  const idEl = document.getElementById("res-stepup-id");
  const msgEl = document.getElementById("res-stepup-msg");

  if (amtEl) amtEl.textContent = `₹${parseFloat(STATE.currentPayment.amount).toLocaleString("en-IN")}`;
  if (toEl) toEl.textContent = STATE.currentPayment.receiver_upi;
  if (idEl) idEl.textContent = `#${res.txn_id}`;
  if (msgEl) msgEl.textContent = res.message || "Unusual transaction pattern detected.";

  switchView("stepup");
}

async function confirmStepUpPayment() {
  if (!STATE.currentPayment.txn_id) return;

  showLoader("Verifying Confirmation...", "Updating ledger and completing payment");

  try {
    const res = await apiRequest(`/v1/payments/${STATE.currentPayment.txn_id}/confirm`, "POST");
    hideLoader();
    showCompletedResult(res);
  } catch (err) {
    hideLoader();
    alert("Confirmation Failed: " + err.message);
    switchView("home");
  }
}

function cancelStepUpPayment() {
  alert("Transaction cancelled. Your account balance was not modified.");
  switchView("home");
  fetchBalance();
  fetchHistory();
}

function showHoldResult(res) {
  const amtEl = document.getElementById("res-hold-amt");
  const toEl = document.getElementById("res-hold-to");
  const idEl = document.getElementById("res-hold-id");
  const msgEl = document.getElementById("res-hold-msg");

  if (amtEl) amtEl.textContent = `₹${parseFloat(STATE.currentPayment.amount).toLocaleString("en-IN")}`;
  if (toEl) toEl.textContent = STATE.currentPayment.receiver_upi;
  if (idEl) idEl.textContent = `#${res.txn_id}`;
  if (msgEl) msgEl.textContent = res.message || "Flagged for fraud analyst review.";

  switchView("hold");
}

// ── Event Listeners Setup ───────────────────────────────────────────────────

document.addEventListener("DOMContentLoaded", () => {
  // Check existing session
  if (STATE.token && STATE.user) {
    loadUserData();
    switchView("home");
  } else {
    switchView("login");
  }

  // 1-Tap Demo Users Login
  document.querySelectorAll(".demo-user-card").forEach((card) => {
    card.addEventListener("click", () => {
      const upi = card.getAttribute("data-upi");
      if (upi) {
        performLogin(upi, DEMO_PASSWORD);
      }
    });
  });

  // Custom Login Toggle & Submit
  const toggleBtn = document.getElementById("btn-toggle-custom-login");
  const customForm = document.getElementById("custom-login-form");
  if (toggleBtn && customForm) {
    toggleBtn.addEventListener("click", () => {
      customForm.style.display = customForm.style.display === "none" ? "block" : "none";
    });
  }

  const customLoginBtn = document.getElementById("btn-custom-login");
  if (customLoginBtn) {
    customLoginBtn.addEventListener("click", (e) => {
      e.preventDefault();
      const upi = document.getElementById("custom-upi")?.value.trim();
      const pass = document.getElementById("custom-password")?.value.trim();
      if (upi && pass) {
        performLogin(upi, pass);
      } else {
        alert("Please enter both UPI ID and password");
      }
    });
  }

  // Logout
  const logoutBtn = document.getElementById("btn-logout");
  if (logoutBtn) {
    logoutBtn.addEventListener("click", performLogout);
  }

  // Eye Toggle & Balance Refresh
  const eyeBtn = document.getElementById("btn-toggle-eye");
  if (eyeBtn) eyeBtn.addEventListener("click", toggleBalanceVisibility);

  const refreshBalBtn = document.getElementById("btn-refresh-balance");
  if (refreshBalBtn) refreshBalBtn.addEventListener("click", fetchBalance);

  // Home CTA "Pay UPI ID"
  const homePayBtn = document.getElementById("btn-home-pay");
  if (homePayBtn) {
    homePayBtn.addEventListener("click", () => startPaymentTo(""));
  }

  // Payee Carousel Chips
  document.querySelectorAll(".payee-chip").forEach((chip) => {
    chip.addEventListener("click", () => {
      const upi = chip.getAttribute("data-upi");
      if (upi) startPaymentTo(upi);
    });
  });

  // Back Navigation Buttons
  document.querySelectorAll(".btn-back-home").forEach((btn) => {
    btn.addEventListener("click", () => {
      fetchBalance();
      fetchHistory();
      switchView("home");
    });
  });

  const backPayBtn = document.getElementById("btn-back-to-pay");
  if (backPayBtn) {
    backPayBtn.addEventListener("click", () => switchView("pay"));
  }

  // Quick Amount Buttons
  document.querySelectorAll(".chip-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      const val = btn.getAttribute("data-val");
      if (val) setQuickAmount(val);
    });
  });

  // Simulation Drawer Toggle
  const simToggle = document.getElementById("sim-drawer-toggle");
  const simFields = document.getElementById("sim-fields-container");
  if (simToggle && simFields) {
    simToggle.addEventListener("click", () => {
      simFields.classList.toggle("open");
    });
  }

  // Proceed to PIN
  const proceedBtn = document.getElementById("btn-proceed-pay");
  if (proceedBtn) {
    proceedBtn.addEventListener("click", proceedToPin);
  }

  // Numeric Keypad
  document.querySelectorAll(".key-digit").forEach((key) => {
    key.addEventListener("click", () => {
      const digit = key.getAttribute("data-key");
      if (digit) handlePinKey(digit);
    });
  });

  const backspaceKey = document.getElementById("key-backspace");
  if (backspaceKey) {
    backspaceKey.addEventListener("click", handlePinBackspace);
  }

  const submitKey = document.getElementById("key-submit");
  if (submitKey) {
    submitKey.addEventListener("click", () => {
      if (STATE.pin.length >= 4) {
        executePayment();
      } else {
        alert("Please enter a 4-digit PIN");
      }
    });
  }

  // Step-Up Action Buttons
  const confirmStepUpBtn = document.getElementById("btn-stepup-confirm");
  if (confirmStepUpBtn) {
    confirmStepUpBtn.addEventListener("click", confirmStepUpPayment);
  }

  const cancelStepUpBtn = document.getElementById("btn-stepup-cancel");
  if (cancelStepUpBtn) {
    cancelStepUpBtn.addEventListener("click", cancelStepUpPayment);
  }

  // Demo Simulation Attack Panel Toggle & Actions
  const demoPanelToggle = document.getElementById("demo-panel-toggle");
  const demoPanelBody = document.getElementById("demo-panel-body");
  const demoPanelArrow = document.getElementById("demo-panel-arrow");

  if (demoPanelToggle && demoPanelBody) {
    demoPanelToggle.addEventListener("click", () => {
      const isClosed = demoPanelBody.style.display === "none";
      demoPanelBody.style.display = isClosed ? "flex" : "none";
      if (demoPanelArrow) demoPanelArrow.textContent = isClosed ? "▲" : "▼";
    });
  }

  document.querySelectorAll(".btn-scenario").forEach((btn) => {
    btn.addEventListener("click", () => {
      const scenario = btn.getAttribute("data-scenario");
      if (scenario) triggerSimulationScenario(scenario);
    });
  });

  // Keyboard support for PIN entry
  window.addEventListener("keydown", (e) => {
    if (views.pin && views.pin.classList.contains("active")) {
      if (e.key >= "0" && e.key <= "9") {
        handlePinKey(e.key);
      } else if (e.key === "Backspace") {
        handlePinBackspace();
      } else if (e.key === "Enter") {
        if (STATE.pin.length >= 4) executePayment();
      }
    }
  });
});

async function triggerSimulationScenario(scenario) {
  showLoader(`Simulating ${scenario}...`, "Executing attack scenario via /dev/simulate");

  try {
    let token = localStorage.getItem("sentinel_admin_token");
    if (!token) {
      const authRes = await fetch("/auth/login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ upi_id: "admin@sentinel", password: "AdminPass123!" }),
      });
      if (authRes.ok) {
        const authData = await authRes.json();
        token = authData.access_token;
      }
    }

    const res = await fetch(`/dev/simulate/${scenario}`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "Authorization": `Bearer ${token || STATE.token}`,
      },
    });

    const data = await res.json();
    hideLoader();

    if (!res.ok) {
      throw new Error(data.detail || `Simulation failed with HTTP ${res.status}`);
    }

    const statusEl = document.getElementById("demo-scenario-status");
    if (statusEl) {
      statusEl.style.display = "block";
      statusEl.style.background = "var(--emerald-bg)";
      statusEl.style.color = "var(--emerald)";
      statusEl.textContent = `✓ ${data.scenario} executed: ${data.transactions_created} transactions processed! View in Admin Console.`;
    }

    fetchBalance();
    fetchHistory();
  } catch (err) {
    hideLoader();
    const statusEl = document.getElementById("demo-scenario-status");
    if (statusEl) {
      statusEl.style.display = "block";
      statusEl.style.background = "var(--rose-bg)";
      statusEl.style.color = "var(--rose)";
      statusEl.textContent = `✕ Simulation failed: ${err.message}`;
    }
  }
}

