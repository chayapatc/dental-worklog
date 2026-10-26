// Dental Worklog — Frontend Logic (Pico CSS + auth)

let clinicsCache = [];
let logsCache = [];
let trendsChart = null;
let monthlyChart = null;
let currentUser = null;

// Chart.js is only needed on the Trends and Monthly P&L views — load it on
// demand so the login and logging screens never download it.
let chartJsPromise = null;
function ensureChartJs() {
  if (window.Chart) return Promise.resolve();
  if (!chartJsPromise) {
    chartJsPromise = new Promise((resolve, reject) => {
      const s = document.createElement("script");
      s.src = "/static/chart.umd.min.js";
      s.onload = () => resolve();
      s.onerror = () => {
        chartJsPromise = null;
        reject(new Error("Chart.js failed to load"));
      };
      document.head.appendChild(s);
    });
  }
  return chartJsPromise;
}

// ── Theme (light / dark) ────────────────────────────────────────────────
// The chosen theme is applied by an inline script in <head> before first
// paint; this module only owns the toggle and keeps its label in sync.
const THEME_ICONS = {
  // icon shows the theme you would switch TO
  light: '<circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/>',
  dark: '<path d="M20.5 14.6A8.6 8.6 0 0 1 9.4 3.5 9 9 0 1 0 20.5 14.6Z"/>',
};

function currentTheme() {
  return document.documentElement.getAttribute("data-theme") === "dark" ? "dark" : "light";
}

function syncThemeButton() {
  const btn = document.getElementById("themeBtn");
  const icon = document.getElementById("themeIcon");
  if (!btn || !icon) return;
  const next = currentTheme() === "dark" ? "light" : "dark";
  icon.innerHTML = THEME_ICONS[next];
  const label = `Switch to ${next} theme`;
  btn.setAttribute("aria-label", label);
  btn.setAttribute("title", label);
}

function setTheme(theme) {
  document.documentElement.setAttribute("data-theme", theme);
  try { localStorage.setItem("dw-theme", theme); } catch (e) {}
  syncThemeButton();
}

// Dates read like the design: "26 Oct 2026", matching the LINE bot's replies.
const MONTHS = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"];
function dateLabel(iso) {
  if (!iso || iso.length < 10) return iso || "";
  const [y, m, d] = iso.split("-").map(Number);
  return `${String(d).padStart(2, "0")} ${MONTHS[m - 1] || ""} ${y}`;
}

// Line icons instead of emoji, so the controls match the rest of the UI.
const SVG_ATTRS = 'viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" focusable="false"';
const ICON_EDIT = `<svg ${SVG_ATTRS}><path d="M4 20h4L19 9l-4-4L4 16v4Z"/><path d="M14.5 5.5l4 4"/></svg>`;
const ICON_TRASH = `<svg ${SVG_ATTRS}><path d="M4 7h16M9.5 7V5h5v2M6.5 7l1 12.5h9L17.5 7M10.5 11v5.5M13.5 11v5.5"/></svg>`;

// Money + rate formatting, so every figure in the app reads the same way.
function money(n) { return "฿" + Math.round(n || 0).toLocaleString("en-US"); }
function rateText(r) { return money(r) + "/h"; }

// HTML Escaping Utility to prevent XSS
function escapeHtml(str) {
  if (str === null || str === undefined) return "";
  return String(str)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;");
}

// ── Color Presets ───────────────────────────────────────────────────────
const COLOR_PRESETS = [
  "#38bdf8", "#4ade80", "#fbbf24", "#f87171",
  "#a78bfa", "#fb923c", "#2dd4bf", "#f472b6",
  "#60a5fa", "#34d399",
];
let selectedColor = COLOR_PRESETS[0];

function buildColorSwatches(currentColor) {
  return COLOR_PRESETS.map(c =>
    `<button type="button" class="swatch" style="--swatch:${c}"
       aria-pressed="${c === currentColor}" aria-label="Colour ${c}"
       onclick="selectColor('${c}')" title="${c}"></button>`
  ).join("");
}

function selectColor(color) {
  selectedColor = color;
  document.getElementById("clinic-color-picker").value = color;
  document.getElementById("color-swatches").innerHTML = buildColorSwatches(color);
}

function selectCustomColor(color) {
  selectedColor = color;
  document.getElementById("color-swatches").innerHTML = buildColorSwatches(null);
}

