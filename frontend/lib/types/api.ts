export type UserRole = 'public' | 'admin' | 'lawyer';

export interface AuthenticatedUser {
  id: number | string;
  email: string;
  role: UserRole;
  full_name?: string | null;
  email_verified?: boolean;
}

export interface LoginResponse {
  user: AuthenticatedUser;
  message: string;
}

export interface RegistrationResponse {
  user: AuthenticatedUser;
  message: string;
  email_verification_required: boolean;
  dev_verification_otp?: string | null;
}

export interface EmailVerificationResponse {
  email_verified: boolean;
  message: string;
  dev_verification_otp?: string | null;
  expires_at?: string | null;
}

export interface SectionReference {
  statute: string;
  section: string;
  confidence?: number | null;
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

export interface PublicQueryResponse {
  explanation: string;
  sections: Array<{ title: string; explanation: string; link: string }>;
  sources: Array<{ title: string; link: string }>;
  nextStepGuidance: string;
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

export type AdminDocumentType = 'judgment' | 'statute' | 'other';
export type AdminIngestionStatus =
  'QUEUED' | 'EXTRACTING' | 'CHUNKING' | 'EMBEDDING' | 'INDEXING' | 'COMPLETED' | 'FAILED';
export type ServiceHealth = 'healthy' | 'degraded' | 'down';

export interface ServiceStatus {
  status: ServiceHealth;
  detail?: string;
}

export interface CorpusStats {
  totalDocuments: number;
  lastUpdatedTimestamp: string;
  lastIngestionDate: string;
  breakdown: Record<AdminDocumentType, number>;
  chromaDb: ServiceStatus;
  postgresql: ServiceStatus;
}

export interface AdminIngestionMetadata {
  documentType: AdminDocumentType;
  courtLevel?: string;
  year?: number;
  sourceUrl?: string;
  caseName?: string;
}

export interface AdminIngestionUploadResponse {
  job_id: string;
  status: AdminIngestionStatus;
}

export interface AdminIngestionStatusResponse {
  job_id: string;
  status: AdminIngestionStatus;
  progress: number;
  document_id?: number | string | null;
  chunk_count?: number | null;
  error?: string | null;
}

export interface CorpusStatsResponse {
  total_documents: number;
  last_updated: string | null;
  by_type: Array<{ doc_type: string; count: number }>;
  postgres_status: string;
  chroma_status: string;
}

export type LawyerApplicationStatus =
  'PENDING' | 'UNDER_REVIEW' | 'VERIFIED' | 'REJECTED' | 'RESUBMISSION_REQUIRED' | 'SUSPENDED';

export interface LawyerApplication {
  id: number;
  user_id: number;
  bar_council: string;
  enrollment_number: string;
  enrollment_year: number;
  jurisdiction: string;
  organization?: string | null;
  proof_file_name: string;
  proof_content_type: string;
  status: LawyerApplicationStatus;
  submitted_at: string;
  reviewed_at?: string | null;
  review_note?: string | null;
}

export interface LawyerApplicationEnvelope {
  application: LawyerApplication | null;
}

export interface AdminLawyerApplication extends LawyerApplication {
  applicant_email: string;
  applicant_name?: string | null;
  reviewed_by?: number | null;
}

export interface AdminLawyerApplicationList {
  applications: AdminLawyerApplication[];
}
