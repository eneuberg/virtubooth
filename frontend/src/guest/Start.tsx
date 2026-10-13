/**
 * Start screen (placeholder). OWNER: wave 2 "GP": guest pass + help, party name,
 * one film-strip card per enabled activity with its live line (beer counter, filter
 * count), "Deine Bilder" (GET /api/me/photos), "Was passiert mit meinen Fotos?",
 * the join sheet. See docs/overhaul/design/mockups/01-start.html.
 */
import { ChevronRight } from 'lucide-react';
import { Link } from 'react-aria-components';
import { listExtensions } from '@/extensions/registry';
import { FilmEdge } from '@/ui/FilmEdge';
import { GuestPass } from '@/sdk/components/GuestPass';

const TITLES: Record<string, string> = { beer: 'Beer Cam', booth: 'Fotobox' };

export function Start() {
  return (
    <main className="mx-auto grid max-w-[35rem] gap-7 px-4 pt-3 pb-10">
      <div className="flex items-center justify-between gap-2">
        <GuestPass />
      </div>
      <h1 className="text-3xl font-bold">Party</h1>
      <nav aria-label="Aktivitäten" className="grid gap-3">
        {listExtensions().map((ext) => (
          <Link
            key={ext.id}
            href={`/x/${ext.id}/`}
            data-testid={`tile-${ext.id}`}
            className="block bg-surface-sunk text-ink no-underline outline-none focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus"
          >
            <FilmEdge holes="top" />
            <span className="flex items-center justify-between px-4 py-4 text-xl font-bold">
              <span translate="no">{TITLES[ext.id] ?? ext.id}</span>
              <ChevronRight aria-hidden="true" className="size-6" />
            </span>
            <FilmEdge holes="bottom" />
          </Link>
        ))}
      </nav>
    </main>
  );
}
