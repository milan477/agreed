"use client";

import { useEffect, useState } from "react";
import { useCopilotReadable, useCopilotAction } from "@copilotkit/react-core";
import { api, HomeData } from "@/lib/api";

// Wires the agreed platform into CopilotKit: it exposes the user's context as a
// readable so the copilot represents them accurately, and registers real actions
// the copilot can take on their behalf (open a negotiation, learn from an app,
// text someone). Only mounted when the assistant is enabled, so the offline demo
// is unaffected.
export function CopilotBridge() {
  const [home, setHome] = useState<HomeData | null>(null);
  const reload = () => api.home().then(setHome).catch(() => undefined);
  useEffect(() => {
    reload();
  }, []);

  useCopilotReadable({
    description:
      "The user's profile, goals, and active sessions on agreed. Always negotiate/represent in their voice and within these constraints.",
    value: home
      ? {
          account_type: home.profile.account_type,
          style: home.profile.style,
          constraints: home.profile.constraints,
          voice_sample: home.profile.voice_sample,
          goals: home.goals,
          connections: home.profile.connections,
          sessions: home.sessions.map((s) => ({ id: s.session_id, title: s.title, kind: s.kind, status: s.status })),
        }
      : "loading the user's context…",
  });

  useCopilotAction({
    name: "openNegotiation",
    description: "Open a new negotiation (or community participation) on the user's behalf and take them to it.",
    parameters: [
      { name: "title", type: "string", description: "What the deal or topic is", required: true },
      { name: "kind", type: "string", description: "'negotiation' or 'participation'", required: false },
    ],
    handler: async ({ title, kind }) => {
      const k = kind === "participation" ? "participation" : "negotiation";
      const r = await api.createSession({ title, kind: k });
      window.dispatchEvent(new CustomEvent("agreed:refresh"));
      if (typeof window !== "undefined") window.location.href = `/session/${r.session.session_id}`;
      return `Opened “${title}” as a ${k}.`;
    },
  });

  useCopilotAction({
    name: "learnFromApp",
    description:
      "Connect one of the user's apps so the agent can learn about them automatically. id must be one of: gmail, notion, gcal, contacts.",
    parameters: [{ name: "id", type: "string", description: "connector id", required: true }],
    handler: async ({ id }) => {
      const r = await api.connect(id);
      window.dispatchEvent(new CustomEvent("agreed:refresh"));
      reload();
      return r.learned?.agent_line || `Connected ${id} and learned a few things.`;
    },
  });

  useCopilotAction({
    name: "textForUser",
    description: "Draft a message in the user's own voice and send it as an iMessage on their behalf.",
    parameters: [
      { name: "recipient", type: "string", description: "phone number or Apple ID", required: true },
      { name: "purpose", type: "string", description: "what the message should accomplish", required: true },
    ],
    handler: async ({ recipient, purpose }) => {
      const d = await api.draftMessage(purpose, recipient, "text");
      const r = await api.sendMessage(recipient, d.draft, "text");
      const how = r.simulated ? "simulated a send" : "sent it";
      return `Drafted in your voice and ${how} to ${recipient}: “${d.draft}”`;
    },
  });

  return null;
}
