/* ============================================================
   MentorMind — ui/app.js
   Handles:
     1. Drop-zone / file-input interactions with auth guard,
        file type & size validation, and TUS resumable upload
     2. Periodic health-check against the isactive webhook
     3. Auth state: login / logout + permission check
   ============================================================ */

'use strict';

// ------------------------------------------------------------------ //
// Constants                                                           //
// ------------------------------------------------------------------ //
const HEALTH_URL     = 'https://echoautomation.theworkpc.com/webhook/isactive';
const USERS_URL      = 'https://echoautomation.theworkpc.com/webhook/mentormindusers';
const CHECK_INTERVAL = 15_000;   // health-check poll every 15 s
const FETCH_TIMEOUT  = 10_000;   // treat any request as failed after 10 s

const MAX_FILE_BYTES = 500 * 1024 * 1024;   // 500 MB
const ALLOWED_TYPES  = new Set([
  'video/mp4',
  'audio/mp4',
  'audio/m4a',
  'audio/x-m4a',
]);

// TUS upload chunk size — 5 MB
const TUS_CHUNK_SIZE = 5 * 1024 * 1024;

// Colours match the brand: blue = Mentor, orange = Mind
const COLOR_ONLINE   = '#2499ee';
const COLOR_OFFLINE  = '#ff9933';
const SHADOW_ONLINE  = '0 0 10px #2499ee, 0 0 26px #1a7abf';
const SHADOW_OFFLINE = '0 0 10px #ff9933, 0 0 26px #e87722';

// ------------------------------------------------------------------ //
// Drop-zone / file-input elements                                     //
// ------------------------------------------------------------------ //
const zone          = document.getElementById('dropZone');
const input         = document.getElementById('fileInput');
const uploadBtn     = document.getElementById('uploadBtn');
const uploadBtnLabel = document.getElementById('uploadBtnLabel');

// Upload feedback elements
const feedback     = document.getElementById('uploadFeedback');
const errorEl      = document.getElementById('uploadError');
const progressWrap = document.getElementById('uploadProgressWrap');
const progressBar  = document.getElementById('uploadProgressBar');
const statusEl_up  = document.getElementById('uploadStatus');

// ------------------------------------------------------------------ //
// Feedback helpers                                                    //
// ------------------------------------------------------------------ //

function showFeedback() {
  feedback.style.display = 'flex';
}

function hideFeedback() {
  feedback.style.display = 'none';
  errorEl.textContent        = '';
  statusEl_up.textContent    = '';
  progressWrap.style.display = 'none';
  progressBar.style.width    = '0%';
}

function showError(msg) {
  showFeedback();
  errorEl.textContent        = msg;
  progressWrap.style.display = 'none';
  statusEl_up.textContent    = '';
}

function showProgress(pct, statusText) {
  showFeedback();
  errorEl.textContent        = '';
  progressWrap.style.display = 'block';
  progressBar.style.width    = pct + '%';
  statusEl_up.textContent    = statusText || '';
}

function showSuccess(msg) {
  showFeedback();
  errorEl.textContent        = '';
  progressWrap.style.display = 'none';
  progressBar.style.width    = '0%';
  statusEl_up.textContent    = msg;
}

// ------------------------------------------------------------------ //
// Zone state helpers                                                  //
// ------------------------------------------------------------------ //

function setFile(f) {
  zone.querySelector('.drop-label').textContent = '\u2714 ' + f.name;
  zone.querySelector('.drop-sub').textContent   =
    (f.size / (1024 * 1024)).toFixed(2) + ' MB \u00b7 Ready';
}

function resetZone() {
  zone.querySelector('.drop-label').textContent = 'Drop Your Record Here';
  zone.querySelector('.drop-sub').textContent   = 'Drop here \u00b7 or click to upload \u00b7 MP4 / M4A';
}

// ------------------------------------------------------------------ //
// Pending file — staged after validation, uploaded on button click    //
// ------------------------------------------------------------------ //

let pendingFile = null;

function setPendingFile(f) {
  pendingFile = f;
  setFile(f);
  uploadBtn.classList.add('ready');
  uploadBtnLabel.textContent = 'Upload Record';
  hideFeedback();
}

function clearPendingFile() {
  pendingFile = null;
  uploadBtn.classList.remove('ready');
}

// ------------------------------------------------------------------ //
// Button state helpers                                                //
// ------------------------------------------------------------------ //

function setButtonUploading() {
  uploadBtn.classList.remove('ready');
  uploadBtn.classList.add('uploading');
  uploadBtn.disabled = true;
  uploadBtnLabel.textContent = 'Uploading\u2026';
}

function setButtonIdle() {
  uploadBtn.classList.remove('uploading', 'ready');
  uploadBtn.disabled = false;
  uploadBtnLabel.textContent = 'Upload Record';
}

