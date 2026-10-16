import { useEffect, useState } from "react";
import type { TopData } from "../types";

const BASE = import.meta.env.BASE_URL;
let cached: TopData | null = null;

export function useTop() {
  const [data, setData] = useState<TopData | null>(cached);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    // The initial state already holds a cached copy.
    if (cached) return;
    fetch(`${BASE}data/top.json`)
      .then((r) => {
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        return r.json();
      })
      .then((top: TopData) => {
        cached = top;
        setData(top);
      })
      .catch((e) => setError(e.message));
  }, []);

  return { data, error };
}
