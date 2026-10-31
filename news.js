// Renders window.NEWS (from news-data.js) into any <ul data-news> element.
// Add data-news-limit="N" to show only the N most recent items.
(function () {
  var MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];

  function formatDate(date) {
    var parts = String(date).split('-');
    if (parts.length === 1) {
      return parts[0];
    }
    var month = MONTHS[parseInt(parts[1], 10) - 1];
    return parts.length === 3 ? month + ' ' + parseInt(parts[2], 10) + ', ' + parts[0] : month + ' ' + parts[0];
  }

  // Newest first; items with the same date keep their order in news-data.js.
  function sortedNews() {
    return (window.NEWS || [])
      .map(function (item, index) { return { item: item, index: index }; })
      .sort(function (a, b) {
        if (a.item.date !== b.item.date) {
          return a.item.date < b.item.date ? 1 : -1;
        }
        return a.index - b.index;
      })
      .map(function (entry) { return entry.item; });
  }

  function renderNews(list) {
    var limit = parseInt(list.getAttribute('data-news-limit'), 10);
    var items = sortedNews();
    if (limit > 0) {
      items = items.slice(0, limit);
    }

    list.innerHTML = '';
    if (!items.length) {
      list.innerHTML = '<li class="news-empty">No news yet.</li>';
      return;
    }

    items.forEach(function (item) {
      var li = document.createElement('li');
      li.className = 'news-item';
      var time = document.createElement('time');
      time.className = 'news-date';
      time.setAttribute('datetime', item.date);
      time.textContent = formatDate(item.date);
      var text = document.createElement('div');
      text.className = 'news-text';
      text.innerHTML = item.text;
      li.appendChild(time);
      li.appendChild(text);
      list.appendChild(li);
    });
  }

  document.addEventListener('DOMContentLoaded', function () {
    document.querySelectorAll('[data-news]').forEach(renderNews);
  });
})();
