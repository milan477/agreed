"use client";

import { CopilotKit } from "@copilotkit/react-core";
import { CopilotPopup } from "@copilotkit/react-ui";
import "@copilotkit/react-ui/styles.css";

// CopilotKit assistant (AG-UI). Gated behind an env flag so the core demo never
// depends on an LLM key; the runtime at /api/copilotkit returns 501 without one.
export function Assistant({ children }: { children: React.ReactNode }) {
  const enabled = process.env.NEXT_PUBLIC_ENABLE_ASSISTANT === "1";
  if (!enabled) return <>{children}</>;
  return (
    <CopilotKit runtimeUrl="/api/copilotkit">
      {children}
      <CopilotPopup
        labels={{
          title: "agreed assistant",
          initial: "Ask me about the negotiation, the trace, or your brief.",
        }}
      />
    </CopilotKit>
  );
}
