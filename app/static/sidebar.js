// sidebar.js - Universal Navigation Sidebar Drawer Controller

(function () {
  const $ = (id) => document.getElementById(id);
  let _isToggling = false;

  function isSidebarOpen() {
    const sidebar = $('appSidebar');
    return !!(sidebar && sidebar.classList.contains('open'));
  }

  function openSidebar() {
    const sidebar = $('appSidebar');
    const backdrop = $('sidebarBackdrop');
    const btn = $('hamburgerBtn') || $('hamburgerMenuBtn');
    if (!sidebar) return;
    sidebar.classList.add('open');
    if (backdrop) backdrop.classList.add('open');
    if (btn) {
      btn.setAttribute('aria-expanded', 'true');
      btn.classList.add('active');
    }
    document.body.style.overflow = 'hidden';
  }

  function closeSidebar() {
    const sidebar = $('appSidebar');
    const backdrop = $('sidebarBackdrop');
    const btn = $('hamburgerBtn') || $('hamburgerMenuBtn');
    if (!sidebar) return;
    sidebar.classList.remove('open');
    if (backdrop) backdrop.classList.remove('open');
    if (btn) {
      btn.setAttribute('aria-expanded', 'false');
      btn.classList.remove('active');
    }
    document.body.style.overflow = '';
  }

  function toggleSidebar() {
    if (_isToggling) return;
    _isToggling = true;
    setTimeout(() => { _isToggling = false; }, 150);

    if (isSidebarOpen()) {
      closeSidebar();
    } else {
      openSidebar();
    }
  }

  // Expose helpers globally
  window.isSidebarOpen = isSidebarOpen;
  window.openSidebar = openSidebar;
  window.closeSidebar = closeSidebar;
  window.toggleSidebar = toggleSidebar;

  function cleanupBrandNavLinks() {
    document.querySelectorAll('header.brand-card nav a, .brand-card nav a, .sidebar-item .status-badge').forEach(el => el.remove());
  }

  function initSidebar() {
    cleanupBrandNavLinks();

    // Use delegated click on document for infallible event capture
    if (!window._sidebarClickDelegated) {
      window._sidebarClickDelegated = true;
      document.addEventListener('click', (event) => {
        const hamburger = event.target.closest('#hamburgerBtn, #hamburgerMenuBtn, .top-left-hamburger-btn');
        if (hamburger) {
          event.preventDefault();
          event.stopPropagation();
          toggleSidebar();
          return;
        }

        const closeBtn = event.target.closest('#closeSidebarBtn, .sidebar-close-btn');
        if (closeBtn) {
          event.preventDefault();
          event.stopPropagation();
          closeSidebar();
          return;
        }

        const backdrop = event.target.closest('#sidebarBackdrop');
        if (backdrop && isSidebarOpen()) {
          event.preventDefault();
          event.stopPropagation();
          closeSidebar();
          return;
        }

        // Clicking outside the sidebar drawer when open also closes it
        if (isSidebarOpen() && !event.target.closest('#appSidebar')) {
          closeSidebar();
        }
      });
    }

    if (!window._sidebarEscBound) {
      window._sidebarEscBound = true;
      document.addEventListener('keydown', (event) => {
        if (event.key === 'Escape' && isSidebarOpen()) {
          closeSidebar();
          const btn = $('hamburgerBtn') || $('hamburgerMenuBtn');
          btn?.focus();
        }
      });
    }

    // Role check to reveal admin sidebar group if present
    fetch('/api/me')
      .then(res => res.ok ? res.json() : null)
      .then(me => {
        if (me && me.role === 'admin') {
          const adminGroup = $('sidebarAdminGroup');
          if (adminGroup) adminGroup.hidden = false;
        }
      })
      .catch(() => {});
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initSidebar);
  } else {
    initSidebar();
  }
})();
