import { act, fireEvent, render, screen, within } from '@testing-library/react';
import { useLocale } from 'react-aria-components';
import { describe, expect, it, vi } from 'vitest';
import { Button } from './Button';
import { ConnectionIndicator } from './ConnectionIndicator';
import { DataTable } from './DataTable';
import { FilmEdge } from './FilmEdge';
import { HelpDisclosure } from './HelpDisclosure';
import { Notice } from './Notice';
import { PhotoTile } from './PhotoTile';
import { SegmentedControl } from './SegmentedControl';
import { Sheet } from './Sheet';
import { TextField } from './TextField';
import { clearToasts, showToast, ToastSlot } from './Toast';
import { UiProvider } from './UiProvider';

function LocaleProbe() {
  return <span data-testid="locale">{useLocale().locale}</span>;
}

describe('UiProvider', () => {
  it('pins React Aria to de-DE whatever the browser language is', () => {
    vi.spyOn(navigator, 'language', 'get').mockReturnValue('en-US');
    render(
      <UiProvider>
        <LocaleProbe />
      </UiProvider>,
    );
    expect(screen.getByTestId('locale').textContent).toBe('de-DE');
  });
});

describe('Button', () => {
  it('keeps its label (and width) while pending and announces the pending text', () => {
    render(
      <Button variant="primary" isPending pendingLabel="Sendet…">
        Erneut senden
      </Button>,
    );
    const button = screen.getByRole('button');
    expect(button.textContent).toContain('Erneut senden');
    expect(within(button).getByRole('progressbar', { name: 'Sendet…' })).toBeTruthy();
  });

  it('passes no default react-aria class through', () => {
    render(<Button>Speichern</Button>);
    expect(screen.getByRole('button').className).not.toMatch(/react-aria-/);
  });
});

describe('Toast', () => {
  it('shows one toast at a time: a new one replaces the old one', () => {
    render(<ToastSlot />);
    act(() => {
      showToast({ message: 'Keine Verbindung. Nochmal versuchen?', tone: 'error' });
    });
    act(() => {
      showToast({ message: 'Hochgeladen', tone: 'success' });
    });
    expect(screen.queryByText('Keine Verbindung. Nochmal versuchen?')).toBeNull();
    expect(screen.getByText('Hochgeladen')).toBeTruthy();
    act(() => clearToasts());
    expect(screen.queryByText('Hochgeladen')).toBeNull();
  });

  it('runs the action and closes', () => {
    const onAction = vi.fn<() => void>();
    render(<ToastSlot />);
    act(() => {
      showToast({ message: 'Foto 0018 ausgeblendet', action: { label: 'Rückgängig', onAction } });
    });
    fireEvent.click(screen.getByRole('button', { name: 'Rückgängig' }));
    expect(onAction).toHaveBeenCalledOnce();
    expect(screen.queryByText('Foto 0018 ausgeblendet')).toBeNull();
  });
});

describe('Sheet', () => {
  it('offers a close button when dismissable', () => {
    const onOpenChange = vi.fn<(open: boolean) => void>();
    render(
      <Sheet isOpen onOpenChange={onOpenChange} title="Hochladen">
        <p>Inhalt</p>
      </Sheet>,
    );
    const dialog = screen.getByRole('dialog', { name: 'Hochladen' });
    fireEvent.click(within(dialog).getByRole('button', { name: 'Schließen' }));
    expect(onOpenChange).toHaveBeenCalledWith(false);
  });

  it('has no way out when not dismissable (join)', () => {
    const onOpenChange = vi.fn<(open: boolean) => void>();
    render(
      <Sheet isOpen onOpenChange={onOpenChange} isDismissable={false} title="Willkommen" data-testid="join">
        <p>Text</p>
      </Sheet>,
    );
    const dialog = screen.getByRole('dialog', { name: 'Willkommen' });
    expect(within(dialog).queryByRole('button', { name: 'Schließen' })).toBeNull();
    fireEvent.keyDown(dialog, { key: 'Escape' });
    expect(onOpenChange).not.toHaveBeenCalled();
    const root = screen.getByTestId('join');
    expect(root.className).toContain('vb-scrim');
    expect(root.className).not.toMatch(/modal|backdrop|react-aria-/i);
  });
});

describe('SegmentedControl', () => {
  it('is a radiogroup and reports the chosen id', () => {
    const onChange = vi.fn<(value: string) => void>();
    render(
      <SegmentedControl
        label="Gefäß"
        value="bottle"
        onChange={onChange}
        options={[
          { id: 'bottle', label: 'Flasche' },
          { id: 'cup', label: 'Becher' },
        ]}
      />,
    );
    const group = screen.getByRole('radiogroup', { name: 'Gefäß' });
    fireEvent.click(within(group).getByRole('radio', { name: 'Becher' }));
    expect(onChange).toHaveBeenCalledWith('cup');
  });
});

