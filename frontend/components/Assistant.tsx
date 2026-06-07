"use client";

import { CopilotKit } from "@copilotkit/react-core";
import { CopilotPopup } from "@copilotkit/react-ui";
import "@copilotkit/react-ui/styles.css";
import { CopilotBridge } from "./CopilotBridge";

// CopilotKit assistant (AG-UI). Gated behind an env flag so the core demo never
// depends on an LLM key; the runtime at /api/copilotkit returns 501 without one.
// When enabled, CopilotBridge gives the copilot read access to the user's context
// and real actions it can take on their behalf.
export function Assistant({ children }: { children: React.ReactNode }) {
  const enabled = process.env.NEXT_PUBLIC_ENABLE_ASSISTANT === "1";
  if (!enabled) return <>{children}</>;
  return (
    <CopilotKit runtimeUrl="/api/copilotkit">
      <CopilotBridge />
      {children}
      <CopilotPopup
        labels={{
          title: "your agreed agent",
          initial:
            "I'm your agent. Tell me what to get done — I can open a negotiation, learn from your apps, or text someone for you.",
        }}
      />
    </CopilotKit>
  );
}
