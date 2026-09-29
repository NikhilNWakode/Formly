"use client";

import dynamic from "next/dynamic";
import { useCallback, useRef, useState } from "react";

import { EmptyState } from "@/components/EmptyState";
import { ExampleModels } from "@/components/ExampleModels";
import { ExamplePrompts } from "@/components/ExamplePrompts";
import {
  AssetLoadingState,
  ErrorState,
  GeneratingState,
} from "@/components/GenerationState";
import { PROMPT_MAX_LENGTH, PromptInput } from "@/components/PromptInput";
import { ViewerControls } from "@/components/ViewerControls";
import type { ModelViewerHandle } from "@/components/ModelViewer";
import { generateModel } from "@/lib/api";
import { type ExampleModel, exampleIdForUrl, toModel } from "@/lib/examples";
import { ApiError, type ApiErrorKind, type GeneratedModel, type GenerationState } from "@/lib/types";

/**
 * three.js + R3F is ~600KB of JS that is useless until a model exists, so the
 * viewer is loaded on demand rather than in the initial bundle.
 */
const ModelViewer = dynamic(
  () => import("@/components/ModelViewer").then((m) => m.ModelViewer),
  { ssr: false },
);

interface ErrorInfo {
  kind: ApiErrorKind;
  message: string;
}

export default function Home() {
  const [prompt, setPrompt] = useState("");
  const [state, setState] = useState<GenerationState>("idle");
  const [model, setModel] = useState<GeneratedModel | null>(null);
  const [error, setError] = useState<ErrorInfo | null>(null);
  const [hint, setHint] = useState<string | null>(null);
  const [assetLoading, setAssetLoading] = useState(false);
  const [isFullscreen, setIsFullscreen] = useState(false);

  const viewerRef = useRef<ModelViewerHandle>(null);
  const shellRef = useRef<HTMLDivElement>(null);

  const isGenerating = state === "generating";

  const handleGenerate = useCallback(async () => {
    const trimmed = prompt.trim();

    // Mirror the server's rules so obvious mistakes never cost a round trip.
    if (!trimmed) {
      setHint("Please describe the object you want to create.");
      return;
    }
    if (trimmed.length < 3) {
      setHint("Please use at least 3 characters.");
      return;
    }
    if (trimmed.length > PROMPT_MAX_LENGTH) {
      setHint(`Please keep it under ${PROMPT_MAX_LENGTH} characters.`);
      return;
    }

    setHint(null);
    setError(null);
    setState("generating");

    try {
      const result = await generateModel(trimmed);
      setModel(result);
      setAssetLoading(true);
      setState("success");
    } catch (cause) {
      const apiError =
        cause instanceof ApiError
          ? cause
          : new ApiError("Something went wrong. Please try again.", "generation");

      setError({ kind: apiError.kind, message: apiError.message });
      // Key behaviour: a failed retry must not destroy a model the user
      // already has. Keep `model` and fall back to "success" so it stays
      // rendered, with the error shown as a banner beneath it.
      setState(model ? "success" : "error");
    }
  }, [prompt, model]);

  const handleSelectExample = useCallback((example: string) => {
    setPrompt(example);
    setHint(null);
  }, []);

  /**
   * Show a pre-generated model. Deliberately does not call the generation API:
   * examples exist precisely for when that service is unavailable.
   */
  const handleSelectExampleModel = useCallback((example: ExampleModel) => {
    setError(null);
    setHint(null);
    setModel(toModel(example));
    setAssetLoading(true);
    setState("success");
  }, []);

  const handleReset = useCallback(() => {
    viewerRef.current?.resetView();
  }, []);

  const handleViewerError = useCallback(() => {
    setAssetLoading(false);
    setError({
      kind: "generation",
      message: "The generated model could not be loaded.",
    });
    setModel(null);
    setState("error");
  }, []);

  const handleToggleFullscreen = useCallback(async () => {
    const element = shellRef.current;
    if (!element) return;

    try {
      if (document.fullscreenElement) {
        await document.exitFullscreen();
        setIsFullscreen(false);
      } else {
        await element.requestFullscreen();
        setIsFullscreen(true);
      }
    } catch {
      // Fullscreen can be blocked by permissions policy; the viewer still works.
      setIsFullscreen(Boolean(document.fullscreenElement));
    }
  }, []);

  const showErrorBanner = error && model && state === "success";

  return (
    <main className="mx-auto flex min-h-screen w-full max-w-3xl flex-col px-5 py-14 sm:px-6 sm:py-20">
      <header className="animate-fade-up">
        <h1 className="text-[13px] font-semibold uppercase tracking-[0.2em] text-zinc-400">
          Formly
        </h1>
        <p className="mt-5 text-3xl font-semibold tracking-tight text-white sm:text-4xl">
          Turn words into 3D.
        </p>
        <p className="mt-2.5 text-sm leading-relaxed text-zinc-500">
          Describe an object and bring it to life.
        </p>
      </header>

      <section className="mt-9 animate-fade-up">
        <PromptInput
          value={prompt}
          onChange={setPrompt}
          onSubmit={handleGenerate}
          disabled={isGenerating}
          hint={hint}
        />
        <ExamplePrompts
          onSelect={handleSelectExample}
          disabled={isGenerating}
          activePrompt={prompt}
        />
        <ExampleModels
          onSelect={handleSelectExampleModel}
          disabled={isGenerating}
          activeId={model?.source === "example" ? exampleIdForUrl(model.modelUrl) : null}
        />
      </section>

      <section className="mt-10 animate-fade-up">
        <div
          ref={shellRef}
          className="relative aspect-[4/3] w-full overflow-hidden rounded-xl border border-hairline bg-surface shadow-panel sm:aspect-[16/10]"
        >
          {state === "idle" && <EmptyState />}

          {isGenerating && <GeneratingState />}

          {state === "error" && error && (
            <ErrorState
              kind={error.kind}
              message={error.message}
              onRetry={handleGenerate}
            />
          )}

          {state === "success" && model && (
            <>
              {assetLoading && <AssetLoadingState />}
              {/*
                Provenance is stated on the model itself, not just in the
                controls below, so an example can never be mistaken for a
                fresh AI result at a glance.
              */}
              <span
                className={`pointer-events-none absolute left-3 top-3 z-10 rounded-full border px-2.5 py-1 text-[10px] font-medium uppercase tracking-wider ${
                  model.source === "example"
                    ? "border-hairline-strong bg-surface/80 text-zinc-400"
                    : "border-accent/30 bg-accent-muted text-accent"
                }`}
              >
                {model.source === "example" ? "Example model" : "Generated with AI"}
              </span>
              <ModelViewer
                key={model.modelUrl}
                ref={viewerRef}
                url={model.modelUrl}
                onLoaded={() => setAssetLoading(false)}
                onError={handleViewerError}
              />
            </>
          )}
        </div>

        {state === "success" && model && (
          <ViewerControls
            model={model}
            onReset={handleReset}
            onToggleFullscreen={handleToggleFullscreen}
            isFullscreen={isFullscreen}
            disabled={assetLoading}
          />
        )}

        {showErrorBanner && (
          <ErrorState
            kind={error.kind}
            message={error.message}
            onRetry={handleGenerate}
            compact
          />
        )}

        {state === "success" && model && (
          <p className="mt-4 truncate text-xs text-zinc-600" title={model.prompt}>
            {model.prompt}
          </p>
        )}
      </section>

      <footer className="mt-auto pt-14 text-[11px] text-zinc-700">
        <p>
          Drag to rotate, scroll to zoom, right-click to pan. Models are generated on
          demand and are not stored.
        </p>
      </footer>
    </main>
  );
}
