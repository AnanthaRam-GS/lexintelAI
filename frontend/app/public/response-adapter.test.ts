import { describe, expect, it } from 'vitest';

import { toPublicResponseCardProps } from './response-adapter';

const responseFixture = {
  explanation: 'A written notice usually gives both sides a clear record of the issue.',
  sections: [
    {
      title: 'Indian Contract Act, 1872',
      explanation: 'A contract may set out how either side can end the arrangement.',
      link: 'https://www.indiacode.nic.in/',
    },
  ],
  sources: [{ title: 'India Code', link: 'https://www.indiacode.nic.in/' }],
  nextStepGuidance: 'Keep a copy of the notice and the agreement before you respond.',
};

describe('toPublicResponseCardProps', () => {
  it('prevents public responses from exposing professional-only ResponseCard fields', () => {
    const props = toPublicResponseCardProps(responseFixture);

    expect(props).toEqual({
      mode: 'public',
      content: {
        heading: 'What this may mean for you',
        paragraphs: ['A written notice usually gives both sides a clear record of the issue.'],
        keyPoints: ['Keep a copy of the notice and the agreement before you respond.'],
      },
      sections: [
        {
          code: '',
          section: '',
          title: 'Indian Contract Act, 1872',
          explanation: 'A contract may set out how either side can end the arrangement.',
          sourceUrl: 'https://www.indiacode.nic.in/',
        },
      ],
      citations: [{ title: 'India Code', sourceUrl: 'https://www.indiacode.nic.in/' }],
    });
    expect(props.sections[0]).not.toHaveProperty('confidence');
    expect(props.citations[0]).not.toHaveProperty('court');
    expect(props.citations[0]).not.toHaveProperty('year');
    expect(props.citations[0]).not.toHaveProperty('excerpt');
  });
});
