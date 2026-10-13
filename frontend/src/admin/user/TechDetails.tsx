import { useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';
import { Link } from 'react-aria-components';
import type { UserDetail, UserFingerprint } from '@/api/types';
import { formatDateTime, formatRelative } from '@/lib/format';
import { Badge } from '@/ui/Badge';
import { Button } from '@/ui/Button';
import { HelpDisclosure } from '@/ui/HelpDisclosure';
import { showToast } from '@/ui/Toast';
import { showError } from '../common/usePhotoActions';
import { describeUA, releasedText, shortHash } from '../lib/labels';
import { liftDeviceBan } from '../store/actions';

const LINK =
  'font-semibold text-ink underline decoration-line-strong underline-offset-3 outline-none hover:decoration-ink focus-visible:outline-2 focus-visible:outline-focus';

function text(value: unknown): string | null {
  if (typeof value === 'string' && value.trim()) return value;
  if (typeof value === 'number') return String(value);
  return null;
}

function DeviceTrait({ trait, userId }: { trait: UserFingerprint; userId: number }) {
  const qc = useQueryClient();
  const [busy, setBusy] = useState(false);
  const others = trait.users.filter((u) => u.id !== userId);

  const lift = async () => {
    setBusy(true);
    try {
      const res = await liftDeviceBan(qc, trait.fp_hash);
      const self = res.users_unbanned.some((u) => u.id === userId);
      const rest = res.users_unbanned.filter((u) => u.id !== userId).length;
      showToast({
        message: `${self ? 'Gerätemerkmal und Gast entsperrt' : 'Gerätemerkmal entsperrt'}${releasedText(rest)}`,
        tone: 'success',
      });
    } catch (err) {
      showError(err);
    } finally {
      setBusy(false);
    }
  };

  return (
    <li className="grid gap-1 border-b border-line py-2 last:border-0" data-testid="fp">
      <span className="flex flex-wrap items-center gap-2">
        <span title={trait.fp_hash} className="font-semibold tabular">
          {shortHash(trait.fp_hash)}
        </span>
        {trait.current ? <Badge>aktuell</Badge> : null}
        {trait.banned ? <Badge tone="mark">Gesperrt</Badge> : null}
      </span>
      <span className="text-ink-muted">
        erstmals {formatDateTime(trait.first_seen)}, zuletzt {formatRelative(trait.last_seen)}
      </span>
      {others.length > 0 ? (
        <span className="flex flex-wrap gap-x-3">
          <strong data-testid="fp-shared">
            {others.length === 1 ? 'Auch auf 1 anderen Gerät:' : `Auch auf ${others.length} anderen Geräten:`}
          </strong>
          {others.map((u) => (
            <Link key={u.id} href={`/user?id=${u.id}`} translate="no" className={LINK}>
              {u.name}
              {u.banned ? (
                <span className="font-normal text-mark">
                  {u.auto_banned ? ' (automatisch gesperrt)' : ' (gesperrt)'}
                </span>
              ) : null}
            </Link>
          ))}
        </span>
      ) : (
        <span className="text-ink-muted">Kein anderes Gerät hat dieses Merkmal.</span>
      )}
      {trait.banned ? (
        <Button
          size="xs"
          variant="secondary"
          isPending={busy}
          onPress={() => void lift()}
          className="justify-self-start"
          data-testid="unban-fingerprint"
        >
          Gerätemerkmal entsperren
        </Button>
      ) : null}
    </li>
  );
}

/** Collapsed by default: device, device traits (and who shares them), IP, user agent. */
export function TechDetails({ detail }: { detail: UserDetail }) {
  const { user, fingerprints } = detail;
  const c = user.fp_components;
  const gpu = [
    text(c['gl_renderer']),
    text(c['gl_vendor']) && c['gl_vendor'] !== c['gl_renderer'] ? `(${text(c['gl_vendor'])})` : null,
  ]
    .filter(Boolean)
    .join(' ');
  const power = [
    text(c['cores']) ? `${text(c['cores'])} Kerne` : null,
    text(c['memory']) ? `${text(c['memory'])} GB RAM` : null,
  ]
    .filter(Boolean)
    .join(', ');
  const rows: Array<[string, string | null]> = [
    ['Gerät', describeUA(user.user_agent || text(c['ua']))],
    ['Bildschirm', text(c['screen'])],
    ['Grafik', gpu || null],
    ['Sprache', text(c['languages'])],
    ['Zeitzone', text(c['timezone'])],
    ['Leistung', power || null],
    [
      'IP-Adresse',
      user.first_ip && user.first_ip !== user.last_ip
        ? `${user.last_ip} (zuerst ${user.first_ip})`
        : user.last_ip,
    ],
    ['Zuletzt gesehen', formatRelative(user.last_seen_at)],
    ['Erstmals da', formatDateTime(user.created_at)],
    ['Einwilligung', `${formatDateTime(user.consent_at)} (Version ${user.consent_version})`],
    ['Gast-Nr.', `#${user.id}`],
  ];
  return (
    <div data-testid="device">
      <HelpDisclosure variant="section" summary="Technische Details" headingLevel={2}>
        <dl className="grid gap-x-8 gap-y-2 sm:grid-cols-[10rem_minmax(0,1fr)]">
          {rows
            .filter(([, v]) => v)
            .map(([k, v]) => (
              <div key={k} className="contents">
                <dt className="text-ink-muted">{k}</dt>
                <dd className="min-w-0 break-words">{v}</dd>
              </div>
            ))}
          <dt className="text-ink-muted">Gerätemerkmale</dt>
          <dd data-testid="fingerprints">
            {fingerprints.length === 0 ? (
              'Keins bekannt.'
            ) : (
              <ul className="grid">
                {fingerprints.map((f) => (
                  <DeviceTrait key={f.fp_hash} trait={f} userId={user.id} />
                ))}
              </ul>
            )}
          </dd>
          <dt className="text-ink-muted">User-Agent</dt>
          <dd className="min-w-0 text-xs break-words text-ink-muted">{user.user_agent || '–'}</dd>
        </dl>
      </HelpDisclosure>
    </div>
  );
}
