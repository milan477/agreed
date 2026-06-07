// Thin client for the agreed backend API.

export const API_BASE =
  process.env.NEXT_PUBLIC_API_BASE || "http://localhost:8000";

export function getUserId(): string {
  if (typeof window === "undefined") return "demo-user";
  let u = localStorage.getItem("agreed_user");
  if (!u) {
    u = "u_" + Math.random().toString(36).slice(2, 10);
    localStorage.setItem("agreed_user", u);
  }
  return u;
}

async function req<T>(path: string, opts: RequestInit = {}): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    ...opts,
    headers: {
      "Content-Type": "application/json",
      "X-User-Id": getUserId(),
      ...(opts.headers || {}),
    },
  });
  if (!res.ok) throw new Error(`${res.status} ${await res.text()}`);
  return res.json();
}

export type Goal = {
  id: string;
  title: string;
  kind: "negotiation" | "participation";
  status: string;
  created_from_chat?: boolean;
  other_party_label?: string;
};

export type Session = {
  session_id: string;
  invite_code: string;
  host_user_id: string;
  title: string;
  kind: "negotiation" | "participation";
  status: string;
  framework: string;
  max_rounds: number;
  use_custom_agent: boolean;
  custom_agent_url?: string;
  other_party_id?: string | null;
  other_party_label?: string | null;
  parties: Record<string, { role: string; submitted: boolean; label: string }>;
  negotiation_result?: NegotiationResult | null;
  brief?: any;
  goal_id?: string;
};

export type Terms = {
  price: number;
  delivery_weeks: number;
  payment_terms: string;
  warranty_months: number;
  support_hours: number;
};

export type Score = {
  buyer_score: number;
  seller_score: number;
  joint_surplus: number;
  min_utility: number;
  utility_gap: number;
};

export type Turn = {
  round: number;
  actor: "Buyer" | "Seller";
  action: "propose" | "accept";
  terms: Terms;
  my_reasoning: string;
  buyer_utility: number;
  seller_utility: number;
  moderator_note?: string | null;
};

export type NegotiationResult = {
  outcome: string;
  deal_terms: Terms | null;
  rounds: number;
  transcript: Turn[];
  score: Score | null;
  trace_id: string;
  negotiation_id?: string;
};

export type TraceSummary = {
  trace_id: string;
  span_count: number;
  by_kind: Record<string, number>;
  weave_url: string | null;
  steps: { id: string; label: string; kind: string; category: string; duration_ms: number; detail: any }[];
};

export type HomeData = {
  user_id: string;
  profile: { intent_summary: string; style: string; constraints: string; goals: Goal[] };
  chat_history: { role: string; content: string }[];
  goals: Goal[];
  sessions: Session[];
  contacts: { user_id: string; label: string }[];
};

export const api = {
  health: () => req<any>("/api/health"),
  home: () => req<HomeData>("/api/home"),
  chat: (message: string, history: { role: string; content: string }[] = []) =>
    req<{ reply: string; profile: HomeData["profile"]; new_goals: Goal[] }>("/api/chat", {
      method: "POST",
      body: JSON.stringify({ message, history }),
    }),
  joinInvite: (link: string) =>
    req<{ session: Session; invite_url: string }>("/api/invitations/join", {
      method: "POST",
      body: JSON.stringify({ link }),
    }),
  createSession: (body: { title: string; kind: string; goal_id?: string; other_party_label?: string }) =>
    req<{ session: Session; invite_url: string }>("/api/sessions", {
      method: "POST",
      body: JSON.stringify(body),
    }),
  getSession: (id: string) =>
    req<{ session: Session; contacts: { user_id: string; label: string }[] }>(`/api/sessions/${id}`),
  updateSession: (id: string, patch: Record<string, unknown>) =>
    req<{ session: Session }>(`/api/sessions/${id}`, {
      method: "PATCH",
      body: JSON.stringify(patch),
    }),
  submitAgent: (id: string) =>
    req<{ session: Session }>(`/api/sessions/${id}/submit`, { method: "POST" }),
  frameworks: () => req<{ frameworks: { key: string; name: string; description: string }[] }>("/api/frameworks"),
  trace: (id: string) => req<TraceSummary>(`/api/trace/${id}`),
  sign: (negotiation_id: string, signature: string, party: string) =>
    req<any>("/api/agreement/sign", {
      method: "POST",
      body: JSON.stringify({ negotiation_id, signature, party }),
    }),
};
