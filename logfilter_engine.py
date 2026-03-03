# logfilter_engine.py
from __future__ import annotations

from typing import Dict, List, Tuple, Optional, Any
import re

FilterItem = Dict[str, Any]  # {"type": "string"|"regex", "value": str, "label": str, "enabled": bool, ...}


def _norm(s: str) -> str:
    """Normalize common whitespace/control differences so plain string matching is reliable."""
    if not s:
        return ""
    # remove stray carriage returns, normalize tabs, collapse repeated spaces
    s = s.replace("\r", "")
    s = s.replace("\t", " ")
    s = re.sub(r"[ ]{2,}", " ", s)
    return s


def rebuild_compiled_patterns(includes: List[FilterItem], excludes: List[FilterItem], case_insensitive: bool) -> None:
    """Compile regex items in-place and store as item['compiled'].
    Keeps item['regex_error'] if invalid.
    """
    flags = re.IGNORECASE if case_insensitive else 0

    def compile_item(it: FilterItem) -> None:
        if it.get("type") != "regex":
            it.pop("compiled", None)
            it.pop("regex_error", None)
            return

        rx = (it.get("value") or "").strip()
        if not rx:
            it.pop("compiled", None)
            it.pop("regex_error", None)
            return

        try:
            it["compiled"] = re.compile(rx, flags)
            it.pop("regex_error", None)
        except re.error as e:
            it.pop("compiled", None)
            it["regex_error"] = str(e)

    for it in includes:
        compile_item(it)
    for it in excludes:
        compile_item(it)


def _enabled_items(items: List[FilterItem]) -> List[FilterItem]:
    return [it for it in items if it.get("enabled", True)]


def _match_item(line: str, item: FilterItem, case_insensitive: bool) -> bool:
    """Match one item against one line (strictly line-by-line)."""
    t = item.get("type", "string")
    v = item.get("value", "")
    if not v:
        return True

    if t == "regex":
        pat = item.get("compiled")
        if pat is not None:
            return pat.search(line) is not None

        # fallback: attempt compile on the fly (should be rare if rebuild_compiled_patterns is used)
        flags = re.IGNORECASE if case_insensitive else 0
        try:
            return re.search(v, line, flags) is not None
        except re.error:
            return False

    # string
    line_n = _norm(line)
    v_n = _norm(v)

    if case_insensitive:
        return v_n.lower() in line_n.lower()
    return v_n in line_n


def apply_filters_in_memory(
    lines: List[str],
    includes: List[FilterItem],
    excludes: List[FilterItem],
    *,
    case_insensitive: bool = True,
    include_mode: str = "AND",  # "AND" | "OR"
) -> Tuple[List[str], Dict[int, int]]:
    """Return (filtered_lines, include_single_match_counts_by_index).

    include_single_match_counts_by_index counts matches of each INCLUDE criterion alone (enabled only).
    Used to detect 'blocking include' (count == 0).
    """
    inc_items = _enabled_items(includes)
    exc_items = _enabled_items(excludes)

    # map enabled includes back to original indices
    enabled_inc_indices = [i for i, it in enumerate(includes) if it.get("enabled", True)]
    single_counts = {i: 0 for i in enabled_inc_indices}

    def inc_all(line: str) -> bool:
        return all(_match_item(line, it, case_insensitive) for it in inc_items)

    def inc_any(line: str) -> bool:
        return any(_match_item(line, it, case_insensitive) for it in inc_items)

    def exc_any(line: str) -> bool:
        return any(_match_item(line, it, case_insensitive) for it in exc_items)

    out: List[str] = []
    for line in lines:
        # single-include counts (enabled only)
        for idx in enabled_inc_indices:
            if _match_item(line, includes[idx], case_insensitive):
                single_counts[idx] += 1

        # combined filter
        if inc_items:
            if include_mode == "AND":
                if not inc_all(line):
                    continue
            else:  # OR
                if not inc_any(line):
                    continue

        if exc_items and exc_any(line):
            continue

        out.append(line)

    return out, single_counts


def apply_filters_streaming(
    input_path: str,
    output_path: str,
    includes: List[FilterItem],
    excludes: List[FilterItem],
    *,
    case_insensitive: bool = True,
    include_mode: str = "AND",
) -> Tuple[int, int, Dict[int, int]]:
    """Streaming version:
    - reads input line-by-line
    - writes output line-by-line
    - returns (total_lines, output_lines, include_single_match_counts_by_index)
    """
    inc_items = _enabled_items(includes)
    exc_items = _enabled_items(excludes)

    enabled_inc_indices = [i for i, it in enumerate(includes) if it.get("enabled", True)]
    single_counts = {i: 0 for i in enabled_inc_indices}

    def inc_all(line: str) -> bool:
        return all(_match_item(line, it, case_insensitive) for it in inc_items)

    def inc_any(line: str) -> bool:
        return any(_match_item(line, it, case_insensitive) for it in inc_items)

    def exc_any(line: str) -> bool:
        return any(_match_item(line, it, case_insensitive) for it in exc_items)

    total = 0
    out_n = 0

    # read bytes -> decode as utf-8 first, fallback latin-1 (same philosophy as your safe_read_text)
    def iter_lines():
        with open(input_path, "rb") as f:
            data = f.read()
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            text = data.decode("latin-1", errors="replace")
        # keep same behavior as splitlines(): no trailing '\n' in the yielded strings
        for ln in text.splitlines():
            yield ln

    with open(output_path, "w", encoding="utf-8", newline="\n") as out:
        for line in iter_lines():
            total += 1

            for idx in enabled_inc_indices:
                if _match_item(line, includes[idx], case_insensitive):
                    single_counts[idx] += 1

            if inc_items:
                if include_mode == "AND":
                    if not inc_all(line):
                        continue
                else:
                    if not inc_any(line):
                        continue

            if exc_items and exc_any(line):
                continue

            out.write(line + "\n")
            out_n += 1

    return total, out_n, single_counts