// ------------------------------------------------------------------ //
// Authorization check                                                 //
// ------------------------------------------------------------------  //
// Returns true  → user is SSO-authenticated AND activated.           //
// Returns false → user is not authorised; appropriate UI has been     //
//                 updated and the file should NOT be uploaded.        //
// ------------------------------------------------------------------ //
async function checkAuthorized() {
  // Step 1: SSO session
  let meData;
  try {
    const meRes = await fetch('/auth/me', {
      cache:  'no-store',
      signal: AbortSignal.timeout(FETCH_TIMEOUT),
    });
    meData = await meRes.json();
  } catch (_) {
    showError('Could not reach the server. Please refresh the page.');
    return false;
  }

  if (!meData.authenticated) {
    // Not logged in — send to SSO.  The return trip brings them back here.
    window.location.href = '/auth/login';
    return false;
  }

  // Step 2: activation webhook
  const email = (meData.user.email || '').toLowerCase();
  try {
    const permRes = await fetch(
      `${USERS_URL}?email=${encodeURIComponent(email)}`,
      { cache: 'no-store', signal: AbortSignal.timeout(FETCH_TIMEOUT) }
    );

    if (permRes.ok) return true;   // 200 → authorised

    if (permRes.status === 404) {
      showError('Account not activated. Please ask Codeline to activate your account.');
      return false;
    }

    // 5xx or unexpected
    showError('We are under maintenance for a while. Please try again later.');
    return false;

  } catch (_) {
    showError('We are under maintenance for a while. Please try again later.');
    return false;
  }
}

// ------------------------------------------------------------------ //
// File validation                                                     //
// ------------------------------------------------------------------ //

function validateFile(f) {
  if (!ALLOWED_TYPES.has(f.type)) {
    // Some browsers report '' or a system MIME for .m4a — also check extension
    const ext = f.name.split('.').pop().toLowerCase();
    if (ext !== 'mp4' && ext !== 'm4a') {
      showError('Only MP4 and M4A files are accepted.');
      return false;
    }
  }
  if (f.size > MAX_FILE_BYTES) {
    showError('File exceeds the 500 MB limit (' +
      (f.size / (1024 * 1024)).toFixed(1) + ' MB).');
    return false;
  }
  return true;
}

// ------------------------------------------------------------------ //
// TUS upload                                                          //
// ------------------------------------------------------------------ //

// Track the active upload instance so a new drop cancels the old one.
let activeUpload = null;

function startUpload(f) {
  if (activeUpload) {
    activeUpload.abort();
    activeUpload = null;
  }

  clearPendingFile();
  setButtonUploading();

  const upload = new tus.Upload(f, {
    endpoint:    '/upload/',
    chunkSize:   TUS_CHUNK_SIZE,
    retryDelays: [0, 1_000, 3_000, 5_000],
    metadata: {
      filename: f.name,
      filetype: f.type || 'video/mp4',
    },

    onProgress(bytesSent, bytesTotal) {
      const pct = bytesTotal > 0
        ? Math.round((bytesSent / bytesTotal) * 100)
        : 0;
      showProgress(
        pct,
        'Uploading\u2026 ' + pct + '% ' +
        '(' + (bytesSent / (1024 * 1024)).toFixed(1) + ' / ' +
        (bytesTotal / (1024 * 1024)).toFixed(1) + ' MB)'
      );
    },

    onError(err) {
      activeUpload = null;
      setButtonIdle();
      resetZone();
      // Provide a user-friendly message for auth failures
      const httpStatus = err.originalResponse ? err.originalResponse.getStatus() : 0;
      if (httpStatus === 401) {
        window.location.href = '/auth/login';
        return;
      }
      if (httpStatus === 403) {
        showError('Account not activated. Please ask Codeline to activate your account.');
        return;
      }
      if (httpStatus === 413) {
        showError('File exceeds the 500 MB server limit.');
        return;
      }
      showError('Upload failed. Please try again.');
    },

    onSuccess() {
      activeUpload = null;
      setButtonIdle();
      resetZone();
      showSuccess('Upload complete \u2014 your file is being processed.');
    },
  });

  upload.start();
  activeUpload = upload;
}

// ------------------------------------------------------------------ //
// Central file handler — auth → validate → stage                     //
// Upload is deferred until the user clicks the "Upload Record" button //
// ------------------------------------------------------------------ //

async function handleFile(f) {
  if (!f) return;

  hideFeedback();
  clearPendingFile();
  resetZone();

  // Auth gate first — redirect or show error and bail if not authorised
  const ok = await checkAuthorized();
  if (!ok) return;

  // File type & size validation
  if (!validateFile(f)) return;

  // Stage the file — upload starts when the button is clicked
  setPendingFile(f);
}

// ------------------------------------------------------------------ //
// Drop-zone events                                                    //
// ------------------------------------------------------------------ //

zone.addEventListener('dragover',  e => { e.preventDefault(); zone.classList.add('drag-over'); });
zone.addEventListener('dragleave', ()  => zone.classList.remove('drag-over'));

zone.addEventListener('drop', e => {
  e.preventDefault();
  zone.classList.remove('drag-over');
  handleFile(e.dataTransfer.files[0]);
});

// Drop zone click opens the file picker only when not actively uploading
zone.addEventListener('click', () => {
  if (!activeUpload) input.click();
});

input.addEventListener('change', e => {
  handleFile(e.target.files[0]);
  // Reset input so the same file can be re-selected after a failure
  e.target.value = '';
});