describe('TextField', () => {
  it('shows the inline error and marks the input invalid', () => {
    render(
      <TextField label="Instagram-Name" prefix="@" errorMessage="Instagram-Namen haben keine Leerzeichen." />,
    );
    const input = screen.getByRole('textbox', { name: 'Instagram-Name' });
    expect(input.getAttribute('aria-invalid')).toBe('true');
    expect(input.getAttribute('spellcheck')).toBe('false');
    expect(screen.getByText('Instagram-Namen haben keine Leerzeichen.')).toBeTruthy();
  });
});

describe('FilmEdge', () => {
  it('prints a zero-padded frame number', () => {
    render(<FilmEdge label="Nächstes Bier" frame={31} />);
    expect(screen.getByText('0031')).toBeTruthy();
  });

  it('is a progress bar while uploading', () => {
    render(<FilmEdge frame={19} state="uploading" progress={0.4} />);
    const bar = screen.getByRole('progressbar', { name: 'Wird hochgeladen…' });
    expect(bar.getAttribute('aria-valuenow')).toBe('40');
  });

  it('puts data-* props on its root (no wrapper needed); a caller data-state wins', () => {
    render(
      <FilmEdge frame={2} state="error" data-testid="upload-status" data-state="failed" data-total={7} />,
    );
    const root = screen.getByTestId('upload-status');
    expect(root.classList.contains('vb-film')).toBe(true);
    expect(root.dataset['state']).toBe('failed');
    expect(root.dataset['total']).toBe('7');
  });
});

describe('ConnectionIndicator', () => {
  it('takes a test id and data-* on the output itself', () => {
    render(<ConnectionIndicator status="polling" data-testid="conn" data-state="polling" />);
    const el = screen.getByTestId('conn');
    expect(el.tagName).toBe('OUTPUT');
    expect(el.dataset['status']).toBe('polling');
    expect(el.textContent).toBe('nur Abfrage');
  });
});

describe('DataTable', () => {
  it('gives rows (and the scroll box) data-* attributes', () => {
    const rows = [
      { id: 1, name: 'Ente #1' },
      { id: 2, name: 'Giraffe #2' },
    ];
    render(
      <DataTable
        aria-label="Gäste"
        data-testid="guests"
        columns={[{ id: 'name', label: 'Name', isRowHeader: true, render: (r) => r.name }]}
        rows={rows}
        getRowId={(r) => r.id}
        rowProps={(r) => ({ 'data-testid': 'guest-row', 'data-id': r.id })}
      />,
    );
    const box = screen.getByTestId('guests');
    const found = within(box).getAllByTestId('guest-row');
    expect(found.map((r) => r.dataset['id'])).toEqual(['1', '2']);
    expect(found[0]?.getAttribute('role')).toBe('row');
  });
});

describe('HelpDisclosure', () => {
  it('wraps the trigger in a heading by default', () => {
    render(<HelpDisclosure summary="Was passiert dabei?">Text</HelpDisclosure>);
    expect(screen.getByRole('heading', { level: 3, name: 'Was passiert dabei?' })).toBeTruthy();
  });

  it('headingLevel false: a plain toggle, no heading', () => {
    render(
      <HelpDisclosure summary="Mehr dazu" headingLevel={false}>
        Details
      </HelpDisclosure>,
    );
    expect(screen.queryByRole('heading')).toBeNull();
    const toggle = screen.getByRole('button', { name: 'Mehr dazu' });
    expect(toggle.getAttribute('aria-expanded')).toBe('false');
    fireEvent.click(toggle);
    expect(toggle.getAttribute('aria-expanded')).toBe('true');
  });
});

describe('PhotoTile', () => {
  it('marks a hidden photo in data and words', () => {
    render(
      <PhotoTile
        src="/x.jpg"
        alt="Bier 0032"
        label="Bier 0032"
        sublabel="Mutiger Krake"
        isHidden
        data-testid="tile"
      />,
    );
    const tile = screen.getByTestId('tile');
    expect(tile.dataset['hidden']).toBe('true');
    expect(within(tile).getByText('Ausgeblendet')).toBeTruthy();
  });

  it('offers a labelled selection checkbox', () => {
    const onChange = vi.fn<(selected: boolean) => void>();
    render(
      <PhotoTile
        src="/x.jpg"
        alt="Foto 0018"
        label="Foto 0018"
        selection={{ isSelected: false, onChange, label: 'Foto 0018 auswählen' }}
      />,
    );
    fireEvent.click(screen.getByRole('checkbox', { name: 'Foto 0018 auswählen' }));
    expect(onChange).toHaveBeenCalledWith(true);
  });
});

describe('Notice', () => {
  it('uses the neutral vb-screen class', () => {
    render(<Notice title="Keine Verbindung" data-testid="fatal" />);
    const el = screen.getByTestId('fatal');
    expect(el.getAttribute('role')).toBe('alert');
    expect(el.className).toBe('vb-screen');
    expect(screen.getByRole('heading', { level: 1, name: 'Keine Verbindung' })).toBeTruthy();
  });
});
