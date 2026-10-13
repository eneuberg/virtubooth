import { QueryClient, type QueryKey } from '@tanstack/react-query';
import { describe, expect, it, vi } from 'vitest';
import type { AdminEvent } from '@/api/events';
import type {
  AdminPhoto,
  AdminUser,
  AdminUsersResponse,
  ExportJob,
  ExportsResponse,
  InstagramHandle,
  PauseState,
  StopState,
  UserDetail,
} from '@/api/types';
import { applyAdminEvent, arrivedLive } from './applyEvent';
import { incomingPhotos, listedPhotos, mergeIncoming, type PhotoPages } from './cache';
import { qk } from './keys';
import { ALL_PHOTOS, type PhotoFilter } from './types';

let seq = 0;
function photo(over: Partial<AdminPhoto> = {}): AdminPhoto {
  seq += 1;
  const id = over.id ?? `photo${String(seq).padStart(4, '0')}`;
  return {
    id,
    extension: 'beer',
    seq,
    created_at: `2026-10-13T20:${String(seq % 60).padStart(2, '0')}:00.000+00:00`,
    width: 1080,
    height: 1440,
    bytes: 1000,
    meta: {},
    hidden: false,
    hidden_at: null,
    hidden_reason: null,
    deleted: false,
    url: `/media/${id}`,
    thumb_url: `/media/${id}?thumb=1`,
    user: { id: 1, name: 'Ente', instagram: null, banned: false, auto_banned: false, uploads_paused: false },
    ...over,
  };
}

function user(over: Partial<AdminUser> = {}): AdminUser {
  return {
    id: 1,
    name: 'Ente',
    instagram: null,
    created_at: '2026-10-13T20:00:00.000+00:00',
    last_seen_at: '2026-10-13T20:00:00.000+00:00',
    consent_at: '2026-10-13T20:00:00.000+00:00',
    consent_version: '1',
    fp_hash: null,
    fp_components: {},
    first_ip: '1.2.3.4',
    last_ip: '1.2.3.4',
    user_agent: 'ua',
    banned: false,
    banned_at: null,
    ban_reason: null,
    photo_count: 0,
    uploads_paused: false,
    uploads_paused_at: null,
    uploads_paused_source: null,
    uploads_lock_period: null,
    auto_banned: false,
    auto_ban: null,
    ...over,
  };
}

function pages(photos: AdminPhoto[], total = photos.length, next: string | null = null): PhotoPages {
  return { pages: [{ photos, next, total }], pageParams: [null] };
}

function setup() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const invalidate = vi.fn<(keys: ReadonlyArray<QueryKey>) => void>();
  const apply = (event: AdminEvent) => applyAdminEvent(event, { qc, invalidate });
  const invalidated = () => invalidate.mock.calls.flatMap(([keys]) => keys.map((k) => JSON.stringify(k)));
  return { qc, apply, invalidate, invalidated };
}

const LIVE = qk.photos('live', ALL_PHOTOS);
const HIDDEN_ONLY: PhotoFilter = { ext: null, status: 'hidden', user: null };

