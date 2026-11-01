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

  function markCurrentPage() {
    var page = window.location.pathname.split('/').pop() || 'index.html';
    document.querySelectorAll('nav a').forEach(function (link) {
      if (link.getAttribute('href') === page) {
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
