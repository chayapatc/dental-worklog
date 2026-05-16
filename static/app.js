// Dental Worklog — Frontend Logic (with auth)

let clinicsCache = [];
let rankingChart = null;
let trendsChart = null;
let currentUser = null;

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
  // Display user info
  document.getElementById("user-name").textContent = currentUser.name;
  const av = document.getElementById("user-avatar");
  if (currentUser.avatar_url) {
    av.src = currentUser.avatar_url;
    av.style.display = "";
  } else {
    av.style.display = "none";
  }
}

function logout() {
  window.location.href = "/auth/logout";
}

// ── Navigation ──────────────────────────────────────────────────────────
document.querySelectorAll("nav button").forEach(btn => {
  btn.addEventListener("click", () => {
    document.querySelectorAll("nav button").forEach(b => b.classList.remove("active"));
    btn.classList.add("active");
    document.querySelectorAll(".view").forEach(v => v.classList.remove("active"));
    document.getElementById("view-" + btn.dataset.view).classList.add("active");
    if (btn.dataset.view === "log") refreshLogView();
    if (btn.dataset.view === "clinics") refreshClinics();
    if (btn.dataset.view === "ranking") refreshRanking();
    if (btn.dataset.view === "trends") refreshTrends();
  });
});

// ── Period Toggles ─────────────────────────────────────────────────────
document.querySelectorAll(".toggle-group button").forEach(btn => {
  btn.addEventListener("click", () => {
    const group = btn.parentElement;
    group.querySelectorAll("button").forEach(b => b.classList.remove("active"));
    btn.classList.add("active");
    if (group.id === "ranking-period-toggle") refreshRanking();
    if (group.id === "trends-period-toggle") refreshTrends();
  });
});

// ── API Helpers ─────────────────────────────────────────────────────────
async function api(url, opts = {}) {
  const res = await fetch(url, {
    headers: { "Content-Type": "application/json" },
    ...opts,
  });
  // Redirect to login if session expired
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

// ── Populate Clinic Dropdown ───────────────────────────────────────────
function populateClinicSelect() {
  const sel = document.getElementById("log-clinic");
  sel.innerHTML = '<option value="">-- Select --</option>';
  clinicsCache.forEach(c => {
    sel.innerHTML += `<option value="${c.id}">${c.name}</option>`;
  });
}

// ── Clinics View ────────────────────────────────────────────────────────
async function refreshClinics() {
  await loadClinics();
  const tbody = document.querySelector("#clinics-table tbody");
  if (clinicsCache.length === 0) {
    tbody.innerHTML = '<tr><td class="empty" colspan="2">No clinics yet — add one above</td></tr>';
    return;
  }
  tbody.innerHTML = clinicsCache.map(c =>
    `<tr><td>${c.name}</td></tr>`
  ).join("");
}

async function addClinic() {
  const input = document.getElementById("clinic-name");
  const name = input.value.trim();
  if (!name) return toast("Enter a clinic name", true);
  try {
    await api("/api/clinics", {
      method: "POST",
      body: JSON.stringify({ name }),
    });
    input.value = "";
    toast("Clinic added!");
    await refreshClinics();
    await loadClinics();
    populateClinicSelect();
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

async function refreshRecentLogs() {
  const tbody = document.querySelector("#recent-logs tbody");
  try {
    const logs = await api("/api/logs");
    if (logs.length === 0) {
      tbody.innerHTML = '<tr><td class="empty" colspan="4">No entries yet</td></tr>';
      return;
    }
    tbody.innerHTML = logs.map(l =>
      `<tr>
        <td>${l.date}</td>
        <td>${l.clinic_name}</td>
        <td>${l.hours}h</td>
        <td style="text-align:right">฿${l.income.toLocaleString()}</td>
        <td style="text-align:right" class="rate-good">฿${Math.round(l.income/l.hours)}/h</td>
      </tr>`
    ).join("");
  } catch (e) {
    toast(e.message, true);
  }
}

async function submitLog() {
  const clinicId = document.getElementById("log-clinic").value;
  const date = document.getElementById("log-date").value;
  const hours = document.getElementById("log-hours").value;
  const income = document.getElementById("log-income").value;

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
      }),
    });
    document.getElementById("log-hours").value = "";
    document.getElementById("log-income").value = "";
    toast("Work log saved!");
    await refreshRecentLogs();
  } catch (e) {
    toast(e.message, true);
  }
}

// ── Ranking View ───────────────────────────────────────────────────────
function getActivePeriod(groupId) {
  const btn = document.querySelector("#" + groupId + " button.active");
  return btn ? btn.dataset.period : "weekly";
}

