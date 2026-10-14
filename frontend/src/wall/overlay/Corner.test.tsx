import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { DEFAULT_CONFIG } from '../api/types';
import { Corner } from './Corner';
import { qrTarget } from './qr';

const overlay = DEFAULT_CONFIG.overlay;
const qr = { url: '/x/beer/?t=abc', name: 'Otter 3' };

describe('the corner QR code', () => {
  it('resolves a path against the wall page, keeps an absolute URL', () => {
    expect(qrTarget('/?t=abc', 'http://10.0.0.5:8000')).toBe('http://10.0.0.5:8000/?t=abc');
    expect(qrTarget('https://party.example.com/?t=abc', 'http://10.0.0.5:8000')).toBe(
      'https://party.example.com/?t=abc',
    );
  });

  it('shows the code and its name only with overlay.qr on and a code', () => {
    const { rerender } = render(
      <Corner overlay={{ ...overlay, qr: true }} eventName="Fest" total={3} qr={qr} />,
    );
    const figure = screen.getByTestId('wall-qr');
    expect(figure.textContent).toContain('Otter 3');
    expect(figure.getAttribute('data-url')).toBe(`${location.origin}/x/beer/?t=abc`);
    rerender(<Corner overlay={{ ...overlay, qr: false }} eventName="Fest" total={3} qr={qr} />);
    expect(screen.queryByTestId('wall-qr')).toBeNull();
    rerender(<Corner overlay={{ ...overlay, qr: true }} eventName="Fest" total={3} qr={null} />);
    expect(screen.queryByTestId('wall-qr')).toBeNull();
  });

  it('a corner with only the QR code still renders', () => {
    render(
      <Corner
        overlay={{ ...overlay, qr: true, event_name: false, counter: false }}
        eventName=""
        total={0}
        qr={qr}
      />,
    );
    expect(screen.getByTestId('wall-corner')).toBeTruthy();
  });
});
