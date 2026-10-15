/**
 * Compile-time contract checks (no runtime code): every hand-written type of the
 * ML-Pipeline and Live-Wall admin must accept what the server answers, i.e. the
 * generated schema type with its server-defaulted fields filled in. A backend change
 * that the UI does not follow fails `tsc` here instead of in the browser.
 */
import type { Assert, Fits } from '@/api/contract';
import type { components } from '@/api/schema.gen';
import type { AnalysisStatus, CategoryItem, CategoryPreview, PhotoAnalysis, ValuesOut } from '../wall/types';
import type { LlmStatus, TestImageResult } from './types';

type S = components['schemas'];

// test runs: the server's boxes/details are loose dicts; the worker writes them in
// AnalysisBox / {label, value} shape (enrich/testjobs.py), so these two are checked
// without them
type LooseRun = Omit<S['TestRunOut'], 'boxes' | 'details'>;
type UiRun = Omit<NonNullable<TestImageResult['local']>, 'boxes' | 'details'>;

export type ContractChecks = [
  Assert<Fits<S['LlmStatus'], LlmStatus>>,
  Assert<Fits<LooseRun, UiRun>>,
  Assert<Fits<S['ExternalTestOut'], NonNullable<TestImageResult['external']>>>,
  Assert<Fits<S['CategoryItem'], CategoryItem>>,
  Assert<Fits<S['CategoryPreviewOut'], CategoryPreview>>,
  Assert<Fits<S['ValuesOut'], ValuesOut>>,
  Assert<Fits<S['PhotoAnalysis'], PhotoAnalysis>>,
  Assert<Fits<S['AnalysisStatus'], AnalysisStatus>>,
];
