import type { GeneratedModel } from "./types";

/**
 * Pre-generated example models.
 *
 * These are **not** produced at request time. Each file was generated earlier
 * with the same Shap-E provider the live app uses, then committed so the 3D
 * experience still works when the free ZeroGPU quota is exhausted. Selecting
 * one never calls the generation API.
 *
 * They are deliberately real Shap-E output rather than hand-modelled meshes:
 * an example should show what this product actually produces, blobby vertex
 * colours included. A crisp hand-made asset here would flatter the model.
 *
 * Served as static files from `public/examples`, so they cost nothing on the
 * backend and are fetched only when a user picks one -- they are not part of
 * the initial page load.
 */

export interface ExampleModel {
  id: string;
  /** Button label. */
  label: string;
  /** The prompt this asset was originally generated from. */
  prompt: string;
  /** Static path, same-origin. */
  file: string;
  triangleCount: number;
  byteSize: number;
}

export const EXAMPLE_MODELS: ExampleModel[] = [
  {
    id: "japanese-pagoda",
    label: "Japanese Pagoda",
    prompt: "A small Japanese pagoda",
    file: "/examples/japanese-pagoda.glb",
    triangleCount: 115712,
    byteSize: 2315368,
  },
  {
    id: "cyberpunk-helmet",
    label: "Cyberpunk Helmet",
    prompt: "A futuristic cyberpunk helmet",
    file: "/examples/cyberpunk-helmet.glb",
    triangleCount: 214268,
    byteSize: 4285948,
  },
];

/** Which example is on screen, derived from its url so no extra state is needed. */
export function exampleIdForUrl(url: string): string | null {
  return EXAMPLE_MODELS.find((example) => example.file === url)?.id ?? null;
}

/**
 * Adapt an example into the same shape the viewer already consumes, so the
 * viewer, controls and download path stay identical for both sources.
 *
 * `generationSeconds` is 0 because nothing was generated: the UI shows a
 * "pre-generated" note for examples rather than a fabricated timing.
 */
export function toModel(example: ExampleModel): GeneratedModel {
  return {
    source: "example",
    modelUrl: example.file,
    downloadUrl: example.file,
    // The filename makes the provenance obvious on disk, not just in the UI.
    filename: `formly-example-${example.id}.glb`,
    format: "glb",
    prompt: example.prompt,
    provider: "pre-generated",
    generationSeconds: 0,
    vertexCount: 0,
    triangleCount: example.triangleCount,
    byteSize: example.byteSize,
  };
}
