/**
 * The frontend's view of the API. Nothing here names a model or a provider --
 * swapping Shap-E for something else must not touch the UI.
 */

export type GenerationState = "idle" | "generating" | "success" | "error";

/**
 * Where the model on screen came from.
 *
 * The distinction is load-bearing, not cosmetic: the UI must never let a
 * pre-generated example read as a fresh AI result.
 */
export type ModelSource = "generated" | "example";

/** A model ready to hand to the viewer, from either source. */
export interface GeneratedModel {
  source: ModelSource;
  /** Absolute URL the viewer loads the GLB from. */
  modelUrl: string;
  /** Absolute URL that returns the GLB as a download. */
  downloadUrl: string;
  /** Sanitized filename, e.g. formly-cyberpunk-helmet.glb */
  filename: string;
  format: string;
  prompt: string;
  provider: string;
  /** Measured provider latency in seconds. */
  generationSeconds: number;
  vertexCount: number;
  triangleCount: number;
  byteSize: number;
}

/** Distinguishes failures so the UI can use the right wording. */
export type ApiErrorKind =
  | "validation"
  | "network"
  | "generation"
  | "rate_limit"
  /** Upstream free GPU capacity is exhausted. Distinct from a generic
   *  failure because it is temporary and not the user's fault. */
  | "quota";

export class ApiError extends Error {
  readonly kind: ApiErrorKind;

  constructor(message: string, kind: ApiErrorKind) {
    super(message);
    this.name = "ApiError";
    this.kind = kind;
  }
}
