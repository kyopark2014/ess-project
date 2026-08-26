import { useCallback, useEffect, useRef, useState, type DragEvent } from "react";
import { fileUploadService } from "../services/fileUploadService";

export interface AttachedImage {
  url: string;
  name: string;
  previewUrl: string;
}

export interface LoadedFile {
  path: string;
  name: string;
  size: number;
}

const ERROR_MESSAGE_DISPLAY_DURATION_MS = 5000;

function extensionFromMime(mime: string): string {
  if (mime === "image/jpeg") return ".jpg";
  if (mime === "image/webp") return ".webp";
  if (mime === "image/gif") return ".gif";
  return ".png";
}

export function isImageFile(file: File): boolean {
  if (file.type.startsWith("image/")) return true;
  return /\.(png|jpe?g|gif|webp)$/i.test(file.name);
}

export function normalizeImageFile(
  file: File,
  fallbackName = "pasted_screenshot",
): File {
  if (!isImageFile(file)) return file;
  const mime = file.type || "image/png";
  const ext = extensionFromMime(mime);
  const hasUsefulName =
    file.name &&
    file.name !== "image.png" &&
    file.name !== "image.jpg" &&
    file.name !== "blob";
  if (hasUsefulName) return file;
  return new File([file], `${fallbackName}${ext}`, { type: mime });
}

export function collectClipboardImages(clipboardData: DataTransfer | null): File[] {
  if (!clipboardData) return [];

  const files: File[] = [];
  const seen = new Set<string>();

  // Clipboard File objects for the same paste often differ in name/lastModified
  // between items and files, so dedupe by size+type only.
  const pushUnique = (file: File) => {
    const key = `${file.size}:${file.type || "image/png"}`;
    if (seen.has(key)) return;
    seen.add(key);
    files.push(normalizeImageFile(file));
  };

  // Prefer items; files usually mirrors the same image with different metadata.
  for (const item of Array.from(clipboardData.items ?? [])) {
    if (!item.type.startsWith("image/")) continue;
    const blob = item.getAsFile();
    if (blob) pushUnique(blob);
  }

  if (files.length === 0) {
    for (const file of Array.from(clipboardData.files ?? [])) {
      if (isImageFile(file)) pushUnique(file);
    }
  }

  return files;
}

interface UseFileUploadOptions {
  disabled?: boolean;
}

