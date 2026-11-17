export type Role = "admin" | "investigator" | "analyst";

export interface User {
  id: string;
  username: string;
  full_name: string;
  role: Role;
  is_active: boolean;
  created_at?: string;
}

export const DOC_TYPES = [
  "FIR",
  "Witness Statement",
  "Investigation Report",
  "Evidence Report",
  "Charge Sheet",
  "Legal Document",
  "Other",
] as const;
export type DocType = (typeof DOC_TYPES)[number];

export type DocStatus = "uploaded" | "extracting" | "ocr" | "chunking" | "embedding" | "indexed" | "failed";

export interface DocumentItem {
  id: string;
  title: string;
  original_filename: string;
  file_ext: string;
  mime_type: string;
  size_bytes: number;
  sha256: string;
  doc_type: DocType;
  case_id: string | null;
  case_number: string | null;
  incident_date: string | null;
  police_station: string | null;
  district: string | null;
  language: string | null;
  classification: string;
  page_count: number;
  ocr_pages: number[];
  status: DocStatus;
  status_detail: string | null;
  error_message: string | null;
  processing_seconds: number | null;
  chunk_count: number;
  embedding_model: string | null;
  metadata: Record<string, unknown>;
  created_at: string;
  updated_at?: string;
  can_modify?: boolean;
}

export interface CaseItem {
  id: string;
  case_number: string;
  title: string;
  description: string;
  police_station: string | null;
  district: string | null;
  status: string;
  document_count: number | null;
  created_at: string;
  documents?: DocumentItem[];
  members?: { id: string; username: string; full_name: string; role: Role }[];
}

export interface Citation {
  label: string;
  chunk_id: string | null;
  document_id: string | null;
  document_title: string;
  filename?: string;
  doc_type?: string;
  page: number;
  passage: string;
  support: number | null;
  verified?: boolean;
}

export interface Source {
  label: string;
  chunk_id: string;
  document_id: string;
  document_title: string;
  filename: string;
  doc_type: string;
  page_start: number;
  page_end: number;
  heading: string | null;
  section_number: string | null;
  text: string;
  scores: Record<string, number>;
}

export interface Message {
  id: string;
  role: "user" | "assistant";
  content: string;
  abstained: boolean;
  created_at: string;
  citations: Citation[];
  retrieval: {
    config?: string;
    sources?: Source[];
    warnings?: string[];
    unsupported_sentences?: string[];
    timings_ms?: Record<string, number>;
    retrieval?: { stage_counts?: Record<string, number>; timings_ms?: Record<string, number> };
    llm_error?: string | null;
  };
}

export interface Conversation {
  id: string;
  title: string;
  case_id: string | null;
  created_at: string;
  updated_at: string;
  messages?: Message[];
}

export interface Entity {
  id: string;
  document_id: string;
  document_title: string | null;
  entity_type: string;
  value: string;
  normalized_value: string;
  page: number;
  context: string;
  method: string;
  confidence: number;
  verification_status: string;
  chunk_id: string | null;
}

export interface TimelineEvent {
  date: string | null;
  time: string | null;
  time_text: string | null;
  description: string;
  document_id: string;
  document_title: string;
  doc_type: string;
  page: number;
  nature: string;
  category: string | null;
  people: string[];
  locations: string[];
  flags: string[];
}

export interface Conflict {
  type: string;
  category: string;
  message: string;
  versions: { value: string; document_title: string; document_id: string; page: number; nature: string; passage: string }[];
}

export interface Timeline {
  events: TimelineEvent[];
  conflicts: Conflict[];
  flags: string[];
}

export interface ReportItem {
  id: string;
  report_type: string;
  title: string;
  status: "generating" | "draft" | "human_verified" | "failed";
  case_id: string | null;
  created_at: string;
  progress?: string | null;
  error?: string | null;
  content?: any; // eslint-disable-line @typescript-eslint/no-explicit-any
}
