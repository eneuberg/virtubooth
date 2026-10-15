/**
 * „Filter zeigen“: Fotobox photos are shown with their filter baked in (what the guest
 * saw), or as the unfiltered original the booth uploads alongside (`raw_url`). On by
 * default; the choice is remembered in this browser, one preference per surface (the
 * admin's views share one, the guest's „Deine Bilder“ another).
 *
 * A photo without a separate original (Beer Cam, the „Normal“ filter, taken before
 * originals were kept) always shows its one file.
 */
import { create, type StoreApi, type UseBoundStore } from 'zustand';

/** What a photo needs for the switch (AdminPhoto and GuestPhoto both have it). */
export interface PhotoVariants {
  url: string;
  thumb_url: string;
  raw_url: string | null;
  raw_thumb_url: string | null;
  meta?: Record<string, unknown>;
}

export interface FilterPreference {
  show: boolean;
  setShow: (show: boolean) => void;
}

export const ADMIN_FILTER_KEY = 'vb.admin.photos.filter';
export const GUEST_FILTER_KEY = 'vb.guest.photos.filter';

function remembered(key: string): boolean {
  try {
    return localStorage.getItem(key) !== 'off';
  } catch {
    return true;
  }
}

/** A remembered „Filter zeigen“ preference (on unless this browser switched it off). */
export function createFilterPreference(key: string): UseBoundStore<StoreApi<FilterPreference>> {
  return create<FilterPreference>((set) => ({
    show: remembered(key),
    setShow: (show) => {
      try {
        localStorage.setItem(key, show ? 'on' : 'off');
      } catch {
        // private window: the choice lasts for this page only
      }
      set({ show });
    },
  }));
}

export const useAdminShowFilter = createFilterPreference(ADMIN_FILTER_KEY);
export const useGuestShowFilter = createFilterPreference(GUEST_FILTER_KEY);

/** The image to show: the photo, or its original when the filter is switched off. */
export function photoSrc(photo: PhotoVariants, showFilter: boolean, thumb = false): string {
  if (!showFilter) {
    const raw = thumb ? photo.raw_thumb_url : photo.raw_url;
    if (raw) return raw;
  }
  return thumb ? photo.thumb_url : photo.url;
}

/** The image for `photo` under the admin's „Filter zeigen“ (`thumb`: the 400 px one). */
export function useAdminPhotoSrc(photo: PhotoVariants, thumb = false): string {
  const show = useAdminShowFilter((s) => s.show);
  return photoSrc(photo, show, thumb);
}

/** Whether a photo's own switch belongs next to it: it was taken with a filter choice. */
export function hasFilterChoice(photo: PhotoVariants): boolean {
  return hasOriginal(photo) || (photo.meta !== undefined && 'filter' in photo.meta);
}

/** The photo has an unfiltered original to switch to. */
export function hasOriginal(photo: PhotoVariants): boolean {
  return photo.raw_url !== null;
}

/**
 * Why a photo can't switch, in one line: it was taken without a filter (nothing to
 * take away), or before originals were kept. Empty when it can.
 */
export function noOriginalHint(photo: PhotoVariants): string {
  if (hasOriginal(photo)) return '';
  const filter = photo.meta?.['filter'];
  if (typeof filter !== 'string' || filter === 'normal') return 'Ohne Filter aufgenommen.';
  return 'Kein Original ohne Filter gespeichert (vor dem Update aufgenommen).';
}

/** The download URL: the photo with its filter, or (`raw`) the original. */
export function downloadHref(photo: PhotoVariants, raw = false): string {
  return `${(raw && photo.raw_url) || photo.url}${raw && photo.raw_url ? '&' : '?'}download=1`;
}
