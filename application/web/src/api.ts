import type { AppConfig, DashboardStats, Message, StreamEvent, Task } from "./types";
import { uiError, uiLog } from "./debug";

export interface RagUploadResult {
  ok: boolean;
  file_name: string;
  s3_key: string;
  url?: string | null;
  message: string;
  sync?: {
    ingestion_job_id?: string;
    status?: string;
  };
}

export interface RagUploadPresignResult {
  ok: boolean;
  file_name: string;
  s3_key: string;
  content_type?: string;
  upload_url: string;
  headers: Record<string, string>;
  expires_in?: number;
  url?: string | null;
}

export interface FileUploadResult {
  ok: boolean;
  file_name: string;
  s3_key: string;
  url: string;
  content_type?: string;
}

export interface LoadFileResult {
  ok: boolean;
  file_name: string;
  s3_key: string;
  workspace_path: string;
  content_type?: string;
  mount_ready?: boolean;
}

export interface LoadFilePresignResult {
  ok: boolean;
  file_name: string;
  s3_key: string;
  workspace_path: string;
  content_type?: string;
  upload_url: string;
  headers: Record<string, string>;
  expires_in?: number;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const method = init?.method ?? "GET";
  uiLog(`api:${method} ${path}`);
  const res = await fetch(path, {
    credentials: "include",
    headers: {
      "Content-Type": "application/json",
      ...(init?.headers ?? {}),
    },
    ...init,
  });
  if (!res.ok) {
    const text = await res.text();
    uiError(`api:${method} ${path} failed`, { status: res.status, body: text });
    let message = text || res.statusText;
    try {
      const parsed = JSON.parse(text) as { detail?: string | { msg?: string }[] };
      if (typeof parsed.detail === "string" && parsed.detail) {
        message = parsed.detail;
      }
    } catch {
      // keep raw text
    }
    throw new Error(message);
  }
  if (res.status === 204) {
    uiLog(`api:${method} ${path} -> 204`);
    return undefined as T;
  }
  const text = await res.text();
  if (!text) {
    uiLog(`api:${method} ${path} -> empty`);
    return undefined as T;
  }
  const data = JSON.parse(text) as T;
  uiLog(`api:${method} ${path} -> ok`);
  return data;
}

export interface GraphStatus {
  user_id: string;
  exists: boolean;
  path: string | null;
  status: "idle" | "queued" | "running" | "ready" | "error" | "skipped_cooldown" | "disabled" | string;
  enabled?: boolean;
  error?: string | null;
  last_success_at?: string | null;
  cooldown_seconds?: number;
  next_eligible_at?: string | null;
}

export interface EssStatus {
  ess_dir: string;
  docs_dir?: string;
  raw_dir?: string;
  files?: Array<{ name: string; path: string; bytes: number; mtime?: number }>;
  documents?: Array<Record<string, unknown>>;
  doc_count?: number;
  doc_list?: string;
  exists?: boolean;
  status: "idle" | "queued" | "running" | "ready" | "error" | "unchanged" | string;
  foundation_model_parser_enabled?: boolean;
  error?: string | null;
  message?: string | null;
  last_success_at?: string | null;
  progress?: {
    file?: string | null;
    file_i?: number | null;
    file_n?: number | null;
    page?: number | null;
    page_n?: number | null;
    pct?: number | null;
  } | null;
}

export interface EssConfig {
  ess_dir: string;
  docs_dir?: string;
  raw_dir?: string;
  files?: Array<{ name: string; path: string; bytes: number; mtime?: number }>;
  documents?: Array<Record<string, unknown>>;
  doc_count?: number;
  foundation_model_parser_enabled?: boolean;
}

export interface EssDocument {
  filename?: string;
  original_filename?: string;
  display_name?: string;
  md_file?: string;
  md_path?: string;
  source_path?: string;
  status?: string;
  bytes?: number;
  pdf_available?: boolean;
  md_available?: boolean;
  pdf_url?: string | null;
  pdf_api_url?: string | null;
  md_url?: string | null;
  md_viewer_url?: string | null;
  md_published?: boolean;
}

export interface EssDocListResult {
  ess_dir: string;
  docs_dir?: string;
  documents: EssDocument[];
  doc_count?: number;
  doc_list?: string;
  doc_list_updated_at?: string | null;
  sharing_url?: string | null;
}

