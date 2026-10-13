// Classic (non-module) script on every page with an app. If the app's modules never
// start (a content blocker dropped one of them, or a very old browser), tell the
// guest what to do instead of leaving a blank or half-built page.
//
// Contract: the app sets `window.__vbReady = true` once its module graph ran.
// Keep this file tiny, dependency-free and ES5: it must work where the app does not.
// No inline styles (CSP style-src 'self'); the classes come from the built app.css,
// and the layout still reads without them (plain heading, text and button).
(function () {
  var WAIT_MS = 6000;
  var SVG = 'http://www.w3.org/2000/svg';

  function el(tag, cls, text) {
    var node = document.createElement(tag);
    if (cls) node.className = cls;
    if (text) node.textContent = text;
    return node;
  }

  // lucide "puzzle" (ISC), drawn with DOM calls: no innerHTML
  function icon() {
    var svg = document.createElementNS(SVG, 'svg');
    svg.setAttribute('viewBox', '0 0 24 24');
    svg.setAttribute('fill', 'none');
    svg.setAttribute('stroke', 'currentColor');
    svg.setAttribute('stroke-width', '1.75');
    svg.setAttribute('stroke-linecap', 'round');
    svg.setAttribute('stroke-linejoin', 'round');
    svg.setAttribute('aria-hidden', 'true');
    svg.setAttribute('class', 'vb-screen-icon');
    var path = document.createElementNS(SVG, 'path');
    path.setAttribute(
      'd',
      'M15.39 4.39a1 1 0 0 0 1.68-.474 2.5 2.5 0 1 1 3.014 3.015 1 1 0 0 0-.474 1.68l1.683 1.682a2.414 2.414 0 0 1 0 3.414L19.61 15.39a1 1 0 0 1-1.68-.474 2.5 2.5 0 1 0-3.014 3.015 1 1 0 0 1 .474 1.68l-1.683 1.682a2.414 2.414 0 0 1-3.414 0L8.61 19.61a1 1 0 0 0-1.68.474 2.5 2.5 0 1 1-3.014-3.015 1 1 0 0 0 .474-1.68l-1.683-1.682a2.414 2.414 0 0 1 0-3.414L4.39 8.61a1 1 0 0 1 1.68.474 2.5 2.5 0 1 0 3.014-3.015 1 1 0 0 1-.474-1.68l1.683-1.682a2.414 2.414 0 0 1 3.414 0z'
    );
    svg.appendChild(path);
    return svg;
  }

  setTimeout(function () {
    if (window.__vbReady || !document.body) return;
    if (document.querySelector('[data-testid="load-failed"]')) return;
    var box = el('div', 'vb-screen vb-screen--boot');
    box.setAttribute('role', 'alert');
    box.setAttribute('data-testid', 'load-failed');
    var inner = el('div', 'vb-screen-inner');
    var title = el('h2', 'vb-screen-title', 'Die Seite startet nicht');
    var text = el(
      'p',
      'vb-screen-text',
      'Wahrscheinlich blockiert ein Werbe- oder Tracking-Blocker einen Teil der Seite. ' +
        'Schalte ihn für diese Seite aus und lade sie neu.'
    );
    var actions = el('div', 'vb-screen-actions');
    var button = el('button', 'vb-btn vb-btn--primary', 'Seite neu laden');
    button.type = 'button';
    button.setAttribute('data-testid', 'reload');
    button.addEventListener('click', function () {
      location.reload();
    });
    actions.appendChild(button);
    inner.appendChild(icon());
    inner.appendChild(title);
    inner.appendChild(text);
    inner.appendChild(actions);
    box.appendChild(inner);
    document.body.appendChild(box);
    button.focus();
  }, WAIT_MS);
})();
