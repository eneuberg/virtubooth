import { QueryClientProvider } from '@tanstack/react-query';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { useState } from 'react';
import { describe, expect, it } from 'vitest';
import type { AdminExtension, AdminPhoto } from '@/api/types';
import { UiProvider } from '@/ui/UiProvider';
import { json, must, stubApi, testClient, type Route } from '../testing';
import { AnalysisBoxes, AnalysisPanel } from './AnalysisPanel';
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
  user: {
    id: 1,
    name: 'Gast 1',
    instagram: null,
    banned: false,
    auto_banned: false,
    uploads_paused: false,
    is_host: false,
  },
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

/** the panel and the frames on the photo, as the inspector wires them */
function Inspector() {
  const [show, setShow] = useState(true);
  return (
    <>
      <div data-testid="photo">
        <AnalysisBoxes photo={PHOTO} visible={show} />
      </div>
      <AnalysisPanel photo={PHOTO} showBoxes={show} onShowBoxesChange={setShow} />
    </>
  );
}

function renderPanel(routes: Record<string, Route>, extensions: AdminExtension[] = [WALL]) {
  const requests = stubApi({ 'GET /api/admin/extensions': () => ({ extensions }), ...routes });
  const view = render(
    <QueryClientProvider client={testClient()}>
      <UiProvider>
        <Inspector />
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
    expect(boxes).toHaveLength(3);
    expect(boxes[0]?.dataset.kind).toBe('face');
    expect(boxes[0]?.style.left).toBe('10.00%');
    expect(boxes[0]?.style.height).toBe('30.00%');
    expect(boxes[0]?.textContent).toBe('Gesicht 1');
    // on the photo, not in the panel
    expect(screen.getByTestId('photo').contains(boxes[0] ?? null)).toBe(true);
    expect(screen.getByTestId('analysis').querySelector('img')).toBeNull();
    expect(screen.getByTestId('analysis-details').textContent).toContain('Gesichter2');
    expect(screen.getByRole('button', { name: 'Rohwerte' })).toBeTruthy();

    fireEvent.click(screen.getByRole('switch', { name: 'Rahmen auf dem Foto zeigen' }));
    await waitFor(() => expect(screen.queryAllByTestId('analysis-box')).toHaveLength(0));
  });

  it('has no "Neu analysieren" (analyses are frozen)', async () => {
    renderPanel({ [PATH]: () => photoAnalysis('failed') });
    expect(await screen.findByText('fehlgeschlagen')).toBeTruthy();
    expect(screen.queryByRole('button', { name: /analysieren/i })).toBeNull();
  });

  it('lists the objects with source, scores and runs; a hovered object lights its frame', async () => {
    renderPanel({ [PATH]: () => photoAnalysis() });
    const objects = await screen.findAllByTestId('analysis-object');
    expect(objects).toHaveLength(2);
    expect(objects[0]?.textContent).toContain('Weinglas');
    expect(objects[0]?.textContent).toContain('91');
    expect(objects[0]?.textContent).toContain('lokal');
    expect(objects[1]?.textContent).toContain('Claude');
    // property scores per object (index = idx)
    expect(objects[0]?.textContent).toContain('coolness 0,20');
    expect(objects[1]?.textContent).toContain('coolness 0,90');
    expect(screen.getByTestId('analysis-runs').textContent).toContain('Erkennung Claude: fertig');
    // faces and hands from boxes, plus the one object with a box
    const frames = screen.getAllByTestId('analysis-box');
    expect(frames.map((f) => f.dataset.kind)).toEqual(['face', 'hand', 'object']);
    fireEvent.pointerEnter(must(objects[0]));
    await waitFor(() => expect(frames[2]?.dataset.lit).toBe('true'));
    fireEvent.pointerLeave(must(objects[0]));
    await waitFor(() => expect(screen.getAllByTestId('analysis-box')[2]?.dataset.lit).toBeUndefined());
  });

  it('tells a photo without an object list from one where nothing was found', async () => {
    renderPanel({ [PATH]: () => ({ ...photoAnalysis(), objects: [], runs: [] }) });
    expect(await screen.findByText(/Keine Objektliste: das Foto wurde ohne Objekterkennung/)).toBeTruthy();
    cleanup();
    const runs = photoAnalysis().runs;
    renderPanel({ [PATH]: () => ({ ...photoAnalysis(), objects: [], runs }) });
    expect(await screen.findByText('Keine Objekte erkannt.')).toBeTruthy();
  });

  it("marks the guest's opt-outs", async () => {
    renderPanel({
      [PATH]: () => ({ ...photoAnalysis(), opt_out: { analysis: true, external_ai: true } }),
    });
    const marks = await screen.findByTestId('analysis-opt-out');
    expect(marks.textContent).toContain('Gast möchte keine Auswertung');
    expect(marks.textContent).toContain('Keine externe KI');
  });
});
