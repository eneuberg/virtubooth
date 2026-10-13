/**
 * Beer Cam page (placeholder). OWNER: wave 2 "AC": camera session, bottle/cup outline,
 * vessel toggle, shutter, upload with progress on the film edge, success print with
 * "Noch ein Bier", outbox, paused/stopped handling up front (never lose a shot).
 */
import { Beer, CupSoda, SwitchCamera } from 'lucide-react';
import { useState } from 'react';
import { ActivityMenu } from '@/sdk/components/ActivityMenu';
import { ActivityShell } from '@/sdk/components/ActivityShell';
import type { ExtensionPageProps } from '@/sdk/extension';
import { FilmEdge } from '@/ui/FilmEdge';
import { IconButton } from '@/ui/IconButton';
import { SegmentedControl } from '@/ui/SegmentedControl';
import { Shutter } from '@/ui/Shutter';

export default function BeerPage({ id }: ExtensionPageProps) {
  const [vessel, setVessel] = useState<'bottle' | 'cup'>('bottle');
  return (
    <ActivityShell
      title={<ActivityMenu currentId={id} title="Beer Cam" />}
      stage={<div className="grid size-full place-items-center text-sm text-papier-muted">Kamera folgt</div>}
      filmEdge={<FilmEdge label="Nächstes Bier" frame={1} end={<>Ziel 1&nbsp;Mio.</>} />}
      hint={vessel === 'bottle' ? 'Halte die Flasche in den Umriss.' : 'Halte den Becher in den Umriss.'}
      controls={
        <>
          <SegmentedControl
            label="Gefäß"
            tone="camera"
            iconOnly="narrow"
            value={vessel}
            onChange={setVessel}
            options={[
              { id: 'bottle', label: 'Flasche', icon: Beer },
              { id: 'cup', label: 'Becher', icon: CupSoda },
            ]}
          />
          <Shutter state="not-ready" data-testid="shutter" />
          <IconButton label="Kamera wechseln" icon={SwitchCamera} variant="camera" size="lg" isDisabled />
        </>
      }
    />
  );
}
