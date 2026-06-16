/* Dashboard: poll /api/dimensions/summary every 10s and update cards in-place.
   Cards are identified by data-dimension-id so adding DB rows adds cards on next full reload.
   Records table is also refreshed each tick.
   runEvaluation() posts to /api/generate-and-evaluate and renders results inline. */

const POLL_INTERVAL_MS = 10000;

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

// ── Card update ───────────────────────────────────────────────────────────────

function updateCard(dim) {
  const card = document.querySelector(`[data-dimension-id="${dim.dimension_id}"]`);
  if (!card) return;

  const noData = dim.sample_count === 0;
  card.className = "dimension-card " + (noData ? "nodata" : (dim.is_safe ? "safe" : "unsafe"));

  const bannerEl = card.querySelector(".card-banner");
  if (bannerEl) {
    if (noData)          bannerEl.textContent = "— NO DATA YET";
    else if (dim.is_safe) bannerEl.textContent = "✓ SAFE";
    else                  bannerEl.textContent = "✗ UNSAFE";
  }

  const scoreValEl = card.querySelector(".card-score-val");
  if (scoreValEl) scoreValEl.textContent = dim.avg_score.toFixed(2) + " / 5.0";

  const scoreMinEl = card.querySelector(".card-score-minmax");
  if (scoreMinEl) scoreMinEl.textContent = "min " + dim.min_score.toFixed(2);

  const barEl = card.querySelector(".card-progress-bar");
  if (barEl) barEl.style.width = Math.min(100, (dim.avg_score / 5) * 100) + "%";

  const sampleEl = card.querySelector(".card-samples");
  if (sampleEl) sampleEl.textContent = `${dim.sample_count} sample${dim.sample_count !== 1 ? "s" : ""}`;
}

// ── Polling ───────────────────────────────────────────────────────────────────

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

    if (data.items.length === 0) {
      tbody.innerHTML = `<tr><td colspan="5" style="color:#95a5a6;text-align:center;padding:2rem">
        No records yet — run an evaluation above to send payloads.</td></tr>`;
      return;
    }

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

// ── Interactive evaluation panel ──────────────────────────────────────────────

async function runEvaluation() {
  const query = document.getElementById("eval-query").value.trim();
  if (!query) return;

  const btn      = document.getElementById("eval-btn");
  const resultEl = document.getElementById("eval-result");

  btn.disabled = true;
  btn.textContent = "⏳ Evaluating…";
  resultEl.style.display = "none";

  try {
    const resp = await fetch("/api/generate-and-evaluate", {
      method:  "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({
        query,
        // include defaults so this works even if server runs old code
        prompt_id:   crypto.randomUUID ? crypto.randomUUID() : Date.now().toString(36),
        model_name:  "gpt-4o-poc",
        model_version: "2024-08-06",
        environment: "development",
        purpose:     "poc-demo",
      }),
    });

    if (!resp.ok) {
      const err = await resp.json().catch(() => ({ detail: resp.statusText }));
      resultEl.innerHTML = `<p style="color:#e74c3c">Error ${resp.status}: ${escHtml(err.detail || resp.statusText)}</p>`;
      resultEl.style.display = "block";
      return;
    }

    const data = await resp.json();
    resultEl.innerHTML = renderEvalResult(data);
    resultEl.style.display = "block";

    // Refresh dimension cards and records table to include the new evaluation
    await refreshDashboard();
  } catch (e) {
    resultEl.innerHTML = `<p style="color:#e74c3c">Network error: ${escHtml(e.message)}</p>`;
    resultEl.style.display = "block";
  } finally {
    btn.disabled = false;
    btn.textContent = "▶ Run Evaluation";
  }
}

function renderEvalResult(data) {
  const generatedResponse = data.generated_response || "";
  const evaluation = data.evaluation || data;
  const dims = evaluation.ethical_dimensions || [];

  const dimRows = dims.map(d => {
    const metrics = d.dimension_metrics || [];
    const score = metrics.length
      ? metrics.reduce((s, m) => s + (m.metric_metadata?.score ?? 0), 0) / metrics.length
      : 0;
    const pct = Math.min(100, (score / 5) * 100);
    return `<div class="eval-dim-row">
      <span class="eval-dim-name">${escHtml(d.dimension_name)}</span>
      <div class="eval-dim-bar-wrap"><div class="eval-dim-bar" style="width:${pct.toFixed(1)}%"></div></div>
      <span class="eval-dim-score">${score.toFixed(2)} / 5.0</span>
    </div>`;
  }).join("");

  return `
    <p style="font-weight:700;font-size:0.78rem;letter-spacing:0.06em;color:#7f8c8d;text-transform:uppercase;margin-bottom:0.4rem">Generated Response</p>
    <p style="color:#555;margin-bottom:1rem;font-size:0.85rem;line-height:1.5">${escHtml(generatedResponse)}</p>
    <p style="font-weight:700;font-size:0.78rem;letter-spacing:0.06em;color:#7f8c8d;text-transform:uppercase;margin-bottom:0.5rem">Ethical Dimension Scores (this evaluation)</p>
    ${dimRows || '<p style="color:#95a5a6">No dimensions returned.</p>'}`;
}

// ── Boot ──────────────────────────────────────────────────────────────────────

// Format server-rendered timestamps to local time on page load
document.querySelectorAll("td[data-ts]").forEach(td => {
  td.textContent = formatTs(td.dataset.ts);
});

// Immediate refresh + interval
refreshDashboard();
setInterval(refreshDashboard, POLL_INTERVAL_MS);