// ------------------------------------------------------------------ //
// Upload button                                                       //
// ------------------------------------------------------------------ //
// Only starts an upload when a file has been staged via the drop zone //
// or the file input (clicking the drop zone).  Does nothing otherwise //
// — the drop zone is the sole entry point for file selection.        //
// ------------------------------------------------------------------ //

uploadBtn.addEventListener('click', () => {
  if (pendingFile) {
    startUpload(pendingFile);
  }
});

// ------------------------------------------------------------------ //
// Health check                                                        //
// ------------------------------------------------------------------ //
const statusEl = document.getElementById('sysStatus');

function setStatus(text, color, shadow) {
  statusEl.textContent      = text;
  statusEl.style.color      = color;
  statusEl.style.textShadow = shadow;
}

async function checkHealth() {
  try {
    const res = await fetch(HEALTH_URL, {
      method: 'GET',
      cache:  'no-store',
      signal: AbortSignal.timeout(FETCH_TIMEOUT),
    });

    if (res.ok) {                  // 200–299 → online
      setStatus('All Systems Online', COLOR_ONLINE, SHADOW_ONLINE);
      return;
    }
  } catch (_) {
    // Network error, DNS failure, or request timed out
  }

  // Non-200 (including 404) or timeout → immediately offline
  setStatus('Offline', COLOR_OFFLINE, SHADOW_OFFLINE);
}

// Run immediately on page load, then on a fixed interval
checkHealth();
setInterval(checkHealth, CHECK_INTERVAL);

// ------------------------------------------------------------------ //
// Auth                                                                //
// ------------------------------------------------------------------ //
const authBtn = document.getElementById('authBtn');
const authSub = document.getElementById('authSub');

// Pre-built innerHTML strings for each logged-out sub-text state
const MSG_DEFAULT     = 'Using <span class="cl-brand">Codeline</span> Account';
const MSG_NOT_ACTIVE  = 'Please ask <span class="cl-brand">Codeline</span> to activate your account';
const MSG_MAINTENANCE = 'We are under maintenance for a while!';

/** Convert any casing to Title Case — "john doe" → "John Doe" */
function toTitleCase(str) {
  if (!str) return '';
  return str.replace(/\w\S*/g, w => w.charAt(0).toUpperCase() + w.slice(1).toLowerCase());
}

/** Switch the button + label into the logged-in / authorised state */
function showLoggedIn(name) {
  authBtn.textContent = 'Logout';
  authBtn.classList.add('logout');
  authBtn.onclick = () => { window.location.href = '/auth/logout'; };

  authSub.textContent = 'Nice to see you ' + toTitleCase(name);
  authSub.classList.add('greeting');
}

/** Keep (or restore) the default logged-out state.
 *  @param {string}  [html]  - innerHTML for the sub-text (may contain spans).
 *  @param {boolean} [warn]  - When true, render the sub-text in offline orange.
 */
function showLoggedOut(html = MSG_DEFAULT, warn = false) {
  authBtn.textContent = 'Login';
  authBtn.classList.remove('logout');
  authBtn.onclick = () => { window.location.href = '/auth/login'; };

  authSub.innerHTML = html;
  authSub.classList.remove('greeting');

  if (warn) {
    authSub.style.color         = COLOR_OFFLINE;
    authSub.style.textShadow    = SHADOW_OFFLINE;
    authSub.style.textTransform = 'none';
    authSub.style.letterSpacing = '.1em';
  } else {
    authSub.style.color         = '';
    authSub.style.textShadow    = '';
    authSub.style.textTransform = '';
    authSub.style.letterSpacing = '';
  }
}

/**
 * On page load:
 *   1. Call /auth/me to check session.
 *   2. If authenticated, call the users webhook with the email.
 *   3. Only on webhook 200 → flip to logout + greeting state.
 */
async function initAuth() {
  try {
    const meRes  = await fetch('/auth/me', {
      cache:  'no-store',
      signal: AbortSignal.timeout(FETCH_TIMEOUT),
    });
    const meData = await meRes.json();

    if (!meData.authenticated) {
      showLoggedOut();
      return;
    }

    // Authenticated — check permission via the users webhook
    const { email, name } = meData.user;
    const normalizedEmail = (email || '').toLowerCase();

    try {
      const permRes = await fetch(
        `${USERS_URL}?email=${encodeURIComponent(normalizedEmail)}`,
        { cache: 'no-store', signal: AbortSignal.timeout(FETCH_TIMEOUT) }
      );

      if (permRes.ok) {                   // 200 → authorised
        showLoggedIn(name);
        return;
      }

      if (permRes.status === 404) {       // account not activated
        showLoggedOut(MSG_NOT_ACTIVE);
        return;
      }

      // 5xx or any other error → maintenance
      showLoggedOut(MSG_MAINTENANCE, true);

    } catch (_) {
      // Timeout or network failure → maintenance
      showLoggedOut(MSG_MAINTENANCE, true);
    }

  } catch (_) {
    // /auth/me unreachable — default to logged-out state
    showLoggedOut();
  }
}

initAuth();
