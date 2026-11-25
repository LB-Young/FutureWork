"""Search scoped experience first and return bounded, traceable JSON results."""

import json

from futurework.contexts.retrieval import MemoryRetriever
from futurework.contexts.types import ScopeKey


def run(args: dict, config: dict, retriever: MemoryRetriever, scope: ScopeKey, actor_id: str) -> str:
    """Execute memory retrieval only with the dispatcher's bound actor and scope."""
    found = retriever.search(args["query"], scope, actor_id,
                             group_id=args.get("group_id"), limit=args.get("limit", 5))
    result = found.as_dict()
    cap = config["memory"]["search_max_result_chars"]
    for match in result["matches"]:
        match["content"] = match["content"][:max(1, cap // max(1, len(result["matches"])) - 300)]
    while len(json.dumps(result, ensure_ascii=False)) > cap and result["matches"]:
        result["matches"].pop()
    if len(json.dumps(result, ensure_ascii=False)) > cap:
        raise ValueError("memory search result exceeds configured limit")
    return json.dumps(result, ensure_ascii=False)
