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
