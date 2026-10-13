/** A scriptable XMLHttpRequest for upload tests. */
type Listener = (e: { loaded?: number; total?: number; lengthComputable?: boolean }) => void;

export class FakeXhr {
  static last: FakeXhr | null = null;
  static all: FakeXhr[] = [];
  method = '';
  url = '';
  headers: Record<string, string> = {};
  body: unknown = null;
  responseType = '';
  timeout = 0;
  status = 0;
  response: unknown = null;
  aborted = false;
  /** answered, failed, timed out or aborted */
  settled = false;
  private responseHeaders: Record<string, string> = {};
  private listeners: Record<string, Listener[]> = {};
  upload = {
    listeners: [] as Listener[],
    addEventListener: (_type: string, fn: Listener) => {
      this.upload.listeners.push(fn);
    },
  };

  constructor() {
    FakeXhr.last = this;
    FakeXhr.all.push(this);
  }

  open(method: string, url: string) {
    this.method = method;
    this.url = url;
  }

  setRequestHeader(name: string, value: string) {
    this.headers[name] = value;
  }

  getResponseHeader(name: string): string | null {
    return this.responseHeaders[name.toLowerCase()] ?? null;
  }

  addEventListener(type: string, fn: Listener) {
    (this.listeners[type] ??= []).push(fn);
  }

  send(body: unknown) {
    this.body = body;
  }

  abort() {
    this.aborted = true;
    this.emit('abort');
  }

  private emit(type: string) {
    this.settled = true;
    for (const fn of this.listeners[type] ?? []) fn({});
  }

  progress(loaded: number, total: number) {
    for (const fn of this.upload.listeners) fn({ loaded, total, lengthComputable: true });
  }

  respond(status: number, body: unknown, headers: Record<string, string> = {}) {
    this.status = status;
    this.response = body;
    this.responseHeaders = Object.fromEntries(Object.entries(headers).map(([k, v]) => [k.toLowerCase(), v]));
    this.emit('load');
  }

  fail() {
    this.emit('error');
  }

  expire() {
    this.emit('timeout');
  }

  /** Waits (a few ticks) for a request that has not been answered yet. */
  static async next(): Promise<FakeXhr> {
    for (let i = 0; i < 50; i++) {
      const open = FakeXhr.all.find((x) => !x.settled && x.body !== null);
      if (open) return open;
      // oxlint-disable-next-line no-await-in-loop -- polling on purpose
      await new Promise((resolve) => setTimeout(resolve, 0));
    }
    throw new Error('no open request');
  }

  static reset() {
    FakeXhr.last = null;
    FakeXhr.all = [];
  }
}

export const PHOTO = {
  id: 'AbCdEfGh12345678',
  extension: 'beer',
  seq: 4,
  created_at: '2026-10-13T01:39:22.113+00:00',
  width: 1080,
  height: 1440,
  url: '/media/AbCdEfGh12345678',
  thumb_url: '/media/AbCdEfGh12345678?thumb=1',
};
