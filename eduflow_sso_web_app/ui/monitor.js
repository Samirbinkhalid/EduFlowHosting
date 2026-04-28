/* ============================================================
   MentorMind — ui/monitor.js  (v2)
   Fetches /dbstatus/data and renders:
     • Uploads table   (with Failed stat card)
     • Transcriptions table
   Auto-refreshes every 30 seconds with a live countdown.
   ============================================================ */

'use strict';

const DATA_URL     = '/dbstatus/data';
const REFRESH_SECS = 30;
const AUTH_URL     = '/auth/me';

// ── DOM refs — uploads ────────────────────────────────────────────────
const tableBody     = document.getElementById('tableBody');
const statTotal     = document.getElementById('statTotal');
const statPending   = document.getElementById('statPending');
const statProcessed = document.getElementById('statProcessed');
const statFailed    = document.getElementById('statFailed');

// ── DOM refs — transcriptions ─────────────────────────────────────────
const txTableBody    = document.getElementById('txTableBody');
const statTxTotal    = document.getElementById('statTxTotal');
const statTxPending  = document.getElementById('statTxPending');
const statTxProcessed= document.getElementById('statTxProcessed');

// ── DOM refs — shared ─────────────────────────────────────────────────
const refreshLabel = document.getElementById('refreshLabel');
const refreshDot   = document.getElementById('refreshDot');
const genAt        = document.getElementById('genAt');
const adminEmail   = document.getElementById('adminEmail');

let countdownTimer = null;
let countdownVal   = REFRESH_SECS;

// ------------------------------------------------------------------ //
// Utilities                                                           //
// ------------------------------------------------------------------ //

