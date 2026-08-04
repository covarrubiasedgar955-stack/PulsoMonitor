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
