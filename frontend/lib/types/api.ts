export type UserRole = 'lawyer' | 'admin';

export interface AuthenticatedUser {
  id: number | string;
  email: string;
  role: UserRole;
}

export interface LoginResponse {
  user: AuthenticatedUser;
  message: string;
}

export interface SectionReference {
  statute: string;
  section: string;
  confidence?: number;
  context?: string | null;
}

export interface ProfessionalPrecedent {
  document_id: number | string;
  case_name: string;
  court?: string | null;
  year?: number | null;
  relevance_score: number;
  excerpt?: string | null;
  source_url?: string | null;
  page_start?: number | null;
  page_end?: number | null;
  paragraph_start?: number | null;
  paragraph_end?: number | null;
}

export interface ProfessionalCaseBrief {
  summary: string;
  applicable_law: string[];
  key_issues: string[];
  procedural_considerations: string[];
  precedent_analysis: string[];
  limitations: string[];
}

export interface ProfessionalQueryResponse {
  identified_sections: SectionReference[];
  precedents: ProfessionalPrecedent[];
  case_brief: ProfessionalCaseBrief;
}

export interface QueryHistoryItem {
  id: number;
  mode: string;
  query_text: string;
  response_json: ProfessionalQueryResponse | Record<string, unknown> | null;
  generation_backend?: string | null;
  created_at: string;
}

export interface OffenseFrequencyPoint {
  section: string;
  year: number;
  count: number;
}

export interface OutcomeDistributionPoint {
  section: string;
  court_level: string;
  convicted: number;
  acquitted: number;
  appeal_allowed: number;
  appeal_dismissed: number;
}

export interface SectionCooccurrencePoint {
  section_a: string;
  section_b: string;
  count: number;
}

export interface IpcBnsMappingRow {
  ipc_section: string;
  ipc_description: string;
  bns_section?: string | null;
  bns_description?: string | null;
  change_type: string;
}

export interface NcrbStatPoint {
  year: number;
  state: string;
  offense_category: string;
  ipc_section?: string | null;
  case_count: number;
  conviction_count?: number | null;
  acquittal_count?: number | null;
}