// ── Auth Bootstrap ──────────────────────────────────────────────────────
async function checkAuth() {
  try {
    const res = await fetch("/api/me");
    const user = await res.json();
    if (user && user.id) {
      currentUser = user;
      showApp();
      // Deep link: /?view=trends opens that view directly. Lets each view be
      // audited and bookmarked on its own URL.
      const requested = new URLSearchParams(window.location.search).get("view");
      if (requested && document.getElementById("view-" + requested)) {
        switchTab(requested);
      } else {
        refreshLogView();
      }
    } else {
      showLogin();
    }
  } catch {
    showLogin();
  }
}

function showLogin() {
  document.getElementById("login-screen").classList.remove("hidden");
  document.getElementById("app-screen").classList.add("hidden");
}

function showApp() {
  document.getElementById("login-screen").classList.add("hidden");
  document.getElementById("app-screen").classList.remove("hidden");
  document.getElementById("user-name").textContent = currentUser.name;
  document.getElementById("user-name").title = currentUser.name;
  const av = document.getElementById("user-avatar");
  const avatarUrl = currentUser.avatar_url || "";
  if (avatarUrl.startsWith("http://") || avatarUrl.startsWith("https://")) {
    av.src = avatarUrl;
    av.style.display = "";
  } else {
    av.style.display = "none";
  }
  // Initialize color swatches on add clinic form
  document.getElementById("color-swatches").innerHTML = buildColorSwatches(COLOR_PRESETS[0]);
  document.getElementById("clinic-color-picker").value = COLOR_PRESETS[0];

  // Check LINE binding status
  checkLineBinding();

  // Handle LINE binding success redirect
  if (window.location.search.includes("line_bound=1")) {
    toast("LINE account bound successfully! 🟢");
    window.history.replaceState({}, "", "/");
  }
}

async function checkLineBinding() {
  try {
    const res = await fetch("/api/line/status");
    if (res.status === 401) return;
    const data = await res.json();
    const badge = document.getElementById("line-badge");
    badge.classList.toggle("hidden", !data.bound);
    badge.title = data.bound ? "LINE connected" : "";
  } catch {}
}

function logout() {
  window.location.href = "/auth/logout";
}

// ── Navigation ──────────────────────────────────────────────────────────
function switchTab(view) {
  const target = document.getElementById("view-" + view);
  if (!target) return;
  // Deep links render the target view server-side, so it may already be
  // active. Hiding every view and re-showing it would throw away the painted
  // content (and invalidate Largest Contentful Paint) for no reason.
  const alreadyActive = target.classList.contains("active");
  target.classList.add("active");
  if (!alreadyActive) {
    document.querySelectorAll(".view").forEach(v => { if (v !== target) v.classList.remove("active"); });
  }
  // Mark the matching tab active on both top nav and bottom nav
  document.querySelectorAll("nav [data-view], .bottom-nav [data-view]").forEach(el => {
    el.classList.toggle("active", el.dataset.view === view);
  });
  if (view === "log") refreshLogView();
  if (view === "clinics") refreshClinics();
  if (view === "tracker") refreshTracker();
  if (view === "trends") refreshTrends();
  if (view === "monthly") refreshMonthly();
  if (view === "income") setDefaultDates();
  // Scroll active bottom nav tab into view
  const activeTab = document.querySelector(".bottom-nav-scroll a.active");
  if (activeTab) activeTab.scrollIntoView({ behavior: "smooth", block: "nearest", inline: "center" });
}

document.querySelectorAll("nav [data-view], .bottom-nav [data-view]").forEach(link => {
  link.addEventListener("click", (e) => {
    e.preventDefault();
    switchTab(link.dataset.view);
    document.getElementById("main-nav").classList.remove("mobile-open");
  });
});

document.getElementById("menu-toggle").addEventListener("click", (e) => {
  const nav = document.getElementById("main-nav");
  const open = nav.classList.toggle("mobile-open");
  e.currentTarget.setAttribute("aria-expanded", String(open));
});

document.getElementById("themeBtn").addEventListener("click", () => {
  setTheme(currentTheme() === "dark" ? "light" : "dark");
});
syncThemeButton();

// ── Period & Metric Toggles ─────────────────────────────────────────────
document.querySelectorAll(".toggle-group button").forEach(btn => {
  btn.addEventListener("click", () => {
    const group = btn.parentElement;
    group.querySelectorAll("button").forEach(b => b.classList.remove("active"));
    btn.classList.add("active");

    const section = group.closest("section");
    if (section && section.id === "view-trends") refreshTrends();
  });
});

// ── API Helpers ─────────────────────────────────────────────────────────
async function api(url, opts = {}) {
  const res = await fetch(url, {
    headers: { "Content-Type": "application/json" },
    ...opts,
  });
  if (res.status === 401) {
    showLogin();
    throw new Error("Session expired — please login again");
  }
  const data = await res.json();
  if (!res.ok) throw new Error(data.error || "Request failed");
  return data;
}

