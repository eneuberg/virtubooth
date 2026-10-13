import { describe, expect, it } from 'vitest';
import { hiddenToast, msg, quoted, t, waitingPhotos } from './messages.de';

const all = [...Object.values(t), ...Object.values(msg)];

describe('German copy', () => {
  it('uses typographic apostrophes and quotes', () => {
    expect(all.filter((text) => /['"]/.test(text))).toEqual([]);
  });

  it('uses the ellipsis character with no space before it', () => {
    expect(all.filter((text) => text.includes('...') || /\s…/.test(text))).toEqual([]);
  });

  it('has no emoji in UI copy', () => {
    expect(all.filter((text) => /\p{Extended_Pictographic}/u.test(text))).toEqual([]);
  });

  it('keeps the glossary words', () => {
    expect(t.hide).toBe('Ausblenden');
    expect(t.unhide).toBe('Einblenden');
    expect(t.retrySend).toBe('Erneut senden');
    expect(t.reloadPage).toBe('Seite neu laden');
    expect(t.stopAllUploads).toBe('Hochladen für alle stoppen');
  });

  it('builds counted texts', () => {
    expect(waitingPhotos(1)).toBe('1\u00a0Foto wartet');
    expect(waitingPhotos(3)).toBe('3\u00a0Fotos warten');
    expect(hiddenToast('Foto\u00a00018')).toBe('Foto\u00a00018 ausgeblendet');
    expect(quoted('Cooler Igel #7')).toBe('„Cooler Igel #7“');
  });
});
