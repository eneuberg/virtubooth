import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { setNoAccessHandler } from '@/api/errors';
import type { ConsentInfo, GuestUser } from '@/api/types';
import {
  canUpload,
  getSession,
  joinParty,
  noteUploadAnswer,
  refreshSession,
  resetSession,
  sessionStore,
  setAnalysisOptOut,
  setInstagram,
  startSession,
  type SessionState,
} from './session';

vi.mock('./device', () => ({
  getDeviceTraits: () => Promise.resolve({ hash: 'ab'.repeat(32), components: { ua: 'test' } }),
}));

const user = (over: Partial<GuestUser> = {}): GuestUser => ({
  name: 'Verrückte Ente #3',
  instagram: null,
  banned: false,
  uploads_paused: false,
  analysis_opt_out: false,
  ...over,
});

const consent = (over: Partial<ConsentInfo> = {}): ConsentInfo => ({
  version: '1',
  title: 'Willkommen bei Testparty! 🎉',
  paragraphs: ['Fotos.', 'Gerät.', 'Sonst nicht.'],
  instagram_prompt: 'Dein Instagram (freiwillig). Dann markieren wir dich!',
  accept_label: "Alles klar, los geht's! 🍻",
  party_name: 'Testparty',
  instagram_account: '@testparty',
  analysis: false,
  ...over,
});

type Reply = { status: number; body: unknown; headers?: Record<string, string> };
interface Call {
  method: string;
  path: string;
  body: Record<string, unknown> | null;
}

function parseBody(text: string): Record<string, unknown> {
  const value: unknown = JSON.parse(text);
  return value && typeof value === 'object' ? Object.fromEntries(Object.entries(value)) : {};
}

/** A fake server: answers in order, records what the client sent. */
function serve(...replies: Array<Reply | Error>) {
  const calls: Call[] = [];
  const queue = [...replies];
  const fetchMock = vi.fn<(input: Request) => Promise<Response>>(async (input) => {
    const text = await input.text();
    calls.push({
      method: input.method,
      path: new URL(input.url).pathname,
      body: text ? parseBody(text) : null,
    });
    const next = queue.shift();
    if (!next) throw new Error(`unexpected ${input.method} ${input.url}`);
    if (next instanceof Error) throw next;
    return new Response(JSON.stringify(next.body), {
      status: next.status,
      headers: { 'Content-Type': 'application/json', ...next.headers },
    });
  });
  vi.stubGlobal('fetch', fetchMock);
  return calls;
}

const known = (u: GuestUser = user(), over: Record<string, unknown> = {}): Reply => ({
  status: 200,
  body: {
    state: u.banned ? 'banned' : 'ok',
    user: u,
    uploads_stopped: false,
    uid_token: 'uid.sig',
    join_text: consent(),
    ...over,
  },
});
const unknownDevice = (c: ConsentInfo = consent()): Reply => ({
  status: 200,
  body: { state: 'needs_consent', consent: c },
});
const joined = (u: GuestUser = user(), over: Record<string, unknown> = {}): Reply => ({
  status: 201,
  body: {
    state: 'ok',
    user: u,
    uploads_stopped: false,
    uid_token: 'uid.new',
    join_text: consent(),
    already_joined: false,
    instagram_kept: false,
    ...over,
  },
});
const failure = (status: number, error: string, message: string): Reply => ({
  status,
  body: { error, message },
});

let restoreNoAccess: () => void;

beforeEach(() => {
  resetSession();
  localStorage.clear();
  restoreNoAccess = setNoAccessHandler(() => undefined);
});

afterEach(() => {
  restoreNoAccess();
});

