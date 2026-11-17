import { useCallback, useEffect, useRef, useState } from "react";
import { api, errorMessage } from "@/services/api";

/** GET `url` and expose { data, error, loading, reload }. Pass null to skip. Optional polling interval. */
export function useApi<T>(url: string | null, params?: Record<string, unknown>, pollMs?: number | ((d: T | null) => number | null)) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState<boolean>(!!url);
  const key = url ? url + JSON.stringify(params ?? {}) : null;
  const dataRef = useRef<T | null>(null);

  const load = useCallback(
    async (silent = false) => {
      if (!url) return;
      if (!silent) setLoading(true);
      try {
        const r = await api.get<T>(url, { params });
        dataRef.current = r.data;
        setData(r.data);
        setError(null);
      } catch (e) {
        setError(errorMessage(e));
      } finally {
        setLoading(false);
      }
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [key],
  );

  useEffect(() => {
    load();
  }, [load]);

  useEffect(() => {
    if (!pollMs || !url) return;
    let timer: ReturnType<typeof setTimeout>;
    const tick = () => {
      const ms = typeof pollMs === "function" ? pollMs(dataRef.current) : pollMs;
      if (ms) timer = setTimeout(async () => {
        await load(true);
        tick();
      }, ms);
    };
    tick();
    return () => clearTimeout(timer);
  }, [load, pollMs, url]);

  return { data, error, loading, reload: load, setData };
}
