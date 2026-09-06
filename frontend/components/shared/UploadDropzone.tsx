'use client';

import { FileText, Upload, X } from 'lucide-react';
import { useRef, useState, type ChangeEvent, type DragEvent } from 'react';

import { ErrorMessage } from './ErrorMessage';
import { formatFileSize, validateFiles } from './file-validation';

export interface UploadDropzoneProps {
  accept?: string;
  maxSizeMB?: number;
  multiple?: boolean;
  onFilesSelected: (files: File[]) => void;
  disabled?: boolean;
}

const defaultAccept = 'application/pdf,.pdf';

export function UploadDropzone({
  accept = defaultAccept,
  maxSizeMB = 10,
  multiple = false,
  onFilesSelected,
  disabled = false,
}: UploadDropzoneProps) {
  const inputRef = useRef<HTMLInputElement>(null);
  const dragDepth = useRef(0);
  const [files, setFiles] = useState<File[]>([]);
  const [errors, setErrors] = useState<string[]>([]);
  const [isDragging, setIsDragging] = useState(false);

  const selectCandidates = (candidates: File[]) => {
    if (disabled || candidates.length === 0) {
      return;
    }

    const validation = validateFiles(multiple ? [...files, ...candidates] : candidates, {
      accept,
      maxSizeMB,
      multiple,
    });

    setErrors(validation.errors);

    if (!multiple && validation.valid.length === 0) {
      return;
    }

    setFiles(validation.valid);
    onFilesSelected(validation.valid);
  };

  const handleInputChange = (event: ChangeEvent<HTMLInputElement>) => {
    selectCandidates(Array.from(event.target.files ?? []));
    event.target.value = '';
  };

  const handleDragEnter = (event: DragEvent<HTMLDivElement>) => {
    event.preventDefault();

    if (disabled) {
      return;
    }

    dragDepth.current += 1;
    setIsDragging(true);
  };

  const handleDragLeave = (event: DragEvent<HTMLDivElement>) => {
    event.preventDefault();

    if (disabled) {
      return;
    }

    dragDepth.current = Math.max(0, dragDepth.current - 1);
    setIsDragging(dragDepth.current > 0);
  };

  const handleDrop = (event: DragEvent<HTMLDivElement>) => {
    event.preventDefault();
    dragDepth.current = 0;
    setIsDragging(false);

    selectCandidates(Array.from(event.dataTransfer.files));
  };

  const removeFile = (fileToRemove: File) => {
    const nextFiles = files.filter((file) => file !== fileToRemove);

    setErrors([]);
    setFiles(nextFiles);
    onFilesSelected(nextFiles);
  };

  return (
    <section className="space-y-4" aria-label="PDF file upload">
      <div
        aria-disabled={disabled}
        className={`rounded-[var(--radius-standard)] border-2 border-dashed p-6 text-center transition-colors duration-[var(--motion-fast)] sm:p-8 ${
          disabled
            ? 'cursor-not-allowed border-[var(--color-border)] bg-[var(--color-surface-subtle)] opacity-60'
            : isDragging
              ? 'border-[var(--color-focus)] bg-[var(--color-info-surface)]'
              : 'border-[var(--color-border)] bg-[var(--color-surface)]'
        }`}
        data-testid="upload-dropzone"
        onDragEnter={handleDragEnter}
        onDragLeave={handleDragLeave}
        onDragOver={(event) => event.preventDefault()}
        onDrop={handleDrop}
      >
        <Upload
          aria-hidden="true"
          className="mx-auto text-[var(--color-brass)]"
          size={28}
          strokeWidth={1.8}
        />
        <p className="font-display text-type-heading-sm mt-3 font-semibold text-[var(--color-ink)]">
          {isDragging ? 'Drop PDF files here' : 'Drag & drop PDF files here'}
        </p>
        <p className="text-type-body-sm-relaxed mt-1 text-[var(--color-muted)]">
          PDF files up to {maxSizeMB} MB{multiple ? ' each' : ''}.
        </p>
        <button
          className="text-type-control mt-4 inline-flex min-h-11 items-center justify-center rounded-[var(--radius-compact)] bg-[var(--color-brass)] px-4 font-semibold text-[var(--color-inverse)] transition-colors duration-[var(--motion-fast)] hover:bg-[var(--color-brass-hover)] active:bg-[var(--color-brass-active)] focus-visible:outline-[0.1875rem] focus-visible:outline-[var(--color-focus)] focus-visible:outline-offset-[0.1875rem] disabled:cursor-not-allowed disabled:opacity-60"
          disabled={disabled}
          onClick={() => inputRef.current?.click()}
          type="button"
        >
          Browse files
        </button>
        <input
          accept={accept}
          aria-label="Choose PDF files"
          className="sr-only"
          disabled={disabled}
          multiple={multiple}
          onChange={handleInputChange}
          ref={inputRef}
          tabIndex={-1}
          type="file"
        />
      </div>

      {errors.length > 0 ? (
        <ErrorMessage message={errors.join(' ')} title="Unable to add files" variant="inline" />
      ) : null}

      {files.length > 0 ? (
        <ul aria-live="polite" className="space-y-2" aria-label="Selected PDF files">
          {files.map((file) => (
            <li
              className="flex items-center gap-3 rounded-[var(--radius-compact)] border border-[var(--color-border)] bg-[var(--color-surface-raised)] p-3"
              key={`${file.name}-${file.size}-${file.lastModified}`}
            >
              <FileText
                aria-hidden="true"
                className="shrink-0 text-[var(--color-brass)]"
                size={20}
                strokeWidth={1.8}
              />
              <div className="min-w-0 flex-1 text-left">
                <p className="text-type-body truncate font-medium text-[var(--color-ink)]">
                  {file.name}
                </p>
                <p className="text-type-label mt-0.5 text-[var(--color-muted)]">
                  {formatFileSize(file.size)}
                </p>
              </div>
              <button
                aria-label={`Remove ${file.name}`}
                className="inline-flex min-h-11 min-w-11 items-center justify-center rounded-[var(--radius-compact)] text-[var(--color-body)] transition-colors duration-[var(--motion-fast)] hover:bg-[var(--color-surface-subtle)] focus-visible:outline-[0.1875rem] focus-visible:outline-[var(--color-focus)] focus-visible:outline-offset-[0.1875rem] disabled:cursor-not-allowed disabled:opacity-60"
                disabled={disabled}
                onClick={() => removeFile(file)}
                type="button"
              >
                <X aria-hidden="true" size={18} strokeWidth={1.8} />
              </button>
            </li>
          ))}
        </ul>
      ) : null}
    </section>
  );
}
