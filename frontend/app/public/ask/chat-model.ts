import type { PublicQueryResponse } from '../query-client';
import type { PublicAnswerFailure } from '../error-copy';

export type ChatMessage =
  | { role: 'user'; kind: 'text'; content: string }
  | { role: 'user'; kind: 'file'; fileName: string }
  | { role: 'assistant'; response: PublicQueryResponse }
  | {
      role: 'assistant';
      kind: 'error';
      failure: PublicAnswerFailure;
      /** From the error's Retry-After, e.g. when today's capacity returns (step 24b). */
      retryAfterSeconds?: number;
    };

export interface ChatEntry {
  id: string;
  message: ChatMessage;
}

export interface ChatState {
  entries: ChatEntry[];
}

type UserChatEntry = ChatEntry & {
  message: Extract<ChatMessage, { role: 'user' }>;
};

type AssistantChatEntry = ChatEntry & {
  message: Extract<ChatMessage, { role: 'assistant' }>;
};

export type ChatAction =
  | { type: 'append-user'; entry: UserChatEntry }
  | { type: 'append-assistant'; entry: AssistantChatEntry }
  | { type: 'remove-error'; id: string }
  | { type: 'clear' };

export const initialChatState: ChatState = { entries: [] };

export function chatReducer(state: ChatState, action: ChatAction): ChatState {
  switch (action.type) {
    case 'append-user':
    case 'append-assistant':
      return { ...state, entries: [...state.entries, action.entry] };
    case 'remove-error':
      return {
        ...state,
        entries: state.entries.filter(
          (entry) =>
            !(
              entry.id === action.id &&
              entry.message.role === 'assistant' &&
              'kind' in entry.message &&
              entry.message.kind === 'error'
            ),
        ),
      };
    case 'clear':
      return initialChatState;
  }
}
