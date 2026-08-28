import { useEffect, useState } from "react";
import { createPortal } from "react-dom";
import { api, type EssDocument } from "../api";
import { copyDocumentForChat } from "../pendingLoadFile";

interface Props {
  onClose: () => void;
  /** ``regulation`` → regulations_list.json, ``project`` → project_list.json, ``drawing`` → drawings_list.json, ``test_case`` → test_cases_list.json */
  kind?: "regulation" | "project" | "drawing" | "test_case";
}

function formatBytes(bytes: number | undefined): string {
  if (bytes == null || !Number.isFinite(bytes) || bytes < 0) return "—";
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function formatCreatedAt(value: string | undefined): string | null {
  const raw = (value || "").trim();
  if (!raw) return null;
  const date = new Date(raw);
  if (Number.isNaN(date.getTime())) return null;
  return date.toLocaleString("ko-KR", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function documentSublineParts(
  doc: EssDocument,
  extra: Array<string | null | undefined> = [],
): string {
  const timestamp =
    formatCreatedAt(doc.updated_at) ||
    formatCreatedAt(doc.extracted_at) ||
    formatCreatedAt(doc.created_at);
  const parts = [timestamp, ...extra, formatBytes(doc.bytes)].filter(Boolean);
  return parts.length > 0 ? parts.join(" · ") : "—";
}

function openInNewTab(url: string) {
  window.open(url, "_blank", "noopener,noreferrer");
}

/** CloudFront URL for agent chat (runtime cannot read ECS ``/mnt/app-data`` paths). */
function markdownCopyUrl(doc: EssDocument): string | null {
  const url = (doc.md_url || "").trim();
  return url || null;
}

function markdownFileName(doc: EssDocument): string | null {
  const fromField = (doc.md_file || "").trim();
  if (fromField) return fromField;
  const local = (doc.md_path || "").trim();
  if (local) return local.split("/").pop() || local;
  return null;
}

function testCaseCopyPath(doc: EssDocument): string | null {
  const json = (doc.json_path || "").trim();
  if (json) return json;
  const src = (doc.source_path || "").trim();
  return src || null;
}

function documentKey(doc: EssDocument): string {
  return doc.filename || doc.md_file || doc.display_name || "doc";
}

export function EssDocumentListModal({ onClose, kind = "regulation" }: Props) {
  const [documents, setDocuments] = useState<EssDocument[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [deletingKey, setDeletingKey] = useState<string | null>(null);
  const title =
    kind === "project"
      ? "Projects"
      : kind === "drawing"
        ? "Drawings"
        : kind === "test_case"
          ? "Test Cases"
          : "Regulations";
  const emptyHint =
    kind === "project"
      ? "등록된 Project 문서가 없습니다. Configure에서 Project 문서를 추가한 뒤 Sync 하세요."
      : kind === "drawing"
        ? "등록된 Drawing 문서가 없습니다. Configure에서 Drawing 문서를 추가한 뒤 Sync 하세요."
        : kind === "test_case"
          ? "등록된 Test Case가 없습니다. testcase-generator 스킬로 생성·저장하세요."
          : "등록된 문서가 없습니다. Configure에서 문서를 추가한 뒤 Sync 하세요.";

  useEffect(() => {
    let cancelled = false;
    (async () => {
      setLoading(true);
      setError(null);
      try {
        const data =
          kind === "project"
            ? await api.getEssProjectList(true)
            : kind === "drawing"
              ? await api.getEssDrawingList(true)
              : kind === "test_case"
                ? await api.getEssTestCaseList()
                : await api.getEssDocList(true);
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
  }, [kind]);

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

  function openJson(doc: EssDocument) {
    const url = doc.json_viewer_url;
    if (!url) return;
    openInNewTab(url);
  }

  function openXlsx(doc: EssDocument) {
    const url = doc.xlsx_api_url;
    if (!url) return;
    openInNewTab(url);
  }

  async function copyMarkdownPath(doc: EssDocument) {
    const url = markdownCopyUrl(doc);
    if (!url) return;
    const name = markdownFileName(doc) || url.split("/").pop() || url;
    const mdBytes = Number(doc.md_bytes);
    // Attach chip immediately + stage for Load files; pass CloudFront URL to agent.
    copyDocumentForChat({
      path: url,
      name,
      size: Number.isFinite(mdBytes) && mdBytes > 0 ? mdBytes : 0,
    });
    try {
      await navigator.clipboard.writeText(url);
    } catch {
      // Clipboard is optional; chat attachment still works via event.
    }
    onClose();
  }

  async function copyTestCasePath(doc: EssDocument) {
    const path = testCaseCopyPath(doc);
    if (!path) return;
    const name = path.split("/").pop() || path;
    const size = Number(doc.bytes);
    copyDocumentForChat({
      path,
      name,
      size: Number.isFinite(size) && size > 0 ? size : 0,
    });
    try {
      await navigator.clipboard.writeText(path);
    } catch {
      // Clipboard is optional; chat attachment still works via event.
    }
    onClose();
  }

  async function deleteDocument(doc: EssDocument) {
    const filename = (doc.filename || "").trim();
    if (!filename) {
      setError("삭제할 파일명이 없습니다.");
      return;
    }
    const label =
      doc.display_name ||
      doc.title ||
      doc.original_filename ||
      filename;
    const kindLabel =
      kind === "project"
        ? "Project"
        : kind === "drawing"
          ? "Drawing"
          : kind === "test_case"
            ? "Test Case"
            : "Regulation";
    const confirmed = window.confirm(
      `"${label}" ${kindLabel} 문서와 관련 파일(원본·JSON${
        kind === "test_case" ? "" : "·Markdown"
      })을 삭제할까요?\n이 작업은 되돌릴 수 없습니다.`,
    );
    if (!confirmed) return;

    const key = documentKey(doc);
    setDeletingKey(key);
    setError(null);
    try {
      await api.deleteEssDocument(filename, kind);
      setDocuments((prev) =>
        prev.filter((d) => (d.filename || "").trim() !== filename),
      );
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setDeletingKey(null);
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
        <h2 id="ess-doc-list-title">{title}</h2>
        {loading ? (
          <p className="ess-configure-muted">문서 목록을 불러오는 중…</p>
        ) : documents.length === 0 ? (
          error ? (
            <p className="modal-error" role="alert">
              {error}
            </p>
          ) : (
            <p className="ess-configure-docs-empty">{emptyHint}</p>
          )
        ) : (
          <>
            {error ? (
              <p className="modal-error" role="alert">
                {error}
              </p>
            ) : null}
            <ul className="ess-doc-list">
            {documents.map((doc) => {
              const key = documentKey(doc);
              const itemTitle =
                doc.display_name ||
                doc.title ||
                doc.original_filename ||
                doc.filename ||
                doc.md_file ||
                "document";
              const canDelete = Boolean((doc.filename || "").trim());
              const isDeleting = deletingKey === key;
              if (kind === "test_case") {
                const canJson = Boolean(
                  doc.json_available && doc.json_viewer_url,
                );
                const canXlsx = Boolean(doc.xlsx_available && doc.xlsx_api_url);
                const copyPath = testCaseCopyPath(doc);
                const canCopy = Boolean(copyPath);
                const rows =
                  typeof doc.rows === "number" && Number.isFinite(doc.rows)
                    ? `${doc.rows} rows`
                    : null;
                return (
                  <li key={key} className="ess-doc-list-item">
                    <div className="ess-doc-list-meta">
                      <span className="ess-doc-list-name" title={itemTitle}>
                        {itemTitle}
                      </span>
                      <span className="ess-doc-list-sub">
                        {documentSublineParts(doc, [
                          doc.standard || null,
                          doc.status || "—",
                          rows,
                        ])}
                      </span>
                    </div>
                    <div className="ess-doc-list-actions">
                      <button
                        type="button"
                        className="ess-doc-list-btn"
                        disabled={!canJson || isDeleting}
                        title={
                          canJson
                            ? "JSON viewer (새 탭)"
                            : "JSON sidecar 없음"
                        }
                        onClick={() => openJson(doc)}
                      >
                        JSON
                      </button>
                      <button
                        type="button"
                        className="ess-doc-list-btn"
                        disabled={!canXlsx || isDeleting}
                        title={
                          canXlsx
                            ? "Excel 다운로드"
                            : "Excel 파일을 찾을 수 없습니다"
                        }
                        onClick={() => openXlsx(doc)}
                      >
                        Excel
                      </button>
                      <button
                        type="button"
                        className="ess-doc-list-btn ess-doc-list-btn-success"
                        disabled={!canCopy || isDeleting}
                        title={
                          canCopy
                            ? `입력창에 파일 첨부 + 경로 복사\n${copyPath}`
                            : "첨부할 파일 경로가 없습니다"
                        }
                        onClick={() => void copyTestCasePath(doc)}
                      >
                        복사
                      </button>
                      <button
                        type="button"
                        className="ess-doc-list-btn ess-doc-list-btn-danger"
                        disabled={!canDelete || isDeleting}
                        title={
                          canDelete
                            ? "원본·JSON 및 목록에서 삭제"
                            : "삭제할 파일명이 없습니다"
                        }
                        onClick={() => void deleteDocument(doc)}
                      >
                        {isDeleting ? "삭제 중…" : "삭제"}
                      </button>
                    </div>
                  </li>
                );
              }

              const canMd = Boolean(doc.md_available && doc.md_viewer_url);
              const canPdf = Boolean(
                doc.pdf_available && (doc.pdf_api_url || doc.pdf_url),
              );
              const mdCopyUrl = markdownCopyUrl(doc);
              const canCopy = Boolean(mdCopyUrl);
              return (
                <li key={key} className="ess-doc-list-item">
                  <div className="ess-doc-list-meta">
                    <span className="ess-doc-list-name" title={itemTitle}>
                      {itemTitle}
                    </span>
                    <span className="ess-doc-list-sub">
                      {documentSublineParts(doc, [doc.status || "—"])}
                    </span>
                  </div>
                  <div className="ess-doc-list-actions">
                    <button
                      type="button"
                      className="ess-doc-list-btn"
                      disabled={!canMd || isDeleting}
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
                      disabled={!canPdf || isDeleting}
                      title={
                        canPdf ? "PDF (새 탭)" : "PDF 파일을 찾을 수 없습니다"
                      }
                      onClick={() => openPdf(doc)}
                    >
                      PDF
                    </button>
                    <button
                      type="button"
                      className="ess-doc-list-btn ess-doc-list-btn-success"
                      disabled={!canCopy || isDeleting}
                      title={
                        canCopy
                          ? `입력창에 Markdown 첨부 + CloudFront URL 복사\n${mdCopyUrl}`
                          : "CloudFront URL 없음 (Sync 후 sharing_url 설정 확인)"
                      }
                      onClick={() => void copyMarkdownPath(doc)}
                    >
                      복사
                    </button>
                    <button
                      type="button"
                      className="ess-doc-list-btn ess-doc-list-btn-danger"
                      disabled={!canDelete || isDeleting}
                      title={
                        canDelete
                          ? "원본·JSON·Markdown 및 목록에서 삭제"
                          : "삭제할 파일명이 없습니다"
                      }
                      onClick={() => void deleteDocument(doc)}
                    >
                      {isDeleting ? "삭제 중…" : "삭제"}
                    </button>
                  </div>
                </li>
              );
            })}
            </ul>
          </>
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