function toast(msg, isError = false) {
  const el = document.getElementById("toast");
  el.textContent = msg;
  el.className = "toast show" + (isError ? " is-error" : "");
  clearTimeout(el._timer);
  el._timer = setTimeout(() => el.classList.remove("show"), 2500);
}

// Tap toast to dismiss
document.getElementById("toast").addEventListener("click", function() {
  this.classList.remove("show");
  clearTimeout(this._timer);
});

// ── Load Clinics Cache ─────────────────────────────────────────────────
async function loadClinics() {
  clinicsCache = await api("/api/clinics");
  return clinicsCache;
}

function populateClinicSelect() {
  const sel = document.getElementById("log-clinic");
  sel.innerHTML = '<option value="">Select a clinic…</option>';
  clinicsCache.forEach(c => {
    sel.innerHTML += `<option value="${c.id}">${escapeHtml(c.name)}</option>`;
  });
}

// ── Clinics View ────────────────────────────────────────────────────────
let editingClinicId = null;

async function refreshClinics() {
  await loadClinics();
  const tbody = document.querySelector("#clinics-table tbody");
  if (clinicsCache.length === 0) {
    tbody.innerHTML = '<tr><td class="text-center muted" colspan="2">No clinics yet</td></tr>';
    return;
  }
  tbody.innerHTML = clinicsCache.map(c => {
    if (editingClinicId === c.id) {
      return `<tr>
        <td>
          <input type="text" id="edit-name-${c.id}" class="input--sm" value="${escapeHtml(c.name)}" aria-label="Clinic name">
          <div class="swatches swatches--edit">${buildColorSwatchesForEdit(c.id, c.color)}</div>
          <input type="color" id="edit-color-picker-${c.id}" value="${c.color}" onchange="selectEditCustomColor(${c.id}, this.value)" title="Custom colour">
        </td>
        <td>
          <div class="row-actions">
            <button class="btn btn--primary btn--sm" onclick="saveEdit(${c.id})">Save</button>
            <button class="btn btn--ghost btn--sm btn--icon" onclick="cancelEdit()" aria-label="Cancel">✕</button>
          </div>
        </td>
      </tr>`;
    }
    return `<tr>
      <td><span class="clinic-cell"><span class="dot" style="background:${c.color}"></span>${escapeHtml(c.name)}</span></td>
      <td>
        <div class="row-actions">
          <button class="btn btn--ghost btn--sm" onclick="startEdit(${c.id})">Edit</button>
          <button class="btn btn--danger btn--sm" onclick="confirmDelete(${c.id})">Delete</button>
        </div>
      </td>
    </tr>`;
  }).join("");
}

let editingColor = null;

function buildColorSwatchesForEdit(clinicId, currentColor) {
  return COLOR_PRESETS.map(c =>
    `<button type="button" class="swatch swatch--sm" style="--swatch:${c}"
       aria-pressed="${c === currentColor}" aria-label="Colour ${c}"
       onclick="selectEditColor(${clinicId}, '${c}')" title="${c}"></button>`
  ).join("");
}

function selectEditColor(clinicId, color) {
  editingColor = color;
  document.getElementById(`edit-color-picker-${clinicId}`).value = color;
  document.querySelector(`.edit-swatches-${clinicId}`).innerHTML = buildColorSwatchesForEdit(clinicId, color);
}

function selectEditCustomColor(clinicId, color) {
  editingColor = color;
  document.querySelector(`.edit-swatches-${clinicId}`).innerHTML = buildColorSwatchesForEdit(clinicId, null);
}

function startEdit(id) {
  const clinic = clinicsCache.find(x => x.id === id);
  editingClinicId = id;
  editingColor = clinic ? clinic.color : COLOR_PRESETS[0];
  refreshClinics();
  setTimeout(() => {
    const inp = document.getElementById(`edit-name-${id}`);
    if (inp) { inp.focus(); inp.select(); }
  }, 50);
}

function cancelEdit() {
  editingClinicId = null;
  editingColor = null;
  refreshClinics();
}

async function saveEdit(id) {
  const inp = document.getElementById(`edit-name-${id}`);
  const name = inp.value.trim();
  if (!name) return toast("Name cannot be empty", true);
  try {
    await api(`/api/clinics/${id}`, { method: "PUT", body: JSON.stringify({ name, color: editingColor }) });
    editingClinicId = null;
    editingColor = null;
    toast("Clinic updated!");
    await refreshClinics();
    await loadClinics();
    populateClinicSelect();
  } catch (e) {
    toast(e.message, true);
  }
}