describe('session state machine', () => {
  it('identifies with device traits and the stored uid, then asks to join', async () => {
    localStorage.setItem('vb_uid', 'stored.uid');
    const calls = serve(unknownDevice());
    expect(getSession()).toEqual({ status: 'loading' });
    await startSession();
    expect(calls[0]).toMatchObject({
      method: 'POST',
      path: '/api/identify',
      body: { uid: 'stored.uid', fp: { hash: 'ab'.repeat(32) } },
    });
    expect(getSession()).toEqual({ status: 'needs_join', join: consent() });
  });

  it('joins: sends version, name and traits, stores the uid token, keeps the texts', async () => {
    const calls = serve(unknownDevice(), joined(user({ instagram: 'anna' })));
    await startSession();
    await joinParty({ instagram: '  anna ' });
    expect(calls[1]).toMatchObject({
      path: '/api/join',
      body: {
        accept: true,
        version: '1',
        instagram: 'anna',
        fp: { hash: 'ab'.repeat(32) },
        analysis_opt_out: false,
      },
    });
    expect(getSession()).toEqual({
      status: 'ready',
      user: user({ instagram: 'anna' }),
      uploadsStopped: false,
    });
    expect(localStorage.getItem('vb_uid')).toBe('uid.new');
    expect(sessionStore.getState().joinText).toEqual(consent());
    expect(sessionStore.getState().outcome).toMatchObject({ alreadyJoined: false });
  });

  it('a known device is ready at once and refreshes its uid copy (the cookie fallback)', async () => {
    serve(known(user(), { uid_token: 'fresh.uid' }));
    await startSession();
    expect(getSession()).toMatchObject({ status: 'ready', user: user() });
    expect(localStorage.getItem('vb_uid')).toBe('fresh.uid');
  });

  it('a known device gets the join texts to read again; the old cache goes', async () => {
    localStorage.setItem('vb_join_text', JSON.stringify(consent({ title: 'Alt' })));
    serve(known(user(), { join_text: consent({ version: '2' }) }));
    expect(sessionStore.getState().joinText).toBeNull();
    await startSession();
    expect(sessionStore.getState().joinText).toEqual(consent({ version: '2' }));
    expect(localStorage.getItem('vb_join_text')).toBeNull();
  });

  it('a banned device ends up banned', async () => {
    serve(known(user({ banned: true })));
    await startSession();
    expect(getSession()).toEqual({ status: 'banned', user: user({ banned: true }) });
    expect(canUpload(getSession())).toMatchObject({ ok: false, reason: 'banned' });
  });

  it('consent_outdated: identifies again and shows the new texts, then rejects', async () => {
    const newer = consent({ version: '2', title: 'Neu' });
    const calls = serve(
      unknownDevice(),
      failure(409, 'consent_outdated', 'Die Hinweise wurden gerade aktualisiert. Bitte neu laden.'),
      unknownDevice(newer),
      joined(),
    );
    await startSession();
    await expect(joinParty({ instagram: null })).rejects.toMatchObject({ code: 'consent_outdated' });
    expect(getSession()).toEqual({ status: 'needs_join', join: newer });
    await joinParty({ instagram: null });
    expect(calls[3]?.body).toMatchObject({ version: '2' });
    expect(getSession().status).toBe('ready');
  });

  it('invalid_instagram rejects and keeps the sheet', async () => {
    serve(unknownDevice(), failure(400, 'invalid_instagram', 'Instagram-Namen haben keine Umlaute.'));
    await startSession();
    await expect(joinParty({ instagram: 'jürgen' })).rejects.toMatchObject({
      code: 'invalid_instagram',
      message: 'Instagram-Namen haben keine Umlaute.',
    });
    expect(getSession().status).toBe('needs_join');
  });

  it('a second tab learns it joined already', async () => {
    serve(
      unknownDevice(),
      joined(user({ instagram: 'tab.a' }), { already_joined: true, instagram_kept: true }),
    );
    await startSession();
    await joinParty({ instagram: 'tab.b' });
    expect(sessionStore.getState().outcome).toEqual({
      alreadyJoined: true,
      instagramKept: true,
      user: user({ instagram: 'tab.a' }),
    });
  });

  it('error → retry: a failed identify shows the error, refreshSession tries again in full', async () => {
    serve(new TypeError('Failed to fetch'), known());
    await startSession();
    const s = getSession();
    expect(s.status).toBe('error');
    expect(s.status === 'error' && s.error.code).toBe('network');
    await refreshSession();
    expect(getSession()).toMatchObject({ status: 'ready' });
  });

  it('a quiet refresh keeps the state when the network is gone', async () => {
    serve(known(), new TypeError('Failed to fetch'));
    await startSession();
    await refreshSession();
    expect(getSession()).toMatchObject({ status: 'ready', user: user() });
  });

  it('quiet refreshes send only the uid and pick up a pause', async () => {
    const calls = serve(known(), known(user({ uploads_paused: true })));
    await startSession();
    await refreshSession();
    expect(calls[1]?.body).toEqual({ uid: 'uid.sig' });
    expect(canUpload(getSession())).toMatchObject({ ok: false, reason: 'paused' });
  });

  it('upload answers update the gate at once', async () => {
    serve(known(), known(user({ uploads_paused: true })), known(user(), { uploads_stopped: true }));
    await startSession();
    noteUploadAnswer('uploads_paused');
    expect(canUpload(getSession())).toMatchObject({ reason: 'paused' });
    await refreshSession(); // the re-check the 403 started
    noteUploadAnswer('uploads_stopped');
    expect(canUpload(getSession())).toMatchObject({ reason: 'stopped' });
    await refreshSession();
    noteUploadAnswer('ok');
    expect(canUpload(getSession())).toEqual({ ok: true });
  });

  it('setInstagram updates the user; null clears', async () => {
    const calls = serve(
      known(),
      { status: 200, body: { user: user({ instagram: 'neu' }) } },
      {
        status: 200,
        body: { user: user() },
      },
    );
    await startSession();
    await expect(setInstagram('@neu')).resolves.toMatchObject({ instagram: 'neu' });
    expect(calls[1]).toMatchObject({ method: 'PATCH', path: '/api/me', body: { instagram: 'neu' } });
    expect(getSession()).toMatchObject({ user: { instagram: 'neu' } });
    await setInstagram(null);
    expect(calls[2]?.body).toEqual({ instagram: null });
    expect(getSession()).toMatchObject({ user: { instagram: null } });
  });

  it('joins with „Meine Fotos nicht automatisch auswerten“', async () => {
    const calls = serve(unknownDevice(), joined(user({ analysis_opt_out: true })));
    await startSession();
    await joinParty({ instagram: null, analysisOptOut: true });
    expect(calls[1]).toMatchObject({ path: '/api/join', body: { analysis_opt_out: true } });
  });

  it('setAnalysisOptOut puts the switch and updates the user', async () => {
    const calls = serve(known(), { status: 200, body: { user: user({ analysis_opt_out: true }) } });
    await startSession();
    await expect(setAnalysisOptOut(true)).resolves.toMatchObject({ analysis_opt_out: true });
    expect(calls[1]).toMatchObject({ method: 'PUT', path: '/api/me/analysis', body: { opt_out: true } });
    expect(getSession()).toMatchObject({ user: { analysis_opt_out: true } });
  });

  it('setInstagram rejects with the server message for an invalid name', async () => {
    serve(known(), failure(400, 'invalid_instagram', 'Zwei Punkte hintereinander gibt es nicht.'));
    await startSession();
    await expect(setInstagram('a..b')).rejects.toMatchObject({ code: 'invalid_instagram' });
    expect(getSession()).toMatchObject({ user: { instagram: null } });
  });
});

describe('canUpload', () => {
  it('allows a ready guest', () => {
    expect(canUpload({ status: 'ready', user: user(), uploadsStopped: false })).toEqual({ ok: true });
  });

  it('follows the server precedence: banned > paused > stopped', () => {
    const both: SessionState = {
      status: 'ready',
      user: user({ uploads_paused: true }),
      uploadsStopped: true,
    };
    expect(canUpload(both)).toMatchObject({ ok: false, reason: 'paused' });
    const banned: SessionState = { status: 'banned', user: user({ banned: true, uploads_paused: true }) };
    expect(canUpload(banned)).toMatchObject({ ok: false, reason: 'banned' });
    expect(canUpload({ status: 'ready', user: user(), uploadsStopped: true })).toMatchObject({
      ok: false,
      reason: 'stopped',
    });
  });

  it('is not ready while loading or joining', () => {
    expect(canUpload({ status: 'loading' })).toMatchObject({ ok: false, reason: 'not_ready' });
  });
});
