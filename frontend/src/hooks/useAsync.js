import { useCallback, useEffect, useState } from "react";

/**
 * Run an async function and track loading / success / error.
 * `deps` controls when it re-runs (same contract as useEffect deps).
 */
export function useAsync(fn, deps = []) {
  const [state, setState] = useState({ status: "loading", data: null, error: null });

  // eslint-disable-next-line react-hooks/exhaustive-deps
  const run = useCallback(() => {
    let alive = true;
    setState((s) => ({ ...s, status: "loading", error: null }));
    Promise.resolve()
      .then(fn)
      .then(
        (data) => alive && setState({ status: "success", data, error: null }),
        (err) =>
          alive &&
          setState({ status: "error", data: null, error: err?.message || String(err) }),
      );
    return () => {
      alive = false;
    };
  }, deps);

  useEffect(() => run(), [run]);

  return { ...state, reload: run };
}
