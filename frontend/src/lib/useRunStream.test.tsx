import { act, renderHook, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { ReactNode } from 'react';
import { useRunStream } from './useRunStream';

class FakeEventSource {
  static instances: FakeEventSource[] = [];
  url: string;
  listeners: Record<string, ((event: MessageEvent) => void)[]> = {};
  onopen: (() => void) | null = null;
  onerror: (() => void) | null = null;
  closed = false;

  constructor(url: string) {
    this.url = url;
    FakeEventSource.instances.push(this);
  }

  addEventListener(type: string, handler: (event: MessageEvent) => void) {
    this.listeners[type] = [...(this.listeners[type] ?? []), handler];
  }

  emit(type: string, data: unknown) {
    for (const handler of this.listeners[type] ?? []) {
      handler({ data: JSON.stringify(data) } as MessageEvent);
    }
  }

  close() {
    this.closed = true;
  }
}

beforeEach(() => {
  FakeEventSource.instances = [];
  vi.stubGlobal('EventSource', FakeEventSource);
});

afterEach(() => {
  vi.unstubAllGlobals();
});

function wrapper({ children }: { children: ReactNode }) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>;
}

describe('useRunStream', () => {
  it('does not connect when runId is undefined', () => {
    renderHook(() => useRunStream(undefined), { wrapper });
    expect(FakeEventSource.instances).toHaveLength(0);
  });

  it('connects to the stream endpoint for the given run', () => {
    renderHook(() => useRunStream('run-1'), { wrapper });
    expect(FakeEventSource.instances).toHaveLength(1);
    expect(FakeEventSource.instances[0].url).toBe('/api/runs/run-1/stream?after=0');
  });

  it('marks as connected on open and appends events to the log', async () => {
    const { result } = renderHook(() => useRunStream('run-1'), { wrapper });
    const source = FakeEventSource.instances[0];

    act(() => source.onopen?.());
    await waitFor(() => expect(result.current.connected).toBe(true));

    act(() => source.emit('scenario_running', { seq: 1, name: 'Cenário A' }));
    await waitFor(() => expect(result.current.log).toHaveLength(1));
    expect(result.current.log[0]).toMatchObject({ type: 'scenario_running', name: 'Cenário A' });
  });

  it('closes the connection once a terminal run_snapshot arrives', async () => {
    const { result } = renderHook(() => useRunStream('run-1'), { wrapper });
    const source = FakeEventSource.instances[0];
    act(() => source.onopen?.());

    act(() => source.emit('run_snapshot', { seq: 2, id: 'run-1', status: 'passed' }));

    await waitFor(() => expect(source.closed).toBe(true));
    expect(result.current.connected).toBe(false);
  });

  it('keeps the connection open for non-terminal run_snapshot events', async () => {
    renderHook(() => useRunStream('run-1'), { wrapper });
    const source = FakeEventSource.instances[0];
    act(() => source.emit('run_snapshot', { seq: 1, id: 'run-1', status: 'running' }));
    expect(source.closed).toBe(false);
  });

  it('reconnects with the last seen seq after an error', async () => {
    vi.useFakeTimers();
    renderHook(() => useRunStream('run-1'), { wrapper });
    const first = FakeEventSource.instances[0];
    first.emit('step_finished', { seq: 7, status: 'passed' });
    act(() => first.onerror?.());

    await act(async () => {
      vi.advanceTimersByTime(2000);
    });

    expect(FakeEventSource.instances).toHaveLength(2);
    expect(FakeEventSource.instances[1].url).toBe('/api/runs/run-1/stream?after=7');
    vi.useRealTimers();
  });

  it('backs off exponentially on repeated errors instead of retrying every 2s forever', async () => {
    // Achado ao vivo: sem isso, uma aba deixada aberta durante uma queda
    // prolongada do servidor martela reconexão pra sempre a cada 2s.
    vi.useFakeTimers();
    renderHook(() => useRunStream('run-1'), { wrapper });

    act(() => FakeEventSource.instances[0].onerror?.()); // 1ª falha -> espera 2s
    await act(async () => vi.advanceTimersByTime(1999));
    expect(FakeEventSource.instances).toHaveLength(1); // ainda não reconectou
    await act(async () => vi.advanceTimersByTime(1));
    expect(FakeEventSource.instances).toHaveLength(2);

    act(() => FakeEventSource.instances[1].onerror?.()); // 2ª falha seguida -> espera 4s
    await act(async () => vi.advanceTimersByTime(3999));
    expect(FakeEventSource.instances).toHaveLength(2);
    await act(async () => vi.advanceTimersByTime(1));
    expect(FakeEventSource.instances).toHaveLength(3);

    vi.useRealTimers();
  });

  it('resets the backoff to the base delay after a successful reconnection', async () => {
    vi.useFakeTimers();
    renderHook(() => useRunStream('run-1'), { wrapper });

    act(() => FakeEventSource.instances[0].onerror?.()); // 1ª falha -> 2s
    await act(async () => vi.advanceTimersByTime(2000));
    act(() => FakeEventSource.instances[1].onopen?.()); // conectou de novo -> reseta o contador

    act(() => FakeEventSource.instances[1].onerror?.()); // falha logo em seguida -> volta pra 2s, não 4s
    await act(async () => vi.advanceTimersByTime(1999));
    expect(FakeEventSource.instances).toHaveLength(2);
    await act(async () => vi.advanceTimersByTime(1));
    expect(FakeEventSource.instances).toHaveLength(3);

    vi.useRealTimers();
  });

  it('ignores malformed event payloads without crashing', () => {
    const { result } = renderHook(() => useRunStream('run-1'), { wrapper });
    const source = FakeEventSource.instances[0];
    act(() => {
      for (const handler of source.listeners.step_finished ?? []) {
        handler({ data: 'not-json' } as MessageEvent);
      }
    });
    expect(result.current.log).toHaveLength(0);
  });

  it('closes the source on unmount', () => {
    const { unmount } = renderHook(() => useRunStream('run-1'), { wrapper });
    const source = FakeEventSource.instances[0];
    unmount();
    expect(source.closed).toBe(true);
  });
});
