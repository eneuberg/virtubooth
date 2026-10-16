/**
 * ML-Pipeline requests for the external AI (PLAN-NIGHT §4.4, under /api/x/wall/admin):
 * config, key, usage, properties, poll now and the test image. The analyzers are in
 * ../wall/api.ts (GET /analysis, PUT /analysis/analyzers/{name}).
 */
import { wallFetch } from '../wall/api';
import type {
  DetectionMode,
  LlmConfigChange,
  LlmKeyState,
  LlmProperty,
  LlmStatus,
  TestImageResult,
} from './types';

export function fetchLlm(): Promise<LlmStatus> {
  return wallFetch('/llm');
}

/** Only the fields given change (each card sends its own); rev, updated_at and by are server-set. */
export function saveLlmConfig(change: LlmConfigChange): Promise<LlmStatus> {
  return wallFetch('/llm/config', { method: 'PUT', json: change });
}

/** „Objekterkennung: Lokal / KI / Aus“ (either/or; also switches the `objects` analyzer). */
export function setObjectDetection(mode: DetectionMode): Promise<LlmStatus> {
  return wallFetch('/llm/object-detection', { method: 'PUT', json: { mode } });
}

export function setLlmKey(provider: string, key: string): Promise<LlmKeyState> {
  return wallFetch('/llm/key', { method: 'PUT', json: { provider, key } });
}

/** Deletes this provider's key only (the others stay). */
export function clearLlmKey(provider: string): Promise<LlmKeyState> {
  return wallFetch(`/llm/key?provider=${encodeURIComponent(provider)}`, { method: 'DELETE' });
}

/**
 * Asks `provider` whether its stored key and `model` work (the models list, one token
 * when the model is not listed). `ok: false` names what is wrong.
 */
export function testLlmKey(provider: string, model: string): Promise<{ ok: boolean; message: string }> {
  return wallFetch('/llm/key/test', { method: 'POST', json: { provider, model } });
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

const propertyPath = (name: string) => `/llm/properties/${encodeURIComponent(name)}`;

/** „Löschen“ (into the Papierkorb) or „Wiederherstellen“ (back as it was). */
export function trashProperty(name: string, trash: boolean): Promise<LlmProperty> {
  return wallFetch(`${propertyPath(name)}/${trash ? 'trash' : 'restore'}`, { method: 'POST' });
}

/** „Endgültig löschen“ (only from the Papierkorb): the property and its scores. */
export async function deleteProperty(name: string): Promise<LlmProperty[]> {
  return (await wallFetch<{ properties: LlmProperty[] }>(propertyPath(name), { method: 'DELETE' }))
    .properties;
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
