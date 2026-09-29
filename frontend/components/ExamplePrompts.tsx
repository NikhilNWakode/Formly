"use client";

/**
 * Clicking an example fills the field but deliberately does NOT generate --
 * generation costs shared GPU quota and the user may want to edit first.
 */

export const EXAMPLE_PROMPTS = [
  "A futuristic cyberpunk helmet",
  "A low-poly medieval treasure chest",
  "A stylized astronaut helmet",
  "A small Japanese pagoda",
] as const;

interface ExamplePromptsProps {
  onSelect: (prompt: string) => void;
  disabled: boolean;
  activePrompt: string;
}

export function ExamplePrompts({ onSelect, disabled, activePrompt }: ExamplePromptsProps) {
  return (
    <div className="mt-5 flex flex-wrap items-center gap-2">
      <span className="mr-1 text-xs font-medium uppercase tracking-wider text-zinc-600">Try</span>
      {EXAMPLE_PROMPTS.map((prompt) => {
        const isActive = activePrompt.trim() === prompt;
        return (
          <button
            key={prompt}
            type="button"
            onClick={() => onSelect(prompt)}
            disabled={disabled}
            className={`rounded-full border px-3 py-1.5 text-xs transition-colors disabled:cursor-not-allowed disabled:opacity-50 ${
              isActive
                ? "border-accent/40 bg-accent-muted text-accent"
                : "border-hairline bg-surface text-zinc-400 hover:border-hairline-strong hover:text-zinc-200"
            }`}
          >
            {prompt}
          </button>
        );
      })}
    </div>
  );
}
