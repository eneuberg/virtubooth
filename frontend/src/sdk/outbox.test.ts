import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { FakeXhr, PHOTO } from './fakeXhr.test-util';
import {
  addToOutbox,
  DB_NAME,
  DB_VERSION,
  flushOutbox,
  fromRecord,
  getOutbox,
  removeFromOutbox,
  sendFromOutbox,
  setOutboxStore,
  STORE,
  subscribeOutboxEvents,
  toRecord,
  type OutboxEvent,
  type OutboxRecord,
  type OutboxStore,
} from './outbox';

vi.mock('./session', () => ({ refreshSession: () => Promise.resolve() }));

/** An in-memory stand-in for the IndexedDB store (same records). */
class MemoryStore implements OutboxStore {
  records = new Map<string, OutboxRecord>();
  failPut = false;
  async put(record: OutboxRecord) {
    if (this.failPut) throw new DOMException('no space', 'QuotaExceededError');
    this.records.set(record.id, record);
  }
  async delete(id: string) {
    this.records.delete(id);
  }
  async getAll() {
    return [...this.records.values()];
  }
}

const jpeg = (n = 1) => new Blob([new Uint8Array([0xff, 0xd8, 0xff, n])], { type: 'image/jpeg' });
const tick = () => new Promise((resolve) => setTimeout(resolve, 0));

let store: MemoryStore;
let events: OutboxEvent[];
let off: () => void;

beforeEach(() => {
  FakeXhr.reset();
  vi.stubGlobal('XMLHttpRequest', FakeXhr);
  store = new MemoryStore();
  setOutboxStore(store);
  events = [];
  off = subscribeOutboxEvents((e) => events.push(e));
});

afterEach(() => {
  off();
  setOutboxStore(undefined);
  vi.unstubAllGlobals();
});

async function answer(status: number, body: unknown, headers: Record<string, string> = {}) {
  (await FakeXhr.next()).respond(status, body, headers);
  await tick();
}

async function failNext() {
  (await FakeXhr.next()).fail();
  await tick();
}

/** Settles the promise right away (no unhandled rejection), for awaiting later. */
const settle = <T>(p: Promise<T>) =>
  p.then(
    (value) => ({ value }),
    (error: unknown) => ({ error }),
  );

describe('records (compatible with the pre-overhaul vb-booth DB)', () => {
  it('uses the same DB, store and record shape, plus the activity', () => {
    expect([DB_NAME, DB_VERSION, STORE]).toEqual(['vb-booth', 1, 'outbox']);
    const blob = jpeg();
    expect(toRecord({ id: 'a', ext: 'beer', meta: { vessel: 'cup' }, at: 5, blob })).toEqual({
      id: 'a',
      ext: 'beer',
      meta: { vessel: 'cup' },
      at: 5,
      type: 'image/jpeg',
      data: blob,
    });
  });

  it('reads old Fotobox records (no ext) and WebKit ArrayBuffers', () => {
    const item = fromRecord({
      id: 'old',
      meta: { filter: 'bw', facing: 'user' },
      at: 1,
      type: 'image/jpeg',
      data: new ArrayBuffer(4),
    });
    expect(item).toMatchObject({ id: 'old', ext: 'booth', state: 'waiting', stored: true, resumed: true });
    expect(item?.blob).toBeInstanceOf(Blob);
    expect(item?.blob.type).toBe('image/jpeg');
  });

  it('skips broken records', () => {
    expect(fromRecord(null)).toBeNull();
    expect(fromRecord({ id: '', meta: {}, data: jpeg() })).toBeNull();
    expect(fromRecord({ id: 'x', meta: 'nope', data: jpeg() })).toBeNull();
    expect(fromRecord({ id: 'x', meta: {} })).toBeNull();
  });
});

