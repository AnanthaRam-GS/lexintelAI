export interface ValidationOptions {
  accept: string;
  maxSizeMB: number;
  multiple: boolean;
}

export interface ValidationResult {
  valid: File[];
  errors: string[];
}

const bytesPerMegabyte = 1024 * 1024;

function parseAcceptedTypes(accept: string) {
  return accept
    .split(',')
    .map((item) => item.trim().toLowerCase())
    .filter(Boolean)
    .reduce(
      (accepted, item) => {
        if (item.startsWith('.')) {
          accepted.extensions.push(item);
        } else {
          accepted.mimeTypes.push(item);
        }

        return accepted;
      },
      { extensions: [] as string[], mimeTypes: [] as string[] },
    );
}

function hasAcceptedMimeType(fileType: string, mimeTypes: string[]) {
  const normalizedType = fileType.toLowerCase();

  return mimeTypes.some(
    (mimeType) =>
      mimeType === normalizedType ||
      (mimeType.endsWith('/*') && normalizedType.startsWith(mimeType.slice(0, -1))),
  );
}

function hasAcceptedExtension(fileName: string, extensions: string[]) {
  const normalizedName = fileName.toLowerCase();

  return extensions.some((extension) => normalizedName.endsWith(extension));
}

function isAcceptedFile(file: File, accept: string) {
  const { extensions, mimeTypes } = parseAcceptedTypes(accept);

  if (mimeTypes.length === 0 && extensions.length === 0) {
    return true;
  }

  if (file.type && mimeTypes.length > 0) {
    return hasAcceptedMimeType(file.type, mimeTypes);
  }

  if (extensions.length > 0) {
    return hasAcceptedExtension(file.name, extensions);
  }

  return false;
}

function deduplicateFiles(files: File[]) {
  const seen = new Set<string>();

  return files.filter((file) => {
    const identity = `${file.name}\u0000${file.size}\u0000${file.lastModified}`;

    if (seen.has(identity)) {
      return false;
    }

    seen.add(identity);
    return true;
  });
}

export function formatFileSize(bytes: number): string {
  if (bytes < 1024) {
    return `${bytes} B`;
  }

  const units = ['KB', 'MB', 'GB'];
  const unitIndex = Math.min(Math.floor(Math.log(bytes) / Math.log(1024)) - 1, units.length - 1);
  const size = bytes / 1024 ** (unitIndex + 1);
  const roundedSize = Math.round(size * 10) / 10;

  return `${roundedSize} ${units[unitIndex]}`;
}

export function validateFiles(files: File[], options: ValidationOptions): ValidationResult {
  const errors: string[] = [];
  const maxSizeBytes = options.maxSizeMB * bytesPerMegabyte;
  const valid = deduplicateFiles(files).filter((file) => {
    const label = file.name || 'This file';
    let fileIsValid = true;

    if (!isAcceptedFile(file, options.accept)) {
      errors.push(`${label} cannot be added. Choose a PDF file.`);
      fileIsValid = false;
    }

    if (file.size > maxSizeBytes) {
      errors.push(
        `${label} is too large. Choose a file that is ${options.maxSizeMB} MB or smaller.`,
      );
      fileIsValid = false;
    }

    return fileIsValid;
  });

  return { errors, valid: options.multiple ? valid : valid.slice(0, 1) };
}
