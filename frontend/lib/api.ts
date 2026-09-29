import { ApiError, type GeneratedModel } from "./types";

/**
 * Single place that knows the backend exists. Components call `generateModel`
 * and get either a `GeneratedModel` or a typed `ApiError`.
 */

const API_BASE_URL = (
  process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000"
).replace(/\/+$/, "");

/** Generation is slow by nature; fail before the browser's own limits bite. */
const REQUEST_TIMEOUT_MS = 300_000;

interface GenerateResponseBody {
  success: boolean;
  model_url: string;
  download_url: string;
  filename: string;
  format: string;
  prompt: string;
  provider: string;
  generation_seconds: number;
  vertex_count: number;
  triangle_count: number;
  byte_size: number;
}

export function absoluteUrl(path: string): string {
  return path.startsWith("http") ? path : `${API_BASE_URL}${path}`;
}

/** Matches the backend's public wording for upstream quota exhaustion. */
const QUOTA_MESSAGE_PATTERN = /busy right now|capacity|quota/i;

function errorKindForStatus(status: number): ApiError["kind"] {
  if (status === 422 || status === 400) return "validation";
  if (status === 429) return "rate_limit";
  return "generation";
}

export async function generateModel(
  prompt: string,
  options: { signal?: AbortSignal } = {},
): Promise<GeneratedModel> {
  // Combine the caller's signal with our own timeout so either can abort.
  const timeoutController = new AbortController();
  const timer = setTimeout(() => timeoutController.abort(), REQUEST_TIMEOUT_MS);

  const onCallerAbort = () => timeoutController.abort();
  options.signal?.addEventListener("abort", onCallerAbort);

  let response: Response;
  try {
    response = await fetch(`${API_BASE_URL}/api/generate`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ prompt }),
      signal: timeoutController.signal,
    });
  } catch (cause) {
    // A caller-initiated abort is not an error the UI should report.
    if (options.signal?.aborted) throw cause;
    // Complements the "network" title rather than repeating it -- the two are
    // shown together, so identical strings read as a rendering bug.
    throw new ApiError(
      "Couldn't reach the server. Check your connection and try again.",
      "network",
    );
  } finally {
    clearTimeout(timer);
    options.signal?.removeEventListener("abort", onCallerAbort);
  }

  let body: Partial<GenerateResponseBody> & { error?: string };
  try {
    body = await response.json();
  } catch {
    throw new ApiError("The generation service returned an unreadable response.", "generation");
  }

  if (!response.ok || !body.success) {
    const message = body.error ?? "We couldn't generate this model.";

    // The backend reports exhausted upstream GPU capacity as a 502 with this
    // exact public message. It is worth separating from a generic failure:
    // nothing is broken and retrying later genuinely works.
    if (QUOTA_MESSAGE_PATTERN.test(message)) {
      throw new ApiError(
        "The free AI inference service has reached its current capacity. Please try again later.",
        "quota",
      );
    }

    throw new ApiError(message, errorKindForStatus(response.status));
  }

  const data = body as GenerateResponseBody;
  return {
    source: "generated",
    modelUrl: absoluteUrl(data.model_url),
    downloadUrl: absoluteUrl(data.download_url),
    filename: data.filename,
    format: data.format,
    prompt: data.prompt,
    provider: data.provider,
    generationSeconds: data.generation_seconds,
    vertexCount: data.vertex_count,
    triangleCount: data.triangle_count,
    byteSize: data.byte_size,
  };
}
