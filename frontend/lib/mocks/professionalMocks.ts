import type {
  AuthenticatedUser,
  IpcBnsMappingRow,
  NcrbStatPoint,
  OffenseFrequencyPoint,
  OutcomeDistributionPoint,
  ProfessionalQueryResponse,
  QueryHistoryItem,
  SectionCooccurrencePoint,
} from '../types/api';

export const mockLawyerUser: AuthenticatedUser = {
  id: 101,
  email: 'counsel.verma@highcourt.nic.in',
  role: 'lawyer',
};

export const mockAdminUser: AuthenticatedUser = {
  id: 1,
  email: 'admin.sharma@legalai.gov.in',
  role: 'admin',
};

export const mockProfessionalQueryResponse: ProfessionalQueryResponse = {
  identified_sections: [
    {
      statute: 'Indian Penal Code, 1860',
      section: 'Section 302',
      confidence: 0.96,
      context:
        'Punishment for murder; requires clear establishment of mens rea and fatal injury intention.',
    },
    {
      statute: 'Bharatiya Nyaya Sanhita, 2023',
      section: 'Section 103(1)',
      confidence: 0.94,
      context:
        'Corresponding provision under the new penal code for murder, maintaining requisite intention threshold.',
    },
    {
      statute: 'Code of Criminal Procedure, 1973',
      section: 'Section 437',
      confidence: 0.88,
      context:
        'When bail may be taken in cases of non-bailable offences, with special provisos for health and infirmity.',
    },
    {
      statute: 'Bharatiya Nagarik Suraksha Sanhita, 2023',
      section: 'Section 480',
      confidence: 0.85,
      context:
        'Corresponding regular bail provisions in non-bailable cases under the procedural enactment.',
    },
  ],
  precedents: [
    {
      document_id: 'SC_2023_CRIM_492',
      case_name: 'Sharad Birdhichand Sarda v. State of Maharashtra',
      court: 'Supreme Court of India',
      year: 1984,
      relevance_score: 0.95,
      excerpt:
        'In circumstantial evidence cases, the circumstances from which the conclusion of guilt is drawn must be fully established, and the facts so established should be consistent only with the hypothesis of the guilt of the accused.',
      source_url: 'https://main.sci.gov.in/judgments/1984/SC_1984_CRIM_162.pdf',
      page_start: 14,
      page_end: 18,
      paragraph_start: 152,
      paragraph_end: 158,
    },
    {
      document_id: 'SC_2021_CRIM_108',
      case_name: 'Satender Kumar Antil v. Central Bureau of Investigation',
      court: 'Supreme Court of India',
      year: 2022,
      relevance_score: 0.91,
      excerpt:
        'Bail is the rule and jail is an exception. The investigating agencies and courts must adhere to procedural safeguards against arbitrary arrest, particularly when continuous custodial interrogation is unwarranted.',
      source_url: 'https://main.sci.gov.in/judgments/2022/SC_2022_CRIM_874.pdf',
      page_start: 8,
      page_end: 12,
      paragraph_start: 35,
      paragraph_end: 42,
    },
    {
      document_id: 'DEL_HC_2024_CRIM_77',
      case_name: 'State (NCT of Delhi) v. Rajesh Kumar & Anr.',
      court: 'Delhi High Court',
      year: 2024,
      relevance_score: 0.87,
      excerpt:
        'Where recovery of the alleged weapon is made without independent pancha witnesses and without corroborative forensic ballistic reports, reliance solely on recovery memos cannot substantiate a conviction under Section 302.',
      source_url: 'https://delhihighcourt.nic.in/judgments/2024/DEL_HC_CRIM_77.pdf',
      page_start: 6,
      page_end: 9,
      paragraph_start: 19,
      paragraph_end: 25,
    },
  ],
  case_brief: {
    summary:
      'The matter concerns an application for regular bail in a criminal proceeding involving circumstantial evidence under Section 302 IPC (and transition Section 103 BNS). The prosecution relies predominantly on circumstantial last-seen recovery evidence without direct eyewitness testimony or corroborated forensic recovery.',
    applicable_law: [
      'Section 302, Indian Penal Code, 1860 (Punishment for murder)',
      'Section 103(1), Bharatiya Nyaya Sanhita, 2023 (Murder)',
      'Section 437 / 439, Code of Criminal Procedure, 1973 (Bail powers in non-bailable offences)',
      'Section 480 / 483, Bharatiya Nagarik Suraksha Sanhita, 2023',
      'Section 27, Indian Evidence Act, 1872 (Discovery statement admissibility)',
    ],
    key_issues: [
      'Whether the circumstantial chain of events satisfies the five golden principles (Panchsheel) laid down in Sharad Birdhichand Sarda.',
      'Whether recovery under Section 27 Evidence Act without independent witnesses can sustain custodial detention pending trial.',
      'Whether prolonged pre-trial incarceration without framing of charges violates Article 21 rights under the Satender Kumar Antil doctrine.',
    ],
    procedural_considerations: [
      'Charge sheet has been filed within statutory limitation period, extinguishing Section 167(2) default bail claims.',
      'Medical condition records must be supported by government hospital medical board certification to satisfy the Section 437 proviso.',
      'Ensure bail petition addresses Section 480 BNSS procedural terminology where charge framing occurred post-July 1, 2024.',
    ],
    precedent_analysis: [
      'Sharad Birdhichand Sarda (1984 SC): Establishes that each circumstantial link must be conclusively proved and point singularly towards the guilt of the accused.',
      'Satender Kumar Antil (2022 SC): Categorizes offences into Category A–D; while Category B includes heinous crimes, trial delay and completed investigation favor bail with stringent conditions.',
      'State v. Rajesh Kumar (2024 Del HC): Reiterates that uncorroborated recovery of weapon from an accessible open place weakens the circumstantial link.',
    ],
    limitations: [
      'Gravity of allegation under Section 302 IPC limits discretion under Section 437 unless exceptional health or prolonged trial delay grounds are demonstrated.',
      'Adverse witness statements under Section 164 CrPC / 183 BNSS have not been formally cross-examined at this pre-trial stage.',
      'Presence of prior criminal antecedents would immediately defeat bail discretion.',
    ],
  },
};

