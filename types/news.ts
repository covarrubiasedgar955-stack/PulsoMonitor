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
}

export type NewsInput = Omit<NewsItem, "id" | "created_at" | "updated_at">;

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

export interface LoginResponse {
  access_token: string;
  token_type: "bearer";
  user: { name: string; role: string };
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
