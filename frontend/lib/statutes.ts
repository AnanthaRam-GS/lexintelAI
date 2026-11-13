/**
 * Exact statute recognition for display (step 27).
 *
 * A statute string from the API ("BNSS", "Bharatiya Nagarik Suraksha Sanhita, 2023", "Cr.P.C.", "Evidence Act") is
 * normalized and compared as a whole name against a fixed list of codes and full names. Nothing is matched as a
 * substring, so no code can match as a prefix of another ("BNS" never matches "BNSS"; "IPC" never matches a word
 * that merely contains those letters).
 */

export type StatuteCode =
  'IPC' | 'BNS' | 'BNSS' | 'CrPC' | 'BSA' | 'Evidence Act' | 'NDPS Act' | 'POCSO Act' | 'SC/ST Act';

/** Every accepted spelling, already in normalized form (see `normalizeStatute`). */
const NAMES: Record<StatuteCode, string[]> = {
  IPC: ['ipc', 'indian penal code', 'penal code'],
  BNS: ['bns', 'bharatiya nyaya sanhita'],
  BNSS: ['bnss', 'bharatiya nagarik suraksha sanhita'],
  CrPC: ['crpc', 'code of criminal procedure', 'criminal procedure code'],
  BSA: ['bsa', 'bharatiya sakshya adhiniyam'],
  'Evidence Act': ['evidence act', 'indian evidence act', 'iea'],
  'NDPS Act': ['ndps', 'ndps act', 'narcotic drugs and psychotropic substances act'],
  'POCSO Act': ['pocso', 'pocso act', 'protection of children from sexual offences act'],
  'SC/ST Act': [
    'sc/st',
    'sc/st act',
    'scheduled castes and the scheduled tribes (prevention of atrocities) act',
    'scheduled castes and scheduled tribes (prevention of atrocities) act',
  ],
};

const LOOKUP = new Map<string, StatuteCode>(
  (Object.entries(NAMES) as [StatuteCode, string[]][]).flatMap(([code, names]) =>
    names.map((name) => [name, code] as const),
  ),
);

/**
 * Lower case, dots removed ("Cr.P.C." -> "crpc"), a leading "the" and a trailing year (", 1973") dropped, spaces
 * collapsed.
 */
export function normalizeStatute(value: string): string {
  return value
    .toLowerCase()
    .replace(/\./g, '')
    .replace(/\s+/g, ' ')
    .trim()
    .replace(/^the /, '')
    .replace(/,?\s*(18|19|20)\d{2}$/, '')
    .trim();
}

/**
 * The statute's code, or null when the string is not one of the known statutes. A full name followed by its
 * abbreviation in parentheses ("Bharatiya Nagarik Suraksha Sanhita (BNSS)") is read by its full name.
 */
export function statuteCode(value: string | null | undefined): StatuteCode | null {
  if (!value) return null;
  const normalized = normalizeStatute(value);
  const direct = LOOKUP.get(normalized);
  if (direct) return direct;
  const withoutParenthetical = normalizeStatute(normalized.replace(/\s*\([^)]*\)\s*$/, ''));
  return withoutParenthetical !== normalized ? (LOOKUP.get(withoutParenthetical) ?? null) : null;
}
