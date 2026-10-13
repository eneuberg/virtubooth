// Sample data for the UI gallery: synthetic photos (no real guests) and made-up names.
import beer1 from './img/beer-1.jpg';
import beer2 from './img/beer-2.jpg';
import beer3 from './img/beer-3.jpg';
import beer4 from './img/beer-4.jpg';
import booth1 from './img/booth-1.jpg';
import booth2 from './img/booth-2.jpg';
import booth3 from './img/booth-3.jpg';
import booth4 from './img/booth-4.jpg';
import booth5 from './img/booth-5.jpg';
import booth6 from './img/booth-6.jpg';
import booth7 from './img/booth-7.jpg';
import booth8 from './img/booth-8.jpg';

export interface SamplePhoto {
  id: string;
  src: string;
  ext: 'beer' | 'booth';
  seq: number;
  guest: string;
}

export const PHOTOS: ReadonlyArray<SamplePhoto> = [
  { id: 'p1', src: beer1, ext: 'beer', seq: 32, guest: 'Mutiger Krake' },
  { id: 'p2', src: booth4, ext: 'booth', seq: 18, guest: 'Hüpfendes Alpaka #2' },
  { id: 'p3', src: booth6, ext: 'booth', seq: 17, guest: 'Hüpfendes Alpaka #2' },
  { id: 'p4', src: beer2, ext: 'beer', seq: 31, guest: 'Singende Giraffe #5' },
  { id: 'p5', src: booth1, ext: 'booth', seq: 16, guest: 'Verrückte Ente' },
  { id: 'p6', src: beer3, ext: 'beer', seq: 30, guest: 'Mutiger Krake' },
  { id: 'p7', src: booth2, ext: 'booth', seq: 15, guest: 'Cooler Igel #7' },
  { id: 'p8', src: beer4, ext: 'beer', seq: 29, guest: 'Ein sehr langer Pseudonym-Name #12' },
  { id: 'p9', src: booth3, ext: 'booth', seq: 14, guest: 'Lustiger Otter #3' },
  { id: 'p10', src: booth5, ext: 'booth', seq: 13, guest: 'Wilde Hummel #9' },
  { id: 'p11', src: booth7, ext: 'booth', seq: 12, guest: 'Verrückte Ente' },
  { id: 'p12', src: booth8, ext: 'booth', seq: 11, guest: 'Cooler Igel #7' },
];

export interface SampleGuest {
  id: number;
  name: string;
  instagram: string | null;
  photos: number;
  status: 'ok' | 'paused' | 'banned' | 'auto';
  seen: string;
}

export const GUESTS: ReadonlyArray<SampleGuest> = [
  { id: 13, name: 'Verrückte Ente', instagram: 'erik.n', photos: 4, status: 'ok', seen: 'gerade eben' },
  {
    id: 12,
    name: 'Hüpfendes Alpaka #2',
    instagram: 'hupf.alpaka',
    photos: 14,
    status: 'ok',
    seen: 'vor 2 Min.',
  },
  { id: 11, name: 'Singende Giraffe #5', instagram: null, photos: 6, status: 'banned', seen: 'vor 40 Min.' },
  {
    id: 10,
    name: 'Mutiger Krake',
    instagram: 'ein.sehr.langer.instagram.name',
    photos: 9,
    status: 'ok',
    seen: 'vor 5 Min.',
  },
  { id: 9, name: 'Cooler Igel #7', instagram: null, photos: 3, status: 'paused', seen: 'vor 12 Min.' },
  { id: 8, name: 'Lustiger Otter #3', instagram: 'otter', photos: 2, status: 'auto', seen: 'vor 1 Std.' },
  { id: 7, name: 'Wilde Hummel #9', instagram: null, photos: 0, status: 'ok', seen: 'vor 2 Std.' },
];
