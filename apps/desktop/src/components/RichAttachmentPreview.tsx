import { useEffect, useState } from "react";
import { attachmentContentUrl } from "../api";
import type { AttachmentRecord } from "../types";

const TEXT_PREVIEW_LIMIT = 512 * 1024;
const TEXT_PREVIEW_CHARS = 12_000;

function formatBytes(bytes: number) {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) {
    return `${(bytes / 1024).toFixed(1)} KB`;
  }

  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function attachmentGlyph(kind: string) {
  if (kind === "image") return "▧";
  if (kind === "pdf") return "PDF";
  if (kind === "audio") return "♪";
  return "≡";
}

function isTextPreviewable(attachment: AttachmentRecord) {
  const mime = attachment.mime_type.toLowerCase();
  const name = attachment.original_name.toLowerCase();

  return (
    attachment.size_bytes <= TEXT_PREVIEW_LIMIT &&
    (
      mime.startsWith("text/") ||
      mime.includes("json") ||
      mime.includes("xml") ||
      mime.includes("yaml") ||
      name.endsWith(".md") ||
      name.endsWith(".txt") ||
      name.endsWith(".csv") ||
      name.endsWith(".json") ||
      name.endsWith(".xml") ||
      name.endsWith(".yaml") ||
      name.endsWith(".yml") ||
      name.endsWith(".log") ||
      name.endsWith(".py") ||
      name.endsWith(".js") ||
      name.endsWith(".ts") ||
      name.endsWith(".tsx") ||
      name.endsWith(".jsx") ||
      name.endsWith(".css") ||
      name.endsWith(".html") ||
      name.endsWith(".sql")
    )
  );
}

export function RichAttachmentPreview({
  attachment,
}: {
  attachment: AttachmentRecord;
}) {
  const url = attachmentContentUrl(attachment.id);
  const [textPreview, setTextPreview] = useState<string | null>(null);
  const [previewError, setPreviewError] = useState<string | null>(null);
  const [previewRequested, setPreviewRequested] = useState(false);

  useEffect(() => {
    if (!previewRequested || !isTextPreviewable(attachment)) return;

    const controller = new AbortController();

    void fetch(url, { signal: controller.signal })
      .then(async (response) => {
        if (!response.ok) {
          throw new Error(`Preview failed (${response.status})`);
        }

        return response.text();
      })
      .then((value) => {
        setTextPreview(
          value.length > TEXT_PREVIEW_CHARS
            ? `${value.slice(0, TEXT_PREVIEW_CHARS)}\n\n… preview truncated …`
            : value,
        );
        setPreviewError(null);
      })
      .catch((error: unknown) => {
        if (controller.signal.aborted) return;
        setPreviewError(
          error instanceof Error ? error.message : "Preview failed",
        );
      });

    return () => controller.abort();
  }, [attachment, previewRequested, url]);

  if (attachment.media_kind === "image") {
    return (
      <a
        className="message-image-link"
        href={url}
        target="_blank"
        rel="noreferrer"
        title={attachment.original_name}
      >
        <img
          className="message-image"
          src={url}
          alt={attachment.original_name}
          loading="lazy"
        />
        <span>{attachment.original_name}</span>
      </a>
    );
  }

  if (attachment.media_kind === "audio") {
    return (
      <div className="rich-attachment-card rich-attachment-audio">
        <div className="rich-attachment-heading">
          <span className="rich-attachment-glyph">♪</span>
          <div>
            <strong>{attachment.original_name}</strong>
            <small>
              audio · {formatBytes(attachment.size_bytes)}
            </small>
          </div>
          <a href={url} target="_blank" rel="noreferrer">
            Open ↗
          </a>
        </div>
        <audio controls preload="metadata" src={url}>
          Your browser does not support audio playback.
        </audio>
      </div>
    );
  }

  if (attachment.media_kind === "pdf") {
    return (
      <details className="rich-attachment-card rich-attachment-pdf">
        <summary className="rich-attachment-heading">
          <span className="rich-attachment-glyph">PDF</span>
          <div>
            <strong>{attachment.original_name}</strong>
            <small>
              PDF · {formatBytes(attachment.size_bytes)}
            </small>
          </div>
          <span className="rich-attachment-preview-label">
            Preview
          </span>
        </summary>
        <div className="rich-pdf-preview">
          <iframe
            src={url}
            title={attachment.original_name}
          />
          <a href={url} target="_blank" rel="noreferrer">
            Open PDF ↗
          </a>
        </div>
      </details>
    );
  }

  if (isTextPreviewable(attachment)) {
    return (
      <details
        className="rich-attachment-card rich-attachment-text"
        onToggle={(event) => {
          if (event.currentTarget.open) {
            setPreviewRequested(true);
          }
        }}
      >
        <summary className="rich-attachment-heading">
          <span className="rich-attachment-glyph">
            {attachmentGlyph(attachment.media_kind)}
          </span>
          <div>
            <strong>{attachment.original_name}</strong>
            <small>
              {attachment.media_kind} · {formatBytes(attachment.size_bytes)}
            </small>
          </div>
          <span className="rich-attachment-preview-label">
            Preview
          </span>
        </summary>

        <div className="rich-text-preview">
          {previewError ? (
            <p>{previewError}</p>
          ) : textPreview == null ? (
            <p>Loading preview…</p>
          ) : (
            <pre>{textPreview}</pre>
          )}

          <a href={url} target="_blank" rel="noreferrer">
            Open file ↗
          </a>
        </div>
      </details>
    );
  }

  return (
    <a
      className="message-file-card"
      href={url}
      target="_blank"
      rel="noreferrer"
    >
      <span className={`file-glyph kind-${attachment.media_kind}`}>
        {attachmentGlyph(attachment.media_kind)}
      </span>
      <span className="file-card-copy">
        <strong>{attachment.original_name}</strong>
        <small>
          {attachment.media_kind} · {formatBytes(attachment.size_bytes)}
        </small>
      </span>
    </a>
  );
}
