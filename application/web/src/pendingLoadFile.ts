import type { LoadedFile } from "./hooks/useFileUpload";

const STORAGE_KEY = "ess:pending-load-file";
export const ESS_ATTACH_FILE_EVENT = "ess:attach-file";

function normalize(raw: unknown): LoadedFile | null {
  if (!raw || typeof raw !== "object") return null;
  const item = raw as Partial<LoadedFile>;
  const path = String(item.path || "").trim();
  const name = String(item.name || "").trim();
  if (!path || !name) return null;
  const size = Number(item.size);
  return {
    path,
    name,
    size: Number.isFinite(size) && size > 0 ? size : 0,
  };
}

/** Notify ChatInput to attach a file chip immediately. */
export function dispatchAttachFile(file: LoadedFile): void {
  const normalized = normalize(file);
  if (!normalized) return;
  window.dispatchEvent(
    new CustomEvent(ESS_ATTACH_FILE_EVENT, { detail: normalized }),
  );
}

/** Stage an ESS markdown path so Load files can attach it without a file picker. */
export function stagePendingLoadFile(file: LoadedFile): void {
  const normalized = normalize(file);
  if (!normalized) return;
  try {
    sessionStorage.setItem(STORAGE_KEY, JSON.stringify(normalized));
  } catch {
    // Ignore quota / private-mode failures; clipboard copy still works.
  }
}

/**
 * Document List 「복사」: stage for Load files, attach chip immediately, copy CloudFront URL.
 */
export function copyDocumentForChat(file: LoadedFile): void {
  const normalized = normalize(file);
  if (!normalized) return;
  stagePendingLoadFile(normalized);
  dispatchAttachFile(normalized);
}

/** Read a staged path without clearing it (for menu hints). */
export function peekPendingLoadFile(): LoadedFile | null {
  try {
    const raw = sessionStorage.getItem(STORAGE_KEY);
    if (!raw) return null;
    return normalize(JSON.parse(raw));
  } catch {
    return null;
  }
}

/** Consume a staged ESS markdown path for Load files attachment. */
export function consumePendingLoadFile(): LoadedFile | null {
  try {
    const raw = sessionStorage.getItem(STORAGE_KEY);
    if (!raw) return null;
    sessionStorage.removeItem(STORAGE_KEY);
    return normalize(JSON.parse(raw));
  } catch {
    try {
      sessionStorage.removeItem(STORAGE_KEY);
    } catch {
      // ignore
    }
    return null;
  }
}
