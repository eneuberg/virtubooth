/**
 * ML-Pipeline queries: the external AI's status (config, key state, usage) every 10 s
 * while the section is open, the properties on focus.
 */
import { useQuery } from '@tanstack/react-query';
import { wk } from '../wall/keys';
import { fetchLlm, fetchProperties } from './api';

export function useLlm(enabled = true) {
  return useQuery({
    queryKey: wk.llm,
    queryFn: fetchLlm,
    enabled,
    staleTime: 0,
    refetchOnWindowFocus: true,
    refetchInterval: 10_000,
    retry: false,
  });
}

export function useProperties(enabled = true) {
  return useQuery({
    queryKey: wk.properties,
    queryFn: fetchProperties,
    enabled,
    staleTime: 0,
    refetchOnWindowFocus: true,
    retry: false,
  });
}
