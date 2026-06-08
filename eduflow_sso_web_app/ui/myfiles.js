/* ============================================================
   EduFlow — ui/myfiles.js
   Fetches /myfiles/data and renders 5 user-scoped tables:
     • Uploaded Files   • Transcriptions   • User Stories
     • Notifications    • Actions
   Long text cells are truncated and clickable → themed popup
   with markdown rendering via marked.js.
   Auto-refreshes every 30 seconds with a live countdown.
   ============================================================ */

'use strict';

const DATA_URL     = '/myfiles/data';
const REFRESH_SECS = 30;
const AUTH_URL     = '/auth/me';
const TRUNC_LEN    = 60;  // chars before truncation

// ── DOM refs ──────────────────────────────────────────────────────
const uploadsBody        = document.getElementById('uploadsBody');
const transcriptionsBody = document.getElementById('transcriptionsBody');
const storiesBody        = document.getElementById('storiesBody');
const notificationsBody  = document.getElementById('notificationsBody');
const actionsBody        = document.getElementById('actionsBody');
const refreshLabel       = document.getElementById('refreshLabel');
const refreshDot         = document.getElementById('refreshDot');
const genAt              = document.getElementById('genAt');
const userEmail          = document.getElementById('userEmail');

let countdownTimer = null;
let countdownVal   = REFRESH_SECS;

// ------------------------------------------------------------------ //
// Utilities                                                           //
// ------------------------------------------------------------------ //

/** Format an ISO 8601 / timestamptz string to a readable local time. */
function fmtTimestamp(ts) {
  if (!ts) return '—';
  const d = new Date(ts);
  if (isNaN(d.getTime())) return escHtml(String(ts));
  const months = ['Jan','Feb','Mar','Apr','May','Jun',
                  'Jul','Aug','Sep','Oct','Nov','Dec'];
  const pad = n => String(n).padStart(2, '0');
  return `${pad(d.getDate())} ${months[d.getMonth()]} ${d.getFullYear()} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

/** Minimal HTML-escape to prevent XSS. */
function escHtml(str) {
  if (str === null || str === undefined) return '';
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

/** Build the is_processed badge (boolean from Postgres). */
function processedBadge(isProcessed) {
  return isProcessed
    ? '<span class="badge badge-processed">Processed</span>'
    : '<span class="badge badge-pending">Pending</span>';
}

/** Truncate text and wrap in a clickable span that opens the popup. */
function truncateCell(text, title) {
  const safe = escHtml(text);
  if (!safe) return '<span class="empty-cell">—</span>';
  if (safe.length <= TRUNC_LEN) return safe;

  const truncated = safe.slice(0, TRUNC_LEN) + '…';
  // Use a data attribute to store the full escaped text; the click handler
  // reads it and opens the popup with markdown rendering.
  return `<span class="truncated-cell" data-full-text="${safe.replace(/"/g, '&quot;')}" data-title="${escHtml(title)}">${truncated}</span>`;
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
// Popup modal                                                         //
// ------------------------------------------------------------------ //

let popupEl = null;

function openPopup(title, rawText) {
  closePopup();

  // Render markdown via marked.js
  let html;
  try {
    html = marked.parse(rawText);
  } catch (_) {
    html = `<pre>${escHtml(rawText)}</pre>`;
  }

  popupEl = document.createElement('div');
  popupEl.className = 'popup-overlay';
  popupEl.innerHTML = `
    <div class="popup-glass">
      <div class="popup-header">
        <span class="popup-title">${escHtml(title)}</span>
        <button class="popup-close" aria-label="Close popup">&times;</button>
      </div>
      <div class="popup-body">${html}</div>
    </div>`;

  // Click overlay background to close
  popupEl.addEventListener('click', (e) => {
    if (e.target === popupEl) closePopup();
  });

  // Close button
  popupEl.querySelector('.popup-close').addEventListener('click', closePopup);

  // Esc key to close
  document.addEventListener('keydown', onEscKey);

  document.body.appendChild(popupEl);
  document.body.style.overflow = 'hidden';
}

function closePopup() {
  if (popupEl) {
    popupEl.remove();
    popupEl = null;
    document.body.style.overflow = '';
    document.removeEventListener('keydown', onEscKey);
  }
}

function onEscKey(e) {
  if (e.key === 'Escape') closePopup();
}

// Delegate click events on truncated cells to open the popup
function attachCellClickListeners() {
  document.querySelectorAll('.truncated-cell').forEach(el => {
    el.addEventListener('click', () => {
      const fullText = el.getAttribute('data-full-text') || '';
      const title    = el.getAttribute('data-title') || 'Details';
      openPopup(title, fullText);
    });
  });
}

// ------------------------------------------------------------------ //
// Render — Uploaded Files                                             //
// ------------------------------------------------------------------ //

function renderUploads(rows) {
  if (!rows || rows.length === 0) {
    uploadsBody.innerHTML = '<tr class="state-row"><td colspan="4">No uploaded files found.</td></tr>';
    return;
  }
  uploadsBody.innerHTML = rows.map((row, i) => `
    <tr>
      <td class="td-num">${i + 1}</td>
      <td class="td-filename" title="${escHtml(row.file_name || '')}">${escHtml(row.file_name || '—')}</td>
      <td>${processedBadge(row.is_processed)}</td>
      <td class="td-date">${fmtTimestamp(row.created_at)}</td>
    </tr>`).join('');
}

// ------------------------------------------------------------------ //
// Render — Transcriptions                                             //
// ------------------------------------------------------------------ //

