export interface Coordinate { latitude: number; longitude: number }
export interface SubjectIntent {
  intent_id: string; query: string; priority: number; is_primary: boolean; status: string;
  confirmed_subject_id: string | null; confirmed_subject_ids: string[];
}
export interface SubjectCandidate {
  subject_id: string; name: string; name_cn: string | null; aliases: string[];
}
export interface SubjectGroup {
  intent: SubjectIntent; candidates: SubjectCandidate[]; status: string; warning: string | null;
}
export interface SubjectAppearance { subject_id: string; evidence_ids: string[] }
export interface VisitPlace {
  place_id: string; canonical_name: string; coordinate: Coordinate;
  verification_status: string; scene_evidence_ids: string[]; subject_appearances: SubjectAppearance[];
}
export interface SceneEvidence {
  evidence_id: string; subject_id: string; names: string[]; description: string | null;
  episode_refs: string[]; image_url: string | null; source_url: string | null;
  source_label: string | null; resolution_status: string;
}
export interface WorkspaceEvidenceView {
  trip_id: string; evidence: SceneEvidence[];
  quarantined: { evidence_id: string; reason_code: string; detail: string }[];
  ambiguous_merges: unknown[];
}
export interface AreaCluster {
  area_id: string; label: string; place_ids: string[]; confidence: number;
  travel_time_status: string; warnings: string[];
}
export interface ScheduledPlace {
  place_id: string; sequence: number; start_at: string; end_at: string;
}
export interface ItineraryDay {
  date: string; visits: ScheduledPlace[]; walking_distance_meters: number; duration_minutes: number;
}
export interface ItineraryVersion {
  itinerary_id: string; version: number; parent_version?: number | null; strategy: string; days: ItineraryDay[];
  omissions: { place_id: string; reason_code: string; detail: string }[];
  validation_issues: { code: string; detail: string }[];
}
export interface WorkspaceCounts {
  raw_scene_records: number; quarantined_records: number; canonical_places: number;
  areas: number; recommended_places: number; scheduled_places: number;
}
export interface PlanPatch {
  patch_id: string; trip_id: string; expected_base_version: number; rationale: string;
  requires_confirmation: boolean; status: string; idempotency_key: string; created_at: string;
  operations: { op: string; [key: string]: unknown }[];
}
export interface WorkspaceView {
  trip_id: string; thread_id: string; state_version: number; status: string;
  requirements: { start_date: string | null; end_date: string | null; subject_intents: SubjectIntent[]; walking_preference: string | null };
  subject_groups: SubjectGroup[]; confirmed_subjects: { intent_id: string; subject: SubjectCandidate; evidence_status: string }[];
  places: VisitPlace[]; areas: AreaCluster[]; base_candidates: { base_id: string; name: string; coordinate: Coordinate }[];
  selected_base_id: string | null; candidate_graph: { evidence_status: string } | null;
  itineraries: ItineraryVersion[]; counts: WorkspaceCounts; warnings: string[];
  handoffs: { handoff_id: string; sender: string; receiver: string; task_type: string; status: string; warnings: string[] }[];
  contexts: { context_id: string; role: string; estimated_tokens: number; byte_size: number }[];
  patches: PlanPatch[]; pending_patch_id: string | null;
  impacts: { patch_id: string; invalidated_nodes: string[]; stable_refs: string[]; confirmation_required: boolean }[];
  diffs: { from_version: number; to_version: number; changed_requirements: string[]; changed_day_numbers: number[] }[];
  knowledge_rules: { rule_id: string; rule_type: string; status: string; evidence_ids: string[] }[];
}
export interface PatchPreview { workspace: WorkspaceView; preview: { patch: PlanPatch; impact: WorkspaceView["impacts"][number] } }
export interface ConversationMessage {
  message_id: string; role: "user" | "assistant"; content: string; intent: string; created_at: string;
}
export interface WorkspaceConversationResponse {
  trip_id: string; messages: ConversationMessage[]; assistant_message: ConversationMessage;
  workspace: WorkspaceView; preview: PatchPreview["preview"] | null;
}
