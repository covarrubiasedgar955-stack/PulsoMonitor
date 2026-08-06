export type NewsStatus =
  | "Pendiente"
  | "En revisión"
  | "Programada"
  | "Publicada"
  | "Archivada";

export type NewsPriority = "Baja" | "Media" | "Alta" | "Urgente";

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
  location: string;
  latitude: number | null;
  longitude: number | null;
  location_source: "" | "manual" | "automatic" | "not_found" | "protected";
  location_confidence: number;
  location_reviewed: boolean;
}

export type NewsInput = Omit<
  NewsItem,
  "id" | "created_at" | "updated_at" | "facebook_post_id" | "scheduled_at" |
  "location_source" | "location_confidence" | "location_reviewed"
>;

export interface NewsStats {
  today: number;
  pending: number;
  published: number;
  urgent: number;
  total: number;
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
  errors: string[];
}

export interface FacebookStatus {
  connected: boolean;
  page_id: string;
  page_name: string;
  graph_version: string;
  last_sync: string | null;
  last_error: string;
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
