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

function csrfToken(): string {
  if (typeof document === "undefined") return "";
  const match = document.cookie.match(/(?:^|;\s*)cdt_csrf=([^;]+)/);
  return match ? decodeURIComponent(match[1]) : "";
}

async function request<T>(
  method: "GET" | "POST",
  path: string,
  body?: unknown,
): Promise<T> {
  const headers: Record<string, string> = {};
  if (body !== undefined) headers["content-type"] = "application/json";
  if (method !== "GET") headers["x-csrf-token"] = csrfToken();

  const resp = await fetch(`${API_BASE}${path}`, {
    method,
    headers,
    credentials: "include",
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });

  if (!resp.ok) {
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
    throw new ApiError(resp.status, detail);
  }
  return resp.json() as Promise<T>;
}

export const api = {
  get: <T>(path: string) => request<T>("GET", path),
  post: <T>(path: string, body?: unknown) => request<T>("POST", path, body),
};

// ---------------------------------------------------------------------------
// Shared response types (mirror backend/app/schemas.py)
// ---------------------------------------------------------------------------

export interface Me {
  user_id: number;
  username: string;
  experience_level: string;
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

// EYD V: currency written without a space after "Rp", thousands with periods.
export const formatRupiah = (v: number): string =>
  "Rp" + Math.round(v).toLocaleString("id-ID");

// EYD V: decimals use a comma (0,5%), not a period.
export const formatPct = (v: number, digits = 1): string =>
  v.toFixed(digits).replace(".", ",") + "%";
