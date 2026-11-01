// Software page: fills each <li data-repo="owner/name" data-pypi="package"> with live
// GitHub stars, the latest tagged release, and the latest PyPI release.
// Results are cached for the browser session to stay well under GitHub's rate limit.
(function () {
  var CACHE_PREFIX = 'software:';

  function cached(url) {
    try {
      var hit = sessionStorage.getItem(CACHE_PREFIX + url);
      if (hit) {
        return Promise.resolve(JSON.parse(hit));
      }
    } catch (e) {}
    return fetch(url).then(function (response) {
      if (!response.ok) {
        throw new Error(response.status);
      }
      return response.json();
    }).then(function (data) {
      try {
        sessionStorage.setItem(CACHE_PREFIX + url, JSON.stringify(data));
      } catch (e) {}
      return data;
    });
  }

  function orNull(promise) {
    return promise.catch(function () { return null; });
  }

  function formatDate(iso) {
    return new Date(iso).toLocaleDateString('en-US', { month: 'short', year: 'numeric' });
  }

  function link(href, text) {
    var a = document.createElement('a');
    a.href = href;
    a.target = '_blank';
    a.rel = 'noopener noreferrer';
    a.textContent = text;
    return a;
  }

  function fill(item) {
    var repo = item.getAttribute('data-repo');
    var pypi = item.getAttribute('data-pypi');
    var meta = item.querySelector('.software-meta');
    var api = 'https://api.github.com/repos/' + repo;

    Promise.all([
      orNull(cached(api)),
      orNull(cached(api + '/releases?per_page=1')),
      pypi ? orNull(cached('https://pypi.org/pypi/' + pypi + '/json')) : null
    ]).then(function (results) {
      var info = results[0];
      var release = results[1] && results[1][0];
      var pkg = results[2];
      var parts = [];

      if (info && info.stargazers_count > 0) {
        var stars = info.stargazers_count;
        parts.push(link(info.html_url + '/stargazers', stars + (stars === 1 ? ' star' : ' stars')));
      }
      if (release) {
        parts.push(link(release.html_url, 'Release ' + release.tag_name + ' (' + formatDate(release.published_at) + ')'));
      }
      if (pkg) {
        parts.push(link('https://pypi.org/project/' + pypi + '/', 'PyPI ' + pkg.info.version));
      }
      if (!parts.length) {
        return;
      }
      parts.forEach(function (part, i) {
        if (i) {
          meta.appendChild(document.createTextNode(' · '));
        }
        meta.appendChild(part);
      });
      meta.hidden = false;

      var install = item.querySelector('.software-install');
      if (pkg && install) {
        install.hidden = false;
      }
    });
  }

  document.addEventListener('DOMContentLoaded', function () {
    document.querySelectorAll('.software-item[data-repo]').forEach(fill);
  });
})();
