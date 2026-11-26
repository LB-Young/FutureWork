"""Run an approved XiaoWei delegation through the task and group services."""

from futurework.kinds import DELEGATION_AUTO


async def run(args: dict, delegation_service) -> str:
    """Create and execute a task only after the model calls this tool."""
    return await delegation_service.execute(
        args["request"], args.get("target_kind", DELEGATION_AUTO),
        args.get("target_id", ""))
