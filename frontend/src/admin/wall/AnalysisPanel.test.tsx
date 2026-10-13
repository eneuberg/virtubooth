import { QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import type { AdminExtension, AdminPhoto } from '@/api/types';
import { UiProvider } from '@/ui/UiProvider';
import { json, stubApi, testClient, type Route } from '../testing';
import { AnalysisPanel } from './AnalysisPanel';
import { photoAnalysis } from './fixtures';

const PHOTO: AdminPhoto = {
  id: 'p1',
  extension: 'beer',
  seq: 1,
  created_at: '2026-10-13T20:41:00Z',
  width: 1080,
  height: 1440,
  bytes: 1000,
  deleted: false,
  hidden: false,
  hidden_at: null,
  hidden_reason: null,
  meta: {},
  url: '/media/p1',
  thumb_url: '/media/p1?thumb=1',
  user: { id: 1, name: 'Gast 1', instagram: null, banned: false, auto_banned: false, uploads_paused: false },
};

const WALL: AdminExtension = {
  id: 'wall',
  title: 'Live-Wall',
  emoji: '📺',
  tagline: '',
  url: null,
  uploads: false,
  meta_labels: {},
  loaded: true,
};

const PATH = 'GET /api/x/wall/admin/photos/p1/analysis';

function renderPanel(routes: Record<string, Route>, extensions: AdminExtension[] = [WALL]) {
  const requests = stubApi({ 'GET /api/admin/extensions': () => ({ extensions }), ...routes });
  const view = render(
    <QueryClientProvider client={testClient()}>
      <UiProvider>
        <AnalysisPanel photo={PHOTO} />
      </UiProvider>
    </QueryClientProvider>,
  );
  return { requests, view };
}

const analysisRequests = (requests: Request[]) => requests.filter((r) => r.url.includes('/api/x/wall/'));

describe('AnalysisPanel', () => {
  it('stays away without the wall extension', async () => {
    const { requests, view } = renderPanel({ [PATH]: () => photoAnalysis() }, []);
    await waitFor(() => expect(requests.length).toBe(1));
    expect(view.container.textContent).toBe('');
    expect(analysisRequests(requests)).toEqual([]);
  });

  it('renders nothing when the route is missing', async () => {
    const { requests, view } = renderPanel({});
    await waitFor(() => expect(analysisRequests(requests).length).toBe(1));
    await waitFor(() => expect(view.container.textContent).toBe(''));
  });

  it('says when there is no analysis yet', async () => {
    renderPanel({ [PATH]: () => json(404, { error: 'not_found', message: 'Nicht gefunden.' }) });
    expect(await screen.findByText('Noch keine Analyse für dieses Foto.')).toBeTruthy();
    expect(screen.getByRole('heading', { name: 'Analyse' })).toBeTruthy();
  });

  it('shows state, boxes, details and raw values', async () => {
    renderPanel({ [PATH]: () => photoAnalysis() });
    expect(await screen.findByText('fertig')).toBeTruthy();
    const boxes = screen.getAllByTestId('analysis-box');
    expect(boxes).toHaveLength(2);
    expect(boxes[0]?.dataset.kind).toBe('face');
    expect(boxes[0]?.style.left).toBe('10.00%');
    expect(boxes[0]?.style.height).toBe('30.00%');
    expect(boxes[0]?.textContent).toBe('Gesicht 1');
    expect(screen.getByTestId('analysis-details').textContent).toContain('Gesichter2');
    expect(screen.getByRole('button', { name: 'Rohwerte' })).toBeTruthy();

    fireEvent.click(screen.getByRole('switch', { name: 'Rahmen zeigen' }));
    await waitFor(() => expect(screen.queryAllByTestId('analysis-box')).toHaveLength(0));
  });

  it('"Neu analysieren" posts and shows the photo waiting', async () => {
    const { requests } = renderPanel({
      [PATH]: () => photoAnalysis('failed'),
      'POST /api/x/wall/admin/photos/p1/analysis': () => photoAnalysis('pending'),
    });
    expect(await screen.findByText('fehlgeschlagen')).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: 'Neu analysieren' }));
    expect(await screen.findByText('wartet')).toBeTruthy();
    expect(requests.some((r) => r.method === 'POST' && r.url.endsWith('/photos/p1/analysis'))).toBe(true);
  });
});
