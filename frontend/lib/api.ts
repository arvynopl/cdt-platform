/**
 * lib/api.ts — typed fetch wrapper for the CDT Platform API.
 *
 * Contract with the backend (see backend/app/security/sessions.py):
 *  - Auth rides on the httpOnly `cdt_session` cookie → every call uses
 *    `credentials: "include"`.
 *  - Mutations require the CSRF double-submit header `X-CSRF-Token`,
 *    mirrored from the JS-readable `cdt_csrf` cookie.
 */

const API_BASE =
  process.env.NEXT_PUBLIC_API_BASE ?? "http://localhost:8000";

export class ApiError extends Error {
  constructor(
    public status: number,
    public detail: string,
  ) {
    super(detail);
    this.name = "ApiError";
  }
}

// The CSRF double-submit token. In a cross-site deployment (frontend and API
// on different domains) the browser stores the `cdt_csrf` cookie against the
// API's domain, so `document.cookie` here can't read it. The auth responses
// (login / register / me) therefore return the token in their body; we cache it
// and prefer the cache, falling back to the cookie for same-site/local dev.
let csrfCache: string | null = null;

function csrfToken(): string {
  if (csrfCache) return csrfCache;
  if (typeof document === "undefined") return "";
  const match = document.cookie.match(/(?:^|;\s*)cdt_csrf=([^;]+)/);
  return match ? decodeURIComponent(match[1]) : "";
}

async function detailFromResponse(resp: Response): Promise<string> {
  let detail = `HTTP ${resp.status}`;
  try {
    const data = await resp.json();
    if (typeof data?.detail === "string") detail = data.detail;
    else if (Array.isArray(data?.detail))
      detail = data.detail
        .map((d: { msg?: string }) => d.msg ?? "")
        .join("; ");
  } catch {
    /* non-JSON error body */
  }
  return detail;
}

async function request<T>(
  method: "GET" | "POST",
  path: string,
  body?: unknown,
  extraHeaders?: Record<string, string>,
): Promise<T> {
  const headers: Record<string, string> = { ...(extraHeaders ?? {}) };
  if (body !== undefined) headers["content-type"] = "application/json";
  if (method !== "GET") headers["x-csrf-token"] = csrfToken();

  const resp = await fetch(`${API_BASE}${path}`, {
    method,
    headers,
    credentials: "include",
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });

  if (!resp.ok) throw new ApiError(resp.status, await detailFromResponse(resp));
  const data = await resp.json();
  // Auth responses carry the CSRF token in their body; cache it for the header
  // on subsequent mutations (see csrfToken).
  if (data && typeof data.csrf_token === "string" && data.csrf_token) {
    csrfCache = data.csrf_token;
  }
  return data as T;
}

export const api = {
  get: <T>(path: string, extraHeaders?: Record<string, string>) =>
    request<T>("GET", path, undefined, extraHeaders),
  post: <T>(path: string, body?: unknown) => request<T>("POST", path, body),
};

/**
 * Download a keyed CSV endpoint as a file. The researcher/admin endpoints
 * authenticate on a request header (not the session cookie), so an anchor
 * `href` can't carry the key — we fetch with the header, then save the blob.
 */
export async function keyedDownload(
  path: string,
  headers: Record<string, string>,
  filename: string,
): Promise<void> {
  const resp = await fetch(`${API_BASE}${path}`, { method: "GET", headers });
  if (!resp.ok) throw new ApiError(resp.status, await detailFromResponse(resp));
  const blob = await resp.blob();
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}

// ---------------------------------------------------------------------------
// Shared response types (mirror backend/app/schemas.py)
// ---------------------------------------------------------------------------

export interface Me {
  user_id: number;
  username: string;
  experience_level: string;
  csrf_token?: string;
}

export interface OnboardingSurvey {
  dei_q1: number; dei_q2: number; dei_q3: number;
  ocs_q1: number; ocs_q2: number; ocs_q3: number;
  lai_q1: number; lai_q2: number; lai_q3: number;
}

export interface RegisterPayload {
  username: string;
  password: string;
  full_name: string;
  age: number;
  gender: "laki-laki" | "perempuan" | "lainnya";
  risk_profile: "konservatif" | "moderat" | "agresif";
  investing_capability: "pemula" | "menengah" | "berpengalaman";
  onboarding_survey: OnboardingSurvey;
  consent: boolean;
}

// ---------------------------------------------------------------------------
// Simulation types (mirror backend/app/services/simulation.py payloads)
// ---------------------------------------------------------------------------

export interface WindowRow {
  id: number;
  date: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
  ma_5: number | null;
  ma_20: number | null;
  rsi_14: number | null;
  trend: string | null;
  daily_return: number | null;
}

export interface StockMeta {
  stock_id: string;
  ticker: string;
  name: string;
  sector: string;
  volatility_class: string;
}

export interface Holding {
  stock_id: string;
  quantity: number;
  avg_price: number;
  current_price: number;
}

