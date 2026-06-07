// CopilotKit runtime endpoint. Enables the in-app assistant when an OpenAI key is
// present. Without a key the endpoint returns 501 and the UI hides the assistant,
// so the core demo never depends on it.
import {
  CopilotRuntime,
  OpenAIAdapter,
  copilotRuntimeNextJSAppRouterEndpoint,
} from "@copilotkit/runtime";
import { NextRequest } from "next/server";

export const POST = async (req: NextRequest) => {
  if (!process.env.OPENAI_API_KEY) {
    return new Response("CopilotKit assistant disabled (no OPENAI_API_KEY).", { status: 501 });
  }
  const runtime = new CopilotRuntime();
  const { handleRequest } = copilotRuntimeNextJSAppRouterEndpoint({
    runtime,
    serviceAdapter: new OpenAIAdapter(),
    endpoint: "/api/copilotkit",
  });
  return handleRequest(req);
};
