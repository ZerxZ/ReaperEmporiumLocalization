from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from diff_match_patch import diff_match_patch
from thefuzz import fuzz, process

from reaper_tools.models import ParatranzData

MAIN_GAME_DIR = "MainGame"
DLC_GAME_DIR = "DLCGame"
DATABASE_DIR = "database"
DLL_STRINGS_FILE = "dll_strings.json"
DMP_EQUAL = 0
DMP_INSERT = 1
DMP_DELETE = -1
DATABASE_ORIGINAL_FUZZY_THRESHOLD = 85
DATABASE_FUZZY_SEARCH_MAX_ENTRIES = 2000
_DIFF_MATCH_PATCH = diff_match_patch()


@dataclass(slots=True)
class DatabaseMatchPair:
    """A comparison-side entry paired with a matched baseline entry when possible."""

    base_entry: ParatranzData | None
    compare_entry: ParatranzData


class DatabaseEntryMatcher:
    """Database matcher shared by dump diff and remote/local comparison."""

    def __init__(self, base_entries: list[ParatranzData], *, enable_fuzzy_search: bool = True) -> None:
        self._base_entries = base_entries
        self._enable_fuzzy_search = enable_fuzzy_search
        self._used_entry_ids: set[int] = set()
        self._by_original: dict[str, list[ParatranzData]] = {}
        self._by_key: dict[str, list[ParatranzData]] = {}
        for entry in base_entries:
            original = database_original_for_match(entry)
            if original:
                self._by_original.setdefault(original, []).append(entry)
            self._by_key.setdefault(entry.key, []).append(entry)

    def find(self, compare_entry: ParatranzData, *, index: int | None = None, use_index: bool = False) -> ParatranzData | None:
        """Match by original first, then equal-length index, then fuzzy original, then non-numeric key."""

        original = database_original_for_match(compare_entry)
        if original:
            exact_candidates = self._by_original.get(original, [])
            exact = self._choose_candidate(exact_candidates, compare_entry)
            if exact is not None:
                return self._reserve(exact)
            if exact_candidates:
                return None
        if use_index and index is not None and index < len(self._base_entries):
            indexed = self._base_entries[index]
            if not self._is_used(indexed):
                return self._reserve(indexed)
        if original and self._enable_fuzzy_search:
            fuzzy_candidate = self._find_fuzzy_original_candidate(original, compare_entry)
            if fuzzy_candidate is not None:
                return self._reserve(fuzzy_candidate)
        if not is_numeric_database_key(compare_entry.key):
            key_candidate = self._choose_candidate(self._by_key.get(compare_entry.key, []), compare_entry)
            if key_candidate is not None:
                return self._reserve(key_candidate)
        return None

    def unmatched_entries(self) -> list[ParatranzData]:
        return [entry for entry in self._base_entries if not self._is_used(entry)]

    def _find_fuzzy_original_candidate(self, original: str, compare_entry: ParatranzData) -> ParatranzData | None:
        original_choices = [
            candidate_original
            for candidate_original, candidates in self._by_original.items()
            if self._choose_candidate(candidates, compare_entry) is not None
        ]
        if not original_choices:
            return None
        match = process.extractOne(
            original,
            original_choices,
            scorer=fuzz.ratio,
        )
        if match is None or match[1] < DATABASE_ORIGINAL_FUZZY_THRESHOLD:
            return None
        matched_original = match[0]
        return self._choose_candidate(self._by_original.get(matched_original, []), compare_entry)

    def _choose_candidate(self, candidates: list[ParatranzData], compare_entry: ParatranzData) -> ParatranzData | None:
        available = [candidate for candidate in candidates if not self._is_used(candidate)]
        if not available:
            return None
        return max(
            available,
            key=lambda candidate: (
                candidate.context == compare_entry.context,
                fuzz.ratio(candidate.context, compare_entry.context),
                candidate.key == compare_entry.key,
            ),
        )

    def _is_used(self, entry: ParatranzData) -> bool:
        return id(entry) in self._used_entry_ids

    def _reserve(self, entry: ParatranzData) -> ParatranzData:
        self._used_entry_ids.add(id(entry))
        return entry


def build_database_match_pairs(
    base_entries: list[ParatranzData],
    compare_entries: list[ParatranzData],
) -> tuple[list[DatabaseMatchPair], list[ParatranzData]]:
    """Match compare-side entries against the baseline and also return unmatched baseline entries."""

    use_index = len(base_entries) == len(compare_entries)
    matcher = DatabaseEntryMatcher(
        base_entries,
        enable_fuzzy_search=not use_index and len(base_entries) <= DATABASE_FUZZY_SEARCH_MAX_ENTRIES,
    )
    pairs: list[DatabaseMatchPair] = []
    for index, compare_entry in enumerate(compare_entries):
        candidate = matcher.find(compare_entry, index=index, use_index=use_index)
        pairs.append(DatabaseMatchPair(candidate, compare_entry))
    return pairs, matcher.unmatched_entries()


