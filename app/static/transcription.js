const $ = (id) => document.getElementById(id);

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

async function loadJobs() {
  try {
    const jobs = await request('/api/jobs');
    const filtered = jobs.filter(job => job.status !== 'deleted');
    filtered.sort((a, b) => new Date(b.created_at || 0) - new Date(a.created_at || 0));
    $('jobs').innerHTML = filtered.length
      ? filtered.map(job => `<article class="job" id="job-${job.id}">
          <div>
            <h3>${escapeHtml(job.filename)}</h3>
            <div class="meta">${job.status === 'waiting' ? `Queue position ${job.queue_position}` : job.status} · requested ${job.requested_model} · used ${job.selected_model || 'pending'}${job.diarization ? ' · <span class="tag-diarization">Diarized</span>' : ''}</div>
            <div class="bar"><i style="width:${job.progress}%"></i></div>
            <div class="meta">${Math.round(job.progress)}% ${job.error ? '· ' + escapeHtml(job.error) : ''}</div>
          </div>
          <div class="job-status-col">
            <span class="status ${job.status}">${job.status}</span>
            ${job.status === 'processing' && job.eta_seconds ? `<span class="job-eta meta" title="${Math.round(job.eta_seconds)}s remaining"><svg viewBox="0 0 24 24" width="13" height="13" stroke="currentColor" stroke-width="2" fill="none" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/></svg>${formatEta(job.eta_seconds)}</span>` : ''}
          </div>
          <div class="downloads">
            ${job.status === 'done' ? job.formats.map(format => `<a href="/api/jobs/${job.id}/outputs/${job.filename.replace(/\.[^.]+$/, '')}${format === 'txt_timestamps' ? '_timestamps.txt' : '.' + format}">${format}</a>`).join('') : ''}
            <button onclick="removeJob('${job.id}')" class="quiet">Delete</button>
          </div>
        </article>`).join('')
      : `
        <div class="empty-state">
          <div class="empty-state-icon">
            <svg viewBox="0 0 24 24" width="22" height="22" stroke="currentColor" stroke-width="2" fill="none" stroke-linecap="round" stroke-linejoin="round"><path d="M12 2a3 3 0 0 0-3 3v7a3 3 0 0 0 6 0V5a3 3 0 0 0-3-3Z"/><path d="M19 10v2a7 7 0 0 1-14 0v-2"/><line x1="12" y1="19" x2="12" y2="22"/></svg>
          </div>
          <p class="empty-state-title">No active jobs in the queue.</p>
          <p class="empty-state-guide">Drop a recording above to get started</p>
        </div>`;
  } catch (error) {
    if (error.message.includes('Authentication')) location.href = '/';
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
  body.append('formats', $('formats').value);
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
setInterval(loadJobs, 3000);
loadUser();
loadJobs();
checkDiarization();

