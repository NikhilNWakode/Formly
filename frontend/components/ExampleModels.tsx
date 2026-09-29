"use client";

import { EXAMPLE_MODELS, type ExampleModel } from "@/lib/examples";

/**
 * Loads a pre-generated model straight into the viewer.
 *
 * Distinct from ExamplePrompts, which only fills the prompt box and still
 * requires a real generation. This one never touches the generation API, so
 * the 3D experience stays demonstrable when the free GPU quota is spent.
 */

interface ExampleModelsProps {
  onSelect: (example: ExampleModel) => void;
  disabled: boolean;
  /** id of the example currently on screen, if any. */
  activeId: string | null;
}

export function ExampleModels({ onSelect, disabled, activeId }: ExampleModelsProps) {
  return (
    <div className="mt-6 border-t border-hairline pt-5">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
        <span className="text-xs font-medium uppercase tracking-wider text-zinc-600">
          Or view an example
        </span>

        <ul className="flex flex-wrap items-center gap-2">
          {EXAMPLE_MODELS.map((example) => {
            const isActive = activeId === example.id;
            return (
              <li key={example.id}>
                <button
                  type="button"
                  onClick={() => onSelect(example)}
                  disabled={disabled}
                  aria-pressed={isActive}
                  aria-label={`View example model: ${example.label}`}
                  className={`rounded-full border px-3 py-1.5 text-xs transition-colors disabled:cursor-not-allowed disabled:opacity-50 ${
                    isActive
                      ? "border-accent/40 bg-accent-muted text-accent"
                      : "border-hairline bg-surface text-zinc-400 hover:border-hairline-strong hover:text-zinc-200"
                  }`}
                >
                  {example.label}
                </button>
              </li>
            );
          })}
        </ul>
      </div>

      <p className="mt-2.5 text-[11px] leading-relaxed text-zinc-600">
        Pre-generated models, shown so you can try the 3D viewer without waiting
        on the AI service. They are not generated when you click.
      </p>
    </div>
  );
}
