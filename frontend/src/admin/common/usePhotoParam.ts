/**
 * The open photo lives in the URL (`?photo=<id>`): deep links work, and on a phone the
 * back button closes the viewer (opening it pushes a history entry, closing goes back).
 */
import { useSearchParams } from 'wouter';

const PHOTO_ID = /^[A-Za-z0-9_-]{8,32}$/;

interface PhotoState {
  vbPhoto?: boolean;
}

function historyState(): PhotoState {
  const state: unknown = history.state;
  return state && typeof state === 'object' ? { ...state } : {};
}

function pushedHere(): boolean {
  return historyState().vbPhoto === true;
}

export function usePhotoParam(): {
  photoId: string | null;
  /** `push`: a viewer the back button should close; `replace`: switch the shown photo */
  openPhoto: (id: string, mode?: 'push' | 'replace') => void;
  closePhoto: () => void;
} {
  const [params, setParams] = useSearchParams();
  const raw = params.get('photo');
  const photoId = raw && PHOTO_ID.test(raw) ? raw : null;

  const openPhoto = (id: string, mode: 'push' | 'replace' = 'push') => {
    const push = mode === 'push' && !photoId;
    setParams(
      (prev) => {
        const next = new URLSearchParams(prev);
        next.set('photo', id);
        return next;
      },
      push ? { state: { vbPhoto: true } } : { replace: true, state: history.state },
    );
  };

  const closePhoto = () => {
    if (pushedHere()) {
      // mark it first: a second close (the API answer and the event both report a
      // deletion) must not go back once more, off the page. And drop ?photo from this
      // entry right away: going back takes a moment (Firefox: a while on a busy
      // machine), and a reload or a link meanwhile would open the photo again. (The
      // forward button then no longer reopens it.)
      const url = new URL(location.href);
      url.searchParams.delete('photo');
      history.replaceState({ ...historyState(), vbPhoto: false }, '', url.pathname + url.search + url.hash);
      history.back();
      return;
    }
    setParams(
      (prev) => {
        const next = new URLSearchParams(prev);
        next.delete('photo');
        return next;
      },
      { replace: true },
    );
  };

  return { photoId, openPhoto, closePhoto };
}
