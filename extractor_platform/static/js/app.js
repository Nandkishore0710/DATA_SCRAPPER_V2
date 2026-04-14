// ---- Custom Strategy Dropdown ----
const strategyOptions = [
    { value: 'fast', label: 'Fast (144 cells)' },
    { value: 'detailed', label: 'Detailed (225 cells)' },
    { value: 'deep', label: 'Deep (400 cells)' },
    { value: 'ultra', label: 'Ultra (625 cells)' },
];

// ---- Dynamic Keyword Row Logic ----
function addKeywordRow(arg) {
    let val = (typeof arg === 'string') ? arg : '';
    const mode = document.getElementById('search-form')?.dataset.mode || 'single';
    const container = document.getElementById('keyword-input-rows');
    if (!container) return;

    // Prevent multiple rows in single search mode
    if (mode !== 'multi' && container.children.length >= 1) {
        if (!val) return; // Ignore blank additions in single mode
    }
    if (!container) return;

    const row = document.createElement('div');
    row.className = 'keyword-row';
    row.style.cssText = 'display: flex; gap: 8px; align-items: center; border-radius: 8px;';

    // Cross button should be hidden in single search unless there are multiple rows
    const showDelete = (mode === 'multi');

    row.innerHTML = `
        <div style="flex: 1; border: 1px solid var(--border); border-radius: 8px; background: var(--input-bg); padding: 2px 12px; display: flex; align-items: center;">
            <input type="text" class="keyword-input-field" placeholder="e.g. Coffee Shops" value="${val}"
                style="border: none; background: transparent; width: 100%; outline: none; padding: 10px 0; font-size: 0.85rem; color: var(--text-main);"
                oninput="this.value=this.value.replace(/[^a-zA-Z0-9 \\-\\&]/g,'')"
                autocomplete="off"
                onkeydown="if(event.key==='Enter'){event.preventDefault();addKeywordRow();}">
        </div>
        <button type="button" class="keyword-delete-btn" onclick="this.parentElement.remove()" 
            style="background: transparent; border: none; color: var(--text-muted); cursor: pointer; padding: 4px; display: flex; align-items: center; opacity: 0.6; transition: 0.2s; visibility: ${showDelete ? 'visible' : 'hidden'};" 
            onmouseover="this.style.opacity='1'; this.style.color='var(--danger)';" onmouseout="this.style.opacity='0.6'; this.style.color='var(--text-muted)';">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><line x1="18" y1="6" x2="6" y2="18"></line><line x1="6" y1="6" x2="18" y2="18"></line></svg>
        </button>
    `;
    container.appendChild(row);
    if (!val) row.querySelector('input').focus();
}
window.addKeywordRow = addKeywordRow;

window.toggleStrategyDropdown = function (e) {
    e.stopPropagation();
    const dd = document.getElementById('strategy-dropdown');

    if (dd.classList.contains('open')) {
        dd.classList.remove('open');
    } else {
        dd.classList.add('open');
    }
};

window.selectStrategy = function (el) {
    // Deselect all
    document.querySelectorAll('.strategy-option').forEach(opt => {
        opt.classList.remove('selected');
        opt.querySelector('.strategy-check').textContent = '';
    });
    // Select clicked
    el.classList.add('selected');
    el.querySelector('.strategy-check').textContent = '✓';
    // Update hidden input + label
    const value = el.dataset.value;
    const label = el.querySelector('.strategy-option-name').textContent;
    document.getElementById('strategy').value = value;
    document.getElementById('strategy-label').textContent = label;
    // Close dropdown
    document.getElementById('strategy-dropdown').classList.remove('open');
};

window.clearStrategy = function (e) {
    e.stopPropagation();
    // Reset to default (Fast)
    const fastOpt = document.querySelector('.strategy-option[data-value="fast"]');
    if (fastOpt) selectStrategy(fastOpt);
};

// Close dropdown when clicking outside
document.addEventListener('click', function (e) {
    const dd = document.getElementById('strategy-dropdown');
    const trigger = document.getElementById('strategy-trigger');
    if (dd && !dd.contains(e.target) && trigger && !trigger.contains(e.target)) {
        dd.classList.remove('open');
    }
});

// Initialize Theme
document.addEventListener('DOMContentLoaded', () => {
    const themeToggle = document.getElementById('theme-toggle');
    const currentTheme = localStorage.getItem('theme') || 'light';

    // Apply theme immediately
    document.documentElement.setAttribute('data-theme', currentTheme);

    if (themeToggle) {
        if (currentTheme === 'dark') {
            themeToggle.checked = true;
        }

        themeToggle.addEventListener('change', function (e) {
            const newTheme = e.target.checked ? 'dark' : 'light';
            document.documentElement.setAttribute('data-theme', newTheme);
            localStorage.setItem('theme', newTheme);
        });
    }
});

// Global State Variables
let token = localStorage.getItem('access_token');
let refresh = localStorage.getItem('refresh_token');
let isLoginMode = true;
let activeJobsInterval = null;
let currentTableViewMode = 'all';
let latestJobsCache = [];
let allowedStrategies = ['fast', 'detailed']; // default free tier; overridden after profile fetch
let userPackageName = 'Free';

// Apply visual locks to the strategy dropdown based on user's allowed strategies
function applyStrategyLocks() {
    const allOptions = document.querySelectorAll('.strategy-option');
    allOptions.forEach(opt => {
        const val = opt.dataset.value;
        const isAllowed = allowedStrategies.includes(val);
        const existingLock = opt.querySelector('.strategy-lock-badge');

        if (!isAllowed) {
            // Disable and add lock
            opt.style.opacity = '0.55';
            opt.style.cursor = 'not-allowed';
            opt.style.pointerEvents = 'none';
            if (!existingLock) {
                const badge = document.createElement('span');
                badge.className = 'strategy-lock-badge';
                badge.innerHTML = `
                    <span style="display:inline-flex; align-items:center; gap:3px; background: linear-gradient(135deg, #f59e0b, #ef4444); color:white; font-size:0.5rem; font-weight:800; padding: 2px 6px; border-radius: 10px; letter-spacing: 0.05em; text-transform: uppercase;">
                        <svg width="7" height="7" viewBox="0 0 24 24" fill="white"><path d="M18 11H6V8a6 6 0 0 1 12 0v3zm-1 0H7V8a5 5 0 0 1 10 0v3zM5 11V8a7 7 0 0 1 14 0v3a2 2 0 0 1 2 2v7a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-7a2 2 0 0 1 2-2zm7 5a1.5 1.5 0 1 0 0-3 1.5 1.5 0 0 0 0 3z"/></svg>
                        Premium
                    </span>`;
                badge.style.marginLeft = 'auto';
                opt.insertBefore(badge, opt.querySelector('.strategy-check'));
            }
        } else {
            // Re-enable
            opt.style.opacity = '';
            opt.style.cursor = 'pointer';
            opt.style.pointerEvents = '';
            if (existingLock) existingLock.remove();
        }
    });

    // If the currently selected strategy is now locked, fall back to 'fast'
    const currentVal = document.getElementById('strategy');
    if (currentVal && !allowedStrategies.includes(currentVal.value)) {
        const fastOpt = document.querySelector('.strategy-option[data-value="fast"]');
        if (fastOpt) selectStrategy(fastOpt);
    }
}

// --- Job Duration Helpers ---
const liveTimerIntervals = {}; // map: elementId -> intervalId

function formatDuration(seconds) {
    if (isNaN(seconds) || seconds < 0) return '—';
    const h = Math.floor(seconds / 3600);
    const m = Math.floor((seconds % 3600) / 60);
    const s = Math.floor(seconds % 60);
    if (h > 0) return `${h}h ${m}m ${s}s`;
    if (m > 0) return `${m}m ${s}s`;
    return `${s}s`;
}

// Start a live elapsed-time counter on an element
function startLiveTimer(elementId, startIso, doneCells = 0, totalCells = 0) {
    if (liveTimerIntervals[elementId]) {
        clearInterval(liveTimerIntervals[elementId]);
    }
    const el = document.getElementById(elementId);
    if (!el) return;
    const startMs = new Date(startIso).getTime();

    // CAPTURE msPerCell AT THIS SNAPSHOT
    const nowMsSnapshot = Date.now();
    const elapsedSnapshot = nowMsSnapshot - startMs;
    // Base estimation on the average speed calculated from the current snapshot
    const msPerCell = (doneCells >= 1) ? elapsedSnapshot / doneCells : 0;

    function tick() {
        const el2 = document.getElementById(elementId);
        if (!el2) {
            clearInterval(liveTimerIntervals[elementId]);
            delete liveTimerIntervals[elementId];
            return;
        }

        const nowMs = Date.now();
        const elapsedSecs = Math.floor((nowMs - startMs) / 1000);
        let timeText = formatDuration(elapsedSecs);

        // Smooth Estimate: decreases linearly until the next fetchJobs refresh
        if (msPerCell > 0 && doneCells >= 5 && totalCells > doneCells) {
            const totalExpectedMs = msPerCell * totalCells;
            const remainingMs = totalExpectedMs - (nowMs - startMs);
            let remainingSecs = Math.floor(remainingMs / 1000);

            if (remainingSecs > 5) {
                // ROUGH TIMING: Use coarser increments for longer durations as requested
                let roughText = '';
                if (remainingSecs > 300) { // > 5m, round to nearest minute
                    roughText = `${Math.ceil(remainingSecs / 60)}m`;
                } else if (remainingSecs > 60) { // > 1m, round to nearest 15s
                    const mins = Math.floor(remainingSecs / 60);
                    const secs = Math.ceil((remainingSecs % 60) / 15) * 15;
                    if (secs >= 60) roughText = `${mins + 1}m`;
                    else roughText = `${mins}m ${secs}s`;
                } else {
                    roughText = `${remainingSecs}s`;
                }
                timeText += ` • ~${roughText} left`;
            }
        }

        el2.textContent = timeText;
    }
    tick();
    liveTimerIntervals[elementId] = setInterval(tick, 1000);
}

// Get a static duration string from a job object
function jobDurationText(job) {
    if (!job.created_at) return '';
    if (job.status === 'completed' || job.status === 'failed' || job.status === 'cancelled') {
        const start = new Date(job.created_at);
        const end = job.completed_at ? new Date(job.completed_at) : new Date();
        const secs = Math.floor((end - start) / 1000);
        return (job.status === 'cancelled' ? '🛑 ' : '✅ ') + formatDuration(secs);
    }
    return null; // means "live timer needed"
}

// State
// Elements
const authView = document.getElementById('auth-view');
const dashView = document.getElementById('dashboard-view');
const runsContent = document.getElementById('runs-list-content');
const detailsContent = document.getElementById('run-details-content');

const API = '/api';
let currentMap = null;
let currentDetailJobId = null;
let currentDetailIsBulk = false;

// --- Navigation ---
window.switchNav = (target) => {
    // Toggle full-screen mode (hide sidebar) only for results view
    if (target === 'run-details') {
        dashView.classList.add('full-screen-mode');
    } else {
        dashView.classList.remove('full-screen-mode');
    }

    // Update active nav item
    document.querySelectorAll('.nav-item').forEach(item => item.classList.remove('active'));
    const activeNav = document.getElementById(`nav-${target}`);
    if (activeNav) activeNav.classList.add('active');

    // Hide all content areas
    runsContent.style.display = 'none';
    detailsContent.style.display = 'none';
    document.getElementById('history-content').style.display = 'none';
    document.getElementById('settings-content').style.display = 'none';
    document.getElementById('packages-content').style.display = 'none';

    // Show target content area
    const actualTarget = target === 'dashboard' ? 'runs-list' : target;
    const targetEl = document.getElementById(`${actualTarget}-content`);
    if (targetEl) targetEl.style.display = 'block';
    if (target === 'history') {
        renderHistory();
    }
    if (target === 'settings') {
        loadUserProfile();
    }
};

// Update the existing back button to use switchNav
const backBtn = document.getElementById('back-to-runs-btn');
if (backBtn) {
    backBtn.addEventListener('click', () => {
        switchNav('dashboard');
    });
}

