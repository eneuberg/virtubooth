import { useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';
import type { UserDetail } from '@/api/types';
import { quoted } from '@/lib/messages.de';
import { Button } from '@/ui/Button';
import { Checkbox } from '@/ui/Checkbox';
import { Sheet } from '@/ui/Sheet';
import { showToast } from '@/ui/Toast';
import { errorText } from '../common/usePhotoActions';
import { autoBanSource, releasedText } from '../lib/labels';
import { unbanUser } from '../store/actions';

/**
 * "Entsperren…": what comes back, the automatic ban explained, and the option to lift
 * the guest's device-trait ban too (which releases the devices banned only by it).
 */
export function UnbanSheet({
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
  const [device, setDevice] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const banned = detail.fingerprints.filter((f) => f.banned);
  const peers = new Set(
    banned.flatMap((f) => f.users.filter((u) => u.id !== user.id && u.auto_banned).map((u) => u.id)),
  ).size;

  const confirm = async () => {
    setBusy(true);
    setError(null);
    try {
      const res = await unbanUser(qc, user.id, device);
      const what =
        res.fingerprints_unbanned.length > 0 ? 'Gast und Gerätemerkmal entsperrt' : 'Gast entsperrt';
      showToast({ message: `${what}${releasedText(res.users_unbanned.length)}`, tone: 'success' });
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
      title={`${quoted(user.name)} entsperren?`}
      size="md"
      data-testid="unban-sheet"
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
              variant="primary"
              isPending={busy}
              onPress={() => void confirm()}
              data-testid="unban-confirm"
            >
              Entsperren
            </Button>
          </div>
        </div>
      }
    >
      <div className="grid gap-4 text-md">
        {user.auto_banned ? (
          <p data-testid="auto-ban-explain">
            Dieses Gerät wurde automatisch gesperrt: Es hat sich neu angemeldet, mit {autoBanSource(user)}.
            Gleiche Handymodelle haben oft dasselbe Merkmal, vielleicht ist das jemand anderes. Entsperren
            gilt nur für dieses Gerät.
          </p>
        ) : null}
        <p>
          Die Fotos, die durch die Sperre ausgeblendet wurden, sind wieder zu sehen. Von Hand ausgeblendete
          bleiben ausgeblendet.
        </p>
        {banned.length > 0 && !user.auto_banned ? (
          <div className="grid gap-1">
            <Checkbox isSelected={device} onChange={setDevice} data-testid="unban-fp">
              Gerätemerkmal-Sperre auch aufheben
            </Checkbox>
            {peers > 0 ? (
              <p className="pl-9 text-sm text-ink-muted" data-testid="unban-fp-peers">
                Entsperrt auch {peers === 1 ? '1 weiteres Gerät, das' : `${peers} weitere Geräte, die`} nur
                deshalb gesperrt {peers === 1 ? 'ist' : 'sind'}.
              </p>
            ) : null}
          </div>
        ) : null}
      </div>
    </Sheet>
  );
}
