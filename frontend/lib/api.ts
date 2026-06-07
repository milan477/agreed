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
  from_connector?: string;
  other_party_label?: string;
};

export type DimTarget = { target?: number | string; walk_away?: number | string; importance?: number };
export type Targets = Record<string, DimTarget>;
export type Viewpoint = { topic: string; stance: string; priority?: number };

export type Session = {
  session_id: string;
  invite_code: string;
  host_user_id: string;
  title: string;
  kind: "negotiation" | "participation";
  account_type?: "individual" | "corporation";
  status: string;
  framework: string;
  max_rounds: number;
  use_custom_agent: boolean;
  custom_agent_url?: string;
  interaction_mode?: "structured" | "textual";
  targets?: Targets | null;
  viewpoints?: Viewpoint[] | null;
  other_party_id?: string | null;
  other_party_label?: string | null;
  tentative_agreements?: TentativeAgreement[];
  parties: Record<string, { role: string; submitted: boolean; label: string }>;
  negotiation_result?: NegotiationResult | null;
  brief?: {
    ranked_priorities: string[];
    walk_away_points?: Record<string, unknown>;
    opening_position?: Record<string, unknown>;
    research_findings?: { title: string; snippet: string }[];
    research_heading?: string;
    strategy?: string;
  } | null;
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

export type ConversationMessage = {
  round: number;
  speaker: string;
  side: "you" | "them";
  action: string;
  text: string;
  terms?: Terms;
};

export type NegotiationResult = {
  outcome: string;
  mode?: "structured" | "textual";
  deal_terms: Terms | null;
  agreement_terms?: Terms | null;
  agreement_text?: string | null;
  summary?: string;
  rounds: number;
  messages?: ConversationMessage[];
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

export type LearnedFact = { summary: string; detail: string; source?: string };

export type Profile = {
  intent_summary: string;
  style: string;
  constraints: string;
  goals: Goal[];
  account_type?: "individual" | "corporation";
  voice_sample?: string;
  phone?: string;
  email?: string;
  preferred_channel?: "text" | "call" | "auto";
  outreach_enabled?: boolean;
  followup_delay_minutes?: number;
  connections?: string[];
  learned_facts?: LearnedFact[];
  counterparties?: string[];
  tone_hint?: string;
};

export type Connector = { id: string; name: string; kind: string; icon: string; blurb: string };

export type Intent =
  | { detected: false }
  | {
      detected: true;
      summary: string;
      kind: "negotiation" | "participation";
      goal_id: string;
      confidence: number;
      needs_confirmation: boolean;
      prompt: string;
    };

export type ChatResult = {
  reply: string;
  profile: Profile;
  new_goals: Goal[];
  intent?: Intent;
  suggested_questions?: string[];
  followup_scheduled?: Followup | null;
  conversation_id?: string;
};

export type Followup = {
  id: string;
  channel: "text" | "call" | "auto";
  purpose: string;
  open_question?: string;
  scheduled_at: number;
  status: string;
  sent_at?: number;
};

export type TentativeAgreement = {
  id: string;
  text: string;
  status: "tentative" | "accepted" | "rejected";
  added_by?: string;
};

export type ConversationSummary = {
  conversation_id: string;
  title: string;
  preview: string;
  message_count: number;
  created_at: number;
  updated_at: number;
};

export type HomeData = {
  user_id: string;
  profile: Profile;
  chat_history: { role: string; content: string }[];
  active_conversation_id?: string;
  conversations?: ConversationSummary[];
  goals: Goal[];
  sessions: Session[];
  contacts: { user_id: string; label: string }[];
  followups?: Followup[];
};

export const api = {
  health: () => req<{ status: string; capabilities: Record<string, string>; weave_url?: string }>("/api/health"),
  home: () => req<HomeData>("/api/home"),
  conversations: () => req<{ conversations: ConversationSummary[] }>("/api/conversations"),
  createConversation: () =>
    req<{ conversation: { conversation_id: string; title: string; messages: { role: string; content: string }[] } }>(
      "/api/conversations",
      { method: "POST" }
    ),
  activateConversation: (conversationId: string) =>
    req<{ conversation: { conversation_id: string; messages: { role: string; content: string }[] } }>(
      `/api/conversations/${conversationId}/activate`,
      { method: "POST" }
    ),
  chat: (
    message: string,
    history: { role: string; content: string }[] = [],
    conversationId?: string
  ) =>
    req<ChatResult>("/api/chat", {
      method: "POST",
      body: JSON.stringify({ message, history, conversation_id: conversationId }),
    }),
  connectors: () => req<{ connectors: Connector[]; connected: string[] }>("/api/connectors"),
  connect: (id: string) =>
    req<{ profile: Profile; learned: { agent_line: string; facts: LearnedFact[] }; new_goals: Goal[] }>(
      `/api/connectors/${id}/connect`,
      { method: "POST" }
    ),
  draftMessage: (purpose: string, recipient = "", channel = "text") =>
    req<{ draft: string }>("/api/message/draft", {
      method: "POST",
      body: JSON.stringify({ purpose, recipient, channel }),
    }),
  sendMessage: (recipient: string, body: string, channel = "text") =>
    req<{ sent?: boolean; started?: boolean; simulated?: boolean; error?: string; note?: string }>(
      "/api/message/send",
      { method: "POST", body: JSON.stringify({ recipient, body, channel }) }
    ),
  addTentative: (id: string, text: string) =>
    req<{ session: Session }>(`/api/sessions/${id}/tentative`, {
      method: "POST",
      body: JSON.stringify({ text }),
    }),
  setTentativeStatus: (id: string, item_id: string, status: string) =>
    req<{ session: Session }>(`/api/sessions/${id}/tentative`, {
      method: "PATCH",
      body: JSON.stringify({ item_id, status }),
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
  chooseAgent: (id: string, use_custom_agent: boolean, custom_agent_url = "") =>
    req<{ session: Session }>(`/api/sessions/${id}/agent-choice`, {
      method: "POST",
      body: JSON.stringify({ use_custom_agent, custom_agent_url }),
    }),
  saveProbe: (
    id: string,
    body: { targets?: Targets; viewpoints?: Viewpoint[]; interaction_mode?: string }
  ) =>
    req<{ session: Session }>(`/api/sessions/${id}/probe`, {
      method: "POST",
      body: JSON.stringify(body),
    }),
  setAccountType: (account_type: "individual" | "corporation") =>
    req<{ profile: Profile }>("/api/account-type", {
      method: "POST",
      body: JSON.stringify({ account_type }),
    }),
  updateContact: (body: {
    phone?: string;
    email?: string;
    preferred_channel?: string;
    outreach_enabled?: boolean;
    followup_delay_minutes?: number;
  }) =>
    req<{ profile: Profile }>("/api/profile/contact", {
      method: "PATCH",
      body: JSON.stringify(body),
    }),
  scheduleFollowup: (body: { channel?: string; purpose: string; delay_minutes?: number }) =>
    req<{ followup: Followup }>("/api/followups/schedule", {
      method: "POST",
      body: JSON.stringify(body),
    }),
  selfImprove: (party = "Buyer", framework = "pareto") =>
    req<{
      diagnosis: Record<string, unknown>;
      optimization: {
        improvement: number;
        baseline_metric: number;
        improved_metric: number;
        improved_strategy: Record<string, unknown>;
      };
    }>("/api/self-improve", {
      method: "POST",
      body: JSON.stringify({ party, framework }),
    }),
  evals: (framework = "pareto", n = 5) =>
    req<{ deal_closure_rate: number; avg_joint_surplus: number }>(`/api/evals?framework=${framework}&n=${n}`),
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
