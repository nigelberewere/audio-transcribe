const $ = (id) => document.getElementById(id);
const auditState = { offset: 0, actor: '', action: '' };
let loadedUsers = [];
let currentAdminUser = null;
let currentManageUser = null;

async function request(url, options = {}) {
  const response = await fetch(url, options);
  if (!response.ok) {
    const data = await response.json().catch(() => ({}));
    throw new Error(data.detail || response.statusText);
  }
  return response.json();
}

function escapeHtml(value) {
  return String(value ?? '').replace(/[&<>"']/g, char => ({
    '&': '&amp;',
    '<': '&lt;',
    '>': '&gt;',
    '"': '&quot;',
    "'": '&#39;'
  }[char]));
}// Remove any legacy navigation links and sidebar badges
function cleanupBrandNavLinks() {
  document.querySelectorAll('header.brand-card nav a, .brand-card nav a, .sidebar-item .status-badge').forEach(el => el.remove());
}
if (document.readyState !== 'loading') cleanupBrandNavLinks();
else document.addEventListener('DOMContentLoaded', cleanupBrandNavLinks);

function formatDateTime(value) {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? '' : date.toLocaleString(undefined, {
    month: 'short',
    day: 'numeric',
    year: 'numeric',
    hour: 'numeric',
    minute: '2-digit'
  });
}

function populateOptions(select, values, emptyLabel) {
  if (!select) return;
  const current = select.value;
  select.innerHTML = `<option value="">${emptyLabel}</option>` + values.map(value => `<option value="${escapeHtml(value)}">${escapeHtml(value)}</option>`).join('');
  select.value = values.includes(current) ? current : '';
}

function toggleAuditFilters() {
  $('auditFilters').hidden = !$('auditFilters').hidden;
}

function renderAudit(entries) {
  const logEl = $('auditLog');
  if (!logEl) return;
  logEl.innerHTML += entries.map(entry => `<tr>
    <td>${formatDateTime(entry.created_at)}</td>
    <td>${escapeHtml(entry.actor)}</td>
    <td><code>${escapeHtml(entry.action)}</code></td>
    <td>${escapeHtml(entry.target || '')}</td>
    <td>${escapeHtml(entry.details || '')}</td>
  </tr>`).join('');
}

async function loadAudit(reset = true) {
  if (!$('auditLog')) return;
  if (reset) {
    auditState.offset = 0;
    $('auditLog').innerHTML = '';
  }
  const params = new URLSearchParams({limit: '50', offset: String(auditState.offset)});
  if (auditState.actor) params.set('actor', auditState.actor);
  if (auditState.action) params.set('action', auditState.action);
  const result = await request('/api/admin/audit-log?' + params);
  populateOptions($('auditActor'), result.actors, 'All actors');
  populateOptions($('auditAction'), result.actions, 'All actions');
  renderAudit(result.entries);
  auditState.offset += result.entries.length;
  $('loadMoreAudit').hidden = !result.has_more;
}

