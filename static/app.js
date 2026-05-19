// Dental Worklog — Frontend Logic (Pico CSS + auth)

let clinicsCache = [];
let rankingChart = null;
let currentUser = null;

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
  document.getElementById("color-swatches").innerHTML = buildColorSwatches(color);
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
  if (currentUser.avatar_url) {
    av.src = currentUser.avatar_url;
    av.style.display = "";
  } else {
    av.style.display = "none";
  }
  // Initialize color swatches on add clinic form
  document.getElementById("color-swatches").innerHTML = buildColorSwatches(COLOR_PRESETS[0]);
}

function logout() {
  window.location.href = "/auth/logout";
}

// ── Navigation ──────────────────────────────────────────────────────────
document.querySelectorAll("nav [data-view]").forEach(link => {
  link.addEventListener("click", (e) => {
    e.preventDefault();
    document.querySelectorAll("nav [data-view]").forEach(b => b.classList.remove("active"));
    link.classList.add("active");
    document.querySelectorAll(".view").forEach(v => v.classList.remove("active"));
    document.getElementById("view-" + link.dataset.view).classList.add("active");
    if (link.dataset.view === "log") refreshLogView();
    if (link.dataset.view === "clinics") refreshClinics();
    if (link.dataset.view === "ranking") refreshRanking();
  });
});

// ── Period Toggles ─────────────────────────────────────────────────────
document.querySelectorAll(".toggle-group button").forEach(btn => {
  btn.addEventListener("click", () => {
    const group = btn.parentElement;
    group.querySelectorAll("button").forEach(b => b.classList.remove("active"));
    btn.classList.add("active");

    // View toggle (Hourly Rate / Net Income)
    if (btn.dataset.rankingView) {
      const isIncome = btn.dataset.rankingView === "income";
      document.getElementById("ranking-rate-view").classList.toggle("hidden", isIncome);
      document.getElementById("ranking-income-view").classList.toggle("hidden", !isIncome);
      if (isIncome) setDefaultDates();
      return;
    }

    // Period toggle (1W/1M/3M/6M)
    const section = group.closest("section");
    if (section && section.id === "view-ranking") refreshRanking();
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
    sel.innerHTML += `<option value="${c.id}">${c.name}</option>`;
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
          <input type="text" id="edit-name-${c.id}" value="${c.name.replace(/"/g, '&quot;')}" style="width:100%;margin-bottom:0.3rem;">
          <div class="edit-swatches-${c.id}" style="display:flex;gap:0.2rem;">${buildColorSwatchesForEdit(c.id, c.color)}</div>
        </td>
        <td style="text-align:right;white-space:nowrap;">
          <button class="outline secondary" style="padding:0.2rem 0.5rem;font-size:0.75rem;" onclick="saveEdit(${c.id})">Save</button>
          <button class="outline contrast" style="padding:0.2rem 0.5rem;font-size:0.75rem;" onclick="cancelEdit()">✕</button>
        </td>
      </tr>`;
    }
    return `<tr>
      <td>${dot}${c.name}</td>
      <td style="text-align:right;white-space:nowrap;">
        <button class="outline secondary" style="padding:0.2rem 0.5rem;font-size:0.75rem;" onclick="startEdit(${c.id}, '${c.name.replace(/'/g, "\\'")}', '${c.color}')">Edit</button>
        <button class="outline contrast" style="padding:0.2rem 0.5rem;font-size:0.75rem;" onclick="confirmDelete(${c.id}, '${c.name.replace(/'/g, "\\'")}')">Delete</button>
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
  document.querySelector(`.edit-swatches-${clinicId}`).innerHTML = buildColorSwatchesForEdit(clinicId, color);
}

