const $ = (id) => document.getElementById(id);

async function request(url, options = {}) {
  const response = await fetch(url, options);
  if (!response.ok) throw new Error((await response.json()).detail || response.statusText);
  return response.json();
}

function escapeHtml(value) {
  return String(value ?? '').replace(/[&<>"']/g, char => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));
}

let currentUser = null;
let currentScope = 'my';

async function loadUser() {
  try {
    const me = await request('/api/me');
    currentUser = me;
    if ($('userName')) {
      $('userName').textContent = me.name || me.username;
      $('userName').title = `${me.username}${me.email ? ' · ' + me.email : ''}`;
    }
    if (me.role === 'admin') {
      if ($('navAdmin')) $('navAdmin').hidden = false;
      if ($('jobScopeToggle')) $('jobScopeToggle').hidden = false;
    }
  } catch (error) {
    if (error.message.includes('Authentication')) location.href = '/';
  }
}

function formatEta(seconds) {
  if (!seconds || seconds <= 0) return '';
  const total = Math.round(seconds);
  if (total < 60) return `ETA ${total}s`;
  const m = Math.floor(total / 60);
  const s = total % 60;
  if (m < 60) return s > 0 ? `ETA ${m}m ${s}s` : `ETA ${m}m`;
  const h = Math.floor(m / 60);
  const remM = m % 60;
  return remM > 0 ? `ETA ${h}h ${remM}m` : `ETA ${h}h`;
}

let jobsPollTimeout = null;

document.addEventListener('pointerdown', (event) => {
  const renameButton = event.target.closest('[data-rename-speakers]');
  if (renameButton) {
    event.stopPropagation();
    openSpeakerEditor(renameButton.dataset.renameSpeakers);
    return;
  }

  const viewButton = event.target.closest('[data-view-job]');
  if (viewButton) {
    event.stopPropagation();
    openTranscriptViewer(viewButton.dataset.viewJob);
    return;
  }

  const removeButton = event.target.closest('[data-remove-job]');
  if (removeButton) {
    event.stopPropagation();
    removeJob(removeButton.dataset.removeJob);
    return;
  }

  const moreButton = event.target.closest('.job-more-btn');
  if (moreButton) {
    event.preventDefault();
    event.stopPropagation();
    const menu = document.getElementById(`job-menu-${moreButton.dataset.jobId}`);
    if (!menu) return;
    const shouldOpen = menu.hidden;
    closeJobMenus();
    if (shouldOpen) {
      menu.hidden = false;
      moreButton.setAttribute('aria-expanded', 'true');
    }
    return;
  }

  if (!event.target.closest('.job-actions-menu')) {
    closeJobMenus();
  }
});

document.addEventListener('keydown', (event) => {
  if (event.key === 'Escape') {
    closeJobMenus();
  }
});

function closeJobMenus() {
  document.querySelectorAll('.job-actions-menu').forEach(menu => {
    menu.hidden = true;
  });
  document.querySelectorAll('.job-more-btn').forEach(button => {
    button.setAttribute('aria-expanded', 'false');
  });
}

function jobActionIcon(type) {
  const icons = {
    transcript: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/><line x1="8" y1="13" x2="16" y2="13"/><line x1="8" y1="17" x2="14" y2="17"/></svg>',
    txt: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/><line x1="8" y1="13" x2="16" y2="13"/><line x1="8" y1="17" x2="16" y2="17"/></svg>',
    txt_timestamps: '<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="9"/><polyline points="12 7 12 12 15 14"/></svg>',
    srt: '<svg viewBox="0 0 24 24" aria-hidden="true"><rect x="3" y="5" width="18" height="14" rx="2"/><path d="M7 10h4M13 10h4M7 14h2M11 14h6"/></svg>',
    vtt: '<svg viewBox="0 0 24 24" aria-hidden="true"><rect x="3" y="5" width="18" height="14" rx="2"/><path d="M7 10h10M7 14h10"/></svg>',
    docx: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/><path d="M8 13h8M8 17h6"/></svg>',
    json: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M9 4C7 4 7 6 7 8v1c0 2-1 3-3 3 2 0 3 1 3 3v1c0 2 0 4 2 4M15 4c2 0 2 2 2 4v1c0 2 1 3 3 3-2 0-3 1-3 3v1c0 2 0 4-2 4"/></svg>',
    speakers: '<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="9" cy="8" r="3"/><path d="M3 20a6 6 0 0 1 12 0M16 11a3 3 0 0 1 0 6M18 20a5 5 0 0 0-2-3.9"/></svg>',
    delete: '<svg viewBox="0 0 24 24" aria-hidden="true"><polyline points="3 6 5 6 21 6"/><path d="M8 6V4h8v2M19 6l-1 14H6L5 6"/><line x1="10" y1="11" x2="10" y2="17"/><line x1="14" y1="11" x2="14" y2="17"/></svg>'
  };
  return `<span class="job-action-icon">${icons[type] || icons.txt}</span>`;
}

function buildJobMenu(job) {
  const fileRoot = `/api/jobs/${job.id}/outputs/${job.filename.replace(/\.[^.]+$/, '')}`;
  const outputActions = job.status === 'done'
    ? job.formats.map(format => {
        const fileSuffix = format === 'txt_timestamps' ? '_timestamps.txt' : `.${format}`;
        const label = format === 'txt_timestamps' ? 'Download TXT timestamps' : `Download ${format.toUpperCase()}`;
        return `<a class="job-action-link" href="${fileRoot}${fileSuffix}" download>${jobActionIcon(format)}<span>${label}</span></a>`;
      }).join('')
    : '';
  const speakerAction = job.status === 'done' && job.diarization
    ? `<button type="button" class="job-action" data-rename-speakers="${job.id}">${jobActionIcon('speakers')}<span>Rename speakers</span></button>`
    : '';

  return `
    <div class="job-actions">
      <button type="button" class="job-more-btn" aria-label="More actions for ${escapeHtml(job.filename)}" aria-expanded="false" data-job-id="${job.id}">⋯</button>
      <div class="job-actions-menu" id="job-menu-${job.id}" hidden>
        <button type="button" class="job-action" data-view-job="${job.id}">${jobActionIcon('transcript')}<span>View transcript</span></button>
        ${speakerAction}
        ${outputActions}
        <button type="button" class="job-action danger" data-remove-job="${job.id}">${jobActionIcon('delete')}<span>Delete job</span></button>
      </div>
    </div>
  `;
}

async function openTranscriptViewer(jobId) {
  const modalId = 'transcript-viewer-modal';
  const existing = document.getElementById(modalId);
  if (existing) existing.remove();

  const state = { saving: false };
  const modal = document.createElement('div');
  modal.id = modalId;
  modal.className = 'transcript-modal-backdrop';
  modal.innerHTML = `
    <div class="transcript-modal" role="dialog" aria-modal="true" aria-labelledby="transcript-modal-title">
      <div class="transcript-modal-header">
        <h3 id="transcript-modal-title">Transcript</h3>
        <button type="button" class="transcript-close-btn" aria-label="Close transcript viewer">&times;</button>
      </div>
      <div class="transcript-modal-body">
        <textarea id="transcript-editor" aria-label="Transcript text" spellcheck="false" placeholder="Loading transcript..."></textarea>
      </div>
      <div class="transcript-modal-actions">
        <button type="button" id="transcript-save-btn" class="primary">Save changes</button>
        <button type="button" id="transcript-cancel-btn" class="quiet">Close</button>
      </div>
    </div>
  `;
  document.body.appendChild(modal);

  const textarea = modal.querySelector('#transcript-editor');
  const saveBtn = modal.querySelector('#transcript-save-btn');
  const closeBtn = modal.querySelector('.transcript-close-btn');
  const cancelBtn = modal.querySelector('#transcript-cancel-btn');

  const closeModal = () => modal.remove();

  const closeHandlers = [closeBtn, cancelBtn];
  closeHandlers.forEach(button => button.addEventListener('click', closeModal));
  modal.addEventListener('click', (event) => {
    if (event.target === modal) closeModal();
  });

  try {
    const preview = await request(`/api/jobs/${jobId}/preview`);
    let transcriptText = '';
    try {
      const segments = JSON.parse(preview.segments || '[]');
      transcriptText = Array.isArray(segments)
        ? segments.map(segment => (segment && segment.text ? String(segment.text).trim() : '')).filter(Boolean).join('\n\n')
        : '';
    } catch {
      transcriptText = '';
    }
    if (!transcriptText.trim()) {
      transcriptText = 'No transcript content is available yet for this job.';
    }
    textarea.value = transcriptText;
  } catch (error) {
    textarea.value = 'Unable to load this transcript right now.';
  }

  saveBtn.addEventListener('click', async () => {
    if (state.saving) return;
    state.saving = true;
    saveBtn.disabled = true;
    saveBtn.textContent = 'Saving...';

    try {
      await request(`/api/jobs/${jobId}/preview`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ text: textarea.value })
      });
      closeModal();
    } catch (error) {
      alert(error.message || 'Unable to save transcript changes.');
    } finally {
      state.saving = false;
      saveBtn.disabled = false;
      saveBtn.textContent = 'Save changes';
    }
  });
}

