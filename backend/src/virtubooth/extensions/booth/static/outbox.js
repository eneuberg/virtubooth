// Fotobox outbox on the phone: photos whose upload failed, kept in IndexedDB
// so a reload, the back button or a closed tab doesn't lose them. The page
// uploads them again on the next visit.
//
// Best effort only: without IndexedDB (private mode in older browsers, some
// in-app WebViews, storage full) every call resolves to false / [] and the
// page keeps the photos in memory and warns before leaving.

const DB_NAME = 'vb-booth';
const STORE = 'outbox';

let dbPromise = null;

function openDb() {
  if (!dbPromise) {
    dbPromise = new Promise((resolve, reject) => {
      const req = indexedDB.open(DB_NAME, 1);
      req.onupgradeneeded = () => req.result.createObjectStore(STORE, { keyPath: 'id' });
      req.onsuccess = () => resolve(req.result);
      req.onerror = () => reject(req.error);
      req.onblocked = () => reject(new Error('IndexedDB blocked'));
    });
  }
  return dbPromise;
}

async function run(mode, fn) {
  const db = await openDb();
  return new Promise((resolve, reject) => {
    const tx = db.transaction(STORE, mode);
    let result;
    const req = fn(tx.objectStore(STORE)); // may throw (DataCloneError): rejects
    if (req) req.onsuccess = () => { result = req.result; };
    tx.oncomplete = () => resolve(result);
    tx.onerror = () => reject(tx.error);
    tx.onabort = () => reject(tx.error || new Error('aborted'));
  });
}

/** Keep a photo. Resolves true once it is on disk, false if it couldn't be stored. */
export async function keep({ id, blob, meta }) {
  const record = { id, meta, at: Date.now(), type: blob.type || 'image/jpeg' };
  try {
    await run('readwrite', (store) => store.put({ ...record, data: blob }));
    return true;
  } catch (_) {
    // some WebKit versions can't store Blobs: the bytes then
    try {
      const data = await blob.arrayBuffer();
      await run('readwrite', (store) => store.put({ ...record, data }));
      return true;
    } catch (err) {
      console.warn('outbox: not stored', err);
      return false;
    }
  }
}

/** Forget a photo (uploaded, or never going to be). */
export async function forget(id) {
  try {
    await run('readwrite', (store) => store.delete(id));
  } catch (err) {
    console.warn('outbox: not deleted', err);
  }
}

/** Every kept photo, oldest first: [{ id, blob, meta }]. */
export async function kept() {
  let records;
  try {
    records = (await run('readonly', (store) => store.getAll())) || [];
  } catch (err) {
    console.warn('outbox: not readable', err);
    return [];
  }
  return records
    .filter((r) => r && r.id && r.data && r.meta)
    .sort((a, b) => a.at - b.at)
    .map((r) => ({
      id: r.id,
      meta: r.meta,
      blob: r.data instanceof Blob ? r.data : new Blob([r.data], { type: r.type || 'image/jpeg' }),
    }));
}
