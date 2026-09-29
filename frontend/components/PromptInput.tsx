"use client";

import { type FormEvent, type KeyboardEvent } from "react";

export const PROMPT_MAX_LENGTH = 300;

interface PromptInputProps {
  value: string;
  onChange: (value: string) => void;
  onSubmit: () => void;
  disabled: boolean;
  /** Client-side validation message, shown under the field. */
  hint?: string | null;
}

export function PromptInput({ value, onChange, onSubmit, disabled, hint }: PromptInputProps) {
  const remaining = PROMPT_MAX_LENGTH - value.length;
  const nearLimit = remaining <= 40;

  function handleSubmit(event: FormEvent) {
    event.preventDefault();
    onSubmit();
  }

  function handleKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    // Enter submits; Shift+Enter adds a newline.
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      if (!disabled) onSubmit();
    }
  }

  return (
    <form onSubmit={handleSubmit} className="w-full">
      <div className="group relative rounded-xl border border-hairline bg-surface shadow-panel transition-colors focus-within:border-hairline-strong">
        <label htmlFor="prompt" className="sr-only">
          Describe your 3D object
        </label>
        <textarea
          id="prompt"
          name="prompt"
          value={value}
          onChange={(e) => onChange(e.target.value.slice(0, PROMPT_MAX_LENGTH))}
          onKeyDown={handleKeyDown}
          rows={3}
          disabled={disabled}
          spellCheck
          autoComplete="off"
          placeholder="Describe your 3D object..."
          aria-describedby="prompt-hint"
          aria-invalid={Boolean(hint)}
          className="block w-full resize-none rounded-xl bg-transparent px-4 py-3.5 text-[15px] leading-relaxed text-zinc-100 placeholder:text-zinc-500 focus:outline-none disabled:cursor-not-allowed disabled:opacity-60"
        />

        <div className="flex items-center justify-between gap-3 border-t border-hairline px-4 py-2.5">
          <span
            id="prompt-hint"
            className={`text-xs ${hint ? "text-red-400" : "text-zinc-500"}`}
            role={hint ? "alert" : undefined}
          >
            {hint ?? "Press Enter to generate, Shift + Enter for a new line"}
          </span>
          <span
            className={`shrink-0 text-xs tabular-nums ${
              nearLimit ? "text-amber-400/80" : "text-zinc-600"
            }`}
          >
            {value.length}/{PROMPT_MAX_LENGTH}
          </span>
        </div>
      </div>

      <button
        type="submit"
        disabled={disabled}
        className="mt-3 inline-flex h-11 w-full items-center justify-center gap-2 rounded-lg bg-accent px-5 text-sm font-medium text-white transition-colors hover:bg-accent-hover disabled:cursor-not-allowed disabled:bg-accent/40 disabled:text-white/70 sm:w-auto sm:min-w-[200px]"
      >
        {disabled ? "Generating..." : "Generate 3D Model"}
      </button>
    </form>
  );
}
