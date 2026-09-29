"use client";

import { useEffect, useState } from "react";
import type { ApiErrorKind } from "@/lib/types";

/**
 * The generating state shows elapsed time, not a percentage: the provider
 * reports no progress, and inventing one would be a lie the user can feel.
 */
export function GeneratingState() {
  const [elapsed, setElapsed] = useState(0);

  useEffect(() => {
    const started = Date.now();
    const id = setInterval(() => setElapsed(Math.floor((Date.now() - started) / 1000)), 1000);
    return () => clearInterval(id);
  }, []);

  return (
    <div className="flex h-full flex-col items-center justify-center gap-5 px-6 text-center animate-fade-in">
      <span
        className="h-7 w-7 rounded-full border-2 border-zinc-700 border-t-accent motion-safe:animate-spin"
        aria-hidden
      />
      <div className="space-y-1.5">
        <p className="text-sm font-medium text-zinc-200" role="status" aria-live="polite">
          Generating your model...
        </p>
        <p className="text-xs text-zinc-500">
          {elapsed < 20
            ? "This usually takes 10-40 seconds."
            : elapsed < 75
              ? "Still working - the GPU may be waking up."
              : "Taking longer than usual, but still going."}
        </p>
      </div>
      <p className="text-xs tabular-nums text-zinc-600">{elapsed}s elapsed</p>
    </div>
  );
}

/** Shown while the browser downloads and parses an already-generated GLB. */
export function AssetLoadingState() {
  return (
    <div className="absolute inset-0 z-10 flex flex-col items-center justify-center gap-3 bg-canvas/70 backdrop-blur-[2px] animate-fade-in">
      <span
        className="h-6 w-6 rounded-full border-2 border-zinc-700 border-t-accent motion-safe:animate-spin"
        aria-hidden
      />
      <p className="text-xs text-zinc-400" role="status" aria-live="polite">
        Loading model...
      </p>
    </div>
  );
}

const ERROR_TITLES: Record<ApiErrorKind, string> = {
  validation: "That prompt needs a tweak",
  network: "The generation service is unavailable",
  generation: "We couldn't generate this model",
  rate_limit: "Too many requests",
  quota: "Generation temporarily unavailable",
};

interface ErrorStateProps {
  kind: ApiErrorKind;
  message: string;
  onRetry: () => void;
  /** True when a previously generated model is still on screen behind this. */
  compact?: boolean;
}

export function ErrorState({ kind, message, onRetry, compact = false }: ErrorStateProps) {
  const title = ERROR_TITLES[kind];
  // A backend message can coincide with our title; showing both would read as
  // a rendering bug.
  const detail = message.replace(/\.$/, "") === title.replace(/\.$/, "") ? null : message;

  if (compact) {
    // A valid model is still visible -- never blank it out for an error banner.
    return (
      <div className="mt-4 flex flex-col gap-3 rounded-lg border border-red-500/20 bg-red-500/5 px-4 py-3 sm:flex-row sm:items-center sm:justify-between animate-fade-in">
        <div className="min-w-0">
          <p className="text-sm font-medium text-red-300">{title}</p>
          {detail && <p className="mt-0.5 text-xs text-zinc-400">{detail}</p>}
        </div>
        <button
          type="button"
          onClick={onRetry}
          className="shrink-0 rounded-md border border-hairline-strong px-3 py-1.5 text-xs text-zinc-200 transition-colors hover:bg-surface-raised"
        >
          Try Again
        </button>
      </div>
    );
  }

  return (
    <div className="flex h-full flex-col items-center justify-center gap-4 px-6 text-center animate-fade-in">
      <div className="flex h-10 w-10 items-center justify-center rounded-full border border-red-500/25 bg-red-500/5">
        <svg viewBox="0 0 24 24" className="h-5 w-5 text-red-400" aria-hidden>
          <path
            fill="none"
            stroke="currentColor"
            strokeWidth="1.6"
            strokeLinecap="round"
            d="M12 8v5m0 3.5h.01M10.3 3.9 2.6 17.1A1.9 1.9 0 0 0 4.3 20h15.4a1.9 1.9 0 0 0 1.7-2.9L13.7 3.9a1.9 1.9 0 0 0-3.4 0Z"
          />
        </svg>
      </div>
      <div className="space-y-1.5">
        <p className="text-sm font-medium text-zinc-200">{title}</p>
        {detail && (
          <p className="max-w-sm text-xs leading-relaxed text-zinc-500">{detail}</p>
        )}
      </div>
      <button
        type="button"
        onClick={onRetry}
        className="rounded-md border border-hairline-strong px-4 py-2 text-xs text-zinc-200 transition-colors hover:bg-surface-raised"
      >
        Try Again
      </button>
    </div>
  );
}
