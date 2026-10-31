// Shared behavior for every page: the light/dark theme toggle, the current-page
// highlight in the nav, the footer, and the CV link flag from site-config.js.
// Load it in <head> after site-config.js.
(function () {
  var STORAGE_KEY = 'theme';
  var root = document.documentElement;

  function storedTheme() {
    try {
      return localStorage.getItem(STORAGE_KEY);
    } catch (e) {
      return null;
    }
  }

  function storeTheme(theme) {
    try {
      localStorage.setItem(STORAGE_KEY, theme);
    } catch (e) {}
  }

  // Apply a saved choice before the page paints, so it never flashes the other theme.
  var saved = storedTheme();
  if (saved === 'light' || saved === 'dark') {
    root.setAttribute('data-theme', saved);
  }

  // Light unless the visitor has chosen dark with the toggle.
  function currentTheme() {
    return root.getAttribute('data-theme') || 'light';
  }

  var SVG = '<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">';
  // Each icon shows the mode the button switches to.
  var ICONS = {
    light: SVG + '<path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"/></svg>',
    dark: SVG + '<circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.93 4.93l1.41 1.41M17.66 17.66l1.41 1.41M2 12h2M20 12h2M6.34 17.66l-1.41 1.41M19.07 4.93l-1.41 1.41"/></svg>'
  };

  function addThemeToggle() {
    var nav = document.querySelector('nav');
    if (!nav) {
      return;
    }
    var button = document.createElement('button');
    button.type = 'button';
    button.className = 'theme-toggle';

    function sync() {
      var theme = currentTheme();
      var label = 'Switch to ' + (theme === 'dark' ? 'light' : 'dark') + ' mode';
      button.innerHTML = ICONS[theme];
      button.setAttribute('aria-label', label);
      button.title = label;
    }

    button.addEventListener('click', function () {
      var next = currentTheme() === 'dark' ? 'light' : 'dark';
      root.setAttribute('data-theme', next);
      storeTheme(next);
      sync();
    });

    sync();
    nav.appendChild(button);
  }

  function markCurrentPage() {
    var page = window.location.pathname.split('/').pop() || 'index.html';
    document.querySelectorAll('nav a').forEach(function (link) {
      if (link.getAttribute('href') === page) {
        link.classList.add('active');
        link.setAttribute('aria-current', 'page');
      }
    });
  }

  function addFooter() {
    var updated = new Date(document.lastModified);
    var footer = document.createElement('footer');
    footer.className = 'site-footer';
    footer.textContent = '© ' + new Date().getFullYear() + ' Pujan Ajmera';
    if (!isNaN(updated)) {
      footer.textContent += ' · Last updated ' + updated.toLocaleDateString('en-US', { year: 'numeric', month: 'long', day: 'numeric' });
    }
    document.body.appendChild(footer);
  }

  function applyCvFlag() {
    var showCV = !window.SITE_FLAGS || window.SITE_FLAGS.showCV !== false;
    if (!showCV) {
      document.querySelectorAll('.cv-link').forEach(function (link) {
        link.remove();
      });
    }
  }

  document.addEventListener('DOMContentLoaded', function () {
    applyCvFlag();
    markCurrentPage();
    addThemeToggle();
    addFooter();
  });
})();
