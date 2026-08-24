export type NewsStatus =
  | "Pendiente"
  | "En revisión"
  | "Programada"
  | "Publicada"
  | "Archivada";

export type NewsPriority = "Baja" | "Media" | "Alta" | "Urgente";
export type EditorialState = "Borrador" | "En revisión" | "Aprobada" | "Cambios solicitados";

export interface NewsItem {
  id: number;
  title: string;
  summary: string;
  content: string;
  source: string;
  author: string;
  municipality: string;
  category: string;
  priority: NewsPriority;
  status: NewsStatus;
  image_url: string;
  url: string;
  published_at: string | null;
  created_at: string;
  updated_at: string;
  is_ai: boolean;
  tags: string[];
  facebook_post_id: string;
  scheduled_at: string | null;
  planned_at: string | null;
  editorial_state: EditorialState;
  assigned_to: number | null;
  review_note: string;
  review_requested_at: string | null;
  approved_at: string | null;
  approved_by: number | null;
  location: string;
  latitude: number | null;
  longitude: number | null;
  location_source: "" | "manual" | "automatic" | "not_found" | "protected";
  location_confidence: number;
  location_reviewed: boolean;
}

export type NewsInput = Omit<
  NewsItem,
  "id" | "created_at" | "updated_at" | "facebook_post_id" | "scheduled_at" | "planned_at" |
  "editorial_state" | "assigned_to" | "review_note" | "review_requested_at" | "approved_at" | "approved_by" |
  "location_source" | "location_confidence" | "location_reviewed"
>;

export interface EditorialItem extends NewsItem {
  assigned_name: string;
  approved_by_name: string;
}

export interface EditorialBoard {
  items: EditorialItem[];
  total: number;
  page: number;
  page_size: number;
  drafts: number;
  review: number;
  approved: number;
  changes: number;
}

export type EditorialAction = "assign" | "request_review" | "approve" | "request_changes" | "reopen";

export interface EditorialBatchResult {
  requested: number;
  updated: number;
  protected: number;
}

export interface NewsStats {
  today: number;
  pending: number;
  published: number;
  urgent: number;
  total: number;
}

export interface AnalyticsPoint {
  label: string;
  value: number;
}

export interface AnalyticsTrendPoint {
  date: string;
  created: number;
  published: number;
}

export interface AnalyticsSummary {
  period_days: number;
  created: number;
  previous_created: number;
  created_change: number;
  published: number;
  pending: number;
  urgent: number;
  ai_created: number;
  mapped: number;
  publication_rate: number;
  ai_rate: number;
  mapped_rate: number;
}

export interface AnalyticsReport {
  generated_at: string;
  summary: AnalyticsSummary;
  trend: AnalyticsTrendPoint[];
  statuses: AnalyticsPoint[];
  categories: AnalyticsPoint[];
  municipalities: AnalyticsPoint[];
  sources: AnalyticsPoint[];
}

export type CalendarDateSource = "planned" | "scheduled" | "published" | "created";

export interface CalendarItem {
  id: number;
  title: string;
  summary: string;
  municipality: string;
  category: string;
  priority: NewsPriority;
  status: NewsStatus;
  event_at: string;
  date_source: CalendarDateSource;
  planned_at: string | null;
  scheduled_at: string | null;
  published_at: string | null;
  facebook_post_id: string;
}

export interface CalendarResponse {
  items: CalendarItem[];
  total: number;
  pending: number;
  scheduled: number;
  published: number;
  urgent: number;
}

export interface NewsListResponse {
  items: NewsItem[];
  total: number;
}

export interface MunicipalityInput {
  name: string;
  region: string;
  state: string;
  active: boolean;
}

export interface Municipality extends MunicipalityInput {
  id: number;
  created_at: string;
  updated_at: string;
  news: number;
  pending: number;
  published: number;
  urgent: number;
  radar_sources: number;
}

export interface MapIncident {
  id: number;
  title: string;
  summary: string;
  municipality: string;
  category: string;
  priority: NewsPriority;
  status: NewsStatus;
  location: string;
  latitude: number;
  longitude: number;
  location_source: string;
  location_confidence: number;
  location_reviewed: boolean;
  created_at: string;
}

export interface MapIncidentList {
  items: MapIncident[];
  total: number;
}

export interface MapStats {
  news: number;
  mapped: number;
  unmapped: number;
  urgent: number;
  review_pending: number;
}

