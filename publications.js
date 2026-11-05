// Publications page: the Cite button shows a paper's BibTeX entry and copies it, and
// graphical abstracts are centered beside the title, authors and journal line.
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

function placeFigures() {
  document.querySelectorAll('.paper-card.has-figure').forEach(function (card) {
    var figure = card.querySelector('.paper-figure');
    var img = figure.querySelector('img');
    var title = card.querySelector('.paper-title').getBoundingClientRect();
    var meta = card.querySelector('.paper-meta-row').getBoundingClientRect();
    var span = meta.bottom - title.top;
    // Centered, but never more than a few pixels above the title.
    var top = Math.max(-6, (span - img.offsetHeight) / 2);
    figure.style.setProperty('--figure-top', top + 'px');
    // Make room below a figure that is taller than the paper's text.
    var padding = parseFloat(getComputedStyle(card).paddingTop) + parseFloat(getComputedStyle(card).paddingBottom);
    card.style.minHeight = (title.top - card.getBoundingClientRect().top - parseFloat(getComputedStyle(card).paddingTop)
      + top + img.offsetHeight + padding) + 'px';
  });
}

document.addEventListener('DOMContentLoaded', placeFigures);
window.addEventListener('load', placeFigures);
window.addEventListener('resize', placeFigures);
document.addEventListener('load', function (event) {
  if (event.target.closest && event.target.closest('.paper-figure')) {
    placeFigures();
  }
}, true);
