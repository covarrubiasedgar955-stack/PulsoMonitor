import type {
  ActivityItem,
  AIAnalysis,
  AIAnalyzeInput,
  AIStatus,
  AnalyticsReport,
  AppSettings,
  AutomationJob,
  AutomationKey,
  BackupInfo,
  CalendarResponse,
  EditorialAction,
  EditorialBatchResult,
  EditorialBoard,
  EditorialItem,
  FacebookPostList,
  FacebookPrepareResult,
  FacebookPublishResult,
  FacebookStatus,
  FacebookSyncResult,
  GeolocationBatchResult,
  LoginResponse,
  MapIncidentList,
  MapStats,
  Municipality,
  MunicipalityInput,
  NewsInput,
  NewsItem,
  NewsListResponse,
  NewsStats,
  RadarItemList,
  RadarScanResult,
  RadarSource,
  RadarSourceInput,
  RadarStats,
  SystemNotification,
  UserCreateInput,
  UserInfo,
  UserRecord,
  UserUpdateInput,
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

function repairMojibake(value: string): string {
  if (!/[ÃÂ]/.test(value)) return value;
  try {
    const bytes = Uint8Array.from(value, (character) => character.charCodeAt(0));
    return new TextDecoder("utf-8", { fatal: true }).decode(bytes);
  } catch {
    return value;
  }
}

function normalizeApiData(value: unknown): unknown {
  if (typeof value === "string") return repairMojibake(value);
  if (Array.isArray(value)) return value.map(normalizeApiData);
  if (value && typeof value === "object") {
    return Object.fromEntries(
      Object.entries(value).map(([key, item]) => [key, normalizeApiData(item)]),
    );
  }
  return value;
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
      const body = normalizeApiData(await response.json()) as { detail?: string; message?: string };
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
  return normalizeApiData(await response.json()) as T;
}

export const api = {
  login(username: string, password: string) {
    return request<LoginResponse>("/api/auth/login", {
      method: "POST",
      body: JSON.stringify({ username, password }),
    });
  },

  currentUser() {
    return request<UserInfo>("/api/auth/me");
  },

  editorialTeam() {
    return request<UserInfo[]>("/api/equipo-editorial");
  },

  listUsers() {
    return request<UserRecord[]>("/api/usuarios");
  },

  createUser(payload: UserCreateInput) {
    return request<UserRecord>("/api/usuarios", {
      method: "POST",
      body: JSON.stringify(payload),
    });
  },

  updateUser(id: number, payload: UserUpdateInput) {
    return request<UserRecord>(`/api/usuarios/${id}`, {
      method: "PUT",
      body: JSON.stringify(payload),
    });
  },

  updateUserPassword(id: number, password: string) {
    return request<void>(`/api/usuarios/${id}/contrasena`, {
      method: "PUT",
      body: JSON.stringify({ password }),
    });
  },

  getSettings() {
    return request<AppSettings>("/api/configuracion");
  },

  updateSettings(payload: AppSettings) {
    return request<AppSettings>("/api/configuracion", {
      method: "PUT",
      body: JSON.stringify(payload),
    });
  },

  listActivity(limit = 30) {
    return request<ActivityItem[]>(`/api/configuracion/actividad?limit=${limit}`);
  },

  listBackups() {
    return request<BackupInfo[]>("/api/configuracion/respaldos");
  },

  createBackup() {
    return request<BackupInfo>("/api/configuracion/respaldos", { method: "POST" });
  },

  listAutomations() {
    return request<AutomationJob[]>("/api/automatizaciones");
  },

  updateAutomation(key: AutomationKey, enabled: boolean, intervalMinutes: number) {
    return request<AutomationJob>(`/api/automatizaciones/${key}`, {
      method: "PUT",
      body: JSON.stringify({ enabled, interval_minutes: intervalMinutes }),
    });
  },

  executeAutomation(key: AutomationKey) {
    return request<AutomationJob>(`/api/automatizaciones/${key}/ejecutar`, { method: "POST" });
  },

  listNotifications(unreadOnly = false) {
    return request<SystemNotification[]>(`/api/notificaciones?unread_only=${unreadOnly}&limit=50`);
  },

  markNotificationsRead() {
    return request<void>("/api/notificaciones/leer", { method: "POST" });
  },

  async downloadBackup(filename: string) {
    const authToken = token();
    const response = await fetch(`${API_URL}/api/configuracion/respaldos/${encodeURIComponent(filename)}`, {
      headers: authToken ? { Authorization: `Bearer ${authToken}` } : {},
    });
    if (!response.ok) throw new ApiError("No se pudo descargar el respaldo.", response.status);
    const url = URL.createObjectURL(await response.blob());
    const link = document.createElement("a");
    link.href = url;
    link.download = filename;
    link.click();
    URL.revokeObjectURL(url);
  },

  stats() {
    return request<NewsStats>("/api/noticias/estadisticas");
  },

  analytics(days = 30) {
    return request<AnalyticsReport>(`/api/estadisticas?days=${days}`);
  },

  async downloadAnalytics(days = 30) {
    const authToken = token();
    const response = await fetch(`${API_URL}/api/estadisticas/exportar.csv?days=${days}`, {
      headers: authToken ? { Authorization: `Bearer ${authToken}` } : {},
    });
    if (!response.ok) throw new ApiError("No se pudo exportar el reporte.", response.status);
    const disposition = response.headers.get("Content-Disposition") || "";
    const filename = disposition.match(/filename="?([^";]+)"?/i)?.[1] || `pulso-monitor-${days}d.csv`;
    const url = URL.createObjectURL(await response.blob());
    const link = document.createElement("a");
    link.href = url;
    link.download = filename;
    link.click();
    URL.revokeObjectURL(url);
  },

  calendar(start: string, end: string) {
    const search = new URLSearchParams({ start, end });
    return request<CalendarResponse>(`/api/calendario?${search.toString()}`);
  },

  planNews(id: number, plannedAt: string | null) {
    return request<NewsItem>(`/api/noticias/${id}/plan-editorial`, {
      method: "PUT",
      body: JSON.stringify({ planned_at: plannedAt }),
    });
  },

  editorialBoard(state = "", assignedTo?: number, municipality = "", sort = "priority_desc", imageFilter = "all", query = "", priority = "", category = "", page = 1, pageSize = 20) {
    const search = new URLSearchParams();
    if (state) search.set("state", state);
    if (assignedTo !== undefined) search.set("assigned_to", String(assignedTo));
    if (municipality) search.set("municipality", municipality);
    if (sort) search.set("sort", sort);
    if (imageFilter !== "all") search.set("image_filter", imageFilter);
    if (query) search.set("search", query);
    if (priority) search.set("priority", priority);
    if (category) search.set("category", category);
    search.set("page", String(page));
    search.set("page_size", String(pageSize));
    return request<EditorialBoard>(`/api/flujo-editorial${search.size ? `?${search.toString()}` : ""}`);
  },

  updateEditorialFlow(id: number, action: EditorialAction, assignedTo: number | null = null, note = "") {
    return request<EditorialItem>(`/api/noticias/${id}/flujo-editorial`, {
      method: "PUT",
      body: JSON.stringify({ action, assigned_to: assignedTo, note }),
    });
  },

  updateEditorialBatch(action: "assign" | "archive" | "delete", newsIds: number[], assignedTo: number | null = null) {
    return request<EditorialBatchResult>("/api/flujo-editorial/lote", {
      method: "POST",
      body: JSON.stringify({ action, news_ids: newsIds, assigned_to: assignedTo }),
    });
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

  listMunicipalities() {
    return request<Municipality[]>("/api/municipios");
  },

  createMunicipality(payload: MunicipalityInput) {
    return request<Municipality>("/api/municipios", {
      method: "POST",
      body: JSON.stringify(payload),
    });
  },

  updateMunicipality(id: number, payload: MunicipalityInput) {
    return request<Municipality>(`/api/municipios/${id}`, {
      method: "PUT",
      body: JSON.stringify(payload),
    });
  },

  deleteMunicipality(id: number) {
    return request<void>(`/api/municipios/${id}`, { method: "DELETE" });
  },

  mapStats() {
    return request<MapStats>("/api/mapa/estadisticas");
  },

  listMapIncidents(params: Record<string, string | number | undefined> = {}) {
    const search = new URLSearchParams();
    Object.entries(params).forEach(([key, value]) => {
      if (value !== undefined && value !== "") search.set(key, String(value));
    });
    const query = search.toString();
    return request<MapIncidentList>(`/api/mapa/incidencias${query ? `?${query}` : ""}`);
  },

  setNewsLocation(id: number, location: string, latitude: number, longitude: number) {
    return request<NewsItem>(`/api/noticias/${id}/ubicacion`, {
      method: "PUT",
      body: JSON.stringify({ location, latitude, longitude }),
    });
  },

  clearNewsLocation(id: number) {
    return request<NewsItem>(`/api/noticias/${id}/ubicacion`, { method: "DELETE" });
  },

  confirmNewsLocation(id: number) {
    return request<NewsItem>(`/api/noticias/${id}/ubicacion/confirmar`, { method: "POST" });
  },

  autoGeolocateNews(limit = 20, retryFailed = false) {
    return request<GeolocationBatchResult>("/api/mapa/geolocalizar", {
      method: "POST",
      body: JSON.stringify({ limit, retry_failed: retryFailed, news_ids: [] }),
    });
  },

  publishNewsToFacebook(id: number, scheduledAt: string | null = null) {
    return request<FacebookPublishResult>(`/api/noticias/${id}/publicar-facebook`, {
      method: "POST",
      body: JSON.stringify({ scheduled_at: scheduledAt }),
    });
  },

  cancelFacebookSchedule(id: number) {
    return request<NewsItem>(`/api/noticias/${id}/programacion-facebook`, { method: "DELETE" });
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

  radarStats() {
    return request<RadarStats>("/api/radar/estadisticas");
  },

  listRadarSources() {
    return request<RadarSource[]>("/api/radar/fuentes");
  },

  createRadarSource(payload: RadarSourceInput) {
    return request<RadarSource>("/api/radar/fuentes", {
      method: "POST",
      body: JSON.stringify(payload),
    });
  },

  updateRadarSource(id: number, payload: RadarSourceInput) {
    return request<RadarSource>(`/api/radar/fuentes/${id}`, {
      method: "PUT",
      body: JSON.stringify(payload),
    });
  },

  deleteRadarSource(id: number) {
    return request<void>(`/api/radar/fuentes/${id}`, { method: "DELETE" });
  },

  scanRadar(sourceId?: number) {
    const query = sourceId ? `?source_id=${sourceId}` : "";
    return request<RadarScanResult>(`/api/radar/escanear${query}`, { method: "POST" });
  },

  listRadarItems(pendingOnly = false) {
    return request<RadarItemList>(`/api/radar/hallazgos?pending_only=${pendingOnly}&limit=100`);
  },

  importRadarItem(id: number) {
    return request<NewsItem>(`/api/radar/hallazgos/${id}/importar`, { method: "POST" });
  },

  facebookStatus() {
    return request<FacebookStatus>("/api/facebook/estado");
  },

  connectFacebook(pageId: string, pageAccessToken: string) {
    return request<FacebookStatus>("/api/facebook/conectar", {
      method: "POST",
      body: JSON.stringify({ page_id: pageId, page_access_token: pageAccessToken }),
    });
  },

  disconnectFacebook() {
    return request<void>("/api/facebook/conexion", { method: "DELETE" });
  },

  syncFacebook() {
    return request<FacebookSyncResult>("/api/facebook/sincronizar", { method: "POST" });
  },

  listFacebookPosts(pendingOnly = true) {
    return request<FacebookPostList>(`/api/facebook/publicaciones?pending_only=${pendingOnly}&limit=100`);
  },

  importFacebookPost(id: number) {
    return request<NewsItem>(`/api/facebook/publicaciones/${id}/importar`, { method: "POST" });
  },

  prepareFacebookPost(id: number) {
    return request<FacebookPrepareResult>(`/api/facebook/publicaciones/${id}/preparar`, { method: "POST" });
  },
};
