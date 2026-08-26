import { useEffect, useState } from "react";
import { createPortal } from "react-dom";
import { api, type EssDocument } from "../api";

interface Props {
  onClose: () => void;
}

function formatBytes(bytes: number | undefined): string {
  if (bytes == null || !Number.isFinite(bytes) || bytes < 0) return "—";
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function openInNewTab(url: string) {
  window.open(url, "_blank", "noopener,noreferrer");
}

function markdownPath(doc: EssDocument): string | null {
  const path = (doc.md_path || "").trim();
  if (path) return path;
  const name = (doc.md_file || "").trim();
  return name || null;
}

export function EssDocumentListModal({ onClose }: Props) {
  const [documents, setDocuments] = useState<EssDocument[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      setLoading(true);
      setError(null);
      try {
        const data = await api.getEssDocList(true);
        if (cancelled) return;
        setDocuments(data.documents ?? []);
      } catch (err) {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : String(err));
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    function onKeyDown(e: KeyboardEvent) {
      if (e.key === "Escape") onClose();
    }
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [onClose]);

  function openMarkdown(doc: EssDocument) {
    const url = doc.md_viewer_url;
    if (!url) return;
    openInNewTab(url);
  }

  function openPdf(doc: EssDocument) {
    // Prefer API route (CloudFront redirect when object exists, else local stream).
    const url = doc.pdf_api_url || doc.pdf_url;
    if (!url) return;
    openInNewTab(url);
  }

  async function copyMarkdownPath(doc: EssDocument) {
    const path = markdownPath(doc);
    if (!path) return;
    try {
      await navigator.clipboard.writeText(path);
      onClose();
    } catch (err) {
      setError(
        err instanceof Error
          ? `경로 복사 실패: ${err.message}`
          : "경로 복사에 실패했습니다.",
      );
    }
  }

  return createPortal(
    <div
      className="modal-overlay"
      role="dialog"
      aria-modal="true"
      aria-labelledby="ess-doc-list-title"
      onMouseDown={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div className="modal ess-doc-list-modal">
        <h2 id="ess-doc-list-title">Document List</h2>
        {loading ? (
          <p className="ess-configure-muted">문서 목록을 불러오는 중…</p>
        ) : error ? (
          <p className="modal-error" role="alert">
            {error}
          </p>
        ) : documents.length === 0 ? (
          <p className="ess-configure-docs-empty">
            등록된 문서가 없습니다. Configure에서 문서를 추가한 뒤 Sync 하세요.
          </p>
        ) : (
          <ul className="ess-doc-list">
            {documents.map((doc) => {
              const key = doc.filename || doc.md_file || doc.display_name || "doc";
              const title =
                doc.display_name ||
                doc.original_filename ||
                doc.filename ||
                doc.md_file ||
                "document";
              const canMd = Boolean(doc.md_available && doc.md_viewer_url);
              const canPdf = Boolean(doc.pdf_available && (doc.pdf_api_url || doc.pdf_url));
              const mdPath = markdownPath(doc);
              const canCopy = Boolean(mdPath);
              return (
                <li key={key} className="ess-doc-list-item">
                  <div className="ess-doc-list-meta">
                    <span className="ess-doc-list-name" title={title}>
                      {title}
                    </span>
                    <span className="ess-doc-list-sub">
                      {doc.status || "—"} · {formatBytes(doc.bytes)}
                    </span>
                  </div>
                  <div className="ess-doc-list-actions">
                    <button
                      type="button"
                      className="ess-doc-list-btn"
                      disabled={!canMd}
                      title={
                        canMd
                          ? "Markdown viewer (새 탭)"
                          : "Markdown 없음 (Sync 필요)"
                      }
                      onClick={() => openMarkdown(doc)}
                    >
                      Markdown
                    </button>
                    <button
                      type="button"
                      className="ess-doc-list-btn"
                      disabled={!canPdf}
                      title={
                        canPdf ? "PDF (새 탭)" : "PDF 파일을 찾을 수 없습니다"
                      }
                      onClick={() => openPdf(doc)}
                    >
                      PDF
                    </button>
                    <button
                      type="button"
                      className="ess-doc-list-btn"
                      disabled={!canCopy}
                      title={
                        canCopy
                          ? `Markdown 경로 복사\n${mdPath}`
                          : "Markdown 경로 없음"
                      }
                      onClick={() => void copyMarkdownPath(doc)}
                    >
                      복사
                    </button>
                  </div>
                </li>
              );
            })}
          </ul>
        )}
        <div className="modal-actions">
          <button
            type="button"
            className="modal-btn-secondary"
            onClick={onClose}
          >
            닫기
          </button>
        </div>
      </div>
    </div>,
    document.body,
  );
}
