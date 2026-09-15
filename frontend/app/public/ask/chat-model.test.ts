import { describe, expect, it } from 'vitest';

import { chatReducer, initialChatState } from './chat-model';

describe('chatReducer', () => {
  it('keeps the required ChatMessage union in stable entry envelopes', () => {
    const state = chatReducer(initialChatState, {
      type: 'append-user',
      entry: {
        id: 'turn-1-user',
        message: { role: 'user', kind: 'text', content: 'Help me' },
      },
    });

    expect(state.entries).toEqual([
      {
        id: 'turn-1-user',
        message: { role: 'user', kind: 'text', content: 'Help me' },
      },
    ]);
  });

  it('removes only the error entry being retried', () => {
    const initialState = {
      entries: [
        {
          id: 'turn-1-user',
          message: { role: 'user' as const, kind: 'text' as const, content: 'Help me' },
        },
        {
          id: 'turn-1-error',
          message: {
            role: 'assistant' as const,
            kind: 'error' as const,
            failure: 'service' as const,
          },
        },
        {
          id: 'turn-2-error',
          message: {
            role: 'assistant' as const,
            kind: 'error' as const,
            failure: 'network' as const,
          },
        },
      ],
    };

    const state = chatReducer(initialState, { type: 'remove-error', id: 'turn-1-error' });

    expect(state.entries.map((entry) => entry.id)).toEqual(['turn-1-user', 'turn-2-error']);
  });

  it('appends an assistant response in a stable entry envelope', () => {
    const response = {
      explanation: 'Keep a copy of the notice.',
      sections: [
        {
          title: 'General legal information',
          explanation: 'The details of the document matter.',
          link: 'https://www.indiacode.nic.in/',
        },
      ],
      sources: [{ title: 'India Code', link: 'https://www.indiacode.nic.in/' }],
      nextStepGuidance: 'Keep the notice and any reply together.',
    };

    const state = chatReducer(initialChatState, {
      type: 'append-assistant',
      entry: { id: 'turn-1-assistant', message: { role: 'assistant', response } },
    });

    expect(state.entries).toEqual([
      { id: 'turn-1-assistant', message: { role: 'assistant', response } },
    ]);
  });

  it('clears the complete thread for a new conversation', () => {
    const state = chatReducer(
      {
        entries: [
          {
            id: 'turn-1-user',
            message: { role: 'user' as const, kind: 'file' as const, fileName: 'notice.pdf' },
          },
        ],
      },
      { type: 'clear' },
    );

    expect(state).toEqual({ entries: [] });
  });
});
