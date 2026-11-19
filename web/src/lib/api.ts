import type { components } from "./api.generated";

export type Project = components["schemas"]["ProjectView"];
export type Output = components["schemas"]["Output"];
type DetailSchema = components["schemas"]["OutputDetail"];
// IDs are assigned before persistence. SQLModel also uses these schemas for construction,
// so OpenAPI marks factory defaults as optional; persisted API responses always include IDs.
export type Detail = Omit<DetailSchema, "chapters" | "beats"> & {
  chapters: (DetailSchema["chapters"][number] & { id: string })[];
  beats: (DetailSchema["beats"][number] & { id: string })[];
};
export type Clip = components["schemas"]["ClipView"];
export type Transcript = components["schemas"]["Transcript"];
export type Settings = components["schemas"]["OutputSettings"];
export type OutputPreferences = Omit<components["schemas"]["OutputPreferences"], "clips" | "condense"> & { clips: Settings; condense: Settings };
export type RuntimeConfig = { provider: string; model: string; live_configured: boolean; max_upload_bytes: number; render_height: number };
export type AnnotationRange = components["schemas"]["AnnotationRange"];
export type AnnotationDocument = Omit<components["schemas"]["AnnotationDocument"], "ranges" | "required_chapters" | "required_specs" | "settings"> & {
  ranges: AnnotationRange[]; required_chapters: AnnotationRange[]; required_specs: AnnotationRange[]; settings: Settings;
};
export type AnnotationView = Omit<components["schemas"]["AnnotationView"], "document"> & { document: AnnotationDocument };

export async function api<T>(path: string, init: RequestInit = {}): Promise<T> {
  const response = await fetch(`/api${path}`, { ...init, cache: "no-store", headers: { ...(init.body ? { "Content-Type": "application/json" } : {}), ...init.headers } });
  if (!response.ok) {
    const data = await response.json().catch(() => ({ detail: `HTTP ${response.status}` }));
    const detail = data.detail;
    throw new Error(typeof detail === "string" ? detail : detail?.message ?? JSON.stringify(detail));
  }
  return response.json() as Promise<T>;
}

export const post = <T>(path: string, body: unknown = {}) => api<T>(path, { method: "POST", body: JSON.stringify(body) });
export const patch = <T>(path: string, body: unknown) => api<T>(path, { method: "PATCH", body: JSON.stringify(body) });

export async function uploadVideo(file: File, onProgress: (percent: number) => void): Promise<string> {
  const storageKey = `cuplik-upload:${file.name}:${file.size}:${file.lastModified}`;
  let id = localStorage.getItem(storageKey);
  let state: { id: string; offset: number; chunk_bytes: number; complete: boolean };
  if (id) {
    try { state = await api(`/uploads/${id}`); }
    catch { id = null; }
  }
  if (!id) {
    state = await post("/uploads", { filename: file.name, total_bytes: file.size });
    id = state.id;
    localStorage.setItem(storageKey, id);
  }
  state = await api(`/uploads/${id}`);
  while (state.offset < file.size) {
    const response = await fetch(`/api/uploads/${id}?offset=${state.offset}`, { method: "PUT", headers: { "Content-Type": "application/octet-stream" }, body: file.slice(state.offset, state.offset + state.chunk_bytes) });
    if (response.status === 409) { state = await api(`/uploads/${id}`); continue; }
    if (!response.ok) {
      const error = await response.json();
      throw new Error(typeof error.detail === "string" ? error.detail : JSON.stringify(error.detail));
    }
    const updated = await response.json();
    state = { ...state, ...updated };
    onProgress(Math.round(state.offset / file.size * 100));
  }
  if (!state.complete) state = { ...state, ...await post<{ complete: boolean; offset: number }>(`/uploads/${id}/complete`) };
  return id!;
}
