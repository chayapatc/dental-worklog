// Dental Worklog — Frontend Logic (Pico CSS + auth)

let clinicsCache = [];
let logsCache = [];
let trendsChart = null;
let monthlyChart = null;
let currentUser = null;

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
    `<span onclick="selectColor('${c}')" style="
      display:inline-block;width:22px;height:22px;border-radius:50%;
      background:${c};cursor:pointer;border:2px solid ${c === currentColor ? '#fff' : 'transparent'};
      transition:border 0.15s;
    " title="${c}"></span>`
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
      refreshLogView();
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
    if (data.bound) {
      badge.style.display = "";
      badge.title = "LINE connected";
    } else {
      badge.style.display = "none";
    }
  } catch {}
}

function logout() {
  window.location.href = "/auth/logout";
}

// ── Navigation ──────────────────────────────────────────────────────────
function switchTab(view) {
  document.querySelectorAll("nav [data-view], .bottom-nav [data-view]").forEach(b => b.classList.remove("active"));
  document.querySelectorAll(".view").forEach(v => v.classList.remove("active"));
  document.getElementById("view-" + view).classList.add("active");
  // Mark active on both top nav and bottom nav
  document.querySelectorAll(`[data-view="${view}"]`).forEach(el => el.classList.add("active"));
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

document.getElementById("menu-toggle").addEventListener("click", () => {
  document.getElementById("main-nav").classList.toggle("mobile-open");
});

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
  el.className = "toast show" + (isError ? " error" : "");
  clearTimeout(el._timer);
  el._timer = setTimeout(() => el.classList.remove("show"), 2500);
}

// ── Load Clinics Cache ─────────────────────────────────────────────────
async function loadClinics() {
  clinicsCache = await api("/api/clinics");
  return clinicsCache;
}

function populateClinicSelect() {
  const sel = document.getElementById("log-clinic");
  sel.innerHTML = '<option value="">-- Select --</option>';
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
    tbody.innerHTML = '<tr><td class="text-center" colspan="3">No clinics yet</td></tr>';
    return;
  }
  tbody.innerHTML = clinicsCache.map(c => {
    const dot = `<span style="display:inline-block;width:12px;height:12px;border-radius:50%;background:${c.color};margin-right:0.5rem;vertical-align:middle;"></span>`;
    if (editingClinicId === c.id) {
      return `<tr>
        <td>
          <input type="text" id="edit-name-${c.id}" value="${escapeHtml(c.name)}" style="width:100%;margin-bottom:0.3rem;">
          <div class="edit-swatches-${c.id}" style="display:flex;gap:0.2rem;align-items:center;">${buildColorSwatchesForEdit(c.id, c.color)}</div>
          <input type="color" id="edit-color-picker-${c.id}" value="${c.color}" onchange="selectEditCustomColor(${c.id}, this.value)" style="width:28px;height:28px;padding:0;border:none;cursor:pointer;margin-top:0.2rem;" title="Custom color">
        </td>
        <td style="text-align:right;white-space:nowrap;">
          <button class="outline secondary" style="padding:0.2rem 0.5rem;font-size:0.75rem;" onclick="saveEdit(${c.id})">Save</button>
          <button class="outline contrast" style="padding:0.2rem 0.5rem;font-size:0.75rem;" onclick="cancelEdit()">✕</button>
        </td>
      </tr>`;
    }
    return `<tr>
      <td>${dot}${escapeHtml(c.name)}</td>
      <td style="text-align:right;white-space:nowrap;">
        <button class="outline secondary" style="padding:0.2rem 0.5rem;font-size:0.75rem;" onclick="startEdit(${c.id})">Edit</button>
        <button class="outline contrast" style="padding:0.2rem 0.5rem;font-size:0.75rem;" onclick="confirmDelete(${c.id})">Delete</button>
      </td>
    </tr>`;
  }).join("");
}

let editingColor = null;