async function renderHistory() {
    const hbody = document.getElementById('history-table-body');
    const dateFilter = document.getElementById('history-date-filter') ? document.getElementById('history-date-filter').value : 'all';

    hbody.innerHTML = '<tr><td colspan="5" style="text-align:center; padding: 40px;"><div class="loading-spinner"></div> Loading history...</td></tr>';

    try {
        let jobs = latestJobsCache;
        if (jobs.length === 0) {
            const res = await fetchAPI('/jobs/');
            if (res.ok) {
                jobs = await res.json();
                latestJobsCache = jobs;
            }
        }

        // Apply dynamic date filter
        const now = new Date();
        const filteredJobs = jobs.filter(job => {
            const jobDate = new Date(job.created_at);
            if (dateFilter === 'all') return true;
            if (dateFilter === 'today') return jobDate.toDateString() === now.toDateString();
            if (dateFilter === 'yesterday') {
                const yesterday = new Date();
                yesterday.setDate(now.getDate() - 1);
                return jobDate.toDateString() === yesterday.toDateString();
            }
            if (dateFilter === '7days') return (now - jobDate) <= 7 * 24 * 60 * 60 * 1000;
            if (dateFilter === '30days') return (now - jobDate) <= 30 * 24 * 60 * 60 * 1000;
            if (dateFilter === 'month') return jobDate.getMonth() === now.getMonth() && jobDate.getFullYear() === now.getFullYear();
            return true;
        });

        if (filteredJobs.length === 0) {
            hbody.innerHTML = `<tr><td colspan="6" style="text-align:center; color:var(--text-muted); padding: 40px;">No history items found${dateFilter !== 'all' ? ' for this period' : ''}.</td></tr>`;
            return;
        }

        hbody.innerHTML = '';
        filteredJobs.forEach(job => {
            const date = new Date(job.created_at).toLocaleString([], { month: 'short', day: 'numeric', year: 'numeric', hour: '2-digit', minute: '2-digit' });
            const count = job.total_extracted || 0;

            let badgeClass = 'RUNNING';
            if (job.status === 'completed') badgeClass = 'SUCCEEDED';
            if (job.status === 'failed') badgeClass = 'FAILED';

            const histTimerId = `hist-timer-${job.bulk_job_id}`;
            if (liveTimerIntervals[histTimerId]) {
                clearInterval(liveTimerIntervals[histTimerId]);
                delete liveTimerIntervals[histTimerId];
            }

            const tr = document.createElement('tr');
            tr.className = 'history-row-item';
            tr.style.cssText = 'cursor: pointer; transition: all 0.2s ease; border-bottom: 1px solid var(--border-light);';
            tr.onmouseover = () => { tr.style.background = 'var(--bg-hover)'; };
            tr.onmouseout = () => { tr.style.background = 'transparent'; };
            tr.onclick = (e) => { if (!e.target.closest('button')) viewHistoryItem(job.bulk_job_id); };

            const histStaticDuration = jobDurationText(job);
            const durationDisplay = histStaticDuration !== null
                ? histStaticDuration.replace('✅ ', '').replace('🛑 ', '')
                : `<span id="${histTimerId}" style="color:var(--accent);">⏱ 0s</span>`;

            tr.innerHTML = `
                <td style="padding: 16px 24px;">
                    <span class="status-badge ${badgeClass}" style="
                        padding: 6px 12px; 
                        border-radius: 20px; 
                        font-size: 0.65rem; 
                        font-weight: 800; 
                        letter-spacing: 0.05em;
                        ${badgeClass === 'SUCCEEDED' ? 'background: rgba(16, 185, 129, 0.1); color: #10b981; border: 1px solid rgba(16, 185, 129, 0.2);' : ''}
                        ${badgeClass === 'RUNNING' ? 'background: rgba(245, 158, 11, 0.1); color: #f59e0b; border: 1px solid rgba(245, 158, 11, 0.2);' : ''}
                        ${badgeClass === 'FAILED' ? 'background: rgba(239, 68, 68, 0.1); color: #ef4444; border: 1px solid rgba(239, 68, 68, 0.2);' : ''}
                    ">${job.status.toUpperCase()}</span>
                </td>
                <td style="padding: 16px 12px;">
                    <div style="color: var(--text-main); font-size: 0.8rem; font-weight: 600;">${date.split(',')[0]}</div>
                    <div style="color: var(--text-muted); font-size: 0.7rem;">${date.split(',')[1] || ''}</div>
                </td>
                <td style="padding: 16px 12px;">
                    <div style="display: flex; flex-direction: column; gap: 2px;">
                        <span style="font-weight: 800; color: var(--text-main); font-size: 0.9rem;">${count} Leads</span>
                        <span style="font-size: 0.65rem; color: var(--text-muted); font-weight: 500; display: flex; align-items: center; gap: 4px;">
                            <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3"><circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/></svg>
                            ${durationDisplay}
                        </span>
                    </div>
                </td>
                <td style="padding: 16px 24px;">
                    <div style="display: flex; justify-content: space-between; align-items: center; gap: 16px;">
                        <div style="flex: 1; min-width: 0;">
                            <div style="font-weight: 700; color: var(--text-main); font-size: 0.85rem; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; margin-bottom: 2px;">
                                ${job.keywords.map(k => typeof k === 'object' ? k.keyword : k).join(', ')}
                            </div>
                            <div style="font-size: 0.7rem; color: var(--text-muted); font-weight: 500; display: flex; align-items: center; gap: 4px;">
                                <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3"><path d="M21 10c0 7-9 13-9 13s-9-6-9-13a9 9 0 0 1 18 0z"/><circle cx="12" cy="10" r="3"/></svg>
                                ${job.location}
                            </div>
                        </div>
                        <div style="display: flex; gap: 8px;">
                            <button class="btn-action-view" title="View Results" style="width: 32px; height: 32px; border-radius: 8px; border: 1px solid var(--border); background: var(--card-bg); color: var(--text-main); display: flex; align-items: center; justify-content: center; cursor: pointer; transition: all 0.2s;">
                                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/><circle cx="12" cy="12" r="3"/></svg>
                            </button>
                            <button class="btn-action-delete" title="Delete Log" onclick="event.stopPropagation(); deleteHistoryItem(${job.bulk_job_id})" style="width: 32px; height: 32px; border-radius: 8px; border: 1px solid rgba(239, 68, 68, 0.1); background: rgba(239, 68, 68, 0.05); color: #ef4444; display: flex; align-items: center; justify-content: center; cursor: pointer; transition: all 0.2s;">
                                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polyline points="3 6 5 6 21 6"></polyline><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"></path></svg>
                            </button>
                        </div>
                    </div>
                </td>
            `;
            hbody.appendChild(tr);

            if (histStaticDuration === null) {
                let totalDone = 0;
                let totalCellsSum = 0;
                if (job.keywords && job.keywords.length > 0) {
                    job.keywords.forEach(kj => {
                        totalDone += (kj.cells_done || 0);
                        totalCellsSum += (kj.total_cells || 0);
                    });
                }
                setTimeout(() => startLiveTimer(histTimerId, job.created_at, totalDone, totalCellsSum), 0);
            }
        });
    } catch (e) {
        hbody.innerHTML = '<tr><td colspan="6" style="text-align:center; color:var(--danger)">Error loading history.</td></tr>';
    }
}

window.deleteHistoryItem = async (bulkJobId) => {
    if (!confirm("Are you sure you want to delete this task? This action cannot be undone.")) return;

    try {
        const res = await fetchAPI(`/jobs/${bulkJobId}/`, { method: 'DELETE' });
        if (res.ok) {
            // Update cache and re-render
            latestJobsCache = latestJobsCache.filter(j => j.bulk_job_id !== bulkJobId);
            renderHistory();
        } else {
            alert("Failed to delete the task. It might still be running or was already deleted.");
        }
    } catch (e) {
        console.error("Delete error:", e);
        alert("An error occurred while deleting the task.");
    }
};

window.viewHistoryItem = (bulkJobId) => {
    // Since our viewJobResults expects specific data, we'll find the job details first
    const job = latestJobsCache.find(j => j.bulk_job_id === bulkJobId);
    if (job && job.keywords && job.keywords.length > 0) {
        // For simplicity, viewing the first keyword of the history item
        const kj = job.keywords[0];
        viewJobResults(kj.keyword_job_id, kj.keyword, job.location);
    } else {
        alert("Could not load details for this run.");
    }
};

// --- Auth Logic (Mobile + OTP + Password) ---
let currentPhone = '';
let currentOTP = '';
let userExists = false;
let resendInterval = null;
let confirmationResult = null; // Firebase storage
let otpMethod = 'sms';

// Initialize Firebase (User should replace these with their own config)
const firebaseConfig = {
    apiKey: "AIzaSyAMNsEB_nZXWaOFK5FaU0xGrT7kbLWRVy4",
    authDomain: "map-extractor-bd212.firebaseapp.com",
    projectId: "map-extractor-bd212",
    storageBucket: "map-extractor-bd212.firebasestorage.app",
    messagingSenderId: "785485348907",
    appId: "1:785485348907:web:70eb7df01866a19bfb2a6e"
};

try {
    if (firebaseConfig.apiKey !== "YOUR_API_KEY") {
        firebase.initializeApp(firebaseConfig);
    }
} catch (e) { console.error("Firebase init failed:", e); }

function initRecaptcha() {
    if (window.recaptchaVerifier) return;
    window.recaptchaVerifier = new firebase.auth.RecaptchaVerifier('recaptcha-container', {
        'size': 'invisible',
        'callback': (response) => { /* solved */ }
    });
}

function startResendTimer() {
    let timeLeft = 30;
    const timerEl = document.getElementById('resend-timer');
    const btnEl = document.getElementById('resend-otp-btn');
    timerEl.style.display = 'inline';
    btnEl.style.display = 'none';

    if (resendInterval) clearInterval(resendInterval);
    resendInterval = setInterval(() => {
        timeLeft--;
        timerEl.innerText = `00:${timeLeft < 10 ? '0' : ''}${timeLeft}`;
        if (timeLeft <= 0) {
            clearInterval(resendInterval);
            timerEl.style.display = 'none';
            btnEl.style.display = 'inline';
        }
    }, 1000);
}

function showAuthError(msg) {
    const errEl = document.getElementById('auth-error');
    errEl.innerText = msg;
    errEl.style.display = 'block';
}

function hideAuthError() {
    document.getElementById('auth-error').style.display = 'none';
}

const authFormClassic = document.getElementById('auth-form-classic');
if (authFormClassic) {
    authFormClassic.addEventListener('submit', async (e) => {
        e.preventDefault();
        const username = document.getElementById('login-username').value;
        const password = document.getElementById('login-password').value;
        const btn = document.getElementById('btn-login-classic');

        btn.disabled = true;
        btn.innerText = "Authenticating...";
        hideAuthError();

        try {
            const res = await fetch(API + '/auth/login/', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ username, password })
            });
            const data = await res.json();

            if (res.ok) {
                localStorage.setItem('access_token', data.access);
                localStorage.setItem('refresh_token', data.refresh);
                localStorage.setItem('username', data.username);
                token = data.access;
                showDashboard();
            } else {
                throw new Error(data.error || "Invalid credentials");
            }
        } catch (err) {
            showAuthError(err.message);
        } finally {
            btn.disabled = false;
            btn.innerText = "Login Now";
        }
    });
}

// SMTP Email Auth (via 7shouters)
const authFormEmail = document.getElementById('auth-form-email');
if (authFormEmail) {
    authFormEmail.addEventListener('submit', async (e) => {
        e.preventDefault();
        const email = document.getElementById('login-email').value;
        const btn = document.getElementById('btn-login-email');

        btn.disabled = true;
        btn.innerText = "Sending Code...";
        hideAuthError();

        try {
            const res = await fetch(API + '/auth/send-otp/', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ phone: email, method: 'email' })
            });
            const data = await res.json();
            if (!res.ok) throw new Error(data.error || "Failed to send Email OTP");

            otpMethod = 'email';
            currentPhone = email;

            document.getElementById('auth-form-email').style.display = 'none';
            document.getElementById('auth-form-otp').style.display = 'block';
            document.getElementById('auth-subtitle').innerText = `We've sent a verification code to ${email}`;

            startResendTimer();
            hideAuthError();
        } catch (err) {
            showAuthError(err.message);
        } finally {
            btn.disabled = false;
            btn.innerText = "Get Verification Code";
        }
    });
}

// Google Auth Logic
const btnGoogle = document.getElementById('btn-google-login');
if (btnGoogle) {
    btnGoogle.addEventListener('click', async () => {
        hideAuthError();
        const provider = new firebase.auth.GoogleAuthProvider();
        try {
            const result = await firebase.auth().signInWithPopup(provider);
            const idToken = await result.user.getIdToken();
            await syncFirebaseLogin(idToken);
        } catch (err) {
            showAuthError(err.message);
        }
    });
}

// Helpers for unified Firebase Backend Sync
async function syncFirebaseLogin(idToken) {
    const res = await fetch(API + '/auth/firebase-login/', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ idToken })
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || "Backend Sync Failed");

    if (data.user_exists) {
        localStorage.setItem('access_token', data.access);
        localStorage.setItem('refresh_token', data.refresh);
        localStorage.setItem('username', data.username);
        token = data.access;
        showDashboard();
    } else {
        // Only trigger for phone users who need to set password
        hideAllAuthForms();
        document.getElementById('auth-form-password').style.display = 'block';
        document.getElementById('auth-subtitle').innerText = "Success! Now set a secure password for your new system account.";
    }
}