export interface GeolocationBatchResult {
  processed: number;
  located: number;
  review_pending: number;
  not_found: number;
  protected: number;
  errors: string[];
}

export interface LoginResponse {
  access_token: string;
  token_type: "bearer";
  user: UserInfo;
}

export type UserRole = "Administrador" | "Editor" | "Reportero";

export interface UserInfo {
  id: number;
  username: string;
  name: string;
  role: UserRole;
}

export interface UserRecord extends UserInfo {
  active: boolean;
  last_login: string | null;
  created_at: string;
  updated_at: string;
}

export interface UserCreateInput {
  username: string;
  name: string;
  role: UserRole;
  password: string;
  active: boolean;
}

export interface UserUpdateInput {
  name: string;
  role: UserRole;
  active: boolean;
}

export interface AppSettings {
  media_name: string;
  tagline: string;
  default_municipality: string;
  contact_email: string;
  updated_at: string;
}

export interface ActivityItem {
  id: number;
  user_name: string;
  action: string;
  entity: string;
  entity_id: string;
  detail: string;
  created_at: string;
}

export interface BackupInfo {
  name: string;
  size: number;
  created_at: string;
}

export type AutomationKey = "facebook" | "radar" | "geolocation" | "images" | "backup" | "cleanup";

export interface AutomationJob {
  key: AutomationKey;
  label: string;
  description: string;
  enabled: boolean;
  interval_minutes: number;
  last_run: string | null;
  next_run: string | null;
  last_status: "idle" | "running" | "success" | "error";
  last_message: string;
  updated_at: string;
}

export interface SystemNotification {
  id: number;
  level: "success" | "error" | "info";
  title: string;
  message: string;
  job_key: string;
  is_read: boolean;
  created_at: string;
}

export type AITone = "Informativo" | "Urgente" | "Institucional" | "Cercano";

export interface AIAnalyzeInput {
  source_text: string;
  municipality: string;
  source: string;
  tone: AITone;
}

export interface AIAnalysis {
  title: string;
  summary: string;
  content: string;
  category: string;
  priority: NewsPriority;
  tags: string[];
  confidence: number;
  warnings: string[];
  provider: "openai" | "local";
  model: string | null;
}

export interface AIStatus {
  connected: boolean;
  provider: "openai" | "local";
  model: string;
}

export interface RadarSourceInput {
  name: string;
  url: string;
  municipality: string;
  category: string;
  enabled: boolean;
}

export interface RadarSource extends RadarSourceInput {
  id: number;
  managed: boolean;
  auto_import: boolean;
  consecutive_errors: number;
  last_scan: string | null;
  last_error: string;
  created_at: string;
  updated_at: string;
  findings: number;
  pending: number;
}

export interface RadarItem {
  id: number;
  source_id: number;
  source_name: string;
  municipality: string;
  category: string;
  title: string;
  summary: string;
  image_url: string;
  url: string;
  published_at: string | null;
  detected_at: string;
  imported_news_id: number | null;
}

export interface RadarItemList {
  items: RadarItem[];
  total: number;
}

export interface RadarStats {
  sources: number;
  active_sources: number;
  findings: number;
  pending: number;
  imported: number;
}

export interface RadarScanResult {
  scanned_sources: number;
  detected: number;
  imported: number;
  cleaned: number;
  errors: string[];
}

export interface FacebookStatus {
  connected: boolean;
  page_id: string;
  page_name: string;
  graph_version: string;
  last_sync: string | null;
  last_error: string;
  health: "disconnected" | "ok" | "network" | "token_expired" | "permissions" | "page_error" | "unknown";
  health_message: string;
  needs_reconnect: boolean;
  checked_at: string | null;
  posts: number;
  pending: number;
  imported: number;
}

export interface FacebookPost {
  id: number;
  external_id: string;
  message: string;
  permalink_url: string;
  picture_url: string;
  created_time: string | null;
  detected_at: string;
  imported_news_id: number | null;
}

export interface FacebookPostList {
  items: FacebookPost[];
  total: number;
}

export interface FacebookSyncResult {
  detected: number;
  total_received: number;
}

export interface FacebookPrepareResult {
  news: NewsItem;
  provider: "openai" | "local";
  model: string | null;
  confidence: number;
  warnings: string[];
}

export interface FacebookPublishResult {
  news: NewsItem;
  facebook_post_id: string;
  scheduled: boolean;
}
