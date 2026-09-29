"use client";

/** The resting state of the viewer, before anything has been generated. */
export function EmptyState() {
  return (
    <div className="flex h-full flex-col items-center justify-center gap-4 px-6 text-center">
      <svg
        viewBox="0 0 48 48"
        className="h-11 w-11 text-zinc-700"
        fill="none"
        stroke="currentColor"
        strokeWidth="1.25"
        strokeLinejoin="round"
        aria-hidden
      >
        <path d="M24 5 42 15v18L24 43 6 33V15z" />
        <path d="M24 5v38M6 15l18 10 18-10" opacity="0.55" />
      </svg>
      <div className="space-y-1.5">
        <p className="text-sm text-zinc-400">Your model will appear here</p>
        <p className="text-xs text-zinc-600">
          Describe an object above, then generate it.
        </p>
      </div>
    </div>
  );
}