async function addClinic() {
  const input = document.getElementById("clinic-name");
  const name = input.value.trim();
  if (!name) return toast("Enter a clinic name", true);
  try {
    await api("/api/clinics", { method: "POST", body: JSON.stringify({ name, color: selectedColor }) });
    input.value = "";
    selectedColor = COLOR_PRESETS[0];
    document.getElementById("clinic-color-picker").value = COLOR_PRESETS[0];
    document.getElementById("color-swatches").innerHTML = buildColorSwatches(COLOR_PRESETS[0]);
    toast("Clinic added!");
    await refreshClinics();
    await loadClinics();
    populateClinicSelect();
  } catch (e) {
    toast(e.message, true);
  }
}

// ── Confirm Dialog ──────────────────────────────────────────────────────
let pendingDeleteId = null;
let pendingDeleteType = null;  // "clinic" or "log"

function confirmDelete(id) {
  const clinic = clinicsCache.find(x => x.id === id);
  const name = clinic ? clinic.name : "";
  pendingDeleteId = id;
  pendingDeleteType = "clinic";
  document.getElementById("confirm-title").textContent = "Delete Clinic";
  document.getElementById("confirm-message").textContent = `Delete "${name}"? This won't affect existing work logs.`;
  document.getElementById("confirm-btn").textContent = "Delete";
  document.getElementById("confirm-dialog").showModal();
}

function confirmDeleteLog(id) {
  const log = logsCache.find(x => x.id === id);
  if (!log) return;
  pendingDeleteId = id;
  pendingDeleteType = "log";
  document.getElementById("confirm-title").textContent = "Delete Log Entry";
  document.getElementById("confirm-message").textContent = `Delete entry: ${log.date} at ${log.clinic_name}? This cannot be undone.`;
  document.getElementById("confirm-btn").textContent = "Delete";
  document.getElementById("confirm-dialog").showModal();
}

function closeConfirm() {
  pendingDeleteId = null;
  pendingDeleteType = null;
  document.getElementById("confirm-dialog").close();
}

async function executeDelete() {
  if (!pendingDeleteId) return;
  try {
    if (pendingDeleteType === "log") {
      await api(`/api/logs/${pendingDeleteId}`, { method: "DELETE" });
      document.getElementById("confirm-dialog").close();
      toast("Log entry deleted");
      currentPage = 1;
      await refreshRecentLogs();
    } else {
      await api(`/api/clinics/${pendingDeleteId}`, { method: "DELETE" });
      document.getElementById("confirm-dialog").close();
      toast("Clinic removed from list (work logs preserved)");
      await refreshClinics();
      await loadClinics();
      populateClinicSelect();
    }
    pendingDeleteId = null;
    pendingDeleteType = null;
  } catch (e) {
    toast(e.message, true);
  }
}

// ── Inline Edit ─────────────────────────────────────────────────────────
function editLog(id) {
  const log = logsCache.find(x => x.id === id);
  if (!log) return;
  const row = document.getElementById("log-row-" + id);
  if (!row) return;

  const clinicOptions = clinicsCache.map(c =>
    `<option value="${c.id}" ${c.id === log.clinic_id ? 'selected' : ''}>${escapeHtml(c.name)}</option>`
  ).join("");

  row.innerHTML = `
    <td><input type="date" value="${log.date}" id="edit-date-${id}" class="input--sm" aria-label="Date"></td>
    <td><select id="edit-clinic-${id}" class="input--sm" aria-label="Clinic">${clinicOptions}</select></td>
    <td><input type="number" value="${log.hours}" id="edit-hours-${id}" step="0.5" min="0" class="input--sm input--num" aria-label="Hours"></td>
    <td><input type="number" value="${log.income}" id="edit-income-${id}" step="100" min="0" class="input--sm input--num" aria-label="Income"></td>
    <td><input type="number" value="${log.expense}" id="edit-expense-${id}" step="100" min="0" class="input--sm input--num" aria-label="Expense"></td>
    <td class="num muted">—</td>
    <td>
      <div class="row-actions">
        <button class="btn btn--primary btn--sm" onclick="saveEditLog(${id})">Save</button>
        <button class="btn btn--ghost btn--sm" onclick="refreshRecentLogs()">Cancel</button>
      </div>
    </td>`;
}