function formatBytes(value) {
  if (value < 1024) return `${value} B`;
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KB`;
  return `${(value / (1024 * 1024)).toFixed(1)} MB`;
}

async function loadAdmin() {
  const [users, overview, me] = await Promise.all([
    request('/api/admin/users'),
    request('/api/admin/overview'),
    request('/api/me').catch(() => null)
  ]);
  loadedUsers = users;
  if (me) {
    currentAdminUser = me.username;
    if ($('userName')) {
      $('userName').textContent = me.name || me.username;
      $('userName').title = `${me.username}${me.email ? ' · ' + me.email : ''}`;
    }
  }

  if ($('stats')) {
    $('stats').innerHTML = [
    ['Total users', overview.total_users],
    ['Active jobs', overview.active_jobs],
    ['Completed today', overview.completed_jobs_today],
    ['Documents', overview.total_documents],
    ['Storage used', formatBytes(overview.total_storage_used)],
    ['Documents today', overview.documents_uploaded_today]
    ].map(([label, value]) => `<article class="stat"><strong>${value}</strong><span>${label}</span></article>`).join('');
  }

  if ($('users')) {
    $('users').innerHTML = users.map(user => {
    const fullName = [user.first_name, user.surname].filter(Boolean).join(' ') || '—';
    const email = user.email || '—';
    return `<tr>
      <td><strong>${escapeHtml(fullName)}</strong></td>
      <td><code>${escapeHtml(user.username)}</code></td>
      <td>${escapeHtml(email)}</td>
      <td><span class="role-badge ${user.role === 'admin' ? 'admin' : ''}">${user.role === 'admin' ? 'Admin' : 'User'}</span></td>
      <td>
        <button type="button" class="status-toggle-btn" onclick="toggleUserStatus('${encodeURIComponent(user.username)}', ${user.active ? 0 : 1})" title="Click to ${user.active ? 'deactivate' : 'activate'} this user">
          <span class="status-badge ${user.active ? 'active' : 'inactive'}">${user.active ? 'Active' : 'Inactive'}</span>
        </button>
      </td>
      <td>${formatDateTime(user.created_at)}</td>
      <td>${escapeHtml(user.created_by || 'Bootstrap')}</td>
      <td><button class="quiet manage-button" onclick="openManageUser('${encodeURIComponent(user.username)}')">Manage account</button></td>
    </tr>`;
    }).join('');
  }

  await Promise.all([loadAudit(), syncSidebarBadges()]);
}

async function loadAdminUser() {
  try {
    const me = await request('/api/me');
    if (me) {
      currentAdminUser = me.username;
      if ($('userName')) {
        $('userName').textContent = me.name || me.username;
        $('userName').title = `${me.username}${me.email ? ' · ' + me.email : ''}`;
      }
    }
  } catch (err) {
    if (window.location.pathname !== '/admin/login' && !$('adminLoginForm')) {
      window.location.href = '/admin/login';
    }
  }
}

async function syncSidebarBadges() {
  if (!$('sidebarHfBadge') && !$('sidebarSmtpBadge') && !$('sidebarLogsBadge')) return;
  try {
    const [hfSettings, smtpSettings, logsSettings] = await Promise.all([
      request('/api/admin/settings').catch(() => null),
      request('/api/admin/notifications/settings').catch(() => null),
      request('/api/admin/logs/settings').catch(() => null)
    ]);
    if (hfSettings && $('sidebarHfBadge')) {
      const active = hfSettings.has_token;
      $('sidebarHfBadge').textContent = active ? (hfSettings.available ? 'Ready' : 'Configured') : 'Not set';
      $('sidebarHfBadge').className = `status-badge ${active ? 'active' : 'inactive'}`;
    }
    if (smtpSettings && $('sidebarSmtpBadge')) {
      const active = smtpSettings.is_enabled;
      $('sidebarSmtpBadge').textContent = active ? 'Enabled' : 'Disabled';
      $('sidebarSmtpBadge').className = `status-badge ${active ? 'active' : 'inactive'}`;
    }
    if (logsSettings && $('sidebarLogsBadge')) {
      $('sidebarLogsBadge').textContent = `${logsSettings.retention_days}d retention`;
      $('sidebarLogsBadge').className = 'status-badge active';
    }
  } catch (e) {
    // Ignore badge sync errors
  }
}

function openManageUser(encodedUsername) {
  const username = decodeURIComponent(encodedUsername);
  const user = loadedUsers.find(u => u.username === username);
  if (!user) return;
  currentManageUser = user;

  const fullName = [user.first_name, user.surname].filter(Boolean).join(' ') || user.username;
  $('manageUserHeading').textContent = `Manage Account: ${fullName} (@${user.username})`;
  $('manageUserMeta').textContent = `Created: ${formatDateTime(user.created_at) || 'Initial setup'} · Registered by: ${user.created_by || 'Bootstrap'}`;

  $('manageFirstName').value = user.first_name || '';
  $('manageSurname').value = user.surname || '';
  $('manageEmail').value = user.email || '';
  $('manageRole').value = user.role || 'user';
  $('manageActive').checked = !!user.active;
  $('manageActiveLabel').textContent = user.active ? 'Active' : 'Inactive';
  $('manageActiveLabel').className = `status-badge ${user.active ? 'active' : 'inactive'}`;

  $('manageNewPassword').value = '';
  $('manageConfirmPassword').value = '';

  ['manageDetailsMessage', 'managePasswordMessage', 'deleteUserMessage'].forEach(id => {
    const el = $(id);
    if (el) { el.textContent = ''; el.className = 'feedback-msg'; }
  });

  const deleteBtn = $('deleteUserBtn');
  if (deleteBtn) {
    if (user.username === currentAdminUser) {
      deleteBtn.disabled = true;
      deleteBtn.title = 'You cannot delete your own logged-in administrator account';
    } else {
      deleteBtn.disabled = false;
      deleteBtn.title = '';
    }
  }

  $('manageUserDialog').showModal();
}

function openResetPassword(username) {
  openManageUser(encodeURIComponent(username));
}

async function saveManageDetails(showFeedback = true) {
  if (!currentManageUser) return false;
  const msgEl = $('manageDetailsMessage');
  if (msgEl && showFeedback) {
    msgEl.textContent = '';
    msgEl.className = 'feedback-msg';
  }

  const body = new URLSearchParams();
  body.set('first_name', $('manageFirstName')?.value.trim() || currentManageUser.first_name || '');
  body.set('surname', $('manageSurname')?.value.trim() || currentManageUser.surname || '');
  body.set('email', $('manageEmail')?.value.trim() || currentManageUser.email || '');
  body.set('role', $('manageRole')?.value || currentManageUser.role || 'user');
  body.set('active', $('manageActive')?.checked ? '1' : '0');

  try {
    await request(`/api/admin/users/${encodeURIComponent(currentManageUser.username)}`, {
      method: 'PATCH',
      body
    });
    if (msgEl && showFeedback) {
      msgEl.textContent = 'Account profile and status updated successfully!';
      msgEl.className = 'feedback-msg success';
    }
    await loadAdmin();
    currentManageUser = loadedUsers.find(u => u.username === currentManageUser.username) || currentManageUser;
    return true;
  } catch (error) {
    if (msgEl) {
      msgEl.textContent = error.message;
      msgEl.className = 'feedback-msg error';
    }
    return false;
  }
}

$('manageActive')?.addEventListener('change', async function () {
  if (!currentManageUser) return;
  const isChecked = this.checked;
  const labelEl = $('manageActiveLabel');
  if (labelEl) {
    labelEl.textContent = isChecked ? 'Active' : 'Inactive';
    labelEl.className = `status-badge ${isChecked ? 'active' : 'inactive'}`;
  }

  const msgEl = $('manageDetailsMessage');
  if (msgEl) {
    msgEl.textContent = isChecked ? 'Activating account...' : 'Deactivating account...';
    msgEl.className = 'feedback-msg';
  }

  const body = new URLSearchParams();
  body.set('active', isChecked ? '1' : '0');
  body.set('first_name', $('manageFirstName')?.value.trim() || currentManageUser.first_name || '');
  body.set('surname', $('manageSurname')?.value.trim() || currentManageUser.surname || '');
  body.set('email', $('manageEmail')?.value.trim() || currentManageUser.email || '');
  body.set('role', $('manageRole')?.value || currentManageUser.role || 'user');

  try {
    await request(`/api/admin/users/${encodeURIComponent(currentManageUser.username)}`, {
      method: 'PATCH',
      body
    });
    currentManageUser.active = isChecked ? 1 : 0;
    if (msgEl) {
      msgEl.textContent = `Account status updated to ${isChecked ? 'Active' : 'Inactive'}!`;
      msgEl.className = 'feedback-msg success';
    }
    await loadAdmin();
    currentManageUser = loadedUsers.find(u => u.username === currentManageUser.username) || currentManageUser;
  } catch (error) {
    this.checked = !isChecked;
    if (labelEl) {
      labelEl.textContent = this.checked ? 'Active' : 'Inactive';
      labelEl.className = `status-badge ${this.checked ? 'active' : 'inactive'}`;
    }
    if (msgEl) {
      msgEl.textContent = error.message;
      msgEl.className = 'feedback-msg error';
    }
  }
});

$('manageDetailsForm')?.addEventListener('submit', async (event) => {
  event.preventDefault();
  await saveManageDetails(true);
});

$('managePasswordForm')?.addEventListener('submit', async (event) => {
  event.preventDefault();
  if (!currentManageUser) return;
  const msgEl = $('managePasswordMessage');
  msgEl.textContent = '';
  msgEl.className = 'feedback-msg';

  const newPass = $('manageNewPassword').value;
  const confirmPass = $('manageConfirmPassword').value;

  if (newPass !== confirmPass) {
    msgEl.textContent = 'Passwords do not match';
    msgEl.className = 'feedback-msg error';
    return;
  }
  if (newPass.length < 8) {
    msgEl.textContent = 'Password must be at least 8 characters';
    msgEl.className = 'feedback-msg error';
    return;
  }

  const body = new FormData();
  body.set('password', newPass);
  body.set('confirm_password', confirmPass);

  try {
    await request(`/api/admin/users/${encodeURIComponent(currentManageUser.username)}/reset-password`, {
      method: 'POST',
      body
    });
    msgEl.textContent = 'Password reset successfully!';
    msgEl.className = 'feedback-msg success';
    $('manageNewPassword').value = '';
    $('manageConfirmPassword').value = '';
    await loadAudit();
  } catch (error) {
    msgEl.textContent = error.message;
    msgEl.className = 'feedback-msg error';
  }
});

$('deleteUserBtn')?.addEventListener('click', async () => {
  if (!currentManageUser) return;
  const msgEl = $('deleteUserMessage');
  msgEl.textContent = '';
  msgEl.className = 'feedback-msg';

  const confirmed = window.confirm(`Are you sure you want to permanently delete user "${currentManageUser.username}"? This cannot be undone.`);
  if (!confirmed) return;

  try {
    await request(`/api/admin/users/${encodeURIComponent(currentManageUser.username)}`, {
      method: 'DELETE'
    });
    $('manageUserDialog').close();
    currentManageUser = null;
    await loadAdmin();
  } catch (error) {
    msgEl.textContent = error.message;
    msgEl.className = 'feedback-msg error';
  }
});

$('closeManageUser')?.addEventListener('click', async () => {
  if (currentManageUser && $('manageUserDialog')?.open) {
    await saveManageDetails(false);
  }
  $('manageUserDialog')?.close();
  currentManageUser = null;
  await loadAdmin();
});

async function toggleUserStatus(encodedUsername, newStatus) {
  const username = decodeURIComponent(encodedUsername);
  const user = loadedUsers.find(u => u.username === username);
  if (!user) return;

  if (username === currentAdminUser && newStatus === 0) {
    const ok = window.confirm('Warning: You are about to deactivate your own administrator account. Proceed?');
    if (!ok) return;
  }

  const body = new URLSearchParams();
  body.set('active', String(newStatus));
  body.set('first_name', user.first_name || '');
  body.set('surname', user.surname || '');
  body.set('email', user.email || '');
  body.set('role', user.role || 'user');

  try {
    await request(`/api/admin/users/${encodeURIComponent(username)}`, {
      method: 'PATCH',
      body
    });
    await loadAdmin();
  } catch (error) {
    alert(error.message || 'Failed to update user status');
  }
}
window.toggleUserStatus = toggleUserStatus;

$('adminLoginForm')?.addEventListener('submit', async (event) => {
  event.preventDefault();
  try {
    await request('/api/admin/login', {method: 'POST', body: new FormData(event.target)});
    location.href = '/admin';
  } catch (error) {
    $('adminLoginError').textContent = error.message;
  }
});
if ($('adminLoginForm')) {
  request('/api/me').then(me => {
    if (me && me.role === 'admin') location.href = '/admin';
  }).catch(() => {});
}

$('createUserForm')?.addEventListener('submit', async (event) => {
  event.preventDefault();
  const form = event.target;
  if (form.elements.password.value !== form.elements.confirm_password.value) {
    $('userError').textContent = 'Passwords do not match';
    return;
  }
  try {
    await request('/api/admin/users', {method: 'POST', body: new FormData(form)});
    form.reset();
    $('userError').textContent = '';
    $('createUserDialog').close();
    await loadAdmin();
  } catch (error) {
    $('userError').textContent = error.message;
  }
});
$('addUser')?.addEventListener('click', () => {
  $('createUserForm').reset();
  $('userError').textContent = '';
  $('createUserDialog').showModal();
});
$('cancelCreateUser')?.addEventListener('click', () => $('createUserDialog').close());

$('auditFilterToggle')?.addEventListener('click', toggleAuditFilters);
$('auditActor')?.addEventListener('change', (event) => {
  auditState.actor = event.target.value;
  loadAudit();
});
$('auditAction')?.addEventListener('change', (event) => {
  auditState.action = event.target.value;
  loadAudit();
});
$('loadMoreAudit')?.addEventListener('click', () => loadAudit(false));

async function loadAdminSettings() {
  if (!$('settingsForm')) return;
  try {
    const settings = await request('/api/admin/settings');
    const badge = $('hfBadge');
    const statusText = $('hfCurrentStatus');
    const clearBtn = $('clearHfTokenBtn');

    if (settings.has_token) {
      if (badge) {
        badge.textContent = settings.available ? 'Configured & Ready' : 'Token Configured';
        badge.className = 'status-badge active';
      }
      if (statusText) {
        statusText.innerHTML = `Active token: <code>${escapeHtml(settings.masked_token)}</code>${settings.message && !settings.available ? ` &middot; <span style="color:var(--danger);">${escapeHtml(settings.message)}</span>` : ''}`;
      }
      if (clearBtn) clearBtn.hidden = false;
    } else {
      if (badge) {
        badge.textContent = 'Not Configured';
        badge.className = 'status-badge inactive';
      }
      if (statusText) {
        statusText.textContent = 'No token configured. Speaker diarization option is currently hidden from users.';
      }
      if (clearBtn) clearBtn.hidden = true;
    }
    const sidebarBadge = $('sidebarHfBadge') || $('hfBadgeMenu') || $('hfBadgeNav');
    if (sidebarBadge) {
      sidebarBadge.textContent = settings.has_token ? (settings.available ? 'Ready' : 'Configured') : 'Not set';
      sidebarBadge.className = `status-badge ${settings.has_token ? 'active' : 'inactive'}`;
    }
  } catch (error) {
    if ($('hfBadge')) {
      $('hfBadge').textContent = 'Error';
      $('hfBadge').className = 'status-badge inactive';
    }
    const sidebarBadge = $('sidebarHfBadge') || $('hfBadgeMenu') || $('hfBadgeNav');
    if (sidebarBadge) {
      sidebarBadge.textContent = 'Error';
      sidebarBadge.className = 'status-badge inactive';
    }
    if ($('hfCurrentStatus')) {
      $('hfCurrentStatus').textContent = `Failed to load settings: ${error.message}`;
    }
  }
}

$('settingsForm')?.addEventListener('submit', async (event) => {
  event.preventDefault();
  const feedback = $('settingsFeedback');
  const tokenInput = $('adminHfToken');
  const saveBtn = $('saveHfTokenBtn');
  const token = tokenInput.value.trim();

  if (!token) {
    if (feedback) {
      feedback.textContent = 'Please enter a valid Hugging Face token (or use Remove Token to clear it).';
      feedback.className = 'feedback-msg error';
    }
    return;
  }

  saveBtn.disabled = true;
  if (feedback) {
    feedback.textContent = 'Saving token...';
    feedback.className = 'feedback-msg';
  }

  try {
    await request('/api/admin/settings', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ hf_token: token })
    });
    tokenInput.value = '';
    if (feedback) {
      feedback.textContent = 'Hugging Face token saved successfully! Diarization is now enabled for users.';
      feedback.className = 'feedback-msg success';
    }
    await loadAdminSettings();
    await loadAudit();
  } catch (error) {
    if (feedback) {
      feedback.textContent = error.message;
      feedback.className = 'feedback-msg error';
    }
  } finally {
    saveBtn.disabled = false;
  }
});

$('clearHfTokenBtn')?.addEventListener('click', async () => {
  const feedback = $('settingsFeedback');
  const confirmed = window.confirm('Are you sure you want to remove the Hugging Face token? Speaker Diarization will be hidden from users.');
  if (!confirmed) return;

  if (feedback) {
    feedback.textContent = 'Removing token...';
    feedback.className = 'feedback-msg';
  }

  try {
    await request('/api/admin/settings', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ hf_token: '' })
    });
    $('adminHfToken').value = '';
    if (feedback) {
      feedback.textContent = 'Token removed. Speaker Diarization is now disabled and hidden from users.';
      feedback.className = 'feedback-msg success';
    }
    await loadAdminSettings();
    await loadAudit();
  } catch (error) {
    if (feedback) {
      feedback.textContent = error.message;
      feedback.className = 'feedback-msg error';
    }
  }
});

async function loadNotificationSettings() {
  if (!$('notificationSettingsForm')) return;
  try {
    const settings = await request('/api/admin/notifications/settings');
    const badge = $('smtpBadge');

    if ($('smtpHost')) $('smtpHost').value = settings.smtp_host || '';
    if ($('smtpPort')) $('smtpPort').value = settings.smtp_port || 587;
    if ($('smtpUsername')) $('smtpUsername').value = settings.smtp_username || '';
    if ($('smtpFromAddress')) $('smtpFromAddress').value = settings.smtp_from_address || '';
    if ($('smtpUseTls')) {
      $('smtpUseTls').checked = settings.smtp_use_tls !== false;
      if ($('smtpUseTlsLabel')) {
        $('smtpUseTlsLabel').textContent = $('smtpUseTls').checked ? 'Use TLS (STARTTLS)' : 'Plaintext (No TLS)';
      }
    }

    if ($('smtpPassword')) {
      $('smtpPassword').value = '';
      $('smtpPassword').placeholder = settings.has_password ? '•••••••• (unchanged)' : 'Enter password';
    }

    if (badge) {
      if (settings.is_enabled) {
        badge.textContent = 'Enabled';
        badge.className = 'status-badge active';
      } else {
        badge.textContent = 'Disabled';
        badge.className = 'status-badge inactive';
      }
    }
    const sidebarBadge = $('sidebarSmtpBadge') || $('smtpBadgeMenu') || $('smtpBadgeNav');
    if (sidebarBadge && badge) {
      sidebarBadge.textContent = badge.textContent;
      sidebarBadge.className = badge.className;
    }
  } catch (error) {
    if ($('smtpBadge')) {
      $('smtpBadge').textContent = 'Error';
      $('smtpBadge').className = 'status-badge inactive';
    }
    const sidebarBadge = $('sidebarSmtpBadge') || $('smtpBadgeMenu') || $('smtpBadgeNav');
    if (sidebarBadge) {
      sidebarBadge.textContent = 'Error';
      sidebarBadge.className = 'status-badge inactive';
    }
    const feedback = $('notificationFeedback');
    if (feedback) {
      feedback.textContent = `Failed to load notification settings: ${error.message}`;
      feedback.className = 'feedback-msg error';
    }
  }
}

$('smtpUseTls')?.addEventListener('change', function () {
  if ($('smtpUseTlsLabel')) {
    $('smtpUseTlsLabel').textContent = this.checked ? 'Use TLS (STARTTLS)' : 'Plaintext (No TLS)';
  }
});

$('notificationSettingsForm')?.addEventListener('submit', async (event) => {
  event.preventDefault();
  const feedback = $('notificationFeedback');
  const saveBtn = $('saveSmtpBtn');

  saveBtn.disabled = true;
  if (feedback) {
    feedback.textContent = 'Saving notification settings...';
    feedback.className = 'feedback-msg';
  }

  const payload = {
    smtp_host: $('smtpHost').value.trim(),
    smtp_port: parseInt($('smtpPort').value, 10) || 587,
    smtp_username: $('smtpUsername').value.trim(),
    smtp_password: $('smtpPassword').value,
    smtp_from_address: $('smtpFromAddress').value.trim(),
    smtp_use_tls: $('smtpUseTls').checked
  };

  try {
    const res = await request('/api/admin/notifications/settings', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    });
    if (feedback) {
      feedback.textContent = res.message || 'Notification settings saved successfully!';
      feedback.className = 'feedback-msg success';
    }
    await loadNotificationSettings();
    await loadAudit();
  } catch (error) {
    if (feedback) {
      feedback.textContent = error.message;
      feedback.className = 'feedback-msg error';
    }
  } finally {
    saveBtn.disabled = false;
  }
});

$('sendTestEmailBtn')?.addEventListener('click', async () => {
  const feedback = $('testEmailFeedback');
  const testBtn = $('sendTestEmailBtn');
  const recipient = $('testRecipientEmail')?.value.trim();

  if (!recipient) {
    if (feedback) {
      feedback.textContent = 'Please enter a recipient email address.';
      feedback.className = 'feedback-msg error';
    }
    return;
  }

  testBtn.disabled = true;
  if (feedback) {
    feedback.textContent = 'Sending test email...';
    feedback.className = 'feedback-msg';
  }

  const payload = {
    recipient_email: recipient,
    smtp_host: $('smtpHost')?.value.trim() || undefined,
    smtp_port: parseInt($('smtpPort')?.value, 10) || undefined,
    smtp_username: $('smtpUsername')?.value.trim() || undefined,
    smtp_password: $('smtpPassword')?.value || undefined,
    smtp_from_address: $('smtpFromAddress')?.value.trim() || undefined,
    smtp_use_tls: $('smtpUseTls')?.checked
  };

  try {
    const res = await request('/api/admin/notifications/test', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    });
    if (feedback) {
      feedback.textContent = res.message || 'Test email sent successfully!';
      feedback.className = 'feedback-msg success';
    }
    await loadAudit();
  } catch (error) {
    if (feedback) {
      feedback.textContent = error.message;
      feedback.className = 'feedback-msg error';
    }
    await loadAudit();
  } finally {
    testBtn.disabled = false;
  }
});

$('logout')?.addEventListener('click', async () => {
  await fetch('/api/logout', {method: 'POST'});
  location.href = '/admin/login';
});

/* ==========================================================================
   Logs Settings & Retention Controller
   ========================================================================== */

async function loadLogsSettings() {
  if (!$('logRetentionForm')) return;
  try {
    const data = await request('/api/admin/logs/settings');
    const days = String(data.retention_days || 1);
    const radio = document.querySelector(`input[name="retention_days"][value="${days}"]`);
    if (radio) radio.checked = true;

    if ($('retentionBadge')) {
      $('retentionBadge').textContent = `${days} Day${days === '1' ? '' : 's'} Retention`;
      $('retentionBadge').className = 'status-badge active';
    }
  } catch (err) {
    console.error('Failed to load log retention settings:', err);
  }
}

$('logRetentionForm')?.addEventListener('submit', async (event) => {
  event.preventDefault();
  const feedback = $('logRetentionFeedback');
  const saveBtn = $('saveRetentionBtn');
  const selectedRadio = document.querySelector('input[name="retention_days"]:checked');
  if (!selectedRadio) return;

  const retentionDays = parseInt(selectedRadio.value, 10);
  if (saveBtn) saveBtn.disabled = true;
  if (feedback) {
    feedback.textContent = 'Updating retention policy...';
    feedback.className = 'feedback-msg';
  }

  try {
    const res = await request('/api/admin/logs/settings', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ retention_days: retentionDays })
    });
    if (feedback) {
      feedback.textContent = `Retention policy updated to ${retentionDays} day${retentionDays === 1 ? '' : 's'}. Pruned ${res.pruned || 0} expired logs.`;
      feedback.className = 'feedback-msg success';
    }
    if ($('retentionBadge')) {
      $('retentionBadge').textContent = `${retentionDays} Day${retentionDays === 1 ? '' : 's'} Retention`;
    }
    await Promise.all([loadAudit(true), syncSidebarBadges()]);
  } catch (error) {
    if (feedback) {
      feedback.textContent = error.message;
      feedback.className = 'feedback-msg error';
    }
  } finally {
    if (saveBtn) saveBtn.disabled = false;
  }
});

$('purgeExpiredLogsBtn')?.addEventListener('click', async () => {
  const feedback = $('logRetentionFeedback');
  const purgeBtn = $('purgeExpiredLogsBtn');
  if (purgeBtn) purgeBtn.disabled = true;
  if (feedback) {
    feedback.textContent = 'Purging expired logs...';
    feedback.className = 'feedback-msg';
  }
  try {
    const res = await request('/api/admin/logs/cleanup', { method: 'POST' });
    if (feedback) {
      feedback.textContent = `Successfully purged ${res.deleted || 0} expired log record${res.deleted === 1 ? '' : 's'}.`;
      feedback.className = 'feedback-msg success';
    }
    await loadAudit(true);
  } catch (error) {
    if (feedback) {
      feedback.textContent = error.message;
      feedback.className = 'feedback-msg error';
    }
  } finally {
    if (purgeBtn) purgeBtn.disabled = false;
  }
});

$('refreshAuditBtn')?.addEventListener('click', () => {
  loadAudit(true);
});

$('resetAuditFiltersBtn')?.addEventListener('click', () => {
  if ($('auditActor')) $('auditActor').value = '';
  if ($('auditAction')) $('auditAction').value = '';
  auditState.actor = '';
  auditState.action = '';
  loadAudit(true);
});

// Page initialization
async function initPage() {
  if ($('adminLoginForm')) {
    // Agent / Admin login page - no dashboard loading
    return;
  }

  if ($('users')) {
    // Main admin overview page
    try {
      await loadAdmin();
    } catch {
      location.href = '/admin/login';
    }
  } else if ($('settingsForm') || $('notificationSettingsForm') || $('logRetentionForm') || $('auditLog')) {
    // Dedicated settings pages
    await loadAdminUser();
    if ($('settingsForm')) {
      await loadAdminSettings();
    }
    if ($('notificationSettingsForm')) {
      await loadNotificationSettings();
    }
    if ($('logRetentionForm') || $('auditLog')) {
      await loadLogsSettings();
      await loadAudit(true);
    }
    await syncSidebarBadges();
  }
}

initPage();


