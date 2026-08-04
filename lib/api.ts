import type {
  AIAnalysis,
  AIAnalyzeInput,
  AIStatus,
  LoginResponse,
  NewsInput,
  NewsItem,
  NewsListResponse,
  NewsStats,
} from "@/types/news";

const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://127.0.0.1:8000";

export class ApiError extends Error {
  status: number;

  constructor(message: string, status: number) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

function token() {
  return typeof window === "undefined" ? null : localStorage.getItem("pulso_token");
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const authToken = token();
  let response: Response;
  try {
    response = await fetch(`${API_URL}${path}`, {
      ...init,
      headers: {
        "Content-Type": "application/json",
        ...(authToken ? { Authorization: `Bearer ${authToken}` } : {}),
        ...init.headers,
      },
    });
  } catch {
    throw new ApiError("No se pudo conectar con la API. Verifica que el backend esté encendido.", 0);
  }

  if (!response.ok) {
    let message = "No se pudo completar la operación.";
    try {
      const body = await response.json();
      message = body.detail || body.message || message;
    } catch {
      // The API did not return JSON.
    }
    if (response.status === 401 && typeof window !== "undefined") {
      localStorage.removeItem("pulso_token");
      window.dispatchEvent(new Event("pulso:logout"));
    }
    throw new ApiError(message, response.status);
  }

  if (response.status === 204) return undefined as T;
  return response.json() as Promise<T>;
}

export const api = {
  login(username: string, password: string) {
    return request<LoginResponse>("/api/auth/login", {
      method: "POST",
      body: JSON.stringify({ username, password }),
    });
  },

  stats() {
    return request<NewsStats>("/api/noticias/estadisticas");
  },

  listNews(params: Record<string, string | number | undefined> = {}) {
    const search = new URLSearchParams();
    Object.entries(params).forEach(([key, value]) => {
      if (value !== undefined && value !== "") search.set(key, String(value));
    });
    const query = search.toString();
    return request<NewsListResponse>(`/api/noticias${query ? `?${query}` : ""}`);
  },

  createNews(payload: NewsInput) {
    return request<NewsItem>("/api/noticias", {
      method: "POST",
      body: JSON.stringify(payload),
    });
  },

  updateNews(id: number, payload: NewsInput) {
    return request<NewsItem>(`/api/noticias/${id}`, {
      method: "PUT",
      body: JSON.stringify(payload),
    });
  },

  deleteNews(id: number) {
    return request<void>(`/api/noticias/${id}`, { method: "DELETE" });
  },

  aiStatus() {
    return request<AIStatus>("/api/ia/estado");
  },

  analyzeWithAI(payload: AIAnalyzeInput) {
    return request<AIAnalysis>("/api/ia/analizar", {
      method: "POST",
      body: JSON.stringify(payload),
    });
  },

  configureAI(apiKey: string, model = "gpt-5.6-luna") {
    return request<AIStatus>("/api/ia/configurar", {
      method: "POST",
      body: JSON.stringify({ api_key: apiKey, model }),
    });
  },
};