async function saveEditLog(id) {
  const date = document.getElementById("edit-date-" + id).value;
  const clinicId = document.getElementById("edit-clinic-" + id).value;
  const hours = document.getElementById("edit-hours-" + id).value;
  const income = document.getElementById("edit-income-" + id).value;
  const expense = document.getElementById("edit-expense-" + id).value;

  if (!clinicId || !date) return toast("Clinic and date required", true);

  try {
    await api(`/api/logs/${id}`, {
      method: "PUT",
      body: JSON.stringify({
        clinic_id: parseInt(clinicId),
        date,
        hours: parseFloat(hours) || 0,
        income: parseFloat(income) || 0,
        expense: parseFloat(expense) || 0,
      }),
    });
    toast("Updated");
    refreshRecentLogs();
  } catch (e) {
    toast(e.message, true);
  }
}

// ── Log View ────────────────────────────────────────────────────────────
async function refreshLogView() {
  await loadClinics();
  populateClinicSelect();
  document.getElementById("log-date").value = new Date().toISOString().slice(0, 10);
  await refreshRecentLogs();
}

let currentPage = 1;
const PER_PAGE = 20;

async function refreshRecentLogs() {
  const tbody = document.querySelector("#recent-logs tbody");
  const footer = document.getElementById("pagination-footer");
  try {
    const result = await api(`/api/logs?page=${currentPage}&per_page=${PER_PAGE}`);
    const { logs, page, total_pages, total } = result;
    logsCache = logs;

    if (logs.length === 0) {
      tbody.innerHTML = '<tr><td class="text-center muted" colspan="7">No entries yet</td></tr>';
      footer.innerHTML = "";
      return;
    }
    tbody.innerHTML = logs.map(l => {
      const hasHours = l.hours > 0;
      const rate = hasHours ? Math.round((l.income - l.expense) / l.hours) : 0;
      return `<tr id="log-row-${l.id}">
        <td class="muted nowrap">${dateLabel(l.date)}</td>
        <td>${escapeHtml(l.clinic_name)}</td>
        <td class="num">${l.hours}h</td>
        <td class="num">${money(l.income)}</td>
        <td class="num ${l.expense > 0 ? '' : 'muted'}">${l.expense > 0 ? '−' + money(l.expense) : '—'}</td>
        <td class="num ${hasHours ? rateClass(rate) : 'muted'}">${hasHours ? rateText(rate) : '—'}</td>
        <td>
          <div class="row-actions">
            <button class="btn btn--ghost btn--sm btn--icon" onclick="editLog(${l.id})" aria-label="Edit entry">${ICON_EDIT}</button>
            <button class="btn btn--danger btn--sm btn--icon" onclick="confirmDeleteLog(${l.id})" aria-label="Delete entry">${ICON_TRASH}</button>
          </div>
        </td>
      </tr>`;
    }).join("");

    footer.innerHTML = `
      <div class="pager">
        <button class="btn btn--ghost btn--sm" onclick="goToPage(${page - 1})" ${page <= 1 ? 'disabled' : ''}>← Prev</button>
        <span class="pager-info">Page ${page} of ${total_pages} · ${total} entries</span>
        <button class="btn btn--ghost btn--sm" onclick="goToPage(${page + 1})" ${page >= total_pages ? 'disabled' : ''}>Next →</button>
      </div>`;
  } catch (e) {
    toast(e.message, true);
  }
}

function goToPage(p) {
  currentPage = p;
  refreshRecentLogs();
}

async function submitLog() {
  const clinicId = document.getElementById("log-clinic").value;
  const date = document.getElementById("log-date").value;
  const hours = document.getElementById("log-hours").value;
  const income = document.getElementById("log-income").value;
  const expense = document.getElementById("log-expense").value || 0;

  if (!clinicId || !date) {
    return toast("Fill all required fields (clinic, date)", true);
  }

  const incomeVal = parseFloat(income) || 0;
  const expenseVal = parseFloat(expense) || 0;
  const hoursVal = parseFloat(hours) || 0;
  if (incomeVal === 0 && expenseVal === 0) {
    return toast("Enter income or expense", true);
  }
  if (incomeVal > 0 && hoursVal === 0) {
    return toast("Hours required when logging income", true);
  }

  try {
    await api("/api/logs", {
      method: "POST",
      body: JSON.stringify({
        clinic_id: parseInt(clinicId),
        date,
        hours: hoursVal,
        income: incomeVal,
        expense: expenseVal,
      }),
    });
    // Clear form
    document.getElementById("log-date").value = new Date().toISOString().split("T")[0];
    document.getElementById("log-hours").value = "";
    document.getElementById("log-income").value = "";
    document.getElementById("log-expense").value = "";
    const net = incomeVal - expenseVal;
    const rate = hoursVal > 0 ? ` (${rateText(net / hoursVal)})` : "";
    toast(`Saved — net ${money(net)}${rate}`);
    currentPage = 1;
    await refreshRecentLogs();
  } catch (e) {
    toast(e.message, true);
  }
}

