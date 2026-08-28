import { useEffect } from "react";
import { createPortal } from "react-dom";

export interface SyncProgressInfo {
  file?: string | null;
  file_i?: number | null;
  file_n?: number | null;
  page?: number | null;
  page_n?: number | null;
  pct?: number | null;
  aggregated?: boolean | null;
}

interface Props {
  title: string;
  busy: boolean;
  message: string | null;
  progress?: SyncProgressInfo | null;
  onClose: () => void;
}

export function SyncProgressModal({
  title,
  busy,
  message,
  progress,
  onClose,
}: Props) {
  useEffect(() => {
    function onKeyDown(e: KeyboardEvent) {
      if (e.key === "Escape" && !busy) onClose();
    }
    window.addEventListener("keydown", onKeyDown);
    const prev = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      window.removeEventListener("keydown", onKeyDown);
      document.body.style.overflow = prev;
    };
  }, [busy, onClose]);

  useEffect(() => {
    if (busy) return;
    const timer = window.setTimeout(() => onClose(), 4000);
    return () => window.clearTimeout(timer);
  }, [busy, message, onClose]);

  const fileName = progress?.file?.trim() || null;
  const pct =
    typeof progress?.pct === "number" && Number.isFinite(progress.pct)
      ? Math.max(0, Math.min(100, Math.round(progress.pct)))
      : null;
  const pageLabel =
    typeof progress?.page === "number" &&
    typeof progress?.page_n === "number" &&
    progress.page_n > 0
      ? progress.aggregated
        ? `완료 ${progress.page}/${progress.page_n} 페이지`
        : `페이지 ${progress.page}/${progress.page_n}`
      : null;
  const fileLabel =
    typeof progress?.file_i === "number" &&
    typeof progress?.file_n === "number" &&
    progress.file_n > 0
      ? `파일 ${progress.file_i}/${progress.file_n}`
      : null;

  const display =
    message?.trim() ||
    (busy ? "동기화를 진행하고 있습니다…" : "동기화가 완료되었습니다.");

  return createPortal(
    <div
      className="modal-overlay sync-progress-overlay"
      role="dialog"
      aria-modal="true"
      aria-labelledby="sync-progress-title"
      aria-busy={busy}
      onMouseDown={(e) => {
        if (e.target === e.currentTarget && !busy) onClose();
      }}
    >
      <div className="sync-progress-modal">
        <div className="sync-progress-header">
          <h2 id="sync-progress-title">{title}</h2>
          {!busy && (
            <button
              type="button"
              className="sync-progress-close"
              aria-label="닫기"
              onClick={onClose}
            >
              ×
            </button>
          )}
        </div>

        <div className="sync-progress-body">
          {busy ? (
            <div className="sync-progress-spinner" aria-hidden="true" />
          ) : (
            <div className="sync-progress-done" aria-hidden="true">
              ✓
            </div>
          )}

          {fileName && (
            <p className="sync-progress-file" title={fileName}>
              {fileName}
            </p>
          )}

          {(fileLabel || pageLabel || pct !== null) && (
            <div className="sync-progress-meta">
              {fileLabel && <span>{fileLabel}</span>}
              {pageLabel && <span>{pageLabel}</span>}
              {pct !== null && <span>{pct}%</span>}
            </div>
          )}

          {busy && (fileLabel || pageLabel || pct !== null) && (
            <div
              className="sync-progress-bar"
              role="progressbar"
              aria-valuemin={0}
              aria-valuemax={100}
              aria-valuenow={pct ?? 0}
            >
              <div
                className="sync-progress-bar-fill"
                style={{ width: `${pct ?? 0}%` }}
              />
            </div>
          )}

          <p className="sync-progress-message">{display}</p>
          {busy && (
            <p className="sync-progress-hint">
              완료될 때까지 이 창을 유지하거나, 사이드바의 Syncing 표시로
              진행 상태를 확인할 수 있습니다.
            </p>
          )}
        </div>

        <div className="sync-progress-actions">
          {busy ? (
            <button
              type="button"
              className="sync-progress-btn is-secondary"
              onClick={onClose}
            >
              백그라운드로 계속
            </button>
          ) : (
            <button
              type="button"
              className="sync-progress-btn"
              onClick={onClose}
            >
              확인
            </button>
          )}
        </div>
      </div>
    </div>,
    document.body,
  );
}
