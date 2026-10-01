const $ = (id) => document.getElementById(id);

// Workspace modules list.
// Adding a future module (e.g. PDF tools) only requires adding a single entry to this array.
const MODULES = [
  {
    id: "transcription",
    title: "Transcription",
    description: "Transcribe meeting recordings",
    href: "/transcription",
    badge: "Audio & Video",
    icon: `<svg viewBox="0 0 24 24" width="24" height="24" stroke="currentColor" stroke-width="2" fill="none" stroke-linecap="round" stroke-linejoin="round"><path d="M12 2a3 3 0 0 0-3 3v7a3 3 0 0 0 6 0V5a3 3 0 0 0-3-3Z"/><path d="M19 10v2a7 7 0 0 1-14 0v-2"/><line x1="12" y1="19" x2="12" y2="22"/></svg>`,
  },
  {
    id: "documents",
    title: "Documents",
    description: "Store and manage files",
    href: "/documents",
    badge: "Repository",
    icon: `<svg viewBox="0 0 24 24" width="24" height="24" stroke="currentColor" stroke-width="2" fill="none" stroke-linecap="round" stroke-linejoin="round"><path d="M4 20h16a2 2 0 0 0 2-2V8a2 2 0 0 0-2-2h-7.93a2 2 0 0 1-1.66-.9l-.82-1.2A2 2 0 0 0 7.93 3H4a2 2 0 0 0-2 2v13c0 1.1.9 2 2 2Z"/></svg>`,
  },
];

async function request(url, options = {}) {
  const response = await fetch(url, options);
  if (!response.ok) throw new Error((await response.json()).detail || response.statusText);
  return response.json();
}

function escapeHtml(value) {
  return String(value ?? '').replace(/[&<>"']/g, char => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));
}

async function loadUser() {
  try {
    const me = await request('/api/me');
    if ($('userName')) {
      $('userName').textContent = me.name || me.username;
      $('userName').title = `${me.username}${me.email ? ' · ' + me.email : ''}`;
    }
    if (me.role === 'admin') {
      if ($('navAdmin')) $('navAdmin').hidden = false;
      if (!MODULES.some(m => m.id === 'admin')) {
        MODULES.push({
          id: "admin",
          title: "Administration & Settings",
          description: "Manage users, access permissions, audio AI models, and email notifications",
          href: "/admin",
          badge: "Control Center",
          icon: `<svg viewBox="0 0 24 24" width="24" height="24" stroke="currentColor" stroke-width="2" fill="none" stroke-linecap="round" stroke-linejoin="round"><path d="M12.22 2h-.44a2 2 0 0 0-2 2v.18a2 2 0 0 1-1 1.73l-.43.25a2 2 0 0 1-2 0l-.15-.08a2 2 0 0 0-2.73.73l-.22.38a2 2 0 0 0 .73 2.73l.15.1a2 2 0 0 1 1 1.72v.51a2 2 0 0 1-1 1.74l-.15.09a2 2 0 0 0-.73 2.73l.22.38a2 2 0 0 0 2.73.73l.15-.08a2 2 0 0 1 2 0l.43.25a2 2 0 0 1 1 1.73V20a2 2 0 0 0 2 2h.44a2 2 0 0 0 2-2v-.18a2 2 0 0 1 1-1.73l.43-.25a2 2 0 0 1 2 0l.15.08a2 2 0 0 0 2.73-.73l.22-.39a2 2 0 0 0-.73-2.73l-.15-.08a2 2 0 0 1-1-1.74v-.5a2 2 0 0 1 1-1.74l.15-.09a2 2 0 0 0 .73-2.73l-.22-.38a2 2 0 0 0-2.73-.73l-.15.08a2 2 0 0 1-2 0l-.43-.25a2 2 0 0 1-1-1.73V4a2 2 0 0 0-2-2z"/><circle cx="12" cy="12" r="3"/></svg>`,
        });
        renderModules();
      }
    }
  } catch (error) {
    if (error.message.includes('Authentication')) location.href = '/';
  }
}

function renderModules() {
  const grid = $('modulesGrid');
  if (!grid) return;
  grid.innerHTML = MODULES.map(mod => `
    <a href="${escapeHtml(mod.href)}" class="module-card">
      <div class="module-card-head">
        <div class="module-card-icon">${mod.icon}</div>
        ${mod.badge ? `<span class="module-card-badge">${escapeHtml(mod.badge)}</span>` : ''}
      </div>
      <h3>${escapeHtml(mod.title)}</h3>
      <p>${escapeHtml(mod.description)}</p>
      <div class="module-card-foot">
        <span>Open module</span>
        <span aria-hidden="true">&rarr;</span>
      </div>
    </a>
  `).join('');
}

$('logout').onclick = async () => {
  await fetch('/api/logout', {method: 'POST'});
  location.href = '/';
};

loadUser();
renderModules();
