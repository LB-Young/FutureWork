"""List active Agents and Teams or rank them against a task description."""

import json
import math
import re
import tomllib
import unicodedata
from collections import Counter

from futurework.kinds import FRIEND, TEAM


def _terms(text: str) -> Counter[str]:
    """Create Unicode-aware word and Han-character n-gram features."""
    normalized = unicodedata.normalize("NFKC", text).casefold()
    terms: Counter[str] = Counter()
    for part in re.findall(r"[\u4e00-\u9fff]+|[a-z0-9]+", normalized):
        if "\u4e00" <= part[0] <= "\u9fff":
            terms.update(part[index:index + 2] for index in range(len(part) - 1))
            if len(part) == 1:
                terms[part] += 1
        else:
            terms[part] += 1
    return terms


def _profile_text(agent_service, kind: str, item_id: str, limit: int) -> str:
    """Read the matching identity Markdown, never conversation history."""
    path = agent_service.config_store.path(kind, item_id).with_suffix(".md")
    return path.read_text(encoding="utf-8")[:limit] if path.is_file() else ""


def _group_purpose(agent_service, group_id: str) -> str:
    """Use the current Team configuration's purpose when one is defined."""
    path = agent_service.config_store.path("teams", group_id)
    if not path.is_file():
        return ""
    with path.open("rb") as source:
        return str(tomllib.load(source).get("purpose", ""))


def _features(fields: list[tuple[str, float]]) -> Counter[str]:
    result: Counter[str] = Counter()
    for value, weight in fields:
        for term, count in _terms(value).items():
            result[term] += count * weight
    return result


def _rank(query: str, candidates: list[tuple[dict, Counter[str]]], settings: dict, top_k: int) -> list[dict]:
    """Rank a small live directory with deterministic TF-IDF cosine similarity."""
    query_terms = _terms(query)
    if not query_terms:
        return []
    count = len(candidates)
    frequencies = Counter(term for _, features in candidates for term in features)
    idf = {term: 1 + math.log((count + 1) / (frequencies[term] + 1)) for term in query_terms}
    query_norm = math.sqrt(sum((amount * idf[term]) ** 2 for term, amount in query_terms.items()))
    ranked = []
    for item, features in candidates:
        document_norm = math.sqrt(sum((amount * (1 + math.log((count + 1) / (frequencies[term] + 1)))) ** 2
                                      for term, amount in features.items()))
        dot = sum(query_terms[term] * features.get(term, 0) * idf[term] ** 2 for term in query_terms)
        cosine = dot / (query_norm * document_norm) if document_norm else 0.0
        coverage = sum(amount for term, amount in query_terms.items() if term in features) / sum(query_terms.values())
        score = cosine * (1 - settings["coverage_weight"]) + coverage * settings["coverage_weight"]
        if score >= settings["min_score"]:
            ranked.append((score, item))
    ranked.sort(key=lambda pair: (-pair[0], pair[1]["kind"], pair[1]["id"]))
    return [{**item, "score": round(score, 4)} for score, item in ranked[:top_k]]


def run(args: dict, agent_service) -> str:
    """Return all active identities or Top K related friends and groups as JSON."""
    settings = agent_service.config["directory_search"]
    kind = args.get("target_kind", "all")
    if kind not in {"all", FRIEND, TEAM}:
        raise ValueError("target_kind must be all, agent, or group")
    query = args.get("query")
    if query is not None and (not isinstance(query, str) or not query.strip()
                              or len(query) > settings["max_query_chars"]):
        raise ValueError("query is empty or too long")
    if query is None and "top_k" in args:
        raise ValueError("top_k requires query")
    top_k = args.get("top_k", settings["default_top_k"])
    if type(top_k) is not int or not 1 <= top_k <= settings["max_top_k"]:
        raise ValueError("top_k is outside the configured limit")
    friends = agent_service.database.agents()
    names = {friend["id"]: friend["name"] for friend in friends}
    by_id = {friend["id"]: friend for friend in friends}
    candidates = []
    if kind in {"all", FRIEND}:
        for friend in friends:
            item = {"kind": FRIEND, "id": friend["id"], "name": friend["name"],
                    "role": friend["role"], "capabilities": friend["capabilities"]}
            fields = [(friend["name"], settings["name_weight"]),
                      (friend["role"], settings["role_weight"]),
                      (" ".join(friend["capabilities"]), settings["capability_weight"]),
                      (_profile_text(agent_service, "agents", friend["id"], settings["max_profile_chars"]),
                       settings["profile_weight"])]
            candidates.append((item, _features(fields)))
    if kind in {"all", TEAM}:
        for group in agent_service.database.groups():
            members = [by_id[member_id] for member_id in group["members"] if member_id in by_id]
            capabilities = {}
            for member in members:
                for capability, proficiency in member["capabilities"].items():
                    capabilities[capability] = max(capabilities.get(capability, 0), proficiency)
            purpose = _group_purpose(agent_service, group["id"])
            item = {"kind": TEAM, "id": group["id"], "name": group["name"],
                    "role": group["role"], "purpose": purpose, "mode": group["mode"],
                    "members": [{"id": member_id, "name": names.get(member_id, member_id)}
                                for member_id in group["members"]],
                    "capabilities": capabilities}
            member_text = " ".join(f"{member['name']} {member['role']}" for member in members)
            fields = [(group["name"], settings["name_weight"]),
                      (group["role"] + " " + purpose, settings["role_weight"]),
                      (member_text, settings["member_weight"]),
                      (" ".join(capabilities), settings["capability_weight"]),
                      (_profile_text(agent_service, "teams", group["id"], settings["max_profile_chars"]),
                       settings["profile_weight"])]
            candidates.append((item, _features(fields)))
    response = {"assistant": {"id": "assistant", "name": agent_service.config["assistant"]["name"],
                              "role": agent_service.config["assistant"]["role"]},
                "query": query or "", "target_kind": kind,
                "friends": [], "teams": [], "matches": []}
    if query is None:
        response["friends"] = [item for item, _ in candidates if item["kind"] == FRIEND]
        response["teams"] = [item for item, _ in candidates if item["kind"] == TEAM]
    else:
        response["matches"] = _rank(query.strip(), candidates, settings, top_k)
    return json.dumps(response, ensure_ascii=False)
