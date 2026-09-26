const $ = id => document.getElementById(id);
let folderId = '';
let currentDocuments = [];
const selectedDocIds = new Set();

const ALLOWED_EXTENSIONS = new Set([
  'pdf', 'doc', 'docx', 'xls', 'xlsx', 'ppt', 'pptx',
  'txt', 'csv', 'rtf', 'odt', 'ods', 'odp', 'jpg', 'jpeg', 'png'
]);
const MAX_SIZE_BYTES = 50 * 1024 * 1024; // 50MB

function validateFile(file) {
  if (!file) return 'No file selected.';
  const nameParts = file.name.split('.');
  const ext = nameParts.length > 1 ? nameParts.pop().toLowerCase() : '';
  if (!ALLOWED_EXTENSIONS.has(ext)) {
    return `File type '.${ext || 'unknown'}' is not allowed. Allowed types: PDF, Word, Excel, PowerPoint, text, and image files.`;
  }
  if (file.size > MAX_SIZE_BYTES) {
    return `File exceeds the 50MB size limit (${(file.size / (1024 * 1024)).toFixed(1)}MB).`;
  }
  return null;
}

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

function formatBytes(value) {
  if (value < 1024) return `${value} B`;
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KB`;
  return `${(value / (1024 * 1024)).toFixed(1)} MB`;
}

function formatDate(value) {
  return new Date(value).toLocaleDateString(undefined, {year: 'numeric', month: 'short', day: 'numeric'});
}

function updateSelectionUI() {
  const count = selectedDocIds.size;
  const toolsBtn = $('toolsBtn');
  if (toolsBtn) {
    toolsBtn.disabled = count === 0;
    toolsBtn.textContent = count > 0 ? `Tools (${count})` : 'Tools';
  }
  const summary = $('selectionSummary');
  if (summary) {
    summary.textContent = `${count} selected`;
  }
  const selectAll = $('selectAllCheckbox');
  if (selectAll && currentDocuments.length > 0) {
    selectAll.checked = currentDocuments.every(d => selectedDocIds.has(d.id));
    selectAll.indeterminate = count > 0 && !selectAll.checked;
  }
}

async function load() {
  const result = await request('/api/documents' + (folderId ? `?folder_id=${encodeURIComponent(folderId)}` : ''));
  currentDocuments = result.documents || [];

  // Remove any deleted or non-existent ids from selectedDocIds
  const currentIds = new Set(currentDocuments.map(d => d.id));
  for (const id of selectedDocIds) {
    if (!currentIds.has(id)) selectedDocIds.delete(id);
  }

  $('folders').innerHTML = result.folders.map(folder =>
    `<button class="folder-link ${folder.id === folderId ? 'active' : ''}" data-folder="${folder.id}">${escapeHtml(folder.name)}</button>`
  ).join('');

  if (currentDocuments.length > 0) {
    $('selectBar').hidden = false;
    $('documents').innerHTML = currentDocuments.map(document => {
      const isDerived = document.source_document_ids && document.source_document_ids.length > 0;
      return `<article class="document-row">
        <div class="document-lead">
          <input type="checkbox" class="doc-checkbox" data-id="${document.id}" ${selectedDocIds.has(document.id) ? 'checked' : ''} aria-label="Select ${escapeHtml(document.filename)}">
          <div>
            <button class="document-name" onclick="showVersions('${document.id}')">${escapeHtml(document.filename)}</button>
            <div class="meta">
              ${formatBytes(document.file_size)} · ${escapeHtml(document.uploaded_by)} · ${formatDate(document.uploaded_at)} · v${document.current_version}
              ${isDerived ? ' · <span class="tag-derived">Derived</span>' : ''}
            </div>
            <div class="tags">${document.tags.map(tag => `<span>${escapeHtml(tag)}</span>`).join('')}</div>
          </div>
        </div>
        <div class="document-actions">
          <a class="quiet" href="/api/documents/${document.id}/download">Download</a>
          <button class="quiet" onclick="editTags('${document.id}', '${escapeHtml(document.tags.join(', '))}')">Tags</button>
          <button class="quiet" onclick="removeDocument('${document.id}')">Delete</button>
        </div>
      </article>`;
    }).join('');
  } else {
    $('selectBar').hidden = true;
    $('documents').innerHTML = `
      <div class="empty-state">
        <div class="empty-state-icon">
          <svg viewBox="0 0 24 24" width="22" height="22" stroke="currentColor" stroke-width="2" fill="none" stroke-linecap="round" stroke-linejoin="round"><path d="M4 20h16a2 2 0 0 0 2-2V8a2 2 0 0 0-2-2h-7.93a2 2 0 0 1-1.66-.9l-.82-1.2A2 2 0 0 0 7.93 3H4a2 2 0 0 0-2 2v13c0 1.1.9 2 2 2Z"/></svg>
        </div>
        <p class="empty-state-title">No documents in this folder.</p>
        <p class="empty-state-guide">Drop a file above to get started</p>
      </div>`;
  }

  // Wire folder buttons
  document.querySelectorAll('.folder-link').forEach(button => {
    button.onclick = () => {
      folderId = button.dataset.folder;
      selectedDocIds.clear();
      load();
    };
  });

  // Wire row checkboxes
  document.querySelectorAll('.doc-checkbox').forEach(cb => {
    if (cb.id === 'selectAllCheckbox') return;
    cb.onchange = e => {
      const id = e.target.dataset.id;
      if (e.target.checked) selectedDocIds.add(id);
      else selectedDocIds.delete(id);
      updateSelectionUI();
    };
  });

  updateSelectionUI();
}

$('selectAllCheckbox')?.addEventListener('change', function () {
  if (this.checked) {
    currentDocuments.forEach(d => selectedDocIds.add(d.id));
  } else {
    selectedDocIds.clear();
  }
  document.querySelectorAll('.doc-checkbox').forEach(cb => {
    if (cb.id !== 'selectAllCheckbox') cb.checked = selectedDocIds.has(cb.dataset.id);
  });
  updateSelectionUI();
});

async function upload(file) {
  const validationError = validateFile(file);
  if (validationError) {
    $('message').textContent = validationError;
    $('file').value = '';
    return;
  }
  const body = new FormData();
  body.append('file', file);
  body.append('folder_id', folderId);
  try {
    await request('/api/documents', {method: 'POST', body});
    $('message').textContent = '';
    $('file').value = '';
    await load();
  } catch (error) {
    $('message').textContent = error.message;
  }
}

$('drop').onclick = event => {
  if (event.target.id !== 'file') $('file').click();
};
$('file').onchange = event => event.target.files[0] && upload(event.target.files[0]);
$('drop').ondragover = event => { event.preventDefault(); };
$('drop').ondrop = event => {
  event.preventDefault();
  event.dataTransfer.files[0] && upload(event.dataTransfer.files[0]);
};

$('newFolder').onclick = async () => {
  const name = prompt('Folder name');
  if (!name) return;
  const body = new FormData();
  body.append('name', name);
  body.append('parent_folder_id', folderId);
  try {
    await request('/api/documents/folders', {method: 'POST', body});
    await load();
  } catch (error) {
    $('message').textContent = error.message;
  }
};

async function showVersions(id) {
  const document = await request(`/api/documents/${id}`);
  const isDerived = document.source_document_ids && document.source_document_ids.length > 0;
  $('versionContent').innerHTML = `
    <p class="eyebrow">FILE HISTORY</p>
    <h2>${escapeHtml(document.filename)}</h2>
    ${isDerived ? `<p class="meta" style="margin-bottom: 12px;">Derived from document: ${escapeHtml(document.source_document_ids.join(', '))}</p>` : ''}
    <form id="versionForm">
      <input type="file" name="file" accept=".pdf,.doc,.docx,.xls,.xlsx,.ppt,.pptx,.txt,.csv,.rtf,.odt,.ods,.odp,.jpg,.jpeg,.png" required>
      <input name="change_note" placeholder="Optional change note">
      <button>Upload new version</button>
      <p id="versionError" class="error"></p>
    </form>
    <div class="version-list">
      ${document.versions.map(version => `
        <p>
          <strong>Version ${version.version_number}</strong> · ${formatDate(version.uploaded_at)} · ${escapeHtml(version.uploaded_by)}
          ${version.change_note ? `· ${escapeHtml(version.change_note)}` : ''}
          <a href="/api/documents/${id}/download?version=${version.version_number}">Download</a>
        </p>
      `).join('')}
    </div>`;

  $('versionForm').onsubmit = async event => {
    event.preventDefault();
    const file = event.target.elements.file?.files?.[0];
    const validationError = validateFile(file);
    if (validationError) {
      $('versionError').textContent = validationError;
      return;
    }
    try {
      await request(`/api/documents/${id}/versions`, {method: 'POST', body: new FormData(event.target)});
      $('versions').close();
      await load();
    } catch (error) {
      $('versionError').textContent = error.message;
    }
  };
  $('versions').showModal();
}

async function editTags(id, current) {
  const tags = prompt('Tags, separated by commas', current);
  if (tags === null) return;
  const body = new FormData();
  body.append('tags', tags);
  await request(`/api/documents/${id}/tags`, {method: 'PUT', body});
  load();
}

async function removeDocument(id) {
  if (!confirm('Move this document to deleted files?')) return;
  await request(`/api/documents/${id}`, {method: 'DELETE'});
  load();
}

// --- Tools Modal Configuration & Execution ---

function setupToolsModal() {
  const selectedDocs = currentDocuments.filter(d => selectedDocIds.has(d.id));
  const pdfDocs = selectedDocs.filter(d => d.filename.toLowerCase().endsWith('.pdf'));
  const allPdfs = selectedDocs.length > 0 && selectedDocs.length === pdfDocs.length;
  $('toolsError').textContent = '';

  const names = selectedDocs.map(d => d.filename).join(', ');
  $('toolsSelectedSummary').textContent = `${selectedDocs.length} file(s) selected: ${names}`;

  // 1. Merge: Enabled when 2+ files selected and all are PDFs
  const canMerge = selectedDocs.length >= 2 && allPdfs;
  const mergeBox = $('toolMergeBox');
  const mergeNotice = $('toolMergeNotice');
  const mergeForm = $('toolMergeForm');
  if (canMerge) {
    mergeBox.classList.remove('disabled');
    mergeForm.hidden = false;
    mergeNotice.hidden = true;
    $('toolMergeBadge').className = 'tool-badge active';
    $('toolMergeBadge').textContent = 'Ready';
    $('mergeOutputName').value = `merged_${selectedDocs[0].filename.replace(/\.pdf$/i, '')}.pdf`;
  } else {
    mergeBox.classList.add('disabled');
    mergeForm.hidden = true;
    mergeNotice.hidden = false;
    $('toolMergeBadge').className = 'tool-badge';
    $('toolMergeBadge').textContent = 'Requires 2+ PDFs';
    mergeNotice.textContent = selectedDocs.length < 2
      ? 'Select 2 or more files to merge.'
      : 'All selected files must be PDF documents to merge.';
  }

  // 2. Split: Enabled with exactly 1 PDF
  const canSplit = selectedDocs.length === 1 && allPdfs;
  const splitBox = $('toolSplitBox');
  const splitNotice = $('toolSplitNotice');
  const splitForm = $('toolSplitForm');
  if (canSplit) {
    splitBox.classList.remove('disabled');
    splitForm.hidden = false;
    splitNotice.hidden = true;
    $('toolSplitBadge').className = 'tool-badge active';
    $('toolSplitBadge').textContent = 'Ready';
    $('splitPageRanges').value = '';
  } else {
    splitBox.classList.add('disabled');
    splitForm.hidden = true;
    splitNotice.hidden = false;
    $('toolSplitBadge').className = 'tool-badge';
    $('toolSplitBadge').textContent = 'Requires 1 PDF';
    splitNotice.textContent = selectedDocs.length !== 1
      ? 'Select exactly 1 PDF document to split.'
      : 'Selected file is not a PDF document.';
  }

  // 3. Watermark: Enabled with 1+ PDFs
  const canWatermark = selectedDocs.length >= 1 && allPdfs;
  const watermarkBox = $('toolWatermarkBox');
  const watermarkNotice = $('toolWatermarkNotice');
  const watermarkForm = $('toolWatermarkForm');
  if (canWatermark) {
    watermarkBox.classList.remove('disabled');
    watermarkForm.hidden = false;
    watermarkNotice.hidden = true;
    $('toolWatermarkBadge').className = 'tool-badge active';
    $('toolWatermarkBadge').textContent = `${selectedDocs.length} PDF(s)`;
    $('watermarkText').value = 'CONFIDENTIAL';
  } else {
    watermarkBox.classList.add('disabled');
    watermarkForm.hidden = true;
    watermarkNotice.hidden = false;
    $('toolWatermarkBadge').className = 'tool-badge';
    $('toolWatermarkBadge').textContent = 'Requires PDF(s)';
    watermarkNotice.textContent = selectedDocs.length === 0
      ? 'Select 1 or more PDF documents to watermark.'
      : 'All selected files must be PDF documents.';
  }

  // 4. Convert: Enabled based on selected file's type (1 file selected)
  const convertBox = $('toolConvertBox');
  const convertNotice = $('toolConvertNotice');
  const convertForm = $('toolConvertForm');
  const convertSelect = $('convertTargetSelect');
  const convertNoticeMeta = $('convertNoticeMeta');

  let canConvert = false;
  if (selectedDocs.length === 1) {
    const ext = selectedDocs[0].filename.split('.').pop().toLowerCase();
    convertSelect.innerHTML = '';
    convertNoticeMeta.hidden = true;

    if (ext === 'docx') {
      canConvert = true;
      convertSelect.innerHTML = '<option value="pdf">PDF Document (.pdf)</option>';
    } else if (ext === 'pdf') {
      canConvert = true;
      convertSelect.innerHTML = '<option value="docx">Word Document (.docx)</option>';
      convertNoticeMeta.hidden = false;
    } else if (['jpg', 'jpeg', 'png'].includes(ext)) {
      canConvert = true;
      convertSelect.innerHTML = '<option value="pdf">PDF Document (.pdf)</option>';
    }
  }

  if (canConvert) {
    convertBox.classList.remove('disabled');
    convertForm.hidden = false;
    convertNotice.hidden = true;
    $('toolConvertBadge').className = 'tool-badge active';
    $('toolConvertBadge').textContent = 'Ready';
  } else {
    convertBox.classList.add('disabled');
    convertForm.hidden = true;
    convertNotice.hidden = false;
    $('toolConvertBadge').className = 'tool-badge';
    $('toolConvertBadge').textContent = '1 File (DOCX/PDF/Img)';
    convertNotice.textContent = selectedDocs.length !== 1
      ? 'Select a single file to convert.'
      : 'File type does not support conversion (supported: DOCX, PDF, JPG, PNG).';
  }

  $('toolsDialog').showModal();
}

$('toolsBtn')?.addEventListener('click', setupToolsModal);
$('closeToolsBtn')?.addEventListener('click', () => $('toolsDialog').close());

// Merge Action
$('executeMergeBtn')?.addEventListener('click', async () => {
  $('toolsError').textContent = '';
  const selectedDocs = currentDocuments.filter(d => selectedDocIds.has(d.id));
  const outputFilename = $('mergeOutputName').value.trim();

  try {
    await request('/api/documents/tools/merge', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({
        document_ids: selectedDocs.map(d => d.id),
        output_filename: outputFilename || null
      })
    });
    $('toolsDialog').close();
    selectedDocIds.clear();
    await load();
  } catch (err) {
    $('toolsError').textContent = err.message;
  }
});

// Split Action
$('executeSplitBtn')?.addEventListener('click', async () => {
  $('toolsError').textContent = '';
  const selectedDocs = currentDocuments.filter(d => selectedDocIds.has(d.id));
  if (selectedDocs.length !== 1) return;
  const pageRanges = $('splitPageRanges').value.trim();

  try {
    await request('/api/documents/tools/split', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({
        document_id: selectedDocs[0].id,
        page_ranges: pageRanges || null
      })
    });
    $('toolsDialog').close();
    selectedDocIds.clear();
    await load();
  } catch (err) {
    $('toolsError').textContent = err.message;
  }
});

// Watermark Action
$('executeWatermarkBtn')?.addEventListener('click', async () => {
  $('toolsError').textContent = '';
  const selectedDocs = currentDocuments.filter(d => selectedDocIds.has(d.id));
  const watermarkText = $('watermarkText').value.trim();
  if (!watermarkText) {
    $('toolsError').textContent = 'Please enter a watermark text.';
    return;
  }

  try {
    await request('/api/documents/tools/watermark', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({
        document_ids: selectedDocs.map(d => d.id),
        watermark_text: watermarkText
      })
    });
    $('toolsDialog').close();
    selectedDocIds.clear();
    await load();
  } catch (err) {
    $('toolsError').textContent = err.message;
  }
});

// Convert Action
$('executeConvertBtn')?.addEventListener('click', async () => {
  $('toolsError').textContent = '';
  const selectedDocs = currentDocuments.filter(d => selectedDocIds.has(d.id));
  if (selectedDocs.length !== 1) return;
  const targetFormat = $('convertTargetSelect').value;

  try {
    await request('/api/documents/tools/convert', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({
        document_id: selectedDocs[0].id,
        target_format: targetFormat
      })
    });
    $('toolsDialog').close();
    selectedDocIds.clear();
    await load();
  } catch (err) {
    $('toolsError').textContent = err.message;
  }
});

$('logout').onclick = async () => {
  await fetch('/api/logout', {method: 'POST'});
  location.href = '/';
};

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

loadUser();
load().catch(error => {
  if (error.message.includes('Authentication')) location.href = '/';
  else $('message').textContent = error.message;
});
