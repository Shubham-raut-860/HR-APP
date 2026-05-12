import axios from 'axios';

const MESSAGE_KEYS = ['detail', 'message', 'error'] as const;

const isRecord = (value: unknown): value is Record<string, unknown> =>
  typeof value === 'object' && value !== null;

const extractMessage = (value: unknown): string | null => {
  if (typeof value === 'string') {
    const trimmed = value.trim();
    return trimmed.length > 0 ? trimmed : null;
  }

  if (isRecord(value)) {
    for (const key of MESSAGE_KEYS) {
      const candidate = value[key];
      if (typeof candidate === 'string' && candidate.trim()) {
        return candidate.trim();
      }
    }
  }

  return null;
};

export const parseBlobErrorMessage = async (blob: Blob): Promise<string | null> => {
  const contentType = blob.type.toLowerCase();
  const looksLikeTextError =
    contentType.includes('application/json') ||
    contentType.includes('application/problem+json') ||
    contentType.startsWith('text/');

  if (!looksLikeTextError) {
    return null;
  }

  const text = await blob.text();
  if (!text.trim()) {
    return null;
  }

  try {
    const parsed = JSON.parse(text);
    return extractMessage(parsed) ?? text.trim();
  } catch {
    return text.trim();
  }
};

export const assertBlobResponseSuccess = async (blob: Blob, fallbackMessage: string): Promise<void> => {
  const errorMessage = await parseBlobErrorMessage(blob);
  if (errorMessage) {
    throw new Error(errorMessage || fallbackMessage);
  }
};

export const throwBlobRequestError = async (error: unknown, fallbackMessage: string): Promise<never> => {
  if (axios.isAxiosError(error)) {
    const responseData = error.response?.data;

    if (responseData instanceof Blob) {
      const blobMessage = await parseBlobErrorMessage(responseData);
      if (blobMessage) {
        error.message = blobMessage;
        throw error;
      }
    }

    const responseMessage = extractMessage(responseData);
    if (responseMessage) {
      error.message = responseMessage;
      throw error;
    }

    if (error.message) {
      throw error;
    }
  }

  if (error instanceof Error && error.message) {
    throw error;
  }

  throw new Error(fallbackMessage);
};
