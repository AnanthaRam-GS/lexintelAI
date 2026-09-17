export type PublicQueryInput =
  { kind: 'text'; content: string } | { kind: 'file'; file: File; question: string };

export interface PublicQueryResponse {
  explanation: string;
  sections: Array<{ title: string; explanation: string; link: string }>;
  sources: Array<{ title: string; link: string }>;
  nextStepGuidance: string;
}