export const mockOffenseFrequencyData: OffenseFrequencyPoint[] = [
  { section: 'IPC 302', year: 2019, count: 28941 },
  { section: 'IPC 302', year: 2020, count: 29193 },
  { section: 'IPC 302', year: 2021, count: 29272 },
  { section: 'IPC 302', year: 2022, count: 28522 },
  { section: 'IPC 302', year: 2023, count: 27810 },
  { section: 'IPC 420', year: 2019, count: 112450 },
  { section: 'IPC 420', year: 2020, count: 121080 },
  { section: 'IPC 420', year: 2021, count: 136920 },
  { section: 'IPC 420', year: 2022, count: 148500 },
  { section: 'IPC 420', year: 2023, count: 154210 },
  { section: 'IPC 376', year: 2019, count: 32033 },
  { section: 'IPC 376', year: 2020, count: 28046 },
  { section: 'IPC 376', year: 2021, count: 31677 },
  { section: 'IPC 376', year: 2022, count: 31516 },
  { section: 'IPC 376', year: 2023, count: 29890 },
  { section: 'IPC 307', year: 2019, count: 52400 },
  { section: 'IPC 307', year: 2020, count: 54100 },
  { section: 'IPC 307', year: 2021, count: 56900 },
  { section: 'IPC 307', year: 2022, count: 55400 },
  { section: 'IPC 307', year: 2023, count: 53800 },
];

export const mockOutcomeDistributionData: OutcomeDistributionPoint[] = [
  {
    section: 'IPC 302 (Murder)',
    court_level: 'Sessions Court',
    convicted: 12450,
    acquitted: 18200,
    appeal_allowed: 0,
    appeal_dismissed: 0,
  },
  {
    section: 'IPC 302 (Murder)',
    court_level: 'High Court',
    convicted: 4800,
    acquitted: 3200,
    appeal_allowed: 3950,
    appeal_dismissed: 5200,
  },
  {
    section: 'IPC 302 (Murder)',
    court_level: 'Supreme Court',
    convicted: 1100,
    acquitted: 950,
    appeal_allowed: 1420,
    appeal_dismissed: 2150,
  },
  {
    section: 'IPC 420 (Cheating)',
    court_level: 'Sessions Court',
    convicted: 28400,
    acquitted: 41200,
    appeal_allowed: 0,
    appeal_dismissed: 0,
  },
  {
    section: 'IPC 420 (Cheating)',
    court_level: 'High Court',
    convicted: 8200,
    acquitted: 6400,
    appeal_allowed: 9100,
    appeal_dismissed: 11200,
  },
  {
    section: 'IPC 420 (Cheating)',
    court_level: 'Supreme Court',
    convicted: 1850,
    acquitted: 1400,
    appeal_allowed: 2300,
    appeal_dismissed: 3100,
  },
];

export const mockSectionCooccurrenceData: SectionCooccurrencePoint[] = [
  { section_a: 'IPC 302', section_b: 'IPC 120B (Criminal Conspiracy)', count: 18450 },
  { section_a: 'IPC 302', section_b: 'IPC 34 (Common Intention)', count: 24300 },
  { section_a: 'IPC 302', section_b: 'IPC 201 (Disappearance of Evidence)', count: 12890 },
  { section_a: 'IPC 420', section_b: 'IPC 468 (Forgery for Cheating)', count: 34100 },
  { section_a: 'IPC 420', section_b: 'IPC 471 (Using Forged Document)', count: 32540 },
  { section_a: 'IPC 420', section_b: 'IPC 120B (Criminal Conspiracy)', count: 29800 },
  { section_a: 'IPC 376', section_b: 'IPC 506 (Criminal Intimidation)', count: 21400 },
  { section_a: 'IPC 307', section_b: 'Arms Act Sec 25/27', count: 19600 },
];