async function openSpeakerEditor(jobId) {
  const modalId = 'speaker-editor-modal';
  const existing = document.getElementById(modalId);
  if (existing) existing.remove();

  const modal = document.createElement('div');
  modal.id = modalId;
  modal.className = 'transcript-modal-backdrop';
  modal.innerHTML = `
    <div class="transcript-modal speaker-editor-modal" role="dialog" aria-modal="true" aria-labelledby="speaker-editor-title">
      <div class="transcript-modal-header">
        <h3 id="speaker-editor-title">Rename speakers</h3>
        <button type="button" class="transcript-close-btn" aria-label="Close speaker editor">&times;</button>
      </div>
      <div class="transcript-modal-body">
        <p class="meta speaker-editor-intro">Names are applied when exports are regenerated. The original speaker labels remain unchanged.</p>
        <div id="speaker-editor-list" class="speaker-editor-list"><p class="meta">Loading speakers...</p></div>
        <p id="speaker-editor-error" class="error"></p>
      </div>
      <div class="transcript-modal-actions">
        <button type="button" id="speaker-save-btn" class="primary">Save and regenerate</button>
        <button type="button" id="speaker-cancel-btn" class="quiet">Close</button>
      </div>
    </div>
  `;
  document.body.appendChild(modal);

  const list = modal.querySelector('#speaker-editor-list');
  const error = modal.querySelector('#speaker-editor-error');
  const saveBtn = modal.querySelector('#speaker-save-btn');
  const closeModal = () => modal.remove();
  modal.querySelector('.transcript-close-btn').addEventListener('click', closeModal);
  modal.querySelector('#speaker-cancel-btn').addEventListener('click', closeModal);
  modal.addEventListener('click', (event) => {
    if (event.target === modal) closeModal();
  });

  try {
    const data = await request(`/api/jobs/${jobId}/speakers`);
    list.innerHTML = data.speakers.map(speaker => `
      <label class="speaker-editor-row">
        <span class="speaker-editor-label">${escapeHtml(speaker.speaker_label)}</span>
        <span class="speaker-editor-sample">${escapeHtml(speaker.sample)}</span>
        <input type="text" maxlength="120" data-speaker-label="${escapeHtml(speaker.speaker_label)}" value="${escapeHtml(speaker.display_name)}" placeholder="Display name">
      </label>
    `).join('');
  } catch (requestError) {
    error.textContent = requestError.message || 'Unable to load speakers.';
    saveBtn.disabled = true;
    return;
  }

  saveBtn.addEventListener('click', async () => {
    saveBtn.disabled = true;
    error.textContent = '';
    const names = {};
    list.querySelectorAll('[data-speaker-label]').forEach(input => {
      names[input.dataset.speakerLabel] = input.value.trim();
    });
    try {
      await request(`/api/jobs/${jobId}/speakers`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ names })
      });
      await request(`/api/jobs/${jobId}/speakers/regenerate`, { method: 'POST' });
      closeModal();
      await loadJobs();
    } catch (requestError) {
      error.textContent = requestError.message || 'Unable to regenerate exports.';
      saveBtn.disabled = false;
    }
  });
}

