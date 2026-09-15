import { apiFetch } from '../../lib/api';
import type { PublicQueryInput, PublicQueryResponse } from './query-contract';

export type { PublicQueryInput, PublicQueryResponse } from './query-contract';

interface PublicQueryRequest {
  text: string;
}

export async function fetchPublicQuery(input: PublicQueryInput): Promise<PublicQueryResponse> {
  assertPublicQueryInput(input);

  if (input.kind === 'file') {
    throw new Error('Public PDF query is not available yet.');
  }

  const text = input.content.trim();
  if (!text) {
    throw new Error('Public query text must not be empty.');
  }

  return apiFetch<PublicQueryResponse>('/query/public', {
    method: 'POST',
    body: JSON.stringify({ text } satisfies PublicQueryRequest),
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
