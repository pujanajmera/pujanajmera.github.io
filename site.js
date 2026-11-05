// Shared behavior for every page: optional figures, the current-page highlight in
// the nav, and the CV link flag from site-config.js.
// Load it in <head> after site-config.js.
(function () {
  // Optional images (<img data-optional>): their <figure> stays hidden (see style.css)
  // until the image loads, and is removed if the file is missing. A figure can then be
  // added later just by saving the image at its path.
  document.addEventListener('load', function (event) {
    var img = event.target;
    if (img.tagName === 'IMG' && img.hasAttribute('data-optional') && img.closest('figure')) {
      img.closest('figure').classList.add('is-loaded');
    }
  }, true);
  document.addEventListener('error', function (event) {
    var img = event.target;
    if (img.tagName === 'IMG' && img.hasAttribute('data-optional')) {
      (img.closest('figure') || img).remove();
    }
  }, true);

  // Pages are linked without ".html" (GitHub Pages serves /research from research.html),
  // so "/research", "/research.html" and "research" all name the same page.
  function pageName(path) {
    var name = path.split('/').pop().replace(/\.html$/, '');
    return name === 'index' ? '' : name;
  }

  function markCurrentPage() {
    var page = pageName(window.location.pathname);
    document.querySelectorAll('nav a').forEach(function (link) {
      if (link.host === window.location.host && pageName(link.pathname) === page) {
        link.classList.add('active');
        link.setAttribute('aria-current', 'page');
      }
    });
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
  });
})();
