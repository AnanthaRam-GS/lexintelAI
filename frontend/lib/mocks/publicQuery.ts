export type PublicQueryInput = { kind: 'text'; content: string } | { kind: 'file'; file: File };

export interface PublicQueryResponse {
  explanation: string;
  sections: Array<{ title: string; explanation: string; link: string }>;
  sources: Array<{ title: string; link: string }>;
  nextStepGuidance: string;
}

const publicSources = [
  {
    title: 'India Code',
    link: 'https://www.indiacode.nic.in/',
  },
];

const publicSections = [
  {
    title: 'General legal information',
    explanation:
      'The laws that apply depend on your specific facts, documents, and the place where the issue occurred.',
    link: 'https://www.indiacode.nic.in/',
  },
];

function getMockDelay(): number {
  const configuredDelay = Number(process.env.NEXT_PUBLIC_LEGALAI_PUBLIC_QUERY_MOCK_DELAY_MS);

  if (Number.isFinite(configuredDelay) && configuredDelay >= 0) {
    return configuredDelay;
  }

  return 800 + Math.floor(Math.random() * 701);
}

function wait(delayMs: number): Promise<void> {
  return new Promise((resolve) => {
    setTimeout(resolve, delayMs);
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

// TODO(contract): confirm against backend/app/models/ and delete this mock once
// POST /query/public is exposed through frontend/lib/api.ts. Consumers must then
// change only this import, not their state shape or rendering logic.
export async function fetchPublicQueryMock(input: PublicQueryInput): Promise<PublicQueryResponse> {
  assertPublicQueryInput(input);
  await wait(getMockDelay());

  if (process.env.NEXT_PUBLIC_LEGALAI_PUBLIC_QUERY_MOCK_FAILURE === 'true') {
    throw new Error('Public query mock failed.');
  }

  return {
    explanation:
      input.kind === 'file'
        ? 'This is general legal information to help you understand the PDF you shared.'
        : 'This is general legal information to help you understand the question you raised.',
    sections: publicSections,
    sources: publicSources,
    nextStepGuidance:
      'Keep copies of the relevant documents and consider speaking with a qualified legal professional about your situation.',
  };
}