function buildColorSwatchesForEdit(clinicId, currentColor) {
  return COLOR_PRESETS.map(c =>
    `<span onclick="selectEditColor(${clinicId}, '${c}')" style="
      display:inline-block;width:20px;height:20px;border-radius:50%;
      background:${c};cursor:pointer;border:2px solid ${c === currentColor ? '#fff' : 'transparent'};
      transition:border 0.15s;
    " title="${c}"></span>`
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
      tbody.innerHTML = '<tr><td class="text-center" colspan="7">No entries yet</td></tr>';
      footer.innerHTML = "";
      return;
    }
    tbody.innerHTML = logs.map(l =>
      `<tr>
        <td>${l.date}</td>
        <td>${escapeHtml(l.clinic_name)}</td>
        <td>${l.hours}h</td>
        <td style="text-align:right">฿${l.income.toLocaleString()}</td>
        <td style="text-align:right">${l.expense > 0 ? '-฿' + l.expense.toLocaleString() : '-'}</td>
        <td style="text-align:right" class="${l.hours > 0 ? 'rate-good' : ''}">${l.hours > 0 ? '฿' + Math.round((l.income - l.expense)/l.hours) + '/h' : '-'}</td>
        <td style="text-align:center;">
          <button class="outline contrast" style="padding:0.1rem 0.4rem;font-size:0.7rem;" onclick="confirmDeleteLog(${l.id})" title="Delete">✕</button>
        </td>
      </tr>`
    ).join("");

    footer.innerHTML = `
      <div style="display:flex;align-items:center;justify-content:center;gap:0.75rem;padding:0.75rem 0;">
        <button class="outline secondary" style="padding:0.2rem 0.75rem;font-size:0.8rem;" onclick="goToPage(${page - 1})" ${page <= 1 ? 'disabled' : ''}>← Prev</button>
        <span style="font-size:0.8rem;color:var(--pico-muted-color);">Page ${page} of ${total_pages} (${total} entries)</span>
        <button class="outline secondary" style="padding:0.2rem 0.75rem;font-size:0.8rem;" onclick="goToPage(${page + 1})" ${page >= total_pages ? 'disabled' : ''}>Next →</button>
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
    const rate = hoursVal > 0 ? ` (฿${Math.round(net / hoursVal)}/h)` : "";
    toast(`Saved! Net: ฿${Math.round(net)}${rate}`);
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
      tbody.innerHTML = '<tr><td class="text-center" colspan="5">No data yet — log some work hours first</td></tr>';
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
        const valueStr = isRate
          ? `฿${d.hourly_rate}/h`
          : `฿${value.toLocaleString()}`;
        return `<tr>
          <td class="rank">#${i + 1}</td>
          <td>${escapeHtml(d.clinic_name)}</td>
          <td>${d.total_hours.toFixed(1)}h</td>
          <td style="text-align:right">${valueStr}</td>
          <td style="text-align:right" class="${rateClass(d.hourly_rate)}">฿${d.hourly_rate}/h</td>
        </tr>`;
      }).join("");
    }

    // Chart
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
      tbody.innerHTML = '<tr><td class="text-center" colspan="7">No data in this date range</td></tr>';
      return;
    }
    tbody.innerHTML = rankings.map((d, i) =>
      `<tr>
        <td class="rank">#${i + 1}</td>
        <td>${escapeHtml(d.clinic_name)}</td>
        <td>${d.total_hours.toFixed(1)}h</td>
        <td style="text-align:right">฿${d.total_income.toLocaleString()}</td>
        <td style="text-align:right">${d.total_expense > 0 ? '-฿' + d.total_expense.toLocaleString() : '-'}</td>
        <td style="text-align:right" class="rate-good">฿${d.net_income.toLocaleString()}</td>
        <td style="text-align:right" class="${rateClass(d.hourly_rate)}">฿${d.hourly_rate}/h</td>
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

    let totalIncome = 0, totalExpense = 0, totalNet = 0;
    months.forEach(m => {
      totalIncome += m.income;
      totalExpense += m.expense;
      totalNet += m.net;
    });
    document.getElementById("monthly-totals").innerHTML =
      `Total income: ฿${totalIncome.toLocaleString()} &nbsp;|&nbsp; Expenses: ฿${totalExpense.toLocaleString()} &nbsp;|&nbsp; Net: <strong>฿${totalNet.toLocaleString()}</strong>`;

    const labels = months.map(m => m.label);
    const incomeData = months.map(m => m.income);
    const expenseData = months.map(m => m.expense);
    const netData = months.map(m => m.net);

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
              label: ctx => `${ctx.dataset.label}: ฿${ctx.raw.toLocaleString()}`,
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
    cal.style.gridTemplateColumns = "repeat(7,1fr)";

    // Weekday headers: single letters
    let html = ["S","M","T","W","T","F","S"].map((h,i) => {
      const isToday = i === today.getDay();
      return `<div style="padding:6px 2px;font-size:0.7rem;font-weight:600;text-align:center;color:${isToday?'var(--pico-primary-background)':'var(--pico-muted-color)'};">${h}</div>`;
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

        let cellStyle = "min-height:52px;padding:3px 4px;background:var(--pico-card-background-color);border:1px solid var(--pico-card-border-color);overflow:hidden;";
        if (!isCurrentMonth) cellStyle += "opacity:0.35;";
        if (isToday) cellStyle += "box-shadow:inset 0 0 0 2px var(--pico-primary-background);";

        let content = `<div style="font-size:0.7rem;font-weight:${isToday?'700':'400'};color:${isCurrentMonth?'var(--pico-color)':'var(--pico-muted-color)'};margin-bottom:2px;">${dayNum}</div>`;

        if (d && d.total > 0) {
          const dots = d.clinics.map(c =>
            `<span style="display:inline-block;width:6px;height:6px;border-radius:50%;background:${c.color};margin:0 1px;" title="${escapeHtml(c.clinic_name)}: ${c.count}"></span>`
          ).join("");
          content += `<div style="display:flex;align-items:center;gap:2px;margin-bottom:1px;">${dots}<span style="font-weight:700;font-size:0.6rem;color:var(--pico-primary-background);">${d.total}</span></div>`;
        }
        if (evs.length > 0) {
          content += `<div style="margin-top:2px;">`;
          evs.slice(0,3).forEach((e,i) => {
            const colors = ["#f87171","#4ade80","#38bdf8","#a78bfa"];
            content += `<div style="font-size:0.6rem;line-height:1.25;padding-left:4px;border-left:2px solid ${colors[i%colors.length]};margin-bottom:1px;word-break:break-word;" title="${escapeHtml(e.summary)}">${escapeHtml(e.summary)}</div>`;
          });
          if (evs.length > 3) content += `<div style="font-size:0.55rem;color:var(--pico-muted-color);padding-left:4px;">+${evs.length-3}</div>`;
          content += `</div>`;
        }
        html += `<div style="${cellStyle}">${content}</div>`;
      }
    }

    cal.innerHTML = html;
  } catch (e) {
    toast(e.message, true);
  }
}


// ── Init ────────────────────────────────────────────────────────────────
checkAuth();