function startEdit(id, name, color) {
  editingClinicId = id;
  editingColor = color;
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

function confirmDelete(id, name) {
  pendingDeleteId = id;
  pendingDeleteType = "clinic";
  document.getElementById("confirm-title").textContent = "Delete Clinic";
  document.getElementById("confirm-message").textContent = `Delete "${name}"? This won't affect existing work logs.`;
  document.getElementById("confirm-btn").textContent = "Delete";
  document.getElementById("confirm-dialog").showModal();
}

function confirmDeleteLog(id, date, clinic) {
  pendingDeleteId = id;
  pendingDeleteType = "log";
  document.getElementById("confirm-title").textContent = "Delete Log Entry";
  document.getElementById("confirm-message").textContent = `Delete entry: ${date} at ${clinic}? This cannot be undone.`;
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

    if (logs.length === 0) {
      tbody.innerHTML = '<tr><td class="text-center" colspan="7">No entries yet</td></tr>';
      footer.innerHTML = "";
      return;
    }
    tbody.innerHTML = logs.map(l =>
      `<tr>
        <td>${l.date}</td>
        <td>${l.clinic_name}</td>
        <td>${l.hours}h</td>
        <td style="text-align:right">฿${l.income.toLocaleString()}</td>
        <td style="text-align:right">${l.expense > 0 ? '-฿' + l.expense.toLocaleString() : '-'}</td>
        <td style="text-align:right" class="rate-good">฿${Math.round((l.income - l.expense)/l.hours)}/h</td>
        <td style="text-align:center;">
          <button class="outline contrast" style="padding:0.1rem 0.4rem;font-size:0.7rem;" onclick="confirmDeleteLog(${l.id}, '${l.date}', '${l.clinic_name.replace(/'/g, "\\'")}')" title="Delete">✕</button>
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

  if (!clinicId || !date || !hours || !income) {
    return toast("Fill all fields", true);
  }

  try {
    await api("/api/logs", {
      method: "POST",
      body: JSON.stringify({
        clinic_id: parseInt(clinicId),
        date,
        hours: parseFloat(hours),
        income: parseFloat(income),
        expense: parseFloat(expense),
      }),
    });
    document.getElementById("log-hours").value = "";
    document.getElementById("log-income").value = "";
    toast("Work log saved!");
    currentPage = 1;
    await refreshRecentLogs();
  } catch (e) {
    toast(e.message, true);
  }
}

// ── Ranking View ───────────────────────────────────────────────────────
function getActivePeriod(sectionId) {
  const btn = document.querySelector("#" + sectionId + " .toggle-group button.active");
  return btn ? btn.dataset.period : "weekly";
}

function rateClass(rate) {
  if (rate >= 2000) return "rate-good";
  if (rate >= 1000) return "rate-mid";
  return "rate-bad";
}

async function refreshRanking() {
  const period = getActivePeriod("view-ranking");
  const periodLabels = { weekly: "week", monthly: "month", quarterly: "quarter", semiyearly: "half-year" };
  const periodLabel = periodLabels[period] || "week";
  document.getElementById("ranking-title").textContent = "Ranking by Avg Hourly Rate";
  document.getElementById("ranking-subtitle").textContent = `Grouped by ${periodLabel}`;

  try {
    const data = await api(`/api/reports/ranking?period=${period}`);

    const tbody = document.querySelector("#ranking-table tbody");
    const labelEl = document.getElementById("ranking-period-label");

    if (data.length === 0) {
      tbody.innerHTML = '<tr><td class="text-center" colspan="5">No data yet — log some work hours first</td></tr>';
      labelEl.textContent = "";
    } else {
      const periods = [...new Set(data.map(d => d.period))].sort().reverse();
      const latestPeriod = periods[0];

      // Format the period label
      if (period === "weekly") {
        labelEl.textContent = `Week of ${latestPeriod}`;
      } else if (period === "quarterly" || period === "semiyearly") {
        labelEl.textContent = `${latestPeriod}`;
      } else {
        labelEl.textContent = `${latestPeriod}`;
      }

      const latest = data.filter(d => d.period === latestPeriod);
      const ranked = latest.sort((a, b) => b.hourly_rate - a.hourly_rate);
      tbody.innerHTML = ranked.map((d, i) => {
        const net = d.total_income - (d.total_expense || 0);
        return `<tr>
          <td class="rank">#${i + 1}</td>
          <td>${d.clinic_name}</td>
          <td>${d.total_hours.toFixed(1)}h</td>
          <td style="text-align:right">฿${net.toLocaleString()}</td>
          <td style="text-align:right" class="${rateClass(d.hourly_rate)}">฿${d.hourly_rate}/h</td>
        </tr>`;
      }).join("");
    }

    // Chart
    if (rankingChart) rankingChart.destroy();
    const ctx = document.getElementById("ranking-chart").getContext("2d");
    const allClinics = [...new Set(data.map(d => d.clinic_name))];
    const allPeriods = [...new Set(data.map(d => d.period))].sort().slice(-12);
    const datasets = allClinics.map(name => {
      const clinicColor = data.find(d => d.clinic_name === name)?.color || "#38bdf8";
      return {
        label: name,
        data: allPeriods.map(p => {
          const entry = data.find(d => d.clinic_name === name && d.period === p);
          return entry ? entry.hourly_rate : null;
        }),
        borderColor: clinicColor,
        backgroundColor: clinicColor + "20",
        tension: 0.3, spanGaps: true,
      };
    });
    rankingChart = new Chart(ctx, {
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

// ── Income Ranking ──────────────────────────────────────────────────────
function setDefaultDates() {
  // Use local date (not UTC) to respect user's timezone
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
        <td>${d.clinic_name}</td>
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

// ── Init ────────────────────────────────────────────────────────────────
checkAuth();
