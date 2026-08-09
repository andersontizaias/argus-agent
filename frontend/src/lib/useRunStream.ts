import { useEffect, useRef, useState } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { queryKeys } from '@/lib/queries';
import { TERMINAL_RUN_STATUSES, type RunDetail, type RunStatus } from '@/types/api';

export interface RunStreamLogEntry {
  type: string;
  seq?: number;
  [key: string]: unknown;
}

// Backoff exponencial (2s, 4s, 8s, 16s, cap em 30s) em vez de tentar de nova
// a cada 2s pra sempre — uma aba de Detalhe da Run deixada aberta durante
// uma queda prolongada do servidor (deploy, reinício) não deve martelar
// reconexão por horas (achado ao vivo: dezenas de reinícios do servidor
// durante uma sessão de depuração, com a aba aberta, geraram milhares de
// tentativas). Reseta pro valor base assim que uma conexão abre de verdade.
const RECONNECT_BASE_MS = 2000;
const RECONNECT_MAX_MS = 30000;

const EVENT_TYPES = [
  'run_snapshot',
  'run_provisioning',
  'run_running',
  'run_error',
  'scenario_running',
  'scenario_finished',
  'step_finished',
  'run_finished',
];

/** Assina o SSE de uma run e mantém a query do detalhe (useRun) sempre
 * fresca — cada evento invalida o cache em vez de tentar reconstruir o
 * estado localmente (bem mais simples e sempre consistente com o que o
 * backend realmente persistiu). Reconecta com `?after=seq` pra retomar de
 * onde parou em vez de perder eventos numa queda momentânea. */
export function useRunStream(runId: string | undefined) {
  const [log, setLog] = useState<RunStreamLogEntry[]>([]);
  const [connected, setConnected] = useState(false);
  const lastSeqRef = useRef(0);
  const queryClient = useQueryClient();

  useEffect(() => {
    if (!runId) return;
    const currentRunId = runId; // narrowed const — o TS não propaga o guard acima pra dentro dos closures abaixo
    let cancelled = false;
    let source: EventSource | null = null;
    let retryTimer: ReturnType<typeof setTimeout> | undefined;
    let attempt = 0;

    function connect() {
      if (cancelled) return;
      source = new EventSource(`/api/runs/${currentRunId}/stream?after=${lastSeqRef.current}`);

      source.onopen = () => {
        attempt = 0;
        setConnected(true);
      };
      source.onerror = () => {
        setConnected(false);
        source?.close();
        if (!cancelled) {
          const delay = Math.min(RECONNECT_BASE_MS * 2 ** attempt, RECONNECT_MAX_MS);
          attempt += 1;
          retryTimer = setTimeout(connect, delay);
        }
      };

      for (const type of EVENT_TYPES) {
        source.addEventListener(type, (event: MessageEvent) => {
          let data: Record<string, unknown>;
          try {
            data = JSON.parse(event.data);
          } catch {
            return;
          }
          if (typeof data.seq === 'number') lastSeqRef.current = data.seq;

          setLog((prev) => [...prev.slice(-199), { type, ...data }]);
          queryClient.setQueryData<RunDetail>(queryKeys.run(currentRunId), (old) =>
            type === 'run_snapshot' ? (data as unknown as RunDetail) : old
          );
          queryClient.invalidateQueries({ queryKey: queryKeys.run(currentRunId) });

          if (type === 'run_snapshot' && TERMINAL_RUN_STATUSES.includes(data.status as RunStatus)) {
            source?.close();
            setConnected(false);
          }
        });
      }
    }

    connect();
    return () => {
      cancelled = true;
      if (retryTimer) clearTimeout(retryTimer);
      source?.close();
    };
  }, [runId, queryClient]);

  return { log, connected };
}
