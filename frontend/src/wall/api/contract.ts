/**
 * Compile-time contract checks (no runtime code) of the wall screen's hand-written
 * types against the generated schema: what the server sends must fit them.
 */
import type { Assert, Fits } from '@/api/contract';
import type { components } from '@/api/schema.gen';
import type { CategoryWinner, WallCategory, WallCategoryVerdict, WallPhoto } from './types';

type S = components['schemas'];

export type ContractChecks = [
  Assert<Fits<S['WallCategory'], WallCategory>>,
  Assert<Fits<S['WallWinner'], CategoryWinner>>,
  Assert<Fits<S['WallVerdict'], WallCategoryVerdict>>,
  Assert<Fits<S['WallPhoto'], WallPhoto>>,
];
