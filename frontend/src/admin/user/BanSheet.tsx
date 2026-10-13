import { useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';
import type { UserDetail } from '@/api/types';
import { quoted } from '@/lib/messages.de';
import { Button } from '@/ui/Button';
import { Checkbox } from '@/ui/Checkbox';
import { HelpDisclosure } from '@/ui/HelpDisclosure';
import { Sheet } from '@/ui/Sheet';
import { TextField } from '@/ui/TextField';
import { showToast } from '@/ui/Toast';
import { errorText } from '../common/usePhotoActions';
import { deviceCount } from '../lib/labels';
import { banUser } from '../store/actions';

function effect(visible: number): string {
  if (visible === 0) return 'Weitere Uploads sind blockiert. Sichtbare Fotos hat der Gast gerade keine.';
  if (visible === 1) return 'Das sichtbare Foto wird ausgeblendet, weitere Uploads sind blockiert.';
  return `Alle ${visible} sichtbaren Fotos werden ausgeblendet, weitere Uploads sind blockiert.`;
}

/**
 * "Sperren…": reason, the device-trait option with its warning, and the decision, in
 * one sheet (the page itself keeps only the button). Focus starts on "Abbrechen".
 */
export function BanSheet({
  detail,
  isOpen,
  onOpenChange,
  onDone,
}: {
  detail: UserDetail;
  isOpen: boolean;
  onOpenChange: (open: boolean) => void;
  onDone: () => void;
}) {
  const qc = useQueryClient();
  const { user } = detail;
  const [reason, setReason] = useState('');
  const [device, setDevice] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const visible = detail.photos.filter((p) => !p.hidden).length;
  const current = detail.fingerprints.find((f) => f.current);
  const sharing = current ? current.users.filter((u) => u.id !== user.id).length : 0;

  const confirm = async () => {
    setBusy(true);
    setError(null);
    try {
      const res = await banUser(qc, user.id, { reason, fingerprint: device });
      showToast({
        message: res.fingerprint_banned ? 'Gast und Gerätemerkmal gesperrt' : 'Gast gesperrt',
        tone: 'success',
      });
      setReason('');
      setDevice(false);
      onOpenChange(false);
      onDone();
    } catch (err) {
      setError(errorText(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Sheet
      isOpen={isOpen}
      onOpenChange={(open) => !busy && onOpenChange(open)}
      title={`${quoted(user.name)} sperren?`}
      description={effect(visible)}
      size="md"
      data-testid="ban-sheet"
      footer={
        <div className="grid gap-3">
          {error ? (
            <p role="alert" className="text-sm font-semibold text-danger">
              {error}
            </p>
          ) : null}
          <div className="grid grid-cols-2 gap-3">
            <Button variant="secondary" autoFocus isDisabled={busy} onPress={() => onOpenChange(false)}>
              Abbrechen
            </Button>
            <Button
              variant="danger"
              isPending={busy}
              onPress={() => void confirm()}
              data-testid="ban-confirm"
            >
              {device ? 'Gast und Merkmal sperren' : 'Sperren'}
            </Button>
          </div>
        </div>
      }
    >
      <div className="grid gap-4">
        <TextField
          label="Grund (freiwillig, nur für euch)"
          placeholder="z. B. unpassende Fotos…"
          maxLength={200}
          value={reason}
          onChange={setReason}
          autoComplete="off"
          data-testid="ban-reason"
        />
        <div className="grid gap-1">
          <Checkbox isSelected={device} onChange={setDevice} isDisabled={!user.fp_hash} data-testid="ban-fp">
            Gerätemerkmal auch sperren{user.fp_hash ? '' : ' (keins bekannt)'}
          </Checkbox>
          <p className="pl-9 text-sm text-ink-muted" data-testid="fp-warning">
            Nur für Störer, die sich immer wieder neu anmelden: Neue Geräte mit diesem Merkmal starten dann
            gesperrt, auch Unbeteiligte mit dem gleichen Handymodell.
            {sharing > 0
              ? ` ${sharing === 1 ? '1 anderes Gerät hat' : `${deviceCount(sharing)} haben`} dieses Merkmal schon; bekannte Gäste bleiben unberührt.`
              : ''}
          </p>
        </div>
        <HelpDisclosure summary="Was ist ein Gerätemerkmal?">
          <p>
            Eine Kennung, die der Browser aus Bildschirm, Grafik, Sprache und Ähnlichem bildet. Ein Hinweis,
            keine Identität: Zwei gleiche iPhones haben oft dasselbe Merkmal.
          </p>
        </HelpDisclosure>
      </div>
    </Sheet>
  );
}
