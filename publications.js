// Publications page: the Cite button shows a paper's BibTeX entry and copies it.
document.addEventListener('click', function (event) {
  var button = event.target.closest('[data-cite]');
  if (!button) {
    return;
  }
  var entry = button.closest('.paper-card').querySelector('.paper-bibtex');
  entry.hidden = !entry.hidden;
  button.setAttribute('aria-expanded', String(!entry.hidden));
  if (!entry.hidden && navigator.clipboard) {
    navigator.clipboard.writeText(entry.textContent).then(function () {
      button.textContent = 'Copied';
      setTimeout(function () {
        button.textContent = 'Cite';
      }, 1500);
    }, function () {});
  }
});
