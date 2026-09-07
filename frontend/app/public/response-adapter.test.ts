import { createElement, useState, type ChangeEvent } from 'react';
import { cleanup, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { ResponseCard } from '../../components/shared';
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

const repeatedSectionUrlFixture = {
  explanation: 'Different legal points can come from the same public source.',
  sections: [
    {
      title: 'General rights information',
      explanation: 'The first point concerns written notice.',
      link: 'https://www.indiacode.nic.in/',
    },
    {
      title: 'General rights information',
      explanation: 'The second point concerns keeping records.',
      link: 'https://www.indiacode.nic.in/',
    },
  ],
  sources: [{ title: 'India Code', link: 'https://www.indiacode.nic.in/' }],
  nextStepGuidance: 'Keep the source and your documents together.',
};

function ResponseWithDraft({ response }: { response: typeof repeatedSectionUrlFixture }) {
  const [draft, setDraft] = useState('');

  return createElement(
    'div',
    null,
    createElement('label', { htmlFor: 'response-draft' }, 'Draft check'),
    createElement('input', {
      id: 'response-draft',
      onChange: (event: ChangeEvent<HTMLInputElement>) => setDraft(event.target.value),
      value: draft,
    }),
    createElement(ResponseCard, toPublicResponseCardProps(response)),
  );
}

describe('toPublicResponseCardProps', () => {
  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
  });

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
          section: '0',
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

  it('keeps same-URL public sections distinct without duplicate-key warnings after parent rerenders', async () => {
    const user = userEvent.setup();
    const consoleError = vi.spyOn(console, 'error').mockImplementation(() => undefined);
    render(createElement(ResponseWithDraft, { response: repeatedSectionUrlFixture }));

    expect(screen.getAllByRole('heading', { name: 'General rights information' })).toHaveLength(2);
    expect(screen.getByText('The first point concerns written notice.')).toBeVisible();
    expect(screen.getByText('The second point concerns keeping records.')).toBeVisible();

    const draft = screen.getByLabelText('Draft check');
    await user.type(draft, 'Parent update');

    expect(draft).toHaveValue('Parent update');
    expect(screen.getAllByRole('heading', { name: 'General rights information' })).toHaveLength(2);
    expect(screen.getByText('The first point concerns written notice.')).toBeVisible();
    expect(screen.getByText('The second point concerns keeping records.')).toBeVisible();

    const duplicateKeyErrors = consoleError.mock.calls.filter((call) =>
      call.some(
        (argument) =>
          typeof argument === 'string' &&
          /children with the same key|unique [`\"]key[`\"]/i.test(argument),
      ),
    );
    expect(duplicateKeyErrors).toEqual([]);
  });
});
