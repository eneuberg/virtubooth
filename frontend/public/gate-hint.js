// Optional refinement of gate.html (the page works without it): in the built-in
// browser of Instagram, WhatsApp & co. the guest gets the one piece of advice that
// helps. Classic ES5, no innerHTML, no inline styles (CSP).
(function () {
  var apps = [
    [/Instagram/i, 'Instagram'],
    [/FBAN|FBAV|FB_IAB|FBIOS/i, 'Facebook'],
    [/WhatsApp/i, 'WhatsApp'],
    [/Snapchat/i, 'Snapchat'],
    [/TikTok|musical_ly|BytedanceWebview/i, 'TikTok'],
  ];
  function show() {
    var el = document.querySelector('[data-testid="gate-app-hint"]');
    if (!el) return;
    var ua = navigator.userAgent;
    for (var i = 0; i < apps.length; i++) {
      if (apps[i][0].test(ua)) {
        el.textContent =
          'Du bist gerade im Browser von ' +
          apps[i][1] +
          '. Öffne lieber die Kamera-App deines Handys und scanne den QR-Code damit: Dann öffnet sich die Seite im richtigen Browser, und die Kamera geht.';
        el.hidden = false;
        return;
      }
    }
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', show);
  else show();
})();