// Switching Logic
const hideAllAuthForms = () => {
    ['auth-form-classic', 'auth-form-phone', 'auth-form-email', 'auth-form-otp', 'auth-form-password'].forEach(id => {
        const el = document.getElementById(id);
        if (el) el.style.display = 'none';
    });
};

const showClassicForm = (e) => {
    if (e) e.preventDefault();
    hideAllAuthForms();
    document.getElementById('auth-form-classic').style.display = 'block';
    document.getElementById('social-divider').style.display = 'flex';
    document.getElementById('btn-google-login').style.display = 'flex';
    document.getElementById('auth-title').innerText = "Login Boss";
    document.getElementById('auth-subtitle').innerText = "Access your account with username & password";
    hideAuthError();
};

document.querySelectorAll('.switch-to-classic-btn').forEach(btn => {
    btn.onclick = showClassicForm;
});

const switchToPhone = document.getElementById('switch-to-phone');
if (switchToPhone) {
    switchToPhone.onclick = (e) => {
        e.preventDefault();
        hideAllAuthForms();
        document.getElementById('auth-form-phone').style.display = 'block';
        document.getElementById('auth-title').innerText = "Login with Phone";
        document.getElementById('auth-subtitle').innerText = "Enter your mobile number to get OTP";
        hideAuthError();
    };
}

const switchToEmail = document.getElementById('switch-to-email');
if (switchToEmail) {
    switchToEmail.onclick = (e) => {
        e.preventDefault();
        hideAllAuthForms();
        document.getElementById('auth-form-email').style.display = 'block';
        document.getElementById('auth-title').innerText = "Login with Email";
        document.getElementById('auth-subtitle').innerText = "Sign in using your email address";
        hideAuthError();
    };
}

const switchSignup = document.getElementById('btn-switch-signup');
if (switchSignup) {
    switchSignup.onclick = (e) => {
        e.preventDefault();
        hideAllAuthForms();
        document.getElementById('auth-form-phone').style.display = 'block';
        document.getElementById('auth-title').innerText = "Join the Platform";
        document.getElementById('auth-subtitle').innerText = "New operative? Register with your mobile number.";
        hideAuthError();
    };
}

// Step 1: Send OTP
const authFormPhone = document.getElementById('auth-form-phone');
if (authFormPhone) {
    authFormPhone.addEventListener('submit', async (e) => {
        e.preventDefault();
        const phone = document.getElementById('mobile-number').value;
        if (!/^\d{10}$/.test(phone)) return showAuthError("Please enter a valid 10-digit number");

        otpMethod = document.querySelector('input[name="otp-method"]:checked').value;
        currentPhone = '+91' + phone;
        const btn = document.getElementById('btn-send-otp');
        btn.disabled = true;
        btn.innerText = "Processing...";

        try {
            if (otpMethod === 'sms') {
                // Firebase SMS Path
                initRecaptcha();
                const appVerifier = window.recaptchaVerifier;
                confirmationResult = await firebase.auth().signInWithPhoneNumber(currentPhone, appVerifier);

                document.getElementById('auth-form-phone').style.display = 'none';
                document.getElementById('auth-form-otp').style.display = 'block';
                document.getElementById('auth-subtitle').innerText = `Firebase has sent a 6-digit SMS to ${currentPhone}`;
            } else {
                // WhatsApp Path (Via Backend Twilio/Meta)
                const res = await fetch(API + '/auth/send-otp/', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ phone: currentPhone, method: 'whatsapp' })
                });
                const data = await res.json();
                if (!res.ok) throw new Error(data.error || "Failed to send WhatsApp OTP");

                document.getElementById('auth-form-phone').style.display = 'none';
                document.getElementById('auth-form-otp').style.display = 'block';
                document.getElementById('auth-subtitle').innerText = `We've sent a WhatsApp verification code to ${currentPhone}`;
            }

            startResendTimer();
            hideAuthError();
        } catch (err) {
            console.error(err);
            showAuthError(err.message || "Failed to initiate verification");
            // Reset recaptcha if failed
            if (window.recaptchaVerifier) {
                window.recaptchaVerifier.render().then(widgetId => {
                    grecaptcha.reset(widgetId);
                });
            }
        } finally {
            btn.disabled = false;
            btn.innerText = "Get Verification Code";
        }
    });
}

// Step 2: Verify OTP
const authFormOtp = document.getElementById('auth-form-otp');
if (authFormOtp) {
    authFormOtp.addEventListener('submit', async (e) => {
        e.preventDefault();
        const otp = document.getElementById('otp-input').value;
        if (otp.length !== 6) return showAuthError("Please enter 6-digit OTP");

        const btn = document.getElementById('btn-verify-otp');
        btn.disabled = true;
        btn.innerText = "Verifying...";

        try {
            if (otpMethod === 'sms' && confirmationResult) {
                // Firebase Verification
                const result = await confirmationResult.confirm(otp);
                const idToken = await result.user.getIdToken();

                // Store currentPhone for the final register step if user doesn't exist
                currentOTP = otp;

                // Use unified sync helper
                await syncFirebaseLogin(idToken);
            } else {
                // Traditional Backend Verification (Twilio/WhatsApp)
                const res = await fetch(API + '/auth/verify-otp/', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ phone: currentPhone, otp: otp })
                });
                const data = await res.json();
                if (!res.ok) throw new Error(data.error || "Invalid OTP");

                currentOTP = otp;
                userExists = data.user_exists;

                document.getElementById('auth-form-otp').style.display = 'none';
                document.getElementById('auth-form-password').style.display = 'block';
                document.getElementById('password-label').innerText = userExists ? "Enter Account Password" : "Set New Account Password";
                document.getElementById('btn-finish-auth').innerText = userExists ? "Login to Dashboard" : "Create Account & Login";
                document.getElementById('auth-subtitle').innerText = userExists ? "Welcome back! Verification successful." : "Almost there! Create your password.";
            }
            hideAuthError();
        } catch (err) {
            showAuthError(err.message);
        } finally {
            btn.disabled = false;
            btn.innerText = "Verify & Continue";
        }
    });
}

// Step 3: Complete Auth
const authFormPassword = document.getElementById('auth-form-password');
if (authFormPassword) {
    authFormPassword.addEventListener('submit', async (e) => {
        e.preventDefault();
        const password = document.getElementById('final-password').value;
        const btn = document.getElementById('btn-finish-auth');
        btn.disabled = true;

        const payload = { phone: currentPhone, password: password };
        if (otpMethod === 'sms') {
            try {
                payload.firebaseToken = await firebase.auth().currentUser.getIdToken();
            } catch (e) { payload.otp = currentOTP; } // Fallback
        } else {
            payload.otp = currentOTP;
        }

        try {
            const res = await fetch(API + '/auth/register/', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload)
            });
            const data = await res.json();
            if (!res.ok) throw new Error(data.error || "Authentication failed");

            localStorage.setItem('access_token', data.access);
            localStorage.setItem('refresh_token', data.refresh);
            localStorage.setItem('username', data.username);
            token = data.access;

            showDashboard();
            hideAuthError();
        } catch (err) {
            showAuthError(err.message);
        } finally {
            btn.disabled = false;
        }
    });
}

const changeNumberBtn = document.getElementById('change-number-btn');
if (changeNumberBtn) {
    changeNumberBtn.addEventListener('click', (e) => {
        e.preventDefault();
        document.getElementById('auth-form-otp').style.display = 'none';
        document.getElementById('auth-form-phone').style.display = 'block';
        document.getElementById('auth-subtitle').innerText = "Enter your mobile number to get started";
    });
}

const resendOtpBtn = document.getElementById('resend-otp-btn');
if (resendOtpBtn) {
    resendOtpBtn.addEventListener('click', async (e) => {
        e.preventDefault();
        hideAuthError();
        try {
            const res = await fetch(API + '/auth/send-otp/', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ phone: currentPhone })
            });
            if (res.ok) {
                startResendTimer();
                alert("A new OTP has been sent!");
            }
        } catch (err) { showAuthError("Failed to resend"); }
    });
}

const logoutHandler = () => {
    localStorage.clear();
    token = null;
    if (activeJobsInterval) clearInterval(activeJobsInterval);
    showAuth();
};

// --- Settings & Profile Management ---
function setupSettingsListeners() {
    const editBtn = document.getElementById('edit-profile-btn');
    const saveBtn = document.getElementById('save-profile-btn');
    const cancelBtn = document.getElementById('cancel-profile-btn');
    const actionsRow = document.getElementById('settings-actions-row');

    const nameInp = document.getElementById('settings-name-display');
    const emailInp = document.getElementById('settings-email-display');
    const userInp = document.getElementById('settings-user-display-input');

    if (editBtn) {
        editBtn.addEventListener('click', () => {
            nameInp.readOnly = false;
            emailInp.readOnly = false;
            userInp.readOnly = false;
            nameInp.style.borderColor = 'var(--accent)';
            emailInp.style.borderColor = 'var(--accent)';
            userInp.style.borderColor = 'var(--accent)';
            nameInp.style.background = 'rgba(249,115,22,0.03)';
            emailInp.style.background = 'rgba(249,115,22,0.03)';
            userInp.style.background = 'rgba(249,115,22,0.03)';

            actionsRow.style.display = 'flex';
            editBtn.style.display = 'none';
        });
    }

    if (cancelBtn) {
        cancelBtn.addEventListener('click', () => {
            nameInp.readOnly = true;
            emailInp.readOnly = true;
            userInp.readOnly = true;
            nameInp.style.borderColor = 'transparent';
            emailInp.style.borderColor = 'transparent';
            userInp.style.borderColor = 'transparent';
            nameInp.style.background = 'none';
            emailInp.style.background = 'none';
            userInp.style.background = 'none';

            actionsRow.style.display = 'none';
            editBtn.style.display = 'flex';

            // Reset to original values
            const name = localStorage.getItem('username') || 'Admin User';
            const email = localStorage.getItem('user_email') || 'no-email@extractor.io';
            nameInp.value = name;
            emailInp.value = email;
            userInp.value = name.toLowerCase().replace(/\s+/g, '_');
        });
    }

    if (saveBtn) {
        saveBtn.addEventListener('click', async () => {
            saveBtn.disabled = true;
            saveBtn.innerText = 'Syncing...';

            try {
                const res = await fetchAPI('/auth/profile/update/', {
                    method: 'POST',
                    body: JSON.stringify({
                        username: userInp.value,
                        email: emailInp.value
                    })
                });

                const data = await res.json();
                if (!res.ok) throw new Error(data.error || 'Identity sync failed');

                // Persist successful changes
                localStorage.setItem('username', nameInp.value);
                localStorage.setItem('user_email', emailInp.value);

                alert('Protocol profile updated and synced successfully!');
                if (cancelBtn) cancelBtn.click(); // Reset UI mode

                // Refresh main sidebar display
                const sbUser = document.getElementById('sidebar-username');
                if (sbUser) sbUser.innerText = nameInp.value;

                // Update large avatar letter in profile
                const lAvatar = document.getElementById('profile-avatar-large');
                if (lAvatar) lAvatar.textContent = nameInp.value.charAt(0).toUpperCase();

                // Update top header name
                const profileTitle = document.getElementById('profile-full-name');
                if (profileTitle) profileTitle.textContent = nameInp.value;

            } catch (e) {
                alert('Update Error: ' + e.message);
            } finally {
                saveBtn.disabled = false;
                saveBtn.innerText = 'Save Protocol';
            }
        });
    }
}

// Ensure listeners are set up
if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', setupSettingsListeners);
} else {
    setupSettingsListeners();
}

const logoutBtn = document.getElementById('logout-btn');
if (logoutBtn) {
    logoutBtn.addEventListener('click', logoutHandler);
}

async function fetchAPI(endpoint, options = {}) {
    if (!options.headers) options.headers = {};
    options.headers['Authorization'] = `Bearer ${token}`;
    let res = await fetch(API + endpoint, options);
    if (res.status === 401) {
        localStorage.clear(); token = null; showAuth();
        throw new Error("Session expired");
    }
    return res;
}

function showAuth() {
    dashView.classList.remove('active');
    authView.classList.add('active');
    if (activeJobsInterval) clearInterval(activeJobsInterval);
}

