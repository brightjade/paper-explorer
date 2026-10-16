import { useEffect, useRef, useState } from "react";

/**
 * How many of `total` items to render, growing by `step` whenever the sentinel
 * element comes within reach of the viewport. Starts over when `resetKey`
 * changes (another conference, filter, search or sort), so clearing a filter
 * mounts one batch of rows instead of the whole conference at once.
 */
export function useRevealOnScroll(total: number, resetKey: string, step = 100) {
  const [limit, setLimit] = useState(step);
  const [limitFor, setLimitFor] = useState(resetKey);
  if (resetKey !== limitFor) {
    setLimitFor(resetKey);
    setLimit(step);
  }

  const sentinelRef = useRef<HTMLDivElement>(null);
  const shown = Math.min(limit, total);

  useEffect(() => {
    const sentinel = sentinelRef.current;
    if (!sentinel || shown >= total) return;
    // A new observer reports the sentinel's state right away, so a sentinel
    // still in reach after a batch lands asks for the next one.
    const observer = new IntersectionObserver(
      (entries) => {
        if (entries.some((e) => e.isIntersecting)) setLimit((l) => l + step);
      },
      { rootMargin: "800px 0px" },
    );
    observer.observe(sentinel);
    return () => observer.disconnect();
  }, [shown, total, step]);

  const showMore = () => setLimit((l) => l + step);
  return { shown, sentinelRef, showMore };
}
