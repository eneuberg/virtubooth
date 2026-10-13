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
    const loaders = ['beer', 'booth'].map((id) => getExtension(id)?.card);
    for (const load of loaders) expect(load).toBeTypeOf('function');
    const modules = await Promise.all(loaders.map((load) => (load ? load() : Promise.resolve(null))));
    for (const mod of modules) expect(mod?.default).toBeTypeOf('function');
  });
});