describe('a shot', () => {
  it('is on disk before it is sent and leaves the outbox once the server has it', async () => {
    const stored = await addToOutbox({ id: 's1', ext: 'beer', meta: { vessel: 'bottle' }, blob: jpeg() });
    expect(stored).toBe(true);
    expect(store.records.get('s1')).toMatchObject({ id: 's1', ext: 'beer', meta: { vessel: 'bottle' } });
    expect(getOutbox()).toMatchObject({ pending: 0, atRisk: 0 }); // a fresh shot doesn't "wait"
    const sent = sendFromOutbox('s1');
    await answer(201, { photo: PHOTO, beer_number: 4, total: 3 });
    await expect(sent).resolves.toMatchObject({ total: 3 });
    expect(getOutbox().items).toHaveLength(0);
    await tick();
    expect(store.records.size).toBe(0);
    expect(events.map((e) => e.type)).toEqual(['sent']);
  });

  it('waits after a network failure and is sent by the next flush', async () => {
    await addToOutbox({ id: 's2', ext: 'booth', meta: { filter: 'bw', facing: 'user' }, blob: jpeg() });
    const first = settle(sendFromOutbox('s2'));
    await failNext();
    expect(await first).toMatchObject({ error: { code: 'network' } });
    expect(getOutbox()).toMatchObject({ pending: 1 });
    expect(getOutbox().items[0]?.state).toBe('waiting');
    expect(store.records.has('s2')).toBe(true);

    const flushed = flushOutbox();
    await answer(201, { photo: PHOTO, booth_number: 9 });
    await expect(flushed).resolves.toBe(1);
    expect(getOutbox().pending).toBe(0);
    expect(store.records.size).toBe(0);
  });

  it('is dropped when the server refuses it for good', async () => {
    await addToOutbox({ id: 's3', ext: 'beer', meta: { vessel: 'bottle' }, blob: jpeg() });
    const sent = settle(sendFromOutbox('s3'));
    await answer(400, { error: 'invalid_image', message: 'Bild muss genau 1080×1440 px groß sein.' });
    expect(await sent).toMatchObject({ error: { code: 'invalid_image' } });
    expect(getOutbox().items).toHaveLength(0);
    await tick();
    expect(store.records.size).toBe(0);
    expect(events.map((e) => e.type)).toEqual(['dropped']);
  });

  it('is held (kept) while the guest may not upload, and automatic flushes wait', async () => {
    await addToOutbox({ id: 's4', ext: 'beer', meta: { vessel: 'bottle' }, blob: jpeg() });
    const sent = settle(sendFromOutbox('s4'));
    await answer(403, { error: 'uploads_paused', message: 'Pausiert.' });
    expect(await sent).toMatchObject({ error: { code: 'uploads_paused' } });
    expect(getOutbox().items[0]?.state).toBe('held');
    expect(store.records.has('s4')).toBe(true);

    await expect(flushOutbox()).resolves.toBe(0); // no request: the gate is closed
    expect(FakeXhr.all).toHaveLength(1);

    const forced = flushOutbox({ force: true }); // "Erneut senden" / allowed again
    await answer(201, { photo: PHOTO, beer_number: 5, total: 4 });
    await expect(forced).resolves.toBe(1);
  });

  it('remembers a rate limit and skips the photo until then', async () => {
    await addToOutbox({ id: 's5', ext: 'beer', meta: { vessel: 'bottle' }, blob: jpeg() });
    const sent = settle(sendFromOutbox('s5'));
    await answer(429, { error: 'rate_limited', message: 'Langsam!' }, { 'Retry-After': '30' });
    expect(await sent).toMatchObject({ error: { code: 'rate_limited' } });
    const item = getOutbox().items[0];
    expect(item?.state).toBe('waiting');
    expect(item?.waitUntil).toBeGreaterThan(Date.now() + 25_000);
    await expect(flushOutbox()).resolves.toBe(0);
    expect(FakeXhr.all).toHaveLength(1);
  });

  it('sends oldest first and stops at the first failure', async () => {
    await addToOutbox({ id: 'b', ext: 'beer', meta: { vessel: 'bottle' }, blob: jpeg(2), at: 2000 });
    await addToOutbox({
      id: 'a',
      ext: 'booth',
      meta: { filter: 'bw', facing: 'user' },
      blob: jpeg(1),
      at: 1000,
    });
    const a = settle(sendFromOutbox('a'));
    await failNext();
    await a;
    const b = settle(sendFromOutbox('b'));
    await failNext();
    await b;
    FakeXhr.reset();
    const flushed = flushOutbox();
    const req = await FakeXhr.next();
    expect(req.url).toBe('/api/x/booth/upload'); // "a" first
    req.fail();
    await expect(flushed).resolves.toBe(0);
    expect(FakeXhr.all).toHaveLength(1); // stopped
    expect(getOutbox().pending).toBe(2);
  });

  it('is at risk without storage (memory only)', async () => {
    store.failPut = true;
    const stored = await addToOutbox({
      id: 's6',
      ext: 'booth',
      meta: { filter: 'bw', facing: 'user' },
      blob: jpeg(),
    });
    expect(stored).toBe(false);
    expect(getOutbox().atRisk).toBe(1);
    await removeFromOutbox('s6');
    expect(getOutbox()).toMatchObject({ atRisk: 0, pending: 0 });
  });

  it('works with no IndexedDB at all', async () => {
    setOutboxStore(null);
    expect(await addToOutbox({ id: 's7', ext: 'beer', meta: { vessel: 'cup' }, blob: jpeg() })).toBe(false);
    expect(getOutbox().atRisk).toBe(1);
  });
});

describe('the next visit', () => {
  it('sends what an earlier visit kept', async () => {
    store.records.set('kept', {
      id: 'kept',
      meta: { filter: 'normal', facing: 'user' },
      at: 1,
      type: 'image/jpeg',
      data: jpeg(),
    });
    const flushed = flushOutbox();
    await answer(201, { photo: PHOTO, booth_number: 1 });
    await expect(flushed).resolves.toBe(1);
    expect(FakeXhr.all[0]?.url).toBe('/api/x/booth/upload');
    expect(events[0]).toMatchObject({ type: 'sent', item: { id: 'kept', resumed: true } });
  });
});