function bindTranscriptMenuActions() {
  document.querySelectorAll('[data-view-job]').forEach(button => {
    button.addEventListener('click', () => openTranscriptViewer(button.dataset.viewJob));
  });
}

async function loadJobs() {
  clearTimeout(jobsPollTimeout);
  let hasActiveWork = false;
  const openMenu = document.querySelector('.job-actions-menu:not([hidden])');
  const openMenuId = openMenu?.id;
  try {
    const isAllView = currentScope === 'all' && currentUser?.role === 'admin';
    const url = isAllView ? '/api/jobs?all_jobs=true' : '/api/jobs';
    const jobs = await request(url);
    const filtered = jobs.filter(job => job.status !== 'deleted');
    hasActiveWork = filtered.some(job => job.status === 'processing' || job.status === 'waiting');
    filtered.sort((a, b) => new Date(b.created_at || 0) - new Date(a.created_at || 0));
    $('jobs').innerHTML = filtered.length
      ? filtered.map(job => {
          const modelInfo = job.status === 'waiting'
            ? `requested ${job.requested_model}`
            : `requested ${job.requested_model} · used ${job.selected_model || 'pending'}`;
          const ownerBadge = isAllView && job.created_by
            ? ` · <span class="tag-owner" title="Uploaded by ${escapeHtml(job.created_by)}">Dept: ${escapeHtml(job.created_by)}</span>`
            : '';
          return `<article class="job" id="job-${job.id}">
          <div>
            <h3>${escapeHtml(job.filename)}</h3>
            <div class="meta">${job.status === 'waiting' ? `Queue position ${job.queue_position}` : job.status} · ${modelInfo}${ownerBadge}${job.diarization ? ' · <span class="tag-diarization">Diarized</span>' : ''}</div>
            <div class="bar"><i style="width:${job.progress}%"></i></div>
            <div class="meta">${Math.round(job.progress)}% ${job.error ? '· ' + escapeHtml(job.error) : ''}</div>
          </div>
          <div class="job-status-col">
            <span class="status ${job.status}">${job.status}</span>
            ${job.status === 'processing' && job.eta_seconds ? `<span class="job-eta meta" title="${Math.round(job.eta_seconds)}s remaining"><svg viewBox="0 0 24 24" width="13" height="13" stroke="currentColor" stroke-width="2" fill="none" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/></svg>${formatEta(job.eta_seconds)}</span>` : ''}
          </div>
          ${buildJobMenu(job)}
        </article>`;
        }).join('')
      : `
        <div class="empty-state">
          <div class="empty-state-icon">
            <svg viewBox="0 0 24 24" width="22" height="22" stroke="currentColor" stroke-width="2" fill="none" stroke-linecap="round" stroke-linejoin="round"><path d="M12 2a3 3 0 0 0-3 3v7a3 3 0 0 0 6 0V5a3 3 0 0 0-3-3Z"/><path d="M19 10v2a7 7 0 0 1-14 0v-2"/><line x1="12" y1="19" x2="12" y2="22"/></svg>
          </div>
          <p class="empty-state-title">No active jobs in the queue.</p>
          <p class="empty-state-guide">Drop a recording above to get started</p>
        </div>`;

    if (openMenuId) {
      const restoredMenu = document.getElementById(openMenuId);
      const restoredButton = restoredMenu?.parentElement?.querySelector('.job-more-btn');
      if (restoredMenu && restoredButton) {
        restoredMenu.hidden = false;
        restoredButton.setAttribute('aria-expanded', 'true');
      }
    }
  } catch (error) {
    if (error.message.includes('Authentication')) location.href = '/';
  } finally {
    const nextInterval = hasActiveWork ? 1500 : 3000;
    jobsPollTimeout = setTimeout(loadJobs, nextInterval);
  }
}

