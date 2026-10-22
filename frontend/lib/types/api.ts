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

/** Identical for new and already-registered emails, so it carries no account data. */
export interface RegistrationResponse {
  email: string;
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
  /** Trusted chunk the excerpt and provenance come from. */
  chunk_id?: string | null;
  case_name: string;
  court?: string | null;
  year?: number | null;
  /** Reranker score normalized to 0-1 (sigmoid); null when no reranker score is available. */
  relevance_score: number | null;
  /** Raw reranker score. */
  reranker_score?: number | null;
  /** True when the answer cites this precedent through a validated citation. */
  cited_in_answer?: boolean;
  /** Bounded verbatim span of the trusted chunk text. */
  excerpt?: string | null;
  source_url?: string | null;
  page_start?: number | null;
  page_end?: number | null;
  paragraph_start?: number | null;
  paragraph_end?: number | null;
}

export interface ProfessionalCaseBrief {
  summary: string;
  parties_and_roles?: string[];
  material_facts?: string[];
  chronology?: string[];
  statutory_provisions?: string[];
  evidence_identified?: string[];
  applicable_law: string[];
  key_issues: string[];
  procedural_considerations: string[];
  precedent_analysis: string[];
  limitations: string[];
  recommended_research_questions?: string[];
}

/** Per-stage timings and the answering backend; present only when the backend enables LEGALAI_QUERY_DEBUG. */
export interface QueryDebugInfo {
  endpoint: string;
  timings_ms: Record<string, number>;
  backend: Record<string, string | boolean | null>;
}

export interface ProfessionalQueryResponse {
  identified_sections: SectionReference[];
  precedents: ProfessionalPrecedent[];
  case_brief: ProfessionalCaseBrief;
  debug?: QueryDebugInfo | null;
}

export interface PublicQueryResponse {
  explanation: string;
  sections: Array<{ title: string; explanation: string; link: string }>;
  sources: Array<{ title: string; link: string }>;
  nextStepGuidance: string;
  debug?: QueryDebugInfo | null;
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
  /** BNS head NCRB reports next to the IPC head, when it has one. */
  bns_section?: string | null;
  /** Null when NCRB reports no count for the row. */
  case_count: number | null;
  conviction_count?: number | null;
  acquittal_count?: number | null;
  /** True for total and subtotal rows; the API excludes them unless include_aggregates=true. */
  is_aggregate?: boolean;
  /** state_total | ut_total | all_india_total | subtotal_head | group_total, or null for a base row. */
  aggregate_type?: string | null;
}

export type AdminDocumentType = 'judgment' | 'statute' | 'other';
export type AdminIngestionStatus =
  'QUEUED' | 'EXTRACTING' | 'CHUNKING' | 'EMBEDDING' | 'INDEXING' | 'COMPLETED' | 'FAILED';
export type ServiceHealth = 'healthy' | 'degraded' | 'down';

export interface ServiceStatus {
  status: ServiceHealth;
  detail?: string;
}

export interface ReconciliationJobSummary {
  jobId: string;
  errorCode: string | null;
  /** Sanitized, admin-facing message. */
  message: string | null;
  completedAt: string | null;
}

export interface CorpusStats {
  totalDocuments: number;
  lastUpdatedTimestamp: string;
  lastIngestionDate: string;
  breakdown: Record<AdminDocumentType, number>;
  chromaDb: ServiceStatus;
  postgresql: ServiceStatus;
  /** BM25 keyword index. */
  keywordIndex: ServiceStatus;
  /** Vectors in the Chroma collection; null when the store could not be opened. */
  chromaRecordCount: number | null;
  /** Records in the BM25 keyword index; null when it could not be read. */
  keywordRecordCount: number | null;
  /** Chunks in PostgreSQL, the canonical store. */
  postgresChunkCount: number | null;
  /** Failed ingestions whose cleanup did not complete. */
  reconciliationJobCount: number;
  /** The most recent of them (at most 20). */
  reconciliationJobs: ReconciliationJobSummary[];
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
  /** Sanitized, user-safe message. */
  error?: string | null;
  /** Internal failure code, e.g. LEXICAL_INDEX_FAILED or STALE_JOB. */
  error_code?: string | null;
  /** True when cleanup after a failure did not complete; the stores need reconciliation. */
  needs_reconciliation?: boolean;
}

export interface CorpusStatsResponse {
  total_documents: number;
  last_updated: string | null;
  by_type: Array<{ doc_type: string; count: number }>;
  /** Service health: 'healthy' | 'degraded' | 'down'. */
  postgres_status: string;
  chroma_status: string;
  chroma_detail?: string | null;
  chroma_collection?: string | null;
  chroma_record_count?: number | null;
  bm25_status?: string;
  bm25_detail?: string | null;
  bm25_record_count?: number | null;
  postgres_chunk_count?: number | null;
  reconciliation_job_count?: number;
  reconciliation_jobs?: Array<{
    job_id: string;
    error_code?: string | null;
    error_message?: string | null;
    completed_at?: string | null;
  }>;
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
