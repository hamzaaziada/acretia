"""S6.1 research workflows: declarative step graphs, a minimal sequential executor and the catalog (D-033)."""
from __future__ import annotations

from . import steps as _steps  # noqa: F401  (registers assemblers and text steps)
from .base import (RunContext, Step, TemplateError, Workflow, WorkflowError, agent_runtime, execute, output_digest,
                   resolve, run_workflow)
from .catalog import CATALOG, compose, get, ids, parse_command, route, search
from .review import approve, pending, reject

__all__ = ["CATALOG", "RunContext", "Step", "TemplateError", "Workflow", "WorkflowError", "agent_runtime", "approve",
           "compose", "execute", "get", "ids", "output_digest", "parse_command", "pending", "reject", "resolve",
           "route", "run_request", "run_workflow", "search"]


def run_request(workflow, request, *, adapter=None, tools=None, evidence_dir="storage/evidence", job_id,
                on_event=None, cancel=None, resolver=None, review=None, clock=None):
    """Run ``workflow`` for a validated ResearchRequest. Never raises for run-time failures (status "failed")."""
    import time
    org = request.org_id
    try:
        from src.harness.admin.agents import is_enabled
        if not all(is_enabled(org, part) for part in workflow.id.split("+")):
            from src.harness.research.api import ResearchResult
            from src.harness.evidence import EvidenceBundle, head_hash
            from pathlib import Path
            b = EvidenceBundle(Path(evidence_dir) / f"{job_id}.jsonl")
            try:
                b.append("workflow_disabled", {"workflow": workflow.id}, source="admin", output={"enabled": False})
                head = head_hash(b.path)
            finally:
                b.close()
            return ResearchResult(job_id=job_id, status="failed", evidence_head=head,
                                  error=f"workflow {workflow.id} is disabled for org {org}").validate()
    except ImportError:
        pass
    ctx = RunContext(workflow, request, job_id=job_id, evidence_dir=evidence_dir, tools=tools, adapter=adapter,
                     emit=on_event, cancel=cancel, resolver=resolver, review=review,
                     clock=clock or time.perf_counter)
    return run_workflow(workflow, ctx)
