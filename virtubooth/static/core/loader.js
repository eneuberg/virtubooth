// Classic (non-module) script on every page. If the page's modules never
// start (a content blocker dropped one of them, or a very old browser), tell
// the guest what to do instead of showing a half-built page.
(function () {
  var WAIT_MS = 6000;
  setTimeout(function () {
    if (window.__vbReady || !document.body) return;
    var box = document.createElement('div');
    box.className = 'vb-notice';
    box.setAttribute('role', 'alert');
    box.setAttribute('data-testid', 'load-failed');
    var inner = document.createElement('div');
    inner.className = 'vb-page';
    var emoji = document.createElement('div');
    emoji.className = 'vb-notice-emoji';
    emoji.textContent = '🧩';
    var title = document.createElement('h2');
    title.textContent = 'Die Seite startet nicht';
    var text = document.createElement('p');
    text.className = 'vb-muted';
    text.textContent = 'Wahrscheinlich blockiert ein Werbe- oder Tracking-Blocker einen Teil der Seite. ' +
      'Schalte ihn für diese Seite aus und lade neu.';
    var button = document.createElement('button');
    button.className = 'vb-btn vb-btn--primary';
    button.type = 'button';
    button.textContent = 'Neu laden';
    button.addEventListener('click', function () { location.reload(); });
    inner.appendChild(emoji);
    inner.appendChild(title);
    inner.appendChild(text);
    inner.appendChild(button);
    box.appendChild(inner);
    document.body.appendChild(box);
  }, WAIT_MS);
})();
