// Mockups only: draws sprocket rows into <span class="holes" data-p="0.4" data-tone="..."></span>
let n = 0;
document.querySelectorAll('.holes').forEach((el) => {
  const id = 'h' + n++;
  const p = parseFloat(el.dataset.p || '0');
  const h = parseFloat(el.dataset.h || '8');
  const pitch = parseFloat(el.dataset.pitch || '14');
  const hole = el.dataset.hole || 'rgb(251 239 233 / 0.24)';
  const fill = el.dataset.fill || '#ffa630';
  const NS = 'http://www.w3.org/2000/svg';
  const svg = document.createElementNS(NS, 'svg');
  svg.setAttribute('width', '100%'); svg.setAttribute('height', h); svg.setAttribute('aria-hidden', 'true');
  svg.innerHTML = `<defs>
    <pattern id="${id}a" width="${pitch}" height="${h}" patternUnits="userSpaceOnUse"><rect x="${pitch * 0.2}" y="${h * 0.12}" width="${pitch * 0.6}" height="${h * 0.76}" rx="${h * 0.22}" fill="${hole}"/></pattern>
    <pattern id="${id}b" width="${pitch}" height="${h}" patternUnits="userSpaceOnUse"><rect x="${pitch * 0.2}" y="${h * 0.12}" width="${pitch * 0.6}" height="${h * 0.76}" rx="${h * 0.22}" fill="${fill}"/></pattern>
  </defs><rect width="100%" height="${h}" fill="url(#${id}a)"/><rect width="${p * 100}%" height="${h}" fill="url(#${id}b)"/>`;
  el.replaceWith(svg);
  svg.setAttribute('class', 'holes ' + el.className.replace('holes', '').trim());
});