/** Format a Unix epoch (seconds) as "DD Mon YYYY HH:MM" local time. */
function fmtEpoch(epoch) {
  const d = new Date(epoch * 1000);
  const months = ['Jan','Feb','Mar','Apr','May','Jun',
                  'Jul','Aug','Sep','Oct','Nov','Dec'];
  const pad = n => String(n).padStart(2, '0');
  return `${pad(d.getDate())} ${months[d.getMonth()]} ${d.getFullYear()} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

/** Truncate a UUID to its first 8 hex chars; full UUID in title tooltip. */
function shortUuid(uuid) {
  return `<span title="${uuid}" style="cursor:default">${uuid.slice(0,8)}&hellip;</span>`;
}

/** Minimal HTML-escape to prevent XSS from DB-stored values. */
function escHtml(str) {
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

/** Build the status badge for an upload row. */
function uploadBadge(isProcessed) {
  switch (isProcessed) {
    case  1: return '<span class="badge badge-processed">Done</span>';
    case  2: return '<span class="badge badge-inprogress">In Progress</span>';
    case -1: return '<span class="badge badge-failed">Failed</span>';
    default: return '<span class="badge badge-pending">Pending</span>';
  }
}

/** Build the status badge for a transcription row. */
function txBadge(isProcessed) {
  return isProcessed === 1
    ? '<span class="badge badge-processed">Processed</span>'
    : '<span class="badge badge-pending">Pending</span>';
}

// ------------------------------------------------------------------ //
// Countdown ticker                                                    //
// ------------------------------------------------------------------ //

function startCountdown() {
  stopCountdown();
  countdownVal = REFRESH_SECS;
  countdownTimer = setInterval(() => {
    countdownVal--;
    if (countdownVal <= 0) {
      stopCountdown();
      fetchData();
    } else {
      refreshLabel.textContent = `Next refresh in ${countdownVal}s`;
    }
  }, 1000);
}

function stopCountdown() {
  if (countdownTimer) {
    clearInterval(countdownTimer);
    countdownTimer = null;
  }
}

// ------------------------------------------------------------------ //
// Render — uploads                                                    //
// ------------------------------------------------------------------ //

function renderUploadStats(data) {
  statTotal.textContent     = data.total     ?? '—';
  statPending.textContent   = data.pending   ?? '—';
  statProcessed.textContent = data.processed ?? '—';
  statFailed.textContent    = data.failed    ?? '—';
}

function renderUploadsTable(uploads) {
  if (!uploads || uploads.length === 0) {
    tableBody.innerHTML = `
      <tr class="state-row">
        <td colspan="7">No upload records found.</td>
      </tr>`;
    return;
  }

  tableBody.innerHTML = uploads.map((row, i) => `
    <tr>
      <td class="td-num">${i + 1}</td>
      <td class="td-name">${escHtml(row.user_name  || '—')}</td>
      <td class="td-email">${escHtml(row.user_email || '—')}</td>
      <td class="td-uuid">${shortUuid(row.uuid)}</td>
      <td class="td-date">${fmtEpoch(row.created_at)}</td>
      <td class="td-num">${row.retry_count ?? 0}</td>
      <td>${uploadBadge(row.is_processed)}</td>
    </tr>`).join('');
}

// ------------------------------------------------------------------ //
// Render — transcriptions                                             //
// ------------------------------------------------------------------ //

function renderTxStats(data) {
  statTxTotal.textContent     = data.transcription_total     ?? '—';
  statTxPending.textContent   = data.transcription_pending   ?? '—';
  statTxProcessed.textContent = data.transcription_processed ?? '—';
}

function renderTxTable(transcriptions) {
  if (!transcriptions || transcriptions.length === 0) {
    txTableBody.innerHTML = `
      <tr class="state-row">
        <td colspan="6">No transcription records found.</td>
      </tr>`;
    return;
  }

  txTableBody.innerHTML = transcriptions.map((row, i) => `
    <tr>
      <td class="td-num">${i + 1}</td>
      <td class="td-name">${escHtml(row.user_name  || '—')}</td>
      <td class="td-email">${escHtml(row.user_email || '—')}</td>
      <td class="td-uuid">${shortUuid(row.uuid)}</td>
      <td class="td-date">${fmtEpoch(row.created_at)}</td>
      <td>${txBadge(row.is_processed)}</td>
    </tr>`).join('');
}

// ------------------------------------------------------------------ //
// Error / loading state helpers (uploads table only)                 //
// ------------------------------------------------------------------ //

function renderError(msg) {
  tableBody.innerHTML = `
    <tr class="state-row">
      <td colspan="7">
        <span class="error-msg">${escHtml(msg)}</span><br>
        <button class="retry-btn" onclick="fetchData()">Retry</button>
      </td>
    </tr>`;
  txTableBody.innerHTML = `
    <tr class="state-row">
      <td colspan="6"><span class="error-msg">—</span></td>
    </tr>`;
}

function renderLoading() {
  tableBody.innerHTML = `
    <tr class="state-row">
      <td colspan="7"><span class="spinner"></span> Loading records…</td>
    </tr>`;
  txTableBody.innerHTML = `
    <tr class="state-row">
      <td colspan="6"><span class="spinner"></span> Loading records…</td>
    </tr>`;
}

// ------------------------------------------------------------------ //
// Main fetch                                                          //
// ------------------------------------------------------------------ //

async function fetchData() {
  stopCountdown();
  refreshLabel.textContent = 'Refreshing…';

  let resp;
  try {
    resp = await fetch(DATA_URL, {
      cache: 'no-store',
      signal: AbortSignal.timeout(15_000),
    });
  } catch (_) {
    renderError('Could not reach the server. Check your connection.');
    refreshLabel.textContent = 'Refresh failed — ';
    appendRetryCountdown();
    return;
  }

  if (resp.status === 401) {
    window.location.href = '/auth/login';
    return;
  }

  if (resp.status === 403) {
    const errRow = `<span class="error-msg">Access denied. You are not an administrator.</span>`;
    tableBody.innerHTML  = `<tr class="state-row"><td colspan="7">${errRow}</td></tr>`;
    txTableBody.innerHTML= `<tr class="state-row"><td colspan="6">${errRow}</td></tr>`;
    refreshLabel.textContent = 'Access denied';
    return;
  }

  if (!resp.ok) {
    renderError(`Server error (HTTP ${resp.status}). Please try again.`);
    appendRetryCountdown();
    return;
  }

  const data = await resp.json();

  renderUploadStats(data);
  renderUploadsTable(data.uploads);
  renderTxStats(data);
  renderTxTable(data.transcriptions);

  genAt.textContent = `Generated at ${fmtEpoch(data.generated_at)}`;
  refreshLabel.textContent = `Last updated ${fmtEpoch(data.generated_at)}`;
  startCountdown();
}

/** After an error, show a secondary countdown then auto-retry. */
function appendRetryCountdown() {
  let t = REFRESH_SECS;
  countdownTimer = setInterval(() => {
    t--;
    if (t <= 0) {
      stopCountdown();
      fetchData();
    } else {
      refreshLabel.textContent = `Retry in ${t}s`;
    }
  }, 1000);
}

// ------------------------------------------------------------------ //
// Populate admin email from /auth/me                                 //
// ------------------------------------------------------------------ //

async function loadAdminEmail() {
  try {
    const res  = await fetch(AUTH_URL, { cache: 'no-store', signal: AbortSignal.timeout(8_000) });
    const data = await res.json();
    if (data.authenticated && data.user && data.user.email) {
      adminEmail.textContent = data.user.email;
    }
  } catch (_) {
    // non-critical — silently ignore
  }
}

// ------------------------------------------------------------------ //
// Boot                                                                //
// ------------------------------------------------------------------ //
loadAdminEmail();
fetchData();
