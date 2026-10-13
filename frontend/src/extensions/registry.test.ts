import { describe, expect, it } from 'vitest';
import { getExtension, listExtensions } from './registry';

describe('extension registry', () => {
  it('collects every extension folder by id', () => {
    expect(
      listExtensions()
        .map((e) => e.id)
        .toSorted(),
    ).toEqual(['beer', 'booth']);
    expect(getExtension('booth')?.id).toBe('booth');
    expect(getExtension('nope')).toBeUndefined();
  });

  it('uses ids the backend accepts', () => {
    for (const ext of listExtensions()) expect(ext.id).toMatch(/^[a-z][a-z0-9-]{1,30}$/);
  });

  it('beer and booth bring their own live line for Start (the lazy card slot)', async () => {
    for (const id of ['beer', 'booth']) {
      const card = getExtension(id)?.card;
      expect(card, id).toBeTypeOf('function');
      const mod = await card?.();
      expect(mod?.default, id).toBeTypeOf('function');
    }
  });
});
