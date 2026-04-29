from __future__ import annotations

import asyncio
import time
import uuid
from dataclasses import dataclass, replace
from typing import Any

from aviary.schemas import ApprovalDecision, ApprovalResponse, ApprovalStatus


@dataclass(frozen=True)
class PendingApproval:
    response: ApprovalResponse
    future: asyncio.Future[bool]


class ApprovalBroker:
    def __init__(self) -> None:
        self._approvals: dict[str, PendingApproval] = {}
        self._lock = asyncio.Lock()

    async def create_approval(
        self,
        *,
        session_id: str,
        tool_name: str,
        tool_input: dict[str, Any],
        timeout_seconds: float,
        tool_use_id: str | None = None,
        agent_id: str | None = None,
    ) -> ApprovalResponse:
        now = time.time()
        approval = ApprovalResponse(
            approval_id=str(uuid.uuid4()),
            session_id=session_id,
            tool_name=tool_name,
            tool_input=tool_input,
            status=ApprovalStatus.PENDING,
            tool_use_id=tool_use_id,
            agent_id=agent_id,
            created_at=now,
            expires_at=now + timeout_seconds,
        )
        async with self._lock:
            self._approvals = {
                **self._approvals,
                approval.approval_id: PendingApproval(
                    response=approval,
                    future=asyncio.get_running_loop().create_future(),
                ),
            }
        return approval

    async def request_approval(
        self,
        *,
        session_id: str,
        tool_name: str,
        tool_input: dict[str, Any],
        timeout_seconds: float,
        tool_use_id: str | None = None,
        agent_id: str | None = None,
    ) -> bool:
        approval = await self.create_approval(
            session_id=session_id,
            tool_name=tool_name,
            tool_input=tool_input,
            timeout_seconds=timeout_seconds,
            tool_use_id=tool_use_id,
            agent_id=agent_id,
        )
        return await self.wait_for_decision(approval.approval_id)

    async def wait_for_decision(self, approval_id: str) -> bool:
        pending = await self._get_pending(approval_id)
        timeout = max(pending.response.expires_at - time.time(), 0)
        try:
            return await asyncio.wait_for(pending.future, timeout=timeout)
        except TimeoutError:
            await self._mark_terminal(
                approval_id=approval_id,
                status=ApprovalStatus.EXPIRED,
                value=False,
                reason="approval timed out",
            )
            return False

    async def decide(
        self,
        *,
        session_id: str,
        approval_id: str,
        decision: ApprovalDecision,
        reason: str | None = None,
    ) -> ApprovalResponse:
        pending = await self._get_pending(approval_id)
        if pending.response.session_id != session_id:
            raise KeyError(approval_id)
        if pending.response.status != ApprovalStatus.PENDING:
            return pending.response

        approved = decision == ApprovalDecision.APPROVE
        status = ApprovalStatus.APPROVED if approved else ApprovalStatus.DENIED
        return await self._mark_terminal(
            approval_id=approval_id,
            status=status,
            value=approved,
            reason=reason,
        )

    async def list_session_approvals(self, session_id: str) -> list[ApprovalResponse]:
        async with self._lock:
            return [
                pending.response
                for pending in self._approvals.values()
                if pending.response.session_id == session_id
            ]

    async def cancel_session(self, session_id: str) -> None:
        approvals = await self.list_session_approvals(session_id)
        for approval in approvals:
            if approval.status == ApprovalStatus.PENDING:
                await self._mark_terminal(
                    approval_id=approval.approval_id,
                    status=ApprovalStatus.CANCELLED,
                    value=False,
                    reason="session closed",
                )

    async def _get_pending(self, approval_id: str) -> PendingApproval:
        async with self._lock:
            pending = self._approvals.get(approval_id)
        if pending is None:
            raise KeyError(approval_id)
        return pending

    async def _mark_terminal(
        self,
        *,
        approval_id: str,
        status: ApprovalStatus,
        value: bool,
        reason: str | None,
    ) -> ApprovalResponse:
        async with self._lock:
            pending = self._approvals.get(approval_id)
            if pending is None:
                raise KeyError(approval_id)
            if pending.response.status != ApprovalStatus.PENDING:
                return pending.response

            updated_response = pending.response.model_copy(
                update={
                    "status": status,
                    "reason": reason,
                    "decided_at": time.time(),
                }
            )
            updated = replace(pending, response=updated_response)
            self._approvals = {**self._approvals, approval_id: updated}
            if not pending.future.done():
                pending.future.set_result(value)
            return updated_response
