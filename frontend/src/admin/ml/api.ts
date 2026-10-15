/**
 * ML-Pipeline requests for the external AI (PLAN-NIGHT §4.4, under /api/x/wall/admin):
 * config, key, usage, properties, poll now and the test image. The analyzers are in
 * ../wall/api.ts (GET /analysis, PUT /analysis/analyzers/{name}).
 */
import { wallFetch } from '../wall/api';
import type { LlmConfig, LlmKeyState, LlmProperty, LlmStatus, TestImageResult } from './types';

export function fetchLlm(): Promise<LlmStatus> {
  return wallFetch('/llm');
}

/** The editable part only; rev, updated_at and by are server-set. */
export function saveLlmConfig(config: LlmConfig): Promise<LlmStatus> {
  const { enabled, provider, model, poll_interval_s, detect, image_max_px, budget } = config;
  return wallFetch('/llm/config', {
    method: 'PUT',
    json: { enabled, provider, model, poll_interval_s, detect, image_max_px, budget },
  });
}

export function setLlmKey(provider: string, key: string): Promise<LlmKeyState> {
  return wallFetch('/llm/key', { method: 'PUT', json: { provider, key } });
}

export function clearLlmKey(): Promise<LlmKeyState> {
  return wallFetch('/llm/key', { method: 'DELETE' });
}

export function testLlmKey(): Promise<{ ok: boolean; message: string }> {
  return wallFetch('/llm/key/test', { method: 'POST' });
}

export function pollNow(): Promise<{ started: boolean; reason: string | null }> {
  return wallFetch('/llm/poll', { method: 'POST' });
}

export async function fetchProperties(): Promise<LlmProperty[]> {
  return (await wallFetch<{ properties: LlmProperty[] }>('/llm/properties')).properties;
}

export function createProperty(name: string, prompt: string): Promise<LlmProperty> {
  return wallFetch('/llm/properties', { method: 'POST', json: { name, prompt } });
}

export function archiveProperty(name: string, archive: boolean): Promise<LlmProperty> {
  const action = archive ? 'archive' : 'unarchive';
  return wallFetch(`/llm/properties/${encodeURIComponent(name)}/${action}`, { method: 'POST' });
}

/**
 * Run the pipeline (or some analyzers) on an image without storing it. `analyzers`:
 * null = the whole pipeline; `external`: also send it to the external AI.
 */
export function runTestImage(
  file: File,
  analyzers: string[] | null,
  external: boolean,
): Promise<TestImageResult> {
  const form = new FormData();
  form.set('file', file);
  form.set('analyzers', analyzers ? analyzers.join(',') : 'all');
  form.set('external', external ? '1' : '0');
  return wallFetch('/test-image', { method: 'POST', body: form });
}