// ── Trends View (merged Rate + Net Income) ──────────────────────────────
function getActivePeriod() {
  const btn = document.querySelector("#ranking-period-toggle button.active");
  return btn ? btn.dataset.period : "weekly";
}

function getActiveMetric() {
  const btn = document.querySelector("[data-trends-metric].active");
  return btn ? btn.dataset.trendsMetric : "rate";
}

function rateClass(rate) {
  if (rate >= 2000) return "rate-good";
  if (rate >= 1000) return "rate-mid";
  return "rate-bad";
}

async function refreshTrends() {
  const period = getActivePeriod();
  const metric = getActiveMetric();
  const periodLabels = { weekly: "week", monthly: "month", quarterly: "quarter", semiyearly: "half-year" };
  const periodLabel = periodLabels[period] || "week";

  const isRate = metric === "rate";
  document.getElementById("trends-title").textContent = isRate ? "Hourly Rate Trends" : "Net Income Trends";
  document.getElementById("trends-subtitle").textContent = `Grouped by ${periodLabel}`;

  try {
    const data = await api(`/api/reports/ranking?period=${period}`);

    const tbody = document.querySelector("#trends-table tbody");
    const labelEl = document.getElementById("trends-period-label");

    if (data.length === 0) {
      tbody.innerHTML = '<tr><td class="text-center muted" colspan="5">No data yet — log some work hours first</td></tr>';
      labelEl.textContent = "";
    } else {
      const periods = [...new Set(data.map(d => d.period))].sort().reverse();
      const latestPeriod = periods[0];

      if (period === "weekly") {
        labelEl.textContent = `Week of ${latestPeriod}`;
      } else {
        labelEl.textContent = `${latestPeriod}`;
      }

      const latest = data.filter(d => d.period === latestPeriod);
      let ranked;
      if (isRate) {
        ranked = latest.sort((a, b) => b.hourly_rate - a.hourly_rate);
      } else {
        ranked = latest.sort((a, b) => (b.net_income || 0) - (a.net_income || 0));
      }
      tbody.innerHTML = ranked.map((d, i) => {
        const value = isRate ? d.hourly_rate : (d.net_income || 0);
        const valueStr = isRate ? rateText(d.hourly_rate) : money(value);
        return `<tr>
          <td class="rank">${i + 1}</td>
          <td>${escapeHtml(d.clinic_name)}</td>
          <td class="num">${d.total_hours.toFixed(1)}h</td>
          <td class="num">${valueStr}</td>
          <td class="num ${rateClass(d.hourly_rate)}">${rateText(d.hourly_rate)}</td>
        </tr>`;
      }).join("");
    }

    // Chart (Chart.js is fetched on first use)
    await ensureChartJs();
    if (trendsChart) trendsChart.destroy();
    const ctx = document.getElementById("trends-chart").getContext("2d");
    const allClinics = [...new Set(data.map(d => d.clinic_name))];
    const allPeriods = [...new Set(data.map(d => d.period))].sort().slice(-12);
    const datasets = allClinics.map(name => {
      const clinicColor = data.find(d => d.clinic_name === name)?.color || "#38bdf8";
      return {
        label: name,
        data: allPeriods.map(p => {
          const entry = data.find(d => d.clinic_name === name && d.period === p);
          if (!entry) return null;
          return isRate ? entry.hourly_rate : (entry.net_income || 0);
        }),
        borderColor: clinicColor,
        backgroundColor: clinicColor + "20",
        tension: 0.3, spanGaps: true,
      };
    });
    trendsChart = new Chart(ctx, {
      type: "line", data: { labels: allPeriods, datasets },
      options: {
        responsive: true, maintainAspectRatio: false,
        plugins: { legend: { labels: { color: "#94a3b8", boxWidth: 12, padding: 12 } } },
        scales: {
          x: { ticks: { color: "#64748b", maxTicksLimit: 12 }, grid: { color: "rgba(255,255,255,0.06)" } },
          y: { ticks: { color: "#64748b", callback: v => "฿" + v.toLocaleString() }, grid: { color: "rgba(255,255,255,0.06)" } },
        },
      },
    });
  } catch (e) {
    toast(e.message, true);
  }
}

// ── Income Report ──────────────────────────────────────────────────────
function setDefaultDates() {
  const now = new Date();
  const yyyy = now.getFullYear();
  const mm = String(now.getMonth() + 1).padStart(2, '0');
  const dd = String(now.getDate()).padStart(2, '0');
  document.getElementById("income-end").value = `${yyyy}-${mm}-${dd}`;
  document.getElementById("income-start").value = `${yyyy}-${mm}-01`;
  refreshIncomeRanking();
}

