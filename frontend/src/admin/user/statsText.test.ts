import { describe, expect, it } from 'vitest';
import { NBSP } from '@/lib/format';
import { onlineText, photoCountsText } from './statsText';

describe('onlineText', () => {
  it('says the online time and the visits', () => {
    expect(onlineText(0, 0)).toBe('noch nicht gemessen');
    expect(onlineText(0, 1)).toBe(`unter 1${NBSP}min in 1${NBSP}Besuch`);
    expect(onlineText(12 * 60, 1)).toBe(`12${NBSP}min in 1${NBSP}Besuch`);
    expect(onlineText(3600 + 12 * 60, 3)).toBe(`1${NBSP}h 12${NBSP}min in 3${NBSP}Besuchen`);
  });
});

describe('photoCountsText', () => {
  const extensions = new Map([
    ['beer', { title: 'Beer Cam' }],
    ['booth', { title: 'Fotobox' }],
  ]);

  it('names the activities, most photos first as the server sends them', () => {
    const text = photoCountsText(
      13,
      [
        { id: 'beer', photos: 8 },
        { id: 'booth', photos: 4 },
        { id: 'retired', photos: 1 },
      ],
      extensions,
    );
    expect(text).toBe(`13: Beer Cam${NBSP}8, Fotobox${NBSP}4, retired${NBSP}1`);
  });

  it('is just the number without photos', () => {
    expect(photoCountsText(0, [], extensions)).toBe('0');
  });
});