function showDashboard() {
    authView.classList.remove('active');
    dashView.classList.add('active');

    // Sync user profile
    const user = localStorage.getItem('username') || 'Admin';
    const sideUser = document.getElementById('sidebar-username');
    if (sideUser) sideUser.innerText = `Welcome, ${user}`;
    const avatar = document.getElementById('user-avatar-btn');
    if (avatar) avatar.innerText = user.charAt(0).toUpperCase();

    // Fetch user profile to get package + allowed strategies
    fetchAPI('/auth/profile/').then(res => {
        if (res.ok) return res.json();
    }).then(data => {
        if (!data) return;
        userPackageName = data.package || 'Free';
        if (data.email) localStorage.setItem('user_email', data.email);
        if (data.allowed_strategies && Array.isArray(data.allowed_strategies)) {
            allowedStrategies = data.allowed_strategies;
        }
        // Show package badge in sidebar
        const pkgBadge = document.getElementById('sidebar-package-badge');
        const pkgFree = document.getElementById('sidebar-package-free');
        const isFree = userPackageName.toLowerCase() === 'free' || userPackageName.toLowerCase() === 'starter';
        if (pkgBadge) {
            if (!isFree) {
                pkgBadge.textContent = userPackageName;
                pkgBadge.style.display = 'inline-block';
                if (pkgFree) pkgFree.style.display = 'none';
            } else {
                pkgBadge.style.display = 'none';
                if (pkgFree) { pkgFree.textContent = 'Free Plan'; pkgFree.style.display = 'inline'; }
            }
        }
        applyStrategyLocks();
    }).catch(() => { /* profile fetch failed, keep defaults */ });

    switchNav('dashboard');
    fetchJobs();
    if (activeJobsInterval) clearInterval(activeJobsInterval);
    activeJobsInterval = setInterval(fetchJobs, 3000);
}

window.setViewMode = (mode) => {
    currentTableViewMode = mode;
    const btnAll = document.getElementById('view-mode-all');
    const btnSingle = document.getElementById('view-mode-single');
    const btnBulk = document.getElementById('view-mode-bulk');

    [btnAll, btnSingle, btnBulk].forEach(btn => {
        if (!btn) return;
        btn.style.background = 'transparent';
        btn.style.color = 'var(--text-muted)';
        btn.style.fontWeight = '600';
        btn.style.border = 'none';
        btn.style.boxShadow = 'none';
    });

    const activeBtn = document.getElementById('view-mode-' + mode);
    if (activeBtn) {
        activeBtn.style.background = 'var(--accent-light)';
        activeBtn.style.color = 'var(--accent)';
        activeBtn.style.border = '1px solid rgba(99, 102, 241, 0.2)';
        activeBtn.style.fontWeight = '700';
        activeBtn.style.borderRadius = '10px';
    }

    renderJobs(latestJobsCache);
};

// --- Input Validation ---
function validateInput(el, errorId) {
    const val = el.value;
    const errorEl = document.getElementById(errorId);
    if (!errorEl) return;

    // Regex allows: alphanumeric, spaces, hyphens, and ampersands
    // Note: for bulk mode we also need to allow newlines
    const regex = el.tagName === 'TEXTAREA' ? /[^a-zA-Z0-9\s\-\&\n]/ : /[^a-zA-Z0-9\s\-\&]/;

    if (regex.test(val)) {
        errorEl.style.display = 'block';
        el.style.borderColor = 'var(--danger)';
    } else {
        errorEl.style.display = 'none';
        el.style.borderColor = 'var(--border)';
    }
}

document.addEventListener('input', (e) => {
    if (e.target.id === 'keyword' || e.target.id === 'keyword-bulk') {
        validateInput(e.target, 'keyword-error');
    }
    if (e.target.id === 'location') {
        validateInput(e.target, 'location-error');
    }
});

window.setSearchMode = (mode) => {
    const searchForm = document.getElementById('search-form');
    if (searchForm) searchForm.dataset.mode = mode;

    const btnSingle = document.getElementById('mode-single');
    const btnMulti = document.getElementById('mode-multi');
    const btnState = document.getElementById('mode-state-country');
    const inputSingle = document.getElementById('keyword');
    const inputBulk = document.getElementById('keyword-bulk');

    // UI elements to update
    const keywordLabel = document.getElementById('keyword-label');
    const locationLabel = document.getElementById('location-label');
    const locationInput = document.getElementById('location');
    const strategyWrapper = document.querySelector('.strategy-wrapper');
    const addBtn = document.getElementById('add-keyword-btn');

    // Reset all buttons
    [btnSingle, btnMulti, btnState].forEach(btn => {
        if (btn) {
            btn.style.background = 'transparent';
            btn.style.color = 'var(--text-muted)';
            btn.style.fontWeight = '500';
        }
    });

    // Update labels and strategy visibility
    if (mode === 'state_country') {
        if (keywordLabel) keywordLabel.innerText = "Target Keyword";
        if (locationLabel) locationLabel.innerText = "State or Country Name";
        if (locationInput) locationInput.placeholder = "e.g. Texas or United Kingdom";
        if (strategyWrapper) strategyWrapper.style.display = 'none';
        if (addBtn) addBtn.style.display = 'none';
        const gridSizeGroup = document.getElementById('grid-size-group');
        if (gridSizeGroup) gridSizeGroup.style.display = 'block';
    } else {
        if (keywordLabel) keywordLabel.innerText = "Keywords";
        if (locationLabel) locationLabel.innerText = "Location";
        if (locationInput) locationInput.placeholder = "e.g. Mumbai";
        if (strategyWrapper) strategyWrapper.style.display = 'block';
        if (addBtn) addBtn.style.display = (mode === 'multi' ? 'flex' : 'none');
        const gridSizeGroup = document.getElementById('grid-size-group');
        if (gridSizeGroup) gridSizeGroup.style.display = 'none';
    }

    // Toggle cross buttons (delete keyword buttons)
    const delBtns = document.querySelectorAll('.keyword-delete-btn');
    delBtns.forEach(btn => {
        btn.style.visibility = (mode === 'multi' ? 'visible' : 'hidden');
    });

    const rowsContainer = document.getElementById('keyword-input-rows');
    if (!rowsContainer) return;

    if (mode === 'single' || mode === 'state_country') {
        const activeBtn = mode === 'single' ? btnSingle : btnState;
        if (activeBtn) {
            activeBtn.style.background = 'var(--accent)';
            activeBtn.style.color = 'white';
            activeBtn.style.fontWeight = '700';
        }

        const currentRows = rowsContainer.querySelectorAll('.keyword-row');
        if (currentRows.length > 1) {
            const firstVal = currentRows[0].querySelector('input').value;
            rowsContainer.innerHTML = '';
            addKeywordRow(firstVal);
        } else if (currentRows.length === 0) {
            addKeywordRow('');
        }
    } else if (mode === 'multi') {
        if (btnMulti) {
            btnMulti.style.background = 'var(--accent)';
            btnMulti.style.color = 'white';
            btnMulti.style.fontWeight = '700';
        }

        const currentRows = rowsContainer.querySelectorAll('.keyword-row');
        if (currentRows.length < 2) {
            while (rowsContainer.querySelectorAll('.keyword-row').length < 2) {
                addKeywordRow('');
            }
        }
    }
};

// Ensure initial state
document.addEventListener('DOMContentLoaded', () => {
    if (document.getElementById('search-form')) {
        setSearchMode('single');
        // Initial rows if empty
        const rows = document.getElementById('keyword-input-rows');
        if (rows && rows.children.length === 0) {
            addKeywordRow('');
            addKeywordRow('');
        }
    }

    // Attach event listener to the add button robustly
    const addBtn = document.getElementById('add-keyword-btn');
    if (addBtn) {
        addBtn.addEventListener('click', (e) => {
            e.preventDefault();
            addKeywordRow('');
        });
    }
});

// --- Start Run ---
const searchForm = document.getElementById('search-form');
if (searchForm) {
    searchForm.addEventListener('submit', async (e) => {
        e.preventDefault();
        // Collect keywords from dynamic rows
        const inputs = Array.from(document.querySelectorAll('.keyword-input-field'));
        let keywords = inputs.map(i => i.value.trim()).filter(k => k);

        const location = document.getElementById('location').value;
        const strategy = document.getElementById('strategy').value;
        const btn = document.getElementById('start-btn');

        // --- Client-side strategy access guard ---
        if (!allowedStrategies.includes(strategy)) {
            showUpgradePrompt(strategy);
            return;
        }

        if (keywords.length === 0) {
            alert("Please provide at least one keyword protocol.");
            return;
        }

        const mode = searchForm.dataset.mode || 'single';

        // Single search logic
        if ((mode === 'single' || mode === 'state_country') && keywords.length > 1) {
            keywords = [keywords[0]];
        }

        btn.disabled = true;
        btn.innerHTML = '<span style="font-size: 0.9rem;">Starting...</span>';

        // const mode = searchForm.dataset.mode || 'single'; // already declared above
        const search_type = mode === 'state_country' ? 'state_country' : 'city';
        // Only send grid_size if it's a state_country search (where the user actually controls it).
        // Otherwise, let the backend use the strategy map.
        const grid_size = (search_type === 'state_country') ? (document.getElementById('grid_size')?.value || 8) : undefined;

        try {
            const res = await fetchAPI('/jobs/start/', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    keywords: keywords,
                    location,
                    strategy: strategy,
                    search_type: search_type,
                    grid_size: grid_size
                })
            });

            if (res.ok) {
                // Reset keywords list to 2 default rows
                const rowsContainer = document.getElementById('keyword-input-rows');
                if (rowsContainer) {
                    rowsContainer.innerHTML = '';
                    addKeywordRow();
                    addKeywordRow();
                }
                document.getElementById('location').value = '';
                if (keywords.length > 1) {
                    setViewMode('bulk');
                } else {
                    setViewMode('single');
                }
                fetchJobs();
            } else {
                const data = await res.json();
                if (res.status === 403) {
                    showUpgradePrompt(strategy);
                } else {
                    alert(data.error || 'Failed to start job');
                }
            }
        } catch (e) {
            console.error(e);
        } finally {
            btn.disabled = false;
            btn.innerHTML = `<svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><line x1="5" y1="12" x2="19" y2="12"></line><polyline points="12 5 19 12 12 19"></polyline></svg>`;
        }
    });
}

// Show upgrade prompt when a locked strategy is attempted
function showUpgradePrompt(strategy) {
    const strategyNames = { deep: 'Deep Extraction (20×20)', ultra: 'Ultra Discovery (25×25)' };
    const name = strategyNames[strategy] || strategy;
    const modal = document.createElement('div');
    modal.style.cssText = 'position:fixed;inset:0;background:rgba(0,0,0,0.55);z-index:9999;display:flex;align-items:center;justify-content:center;backdrop-filter:blur(4px);';
    modal.innerHTML = `
        <div style="background:var(--card-bg);border:1px solid var(--border);border-radius:16px;padding:32px;max-width:420px;width:90%;text-align:center;box-shadow:0 20px 60px rgba(0,0,0,0.3);">
            <div style="width:52px;height:52px;background:linear-gradient(135deg,#f59e0b,#ef4444);border-radius:14px;display:flex;align-items:center;justify-content:center;margin:0 auto 16px;">
                <svg width="26" height="26" viewBox="0 0 24 24" fill="white"><path d="M18 11H6V8a6 6 0 0 1 12 0v3zM5 11V8a7 7 0 0 1 14 0v3a2 2 0 0 1 2 2v7a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-7a2 2 0 0 1 2-2zm7 5a1.5 1.5 0 1 0 0-3 1.5 1.5 0 0 0 0 3z"/></svg>
            </div>
            <h3 style="margin:0 0 8px;font-size:1.1rem;font-weight:800;color:var(--text-main);">Premium Strategy Required</h3>
            <p style="margin:0 0 6px;color:var(--text-muted);font-size:0.85rem;line-height:1.5;"><strong style="color:var(--text-main);">${name}</strong> is only available on paid plans.</p>
            <p style="margin:0 0 24px;color:var(--text-muted);font-size:0.8rem;line-height:1.5;">Your current plan is <strong>${userPackageName}</strong>. Upgrade to unlock deeper grid coverage and extract more leads.</p>
            <div style="display:flex;gap:10px;justify-content:center;">
                <button onclick="this.closest('div[style*=\"fixed\"]').remove()" style="padding:9px 20px;border-radius:8px;border:1px solid var(--border);background:var(--bg-color);color:var(--text-muted);font-weight:600;font-size:0.85rem;cursor:pointer;">Maybe Later</button>
                <button onclick="switchNav('packages');this.closest('div[style*=\"fixed\"]').remove();" style="padding:9px 20px;border-radius:8px;border:none;background:linear-gradient(135deg,var(--accent),#6366f1);color:white;font-weight:700;font-size:0.85rem;cursor:pointer;box-shadow:0 4px 14px var(--accent-soft);">View Plans ✦</button>
            </div>
        </div>
    `;
    document.body.appendChild(modal);
    modal.addEventListener('click', (e) => { if (e.target === modal) modal.remove(); });
}

