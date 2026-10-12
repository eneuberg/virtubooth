import { api, boot, h, mountUserChip, toast } from './vb.js';

async function main() {
  await boot();
  mountUserChip(document.getElementById('user-chip'));
  const data = await api('/api/extensions');
  document.getElementById('party-name').textContent = data.party_name;
  document.title = data.party_name;
  const tiles = document.getElementById('tiles');
  for (const ext of data.extensions) {
    tiles.append(
      h('a', { class: 'home-tile', href: ext.url, 'data-testid': `tile-${ext.id}` },
        h('span', { class: 'home-tile-emoji', 'aria-hidden': 'true' }, ext.emoji),
        h('span', {},
          h('div', { class: 'home-tile-title' }, ext.title),
          h('div', { class: 'home-tile-tagline' }, ext.tagline),
        ),
      ),
    );
  }
  if (!data.extensions.length) tiles.append(h('p', { class: 'vb-muted' }, 'Noch nichts freigeschaltet.'));
}

main().catch((err) => toast(err.message || String(err), { type: 'error', ms: 6000 }));
