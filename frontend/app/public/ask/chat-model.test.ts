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
          message: { role: 'assistant' as const, kind: 'error' as const, error: 'Safe copy' },
        },
        {
          id: 'turn-2-error',
          message: { role: 'assistant' as const, kind: 'error' as const, error: 'Safe copy' },
        },
      ],
    };

    const state = chatReducer(initialState, { type: 'remove-error', id: 'turn-1-error' });

    expect(state.entries.map((entry) => entry.id)).toEqual(['turn-1-user', 'turn-2-error']);
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