function rateClass(rate) {
  if (rate >= 2000) return "rate-good";
  if (rate >= 1000) return "rate-mid";
  return "rate-bad";
}

async function refreshRanking() {
  const period = getActivePeriod("ranking-period-toggle");
  const title = document.getElementById("ranking-title");
  title.textContent = `Ranking by Avg Hourly Rate (${period})`;

  try {
    const data = await api(`/api/reports/ranking?period=${period}`);

    // Table
    const tbody = document.querySelector("#ranking-table tbody");
    if (data.length === 0) {
      tbody.innerHTML = '<tr><td class="empty" colspan="5">No data yet — log some work hours first</td></tr>';
    } else {
      const periods = [...new Set(data.map(d => d.period))].sort().reverse();
      const latestPeriod = periods[0];
      const latest = data.filter(d => d.period === latestPeriod);
      const ranked = latest.sort((a, b) => b.hourly_rate - a.hourly_rate);
      tbody.innerHTML = ranked.map((d, i) =>
        `<tr>
          <td class="rank">#${i + 1}</td>
          <td>${d.clinic_name}</td>
          <td>${d.total_hours.toFixed(1)}h</td>
          <td style="text-align:right">฿${d.total_income.toLocaleString()}</td>
          <td style="text-align:right" class="${rateClass(d.hourly_rate)}">฿${d.hourly_rate}/h</td>
        </tr>`
      ).join("");
    }

    // Chart
    if (rankingChart) rankingChart.destroy();
    const ctx = document.getElementById("ranking-chart").getContext("2d");
    const allClinics = [...new Set(data.map(d => d.clinic_name))];
    const allPeriods = [...new Set(data.map(d => d.period))].sort().slice(-12);
    const colors = ["#38bdf8","#4ade80","#fbbf24","#f87171","#a78bfa","#fb923c","#2dd4bf","#f472b6"];
    const datasets = allClinics.map((name, i) => ({
      label: name,
      data: allPeriods.map(p => {
        const entry = data.find(d => d.clinic_name === name && d.period === p);
        return entry ? entry.hourly_rate : null;
      }),
      borderColor: colors[i % colors.length],
      backgroundColor: colors[i % colors.length] + "20",
      tension: 0.3,
      spanGaps: true,
    }));
    rankingChart = new Chart(ctx, {
      type: "line",
      data: { labels: allPeriods, datasets },
      options: {
        responsive: true, maintainAspectRatio: false,
        plugins: { legend: { labels: { color: "#94a3b8", boxWidth: 12, padding: 12 } } },
        scales: {
          x: { ticks: { color: "#64748b", maxTicksLimit: 12 } },
          y: { ticks: { color: "#64748b", callback: v => "฿" + v.toLocaleString() } },
        },
      },
    });
  } catch (e) {
    toast(e.message, true);
  }
}

// ── Trends View ────────────────────────────────────────────────────────
async function refreshTrends() {
  const period = getActivePeriod("trends-period-toggle");
  try {
    const data = await api(`/api/reports/trends?period=${period}`);
    if (trendsChart) trendsChart.destroy();
    const ctx = document.getElementById("trends-chart").getContext("2d");
    const allClinics = [...new Set(data.map(d => d.clinic_name))];
    const allPeriods = [...new Set(data.map(d => d.period))].sort().slice(-12);
    const colors = ["#38bdf8","#4ade80","#fbbf24","#f87171","#a78bfa","#fb923c","#2dd4bf","#f472b6"];
    const datasets = allClinics.map((name, i) => ({
      label: name,
      data: allPeriods.map(p => {
        const entry = data.find(d => d.clinic_name === name && d.period === p);
        return entry ? entry.hourly_rate : null;
      }),
      borderColor: colors[i % colors.length],
      backgroundColor: colors[i % colors.length] + "20",
      tension: 0.3,
      spanGaps: true,
    }));
    trendsChart = new Chart(ctx, {
      type: "line",
      data: { labels: allPeriods, datasets },
      options: {
        responsive: true, maintainAspectRatio: false,
        plugins: { legend: { labels: { color: "#94a3b8", boxWidth: 12, padding: 12 } } },
        scales: {
          x: { ticks: { color: "#64748b", maxTicksLimit: 12 } },
          y: { ticks: { color: "#64748b", callback: v => "฿" + v.toLocaleString() } },
        },
      },
    });
  } catch (e) {
    toast(e.message, true);
  }
}

// ── Init ────────────────────────────────────────────────────────────────
checkAuth();
