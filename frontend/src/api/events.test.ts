import { beforeEach, describe, expect, it, vi } from 'vitest';
import { type AdminEvent, type StreamStatus, ADMIN_EVENT_TYPES, openAdminEvents } from './events';

class FakeEventSource extends EventTarget {
  static instances: FakeEventSource[] = [];
  readyState = 0;
  closed = false;
  readonly url: string;
  constructor(url: string) {
    super();
    this.url = url;
    FakeEventSource.instances.push(this);
  }
  close() {
    this.closed = true;
    this.readyState = 2;
  }
  emit(type: string, data?: string) {
    this.dispatchEvent(data === undefined ? new Event(type) : new MessageEvent(type, { data }));
  }
}

function open() {
  const events: AdminEvent[] = [];
  const statuses: StreamStatus[] = [];
  const handle = openAdminEvents({ onEvent: (e) => events.push(e), onStatus: (s) => statuses.push(s) });
  const source = FakeEventSource.instances[0]!;
  return { events, statuses, handle, source };
}

describe('openAdminEvents', () => {
  beforeEach(() => {
    FakeEventSource.instances = [];
    vi.stubGlobal('EventSource', FakeEventSource);
  });

  it('opens the admin stream', () => {
    const { source, statuses } = open();
    expect(source.url).toBe('/api/admin/events');
    expect(statuses).toEqual(['connecting']);
  });

  it('reports named events with parsed data', () => {
    const { source, events } = open();
    source.emit('photo.hidden', JSON.stringify({ photo: { id: 'abcdefgh' } }));
    source.emit(
      'settings.upload_stop',
      JSON.stringify({ upload_stop: { enabled: true, since: null, by: null } }),
    );
    source.emit('message', JSON.stringify({ ignored: true }));
    expect(events).toEqual([
      { type: 'photo.hidden', data: { photo: { id: 'abcdefgh' } } },
      { type: 'settings.upload_stop', data: { upload_stop: { enabled: true, since: null, by: null } } },
    ]);
  });

  it('passes the SSE id and resumes from a fetch position', () => {
    const events: AdminEvent[] = [];
    openAdminEvents({ onEvent: (e) => events.push(e), since: '17-4' });
    const source = FakeEventSource.instances[0]!;
    expect(source.url).toBe('/api/admin/events?since=17-4');
    source.dispatchEvent(
      new MessageEvent('photo.deleted', { data: '{"id":"abcdefgh","photo":null}', lastEventId: '17-5' }),
    );
    source.emit('stream.resync', '{"reason":"gap"}');
    expect(events).toEqual([
      { type: 'photo.deleted', data: { id: 'abcdefgh', photo: null }, id: '17-5' },
      { type: 'stream.resync', data: { reason: 'gap' } },
    ]);
  });

  it('drops malformed frames', () => {
    const { source, events } = open();
    source.emit('photo.created', '{nope');
    expect(events).toEqual([]);
  });

  it('tracks the connection status', () => {
    const { source, statuses } = open();
    source.emit('open');
    source.readyState = 0;
    source.emit('error');
    source.readyState = 2;
    source.emit('error');
    expect(statuses).toEqual(['connecting', 'live', 'reconnecting', 'closed']);
  });

  it('closes and stops listening', () => {
    const { source, events, statuses, handle } = open();
    handle.close();
    expect(source.closed).toBe(true);
    source.emit('photo.created', '{}');
    expect(events).toEqual([]);
    expect(statuses.at(-1)).toBe('closed');
  });

  it('knows every event type once', () => {
    expect(new Set(ADMIN_EVENT_TYPES).size).toBe(ADMIN_EVENT_TYPES.length);
    expect(ADMIN_EVENT_TYPES).toContain('export.updated');
  });

  it('reports closed without EventSource support', () => {
    vi.stubGlobal('EventSource', undefined);
    const statuses: StreamStatus[] = [];
    openAdminEvents({ onEvent: () => {}, onStatus: (s) => statuses.push(s) }).close();
    expect(statuses[0]).toBe('closed');
  });
});

describe('ADMIN_EVENT_TYPES', () => {
  it('lists every event of the OpenAPI union', async () => {
    const { default: spec } = await import('../../openapi.json');
    const mapping = spec.components.schemas.AdminEvent.discriminator.mapping;
    expect(ADMIN_EVENT_TYPES.toSorted()).toEqual(Object.keys(mapping).toSorted());
  });
});
