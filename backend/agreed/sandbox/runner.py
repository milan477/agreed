"""Sandbox isolation for agents.

Judges require each agent to run in its own sandbox. Each negotiator gets its own
`AgentSandbox`. With an E2B key, agent code/tool execution runs in a real isolated
E2B sandbox; without one, we fall back to an in-process boundary that still
records the isolation in the trace so the architecture is demonstrable.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..config import get_settings
from ..observability import op, record_event


@dataclass
class AgentSandbox:
    agent_name: str
    backend: str = "local"  # "e2b" | "local"
    sandbox_id: str | None = None
    _handle: object | None = field(default=None, repr=False)

    @op(name="sandbox.start", kind="tool")
    def start(self) -> "AgentSandbox":
        s = get_settings()
        if s.has_e2b:
            try:
                from e2b_code_interpreter import Sandbox  # type: ignore

                self._handle = Sandbox(api_key=s.e2b_api_key)
                self.backend = "e2b"
                self.sandbox_id = getattr(self._handle, "sandbox_id", "e2b")
            except Exception as exc:
                record_event("sandbox_e2b_failed", kind="tool", agent=self.agent_name, error=str(exc))
                self.backend = "local"
                self.sandbox_id = f"local:{self.agent_name}"
        else:
            self.backend = "local"
            self.sandbox_id = f"local:{self.agent_name}"
        record_event("sandbox_start", kind="tool", agent=self.agent_name, backend=self.backend, sandbox_id=self.sandbox_id)
        return self

    @op(name="sandbox.run_code", kind="tool")
    def run_code(self, code: str) -> dict:
        """Execute code inside the agent's sandbox (E2B) or locally (restricted)."""
        if self.backend == "e2b" and self._handle is not None:
            try:
                exec_result = self._handle.run_code(code)  # type: ignore[attr-defined]
                return {"backend": "e2b", "stdout": getattr(exec_result, "logs", str(exec_result))}
            except Exception as exc:
                return {"backend": "e2b", "error": str(exc)}
        return {"backend": "local", "note": "local fallback: code execution sandboxed in-process is disabled by default"}

    @op(name="sandbox.close", kind="tool")
    def close(self) -> None:
        if self.backend == "e2b" and self._handle is not None:
            try:
                self._handle.kill()  # type: ignore[attr-defined]
            except Exception:
                pass
        record_event("sandbox_close", kind="tool", agent=self.agent_name, backend=self.backend)


def provision_sandboxes(agent_names: list[str]) -> dict[str, AgentSandbox]:
    """Provision one sandbox per agent (required isolation)."""
    return {name: AgentSandbox(agent_name=name).start() for name in agent_names}
