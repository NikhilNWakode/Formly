"use client";

import type { GeneratedModel } from "@/lib/types";
import { formatBytes, formatCount, formatSeconds } from "@/lib/format";

interface ViewerControlsProps {
  model: GeneratedModel;
  onReset: () => void;
  onToggleFullscreen: () => void;
  isFullscreen: boolean;
  disabled: boolean;
}

export function ViewerControls({
  model,
  onReset,
  onToggleFullscreen,
  isFullscreen,
  disabled,
}: ViewerControlsProps) {
  return (
    <div className="mt-4 flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
      <div className="flex flex-wrap items-center gap-2">
        <button
          type="button"
          onClick={onReset}
          disabled={disabled}
          className="rounded-md border border-hairline bg-surface px-3.5 py-2 text-xs text-zinc-300 transition-colors hover:border-hairline-strong hover:text-white disabled:cursor-not-allowed disabled:opacity-50"
        >
          Reset View
        </button>

        <button
          type="button"
          onClick={onToggleFullscreen}
          disabled={disabled}
          className="rounded-md border border-hairline bg-surface px-3.5 py-2 text-xs text-zinc-300 transition-colors hover:border-hairline-strong hover:text-white disabled:cursor-not-allowed disabled:opacity-50"
        >
          {isFullscreen ? "Exit Fullscreen" : "Fullscreen"}
        </button>

        {/*
          A plain anchor, not a fetch + blob: the backend already sets
          Content-Disposition with a sanitized filename, so the browser's own
          download path is both simpler and more reliable.
        */}
        <a
          href={model.downloadUrl}
          download={model.filename}
          className="rounded-md bg-accent px-3.5 py-2 text-xs font-medium text-white transition-colors hover:bg-accent-hover"
        >
          Download GLB
        </a>
      </div>

      <dl className="flex flex-wrap items-center gap-x-4 gap-y-1 text-[11px] text-zinc-600">
        <div className="flex items-center gap-1.5">
          <dt className="sr-only">Triangles</dt>
          <dd>{formatCount(model.triangleCount)} tris</dd>
        </div>
        <span aria-hidden className="text-zinc-800">
          /
        </span>
        <div className="flex items-center gap-1.5">
          <dt className="sr-only">File size</dt>
          <dd>{formatBytes(model.byteSize)}</dd>
        </div>
        <span aria-hidden className="text-zinc-800">
          /
        </span>
        <div className="flex items-center gap-1.5">
          <dt className="sr-only">Provenance</dt>
          {/*
            An example must never read as a fresh AI result, so the timing is
            replaced rather than shown as 0s.
          */}
          <dd>
            {model.source === "example"
              ? "pre-generated example"
              : `generated in ${formatSeconds(model.generationSeconds)}`}
          </dd>
        </div>
      </dl>
    </div>
  );
}
