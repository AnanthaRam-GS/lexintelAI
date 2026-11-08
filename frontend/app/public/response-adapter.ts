import type { LegalSection, ResponseCardProps } from '../../components/shared';
import { sectionLabelParts } from '../../lib/section-labels';
import type { PublicQueryResponse } from './query-client';

export function toPublicResponseCardProps(response: PublicQueryResponse): ResponseCardProps {
  return {
    mode: 'public',
    content: {
      heading: 'What this may mean for you',
      paragraphs: [response.explanation],
      keyPoints: [response.nextStepGuidance],
    },
    sections: response.sections.map((item, index) => publicSection(item, index)),
    citations: response.sources.map((item) => ({
      title: item.title,
      sourceUrl: item.link,
    })),
    limitations: response.limitations ?? [],
  };
}

type PublicSectionPayload = PublicQueryResponse['sections'][number];

/**
 * Step 25: a section the answer named shows its resolved label (the trusted title, or the answer's wording marked
 * unverified); one with several sections keeps the backend's display title, which already carries the markers.
 */
function publicSection(item: PublicSectionPayload, index: number): LegalSection {
  const base = {
    code: '',
    section: String(index),
    explanation: item.explanation,
    sourceUrl: item.link,
  };
  const references = item.references ?? [];
  if (references.length !== 1) return { ...base, title: item.title };
  const parts = sectionLabelParts(references[0]);
  return {
    ...base,
    title: parts.text ? `${parts.heading} — ${parts.text}` : parts.heading,
    labelMarker: parts.marker,
    labelNote: parts.note,
  };
}
