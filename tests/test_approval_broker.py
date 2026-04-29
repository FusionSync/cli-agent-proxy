import asyncio

import pytest

from aviary.approvals import ApprovalBroker
from aviary.schemas import ApprovalDecision


@pytest.mark.asyncio
async def test_approval_broker_waits_for_allow_decision():
    broker = ApprovalBroker()
    approval = await broker.create_approval(
        session_id="session-1",
        tool_name="Write",
        tool_input={"file_path": "README.md"},
        timeout_seconds=5,
    )

    wait_task = asyncio.create_task(broker.wait_for_decision(approval.approval_id))
    decided = await broker.decide(
        session_id="session-1",
        approval_id=approval.approval_id,
        decision=ApprovalDecision.APPROVE,
        reason="ok",
    )

    assert decided.status == "approved"
    assert await wait_task is True


@pytest.mark.asyncio
async def test_approval_broker_waits_for_deny_decision():
    broker = ApprovalBroker()
    approval = await broker.create_approval(
        session_id="session-1",
        tool_name="Bash",
        tool_input={"command": "rm -rf /tmp/x"},
        timeout_seconds=5,
    )

    wait_task = asyncio.create_task(broker.wait_for_decision(approval.approval_id))
    await broker.decide(
        session_id="session-1",
        approval_id=approval.approval_id,
        decision=ApprovalDecision.DENY,
        reason="dangerous",
    )

    assert await wait_task is False


@pytest.mark.asyncio
async def test_approval_broker_times_out_pending_request():
    broker = ApprovalBroker()
    approval = await broker.create_approval(
        session_id="session-1",
        tool_name="Bash",
        tool_input={"command": "sleep 10"},
        timeout_seconds=0.01,
    )

    assert await broker.wait_for_decision(approval.approval_id) is False
    approvals = await broker.list_session_approvals("session-1")

    assert approvals[0].status == "expired"


@pytest.mark.asyncio
async def test_approval_broker_rejects_wrong_session_decision():
    broker = ApprovalBroker()
    approval = await broker.create_approval(
        session_id="session-1",
        tool_name="Write",
        tool_input={},
        timeout_seconds=5,
    )

    with pytest.raises(KeyError):
        await broker.decide(
            session_id="other-session",
            approval_id=approval.approval_id,
            decision=ApprovalDecision.APPROVE,
        )
