import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { api, type RunsFilter } from '@/lib/api';
import type { ProjectConfig, RunCreateRequest } from '@/types/api';

export const queryKeys = {
  health: ['health'] as const,
  config: ['config'] as const,
  runs: (filter: RunsFilter) => ['runs', filter] as const,
  run: (runId: string) => ['run', runId] as const,
  apiKeys: ['api-keys'] as const,
};

export function useHealth() {
  return useQuery({
    queryKey: queryKeys.health,
    queryFn: api.getHealth,
    refetchInterval: 30_000,
  });
}

export function useConfig() {
  return useQuery({ queryKey: queryKeys.config, queryFn: api.getConfig });
}

export function useSaveConfig() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (payload: Partial<ProjectConfig>) => api.saveConfig(payload),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: queryKeys.config }),
  });
}

export function useTestLlmProvider() {
  return useMutation({
    mutationFn: (providerId: string) => api.testLlmProvider(providerId),
  });
}

export function useRuns(filter: RunsFilter = {}) {
  return useQuery({
    queryKey: queryKeys.runs(filter),
    queryFn: () => api.listRuns(filter),
    refetchInterval: 10_000,
  });
}

export function useRun(runId: string | undefined) {
  return useQuery({
    queryKey: queryKeys.run(runId ?? ''),
    queryFn: () => api.getRun(runId!),
    enabled: !!runId,
  });
}

export function useCreateRun() {
  return useMutation({
    mutationFn: (payload: RunCreateRequest) => api.createRun(payload),
  });
}

export function useCancelRun() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (runId: string) => api.cancelRun(runId),
    onSuccess: (_data, runId) => queryClient.invalidateQueries({ queryKey: queryKeys.run(runId) }),
  });
}

export function useApiKeys() {
  return useQuery({ queryKey: queryKeys.apiKeys, queryFn: api.listApiKeys });
}

export function useCreateApiKey() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (name: string) => api.createApiKey(name),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: queryKeys.apiKeys }),
  });
}

export function useRevokeApiKey() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (keyId: string) => api.revokeApiKey(keyId),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: queryKeys.apiKeys }),
  });
}