async function refreshIncomeRanking() {
  const start = document.getElementById("income-start").value;
  const end = document.getElementById("income-end").value;
  if (!start || !end) return;

  const tbody = document.querySelector("#income-ranking-table tbody");
  try {
    const result = await api(`/api/reports/income-ranking?start=${start}&end=${end}`);
    const { rankings } = result;

    if (rankings.length === 0) {
      tbody.innerHTML = '<tr><td class="text-center muted" colspan="7">No data in this date range</td></tr>';
      return;
    }
    tbody.innerHTML = rankings.map((d, i) =>
      `<tr>
        <td class="rank">${i + 1}</td>
        <td>${escapeHtml(d.clinic_name)}</td>
        <td class="num">${d.total_hours.toFixed(1)}h</td>
        <td class="num">${money(d.total_income)}</td>
        <td class="num ${d.total_expense > 0 ? '' : 'muted'}">${d.total_expense > 0 ? '−' + money(d.total_expense) : '—'}</td>
        <td class="num rate-good">${money(d.net_income)}</td>
        <td class="num ${rateClass(d.hourly_rate)}">${rateText(d.hourly_rate)}</td>
      </tr>`
    ).join("");
  } catch (e) {
    toast(e.message, true);
  }
}


// ── Monthly Summary (bar chart + line) ──────────────────────────────────
function populateYearSelector() {
  const sel = document.getElementById("monthly-year");
  const now = new Date();
  const currentYear = now.getFullYear();
  let html = "";
  for (let y = currentYear; y >= currentYear - 9; y--) {
    html += `<option value="${y}" ${y === currentYear ? "selected" : ""}>${y}</option>`;
  }
  sel.innerHTML = html;
}

async function refreshMonthly() {
  const sel = document.getElementById("monthly-year");
  if (sel.options.length === 0) populateYearSelector();
  const year = sel.value || new Date().getFullYear();

  try {
    const data = await api(`/api/reports/monthly-summary?year=${year}`);
    const months = data.months;

    let totalIncome = 0, totalExpense = 0, totalNet = 0, totalHours = 0;
    months.forEach(m => {
      totalIncome += m.income;
      totalExpense += m.expense;
      totalNet += m.net;
      totalHours += m.hours || 0;
    });
    document.getElementById("monthly-totals").innerHTML =
      `Hours: ${totalHours} &nbsp;|&nbsp; Total income: ฿${totalIncome.toLocaleString()} &nbsp;|&nbsp; Expenses: ฿${totalExpense.toLocaleString()} &nbsp;|&nbsp; Net: <strong>฿${totalNet.toLocaleString()}</strong>`;

    const labels = months.map(m => m.label);
    const incomeData = months.map(m => m.income);
    const expenseData = months.map(m => m.expense);
    const netData = months.map(m => m.net);
    const hoursData = months.map(m => m.hours || 0);

    await ensureChartJs();
    if (monthlyChart) monthlyChart.destroy();
    const ctx = document.getElementById("monthly-chart").getContext("2d");
    monthlyChart = new Chart(ctx, {
      type: "bar",
      data: {
        labels,
        datasets: [
          {
            label: "Income",
            data: incomeData,
            backgroundColor: "#4ade80cc",
            borderColor: "#4ade80",
            borderWidth: 1,
            borderRadius: 3,
            order: 1,
          },
          {
            label: "Expense",
            data: expenseData,
            backgroundColor: "#f87171cc",
            borderColor: "#f87171",
            borderWidth: 1,
            borderRadius: 3,
            order: 1,
          },
          {
            label: "Net",
            data: netData,
            type: "line",
            borderColor: "#38bdf8",
            backgroundColor: "transparent",
            borderWidth: 2.5,
            pointRadius: 4,
            pointBackgroundColor: "#38bdf8",
            tension: 0.3,
            order: 0,
          },
          {
            label: "Hours",
            data: hoursData,
            type: "line",
            borderColor: "#c084fc",
            backgroundColor: "transparent",
            borderWidth: 2,
            borderDash: [5, 5],
            pointRadius: 3,
            pointBackgroundColor: "#c084fc",
            tension: 0.3,
            yAxisID: "y-hours",
            order: 0,
          },
        ],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        interaction: { mode: "index", intersect: false },
        plugins: {
          legend: { labels: { color: "#94a3b8", boxWidth: 12, padding: 12 } },
          tooltip: {
            callbacks: {
              label: ctx => ctx.dataset.label === "Hours"
                ? `${ctx.dataset.label}: ${ctx.raw.toFixed(0)}h`
                : `${ctx.dataset.label}: ฿${ctx.raw.toLocaleString()}`,
            },
          },
        },
        scales: {
          x: {
            ticks: { color: "#64748b" },
            grid: { color: "rgba(255,255,255,0.06)" },
          },
          y: {
            ticks: { color: "#64748b", callback: v => "฿" + v.toLocaleString() },
            grid: { color: "rgba(255,255,255,0.06)" },
          },
          "y-hours": {
            type: "linear",
            position: "right",
            title: { display: true, text: "Hours", color: "#c084fc" },
            ticks: { color: "#c084fc", stepSize: 10 },
            grid: { drawOnChartArea: false },
          },
        },
      },
    });
  } catch (e) {
    toast(e.message, true);
  }
}


