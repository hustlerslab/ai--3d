"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { uploadImages } from "../api/walkthrough-api";
import {
  WalkthroughApiError,
  type PendingImage,
  type UploadRejection,
} from "../types/walkthrough";
import { formatBytes } from "../utils/walkthrough-helpers";

/**
 * Holds the photos a user has picked, validates them in the browser, and
 * uploads them with real progress.
 *
 * Client-side validation (readme2 §13) is a courtesy, not a security control —
 * the engine re-checks every file by magic bytes regardless. Catching an
 * obvious mistake here saves the user a 20 MB round trip to learn their HEIC
 * screenshot is not a JPEG.
 *
 * Object URLs are revoked on removal and on unmount. Without that, every
 * preview keeps a decoded full-size bitmap alive for the life of the page,
 * which on a 40-photo property is hundreds of megabytes.
 */

const ACCEPTED_TYPES = ["image/jpeg", "image/jpg", "image/png", "image/webp"] as const;
const ACCEPTED_EXTENSIONS = [".jpg", ".jpeg", ".png", ".webp"] as const;
const MAX_FILE_BYTES = 20 * 1024 * 1024;
const MAX_FILES = 50;
/** Uploads can legitimately take minutes on a slow connection. */
const UPLOAD_TIMEOUT_MS = 10 * 60 * 1000;

export interface UseWalkthroughUploadResult {
  images: PendingImage[];
  /** Only the images that passed local validation. */
  validImages: PendingImage[];
  uploading: boolean;
  progress: number;
  error: WalkthroughApiError | null;
  rejections: UploadRejection[];

  addFiles: (files: FileList | File[]) => void;
  removeImage: (id: string) => void;
  clearAll: () => void;
  upload: (walkthroughId: string) => Promise<boolean>;
  clearError: () => void;
}

/** Local pre-flight check. Returns a message, or null if the file is fine. */
function validateFile(file: File, existing: PendingImage[]): string | null {
  const name = file.name.toLowerCase();
  const typeOk = (ACCEPTED_TYPES as readonly string[]).includes(file.type);
  const extOk = ACCEPTED_EXTENSIONS.some((ext) => name.endsWith(ext));

  // Some browsers report an empty type for files dragged from odd sources, so
  // an acceptable extension is allowed to stand in — the engine has the final
  // say either way.
  if (!typeOk && !extOk) {
    return "Not a JPEG, PNG, or WebP image.";
  }
  if (file.size === 0) {
    return "This file is empty.";
  }
  if (file.size > MAX_FILE_BYTES) {
    return `Too large — ${formatBytes(file.size)}. The limit is 20 MB.`;
  }
  // Cheap duplicate check. The engine hashes content; this only catches the
  // common case of picking the same file twice.
  if (existing.some((img) => img.file.name === file.name && img.file.size === file.size)) {
    return "Already added.";
  }
  return null;
}

export function useWalkthroughUpload(): UseWalkthroughUploadResult {
  const [images, setImages] = useState<PendingImage[]>([]);
  const [uploading, setUploading] = useState(false);
  const [progress, setProgress] = useState(0);
  const [error, setError] = useState<WalkthroughApiError | null>(null);
  const [rejections, setRejections] = useState<UploadRejection[]>([]);

  // Mirrors `images` so the unmount cleanup can revoke without listing images
  // as an effect dependency (which would revoke on every change).
  const imagesRef = useRef<PendingImage[]>([]);
  imagesRef.current = images;

  const uploadingRef = useRef(false);

  useEffect(() => {
    return () => {
      for (const image of imagesRef.current) URL.revokeObjectURL(image.previewUrl);
    };
  }, []);

  const addFiles = useCallback((incoming: FileList | File[]) => {
    const list = Array.from(incoming);
    if (list.length === 0) return;

    setError(null);
    setRejections([]);

    setImages((current) => {
      const room = MAX_FILES - current.length;
      if (room <= 0) {
        setError(
          new WalkthroughApiError(
            "TOO_MANY_FILES",
            `You can add up to ${MAX_FILES} photos. Remove some before adding more.`,
          ),
        );
        return current;
      }

      const accepted = list.slice(0, room);

      if (list.length > room) {
        setError(
          new WalkthroughApiError(
            "TOO_MANY_FILES",
            `Only the first ${room} of ${list.length} photos were added — the limit is ${MAX_FILES}.`,
          ),
        );
      }

      const next = [...current];
      for (const file of accepted) {
        next.push({
          id: `${file.name}-${file.size}-${file.lastModified}-${next.length}`,
          file,
          previewUrl: URL.createObjectURL(file),
          sizeLabel: formatBytes(file.size),
          error: validateFile(file, next),
        });
      }
      return next;
    });
  }, []);

  const removeImage = useCallback((id: string) => {
    setImages((current) => {
      const target = current.find((img) => img.id === id);
      if (target) URL.revokeObjectURL(target.previewUrl);
      return current.filter((img) => img.id !== id);
    });
  }, []);

  const clearAll = useCallback(() => {
    setImages((current) => {
      for (const image of current) URL.revokeObjectURL(image.previewUrl);
      return [];
    });
    setRejections([]);
    setError(null);
  }, []);

  const upload = useCallback(
    async (walkthroughId: string): Promise<boolean> => {
      if (uploadingRef.current) return false;

      const valid = imagesRef.current.filter((img) => img.error === null);
      if (valid.length === 0) {
        setError(
          new WalkthroughApiError("NO_IMAGES", "Add at least one usable photo first."),
        );
        return false;
      }

      uploadingRef.current = true;
      setUploading(true);
      setProgress(0);
      setError(null);
      setRejections([]);

      const controller = new AbortController();
      const timeout = setTimeout(() => controller.abort(), UPLOAD_TIMEOUT_MS);

      try {
        const result = await uploadImages(
          walkthroughId,
          valid.map((img) => img.file),
          { onProgress: setProgress, signal: controller.signal },
        );

        // Every file bounced — surface it as an error, not a quiet success.
        if (result.totalUploaded === 0) {
          setRejections(result.rejected);
          setError(
            new WalkthroughApiError(
              "INVALID_IMAGE",
              "None of the photos could be used. See the reasons below.",
            ),
          );
          return false;
        }

        // Accepted files are now the engine's; drop the local previews so the
        // grid reflects what was actually stored. clearAll() also clears
        // rejections, so re-apply them afterwards — the user still needs to
        // see which of their photos did not make it.
        clearAll();
        setRejections(result.rejected);
        return true;
      } catch (err) {
        setError(
          err instanceof WalkthroughApiError
            ? err
            : new WalkthroughApiError("UPLOAD_FAILED", "The upload did not finish.", 0, {
                retryable: true,
              }),
        );
        return false;
      } finally {
        clearTimeout(timeout);
        uploadingRef.current = false;
        setUploading(false);
      }
    },
    [clearAll],
  );

  const clearError = useCallback(() => setError(null), []);

  return {
    images,
    validImages: images.filter((img) => img.error === null),
    uploading,
    progress,
    error,
    rejections,
    addFiles,
    removeImage,
    clearAll,
    upload,
    clearError,
  };
}