function renderTranscriptions(rows) {
  if (!rows || rows.length === 0) {
    transcriptionsBody.innerHTML = '<tr class="state-row"><td colspan="3">No transcriptions found.</td></tr>';
    return;
  }
  transcriptionsBody.innerHTML = rows.map((row, i) => `
    <tr>
      <td class="td-num">${i + 1}</td>
      <td class="td-content">${truncateCell(row.summarized_content || '', 'Summarized Content')}</td>
      <td>${processedBadge(row.is_processed)}</td>
    </tr>`).join('');
}

// ------------------------------------------------------------------ //
// Render — User Stories                                               //
// ------------------------------------------------------------------ //

function renderStories(rows) {
  if (!rows || rows.length === 0) {
    storiesBody.innerHTML = '<tr class="state-row"><td colspan="3">No user stories found.</td></tr>';
    return;
  }
  storiesBody.innerHTML = rows.map((row, i) => `
    <tr>
      <td class="td-num">${i + 1}</td>
      <td class="td-content">${truncateCell(row.processed_description || '', 'Processed Description')}</td>
      <td>${processedBadge(row.is_processed)}</td>
    </tr>`).join('');
}

// ------------------------------------------------------------------ //
// Render — Notifications                                              //
// ------------------------------------------------------------------ //

function renderNotifications(rows) {
  if (!rows || rows.length === 0) {
    notificationsBody.innerHTML = '<tr class="state-row"><td colspan="3">No notifications found.</td></tr>';
    return;
  }
  notificationsBody.innerHTML = rows.map((row, i) => `
    <tr>
      <td class="td-num">${i + 1}</td>
      <td class="td-content">${truncateCell(row.message || '', 'Message')}</td>
      <td>${processedBadge(row.is_processed)}</td>
    </tr>`).join('');
}

// ------------------------------------------------------------------ //
// Render — Actions                                                    //
// ------------------------------------------------------------------ //

function renderActions(rows) {
  if (!rows || rows.length === 0) {
    actionsBody.innerHTML = '<tr class="state-row"><td colspan="4">No actions found.</td></tr>';
    return;
  }
  actionsBody.innerHTML = rows.map((row, i) => `
    <tr>
      <td class="td-num">${i + 1}</td>
      <td class="td-filename">${escHtml(row.type || '—')}</td>
      <td>${processedBadge(row.is_processed)}</td>
      <td class="td-date">${fmtTimestamp(row.timestamp)}</td>
    </tr>`).join('');
}

// ------------------------------------------------------------------ //
// Error / loading state helpers                                       //
// ------------------------------------------------------------------ //

function renderAllLoading() {
  const loading = '<tr class="state-row"><td colspan="99"><span class="spinner"></span> Loading records…</td></tr>';
  uploadsBody.innerHTML        = loading.replace('colspan="99"', 'colspan="4"');
  transcriptionsBody.innerHTML = loading.replace('colspan="99"', 'colspan="3"');
  storiesBody.innerHTML        = loading.replace('colspan="99"', 'colspan="3"');
  notificationsBody.innerHTML  = loading.replace('colspan="99"', 'colspan="3"');
  actionsBody.innerHTML        = loading.replace('colspan="99"', 'colspan="4"');
}

function renderAllError(msg) {
  const cols = { uploadsBody: 4, transcriptionsBody: 3, storiesBody: 3, notificationsBody: 3, actionsBody: 4 };
  [uploadsBody, transcriptionsBody, storiesBody, notificationsBody, actionsBody].forEach(body => {
    body.innerHTML = `
      <tr class="state-row">
        <td colspan="${cols[body.id]}">
          <span class="error-msg">${escHtml(msg)}</span><br>
          <button class="retry-btn" onclick="fetchData()">Retry</button>
        </td>
      </tr>`;
  });
}

function renderAllEmpty() {
  uploadsBody.innerHTML        = '<tr class="state-row"><td colspan="4">—</td></tr>';
  transcriptionsBody.innerHTML = '<tr class="state-row"><td colspan="3">—</td></tr>';
  storiesBody.innerHTML        = '<tr class="state-row"><td colspan="3">—</td></tr>';
  notificationsBody.innerHTML  = '<tr class="state-row"><td colspan="3">—</td></tr>';
  actionsBody.innerHTML        = '<tr class="state-row"><td colspan="4">—</td></tr>';
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
    renderAllError('Could not reach the server. Check your connection.');
    refreshLabel.textContent = 'Refresh failed — ';
    appendRetryCountdown();
    return;
  }

  if (resp.status === 401) {
    window.location.href = '/auth/login';
    return;
  }

  if (!resp.ok) {
    renderAllError(`Server error (HTTP ${resp.status}). Please try again.`);
    appendRetryCountdown();
    return;
  }

  const data = await resp.json();

  renderUploads(data.uploads);
  renderTranscriptions(data.transcriptions);
  renderStories(data.user_stories);
  renderNotifications(data.notifications);
  renderActions(data.actions);

  // Attach click listeners to all truncated cells
  attachCellClickListeners();

  genAt.textContent = `Generated at ${fmtTimestamp(new Date(data.generated_at * 1000).toISOString())}`;
  refreshLabel.textContent = `Last updated just now`;
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
// Populate user email from /auth/me                                   //
// ------------------------------------------------------------------ //

async function loadUserEmail() {
  try {
    const res  = await fetch(AUTH_URL, { cache: 'no-store', signal: AbortSignal.timeout(8_000) });
    const data = await res.json();
    if (data.authenticated && data.user && data.user.email) {
      userEmail.textContent = data.user.email;
    }
  } catch (_) {
    // non-critical — silently ignore
  }
}

// ------------------------------------------------------------------ //
// Boot                                                                //
// ------------------------------------------------------------------ //
loadUserEmail();
fetchData();