export interface PortfolioState {
  cash: number;
  total_value: number;
  realized_pnl: number;
  holdings: Holding[];
  sold_trade_count: number;
}

export interface SessionState {
  session_id: string;
  resumed: boolean;
  stocks: StockMeta[];
  current_round: number;
  rounds_total: number;
  rounds_complete: boolean;
  window_start_date: string;
  window_end_date: string;
  stock_ids: string[];
  window: Record<string, WindowRow[]>;
  pre_window_history: Record<string, Partial<WindowRow>[]>;
  portfolio: PortfolioState;
}

export interface Order {
  stock_id: string;
  action: "buy" | "sell";
  quantity: number;
}

export interface RoundResult {
  session_id: string;
  round_number: number;
  errors: string[];
  next_round: number;
  rounds_complete: boolean;
  portfolio: PortfolioState;
}

export interface AnalysisStatus {
  session_id: string;
  status: "in_progress" | "processing" | "completed" | "error";
  rounds_completed: number;
  rounds_total: number;
}

export interface FeedbackItem {
  bias_type: string;
  severity: string;
  explanation_text: string | null;
  recommendation_text: string | null;
}

export interface SessionResults {
  session_id: string;
  final_portfolio_value: number | null;
  initial_capital: number;
  metric: {
    overconfidence_score: number | null;
    disposition_pgr: number | null;
    disposition_plr: number | null;
    disposition_dei: number | null;
    loss_aversion_index: number | null;
    dei_ci: [number | null, number | null];
    ocs_ci: [number | null, number | null];
    lai_ci: [number | null, number | null];
    ci_low_confidence: boolean;
  };
  feedback: FeedbackItem[];
}

// ---------------------------------------------------------------------------
// Profile types (mirror backend/app/routers/profile.py payload)
// ---------------------------------------------------------------------------

export interface MetricPoint {
  session_num: number;
  session_id: string;
  ocs: number;
  dei: number;
  dei_raw: number;
  pgr: number;
  plr: number;
  lai_norm: number;
  lai_raw: number;
  computed_at: string | null;
}

export interface CdtSnapshotPoint {
  session_number: number;
  cdt_overconfidence: number;
  cdt_disposition: number;
  cdt_loss_aversion: number;
  cdt_risk_preference: number;
  cdt_stability_index: number;
}

export interface BiasVector {
  overconfidence: number;
  disposition: number;
  loss_aversion: number;
}

export interface ThresholdSet {
  dei: number;
  ocs: number;
  lai: number;
}

export interface ProfileResponse {
  profile: {
    bias_intensity_vector: BiasVector;
    risk_preference: number;
    stability_index: number;
    session_count: number;
    interaction_scores: Record<string, number | null> | null;
    last_updated_at: string | null;
  } | null;
  metrics: MetricPoint[];
  cdt_snapshots: CdtSnapshotPoint[];
  thresholds: {
    scientific: ThresholdSet;
    personal: { values: ThresholdSet; is_fallback: boolean } | null;
  };
}

export interface HistoryResponse {
  rows: Record<string, unknown>[];
}

// ---------------------------------------------------------------------------
// Researcher dashboard types (mirror backend/modules/utils/research_export.py
// and backend/app/routers/researcher.py). These endpoints are key-gated on
// request headers (X-Researcher-Key / X-Admin-Token), not the session cookie.
// ---------------------------------------------------------------------------

export interface CohortSummary {
  total_users: number;
  total_sessions: number;
  users_with_consent: number;
  users_with_survey: number;
  users_with_min_3_sessions: number;
  mean_dei: number;
  sd_dei: number;
  mean_ocs: number;
  sd_ocs: number;
  mean_lai: number;
  sd_lai: number;
  mean_stability_index: number;
  completion_rate: number;
  excluded_non_participants: number;
}

export interface ProgressionRow {
  bias: "dei" | "ocs" | "lai";
  session_number: number;
  values: number[];
  n: number;
}

export interface ProgressionResponse {
  progression: ProgressionRow[];
}

export interface MlPerformance {
  available: boolean;
  summary: Record<string, unknown> | null;
  classification_report: Record<string, string>[] | null;
  feature_importance_path: string | null;
  decision_tree_path: string | null;
  generated_at: string | null;
}

export interface AdminSummary {
  total_users: number;
  total_sessions: number;
  sessions_by_status: Record<string, number>;
  completed_sessions: number;
  completion_rate: number;
  total_bias_metrics: number;
  total_session_errors: number;
  error_rate_per_session: number;
  total_uat_feedback: number;
  avg_sus_score: number | null;
}

// EYD V: currency written without a space after "Rp", thousands with periods.
export const formatRupiah = (v: number): string =>
  "Rp" + Math.round(v).toLocaleString("id-ID");

// EYD V: decimals use a comma (0,5%), not a period.
export const formatPct = (v: number, digits = 1): string =>
  v.toFixed(digits).replace(".", ",") + "%";
