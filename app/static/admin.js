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
}

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
  const current = select.value;
  select.innerHTML = `<option value="">${emptyLabel}</option>` + values.map(value => `<option value="${escapeHtml(value)}">${escapeHtml(value)}</option>`).join('');
  select.value = values.includes(current) ? current : '';
}

function toggleAuditFilters() {
  $('auditFilters').hidden = !$('auditFilters').hidden;
}

function renderAudit(entries) {
  $('auditLog').innerHTML += entries.map(entry => `<tr>
    <td>${formatDateTime(entry.created_at)}</td>
    <td>${escapeHtml(entry.actor)}</td>
    <td><code>${escapeHtml(entry.action)}</code></td>
    <td>${escapeHtml(entry.target || '')}</td>
    <td>${escapeHtml(entry.details || '')}</td>
  </tr>`).join('');
}

async function loadAudit(reset = true) {
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

  $('stats').innerHTML = [
    ['Total users', overview.total_users],
    ['Active jobs', overview.active_jobs],
    ['Completed today', overview.completed_jobs_today],
    ['Documents', overview.total_documents],
    ['Storage used', formatBytes(overview.total_storage_used)],
    ['Documents today', overview.documents_uploaded_today]
  ].map(([label, value]) => `<article class="stat"><strong>${value}</strong><span>${label}</span></article>`).join('');

  $('users').innerHTML = users.map(user => {
    const fullName = [user.first_name, user.surname].filter(Boolean).join(' ') || '—';
    const email = user.email || '—';
    return `<tr>
      <td><strong>${escapeHtml(fullName)}</strong></td>
      <td><code>${escapeHtml(user.username)}</code></td>
      <td>${escapeHtml(email)}</td>
      <td><span class="role-badge ${user.role === 'admin' ? 'admin' : ''}">${user.role === 'admin' ? 'Admin' : 'User'}</span></td>
      <td><span class="status-badge ${user.active ? 'active' : 'inactive'}">${user.active ? 'Active' : 'Inactive'}</span></td>
      <td>${formatDateTime(user.created_at)}</td>
      <td>${escapeHtml(user.created_by || 'Bootstrap')}</td>
      <td><button class="quiet manage-button" onclick="openManageUser('${encodeURIComponent(user.username)}')">Manage account</button></td>
    </tr>`;
  }).join('');

  await loadAudit();
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

$('manageActive')?.addEventListener('change', function () {
  $('manageActiveLabel').textContent = this.checked ? 'Active' : 'Inactive';
});

$('manageDetailsForm')?.addEventListener('submit', async (event) => {
  event.preventDefault();
  if (!currentManageUser) return;
  const msgEl = $('manageDetailsMessage');
  msgEl.textContent = '';
  msgEl.className = 'feedback-msg';

  const body = new URLSearchParams();
  body.set('first_name', $('manageFirstName').value.trim());
  body.set('surname', $('manageSurname').value.trim());
  body.set('email', $('manageEmail').value.trim());
  body.set('role', $('manageRole').value);
  body.set('active', $('manageActive').checked ? '1' : '0');

  try {
    await request(`/api/admin/users/${encodeURIComponent(currentManageUser.username)}`, {
      method: 'PATCH',
      body
    });
    msgEl.textContent = 'Account profile and status updated successfully!';
    msgEl.className = 'feedback-msg success';
    await loadAdmin();
    currentManageUser = loadedUsers.find(u => u.username === currentManageUser.username) || currentManageUser;
  } catch (error) {
    msgEl.textContent = error.message;
    msgEl.className = 'feedback-msg error';
  }
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

$('closeManageUser')?.addEventListener('click', () => {
  $('manageUserDialog').close();
  currentManageUser = null;
});

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

$('logout')?.addEventListener('click', async () => {
  await fetch('/api/logout', {method: 'POST'});
  location.href = '/admin/login';
});

if ($('users')) loadAdmin().catch(() => { location.href = '/'; });
