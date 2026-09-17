import { apiFetch, publicQueryApi } from '../../lib/api';
import type { PublicQueryInput, PublicQueryResponse } from './query-contract';

export type { PublicQueryInput, PublicQueryResponse } from './query-contract';

interface PublicQueryRequest {
  text: string;
}

interface PublicQueryOptions {
  signal?: AbortSignal;
}

export async function fetchPublicQuery(
  input: PublicQueryInput,
  options: PublicQueryOptions = {},
): Promise<PublicQueryResponse> {
  assertPublicQueryInput(input);

  if (input.kind === 'file') {
    const query = 'Explain the key legal information in this document';
    return publicQueryApi.submitPdf(input.file, query);
  }

  const text = input.content.trim();
  if (!text) {
    throw new Error('Public query text must not be empty.');
  }

  return apiFetch<PublicQueryResponse>('/query/public', {
    method: 'POST',
    body: JSON.stringify({ text } satisfies PublicQueryRequest),
    signal: options.signal,
  });
}

function assertPublicQueryInput(input: unknown): asserts input is PublicQueryInput {
  if (
    !input ||
    typeof input !== 'object' ||
    !('kind' in input) ||
    (input.kind !== 'text' && input.kind !== 'file')
  ) {
    throw new Error('Public query input must have a text or file kind.');
  }
}
