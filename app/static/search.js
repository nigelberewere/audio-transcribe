// search.js - Global full-text search across Transcripts & Documents
(function() {
  const searchInput = document.getElementById('globalSearch');
  const resultsDropdown = document.getElementById('searchResults');
  const clearBtn = document.getElementById('clearSearch');
  if (!searchInput || !resultsDropdown) return;

  let debounceTimer = null;
  let currentQuery = '';

  function escapeHtml(str) {
    return String(str ?? '').replace(/[&<>"']/g, c => ({
      '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
    }[c]));
  }

  // Safely render snippet allowing only <mark> and </mark> tags
  function renderSnippet(snippetHtml) {
    if (!snippetHtml) return '';
    const tokenOpen = '___MARK_OPEN___';
    const tokenClose = '___MARK_CLOSE___';
    const prepared = snippetHtml.replace(/<mark>/gi, tokenOpen).replace(/<\/mark>/gi, tokenClose);
    const escaped = escapeHtml(prepared);
    return escaped.replace(new RegExp(tokenOpen, 'g'), '<mark>').replace(new RegExp(tokenClose, 'g'), '</mark>');
  }

  async function performSearch(query) {
    const trimmed = query.trim();
    if (!trimmed) {
      resultsDropdown.hidden = true;
      resultsDropdown.innerHTML = '';
      if (clearBtn) clearBtn.hidden = true;
      return;
    }
    if (clearBtn) clearBtn.hidden = false;

    try {
      const res = await fetch(`/api/search?q=${encodeURIComponent(trimmed)}`);
      if (!res.ok) {
        if (res.status === 401) return; // unauthenticated
        throw new Error('Search failed');
      }
      const data = await res.json();
      renderResults(trimmed, data);
    } catch (err) {
      console.error('Search error:', err);
    }
  }

  function renderResults(query, data) {
    const transcripts = data.transcripts || [];
    const documents = data.documents || [];
    const hasResults = transcripts.length > 0 || documents.length > 0;

    if (!hasResults) {
      resultsDropdown.innerHTML = `<div class="search-no-results">No matches found for "<strong>${escapeHtml(query)}</strong>"</div>`;
      resultsDropdown.hidden = false;
      return;
    }

    let html = '';
    if (transcripts.length > 0) {
      html += `<div class="search-group"><div class="search-group-title">Transcripts (${transcripts.length})</div>`;
      html += transcripts.map(item => `
        <div class="search-result-item">
          <div class="search-result-header">
            <span class="search-result-title">${escapeHtml(item.filename)}</span>
            <a href="/transcription" class="search-result-link">Open in Transcription &rarr;</a>
          </div>
          ${item.snippet ? `<p class="search-result-snippet">${renderSnippet(item.snippet)}</p>` : ''}
        </div>
      `).join('');
      html += `</div>`;
    }

    if (documents.length > 0) {
      html += `<div class="search-group"><div class="search-group-title">Documents (${documents.length})</div>`;
      html += documents.map(item => `
        <div class="search-result-item">
          <div class="search-result-header">
            <span class="search-result-title">${escapeHtml(item.filename)}</span>
            <a href="/documents" class="search-result-link">Open in Documents &rarr;</a>
          </div>
          ${item.snippet ? `<p class="search-result-snippet">${renderSnippet(item.snippet)}</p>` : ''}
          ${item.tags && item.tags.length ? `
            <div class="search-tags">
              ${item.tags.map(t => `<span class="search-tag-badge">${escapeHtml(t)}</span>`).join('')}
            </div>
          ` : ''}
        </div>
      `).join('');
      html += `</div>`;
    }

    resultsDropdown.innerHTML = html;
    resultsDropdown.hidden = false;
  }

  searchInput.addEventListener('input', (e) => {
    currentQuery = e.target.value;
    clearTimeout(debounceTimer);
    debounceTimer = setTimeout(() => {
      performSearch(currentQuery);
    }, 200);
  });

  searchInput.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') {
      resultsDropdown.hidden = true;
      searchInput.blur();
    } else if (e.key === 'Enter') {
      e.preventDefault();
      clearTimeout(debounceTimer);
      performSearch(searchInput.value);
    }
  });

  if (clearBtn) {
    clearBtn.addEventListener('click', () => {
      searchInput.value = '';
      currentQuery = '';
      resultsDropdown.hidden = true;
      resultsDropdown.innerHTML = '';
      clearBtn.hidden = true;
      searchInput.focus();
    });
  }

  document.addEventListener('click', (e) => {
    if (!searchInput.contains(e.target) && !resultsDropdown.contains(e.target)) {
      resultsDropdown.hidden = true;
    }
  });

  searchInput.addEventListener('focus', () => {
    if (searchInput.value.trim() && resultsDropdown.innerHTML) {
      resultsDropdown.hidden = false;
    }
  });
})();
