import type { ResponseCardProps } from '../../components/shared';
import type { PublicQueryResponse } from './query-client';

export function toPublicResponseCardProps(response: PublicQueryResponse): ResponseCardProps {
  return {
    mode: 'public',
    content: {
      heading: 'What this may mean for you',
      paragraphs: [response.explanation],
      keyPoints: [response.nextStepGuidance],
    },
    sections: response.sections.map((item) => ({
      code: '',
      section: '',
      title: item.title,
      explanation: item.explanation,
      sourceUrl: item.link,
    })),
    citations: response.sources.map((item) => ({
      title: item.title,
      sourceUrl: item.link,
    })),
  };
}