def database_original_for_match(entry: ParatranzData) -> str:
    return " ".join(entry.runtime_original.split()).casefold()


def is_numeric_database_key(key: str) -> bool:
    return key.isdecimal()


def normalized_paratranz_json_text(entries: list[ParatranzData]) -> str:
    payload = [entry.model_dump(mode="json") for entry in entries]
    return json.dumps(payload, ensure_ascii=False, indent=2)


def normalized_entry_json_text(
    entry: ParatranzData,
    *,
    key_normalizer: Callable[[str], str] | None = None,
    ignore_key: bool = False,
) -> str:
    payload = entry.model_dump(mode="json")
    if ignore_key:
        payload.pop("key", None)
    elif key_normalizer is not None:
        payload["key"] = key_normalizer(entry.key)
    return json.dumps(payload, ensure_ascii=False, indent=2)


def format_readable_json_diff(base_text: str, compare_text: str, from_label: str, to_label: str) -> str:
    if base_text == compare_text:
        return ""
    base_chars, compare_chars, line_array = _DIFF_MATCH_PATCH.diff_linesToChars(base_text, compare_text)
    diffs = _DIFF_MATCH_PATCH.diff_main(base_chars, compare_chars, False)
    _DIFF_MATCH_PATCH.diff_charsToLines(diffs, line_array)

    lines = [f"--- {from_label}", f"+++ {to_label}"]
    for operation, text in diffs:
        prefix = _diff_line_prefix(operation)
        lines.extend(f"{prefix}{line}" for line in text.splitlines())
    return "\n".join(lines) + "\n"


def write_readable_json_diff(
    base_entries: list[ParatranzData],
    compare_entries: list[ParatranzData],
    target_file: Path,
    *,
    from_label: str,
    to_label: str,
) -> bool:
    diff_text = format_readable_json_diff(
        normalized_paratranz_json_text(base_entries),
        normalized_paratranz_json_text(compare_entries),
        from_label,
        to_label,
    )
    if not diff_text:
        return False
    target_file.parent.mkdir(parents=True, exist_ok=True)
    target_file.write_text(diff_text, encoding="utf-8", newline="\n")
    return True


def entries_differ_by_patch(
    base_entry: ParatranzData,
    compare_entry: ParatranzData,
    key_normalizer: Callable[[str], str] | None = None,
    *,
    ignore_key: bool = False,
) -> bool:
    base_text = normalized_entry_json_text(base_entry, key_normalizer=key_normalizer, ignore_key=ignore_key)
    compare_text = normalized_entry_json_text(compare_entry, key_normalizer=key_normalizer, ignore_key=ignore_key)
    return any(operation != DMP_EQUAL for operation, _text in _DIFF_MATCH_PATCH.diff_main(base_text, compare_text))


def diff_entries_by_patch(
    base_entries: list[ParatranzData],
    compare_entries: list[ParatranzData],
    *,
    match_key: Callable[[ParatranzData], tuple[str, str]],
    key_normalizer: Callable[[str], str] | None = None,
) -> list[ParatranzData]:
    base_index: dict[tuple[str, str], list[ParatranzData]] = {}
    for entry in base_entries:
        base_index.setdefault(match_key(entry), []).append(entry)

    changed_entries: list[ParatranzData] = []
    for compare_entry in compare_entries:
        candidates = base_index.get(match_key(compare_entry), [])
        if not candidates or all(entries_differ_by_patch(candidate, compare_entry, key_normalizer) for candidate in candidates):
            changed_entries.append(compare_entry)
    return changed_entries


def json_files(root: Path) -> list[Path]:
    if not root.exists():
        return []
    return sorted(root.rglob("*.json"), key=lambda item: item.relative_to(root).as_posix().casefold())


def write_paratranz_file(target: Path, entries: list[ParatranzData]) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = [entry.model_dump(mode="json") for entry in entries]
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8", newline="\n")


def _diff_line_prefix(operation: int) -> str:
    if operation == DMP_DELETE:
        return "-"
    if operation == DMP_INSERT:
        return "+"
    return " "


__all__ = [
    "DATABASE_DIR",
    "DLL_STRINGS_FILE",
    "DLC_GAME_DIR",
    "DMP_DELETE",
    "DMP_EQUAL",
    "DMP_INSERT",
    "DatabaseEntryMatcher",
    "DatabaseMatchPair",
    "MAIN_GAME_DIR",
    "build_database_match_pairs",
    "database_original_for_match",
    "diff_entries_by_patch",
    "entries_differ_by_patch",
    "format_readable_json_diff",
    "is_numeric_database_key",
    "json_files",
    "normalized_entry_json_text",
    "normalized_paratranz_json_text",
    "write_paratranz_file",
    "write_readable_json_diff",
]
