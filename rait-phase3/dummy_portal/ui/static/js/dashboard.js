/* Dashboard: poll /api/dimensions/summary every 10s and update cards in-place.
   Cards are identified by data-dimension-id so adding DB rows adds cards on next full reload.
   Records table is also refreshed each tick. */

const POLL_INTERVAL_MS = 10_000;

function scoreToPercent(score) {
  // Scores from Azure AI evaluators are 0–5; stub scores may also be 0–5 or 0–1.
  // Normalise to 0–100% assuming max scale of 5.
  return Math.min(100, Math.round((score / 5) * 100 * 10) / 10);
}

function updateCard(dim) {
  const card = document.querySelector(`[data-dimension-id="${dim.dimension_id}"]`);
  if (!card) return;

  const scoreEl  = card.querySelector(".card-score");
  const badgeEl  = card.querySelector(".badge");
  const sampleEl = card.querySelector(".card-samples");

  if (scoreEl)  scoreEl.textContent = scoreToPercent(dim.avg_score) + "%";
  if (sampleEl) sampleEl.textContent = `${dim.sample_count} sample${dim.sample_count !== 1 ? "s" : ""}`;

  if (badgeEl) {
    const safe = dim.is_safe;
    badgeEl.textContent  = safe ? "Safe" : "Unsafe";
    badgeEl.className    = "badge " + (safe ? "safe" : "unsafe");
    badgeEl.setAttribute("aria-label", safe ? "Safe" : "Unsafe");
  }

  card.className = "dimension-card " + (dim.is_safe ? "safe" : "unsafe");
}

async function refreshDimensions() {
  try {
    const resp = await fetch("/api/dimensions/summary");
    if (!resp.ok) return;
    const data = await resp.json();
    data.dimensions.forEach(updateCard);
  } catch (_) { /* network error — silent, will retry */ }
}

async function refreshRecords() {
  try {
    const resp = await fetch("/api/records?limit=20");
    if (!resp.ok) return;
    const data = await resp.json();
    const tbody = document.getElementById("records-tbody");
    if (!tbody) return;

    tbody.innerHTML = data.items.map(r => `
      <tr>
        <td><a href="/records/${r.record_id}">#${r.record_id}</a></td>
        <td>${escHtml(r.model_name)} <span style="color:#95a5a6">${escHtml(r.model_version)}</span></td>
        <td><span class="log-type-chip">${escHtml(r.log_type)}</span></td>
        <td>${escHtml(r.model_environment)}</td>
        <td>${formatTs(r.received_at)}</td>
      </tr>`
    ).join("");
  } catch (_) { /* silent */ }
}

async function refreshDashboard() {
  const status = document.getElementById("refresh-status");
  if (status) { status.textContent = "Updating…"; status.className = "updating"; }
  await Promise.all([refreshDimensions(), refreshRecords()]);
  if (status) {
    const now = new Date().toLocaleTimeString();
    status.textContent = `Last updated: ${now}`;
    status.className = "";
  }
}

function escHtml(s) {
  return String(s)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function formatTs(iso) {
  try { return new Date(iso).toLocaleString(); } catch (_) { return iso; }
}

// Boot: immediate refresh + interval
refreshDashboard();
setInterval(refreshDashboard, POLL_INTERVAL_MS);