export interface EssDocsPresignResult {
  ok?: boolean;
  file_name: string;
  original_filename?: string;
  sanitized?: boolean;
  s3_key: string;
  content_type?: string;
  upload_url: string;
  headers?: Record<string, string>;
  expires_in?: number;
  docs_dir?: string;
}

export interface EssRawUploadResult {
  ess_dir: string;
  docs_dir?: string;
  raw_dir: string;
  saved: {
    name: string;
    original_filename?: string;
    sanitized?: boolean;
    path: string;
    bytes: number;
    overwritten?: boolean;
  };
  count: number;
  files?: Array<{ name: string; path: string; bytes: number; mtime?: number }>;
  documents?: Array<Record<string, unknown>>;
  doc_count?: number;
  s3_key?: string;
}

export type GraphPattern = "pattern1" | "pattern2" | "pattern3";

export interface SessionInfo {
  user_id: string;
  name?: string | null;
  picture?: string | null;
  knowledge_graph_enabled?: boolean;
  graph_pattern?: GraphPattern | string;
}

export const api = {
  getSession: () => request<SessionInfo | null>("/api/session"),
  setSession: (credential: string) =>
    request<SessionInfo>("/api/session", {
      method: "POST",
      body: JSON.stringify({ credential }),
    }),
  setSessionWithAccessToken: (access_token: string) =>
    request<SessionInfo>("/api/session", {
      method: "POST",
      body: JSON.stringify({ access_token }),
    }),
  setLocalSession: (user_id: string) =>
    request<SessionInfo>("/api/session", {
      method: "POST",
      body: JSON.stringify({ user_id }),
    }),
  clearSession: () => request<void>("/api/session", { method: "DELETE" }),
  patchSessionSettings: (body: {
    knowledge_graph_enabled?: boolean;
    graph_pattern?: GraphPattern | string;
  }) =>
    request<SessionInfo>("/api/session/settings", {
      method: "PATCH",
      body: JSON.stringify(body),
    }),
  getGraphStatus: () => request<GraphStatus>("/api/graph/status"),
  rebuildGraph: (force = false) =>
    request<GraphStatus>(`/api/graph/rebuild${force ? "?force=1" : ""}`, {
      method: "POST",
    }),
  getEssStatus: () => request<EssStatus>("/api/ess/status"),
  getEssConfig: () => request<EssConfig>("/api/ess/config"),
  getEssDocList: (publishMd = true) =>
    request<EssDocListResult>(
      `/api/ess/doc-list${publishMd ? "" : "?publish_md=0"}`,
    ),
  putEssConfig: (body: { foundation_model_parser_enabled?: boolean }) =>
    request<EssConfig>("/api/ess/config", {
      method: "PUT",
      body: JSON.stringify(body),
    }),
  uploadEssRawFile: async (file: File): Promise<EssRawUploadResult> => {
    // Presigned PUT: browser → S3 directly (avoids ECS/ALB ~80MB body limits).
    uiLog("ess:upload start", { name: file.name, size: file.size });

    const presign = await request<EssDocsPresignResult>("/api/ess/docs/presign", {
      method: "POST",
      body: JSON.stringify({
        file_name: file.name,
        size: file.size,
        content_type: file.type || undefined,
      }),
    });
    if (!presign.upload_url || !presign.s3_key) {
      throw new Error("Presign succeeded but no upload URL was returned");
    }

    uiLog("ess:upload put start", {
      name: presign.file_name,
      s3_key: presign.s3_key,
      size: file.size,
      host: (() => {
        try {
          return new URL(presign.upload_url).host;
        } catch {
          return "";
        }
      })(),
    });

    const putHeaders = new Headers(presign.headers || {});
    if (!putHeaders.has("Content-Type")) {
      putHeaders.set(
        "Content-Type",
        presign.content_type || "application/octet-stream",
      );
    }
    let putRes: Response;
    try {
      putRes = await fetch(presign.upload_url, {
        method: "PUT",
        body: file,
        headers: putHeaders,
      });
    } catch (err) {
      const detail = err instanceof Error ? err.message : String(err);
      uiError("ess:upload put network error", { detail });
      throw new Error(`S3 직접 업로드 네트워크 오류: ${detail}`);
    }
    if (!putRes.ok) {
      const text = await putRes.text();
      uiError("ess:upload put failed", { status: putRes.status, body: text });
      const codeMatch = text.match(/<Code>([^<]+)<\/Code>/i);
      const msgMatch = text.match(/<Message>([^<]+)<\/Message>/i);
      const s3Detail =
        codeMatch || msgMatch
          ? [codeMatch?.[1], msgMatch?.[1]].filter(Boolean).join(": ")
          : "";
      throw new Error(
        s3Detail ||
          text.slice(0, 200) ||
          putRes.statusText ||
          `Direct S3 upload failed (HTTP ${putRes.status})`,
      );
    }

    const data = await request<EssRawUploadResult>("/api/ess/docs/complete", {
      method: "POST",
      body: JSON.stringify({
        file_name: presign.file_name,
        s3_key: presign.s3_key,
        size: file.size,
        original_filename: presign.original_filename || file.name,
      }),
    });
    uiLog("ess:upload ok", { name: data.saved?.name, s3_key: data.s3_key });
    return data;
  },
  syncEss: (full = false, model?: string) => {
    const params = new URLSearchParams();
    if (full) params.set("full", "1");
    if (model?.trim()) params.set("model", model.trim());
    const qs = params.toString();
    return request<EssStatus>(`/api/ess/sync${qs ? `?${qs}` : ""}`, {
      method: "POST",
    });
  },
  getConfig: () => request<AppConfig>("/api/config"),
  getAdminDashboard: () => request<DashboardStats>("/api/admin/dashboard"),
  listTasks: () => request<{ tasks: Task[] }>("/api/tasks"),
  createTask: (body: Partial<Task>) =>
    request<Task>("/api/tasks", {
      method: "POST",
      body: JSON.stringify(body),
    }),
  getTask: (id: string) => request<Task>(`/api/tasks/${id}`),
  patchTask: (id: string, body: Partial<Task>) =>
    request<Task>(`/api/tasks/${id}`, {
      method: "PATCH",
      body: JSON.stringify(body),
    }),
  deleteTask: (id: string) =>
    request<{ ok: boolean }>(`/api/tasks/${id}`, { method: "DELETE" }),
  getMessages: (id: string) =>
    request<{ messages: Message[] }>(`/api/tasks/${id}/messages`),
  uploadToRag: async (
    file: File,
    options?: { sync?: boolean },
  ): Promise<RagUploadResult> => {
    // Presigned PUT: browser → S3 directly (avoids ECS/ALB ~80MB body limits).
    const sync = options?.sync !== false;
    uiLog("rag:upload start", { name: file.name, size: file.size, sync });

    const presign = await request<RagUploadPresignResult>("/api/rag/upload/presign", {
      method: "POST",
      body: JSON.stringify({
        file_name: file.name,
        size: file.size,
        content_type: file.type || undefined,
      }),
    });
    if (!presign.upload_url || !presign.s3_key) {
      throw new Error("Presign succeeded but no upload URL was returned");
    }

    uiLog("rag:upload put start", {
      name: presign.file_name,
      s3_key: presign.s3_key,
      size: file.size,
      host: (() => {
        try {
          return new URL(presign.upload_url).host;
        } catch {
          return "";
        }
      })(),
    });

    const putHeaders = new Headers(presign.headers || {});
    if (!putHeaders.has("Content-Type")) {
      putHeaders.set(
        "Content-Type",
        presign.content_type || "application/octet-stream",
      );
    }
    let putRes: Response;
    try {
      putRes = await fetch(presign.upload_url, {
        method: "PUT",
        body: file,
        headers: putHeaders,
      });
    } catch (err) {
      const detail = err instanceof Error ? err.message : String(err);
      uiError("rag:upload put network error", { detail });
      throw new Error(`S3 직접 업로드 네트워크 오류: ${detail}`);
    }
    if (!putRes.ok) {
      const text = await putRes.text();
      uiError("rag:upload put failed", { status: putRes.status, body: text });
      const codeMatch = text.match(/<Code>([^<]+)<\/Code>/i);
      const msgMatch = text.match(/<Message>([^<]+)<\/Message>/i);
      const s3Detail =
        codeMatch || msgMatch
          ? [codeMatch?.[1], msgMatch?.[1]].filter(Boolean).join(": ")
          : "";
      throw new Error(
        s3Detail ||
          text.slice(0, 200) ||
          putRes.statusText ||
          `Direct S3 upload failed (HTTP ${putRes.status})`,
      );
    }

    const data = await request<RagUploadResult>("/api/rag/upload/complete", {
      method: "POST",
      body: JSON.stringify({
        file_name: presign.file_name,
        s3_key: presign.s3_key,
        size: file.size,
        sync,
      }),
    });
    uiLog("rag:upload complete", data);
    return data;
  },
  uploadFile: async (file: File): Promise<FileUploadResult> => {
    uiLog("file:upload start", { name: file.name, size: file.size, type: file.type });
    const form = new FormData();
    form.append("file", file);
    const res = await fetch("/api/files/upload", {
      method: "POST",
      credentials: "include",
      body: form,
    });
    if (!res.ok) {
      const text = await res.text();
      uiError("file:upload failed", { status: res.status, body: text });
      throw new Error(text || res.statusText);
    }
    const data = (await res.json()) as FileUploadResult;
    if (!data.url) {
      throw new Error("Upload succeeded but no URL was returned");
    }
    uiLog("file:upload complete", data);
    return data;
  },
  loadFile: async (file: File): Promise<LoadFileResult> => {
    // Presigned PUT: browser → S3 directly (avoids ECS/ALB ~80MB body limits).
    uiLog("file:load start", { name: file.name, size: file.size, type: file.type });

    const presign = await request<LoadFilePresignResult>("/api/files/load/presign", {
      method: "POST",
      body: JSON.stringify({
        file_name: file.name,
        size: file.size,
        content_type: file.type || undefined,
      }),
    });
    if (!presign.upload_url || !presign.s3_key) {
      throw new Error("Presign succeeded but no upload URL was returned");
    }

    uiLog("file:load put start", {
      name: presign.file_name,
      s3_key: presign.s3_key,
      size: file.size,
    });
    const putHeaders = new Headers(presign.headers || {});
    if (!putHeaders.has("Content-Type")) {
      putHeaders.set("Content-Type", presign.content_type || "application/octet-stream");
    }
    const putRes = await fetch(presign.upload_url, {
      method: "PUT",
      body: file,
      headers: putHeaders,
    });
    if (!putRes.ok) {
      const text = await putRes.text();
      uiError("file:load put failed", { status: putRes.status, body: text });
      throw new Error(text || putRes.statusText || "Direct S3 upload failed");
    }

    const data = await request<LoadFileResult>("/api/files/load/complete", {
      method: "POST",
      body: JSON.stringify({
        file_name: presign.file_name,
        s3_key: presign.s3_key,
        size: file.size,
      }),
    });
    if (!data.workspace_path) {
      throw new Error("Load succeeded but no workspace path was returned");
    }
    uiLog("file:load complete", data);
    return data;
  },
  streamChat: async function* (
    taskId: string,
    prompt: string,
    files: string[] = [],
    signal?: AbortSignal,
  ): AsyncGenerator<StreamEvent> {
    uiLog("chat:stream start", { taskId, prompt, files });
    const res = await fetch(`/api/tasks/${taskId}/chat`, {
      method: "POST",
      credentials: "include",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ prompt, files }),
      signal,
    });
    if (!res.ok || !res.body) {
      const body = await res.text();
      uiError("chat:stream request failed", { status: res.status, body });
      throw new Error("Chat request failed. Please try again.");
    }

    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    let eventCount = 0;

    try {
      while (true) {
        if (signal?.aborted) {
          throw new DOMException("Aborted", "AbortError");
        }
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const parts = buffer.split("\n\n");
        buffer = parts.pop() ?? "";
        for (const part of parts) {
          const line = part
            .split("\n")
            .find((l) => l.startsWith("data:"));
          if (!line) continue;
          const payload = line.slice(5).trim();
          if (!payload) continue;
          const event = JSON.parse(payload) as StreamEvent;
          eventCount += 1;
          if (event.type === "token") {
            const text = event.data ?? "";
            uiLog("chat:sse token", { chars: text.length, preview: text.slice(0, 80) });
          } else if (event.type === "error") {
            uiError("chat:sse error", event);
          } else {
            uiLog(`chat:sse ${event.type}`, event);
          }
          yield event;
        }
      }
    } catch (err) {
      try {
        await reader.cancel();
      } catch {
        /* ignore cancel errors */
      }
      throw err;
    }

    uiLog("chat:stream end", { taskId, eventCount });
  },
};