export const mockIpcBnsMappingData: IpcBnsMappingRow[] = [
  {
    ipc_section: 'Section 302',
    ipc_description: 'Punishment for murder (death or life imprisonment)',
    bns_section: 'Section 103(1)',
    bns_description:
      'Murder punished with death or imprisonment for life; Section 103(2) covers mob lynching',
    change_type: 'Substantive Expansion',
    source: 'CYTRAIN',
  },
  {
    ipc_section: 'Section 420',
    ipc_description: 'Cheating and dishonestly inducing delivery of property',
    bns_section: 'Section 318(4)',
    bns_description: 'Consolidated under Chapter on Offences Against Property',
    change_type: 'Relocated & Consolidated',
    source: 'CYTRAIN',
  },
  {
    ipc_section: 'Section 124A',
    ipc_description: 'Sedition (bringing hatred or disaffection towards government)',
    bns_section: 'Section 152',
    bns_description:
      'Act endangering sovereignty, unity and integrity of India (omits sedition terminology)',
    change_type: 'Substantive Replacement',
    source: 'CYTRAIN',
  },
  {
    ipc_section: 'Section 376',
    ipc_description: 'Punishment for rape and aggravated forms',
    bns_section: 'Section 64',
    bns_description:
      'Consolidated under Offences Against Women and Children with enhanced minimum penalties',
    change_type: 'Substantive Modification',
    source: 'CYTRAIN',
  },
  {
    ipc_section: 'Section 304A',
    ipc_description: 'Causing death by rash or negligent act',
    bns_section: 'Section 106(1)',
    bns_description:
      'Negligent acts causing death; 106(2) provides severe penalty for hit-and-run without reporting',
    change_type: 'Substantive Expansion',
    source: 'CYTRAIN',
  },
  {
    ipc_section: 'Section 498A',
    ipc_description: 'Husband or relative of husband subjecting woman to cruelty',
    bns_section: 'Section 85 / 86',
    bns_description:
      'Cruelty defined separately with objective mental and physical distress criteria',
    change_type: 'Bifurcated & Clarified',
    source: 'CYTRAIN',
  },
];

export const mockNcrbStatData: NcrbStatPoint[] = [
  {
    year: 2022,
    state: 'Maharashtra',
    offense_category: 'Economic Offences',
    ipc_section: 'IPC 420',
    case_count: 15480,
    conviction_count: 3210,
    acquittal_count: 5120,
  },
  {
    year: 2022,
    state: 'Uttar Pradesh',
    offense_category: 'Violent Crimes',
    ipc_section: 'IPC 302',
    case_count: 4497,
    conviction_count: 2180,
    acquittal_count: 1490,
  },
  {
    year: 2022,
    state: 'Delhi',
    offense_category: 'Crimes Against Women',
    ipc_section: 'IPC 376',
    case_count: 14227,
    conviction_count: 3450,
    acquittal_count: 6100,
  },
  {
    year: 2022,
    state: 'Karnataka',
    offense_category: 'Cyber Crimes',
    ipc_section: 'IT Act & IPC 420',
    case_count: 12556,
    conviction_count: 940,
    acquittal_count: 2450,
  },
  {
    year: 2022,
    state: 'West Bengal',
    offense_category: 'Violent Crimes',
    ipc_section: 'IPC 307',
    case_count: 11200,
    conviction_count: 2310,
    acquittal_count: 4120,
  },
];

export const mockQueryHistoryData: QueryHistoryItem[] = [
  {
    id: 901,
    mode: 'text',
    query_text:
      'Circumstantial evidence murder case bail grounds under Section 437 CrPC / 480 BNSS where weapon recovery lacks independent pancha witnesses.',
    response_json: mockProfessionalQueryResponse,
    generation_backend: 'Legal RAG + InLegalBERT',
    created_at: '2026-09-14T10:45:00Z',
  },
  {
    id: 902,
    mode: 'pdf',
    query_text: 'Brief_State_v_Verma_FIR_241_2024_Bail_Appeal.pdf',
    response_json: mockProfessionalQueryResponse,
    generation_backend: 'Legal RAG + Section Reranker',
    created_at: '2026-09-13T16:20:00Z',
  },
  {
    id: 903,
    mode: 'text',
    query_text:
      'Quashing petition under Section 482 CrPC for commercial dispute dishonestly converted into criminal breach of trust under Section 406/420 IPC.',
    response_json: mockProfessionalQueryResponse,
    generation_backend: 'Legal RAG + Hybrid Dense-BM25',
    created_at: '2026-09-12T11:15:00Z',
  },
  {
    id: 904,
    mode: 'pdf',
    query_text: 'SLP_Crl_Commercial_Breach_Memorandum_2024.pdf',
    response_json: mockProfessionalQueryResponse,
    generation_backend: 'Legal RAG + InLegalBERT',
    created_at: '2026-09-11T09:30:00Z',
  },
  {
    id: 905,
    mode: 'text',
    query_text:
      'Validity of search and seizure under NDPS Act Section 50 without informing option of gazetted officer or magistrate.',
    response_json: mockProfessionalQueryResponse,
    generation_backend: 'Legal RAG + InLegalBERT',
    created_at: '2026-09-10T14:50:00Z',
  },
];
