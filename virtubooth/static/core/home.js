import { api, boot, fatal, h, mountUserChip } from './vb.js';

function showPartyName(name) {
  document.getElementById('party-name').textContent = name;
  document.title = name;
}

async function main() {
  // ask right away: the party name then shows behind the join dialog
  const listing = api('/api/extensions');
  listing.then((data) => showPartyName(data.party_name), () => { /* reported below */ });
  await boot();
  mountUserChip(document.getElementById('user-chip'));
  const data = await listing;
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

main().catch(fatal);
