import { describe, expect, it } from 'vitest';
import { activityList, firstPhotoText } from './copy';

describe('the invitation in "Deine Bilder" before the first photo', () => {
  it('names the activities as quoted titles, so any title fits the sentence', () => {
    expect(activityList(['Beer Cam'])).toBe('„Beer Cam“');
    expect(activityList(['Beer Cam', 'Fotobox'])).toBe('„Beer Cam“ oder „Fotobox“');
    expect(activityList(['Beer Cam', 'Fotobox', 'Glücksrad'])).toBe('„Beer Cam“, „Fotobox“ oder „Glücksrad“');
    expect(activityList([])).toBe('');
  });

  it('builds no article in front of a title', () => {
    const text = firstPhotoText(['Beer Cam', 'Glücksrad']);
    expect(text).toBe(
      'Noch keine Bilder von dir. Probier „Beer Cam“ oder „Glücksrad“ aus: Dein erstes Bild landet dann hier, und du kannst es speichern.',
    );
    expect(text).not.toMatch(/\b(der|die|das|dem|den) „/);
  });

  it('still reads well without an activity that takes photos', () => {
    expect(firstPhotoText([])).toBe(
      'Noch keine Bilder von dir. Sobald du eins machst, landet es hier, und du kannst es speichern.',
    );
  });
});