// ── Tracker (monthly calendar) ──────────────────────────────────────────
let trackerYear = new Date().getFullYear();
let trackerMonth = new Date().getMonth() + 1;

function navTrackerMonth(delta) {
  trackerMonth += delta;
  if (trackerMonth > 12) { trackerMonth = 1; trackerYear++; }
  if (trackerMonth < 1) { trackerMonth = 12; trackerYear--; }
  refreshTracker();
}

function fmtDate(y, m, d) {
  return `${y}-${String(m).padStart(2,'0')}-${String(d).padStart(2,'0')}`;
}

async function refreshTracker() {
  const monthNames = ["January","February","March","April","May","June","July","August","September","October","November","December"];
  document.getElementById("tracker-month-label").textContent = `${monthNames[trackerMonth-1]} ${trackerYear}`;

  try {
    const [wlData, evData] = await Promise.all([
      api(`/api/tracker/worklogs?year=${trackerYear}&month=${trackerMonth}`),
      api(`/api/tracker/events?year=${trackerYear}&month=${trackerMonth}`).catch(() => ({events:[]})),
    ]);

    const dayMap = {};
    wlData.days.forEach(d => { dayMap[d.date] = d; });
    const evMap = {};
    if (evData.events) evData.events.forEach(e => { evMap[e.date] = (evMap[e.date]||[]).concat(e); });

    const today = new Date();
    const todayStr = fmtDate(today.getFullYear(), today.getMonth()+1, today.getDate());

    // Build 6-week grid starting from Sunday of the week containing day 1
    const firstDow = wlData.first_weekday === 6 ? 0 : wlData.first_weekday + 1;
    const startOffset = -firstDow;

    const cal = document.getElementById("tracker-calendar");

    // Weekday headers: single letters
    let html = ["S","M","T","W","T","F","S"].map((h,i) => {
      const isTodayDow = i === today.getDay();
      return `<div class="cal-head${isTodayDow ? " is-today" : ""}">${h}</div>`;
    }).join("");

    for (let week = 0; week < 6; week++) {
      for (let dow = 0; dow < 7; dow++) {
        const offset = startOffset + week * 7 + dow;
        const cellDate = new Date(trackerYear, trackerMonth - 1, 1 + offset);
        const dayNum = cellDate.getDate();
        const cellMonth = cellDate.getMonth() + 1;
        const cellYear = cellDate.getFullYear();
        const dateStr = fmtDate(cellYear, cellMonth, dayNum);
        const isCurrentMonth = cellMonth === trackerMonth && cellYear === trackerYear;
        const isToday = dateStr === todayStr;

        const d = dayMap[dateStr];
        const evs = evMap[dateStr] || [];

        // Out-of-month days are dimmer via a text colour. Never dim the whole
        // cell with opacity: that pushes every child below WCAG AA contrast.
        const cellClass = ["cal-cell",
          isCurrentMonth ? "" : "is-outside",
          isToday ? "is-today" : ""].filter(Boolean).join(" ");

        let content = `<div class="cal-day">${dayNum}</div>`;

        if (d && d.total > 0) {
          const dots = d.clinics.map(c =>
            `<span class="cal-dot" style="background:${c.color}" title="${escapeHtml(c.clinic_name)}: ${c.count}"></span>`
          ).join("");
          content += `<div class="cal-count"><span class="cal-dots">${dots}</span>${d.total}</div>`;
        }
        if (evs.length > 0) {
          evs.slice(0,3).forEach((e,i) => {
            content += `<div class="cal-event cal-event--${i % 4}" title="${escapeHtml(e.summary)}">${escapeHtml(e.summary)}</div>`;
          });
          if (evs.length > 3) content += `<div class="cal-more">+${evs.length - 3} more</div>`;
        }
        html += `<div class="${cellClass}">${content}</div>`;
      }
    }

    cal.innerHTML = html;
  } catch (e) {
    toast(e.message, true);
  }
}


// ── Init ────────────────────────────────────────────────────────────────
checkAuth();