import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { api } from "../api";

type DocKind = "regulation" | "project";

interface Props {
  onClose: () => void;
  /** Called after a file is uploaded so the parent can open ESS Sync. */
  onFileUploaded?: () => void;
}

export function EssConfigureModal({ onClose, onFileUploaded }: Props) {
  const [pendingFile, setPendingFile] = useState<File | null>(null);
  const [pendingKind, setPendingKind] = useState<DocKind | null>(null);
  const [foundationModelParser, setFoundationModelParser] = useState(true);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const regulationInputRef = useRef<HTMLInputElement | null>(null);
  const projectInputRef = useRef<HTMLInputElement | null>(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      setLoading(true);
      setError(null);
      try {
        const data = await api.getEssConfig();
        if (cancelled) return;
        setFoundationModelParser(
          data.foundation_model_parser_enabled !== false,
        );
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
      if (e.key === "Escape" && !busy) onClose();
    }
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [busy, onClose]);

  async function uploadDoc(file: File, kind: DocKind) {
    await api.putEssConfig({
      foundation_model_parser_enabled: foundationModelParser,
    });
    if (kind === "project") {
      await api.uploadEssProjectFile(file);
    } else {
      await api.uploadEssRawFile(file);
    }
  }

  async function handleSave() {
    setBusy(true);
    setError(null);
    try {
      await api.putEssConfig({
        foundation_model_parser_enabled: foundationModelParser,
      });

      if (pendingFile && pendingKind) {
        await uploadDoc(pendingFile, pendingKind);
        setPendingFile(null);
        setPendingKind(null);
        if (regulationInputRef.current) regulationInputRef.current.value = "";
        if (projectInputRef.current) projectInputRef.current.value = "";
        onClose();
        onFileUploaded?.();
        return;
      }

      onClose();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  async function handlePickFile(fileList: FileList | null, kind: DocKind) {
    if (!fileList || fileList.length === 0) return;
    const file = fileList[0];
    const inputRef = kind === "project" ? projectInputRef : regulationInputRef;
    if (inputRef.current) inputRef.current.value = "";

    setPendingFile(file);
    setPendingKind(kind);
    setError(null);
    setBusy(true);
    try {
      await uploadDoc(file, kind);
      setPendingFile(null);
      setPendingKind(null);
      onClose();
      onFileUploaded?.();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  function renderDocSection(kind: DocKind) {
    const label =
      kind === "project" ? "Project 문서 추가" : "Regulation 문서 추가";
    const inputRef = kind === "project" ? projectInputRef : regulationInputRef;
    const isPending = pendingKind === kind && pendingFile;

    return (
      <div className="ess-configure-doc-section">
        <div className="ess-configure-section-label">{label}</div>
        <div className="ess-configure-docs">
          <input
            ref={inputRef}
            type="file"
            className="ess-configure-file-input"
            accept=".pdf,.md,.txt,.markdown,.rst,.docx,.pptx,.csv,.json,.html,.htm,application/pdf,text/plain,text/markdown"
            disabled={busy}
            onChange={(e) => {
              void handlePickFile(e.target.files, kind);
            }}
          />
          <div className="ess-configure-docs-actions">
            <button
              type="button"
              className="modal-btn-secondary"
              disabled={busy}
              onClick={() => inputRef.current?.click()}
            >
              파일 선택…
            </button>
          </div>
          {isPending ? (
            <ul className="ess-configure-docs-list">
              <li>
                <span className="ess-configure-docs-name">
                  {pendingFile.name}
                </span>
                <span className="ess-configure-docs-meta">
                  {(pendingFile.size / 1024).toFixed(1)} KB
                </span>
              </li>
            </ul>
          ) : (
            <p className="ess-configure-docs-empty">
              파일을 선택하면 저장 후 Sync를 수행합니다.
            </p>
          )}
        </div>
      </div>
    );
  }

  return createPortal(
    <div
      className="modal-overlay"
      role="dialog"
      aria-modal="true"
      aria-labelledby="ess-configure-title"
      onMouseDown={(e) => {
        if (e.target === e.currentTarget && !busy) onClose();
      }}
    >
      <div className="modal ess-configure-modal">
        <h2 id="ess-configure-title">ESS Configure</h2>
        {loading ? (
          <p className="ess-configure-muted">불러오는 중…</p>
        ) : (
          <>
            <label className="ess-configure-toggle">
              <span className="ess-configure-toggle-title">
                Foundation Model Parser
              </span>
              <input
                type="checkbox"
                checked={foundationModelParser}
                disabled={busy}
                onChange={(e) => setFoundationModelParser(e.target.checked)}
              />
            </label>

            {renderDocSection("regulation")}
            {renderDocSection("project")}
          </>
        )}
        {error ? (
          <p className="modal-error" role="alert">
            {error}
          </p>
        ) : null}
        <div className="modal-actions">
          <button
            type="button"
            className="modal-btn-secondary"
            disabled={busy}
            onClick={onClose}
          >
            닫기
          </button>
          <button
            type="button"
            className="modal-btn-primary"
            disabled={busy || loading}
            onClick={() => void handleSave()}
          >
            {busy ? "저장 중…" : "저장"}
          </button>
        </div>
      </div>
    </div>,
    document.body,
  );
}