$('logout').onclick = async () => {
  await fetch('/api/logout', {method: 'POST'});
  location.href = '/';
};

let selectedFile = null;
let dragCounter = 0;

const ALLOWED_AUDIO_EXTS = ['.mp3', '.wav', '.m4a', '.mp4', '.mkv', '.ogg', '.flac', '.webm'];

function formatBytes(value) {
  if (!value || value === 0) return '0 B';
  if (value < 1024) return `${value} B`;
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KB`;
  return `${(value / (1024 * 1024)).toFixed(1)} MB`;
}

function validateAudioFile(file) {
  if (!file) return 'Choose a recording first.';
  const name = file.name.toLowerCase();
  const isValid = ALLOWED_AUDIO_EXTS.some(ext => name.endsWith(ext));
  if (!isValid) {
    return `Unsupported file format. Please select an audio or video file (${ALLOWED_AUDIO_EXTS.join(', ')}).`;
  }
  return null;
}

function renderDropDefault() {
  const drop = $('drop');
  if (!drop) return;
  drop.classList.remove('has-file', 'dragover');
  const content = $('dropContent');
  if (content) {
    content.innerHTML = `
      <div class="drop-icon" aria-hidden="true">
        <svg viewBox="0 0 24 24" width="32" height="32" stroke="currentColor" stroke-width="2" fill="none" stroke-linecap="round" stroke-linejoin="round">
          <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/>
          <polyline points="17 8 12 3 7 8"/>
          <line x1="12" y1="3" x2="12" y2="15"/>
        </svg>
      </div>
      <strong>Drop an audio or video recording here</strong>
      <span class="drop-help">MP3, WAV, M4A, MP4, MKV, OGG, FLAC, WEBM &middot; or click to browse</span>
    `;
  }
}

function renderDropSelected(file) {
  const drop = $('drop');
  if (!drop) return;
  drop.classList.remove('dragover');
  drop.classList.add('has-file');
  const content = $('dropContent');
  if (content) {
    content.innerHTML = `
      <div class="drop-file-selected">
        <div class="drop-icon-badge" aria-hidden="true">
          <svg viewBox="0 0 24 24" width="24" height="24" stroke="currentColor" stroke-width="2.5" fill="none" stroke-linecap="round" stroke-linejoin="round">
            <polyline points="20 6 9 17 4 12"/>
          </svg>
        </div>
        <div class="drop-file-details">
          <div class="drop-file-status">Recording ready to transcribe</div>
          <div class="drop-filename" title="${escapeHtml(file.name)}">${escapeHtml(file.name)}</div>
          <div class="drop-meta">
            <span class="drop-filesize">${formatBytes(file.size)}</span>
            <span class="drop-sep">&middot;</span>
            <span class="drop-action-hint">Click or drop another file to replace</span>
          </div>
        </div>
        <button type="button" id="removeFile" class="drop-remove-btn" title="Remove recording" aria-label="Remove recording">&times;</button>
      </div>
    `;
    const removeBtn = $('removeFile');
    if (removeBtn) {
      removeBtn.onclick = (e) => {
        e.stopPropagation();
        clearFile();
      };
    }
  }
}

function setFile(file) {
  const error = validateAudioFile(file);
  if (error) {
    $('uploadError').textContent = error;
    return false;
  }
  $('uploadError').textContent = '';
  selectedFile = file;
  try {
    const dt = new DataTransfer();
    dt.items.add(file);
    $('file').files = dt.files;
  } catch (_) {}
  renderDropSelected(file);
  return true;
}

function clearFile() {
  selectedFile = null;
  if ($('file')) $('file').value = '';
  $('uploadError').textContent = '';
  renderDropDefault();
}

const dropZone = $('drop');
if (dropZone) {
  dropZone.onclick = (e) => {
    if (e.target.closest('#removeFile')) return;
    $('file').click();
  };

  dropZone.onkeydown = (e) => {
    if (e.key === 'Enter' || e.key === ' ') {
      e.preventDefault();
      $('file').click();
    }
  };

  dropZone.ondragenter = (e) => {
    e.preventDefault();
    e.stopPropagation();
    dragCounter++;
    dropZone.classList.add('dragover');
  };

  dropZone.ondragover = (e) => {
    e.preventDefault();
    e.stopPropagation();
    if (!dropZone.classList.contains('dragover')) {
      dropZone.classList.add('dragover');
    }
  };

  dropZone.ondragleave = (e) => {
    e.preventDefault();
    e.stopPropagation();
    dragCounter--;
    if (dragCounter <= 0) {
      dragCounter = 0;
      dropZone.classList.remove('dragover');
    }
  };

  dropZone.ondrop = (e) => {
    e.preventDefault();
    e.stopPropagation();
    dragCounter = 0;
    dropZone.classList.remove('dragover');
    const file = e.dataTransfer?.files?.[0];
    if (file) {
      setFile(file);
    }
  };
}

if ($('file')) {
  $('file').onchange = (e) => {
    const file = e.target.files?.[0];
    if (file) {
      setFile(file);
    }
  };
}

window.addEventListener('dragover', (e) => e.preventDefault());
window.addEventListener('drop', (e) => e.preventDefault());

let diarizationInfo = { available: false, has_token: false };

async function checkDiarization() {
  try {
    diarizationInfo = await request('/api/diarization/status');
    const field = $('diarizationField');
    if (field) {
      if (diarizationInfo.has_token) {
        field.hidden = false;
      } else {
        field.hidden = true;
        if ($('diarization')) $('diarization').checked = false;
      }
    }
  } catch {
    // optional check
  }
}

$('upload').onclick = async () => {
  const file = selectedFile || ($('file')?.files?.[0]);
  if (!file) return $('uploadError').textContent = 'Choose a recording first.';

  const isDiarize = $('diarizationField')?.hidden ? false : ($('diarization')?.checked || false);

  const uploadBtn = $('upload');
  uploadBtn.disabled = true;
  const originalText = uploadBtn.textContent;
  uploadBtn.textContent = 'Adding to queue...';

  const body = new FormData();
  body.append('file', file);
  body.append('model', $('model').value);
  body.append('language', $('language').value);
  body.append('initial_prompt', $('prompt').value);
  body.append('diarization', isDiarize);

  try {
    await request('/api/jobs', {method: 'POST', body});
    $('uploadError').textContent = '';
    clearFile();
    loadJobs();
  } catch (error) {
    $('uploadError').textContent = error.message;
  } finally {
    uploadBtn.disabled = false;
    uploadBtn.textContent = originalText;
  }
};

async function removeJob(id) {
  await request('/api/jobs/' + id, {method: 'DELETE'});
  loadJobs();
}

$('refresh').onclick = loadJobs;
if ($('scopeMyJobs')) {
  $('scopeMyJobs').onclick = () => {
    currentScope = 'my';
    $('scopeMyJobs').classList.add('active');
    $('scopeAllJobs').classList.remove('active');
    loadJobs();
  };
}
if ($('scopeAllJobs')) {
  $('scopeAllJobs').onclick = () => {
    currentScope = 'all';
    $('scopeAllJobs').classList.add('active');
    $('scopeMyJobs').classList.remove('active');
    loadJobs();
  };
}

// --- In-Browser Live Audio Recording ---
let currentUploadMode = 'upload';
let mediaStream = null;
let mediaRecorder = null;
let isRecording = false;
let isPaused = false;
let recordedSeconds = 0;
let timerInterval = null;
let periodicFlushInterval = null;
let recordingSessionId = null;
let nextChunkIndex = 0;
let unflushedChunks = [];
let isFlushingChunks = false;

function setUploadMode(mode) {
  if (isRecording) {
    if (!confirm('Recording is currently in progress. Switching tabs will abandon this recording. Do you want to continue?')) {
      return;
    }
    cancelLiveRecording();
  }
  currentUploadMode = mode;
  if (mode === 'upload') {
    $('modeUploadTab')?.classList.add('active');
    $('modeRecordTab')?.classList.remove('active');
    $('drop').hidden = false;
    $('recordArea').hidden = true;
    $('upload').hidden = false;
  } else {
    $('modeRecordTab')?.classList.add('active');
    $('modeUploadTab')?.classList.remove('active');
    $('drop').hidden = true;
    $('recordArea').hidden = false;
    $('upload').hidden = true;
  }
}

$('modeUploadTab')?.addEventListener('click', () => setUploadMode('upload'));
$('modeRecordTab')?.addEventListener('click', () => setUploadMode('record'));

function getSupportedMimeType() {
  const types = [
    'audio/webm;codecs=opus',
    'audio/webm',
    'audio/ogg;codecs=opus',
    'audio/ogg',
    'audio/mp4',
  ];
  for (const t of types) {
    if (window.MediaRecorder && MediaRecorder.isTypeSupported && MediaRecorder.isTypeSupported(t)) {
      return t;
    }
  }
  return '';
}

function formatHHMMSS(totalSecs) {
  const h = Math.floor(totalSecs / 3600);
  const m = Math.floor((totalSecs % 3600) / 60);
  const s = totalSecs % 60;
  const pad = (n) => String(n).padStart(2, '0');
  return `${pad(h)}:${pad(m)}:${pad(s)}`;
}

async function startLiveRecording() {
  $('recordError').textContent = '';
  if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
    $('recordError').textContent = 'Microphone recording is not supported in this browser or requires an HTTPS / localhost connection.';
    return;
  }

  try {
    mediaStream = await navigator.mediaDevices.getUserMedia({ audio: true });
  } catch (err) {
    if (err.name === 'NotAllowedError' || err.name === 'PermissionDeniedError') {
      $('recordError').textContent = 'Microphone access was denied. Please allow microphone permissions in your browser address bar to record.';
    } else if (err.name === 'NotFoundError' || err.name === 'DevicesNotFoundError') {
      $('recordError').textContent = 'No microphone was found on your device. Please connect a microphone and try again.';
    } else {
      $('recordError').textContent = `Could not access microphone: ${err.message || err.name}`;
    }
    return;
  }

  const mimeType = getSupportedMimeType();
  try {
    mediaRecorder = new MediaRecorder(mediaStream, mimeType ? { mimeType } : undefined);
  } catch (err) {
    mediaRecorder = new MediaRecorder(mediaStream);
  }

  recordingSessionId = 'rec_' + Date.now() + '_' + Math.random().toString(36).substring(2, 9);
  nextChunkIndex = 0;
  unflushedChunks = [];
  recordedSeconds = 0;
  isRecording = true;
  isPaused = false;
  $('recordTimer').textContent = '00:00:00';

  mediaRecorder.ondataavailable = (e) => {
    if (e.data && e.data.size > 0) {
      unflushedChunks.push(e.data);
    }
  };

  // Collect data in chunks via MediaRecorder timeslice (1000ms)
  mediaRecorder.start(1000);

  // Update UI to recording state
  const pill = $('recordStatusPill');
  if (pill) {
    pill.className = 'status failed';
    pill.textContent = 'RECORDING';
    pill.hidden = false;
  }
  $('startRecordBtn').hidden = true;
  $('pauseRecordBtn').hidden = false;
  $('pauseRecordBtn').textContent = 'Pause';
  $('resumeRecordBtn').hidden = true;
  $('stopRecordBtn').hidden = false;
  $('cancelRecordBtn').hidden = false;

  timerInterval = setInterval(() => {
    if (!isPaused) {
      recordedSeconds++;
      $('recordTimer').textContent = formatHHMMSS(recordedSeconds);
    }
  }, 1000);

  // Periodically flush captured chunks to server every 20 seconds
  periodicFlushInterval = setInterval(() => {
    if (isRecording) {
      flushChunksToServer();
    }
  }, 20000);
}

async function flushChunksToServer() {
  if (isFlushingChunks || !recordingSessionId || unflushedChunks.length === 0) return;
  isFlushingChunks = true;
  try {
    while (unflushedChunks.length > 0) {
      const batch = unflushedChunks.splice(0, unflushedChunks.length);
      const blob = new Blob(batch, { type: mediaRecorder?.mimeType || 'audio/webm' });
      const currentIdx = nextChunkIndex++;
      const form = new FormData();
      form.append('chunk_index', currentIdx);
      form.append('chunk', blob, `chunk_${currentIdx}.webm`);
      await fetch(`/api/recordings/${recordingSessionId}/chunks`, {
        method: 'POST',
        body: form
      });
    }
  } catch (err) {
    console.warn('Periodic chunk backup failed:', err);
  } finally {
    isFlushingChunks = false;
  }
}

function pauseLiveRecording() {
  if (mediaRecorder && mediaRecorder.state === 'recording') {
    mediaRecorder.pause();
    isPaused = true;
    const pill = $('recordStatusPill');
    if (pill) {
      pill.className = 'status waiting';
      pill.textContent = 'PAUSED';
    }
    $('pauseRecordBtn').hidden = true;
    $('resumeRecordBtn').hidden = false;
  }
}

function resumeLiveRecording() {
  if (mediaRecorder && mediaRecorder.state === 'paused') {
    mediaRecorder.resume();
    isPaused = false;
    const pill = $('recordStatusPill');
    if (pill) {
      pill.className = 'status failed';
      pill.textContent = 'RECORDING';
    }
    $('resumeRecordBtn').hidden = true;
    $('pauseRecordBtn').hidden = false;
  }
}

async function stopLiveRecording() {
  if (!isRecording) return;
  isRecording = false;
  isPaused = false;
  clearInterval(timerInterval);
  clearInterval(periodicFlushInterval);

  const stopBtn = $('stopRecordBtn');
  stopBtn.disabled = true;
  const originalStopText = stopBtn.textContent;
  stopBtn.textContent = 'Finalizing...';
  $('pauseRecordBtn').hidden = true;
  $('resumeRecordBtn').hidden = true;

  if (mediaRecorder && mediaRecorder.state !== 'inactive') {
    mediaRecorder.stop();
  }
  if (mediaStream) {
    mediaStream.getTracks().forEach(t => t.stop());
  }

  // Small delay to ensure final ondataavailable chunk is captured
  await new Promise(r => setTimeout(r, 200));

  try {
    await flushChunksToServer();

    const isDiarize = $('diarization') ? $('diarization').checked : false;
    const dateStr = new Date().toISOString().slice(0, 16).replace(/[:T]/g, '-');
    const filename = `Meeting_Recording_${dateStr}.webm`;

    const body = new FormData();
    body.append('filename', filename);
    body.append('model', $('model').value);
    body.append('language', $('language').value);
    body.append('initial_prompt', $('prompt').value);
    body.append('diarization', isDiarize);

    const res = await fetch(`/api/recordings/${recordingSessionId}/finalize`, {
      method: 'POST',
      body
    });
    if (!res.ok) {
      const errJson = await res.json().catch(() => ({}));
      throw new Error(errJson.detail || res.statusText);
    }

    $('recordError').textContent = '';
    resetRecordingUI();
    loadJobs();
  } catch (err) {
    $('recordError').textContent = `Failed to finalize recording: ${err.message}`;
    stopBtn.disabled = false;
    stopBtn.textContent = originalStopText;
  }
}

async function cancelLiveRecording() {
  if (isRecording) {
    if (!confirm('Are you sure you want to discard this recording?')) return;
  }
  isRecording = false;
  isPaused = false;
  clearInterval(timerInterval);
  clearInterval(periodicFlushInterval);

  if (mediaRecorder && mediaRecorder.state !== 'inactive') {
    mediaRecorder.stop();
  }
  if (mediaStream) {
    mediaStream.getTracks().forEach(t => t.stop());
  }

  if (recordingSessionId) {
    fetch(`/api/recordings/${recordingSessionId}`, { method: 'DELETE' }).catch(() => {});
  }

  resetRecordingUI();
}

function resetRecordingUI() {
  isRecording = false;
  isPaused = false;
  recordingSessionId = null;
  nextChunkIndex = 0;
  unflushedChunks = [];
  recordedSeconds = 0;
  $('recordTimer').textContent = '00:00:00';
  if ($('recordStatusPill')) $('recordStatusPill').hidden = true;
  $('startRecordBtn').hidden = false;
  $('pauseRecordBtn').hidden = true;
  $('resumeRecordBtn').hidden = true;
  const stopBtn = $('stopRecordBtn');
  stopBtn.hidden = true;
  stopBtn.disabled = false;
  stopBtn.textContent = 'Stop & Transcribe';
  $('cancelRecordBtn').hidden = true;
}

$('startRecordBtn')?.addEventListener('click', startLiveRecording);
$('pauseRecordBtn')?.addEventListener('click', pauseLiveRecording);
$('resumeRecordBtn')?.addEventListener('click', resumeLiveRecording);
$('stopRecordBtn')?.addEventListener('click', stopLiveRecording);
$('cancelRecordBtn')?.addEventListener('click', cancelLiveRecording);

window.addEventListener('beforeunload', (e) => {
  if (isRecording) {
    e.preventDefault();
    e.returnValue = 'Recording in progress — are you sure you want to leave?';
    return e.returnValue;
  }
});

loadUser();
loadJobs();
checkDiarization();
