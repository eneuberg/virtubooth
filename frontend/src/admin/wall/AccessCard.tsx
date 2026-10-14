/**
 * "Zugang": the Live-Wall password and logging out every wall. Own requests, not part
 * of the draft.
 */
import { useQueryClient } from '@tanstack/react-query';
import { KeyRound, LogOut, Trash2 } from 'lucide-react';
import { useState, type FormEvent } from 'react';
import { Button } from '@/ui/Button';
import { ConfirmDialog } from '@/ui/ConfirmDialog';
import { TextField } from '@/ui/TextField';
import { showToast } from '@/ui/Toast';
import { errorText, showError } from '../common/usePhotoActions';
import { clearWallPassword, logoutWalls, setWallPassword } from './api';
import { Card } from './fields';
import { wk } from './keys';
import { passwordText } from './text';
import type { WallAdminOut } from './types';

const MIN_LENGTH = 6;

export function AccessCard({ admin }: { admin: WallAdminOut }) {
  const qc = useQueryClient();
  const [password, setPassword] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<'set' | 'logout' | null>(null);
  const [confirmClear, setConfirmClear] = useState(false);
  const [clearError, setClearError] = useState<string | null>(null);
  const isSet = admin.password.set;

  const refresh = () => qc.invalidateQueries({ queryKey: wk.config });

  const submit = async (e: FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    if (password.length < MIN_LENGTH) {
      setError(`Das Passwort ist zu kurz: mindestens ${MIN_LENGTH} Zeichen.`);
      return;
    }
    setBusy('set');
    setError(null);
    try {
      const state = await setWallPassword(password);
      qc.setQueryData<WallAdminOut>(wk.config, (old) => (old ? { ...old, password: state } : old));
      setPassword('');
      showToast({
        message: isSet ? 'Passwort geändert. Alle Wände sind abgemeldet.' : 'Passwort gesetzt.',
        tone: 'success',
      });
      void refresh();
    } catch (err) {
      setError(errorText(err));
    } finally {
      setBusy(null);
    }
  };

  const clear = async () => {
    setClearError(null);
    try {
      const state = await clearWallPassword();
      qc.setQueryData<WallAdminOut>(wk.config, (old) => (old ? { ...old, password: state } : old));
      showToast({ message: 'Passwort entfernt. Die Live-Wall ist gesperrt.', tone: 'success' });
      void refresh();
    } catch (err) {
      setClearError(errorText(err));
      throw err;
    }
  };

  const logout = async () => {
    setBusy('logout');
    try {
      await logoutWalls();
      showToast({ message: 'Alle Wände sind abgemeldet.', tone: 'success' });
      void refresh();
    } catch (err) {
      showError(err);
    } finally {
      setBusy(null);
    }
  };

  return (
    <Card
      id="zugang"
      title="Zugang"
      icon={KeyRound}
      intro="Am Fernseher /livewall öffnen und das Passwort eingeben. Angemeldete Admins brauchen keins."
    >
      <p className="text-sm font-semibold" data-testid="wall-password-status">
        {passwordText(admin.password)}
      </p>
      <form
        noValidate
        onSubmit={(e) => void submit(e)}
        className="grid gap-2 sm:grid-cols-[minmax(0,1fr)_auto] sm:items-start"
      >
        <TextField
          label="Live-Wall-Passwort"
          type="password"
          autoComplete="new-password"
          size="sm"
          value={password}
          onChange={(v) => {
            setPassword(v);
            setError(null);
          }}
          errorMessage={error}
          description={`Mindestens ${MIN_LENGTH} Zeichen.`}
        />
        <Button
          type="submit"
          size="sm"
          variant="secondary"
          isPending={busy === 'set'}
          className="sm:mt-6.5"
          data-testid="wall-password-submit"
        >
          {isSet ? 'Passwort ändern' : 'Passwort setzen'}
        </Button>
      </form>
      <div className="flex flex-wrap gap-2">
        <Button
          size="xs"
          variant="secondary"
          icon={LogOut}
          isPending={busy === 'logout'}
          onPress={() => void logout()}
          data-testid="wall-logout"
        >
          Alle Wände abmelden
        </Button>
        {isSet ? (
          <Button
            size="xs"
            variant="danger-outline"
            icon={Trash2}
            onPress={() => {
              setClearError(null);
              setConfirmClear(true);
            }}
            data-testid="wall-password-clear"
          >
            Passwort entfernen…
          </Button>
        ) : null}
      </div>
      <ConfirmDialog
        isOpen={confirmClear}
        onOpenChange={setConfirmClear}
        title="Passwort entfernen?"
        confirmLabel="Passwort entfernen"
        onConfirm={clear}
        error={clearError}
        data-testid="confirm"
      >
        <p>
          Alle offenen Wände werden abgemeldet. Die Live-Wall bleibt gesperrt, bis du ein neues Passwort
          setzt.
        </p>
      </ConfirmDialog>
    </Card>
  );
}