describe('applyAdminEvent', () => {
  it('photo.created queues the photo on every matching list, once', () => {
    const { qc, apply, invalidated } = setup();
    const old = photo();
    qc.setQueryData(LIVE, pages([old], 1));
    qc.setQueryData(qk.photos('manage', HIDDEN_ONLY), pages([], 0));
    const fresh = photo();
    apply({ type: 'photo.created', data: { photo: fresh }, id: 'e-1' });
    apply({ type: 'photo.created', data: { photo: fresh }, id: 'e-1' }); // replayed
    const live = qc.getQueryData<PhotoPages>(LIVE);
    expect(incomingPhotos(live).map((p) => p.id)).toEqual([fresh.id]);
    expect(listedPhotos(live).map((p) => p.id)).toEqual([old.id]);
    // a visible photo does not belong to the "hidden" list
    expect(incomingPhotos(qc.getQueryData(qk.photos('manage', HIDDEN_ONLY)))).toEqual([]);
    expect(arrivedLive.has(fresh)).toBe(true);
    expect(invalidated()).toContain(JSON.stringify(qk.stats));
  });

  it('mergeIncoming shows the queued photos on top and counts them', () => {
    const old = photo();
    const fresh = photo();
    const data = mergeIncoming({
      pages: [{ photos: [old], next: null, total: 1, incoming: [fresh] }],
      pageParams: [null],
    });
    expect(listedPhotos(data).map((p) => p.id)).toEqual([fresh.id, old.id]);
    expect(data.pages[0]?.total).toBe(2);
    expect(incomingPhotos(data)).toEqual([]);
  });

  it('photo.created lands on the user page of its guest', () => {
    const { qc, apply } = setup();
    const detail: UserDetail = { user: user(), fingerprints: [], sharing: [], photos: [] };
    qc.setQueryData(qk.user(1), detail);
    const fresh = photo();
    apply({ type: 'photo.created', data: { photo: fresh } });
    expect(qc.getQueryData<UserDetail>(qk.user(1))?.photos.map((p) => p.id)).toEqual([fresh.id]);
  });

  it('photo.hidden / photo.unhidden replace the photo everywhere', () => {
    const { qc, apply } = setup();
    const p = photo();
    qc.setQueryData(LIVE, pages([p]));
    qc.setQueryData(qk.photo(p.id), p);
    qc.setQueryData(qk.user(1), { user: user(), fingerprints: [], sharing: [], photos: [p] });
    const hidden = { ...p, hidden: true, hidden_reason: 'admin' as const };
    apply({ type: 'photo.hidden', data: { photo: hidden } });
    expect(listedPhotos(qc.getQueryData(LIVE))[0]?.hidden).toBe(true);
    expect(qc.getQueryData<AdminPhoto>(qk.photo(p.id))?.hidden).toBe(true);
    expect(qc.getQueryData<UserDetail>(qk.user(1))?.photos[0]?.hidden).toBe(true);
    apply({ type: 'photo.unhidden', data: { photo: { ...hidden, hidden: false, hidden_reason: null } } });
    expect(listedPhotos(qc.getQueryData(LIVE))[0]?.hidden).toBe(false);
  });

  it('photo.deleted removes it once and counts it once', () => {
    const { qc, apply } = setup();
    const a = photo();
    const b = photo();
    qc.setQueryData(LIVE, pages([b, a], 2));
    qc.setQueryData(qk.photo(a.id), a);
    apply({ type: 'photo.deleted', data: { id: a.id, photo: { ...a, deleted: true } } });
    apply({ type: 'photo.deleted', data: { id: a.id, photo: { ...a, deleted: true } } });
    const live = qc.getQueryData<PhotoPages>(LIVE);
    expect(listedPhotos(live).map((p) => p.id)).toEqual([b.id]);
    expect(live?.pages[0]?.total).toBe(1);
    expect(qc.getQueryData<AdminPhoto>(qk.photo(a.id))?.deleted).toBe(true);
  });

  it('photo.deleted beyond the loaded pages still lowers the total of a matching list', () => {
    const { qc, apply } = setup();
    const shown = photo();
    const beyond = photo();
    qc.setQueryData(LIVE, pages([shown], 5, shown.id));
    apply({ type: 'photo.deleted', data: { id: beyond.id, photo: { ...beyond, deleted: true } } });
    expect(qc.getQueryData<PhotoPages>(LIVE)?.pages[0]?.total).toBe(4);
  });

  it('user.created refreshes the guest lists and the pause counts', () => {
    const { apply, invalidated } = setup();
    apply({
      type: 'user.created',
      data: { id: 2, name: 'Igel', instagram: null, banned: false, auto_banned: false, uploads_paused: true },
    });
    expect(invalidated()).toEqual(
      expect.arrayContaining([qk.userLists, qk.uploadPause, qk.pausedUsers].map((k) => JSON.stringify(k))),
    );
  });

  it('user.banned patches the guest, their photos and the marks on tiles', () => {
    const { qc, apply, invalidated } = setup();
    const p = photo();
    qc.setQueryData(LIVE, pages([p]));
    const list: { pages: AdminUsersResponse[]; pageParams: number[] } = {
      pages: [{ users: [user()], next_offset: null }],
      pageParams: [0],
    };
    qc.setQueryData(qk.users({ search: '', status: 'all' }), list);
    qc.setQueryData(qk.user(1), { user: user(), fingerprints: [], sharing: [], photos: [p] });
    const banned = user({ banned: true, ban_reason: 'Spam' });
    const hidden = { ...p, hidden: true, hidden_reason: 'ban' as const, user: { ...p.user, banned: true } };
    apply({ type: 'user.banned', data: { user: banned, photos: [hidden] } });
    const tile = listedPhotos(qc.getQueryData(LIVE))[0];
    expect(tile?.hidden_reason).toBe('ban');
    expect(tile?.user.banned).toBe(true);
    const table = qc.getQueryData<typeof list>(qk.users({ search: '', status: 'all' }));
    expect(table?.pages[0]?.users[0]?.banned).toBe(true);
    expect(qc.getQueryData<UserDetail>(qk.user(1))?.user.ban_reason).toBe('Spam');
    expect(invalidated()).toEqual(
      expect.arrayContaining([qk.bannedUsers, qk.deviceBans, qk.stats].map((k) => JSON.stringify(k))),
    );
  });

  it('user.unbanned brings the photos back', () => {
    const { qc, apply } = setup();
    const p = photo({ hidden: true, hidden_reason: 'ban' });
    qc.setQueryData(LIVE, pages([p]));
    apply({
      type: 'user.unbanned',
      data: { user: user(), photos: [{ ...p, hidden: false, hidden_reason: null }] },
    });
    expect(listedPhotos(qc.getQueryData(LIVE))[0]?.hidden).toBe(false);
  });

  it('fingerprint events refresh the device bans and the user pages', () => {
    const { apply, invalidated } = setup();
    apply({ type: 'fingerprint.banned', data: { fp_hash: 'ab'.repeat(16), user_id: 1 } });
    apply({ type: 'fingerprint.unbanned', data: { fp_hash: 'ab'.repeat(16) } });
    expect(invalidated()).toEqual(
      expect.arrayContaining([qk.deviceBans, qk.userDetails, qk.bannedUsers].map((k) => JSON.stringify(k))),
    );
  });

  it('user.uploads_changed patches the paused flag on the guest and on their photos', () => {
    const { qc, apply, invalidated } = setup();
    const p = photo();
    qc.setQueryData(LIVE, pages([p]));
    qc.setQueryData(qk.user(1), { user: user(), fingerprints: [], sharing: [], photos: [p] });
    const paused = user({ uploads_paused: true, uploads_paused_source: 'admin' });
    apply({ type: 'user.uploads_changed', data: { users: [paused], paused: true } });
    expect(listedPhotos(qc.getQueryData(LIVE))[0]?.user.uploads_paused).toBe(true);
    expect(qc.getQueryData<UserDetail>(qk.user(1))?.user.uploads_paused).toBe(true);
    expect(invalidated()).toContain(JSON.stringify(qk.uploadPause));
  });

  it('settings events replace the upload switches', () => {
    const { qc, apply } = setup();
    const stop: StopState = { enabled: true, since: '2026-10-13T20:00:00.000+00:00', by: 'admin:1' };
    apply({ type: 'settings.upload_stop', data: { upload_stop: stop } });
    expect(qc.getQueryData(qk.uploadStop)).toEqual(stop);
    const pause: PauseState = {
      enabled: true,
      since: null,
      period: 1,
      by: null,
      affected: 2,
      paused_total: 3,
    };
    apply({ type: 'settings.upload_pause', data: { upload_pause: pause, restored: [], kept: [] } });
    expect(qc.getQueryData(qk.uploadPause)).toEqual(pause);
  });

  it('export.updated upserts the job; export.deleted removes it', () => {
    const { qc, apply, invalidated } = setup();
    const job: ExportJob = {
      id: 'job0000000000001',
      kind: 'archive',
      status: 'running',
      progress: 0.4,
      created_at: '2026-10-13T20:00:00.000+00:00',
      started_at: null,
      finished_at: null,
      error: null,
      file_name: null,
      bytes: null,
      download_url: null,
      options: { include_hidden: false, include_db: false },
    };
    const list: ExportsResponse = { jobs: [], public_base_url: null, ffmpeg: true };
    qc.setQueryData(qk.exports, list);
    apply({ type: 'export.updated', data: { job } });
    apply({ type: 'export.updated', data: { job: { ...job, progress: 0.8 } } });
    expect(qc.getQueryData<ExportsResponse>(qk.exports)?.jobs).toEqual([{ ...job, progress: 0.8 }]);
    apply({ type: 'export.updated', data: { job: { ...job, status: 'done', progress: 1 } } });
    expect(invalidated()).toContain(JSON.stringify(qk.exports));
    apply({ type: 'export.deleted', data: { id: job.id } });
    expect(qc.getQueryData<ExportsResponse>(qk.exports)?.jobs).toEqual([]);
  });

  it('instagram.done marks the handle', () => {
    const { qc, apply } = setup();
    const handle: InstagramHandle = {
      handle: 'anna.party',
      users: [],
      photos: 1,
      visible: 1,
      hidden: 0,
      last_upload_at: null,
      recent: [],
      done: false,
    };
    qc.setQueryData(qk.instagram, [handle]);
    apply({ type: 'instagram.done', data: { handle: 'anna.party', done: true } });
    expect(qc.getQueryData<InstagramHandle[]>(qk.instagram)?.[0]?.done).toBe(true);
  });

  it('stream.resync invalidates every admin query', async () => {
    const { qc, apply } = setup();
    qc.setQueryData(qk.stats, { photos: 1 });
    qc.setQueryData(LIVE, pages([photo()]));
    apply({ type: 'stream.resync', data: { reason: 'gap' } });
    await Promise.resolve();
    expect(qc.getQueryState(qk.stats)?.isInvalidated).toBe(true);
    expect(qc.getQueryState(LIVE)?.isInvalidated).toBe(true);
  });

  it('a list that is fetching right now is refetched instead of patched over', () => {
    const { qc, apply } = setup();
    const p = photo();
    qc.setQueryData(LIVE, pages([p]));
    const query = qc.getQueryCache().find({ queryKey: LIVE });
    if (!query) throw new Error('no query');
    query.setState({ fetchStatus: 'fetching' });
    const spy = vi.spyOn(qc, 'invalidateQueries');
    apply({ type: 'photo.hidden', data: { photo: { ...p, hidden: true } } });
    expect(spy).toHaveBeenCalledWith({ queryKey: LIVE, exact: true });
  });
});