// --- Render Runs ---
async function fetchJobs() {
    try {
        const res = await fetchAPI('/jobs/');
        if (!res.ok) return;
        const jobs = await res.json();
        if (Array.isArray(jobs)) {
            latestJobsCache = jobs;
            renderJobs(jobs);
        }
    } catch (e) { console.error(e); }
}

async function fetchJobStatus(jobId) {
    const res = await fetchAPI(`/jobs/${jobId}/status/`);
    if (res.ok) return await res.json();
    return null;
}

async function renderJobs(allJobs) {
    if (!allJobs) return;

    // Filter based on selected view mode
    let jobs = [...allJobs];
    if (currentTableViewMode === 'single') {
        jobs = allJobs.filter(j => j.keywords && j.keywords.length === 1);
    } else if (currentTableViewMode === 'bulk') {
        jobs = allJobs.filter(j => j.keywords && j.keywords.length > 1);
    }

    const tbody = document.getElementById('runs-table-body');
    const recentContainer = document.getElementById('recent-scans-summary');
    const runsListContent = document.getElementById('runs-list-content');
    const activitiesPanel = document.getElementById('activities-panel');

    // Detect if we are on the main scraper/dashboard view
    const isDashboard = runsListContent && runsListContent.style.display !== 'none';

    // 1. Handle Recent Scans Cards (Top 12 Slider)
    if (recentContainer) {
        if (isDashboard && jobs.length > 0) {
            recentContainer.style.display = 'flex'; // Use flex for slider
            const top12 = jobs.slice(0, 12);
            let cardsHtml = '';

            top12.forEach(job => {
                let badgeClass = 'RUNNING';
                if (job.status === 'completed') badgeClass = 'SUCCEEDED';
                if (job.status === 'failed') badgeClass = 'FAILED';
                if (job.status === 'pending') badgeClass = 'READY';

                const ks = job.keywords && job.keywords.length > 0 ? (typeof job.keywords[0] === 'string' ? job.keywords.join(', ') : job.keywords.map(k => k.keyword).join(', ')) : 'Extraction Task';
                const count = job.total_extracted || 0;

                let viewLink = '';
                let progressHtml = '';

                let totalDone = 0;
                let totalCellsSum = 0;
                if (job.keywords && job.keywords.length > 0) {
                    job.keywords.forEach(kj => {
                        totalDone += (kj.cells_done || 0);
                        totalCellsSum += (kj.total_cells || 0);
                    });
                }

                if (totalCellsSum > 0) {
                    let pct = Math.min(Math.round((totalDone / totalCellsSum) * 100), 100);

                    progressHtml = `
                        <div style="margin-top:12px; padding-top: 10px; border-top: 1px solid var(--border-light);">
                            <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom: 6px;">
                                <span style="font-size:0.7rem; font-weight:800; color:${job.status === 'completed' ? 'var(--success)' : (job.status === 'cancelled' ? 'var(--text-muted)' : (job.status === 'failed' ? 'var(--danger)' : 'var(--accent)'))}; text-transform:uppercase; letter-spacing:0.02em;">
                                    ${job.status === 'completed' ? 'Extraction Complete' : (job.status === 'cancelled' ? 'Protocol Terminated' : (job.status === 'failed' ? 'Search Failed' : 'In Progress'))}
                                </span>
                                <span style="font-size:0.75rem; color:var(--text-main); font-weight:800; font-family:'Outfit';">${pct}%</span>
                            </div>
                            <div style="width:100%; height:6px; background:var(--bg-color); border-radius:10px; overflow:hidden; border: 1px solid var(--border-light);">
                                <div style="width:${pct}%; height:100%; background:linear-gradient(90deg, var(--accent), #6366f1); border-radius:10px; transition: width 0.5s cubic-bezier(0.4, 0, 0.2, 1);"></div>
                            </div>
                            <div style="margin-top:4px; font-size:0.6rem; color:var(--text-light); font-weight:600; display:flex; justify-content:space-between;">
                                <span>${totalDone.toLocaleString()} cells done</span>
                                <span>Total: ${totalCellsSum.toLocaleString()}</span>
                            </div>
                        </div>
                    `;
                }

                if ((job.status === 'completed' || job.status === 'cancelled') && job.keywords && job.keywords.length > 0 && count > 0) {
                    const isBulk = job.keywords.length > 1;
                    const safeLoc = (job.location || "").replace(/'/g, "\\'");

                    if (isBulk) {
                        viewLink = `<button class="btn btn-blue" style="margin-top:12px; width:100%; border-radius:8px; font-size:0.8rem; font-weight:700; padding: 10px; letter-spacing:0.01em; box-shadow: 0 4px 10px var(--accent-soft);" onclick="viewJobResults(${job.bulk_job_id}, 'Master Dataset', '${safeLoc}', true)">Access Combined Leads</button>`;
                    } else {
                        const kjObj = job.keywords[0];
                        const safeKw = (kjObj.keyword || "").replace(/'/g, "\\'");
                        viewLink = `<button class="btn btn-blue" style="margin-top:12px; width:100%; border-radius:8px; font-size:0.8rem; font-weight:700; padding: 10px; letter-spacing:0.01em; box-shadow: 0 4px 10px var(--accent-soft);" onclick="viewJobResults(${kjObj.keyword_job_id}, '${safeKw}', '${safeLoc}', false)">Access Dataset</button>`;
                    }
                } else if (job.status === 'completed') {
                    viewLink = `<div style="margin-top:12px; font-size:0.75rem; color:var(--text-muted); font-weight:600; text-align:center;">Finalizing Protocol...</div>`;
                } else if (job.status === 'failed') {
                    viewLink = `<div style="margin-top:12px; font-size:0.75rem; color:var(--danger); font-weight:700; text-align:center; padding: 8px; background: rgba(239, 68, 68, 0.05); border-radius: 8px;">Error Occurred</div>`;
                } else if (job.status === 'cancelled') {
                    viewLink = `<div style="margin-top:12px; font-size:0.75rem; color:var(--text-muted); font-weight:700; text-align:center; padding: 8px; background: var(--bg-color); border: 1px dashed var(--border); border-radius: 8px;">Protocol Terminated</div>`;
                } else {
                    viewLink = `
                        <div style="margin-top:12px; display:flex; flex-direction:column; gap:8px;">
                            <div style="display:flex; align-items:center; justify-content:center; gap:8px; font-size:0.8rem; color:var(--accent); font-weight:700; padding: 10px; background: var(--accent-soft); border-radius: 8px;">
                                <div class="loading-spinner" style="width:14px; height:14px; border-width:2px; margin:0; border-top-color:var(--accent);"></div> 
                                Calibrating...
                            </div>
                            <button onclick="cancelJob(${job.bulk_job_id})" class="btn" style="width:100%; font-size:0.65rem; font-weight:800; color:var(--danger); background:rgba(239, 68, 68, 0.05); border:1px solid rgba(239, 68, 68, 0.1); border-radius:8px; padding:6px; text-transform:uppercase; letter-spacing:0.02em;">
                                Stop Protocol
                            </button>
                        </div>
                    `;
                }

                const dateStr = new Date(job.created_at).toLocaleString([], { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' });
                const cardTimerId = `card-timer-${job.bulk_job_id}`;
                if (liveTimerIntervals[cardTimerId]) {
                    clearInterval(liveTimerIntervals[cardTimerId]);
                    delete liveTimerIntervals[cardTimerId];
                }
                const staticDuration = jobDurationText(job);

                cardsHtml += `
                <div class="recent-card-wrapper">
                    <div class="panel premium-border" style="padding:18px; margin-bottom:0; display:flex; flex-direction:column; justify-content:space-between; background:var(--card-bg); position:relative; height:380px; transition: var(--transition); border-radius: 16px; box-shadow: 0 10px 30px rgba(0,0,0,0.05);">
                    <button onclick="deleteJob(${job.bulk_job_id})" style="position:absolute; top:14px; right:14px; background:var(--bg-color); border:1px solid var(--border-light); color:var(--text-light); cursor:pointer; padding:6px; border-radius:8px; transition:var(--transition); z-index:10;" onmouseover="this.style.color='var(--danger)'; this.style.background='rgba(239, 68, 68, 0.1)';" onmouseout="this.style.color='var(--text-light)'; this.style.background='var(--bg-color)';">
                        <svg viewBox="0 0 24 24" width="12" height="12" fill="none" stroke="currentColor" stroke-width="3.5"><polyline points="3 6 5 6 21 6"></polyline><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"></path></svg>
                    </button>
                    
                    <div style="flex: 1; display: flex; flex-direction: column; min-height: 0;">
                        <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:14px; padding-right: 36px; min-height: 24px;">
                            <div style="min-width: 0; flex: 1;">
                                <span class="status-badge ${badgeClass}" style="font-size: 0.62rem; padding: 4px 10px; font-weight:800; border-radius:6px; letter-spacing:0.02em; display:inline-flex; align-items:center; gap:6px; box-shadow: 0 2px 8px rgba(0,0,0,0.05); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; max-width: 100%;">
                                    <span>${job.status.toUpperCase()}</span>
                                    <span style="opacity: 0.6; font-weight: 300;">•</span>
                                    <span id="${cardTimerId}" data-done="${totalDone}" data-total="${totalCellsSum}" data-start="${job.created_at}" style="overflow: hidden; text-overflow: ellipsis;">${staticDuration !== null ? staticDuration.replace('✅ ', '') : '0s'}</span>
                                </span>
                            </div>
                            <span style="font-size:0.6rem; color:var(--text-light); font-weight:700; text-transform:uppercase; letter-spacing:0.02em; flex-shrink: 0; margin-left: 8px;">${dateStr}</span>
                        </div>
                        
                        <div style="margin-bottom: 2px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;">
                            <h3 style="margin:0; font-family: 'Outfit', sans-serif; font-size:1.05rem; font-weight:800; color:var(--text-main); line-height:1.2; letter-spacing:-0.01em; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;" title="${ks}">${ks}</h3>
                        </div>
                        
                        <div style="font-size:0.75rem; color:var(--text-muted); font-weight:600; margin-bottom:14px; display:flex; align-items:center; gap:5px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;">
                            <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3"><path d="M21 10c0 7-9 13-9 13s-9-6-9-13a9 9 0 0 1 18 0z"></path><circle cx="12" cy="10" r="3"></circle></svg>
                            <span style="overflow: hidden; text-overflow: ellipsis;">${job.location}</span>
                            <span style="color:var(--border); margin: 0 2px;">•</span>
                            <span style="color:${job.execution_mode === 'proxy' ? 'var(--success)' : 'var(--text-light)'}; font-weight:800; font-size:0.55rem; text-transform:uppercase; letter-spacing:0.02em;">${job.execution_mode === 'proxy' ? 'Gateway' : 'Direct'}</span>
                        </div>
                        
                        <div style="display:flex; align-items:center; justify-content:space-between; margin-bottom:12px; background: linear-gradient(135deg, var(--bg-color) 0%, var(--border-light) 100%); padding: 12px; border-radius: 10px; border: 1px solid var(--border-light); position:relative; overflow:hidden;">
                            <div style="position:absolute; right: -8px; top: -8px; opacity: 0.04; transform: rotate(-15deg);">
                                <svg width="60" height="60" viewBox="0 0 24 24" fill="var(--text-main)"><path d="M16 11c1.66 0 2.99-1.34 2.99-3S17.66 5 16 5s-3 1.34-3 3 1.34 3 3 3zm-8 0c1.66 0 2.99-1.34 2.99-3S9.66 5 8 5 5 6.34 5 8s1.34 3 3 3zm0 2c-2.33 0-7 1.17-7 3.5V19h14v-2.5c0-2.33-4.67-3.5-7-3.5zm8 0c-.29 0-.62.02-.97.05 1.16.84 1.97 1.97 1.97 3.45V19h6v-2.5c0-2.33-4.67-3.5-7-3.5z"></path></svg>
                            </div>
                            <div>
                                <div style="font-size:1.5rem; font-weight:850; color:var(--text-main); font-family: 'Outfit'; line-height:1; letter-spacing:-0.02em;">${count.toLocaleString()}</div>
                                <div style="font-size:0.65rem; font-weight:800; color:var(--accent); text-transform:uppercase; letter-spacing:0.08em; margin-top:2px;">Leads Uncovered</div>
                            </div>
                        </div>

                        ${progressHtml}
                    </div>
                    
                    <div style="margin-top: 12px;">
                        ${viewLink}
                    </div>
                </div>`;
            });

            recentContainer.innerHTML = cardsHtml;

            // Re-start timers
            top12.forEach(job => {
                const cardTimerId = `card-timer-${job.bulk_job_id}`;
                let totalDone = 0;
                let totalCellsSum = 0;
                if (job.keywords && job.keywords.length > 0) {
                    job.keywords.forEach(kj => {
                        totalDone += (kj.cells_done || 0);
                        totalCellsSum += (kj.total_cells || 0);
                    });
                }
                setTimeout(() => startLiveTimer(cardTimerId, job.created_at, totalDone, totalCellsSum), 0);
            });
        } else {
            recentContainer.innerHTML = '';
            recentContainer.style.display = 'none';
        }
    }

    // 2. Handle Activities Table (Full History)
    if (tbody) {
        if (jobs.length === 0) {
            tbody.innerHTML = '<tr><td colspan="7" style="text-align:center; padding:48px; color:var(--text-light); font-weight:600;">No search protocols found in your history.</td></tr>';
            return;
        }

        let rowsHtml = '';
        jobs.forEach(job => {
            try {
                let badgeClass = 'RUNNING';
                let displayStatus = 'RUNNING';
                if (job.status === 'completed') { badgeClass = 'SUCCEEDED'; displayStatus = 'DONE'; }
                if (job.status === 'failed') { badgeClass = 'FAILED'; displayStatus = 'FAIL'; }
                if (job.status === 'pending') { badgeClass = 'READY'; displayStatus = 'WAIT'; }

                const date = new Date(job.created_at).toLocaleString([], { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' });
                const count = job.total_extracted || 0;

                let actionBtn = '';
                if ((job.status === 'completed' || job.status === 'cancelled') && job.keywords && job.keywords.length > 0 && typeof job.keywords[0] === 'object' && count > 0) {
                    const isBulk = job.keywords.length > 1;
                    const safeLoc = (job.location || "").replace(/'/g, "\\'");

                    if (isBulk) {
                        actionBtn = `<a href="#" onclick="viewJobResults(${job.bulk_job_id}, 'Master Results', '${safeLoc}', true)" style="color:var(--accent); text-decoration:none; font-weight:800; font-size:0.75rem; display:block; margin-bottom:4px; border-bottom: 2px solid var(--accent-soft); padding-bottom: 2px;">View Master Dataset</a>`;
                    } else {
                        const kj = job.keywords[0];
                        const safeKw = (kj.keyword || "").replace(/'/g, "\\'");
                        actionBtn = `<a href="#" onclick="viewJobResults(${kj.keyword_job_id}, '${safeKw}', '${safeLoc}', false)" style="color:var(--accent); text-decoration:none; font-weight:700; font-size:0.75rem; display:block; margin-bottom:2px;">View Leads</a>`;
                    }
                } else if (job.status === 'failed') {
                    actionBtn = `<span style="color:var(--danger); font-size:0.7rem; font-weight:700;">Protocol Failed</span>`;
                } else {
                    let totalDone = 0;
                    let totalCellsSum = 0;
                    if (job.keywords && job.keywords.length > 0) {
                        job.keywords.forEach(kj => {
                            totalDone += (kj.cells_done || 0);
                            totalCellsSum += (kj.total_cells || 0);
                        });
                    }

                    if (totalCellsSum > 0) {
                        const pct_val = Math.min(Math.round((totalDone / totalCellsSum) * 100), 100);

                        const p_status = job.status === 'cancelled' ? 'Aborted' : (job.status === 'failed' ? 'Failed' : 'Active');
                        const p_color = job.status === 'cancelled' ? 'var(--text-muted)' : (job.status === 'failed' ? 'var(--danger)' : 'var(--accent)');

                        actionBtn = `
                            <div style="min-width: 100px;">
                                <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom: 3px;">
                                    <span style="font-size:0.65rem; font-weight:800; color:${p_color};">${p_status} ${pct_val}%</span>
                                    <span style="font-size:0.55rem; color:var(--text-light); font-weight:700;">${totalDone}/${totalCellsSum}</span>
                                </div>
                                <div style="width:100%; height:4px; background:var(--bg-color); border-radius:10px; overflow:hidden; border: 1px solid var(--border-light);">
                                    <div style="width:${pct_val}%; height:100%; background:linear-gradient(90deg, var(--accent), #6366f1); border-radius:10px;"></div>
                                </div>
                            </div>
                        `;
                    } else {
                        actionBtn = `<span style="color:var(--text-muted); font-size:0.75rem; font-weight:600;">Calibrating...</span>`;
                    }
                }

                let keywordsStr = "Loading...";
                if (job.keywords && job.keywords.length > 0) {
                    keywordsStr = (typeof job.keywords[0] === 'string') ? job.keywords.join(', ') : job.keywords.map(k => k.keyword).join(', ');
                }

                const rowTimerId = `row-timer-${job.bulk_job_id}`;
                if (liveTimerIntervals[rowTimerId]) {
                    clearInterval(liveTimerIntervals[rowTimerId]);
                    delete liveTimerIntervals[rowTimerId];
                }
                const rowStaticDuration = jobDurationText(job);
                const durationCell = rowStaticDuration !== null
                    ? `<span style="font-size:0.65rem; font-weight:700; color:${job.status === 'completed' ? 'var(--success)' : 'var(--text-muted)'}">${rowStaticDuration}</span>`
                    : `<span id="${rowTimerId}" style="font-size:0.65rem; font-weight:700; color:var(--accent);">⏱ Loading...</span>`;

                rowsHtml += `
                    <tr id="run-row-${job.bulk_job_id}">
                        <td><span class="status-badge ${badgeClass}" style="font-size:0.55rem; padding: 3px 6px;">${displayStatus}</span></td>
                        <td style="font-weight:800; color:${job.execution_mode === 'proxy' ? 'var(--success)' : 'var(--text-light)'}; font-size:0.65rem; letter-spacing:0.02em;">${job.execution_mode === 'proxy' ? 'GATEWAY' : 'DIRECT'}</td>
                        <td style="font-size:0.75rem; color:var(--text-muted); font-weight:600;">${date}</td>
                        <td style="font-weight:800; font-size:0.8rem;">${count.toLocaleString()}</td>
                        <td>
                            <div style="font-weight:700; color:var(--text-main); font-size:0.8rem; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; max-width: 180px;">${keywordsStr}</div>
                            <div style="font-size:0.65rem; color:var(--text-light); font-weight:600; text-transform:uppercase; letter-spacing:0.01em;">${job.location}</div>
                        </td>
                        <td>${actionBtn}</td>
                        <td>${durationCell}</td>
                        <td style="text-align: center;">
                            <button onclick="deleteJob(${job.bulk_job_id})" style="background:transparent; border:none; color:var(--text-light); cursor:pointer; padding: 4px; border-radius: 4px; transition: var(--transition);" onmouseover="this.style.color='var(--danger)';" onmouseout="this.style.color='var(--text-light)';">
                                <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="3"><polyline points="3 6 5 6 21 6"></polyline><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"></path></svg>
                            </button>
                        </td>
                    </tr>
                `;
            } catch (err) {
                console.error("Error rendering row:", err);
            }
        });
        tbody.innerHTML = rowsHtml;

        // Start live timers for running rows
        jobs.forEach(job => {
            const rowStaticDuration = jobDurationText(job);
            if (rowStaticDuration === null) {
                const rowTimerId = `row-timer-${job.bulk_job_id}`;
                let totalDone = 0;
                let totalCellsSum = 0;
                if (job.keywords && job.keywords.length > 0) {
                    job.keywords.forEach(kj => {
                        totalDone += (kj.cells_done || 0);
                        totalCellsSum += (kj.total_cells || 0);
                    });
                }
                setTimeout(() => startLiveTimer(rowTimerId, job.created_at, totalDone, totalCellsSum), 0);
            }
        });
    }

    if (activitiesPanel) {
        activitiesPanel.style.display = 'block';
    }
}

// --- Delete Run ---
window.deleteJob = async (jobId) => {
    if (!confirm('Are you sure you want to delete this scrape run and all its extracted data?')) return;
    try {
        const res = await fetchAPI(`/jobs/${jobId}/`, { method: 'DELETE' });
        if (res.ok) fetchJobs();
    } catch (e) {
        console.error(e);
        alert("Failed to delete the job.");
    }
};

window.cancelJob = async (jobId) => {
    if (!confirm('Abort the mission? This will stop the scraper at the current cell and finalize existing data.')) return;
    try {
        const res = await fetchAPI(`/jobs/${jobId}/cancel/`, { method: 'POST' });
        if (res.ok) fetchJobs();
    } catch (e) {
        console.error(e);
        alert("Failed to cancel the job.");
    }
};

let currentDetailResults = [];
let availableFields = [];
let selectedFields = new Set();

window.viewJobResults = async (id, keyword, location, isBulk = false) => {
    currentDetailJobId = id;
    currentDetailIsBulk = isBulk;
    switchNav('run-details');

    const keywordTitle = document.getElementById('card-keyword-title');
    const locationEl = document.getElementById('card-location');
    const countEl = document.getElementById('card-count');

    if (keywordTitle) keywordTitle.innerText = keyword;
    if (locationEl) locationEl.innerText = location;
    if (countEl) countEl.innerText = '...';

    const tbody = document.getElementById('results-table-body');
    const theadRow = document.getElementById('results-table-header');

    if (tbody) tbody.innerHTML = '<tr><td colspan="100%" style="text-align:center; padding: 48px;"><div class="loading-spinner"></div> Loading results...</td></tr>';
    if (theadRow) theadRow.innerHTML = '';

    try {
        const endpoint = isBulk ? `/jobs/${id}/results/` : `/keyword/${id}/results/`;
        const res = await fetchAPI(endpoint);
        if (!res.ok) throw new Error("Failed connecting to dataset");
        const respData = await res.json();
        const places = respData.results || [];
        currentDetailResults = places;

        if (countEl) countEl.innerText = places.length;

        if (places.length === 0) {
            if (tbody) tbody.innerHTML = '<tr><td colspan="100%" style="text-align:center; padding:48px; color:var(--text-muted);">No results found for this dataset.</td></tr>';
            return;
        }

        // RESET field selection for fresh dataset view to ensure Address matches
        selectedFields = new Set();

        // Identify all available fields from the records
        const fieldSet = new Set();
        places.slice(0, 15).forEach(p => {
            Object.keys(p).forEach(k => {
                if (k !== 'id' && k !== 'keyword_job') fieldSet.add(k);
            });
        });
        availableFields = Array.from(fieldSet).sort();

        // Initialize selection with priority fields (Name and ANY address variant)
        const commonFields = ['name', 'full_address', 'address', 'phone', 'rating', 'review_count', 'city', 'street'];
        availableFields.forEach(f => {
            if (commonFields.includes(f)) selectedFields.add(f);
        });

        // Remove website/rating from default if user feels it's unnecessary (as per feedback)
        // We'll keep Rating but remove Website as it's the "last section" usually
        selectedFields.delete('website');
        // reviews visibility restored

        renderTable();
        renderFieldList();

    } catch (e) {
        console.error("View results error:", e);
        if (tbody) tbody.innerHTML = `<tr><td colspan="100%" style="text-align:center; padding:48px; color:var(--danger);">Error: ${e.message}</td></tr>`;
    }
};

let currentResultTab = 'overview';

const fieldLabels = {
    'name': { title: 'Place name', sub: 'title' },
    'rating': { title: 'Total Score', sub: 'totalScore' },
    'review_count': { title: 'Review Count', sub: 'reviewsCount' },
    'full_address': { title: 'Address', sub: 'fullAddress' },
    'street': { title: 'Street', sub: 'street' },
    'city': { title: 'City', sub: 'city' },
    'state': { title: 'State', sub: 'state' },
    'country_code': { title: 'Country Code', sub: 'countryCode' },
    'website': { title: 'Website', sub: 'website' },
    'phone': { title: 'Phone', sub: 'phone' },
    'category': { title: 'Categories', sub: 'categories' },
    'categories': { title: 'Categories', sub: 'categories' },
    'source_keyword': { title: 'Keyword Source', sub: 'keyword' },
    'maps_url': { title: 'URL', sub: 'url' },
    'url': { title: 'URL', sub: 'url' }
};

window.setResultTab = (tab) => {
    currentResultTab = tab;
    const items = document.querySelectorAll('.sub-nav-item');
    items.forEach(item => {
        item.classList.remove('active');
        // Use data-tab or text content to match
        const text = item.innerText.toLowerCase();
        if (tab === 'overview' && text.includes('overview')) item.classList.add('active');
        else if (tab === 'contact' && text.includes('contact')) item.classList.add('active');
        else if (tab === 'social' && text.includes('social')) item.classList.add('active');
        else if (tab === 'rating' && text.includes('rating')) item.classList.add('active');
        else if (tab === 'reviews' && text.includes('reviews')) item.classList.add('active');
        else if (tab === 'leads' && text.includes('leads')) item.classList.add('active');
        else if (tab === 'all' && text.includes('all')) item.classList.add('active');
    });

    // Re-render table with tab-specific filtered fields
    renderTable();
};

function renderTable() {
    const tbody = document.getElementById('results-table-body');
    const theadRow = document.getElementById('results-table-header');
    const places = currentDetailResults;

    if (!tbody || !theadRow) return;

    // Determine which fields to show based on tab
    let displayFields = [];
    if (currentResultTab === 'overview') {
        displayFields = ['name', 'rating', 'review_count', 'street', 'city', 'phone', 'category', 'website'];
        if (currentDetailIsBulk) displayFields.splice(1, 0, 'source_keyword');
    } else if (currentResultTab === 'contact') {
        displayFields = ['name', 'phone', 'website', 'street', 'city', 'state'];
    } else if (currentResultTab === 'social') {
        // If social fields ever get added, they go here
        displayFields = ['name', 'facebook', 'instagram', 'linkedin', 'twitter'].filter(f => availableFields.includes(f));
        if (displayFields.length <= 1) displayFields = ['name', 'website', 'maps_url']; // Fallback
    } else if (currentResultTab === 'rating') {
        displayFields = ['name', 'rating', 'review_count'];
    } else if (currentResultTab === 'reviews') {
        displayFields = ['name', 'rating', 'review_count', 'reviews_text']; // reviews_text as future-proof
        displayFields = displayFields.filter(f => availableFields.includes(f) || ['name', 'rating', 'review_count'].includes(f));
    } else if (currentResultTab === 'leads') {
        displayFields = ['name', 'email', 'phone', 'website'];
        displayFields = displayFields.filter(f => availableFields.includes(f) || ['name', 'phone', 'website'].includes(f));
    } else if (currentResultTab === 'all') {
        displayFields = availableFields;
    } else {
        displayFields = availableFields;
    }

    // Filter by selected fields from config modal (if user feels it's unnecessary)
    const sortedFields = displayFields.filter(f => selectedFields.has(f) || currentResultTab !== 'all');

    theadRow.innerHTML = '';
    theadRow.parentElement.parentElement.classList.add('table-dense');

    // Add # column
    const thNum = document.createElement('th');
    thNum.innerHTML = '#';
    theadRow.appendChild(thNum);

    sortedFields.forEach(f => {
        const th = document.createElement('th');
        const label = fieldLabels[f] || { title: f.replace(/_/g, ' '), sub: f };
        th.innerHTML = `
            <div style="display:flex; flex-direction:column;">
                <span>${label.title}</span>
                <span class="header-subtext">${label.sub}</span>
            </div>
        `;
        theadRow.appendChild(th);
    });

    tbody.innerHTML = '';
    places.forEach((place, idx) => {
        const tr = document.createElement('tr');
        let cellHtml = `<td>${idx + 1}</td>`;
        sortedFields.forEach(f => {
            let val = place[f] || '-';

            if (f === 'category' || f === 'categories') {
                const items = (val && val !== '-') ? (val.includes(',') ? val.split(',') : [val]) : [];
                if (items.length === 1) {
                    val = `<span class="item-badge" style="background:rgba(249,115,22,0.1); color:var(--accent); font-weight:700; margin-right: 4px;">${items[0]}</span>`;
                } else if (items.length > 1) {
                    val = `<span class="item-badge" style="margin-right: 4px;">${items.length} items</span>`;
                } else {
                    val = `<span class="item-badge" style="opacity:0.5; margin-right: 4px;">-</span>`;
                }
            } else if (f === 'website' || f === 'maps_url' || f === 'url') {
                if (val !== '-') {
                    val = `<a href="${val}" target="_blank" style="color:var(--accent); text-decoration:none; font-size:0.8rem; opacity:0.8; overflow:hidden; text-overflow:ellipsis; display:block; max-width:220px;">${val}</a>`;
                }
            }

            cellHtml += `<td>${val}</td>`;
        });
        tr.innerHTML = cellHtml;
        tbody.appendChild(tr);
    });
}

function renderFieldList() {
    const list = document.getElementById('field-list');
    if (!list) return;
    list.innerHTML = '';
    availableFields.forEach(field => {
        const label = document.createElement('label');
        label.style.cssText = "display:flex; align-items:center; gap:8px; padding:8px 12px; background:var(--bg-color); border-radius:8px; cursor:pointer; font-size:0.85rem; border: 1px solid var(--border-light);";

        const input = document.createElement('input');
        input.type = 'checkbox';
        input.checked = selectedFields.has(field);
        input.onchange = () => {
            if (input.checked) selectedFields.add(field);
            else selectedFields.delete(field);
            renderTable();
        };

        label.appendChild(input);
        label.appendChild(document.createTextNode(field.replace(/_/g, ' ')));
        list.appendChild(label);
    });
}

window.selectAllFields = (val) => {
    if (val) availableFields.forEach(f => selectedFields.add(f));
    else selectedFields.clear();
    renderTable();
    renderFieldList();
};

const configBtn = document.getElementById('configure-fields-btn');
if (configBtn) {
    configBtn.onclick = () => {
        const modal = document.getElementById('field-modal');
        if (modal) modal.style.display = 'flex';
    };
}

// --- Export logic ---
const dlCsvBtn = document.getElementById('dl-csv-btn');
if (dlCsvBtn) {
    dlCsvBtn.onclick = () => {
        if (currentDetailResults.length === 0) return alert("Nothing to export");
        const fields = availableFields.filter(f => selectedFields.has(f));
        // Add BOM for Excel compatibility (\uFEFF)
        const header = "\uFEFF" + fields.join(',');
        const rows = currentDetailResults.map(row => {
            return fields.map(f => {
                const v = row[f] || '';
                return `"${String(v).replace(/"/g, '""')}"`;
            }).join(',');
        });

        const csvContent = [header, ...rows].join('\r\n');
        const blob = new Blob([csvContent], { type: 'text/csv;charset=utf-8;' });
        const url = window.URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        const keywordTitle = document.getElementById('card-keyword-title');
        const filename = keywordTitle ? keywordTitle.innerText.replace(/\s+/g, '_') : 'dataset';
        a.download = `Results_${filename}.csv`;
        a.click();
    };
}

const dlJsonBtn = document.getElementById('dl-json-btn');
if (dlJsonBtn) {
    dlJsonBtn.onclick = () => {
        if (currentDetailResults.length === 0) return alert("Nothing to export");
        const fields = availableFields.filter(f => selectedFields.has(f));
        const filtered = currentDetailResults.map(row => {
            const obj = {};
            fields.forEach(f => obj[f] = row[f]);
            return obj;
        });

        const blob = new Blob([JSON.stringify(filtered, null, 2)], { type: 'application/json' });
        const url = window.URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        const keywordTitle = document.getElementById('card-keyword-title');
        const filename = keywordTitle ? keywordTitle.innerText.replace(/\s+/g, '_') : 'dataset';
        a.download = `Results_${filename}.json`;
        a.click();
    };
}

const gdriveBtn = document.getElementById('save-gdrive-btn');
if (gdriveBtn) {
    gdriveBtn.onclick = async () => {
        if (currentDetailResults.length === 0) return alert("Nothing to export");

        // Generate CSV content for Drive upload
        const fields = availableFields.filter(f => selectedFields.has(f));
        const csvRows = [fields.join(',')];
        currentDetailResults.forEach(row => {
            const vals = fields.map(f => {
                const v = row[f] || '';
                return `"${String(v).replace(/"/g, '""')}"`;
            });
            csvRows.push(vals.join(','));
        });

        const blob = new Blob([csvRows.join('\n')], { type: 'text/csv' });
        const keywordTitle = document.getElementById('card-keyword-title');
        const filename = keywordTitle ? `Results_${keywordTitle.innerText.replace(/\s+/g, '_')}.csv` : 'Results_dataset.csv';

        // Call the uploadToDrive function added in the previous turn
        if (window.uploadToDrive) {
            await window.uploadToDrive(blob, filename);
        } else {
            alert("Google Drive integration is not ready.");
        }
    };
}

// --- Payment Integration Initialization ---
window.initiatePayment = async (packageId, name, label, price) => {
    console.log("Initiating payment protocol sync for:", name);
    const modal = document.getElementById('payment-modal');

    // Save package reference for the modal's proceed button to use
    window.selectedPackageId = packageId;

    // Fallback names/prices
    const packageName = name || 'Subscription Plan';
    const pkgLabel = label || 'Protocol';
    let priceText = price || '$0';

    try {
        // Update Premium Modal UI Elements
        if (document.getElementById('pm-package-type')) document.getElementById('pm-package-type').textContent = packageName;
        if (document.getElementById('pm-tier-label')) document.getElementById('pm-tier-label').textContent = pkgLabel;

        // Ensure price has currency symbol
        if (!priceText.includes('$')) priceText = '$' + priceText;

        if (document.getElementById('pm-calc')) document.getElementById('pm-calc').textContent = `1 protocol x ${priceText}`;
        if (document.getElementById('pm-total')) document.getElementById('pm-total').textContent = `= ${priceText} (USD)`;

        // Initial visual mock info for the card side panel
        if (document.getElementById('v-card-name')) document.getElementById('v-card-name').value = (localStorage.getItem('username') || 'PLAYER ONE').toUpperCase();
        if (document.getElementById('v-card-num')) document.getElementById('v-card-num').value = '4242 4242 4242 4242';

        if (modal) modal.style.display = 'flex';
    } catch (err) {
        console.error("Payment UI Error:", err);
    }
};

// --- Start App ---
if (token) {
    showDashboard();
} else {
    showAuth();
}

// --- Input Sanitation ---
['keyword', 'location'].forEach(id => {
    const el = document.getElementById(id);
    if (el) {
        el.addEventListener('input', (e) => {
            const sanitized = e.target.value.replace(/[^a-zA-Z0-9\s\-\&]/g, '');
            if (sanitized !== e.target.value) {
                e.target.value = sanitized;
            }
        });
    }
});

// ============================================================
// GOOGLE DRIVE INTEGRATION
// ------------------------------------------------------------
// SETUP: Create a Google Cloud project, enable the Drive API,
// configure OAuth consent screen, then create an OAuth 2.0
// client ID (Web application). Paste it below.
// Authorized JS origins: http://localhost:8000
// Authorized redirect URIs: (leave empty for implicit flow)
// ============================================================
const GDRIVE_CLIENT_ID = '458316904083-ens3cjb5qrmbknovb7batt1p4f5hi29r.apps.googleusercontent.com';
const GDRIVE_SCOPES = [
    'https://www.googleapis.com/auth/drive.file',          // create/manage files this app makes
    'https://www.googleapis.com/auth/drive.metadata.readonly' // read storage quota
].join(' ');

let gdriveTokenClient = null;
let gdriveAccessToken = localStorage.getItem('gdrive_token') || null;
let gdriveEmail = localStorage.getItem('gdrive_email') || null;

// Format bytes to human‑readable string
function formatBytes(bytes) {
    if (!bytes || bytes <= 0) return '0 B';
    const gb = bytes / (1024 ** 3);
    if (gb >= 1) return gb.toFixed(2) + ' GB';
    const mb = bytes / (1024 ** 2);
    if (mb >= 1) return mb.toFixed(0) + ' MB';
    return (bytes / 1024).toFixed(0) + ' KB';
}

// Update the sidebar Drive widget UI
function renderDriveWidget(connected) {
    const disc = document.getElementById('gdrive-disconnected');
    const conn = document.getElementById('gdrive-connected');
    if (!disc || !conn) return;
    if (connected) {
        disc.style.display = 'none';
        conn.style.display = 'block';
        const emailEl = document.getElementById('gdrive-email');
        if (emailEl && gdriveEmail) emailEl.textContent = gdriveEmail;
    } else {
        disc.style.display = 'flex';
        conn.style.display = 'none';
    }
}

// Fetch Drive storage quota and render the bar
async function fetchDriveStorage() {
    if (!gdriveAccessToken) return;
    try {
        const res = await fetch('https://www.googleapis.com/drive/v3/about?fields=storageQuota,user', {
            headers: { 'Authorization': 'Bearer ' + gdriveAccessToken }
        });
        if (!res.ok) {
            if (res.status === 401) { disconnectGoogleDrive(); return; }
            throw new Error('Drive API error ' + res.status);
        }
        const data = await res.json();
        const quota = data.storageQuota || {};
        const used = parseInt(quota.usage || 0);
        const total = parseInt(quota.limit || 0);
        const free = total - used;
        const pct = total > 0 ? Math.min((used / total) * 100, 100) : 0;
        const color = pct > 85 ? '#ea4335' : pct > 65 ? '#fbbc04' : '#4285f4';

        // Update sidebar email if we have user info
        if (data.user && data.user.emailAddress) {
            gdriveEmail = data.user.emailAddress;
            localStorage.setItem('gdrive_email', gdriveEmail);
            const emailEl = document.getElementById('gdrive-email');
            if (emailEl) emailEl.textContent = gdriveEmail;
        }

        const textEl = document.getElementById('gdrive-storage-text');
        const barEl = document.getElementById('gdrive-storage-bar');
        const freeEl = document.getElementById('gdrive-storage-free');
        if (textEl) textEl.textContent = `${formatBytes(used)} of ${formatBytes(total)} used`;
        if (barEl) {
            barEl.style.width = pct.toFixed(1) + '%';
            barEl.style.background = '#10b981';
        }
        if (freeEl) freeEl.textContent = `${formatBytes(free)} free`;

        renderDriveWidget(true);
    } catch (e) {
        console.warn('Drive storage fetch failed:', e.message);
    }
}

// Connect Google Drive — triggers OAuth popup
window.connectGoogleDrive = function () {
    if (GDRIVE_CLIENT_ID === 'YOUR_GOOGLE_CLIENT_ID.apps.googleusercontent.com') {
        alert('Google Drive: Please set your GDRIVE_CLIENT_ID in app.js.\n\nGo to console.cloud.google.com → APIs & Services → Credentials → Create OAuth 2.0 Client ID.');
        return;
    }
    // Wait for Google Identity Services to load
    const tryConnect = () => {
        if (typeof google === 'undefined' || !google.accounts) {
            setTimeout(tryConnect, 500);
            return;
        }
        gdriveTokenClient = google.accounts.oauth2.initTokenClient({
            client_id: GDRIVE_CLIENT_ID,
            scope: GDRIVE_SCOPES,
            callback: (tokenResponse) => {
                if (tokenResponse.error) {
                    console.error('Drive auth error:', tokenResponse.error);
                    return;
                }
                gdriveAccessToken = tokenResponse.access_token;
                localStorage.setItem('gdrive_token', gdriveAccessToken);
                fetchDriveStorage(); // also calls renderDriveWidget(true) on success
            }
        });
        gdriveTokenClient.requestAccessToken({ prompt: 'consent' });
    };
    tryConnect();
};

// Disconnect Google Drive
window.disconnectGoogleDrive = function () {
    if (gdriveAccessToken && typeof google !== 'undefined' && google.accounts) {
        google.accounts.oauth2.revoke(gdriveAccessToken, () => { });
    }
    gdriveAccessToken = null;
    gdriveEmail = null;
    localStorage.removeItem('gdrive_token');
    localStorage.removeItem('gdrive_email');
    renderDriveWidget(false);
};

// Upload a Blob (CSV or JSON) directly to user's Google Drive
// Returns a promise that resolves to the Drive file URL
window.uploadToDrive = async function (blob, filename) {
    if (!gdriveAccessToken) {
        const wantConnect = confirm('Connect Google Drive to save this file?\n\nClick OK to connect, then try saving again.');
        if (wantConnect) connectGoogleDrive();
        return null;
    }

    // Show uploading toast
    const toast = document.createElement('div');
    toast.style.cssText = 'position:fixed; bottom:24px; right:24px; background:var(--card-bg); border:1px solid var(--border); border-radius:12px; padding:14px 18px; display:flex; align-items:center; gap:10px; box-shadow:0 8px 30px rgba(0,0,0,0.15); z-index:9999; font-size:0.82rem; font-weight:600; color:var(--text-main); transition:opacity 0.3s;';
    toast.innerHTML = `<div class="loading-spinner" style="width:16px;height:16px;border-width:2px;margin:0;border-top-color:#4285f4;"></div> Uploading to Drive…`;
    document.body.appendChild(toast);

    try {
        const meta = JSON.stringify({ name: filename, mimeType: blob.type });
        const form = new FormData();
        form.append('metadata', new Blob([meta], { type: 'application/json' }));
        form.append('file', blob);

        const res = await fetch('https://www.googleapis.com/upload/drive/v3/files?uploadType=multipart&fields=id,webViewLink', {
            method: 'POST',
            headers: { 'Authorization': 'Bearer ' + gdriveAccessToken },
            body: form
        });

        if (!res.ok) {
            if (res.status === 401) {
                disconnectGoogleDrive();
                throw new Error('Session expired. Please reconnect Google Drive.');
            }
            throw new Error('Upload failed: ' + res.status);
        }
        const fileData = await res.json();

        toast.innerHTML = `
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#34a853" stroke-width="2.5"><polyline points="20 6 9 17 4 12"/></svg>
            <span>Saved to Drive</span>
            <a href="${fileData.webViewLink}" target="_blank" style="color:#4285f4; font-weight:700; text-decoration:none;">Open ↗</a>`;
        setTimeout(() => { toast.style.opacity = '0'; setTimeout(() => toast.remove(), 300); }, 4000);

        // Refresh storage bar
        setTimeout(fetchDriveStorage, 1000);
        return fileData.webViewLink;
    } catch (err) {
        toast.innerHTML = `<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="var(--danger)" stroke-width="2.5"><circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/></svg> ${err.message}`;
        setTimeout(() => { toast.style.opacity = '0'; setTimeout(() => toast.remove(), 300); }, 4000);
        return null;
    }
};

// Restore Drive session on page load (token may still be valid)
(function initDriveSession() {
    if (gdriveAccessToken) {
        fetchDriveStorage();
    } else {
        renderDriveWidget(false);
    }
})();
// --- User Profile Dashboard ---
window.switchProfileTab = (tab) => {
    document.querySelectorAll('.profile-tab').forEach(t => {
        t.classList.remove('active-tab');
        t.style.borderColor = 'transparent';
        t.style.color = 'var(--text-muted)';
        t.style.opacity = '0.6';
    });

    // Simple mock tab switching (only 'view' is implemented)
    const active = event ? event.currentTarget : document.querySelector('.profile-tab');
    if (active) {
        active.classList.add('active-tab');
        active.style.borderColor = 'var(--accent)';
        active.style.color = 'var(--accent)';
        active.style.opacity = '1';
    }
};

window.loadUserProfile = async () => {
    // Basic local restoration (immediate UI response)
    const localUsername = localStorage.getItem('username') || 'Admin User';
    const localEmail = localStorage.getItem('user_email') || 'Fetching...';

    // UI Elements
    const avatar = document.getElementById('profile-avatar-large');
    const fullName = document.getElementById('profile-full-name');
    const userDisplayInput = document.getElementById('settings-user-display-input');
    const nameInput = document.getElementById('settings-name-display');
    const emailInput = document.getElementById('settings-email-display');
    const history = document.getElementById('login-history-list');

    if (avatar) avatar.textContent = localUsername.charAt(0).toUpperCase();
    if (fullName) fullName.textContent = localUsername;
    if (userDisplayInput) userDisplayInput.value = localUsername.toLowerCase().replace(/\s+/g, '_');
    if (nameInput) nameInput.value = localUsername;
    if (emailInput) emailInput.value = localEmail;

    // Fetch REAL data from backend API
    try {
        const res = await fetchAPI('/auth/profile/');
        if (res.ok) {
            const data = await res.json();

            // Sync with backend truth
            if (avatar) avatar.textContent = data.username.charAt(0).toUpperCase();
            if (fullName) fullName.textContent = data.username;
            if (userDisplayInput) userDisplayInput.value = data.username;
            if (nameInput) nameInput.value = data.username;
            if (emailInput) emailInput.value = data.email || 'No email set';

            // Update Stats from backend/cache
            const totalLeads = latestJobsCache.reduce((sum, job) => sum + (job.total_extracted || 0), 0);
            const totalUnits = latestJobsCache.length;
            const totalBulk = latestJobsCache.filter(j => j.is_bulk).length;

            if (document.getElementById('stat-leads')) document.getElementById('stat-leads').textContent = totalLeads.toLocaleString();
            if (document.getElementById('stat-units')) document.getElementById('stat-units').textContent = totalUnits;
            if (document.getElementById('stat-bulk')) document.getElementById('stat-bulk').textContent = totalBulk;

            // Subscription Card Sync
            const subProgress = document.getElementById('sub-progress-bar');
            const searchLimit = parseInt(localStorage.getItem('search_limit')) || 10;
            const percent = Math.min(100, (totalUnits / searchLimit) * 100);
            if (subProgress) subProgress.style.width = `${percent}%`;

            const subType = document.getElementById('sub-type-badge');
            if (subType) subType.textContent = data.package || 'Standard Protocol';

            const daysLeft = document.getElementById('sub-days-left');
            if (daysLeft) daysLeft.textContent = 'Active Protocol';

            // REAL Login Sessions (Exact data from API)
            if (history) {
                history.innerHTML = '';
                // Since we don't have a history model yet, we show the Current Session as the "Exact One"
                const currentSession = {
                    location: 'Current Session (Secure)',
                    ip: data.current_ip || 'Internal IP',
                    time: data.last_login || 'Just now'
                };

                const item = document.createElement('div');
                item.style.cssText = 'padding: 10px 20px; border-bottom: 1px solid #f8fafc; display: flex; justify-content: space-between; align-items: center; background: rgba(16, 185, 129, 0.03); border-left: 3px solid #10b981;';
                item.innerHTML = `
                    <div>
                        <p style="font-size: 0.72rem; font-weight: 700; color: var(--text-main); margin: 0;">${currentSession.location}</p>
                        <p style="font-size: 0.62rem; color: var(--text-light); margin: 2px 0 0 0;">IP: ${currentSession.ip}</p>
                        <div style="display: flex; align-items: center; gap: 4px; margin-top: 4px;">
                            <div style="width: 6px; height: 6px; background: #10b981; border-radius: 50%;"></div>
                            <span style="font-size: 0.55rem; font-weight: 800; color: #10b981; text-transform: uppercase;">Primary Instance Active</span>
                        </div>
                    </div>
                    <span style="font-size: 0.65rem; color: var(--accent); font-weight: 700;">${currentSession.time}</span>
                `;
                history.appendChild(item);

                // Add Logout/Terminate Button at the bottom
                const logoutContainer = document.createElement('div');
                logoutContainer.style.cssText = 'padding: 16px 20px; display: flex; justify-content: center;';

                const sessionLogoutBtn = document.createElement('button');
                sessionLogoutBtn.innerHTML = `
                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" style="margin-right:8px;"><path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"></path><polyline points="16 17 21 12 16 7"></polyline><line x1="21" y1="12" x2="9" y2="12"></line></svg>
                    Terminate Protocol Session
                `;
                sessionLogoutBtn.style.cssText = 'width: 100%; padding: 10px; background: rgba(239, 68, 68, 0.08); color: #ef4444; border: 1px solid rgba(239, 68, 68, 0.2); border-radius: 10px; font-size: 0.7rem; font-weight: 800; cursor: pointer; transition: 0.2s; display: flex; align-items: center; justify-content: center; text-transform: uppercase; letter-spacing: 0.02em;';

                sessionLogoutBtn.onmouseover = () => {
                    sessionLogoutBtn.style.background = '#ef4444';
                    sessionLogoutBtn.style.color = 'white';
                };
                sessionLogoutBtn.onmouseout = () => {
                    sessionLogoutBtn.style.background = 'rgba(239, 68, 68, 0.08)';
                    sessionLogoutBtn.style.color = '#ef4444';
                };

                sessionLogoutBtn.onclick = logoutHandler;
                logoutContainer.appendChild(sessionLogoutBtn);
                history.appendChild(logoutContainer);
            }
        }
    } catch (e) {
        console.warn("Profile fetch fail", e);
    }

    // Load Activity Feed
    const feed = document.getElementById('profile-activity-feed');
    if (feed) {
        feed.innerHTML = '';
        const recent = latestJobsCache.slice(0, 4);
        if (recent.length === 0) {
            feed.innerHTML = '<p style="font-size: 0.75rem; color: var(--text-muted); text-align: center;">No protocol logs found.</p>';
        } else {
            recent.forEach(job => {
                const item = document.createElement('div');
                item.style.cssText = 'display: flex; gap: 16px; align-items: flex-start;';
                item.innerHTML = `
                    <div style="margin-top: 4px; width: 10px; height: 10px; border-radius:50%; background: var(--accent); border: 2px solid white; box-shadow: 0 0 0 1px var(--accent);"></div>
                    <div style="flex:1;">
                        <p style="font-size: 0.8rem; font-weight: 800; color: var(--text-main); margin: 0;">${job.keyword || 'Bulk Search'} in ${job.location || 'Unknown'}</p>
                        <p style="font-size: 0.65rem; color: var(--text-muted); margin: 2px 0 0 0;">${new Date(job.created_at).toLocaleString()} • ${job.total_extracted || 0} leads</p>
                    </div>
                `;
                feed.appendChild(item);
            });
        }
    }
};