export function useFileUpload({ disabled = false }: UseFileUploadOptions = {}) {
  const [uploading, setUploading] = useState(false);
  const [uploadError, setUploadError] = useState<string | null>(null);
  const [attachments, setAttachments] = useState<AttachedImage[]>([]);
  const [loadedFiles, setLoadedFiles] = useState<LoadedFile[]>([]);
  const attachmentsRef = useRef<AttachedImage[]>([]);
  const uploadingRef = useRef(false);

  attachmentsRef.current = attachments;
  uploadingRef.current = uploading;

  useEffect(() => {
    if (!uploadError) return;
    const timer = window.setTimeout(
      () => setUploadError(null),
      ERROR_MESSAGE_DISPLAY_DURATION_MS,
    );
    return () => window.clearTimeout(timer);
  }, [uploadError]);

  useEffect(() => {
    return () => {
      for (const item of attachmentsRef.current) {
        if (item.previewUrl.startsWith("blob:")) {
          URL.revokeObjectURL(item.previewUrl);
        }
      }
    };
  }, []);

  const clearUploadError = useCallback(() => setUploadError(null), []);

  const uploadImageFile = useCallback(async (file: File) => {
    setUploading(true);
    setUploadError(null);
    const previewUrl = URL.createObjectURL(file);
    try {
      const result = await fileUploadService.uploadImage(file);
      setAttachments((prev) => [
        ...prev,
        {
          url: result.url,
          name: result.file_name,
          previewUrl,
        },
      ]);
    } catch (err) {
      URL.revokeObjectURL(previewUrl);
      console.error("Image upload failed", err);
      setUploadError("이미지 업로드에 실패했습니다. 다시 시도해 주세요.");
    } finally {
      setUploading(false);
    }
  }, []);

  const uploadImageFiles = useCallback(
    async (files: File[]) => {
      if (files.length === 0 || disabled || uploadingRef.current) return;
      for (const file of files) {
        await uploadImageFile(normalizeImageFile(file, "uploaded_image"));
      }
    },
    [disabled, uploadImageFile],
  );


  const loadWorkspaceFiles = useCallback(
    async (files: File[]) => {
      if (files.length === 0 || disabled || uploadingRef.current) return;
      setUploading(true);
      setUploadError(null);
      try {
        for (const file of files) {
          const result = await fileUploadService.loadFile(file);
          setLoadedFiles((prev) => {
            const next = prev.filter((item) => item.path !== result.workspace_path);
            return [
              ...next,
              {
                path: result.workspace_path,
                name: result.file_name,
                size: file.size,
              },
            ];
          });
        }
      } catch (err) {
        console.error("Load file failed", err);
        setUploadError("파일 로드에 실패했습니다. 다시 시도해 주세요.");
      } finally {
        setUploading(false);
      }
    },
    [disabled],
  );

  const uploadRagFiles = useCallback(
    async (files: File[], onComplete?: (message: string) => void) => {
      if (files.length === 0 || disabled || uploadingRef.current) return;
      setUploading(true);
      setUploadError(null);
      try {
        const names: string[] = [];
        let lastMessage = "";
        for (let i = 0; i < files.length; i += 1) {
          const file = files[i];
          const isLast = i === files.length - 1;
          // Sync only on the last file so multi-select does not 409 mid-batch.
          const result = await fileUploadService.uploadToRag(file, {
            sync: isLast,
          });
          names.push(result.file_name || file.name);
          lastMessage = result.message;
        }
        if (files.length === 1) {
          onComplete?.(lastMessage);
        } else {
          const listed = names.map((n) => `"${n}"`).join(", ");
          onComplete?.(
            `${listed} ${names.length}개가 S3에 업로드 되었고 Knowledge Base와 동기화를 시작합니다.`,
          );
        }
      } catch (err) {
        console.error("Document upload failed", err);
        const detail = err instanceof Error ? err.message : "";
        setUploadError(
          detail
            ? detail.replace(/^RAG upload failed:\s*/i, "")
            : "파일 업로드에 실패했습니다. 다시 시도해 주세요.",
        );
      } finally {
        setUploading(false);
      }
    },
    [disabled],
  );

  const removeAttachment = useCallback((url: string) => {
    setAttachments((prev) => {
      const next: AttachedImage[] = [];
      for (const item of prev) {
        if (item.url === url) {
          if (item.previewUrl.startsWith("blob:")) {
            URL.revokeObjectURL(item.previewUrl);
          }
          continue;
        }
        next.push(item);
      }
      return next;
    });
  }, []);

  const removeLoadedFile = useCallback((path: string) => {
    setLoadedFiles((prev) => prev.filter((item) => item.path !== path));
  }, []);

  /** Attach an already-local workspace path (e.g. ESS Document List markdown). */
  const attachExistingFile = useCallback(
    (file: LoadedFile) => {
      if (disabled) return;
      const path = (file.path || "").trim();
      const name = (file.name || "").trim();
      if (!path || !name) return;
      setLoadedFiles((prev) => {
        const next = prev.filter((item) => item.path !== path);
        return [
          ...next,
          {
            path,
            name,
            size: Number.isFinite(file.size) && file.size > 0 ? file.size : 0,
          },
        ];
      });
    },
    [disabled],
  );

  const clearAttachments = useCallback(() => {
    setAttachments((prev) => {
      for (const item of prev) {
        if (item.previewUrl.startsWith("blob:")) {
          URL.revokeObjectURL(item.previewUrl);
        }
      }
      return [];
    });
    setLoadedFiles([]);
  }, []);

  const [dragOver, setDragOver] = useState(false);
  const dragDepthRef = useRef(0);

  const onDragEnter = useCallback(
    (e: DragEvent) => {
      if (disabled || uploadingRef.current) return;
      if (![...e.dataTransfer.types].includes("Files")) return;
      e.preventDefault();
      dragDepthRef.current += 1;
      setDragOver(true);
    },
    [disabled],
  );

  const onDragOver = useCallback(
    (e: DragEvent) => {
      if (disabled || uploadingRef.current) return;
      if (![...e.dataTransfer.types].includes("Files")) return;
      e.preventDefault();
      e.dataTransfer.dropEffect = "copy";
    },
    [disabled],
  );

  const onDragLeave = useCallback((e: DragEvent) => {
    if (![...e.dataTransfer.types].includes("Files") && dragDepthRef.current === 0) {
      return;
    }
    e.preventDefault();
    dragDepthRef.current = Math.max(0, dragDepthRef.current - 1);
    if (dragDepthRef.current === 0) setDragOver(false);
  }, []);

  const onDrop = useCallback(
    async (e: DragEvent) => {
      e.preventDefault();
      dragDepthRef.current = 0;
      setDragOver(false);
      if (disabled || uploadingRef.current) return;
      const imageFiles = Array.from(e.dataTransfer.files ?? []).filter(isImageFile);
      await uploadImageFiles(imageFiles);
    },
    [disabled, uploadImageFiles],
  );

  return {
    uploading,
    uploadError,
    attachments,
    loadedFiles,
    dragOver,
    isUploading: () => uploadingRef.current,
    clearUploadError,
    uploadImageFiles,
    loadWorkspaceFiles,
    uploadRagFiles,
    attachExistingFile,
    removeAttachment,
    removeLoadedFile,
    clearAttachments,
    onDragEnter,
    onDragOver,
    onDragLeave,
    onDrop,
  };
}
