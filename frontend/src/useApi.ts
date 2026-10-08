import { useCallback, useEffect, useRef, useState } from "react";

export interface ApiState<T> {
  data: T | undefined;
  error: Error | undefined;
  loading: boolean;
  reload: () => void;
}

/**
 * Runs `load` when `deps` change (and every `refreshMs`, if given).
 * Responses that arrive after the deps changed are ignored.
 */
export function useApi<T>(
  load: () => Promise<T>,
  deps: readonly unknown[],
  refreshMs?: number,
): ApiState<T> {
  const [data, setData] = useState<T>();
  const [error, setError] = useState<Error>();
  const [loading, setLoading] = useState(true);
  const [tick, setTick] = useState(0);
  const loadRef = useRef(load);
  loadRef.current = load;

  useEffect(() => {
    let current = true;
    setLoading(true);
    loadRef
      .current()
      .then((value) => {
        if (!current) return;
        setData(value);
        setError(undefined);
      })
      .catch((reason: unknown) => {
        if (current) setError(reason instanceof Error ? reason : new Error(String(reason)));
      })
      .finally(() => {
        if (current) setLoading(false);
      });
    return () => {
      current = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, tick]);

  useEffect(() => {
    if (!refreshMs) return;
    const timer = setInterval(() => setTick((value) => value + 1), refreshMs);
    return () => clearInterval(timer);
  }, [refreshMs]);

  const reload = useCallback(() => setTick((value) => value + 1), []);
  return { data, error, loading, reload };
}
