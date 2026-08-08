import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { api } from '@/lib/api';
import type { ProjectConfig } from '@/types/api';

export const queryKeys = {
  health: ['health'] as const,
  config: ['config'] as const,
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
