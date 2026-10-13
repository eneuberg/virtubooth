/**
 * Fotobox page (placeholder). OWNER: wave 2 "AC": mirrored selfie preview, filter
 * carousel (name under the selected swatch only, nothing over the face), countdown,
 * result print that develops, Speichern / Neues Foto, outbox.
 */
import { SwitchCamera, Timer } from 'lucide-react';
import { ActivityMenu } from '@/sdk/components/ActivityMenu';
import { ActivityShell } from '@/sdk/components/ActivityShell';
import type { ExtensionPageProps } from '@/sdk/extension';
import { Button } from '@/ui/Button';
import { FilmEdge } from '@/ui/FilmEdge';
import { IconButton } from '@/ui/IconButton';
import { Shutter } from '@/ui/Shutter';

export default function BoothPage({ id }: ExtensionPageProps) {
  return (
    <ActivityShell
      title={<ActivityMenu currentId={id} title="Fotobox" />}
      stage={<div className="grid size-full place-items-center text-sm text-papier-muted">Kamera folgt</div>}
      filmEdge={<FilmEdge label="Nächstes Foto" frame={1} end="Normal" />}
      controls={
        <>
          <Button variant="camera" size="sm" icon={Timer}>
            3&nbsp;s
          </Button>
          <Shutter state="not-ready" data-testid="shutter" />
          <IconButton label="Kamera wechseln" icon={SwitchCamera} variant="camera" size="lg" isDisabled />
        </>
      }
    />
  );
}
