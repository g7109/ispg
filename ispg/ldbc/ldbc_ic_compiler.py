#!/usr/bin/env python3
"""LDBC IC query compiler.

This script follows the JOB compilation workflow: it reads SQL/PGQ query templates,
extracts graph patterns from MATCH, maps vertices/edges to CSV data files, and
estimates selectivity for parameterized predicates. It then produces a JSON
description for each query that can be consumed by the optimizer.
"""

from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

import duckdb


REPO_ROOT = Path(__file__).resolve().parents[2]
BASE_DIR = Path(__file__).resolve().parent
IC_DIR = BASE_DIR / "ic"
GRAPH_CATALOG_PATH = BASE_DIR / "ldbc_graph_catalog.json"
GLOGS_SCHEMA_PATH = BASE_DIR / "ldbc_glogs_schema.json"
PARAMS_PATH = IC_DIR / "ic_params.json"
QUERY_FILTERS_DIR = BASE_DIR / "query_filters"
QUERY_PATTERN_DIR = BASE_DIR / "query_pattern"
DATASET_ROOT = REPO_ROOT / "datasets" / "ldbc" / "sf1"

# Only Person_knows_Person edges use var-expand semantics in IC queries
VAR_EXPAND_RELATION_TYPES = {"personknows", "personknowsperson", "knows"}

RELATION_TYPE_OVERRIDES: Dict[str, Dict[str, Any]] = {
	"hascreated": {"canonical_type": "HasCreator", "swap": True},
	"hasreply": {"canonical_type": "ReplyOf", "swap": True},
}


@dataclass
class NodeInfo:
	label: str
	csv: str
	delimiter: str
	id_column: str
	properties: List[str]


def normalize_rel_name(name: str) -> str:
	return re.sub(r"[^a-z0-9]", "", name.lower())


def normalize_identifier(name: str) -> str:
	return re.sub(r"[^a-z0-9]", "", (name or "").lower())


@dataclass
class RelationshipInfo:
	key: str
	type: str
	csv: str
	delimiter: str
	source_label: str
	source_column: str
	target_label: str
	target_column: str
	properties: List[str]


@dataclass
class AliasInfo:
	alias: str
	kind: str  # "vertex" | "edge" | "table"
	label: Optional[str] = None
	label_id: Optional[int] = None
	relationship_key: Optional[str] = None
	relationship_type: Optional[str] = None
	relationship_label: Optional[str] = None
	relation_id: Optional[int] = None
	schema_label: Optional[str] = None
	source_alias: Optional[str] = None
	target_alias: Optional[str] = None
	dataset_hint: Optional[str] = None
	origin: str = "unknown"  # match_graph | match_edge | sql_join | other


def classify_origin(origin: str) -> str:
	origin_lower = (origin or "").lower()
	if origin_lower.startswith("match"):
		return "match"
	if origin_lower.startswith("sql"):
		return "sql"
	return "other"


@dataclass
class PredicateCondition:
	alias: str
	column: str
	operator: str
	values: List[Any]
	expression: str
	parameter_names: List[str]
	source_segment: Optional[str] = None
	custom_sql: Optional[str] = None


@dataclass
class PredicateStats:
	expression: str
	matched_rows: int
	total_rows: int
	selectivity: float


def deduplicate_predicates(predicates: List[PredicateCondition]) -> List[PredicateCondition]:
	"""Remove duplicate predicates with identical expression/parameters, preserving order."""
	seen: Set[Tuple[str, str, str, Tuple[Any, ...], str, str]] = set()
	unique: List[PredicateCondition] = []
	for predicate in predicates:
		key = (
			predicate.alias,
			predicate.column,
			predicate.operator.upper(),
			tuple(predicate.values),
			predicate.custom_sql or "",
			predicate.expression.strip(),
		)
		if key in seen:
			continue
		seen.add(key)
		unique.append(predicate)
	return unique


class GLogsSchema:
	def __init__(self, schema_path: Path) -> None:
		data = json.loads(schema_path.read_text(encoding="utf-8"))
		self.label_name_to_id: Dict[str, int] = {}
		self.relation_signature_to_id: Dict[Tuple[str, str, str], int] = {}
		self.relation_signature_to_label: Dict[Tuple[str, str, str], str] = {}
		for entity in data.get("entities", []):
			label = entity.get("label", {})
			name = label.get("name")
			if name is None:
				continue
			self.label_name_to_id[name.lower()] = label.get("id")
		for relation in data.get("relations", []):
			label = relation.get("label", {})
			rel_name = label.get("name", "")
			rel_id = label.get("id")
			for pair in relation.get("entity_pairs", []):
				src = pair.get("src", {}).get("name", "").lower()
				dst = pair.get("dst", {}).get("name", "").lower()
				type_name = self._extract_relation_type(rel_name)
				if not src or not dst or not type_name:
					continue
				self.relation_signature_to_id[(type_name, src, dst)] = rel_id
				self.relation_signature_to_label[(type_name, src, dst)] = rel_name

	@staticmethod
	def _extract_relation_type(rel_name: str) -> str:
		parts = rel_name.split("_")
		if len(parts) < 3:
			return normalize_rel_name(rel_name)
		return normalize_rel_name("_".join(parts[1:-1]))

	def get_label_id(self, label: str) -> Optional[int]:
		return self.label_name_to_id.get(label.lower())

	def get_relation_id(self, rel_type: str, source_label: str, target_label: str) -> Optional[int]:
		signature = (normalize_rel_name(rel_type), source_label.lower(), target_label.lower())
		return self.relation_signature_to_id.get(signature)

	def get_relation_label(self, rel_type: str, source_label: str, target_label: str) -> Optional[str]:
		signature = (normalize_rel_name(rel_type), source_label.lower(), target_label.lower())
		return self.relation_signature_to_label.get(signature)


class GraphCatalog:
	"""Load the LDBC graph catalog and provide node/relationship metadata."""

	def __init__(self, catalog_path: Path) -> None:
		data = json.loads(catalog_path.read_text(encoding="utf-8"))
		self.nodes_by_label: Dict[str, NodeInfo] = {}
		self.relationships_by_key: Dict[str, RelationshipInfo] = {}
		self.relationships_by_signature: Dict[Tuple[str, str, str], RelationshipInfo] = {}

		for label, info in data.get("nodes", {}).items():
			node = NodeInfo(
				label=info.get("label", label),
				csv=info.get("csv", ""),
				delimiter=info.get("delimiter", "|"),
				id_column=info.get("id_column", "id"),
				properties=list(info.get("properties", [])),
			)
			self.nodes_by_label[node.label.lower()] = node

		for key, info in data.get("relationships", {}).items():
			source = info.get("source", {})
			target = info.get("target", {})
			rel = RelationshipInfo(
				key=key,
				type=info.get("type", key),
				csv=info.get("csv", ""),
				delimiter=info.get("delimiter", "|"),
				source_label=source.get("label", ""),
				source_column=source.get("column", ""),
				target_label=target.get("label", ""),
				target_column=target.get("column", ""),
				properties=list(info.get("properties", [])),
			)
			self.relationships_by_key[rel.key] = rel
			signature = (
				normalize_rel_name(rel.type),
				rel.source_label.lower(),
				rel.target_label.lower(),
			)
			self.relationships_by_signature[signature] = rel

	def get_node(self, label: str) -> Optional[NodeInfo]:
		return self.nodes_by_label.get(label.lower())

	def get_relationship_by_key(self, key: str) -> Optional[RelationshipInfo]:
		return self.relationships_by_key.get(key)

	def find_relationship(self, rel_type: str, source_label: str, target_label: str) -> Optional[RelationshipInfo]:
		signature = (
			normalize_rel_name(rel_type),
			source_label.lower(),
			target_label.lower(),
		)
		return self.relationships_by_signature.get(signature)


class GraphDataset:
	"""DuckDB-backed helper for CSV statistics."""

	def __init__(self, catalog: GraphCatalog, dataset_root: Path) -> None:
		self.catalog = catalog
		self.dataset_root = dataset_root
		self.conn = duckdb.connect()
		self.node_views: Dict[str, str] = {}
		self.relationship_views: Dict[str, str] = {}

	def _register_view(self, view_name: str, csv_path: Path, delimiter: str, header: bool = True) -> None:
		csv_posix = csv_path.as_posix()
		self.conn.execute(
			f"""
			CREATE OR REPLACE VIEW {view_name} AS
			SELECT *
			FROM read_csv_auto(
				'{csv_posix}',
				delim='{delimiter}',
				header={str(header).upper()},
				ignore_errors=TRUE,
				sample_size=-1,
				parallel=FALSE
			);
			"""
		)

	def ensure_node_view(self, label: str) -> str:
		key = label.lower()
		if key in self.node_views:
			return self.node_views[key]
		info = self.catalog.get_node(label)
		if info is None:
			raise KeyError(f"Node label not found in graph catalog: {label}")
		csv_path = self.dataset_root / info.csv
		if not csv_path.exists():
			raise FileNotFoundError(f"CSV for node {label} does not exist: {csv_path}")
		view_name = f"node_{label.lower()}"
		self._register_view(view_name, csv_path, info.delimiter, header=True)
		self.node_views[key] = view_name
		return view_name

	def ensure_relationship_view(self, rel: RelationshipInfo) -> str:
		if rel.key in self.relationship_views:
			return self.relationship_views[rel.key]
		csv_path = self.dataset_root / rel.csv
		if not csv_path.exists():
			raise FileNotFoundError(f"CSV for relationship {rel.key} does not exist: {csv_path}")
		view_name = f"rel_{rel.key.lower()}"
		self._register_view(view_name, csv_path, rel.delimiter, header=True)
		self.relationship_views[rel.key] = view_name
		return view_name

	def evaluate(self, alias: AliasInfo, predicates: List[PredicateCondition]) -> Tuple[List[PredicateStats], PredicateStats]:
		if alias.kind == "vertex":
			if not alias.label:
				raise ValueError(f"Alias {alias.alias} is missing label information")
			view_name = self.ensure_node_view(alias.label)
		elif alias.kind in {"edge", "table"}:
			rel_key = alias.relationship_key or alias.dataset_hint
			if not rel_key:
				raise ValueError(f"Alias {alias.alias} cannot determine dataset key")
			rel_info = self.catalog.get_relationship_by_key(rel_key)
			if rel_info is None:
				raise KeyError(f"Relationship metadata not found: {rel_key}")
			view_name = self.ensure_relationship_view(rel_info)
		else:
			raise ValueError(f"Unknown alias kind: {alias.kind}")

		total_rows = self.conn.execute(f"SELECT COUNT(*) FROM {view_name}").fetchone()[0]
		if not predicates:
			combined = PredicateStats(
				expression="TRUE",
				matched_rows=total_rows,
				total_rows=total_rows,
				selectivity=1.0 if total_rows else 1.0,
			)
			return [], combined

		def predicate_sql(predicate: PredicateCondition) -> Tuple[str, List[Any]]:
			if predicate.custom_sql:
				return predicate.custom_sql, predicate.values
			col_ref = f'"{predicate.column}"'
			op = predicate.operator.upper()
			if op in {"IN", "NOT IN"}:
				placeholders = ", ".join(["?"] * len(predicate.values)) or "NULL"
				sql_part = f"{col_ref} {op} ({placeholders})"
				params = predicate.values
			else:
				sql_part = f"{col_ref} {op} ?"
				params = predicate.values[:1]
			return sql_part, params

		stats: List[PredicateStats] = []
		for predicate in predicates:
			sql_part, params = predicate_sql(predicate)
			matched = self.conn.execute(
				f"SELECT COUNT(*) FROM {view_name} WHERE {sql_part}",
				params,
			).fetchone()[0]
			selectivity = (matched / total_rows) if total_rows else 1.0
			stats.append(
				PredicateStats(
					expression=predicate.expression,
					matched_rows=matched,
					total_rows=total_rows,
					selectivity=selectivity,
				)
			)

		combined_sql_parts: List[str] = []
		combined_params: List[Any] = []
		for predicate in predicates:
			sql_part, params = predicate_sql(predicate)
			combined_sql_parts.append(f"({sql_part})")
			combined_params.extend(params)

		combined_matched = self.conn.execute(
			f"SELECT COUNT(*) FROM {view_name} WHERE {' AND '.join(combined_sql_parts)}",
			combined_params,
		).fetchone()[0]
		combined_selectivity = (
			(combined_matched / total_rows) if total_rows else 1.0
		)
		combined = PredicateStats(
			expression=" AND ".join([p.expression for p in predicates]) or "TRUE",
			matched_rows=combined_matched,
			total_rows=total_rows,
			selectivity=combined_selectivity,
		)
		return stats, combined


def snake_to_camel(name: str) -> str:
	parts = name.split("_")
	if not parts:
		return name
	head, *rest = parts
	return head + "".join(part.capitalize() for part in rest)


def snake_to_pascal(name: str) -> str:
	return "".join(part.capitalize() for part in name.split("_"))


class ParameterResolver:
	def __init__(self, params: Dict[str, Any]) -> None:
		self.params = params
		self.variant_to_key: Dict[str, str] = {}
		for key, value in params.items():
			variants = {
				key,
				key.lower(),
				snake_to_camel(key),
				snake_to_pascal(key),
				key.replace("_", ""),
				key.replace("_", "").lower(),
			}
			for variant in variants:
				normalized = self.normalize(variant)
				self.variant_to_key.setdefault(normalized, key)

	@staticmethod
	def normalize(name: str) -> str:
		return name.replace("_", "").lower()

	def resolve(self, name: str) -> Tuple[Optional[Any], Optional[str]]:
		normalized = self.normalize(name)
		key = self.variant_to_key.get(normalized)
		if key is None:
			return None, None
		return self.params[key], key

	def get(self, name: str) -> Optional[Any]:
		value, _ = self.resolve(name)
		return value


def strip_sql_comment(line: str) -> str:
	return line.split("--", 1)[0]


def strip_sql_comments(text: str) -> str:
	return "\n".join(strip_sql_comment(line) for line in text.splitlines())


def extract_graph_table_block(sql: str) -> Tuple[str, str, str]:
	pattern = re.compile(r"FROM\s+GRAPH_TABLE\s*\(", re.IGNORECASE)
	match = pattern.search(sql)
	if not match:
		raise ValueError("GRAPH_TABLE definition not found")
	start = match.end()
	depth = 1
	idx = start
	while idx < len(sql) and depth > 0:
		char = sql[idx]
		if char == "(":
			depth += 1
		elif char == ")":
			depth -= 1
		idx += 1
	block = sql[start: idx - 1]
	remainder = sql[idx:]
	alias_match = re.search(r"AS\s+([A-Za-z_][\w]*)", remainder, flags=re.IGNORECASE)
	graph_alias = alias_match.group(1) if alias_match else remainder.strip().split()[0]
	return block, graph_alias, sql[idx:]


def extract_plain_match_section(sql: str) -> str:
	lines = sql.splitlines()
	collecting = False
	collected: List[str] = []
	for raw_line in lines:
		line = strip_sql_comment(raw_line)
		stripped = line.strip()
		if not stripped:
			if collecting:
				collected.append("")
			continue
		upper = stripped.upper()
		if not collecting and upper.startswith("MATCH"):
			collecting = True
			collected.append(stripped[len("MATCH"):].strip().rstrip(","))
			continue
		if collecting:
			if upper.startswith(("WHERE", "RETURN", "GROUP", "ORDER", "LIMIT", "UNION", "JOIN", "WITH")):
				break
			collected.append(stripped.rstrip(","))
	return "\n".join(filter(None, collected))


def parse_match_section(match_section: str) -> Tuple[Dict[str, str], List[Dict[str, Any]]]:
	vertex_labels: Dict[str, str] = {}
	edges: List[Dict[str, Any]] = []

	cleaned = []
	for raw_line in match_section.splitlines():
		line = strip_sql_comment(raw_line).strip()
		if not line:
			continue
		cleaned.append(line.rstrip(","))

	node_pattern = re.compile(
		r"\(([A-Za-z_][\w]*)(?:\s*:\s*([A-Za-z_][\w]*))?\)"
	)

	def register_nodes(line: str) -> List[Tuple[str, Optional[str], int, int]]:
		nodes = []
		for match in node_pattern.finditer(line):
			alias = match.group(1)
			label = match.group(2)
			if label:
				vertex_labels.setdefault(alias, label)
			else:
				label = vertex_labels.get(alias)
			nodes.append((alias, label, match.start(), match.end()))
		return nodes

	# Allow PGQ edge syntaxes both with alias (e.g. [e:KNOWS]) and without alias (e.g. [:KNOWS]).
	edge_pattern = re.compile(
		r"-\s*\[(?:(?P<alias>[A-Za-z_][\w]*)\s*:)?\s*(?::)?(?P<type>[A-Za-z_][\w]*)(?:\*(?P<range>\d+(?:\.\.\d+)?))?\]\s*(?P<arrow>->)"
	)

	for line in cleaned:
		is_path = False
		path_alias: Optional[str] = None
		pattern_body = line
		if line.lower().startswith("path "):
			path_match = re.match(r"PATH\s+([A-Za-z_][\w]*)\s*=\s*(.*)", line, re.IGNORECASE)
			if not path_match:
				continue
			path_alias = path_match.group(1)
			pattern_body = path_match.group(2)
			is_path = True

		nodes = register_nodes(pattern_body)
		if len(nodes) < 2:
			continue
		for idx in range(len(nodes) - 1):
			left_alias, left_label, left_end = nodes[idx][0], nodes[idx][1], nodes[idx][3]
			right_alias, right_label, right_start = nodes[idx + 1][0], nodes[idx + 1][1], nodes[idx + 1][2]
			segment = pattern_body[left_end:right_start]
			edge_match = edge_pattern.search(segment)
			if not edge_match:
				continue
			rel_alias = edge_match.group("alias")
			rel_type = edge_match.group("type")
			range_spec = edge_match.group("range")
			min_hops = 1
			max_hops = 1
			if range_spec:
				if ".." in range_spec:
					start_str, end_str = range_spec.split("..", 1)
					min_hops = int(start_str)
					max_hops = int(end_str)
				else:
					min_hops = max_hops = int(range_spec)
			rel_signature = normalize_rel_name(rel_type)
			left_label_norm = (left_label or "").lower()
			right_label_norm = (right_label or "").lower()
			is_var_expand = (
				range_spec is not None
				and left_label_norm == "person"
				and right_label_norm == "person"
				and rel_signature in VAR_EXPAND_RELATION_TYPES
			)
			edges.append(
				{
					"alias": rel_alias,
					"type": rel_type,
					"source_alias": left_alias,
					"target_alias": right_alias,
					"min_hops": min_hops,
					"max_hops": max_hops,
					"is_path": is_path,
					"path_alias": path_alias,
					"is_var_expand": is_var_expand,
				}
			)

	return vertex_labels, edges


def parse_columns_section(columns_section: str) -> Dict[str, Tuple[Optional[str], Optional[str], str]]:
	column_map: Dict[str, Tuple[Optional[str], Optional[str], str]] = {}
	column_regex = re.compile(r"(.+?)\s+AS\s+\"?([A-Za-z0-9_.]+)\"?\s*,?", re.IGNORECASE)
	for raw_line in columns_section.splitlines():
		line = strip_sql_comment(raw_line).strip()
		if not line:
			continue
		match = column_regex.match(line)
		if not match:
			continue
		expr = match.group(1).strip()
		alias_name = match.group(2).strip()
		source_alias: Optional[str] = None
		source_field: Optional[str] = None
		alias_match = re.match(r"([A-Za-z_][\w]*)\.([A-Za-z_][\w]*)", expr)
		if alias_match:
			source_alias = alias_match.group(1)
			source_field = alias_match.group(2)
		column_map[alias_name] = (source_alias, source_field, expr)
	return column_map


def extract_where_clause(sql: str) -> str:
	# Backward-compatible wrapper: return all WHERE segments joined.
	return "\n".join(extract_where_clauses(sql))


def extract_where_clauses(sql: str) -> List[str]:
	"""Extract all WHERE clause segments in SQL.

	We intentionally scope parameter predicate extraction to WHERE + JOIN ON
	(to avoid SELECT/HAVING CASE expressions), but a query can contain multiple
	WHERE clauses (e.g., CTE + outer query). Returning only the first WHERE would
	miss later parameter predicates such as `g.a_id = $personId`.
	"""
	clean = strip_sql_comments(sql)
	clauses: List[str] = []
	for where_match in re.finditer(r"\bWHERE\b", clean, flags=re.IGNORECASE):
		start = where_match.end()
		remainder = clean[start:]
		end = len(remainder)
		for keyword in ["GROUP BY", "ORDER BY", "HAVING", "LIMIT", "UNION", "RETURN", "OFFSET"]:
			pattern = re.compile(rf"\b{keyword}\b", re.IGNORECASE)
			keyword_match = pattern.search(remainder)
			if keyword_match:
				end = min(end, keyword_match.start())
		segment = remainder[:end].strip()
		if segment:
			clauses.append(segment)
	return clauses


def extract_having_clause(sql: str) -> str:
	having_match = re.search(r"\bHAVING\b", sql, flags=re.IGNORECASE)
	if not having_match:
		return ""
	start = having_match.end()
	remainder = sql[start:]
	end = len(remainder)
	for keyword in ["ORDER BY", "LIMIT", "UNION", "RETURN", "OFFSET"]:
		pattern = re.compile(rf"\b{keyword}\b", re.IGNORECASE)
		keyword_match = pattern.search(remainder)
		if keyword_match:
			end = min(end, keyword_match.start())
	return remainder[:end]


def extract_join_on_clauses(sql: str) -> List[str]:
	"""Extract the ON-clause text of each JOIN.

	Note: We intentionally only extract ON clauses rather than scanning the entire SQL
	for parameter predicates. A common pattern in SELECT/HAVING is:
	`CASE WHEN x = $param THEN ...`, which is not a filter predicate. Treating such
	expressions as filters would pollute selectivity estimation and affect planning.
	"""
	clean = strip_sql_comments(sql)
	clauses: List[str] = []
	for match in re.finditer(r"\bON\b", clean, flags=re.IGNORECASE):
		start = match.end()
		remainder = clean[start:]
		end = len(remainder)
		for keyword in [
			"JOIN",
			"WHERE",
			"GROUP BY",
			"HAVING",
			"ORDER BY",
			"LIMIT",
			"UNION",
			"RETURN",
			"OFFSET",
		]:
			pattern = re.compile(rf"\b{keyword}\b", re.IGNORECASE)
			keyword_match = pattern.search(remainder)
			if keyword_match:
				end = min(end, keyword_match.start())
		segment = remainder[:end].strip()
		if segment:
			clauses.append(segment)
	return clauses


def parse_parameter_conditions(
	sql_text: str,
	graph_alias: Optional[str],
	column_map: Dict[str, Tuple[Optional[str], Optional[str], str]],
) -> Iterable[Tuple[str, str, Optional[str], List[str], str]]:
	clean_text = strip_sql_comments(sql_text)
	results: List[Tuple[str, str, Optional[str], List[str], str]] = []

	compare_regex = re.compile(
		r"(?P<lhs>[A-Za-z_][\w]*\.(?:\"[A-Za-z0-9_.]+\"|[A-Za-z_][\w]*))\s*(?P<op>=|<>|<=|>=|<|>)\s*\$(?P<param>[A-Za-z0-9_]+)",
		re.IGNORECASE,
	)
	in_regex = re.compile(
		r"(?P<lhs>[A-Za-z_][\w]*\.(?:\"[A-Za-z0-9_.]+\"|[A-Za-z_][\w]*))\s+(?P<op>IN|NOT IN)\s*\((?P<body>[^)]*)\)",
		re.IGNORECASE,
	)

	for match in compare_regex.finditer(clean_text):
		lhs = match.group("lhs")
		op = match.group("op")
		param = match.group("param")
		segment = match.group(0)
		results.append((lhs, op, None, [param], segment))

	for match in in_regex.finditer(clean_text):
		lhs = match.group("lhs")
		op = match.group("op").upper()
		body = match.group("body")
		params = []
		for token in body.split(","):
			token = token.strip()
			if token.startswith("$"):
				params.append(token[1:])
		segment = match.group(0)
		if params:
			results.append((lhs, op, None, params, segment))

	return results


def resolve_column_reference(
	lhs: str,
	graph_alias: Optional[str],
	column_map: Dict[str, Tuple[Optional[str], Optional[str], str]],
) -> Optional[Tuple[str, str]]:
	table_alias, _, column = lhs.partition(".")
	column = column.strip()
	if column.startswith('"') and column.endswith('"'):
		column = column[1:-1]

	# Support queries that wrap GRAPH_TABLE output in a CTE/subquery and then
	# reference projected columns via a different qualifier (e.g., `g.a_id`).
	# If the column name matches a GRAPH_TABLE projected column, map it back to
	# the originating graph alias/field.
	if column in column_map:
		source_alias, source_field, _ = column_map[column]
		if source_alias and source_field:
			return source_alias, source_field

	if graph_alias and table_alias == graph_alias:
		if column in column_map:
			source_alias, source_field, _ = column_map[column]
			if source_alias and source_field:
				return source_alias, source_field
		if "." in column:
			alias_part, field_part = column.split(".", 1)
			return alias_part, field_part
		if "_" in column:
			alias_part, field_part = column.split("_", 1)
			return alias_part, field_part
		return None

	if "." in column:
		alias_part, field_part = column.split(".", 1)
		return alias_part, field_part

	return table_alias, column


def collect_join_aliases(sql: str) -> Dict[str, str]:
	pattern = re.compile(
		r"\b(?:FROM|JOIN)\s+([A-Za-z_][\w]*)\s+(?:AS\s+)?([A-Za-z_][\w]*)",
		re.IGNORECASE,
	)
	reserved = {
		"where",
		"join",
		"from",
		"group",
		"by",
		"order",
		"having",
		"limit",
		"union",
		"return",
		"offset",
		"on",
		"inner",
		"left",
		"right",
		"full",
		"cross",
		"recursive",
	}
	aliases: Dict[str, str] = {}
	for match in pattern.finditer(sql):
		table = match.group(1)
		alias = match.group(2)
		if alias.lower() in reserved:
			continue
		if table.lower() == "graph_table":
			continue
		aliases.setdefault(alias, table)
	return aliases


def extract_sql_join_edges(sql: str) -> List[Dict[str, str]]:
	clean = strip_sql_comments(sql)
	eq_pattern = re.compile(
		r"([A-Za-z_][\w]*)\.(\"?[A-Za-z0-9_.]+\"?)\s*=\s*([A-Za-z_][\w]*)\.(\"?[A-Za-z0-9_.]+\"?)",
		re.IGNORECASE,
	)
	seen: Set[Tuple[str, str, str, str]] = set()
	edges: List[Dict[str, str]] = []
	for match in eq_pattern.finditer(clean):
		left = match.group(1)
		left_col = match.group(2)
		right = match.group(3)
		right_col = match.group(4)
		if left == right:
			continue
		key = (
			left,
			normalize_identifier(left_col),
			right,
			normalize_identifier(right_col),
		)
		if key in seen:
			continue
		seen.add(key)
		edges.append(
			{
				"left_alias": left,
				"left_column": left_col,
				"right_alias": right,
				"right_column": right_col,
				"condition": match.group(0).strip(),
			}
		)
	return edges


def extract_top_clause(sql: str) -> Optional[Dict[str, Any]]:
	"""Best-effort extraction of a top-k (ORDER BY + LIMIT/FETCH) from the outer query.

	We keep this intentionally lightweight (regex-based) and only use it as planning hints.
	If parsing fails, return None.
	"""
	clean = strip_sql_comments(sql)
	# Normalize whitespace a bit to make regex easier.
	clean = re.sub(r"\s+", " ", clean).strip()

	# Find a trailing LIMIT/FETCH FIRST.
	limit_k: Optional[int] = None
	limit_m = re.search(r"\bLIMIT\s+(\d+)\b", clean, flags=re.IGNORECASE)
	if limit_m:
		limit_k = int(limit_m.group(1))
	else:
		fetch_m = re.search(r"\bFETCH\s+FIRST\s+(\d+)\s+ROWS?\s+ONLY\b", clean, flags=re.IGNORECASE)
		if fetch_m:
			limit_k = int(fetch_m.group(1))
	if limit_k is None:
		return None

	# Heuristic: use the last ORDER BY in the statement as the outer order.
	order_by = None
	idx = clean.lower().rfind(" order by ")
	if idx != -1:
		order_part = clean[idx + len(" order by ") :]
		# Trim at LIMIT/FETCH if present.
		cut = re.search(r"\b(LIMIT|FETCH\s+FIRST)\b", order_part, flags=re.IGNORECASE)
		if cut:
			order_part = order_part[: cut.start()].strip()
		order_by = order_part.strip().rstrip(";")

	return {
		"k": limit_k,
		"order_by": order_by,
	}


class ICQueryCompiler:
	def __init__(
		self,
		catalog: GraphCatalog,
		schema: GLogsSchema,
		dataset: GraphDataset,
		params: Dict[str, Dict[str, Any]],
	) -> None:
		self.catalog = catalog
		self.schema = schema
		self.dataset = dataset
		self.params = params
		self._node_column_cache: Dict[str, Dict[str, str]] = {}
		self._relationship_column_cache: Dict[str, Dict[str, str]] = {}

	def _handle_ic10_month_clause(
		self,
		sql: str,
		graph_alias: Optional[str],
		column_map: Dict[str, Tuple[Optional[str], Optional[str], str]],
		params_for_query: ParameterResolver,
		found_params: set[str],
		resolved_param_keys: set[str],
		unmatched_param_names: set[str],
		alias_predicates: Dict[str, List[PredicateCondition]],
	) -> None:
		if graph_alias is None:
			return
		if "$month" not in sql:
			return
		if "b_birthday" not in column_map:
			return
		alias_ref = f"{graph_alias}.b_birthday"
		if alias_ref not in sql:
			return
		pattern = re.compile(
			rf"AND\s*\(\s*\(\s*EXTRACT\s*\(\s*MONTH\s+FROM\s+{re.escape(alias_ref)}\)\s*=\s*\$(?P<param>[A-Za-z0-9_]+).*?\)\s*OR\s*\(.*?\)\s*\)",
			flags=re.IGNORECASE | re.DOTALL,
		)
		match = pattern.search(sql)
		if not match:
			return
		param_name = match.group("param")
		found_params.add(param_name)
		value, canonical_key = params_for_query.resolve(param_name)
		if value is None:
			unmatched_param_names.add(ParameterResolver.normalize(param_name))
			return
		if canonical_key:
			resolved_param_keys.add(canonical_key)
		source_alias, source_field, _ = column_map["b_birthday"]
		if not source_alias or not source_field:
			return
		clause_text = match.group(0).strip()
		field_expr = f'CAST(epoch_ms("{source_field}") AS DATE)'
		expression_sql = (
			f"((EXTRACT(MONTH FROM {field_expr}) = ?) AND (EXTRACT(DAY FROM {field_expr}) >= 21)) "
			f"OR ((EXTRACT(MONTH FROM {field_expr}) = ((? % 12) + 1)) AND (EXTRACT(DAY FROM {field_expr}) < 22))"
		)
		predicate = PredicateCondition(
			alias=source_alias,
			column=source_field,
			operator="=",
			values=[value, value],
			expression=clause_text,
			parameter_names=[param_name],
			source_segment=clause_text,
			custom_sql=expression_sql,
		)
		alias_predicates.setdefault(source_alias, []).append(predicate)

	def _infer_sql_table_edges(
		self,
		alias_info: Dict[str, AliasInfo],
		sql_join_edges: List[Dict[str, str]],
		evaluation_errors: Dict[str, str],
		graph_alias: Optional[str],
		column_map: Dict[str, Tuple[Optional[str], Optional[str], str]],
	) -> List[Tuple[str, str]]:
		normalized_edges: List[Dict[str, Any]] = []
		graph_column_lookup: Dict[str, Tuple[str, Optional[str]]] = {}
		if graph_alias:
			for alias_name, (source_alias, source_field, _) in column_map.items():
				if not source_alias:
					continue
				norm = normalize_identifier(alias_name)
				graph_column_lookup[norm] = (source_alias, source_field)
		for edge in sql_join_edges:
			normalized_edges.append(
				{
					"left_alias": edge["left_alias"],
					"left_column_norm": normalize_identifier(edge.get("left_column")),
					"left_column_raw": edge.get("left_column"),
					"right_alias": edge["right_alias"],
					"right_column_norm": normalize_identifier(edge.get("right_column")),
					"right_column_raw": edge.get("right_column"),
				}
			)

		identity_pairs: List[Tuple[str, str]] = []
		identity_seen: Set[Tuple[str, str]] = set()

		def resolve_alias_name(
			alias: Optional[str],
			column_norm: Optional[str],
			column_raw: Optional[str],
		) -> Optional[str]:
			if not alias:
				return None
			# Map references to projected GRAPH_TABLE columns back to the originating graph vertex.
			# This supports cases where the SQL uses a CTE alias (e.g., `g.c_id`) instead of the
			# direct GRAPH_TABLE alias (e.g., `gt.c_id`).
			if column_norm and column_norm in graph_column_lookup and alias not in alias_info:
				return graph_column_lookup[column_norm][0]
			if graph_alias and alias == graph_alias:
				if column_norm and column_norm in graph_column_lookup:
					return graph_column_lookup[column_norm][0]
				if column_raw:
					clean = column_raw.strip('"')
					if "." in clean:
						prefix = clean.split(".", 1)[0]
						if prefix in alias_info:
							return prefix
					if "_" in clean:
						prefix = clean.split("_", 1)[0]
						if prefix in alias_info:
							return prefix
			return alias

		def is_vertex_id(alias: str, column_name: Optional[str]) -> bool:
			if not column_name:
				return False
			info = alias_info.get(alias)
			if not info or info.kind != "vertex":
				return False
			label = info.label
			id_column = "id"
			if label:
				node = self.catalog.get_node(label)
				if node:
					id_column = node.id_column
			return normalize_identifier(column_name) == normalize_identifier(id_column)

		def register_identity(graph_vertex: str, sql_vertex: str) -> None:
			key = (graph_vertex, sql_vertex)
			if key in identity_seen:
				return
			identity_seen.add(key)
			identity_pairs.append(key)

		if graph_alias:
			for edge in normalized_edges:
				graph_side: Optional[Tuple[str, Optional[str]]] = None
				other_alias: Optional[str] = None
				other_column: Optional[str] = None
				if edge["left_alias"] == graph_alias:
					if edge["left_column_norm"] in graph_column_lookup:
						graph_side = graph_column_lookup[edge["left_column_norm"]]
					other_alias = resolve_alias_name(
						edge["right_alias"],
						edge["right_column_norm"],
						edge["right_column_raw"],
					)
					other_column = edge["right_column_raw"]
				elif edge["right_alias"] == graph_alias:
					if edge["right_column_norm"] in graph_column_lookup:
						graph_side = graph_column_lookup[edge["right_column_norm"]]
					other_alias = resolve_alias_name(
						edge["left_alias"],
						edge["left_column_norm"],
						edge["left_column_raw"],
					)
					other_column = edge["left_column_raw"]
				if not graph_side or not other_alias or not other_column:
					continue
				graph_vertex, graph_field = graph_side
				if graph_vertex not in alias_info or other_alias not in alias_info:
					continue
				graph_info = alias_info[graph_vertex]
				other_info = alias_info[other_alias]
				if graph_info.kind != "vertex" or other_info.kind != "vertex":
					continue
				if not is_vertex_id(graph_vertex, graph_field):
					continue
				canonical_col = self._canonicalize_column_name(other_alias, other_column, alias_info)
				if not is_vertex_id(other_alias, canonical_col):
					continue
				if classify_origin(graph_info.origin) == classify_origin(other_info.origin):
					continue
				register_identity(graph_vertex, other_alias)

		for alias, info in alias_info.items():
			if info.kind != "table":
				continue
			if info.source_alias and info.target_alias:
				continue
			rel_key = info.relationship_key or info.dataset_hint
			if not rel_key:
				evaluation_errors[alias] = "Unable to determine relationship dataset key"
				continue
			rel_meta = self.catalog.get_relationship_by_key(rel_key)
			if rel_meta is None:
				evaluation_errors[alias] = f"Relationship metadata not found: {rel_key}"
				continue
			src_norm = normalize_identifier(rel_meta.source_column)
			tgt_norm = normalize_identifier(rel_meta.target_column)
			source_label_norm = (rel_meta.source_label or "").lower()
			target_label_norm = (rel_meta.target_label or "").lower()
			candidates: List[Dict[str, Any]] = []
			for edge in normalized_edges:
				if edge["left_alias"] == alias:
					col_norm = edge["left_column_norm"]
					other_alias = edge["right_alias"]
					other_col_norm = edge["right_column_norm"]
					other_col_raw = edge["right_column_raw"]
				elif edge["right_alias"] == alias:
					col_norm = edge["right_column_norm"]
					other_alias = edge["left_alias"]
					other_col_norm = edge["left_column_norm"]
					other_col_raw = edge["left_column_raw"]
				else:
					continue
				resolved_alias = resolve_alias_name(other_alias, other_col_norm, other_col_raw)
				if not resolved_alias or resolved_alias not in alias_info:
					continue
				other_info = alias_info[resolved_alias]
				candidates.append(
					{
						"alias": resolved_alias,
						"label_norm": (other_info.label or "").lower() if other_info.label else None,
						"column_norm": col_norm,
						"column_raw": other_col_raw,
					}
				)
			src_alias: Optional[str] = info.source_alias
			tgt_alias: Optional[str] = info.target_alias
			if not candidates:
				evaluation_errors[alias] = f"Unable to infer endpoints for relationship {alias}"
				continue

			if source_label_norm and target_label_norm and source_label_norm != target_label_norm:
				for candidate in candidates:
					if not src_alias and candidate["label_norm"] == source_label_norm:
						src_alias = candidate["alias"]
					continue
				for candidate in candidates:
					if not tgt_alias and candidate["label_norm"] == target_label_norm and candidate["alias"] != src_alias:
						tgt_alias = candidate["alias"]
						break

			if (not src_alias or not tgt_alias) and (src_norm or tgt_norm):
				for candidate in candidates:
					if not src_alias and candidate["column_norm"] == src_norm:
						src_alias = candidate["alias"]
						continue
					if not tgt_alias and candidate["column_norm"] == tgt_norm and candidate["alias"] != src_alias:
						tgt_alias = candidate["alias"]

			if not src_alias or not tgt_alias:
				distinct_aliases: List[str] = []
				for candidate in candidates:
					alias_candidate = candidate["alias"]
					if alias_candidate not in distinct_aliases:
						distinct_aliases.append(alias_candidate)
				if not src_alias and distinct_aliases:
					src_alias = distinct_aliases[0]
				if (not tgt_alias or tgt_alias == src_alias) and len(distinct_aliases) >= 2:
					tgt_alias = distinct_aliases[1] if distinct_aliases[0] == src_alias else distinct_aliases[0]

			if src_alias and tgt_alias and src_alias != tgt_alias:
				info.source_alias = src_alias
				info.target_alias = tgt_alias
			else:
				evaluation_errors[alias] = f"Unable to infer endpoints for relationship {alias}"

		return identity_pairs

	def _insert_column_alias(
		self,
		mapping: Dict[str, str],
		column_name: str,
		base_counts: Optional[Dict[str, int]] = None,
	) -> None:
		if not column_name:
			return
		clean = column_name.strip()
		norm = normalize_identifier(clean)
		if norm and norm not in mapping:
			mapping[norm] = clean
		if base_counts is None:
			return
		base = clean
		if "__" in base:
			base = base.split("__", 1)[0]
		base_key = normalize_identifier(base)
		if not base_key:
			return
		base_counts[base_key] = base_counts.get(base_key, 0) + 1
		ordinal = base_counts[base_key]
		ordinal_key = f"{base_key}{ordinal}"
		mapping.setdefault(ordinal_key, clean)
		if base_key.endswith("id"):
			prefix = base_key[:-2]
			mapping.setdefault(f"{prefix}{ordinal}id", clean)

	def _get_node_column_mapping(self, label: Optional[str]) -> Dict[str, str]:
		if not label:
			return {}
		key = label.lower()
		if key in self._node_column_cache:
			return self._node_column_cache[key]
		node = self.catalog.get_node(label)
		if node is None:
			return {}
		mapping: Dict[str, str] = {}
		columns = [node.id_column] + node.properties
		for column_name in columns:
			self._insert_column_alias(mapping, column_name)
		self._node_column_cache[key] = mapping
		return mapping

	def _get_relationship_column_mapping(self, rel_key: Optional[str]) -> Dict[str, str]:
		if not rel_key:
			return {}
		if rel_key in self._relationship_column_cache:
			return self._relationship_column_cache[rel_key]
		rel = self.catalog.get_relationship_by_key(rel_key)
		if rel is None:
			return {}
		mapping: Dict[str, str] = {}
		base_counts: Dict[str, int] = {}
		columns = [rel.source_column, rel.target_column] + rel.properties
		for column_name in columns:
			self._insert_column_alias(mapping, column_name, base_counts)
		self._relationship_column_cache[rel_key] = mapping
		return mapping

	def _canonicalize_column_name(
		self,
		alias: str,
		column: str,
		alias_info: Dict[str, AliasInfo],
	) -> str:
		info = alias_info.get(alias)
		if not info or not column:
			return column.strip('"')
		column_clean = column.strip('"')
		mapping: Dict[str, str] = {}
		if info.kind == "vertex":
			mapping = self._get_node_column_mapping(info.label)
		elif info.kind in {"edge", "table"}:
			rel_key = info.relationship_key or info.dataset_hint
			mapping = self._get_relationship_column_mapping(rel_key)
		return mapping.get(normalize_identifier(column_clean), column_clean)

	def _resolve_relation(
		self,
		rel_type: str,
		source_label: str,
		target_label: str,
	) -> Tuple[Optional[int], Optional[str], bool, Optional[RelationshipInfo], Optional[str], Optional[str]]:
		relation_id = self.schema.get_relation_id(rel_type, source_label, target_label)
		relation_label = self.schema.get_relation_label(rel_type, source_label, target_label)
		rel_info = self.catalog.find_relationship(rel_type, source_label, target_label)
		if relation_id is not None:
			return relation_id, relation_label, False, rel_info, source_label, target_label
		normalized = normalize_rel_name(rel_type)
		override = RELATION_TYPE_OVERRIDES.get(normalized)
		if override:
			lookup_type = override.get("canonical_type", rel_type)
			lookup_source = source_label
			lookup_target = target_label
			is_reversed = False
			if override.get("swap"):
				lookup_source, lookup_target = target_label, source_label
				is_reversed = True
			rel_id = self.schema.get_relation_id(lookup_type, lookup_source, lookup_target)
			rel_label = self.schema.get_relation_label(lookup_type, lookup_source, lookup_target)
			rel_descr = self.catalog.find_relationship(lookup_type, lookup_source, lookup_target)
			if rel_id is not None:
				return rel_id, rel_label, is_reversed, rel_descr, lookup_source, lookup_target
		rel_id = self.schema.get_relation_id(rel_type, target_label, source_label)
		rel_label = self.schema.get_relation_label(rel_type, target_label, source_label)
		rel_descr = self.catalog.find_relationship(rel_type, target_label, source_label)
		if rel_id is not None:
			return rel_id, rel_label, True, rel_descr, target_label, source_label
		return None, None, False, rel_info, source_label, target_label

	def compile(self, query_name: str, sql: str) -> Tuple[Dict[str, Any], Dict[str, Any]]:
		try:
			block, graph_alias, _ = extract_graph_table_block(sql)
		except ValueError:
			graph_alias = None
			match_section = extract_plain_match_section(sql)
			columns_body = ""
		else:
			match_start = block.lower().find("match")
			columns_start = block.lower().find("columns")
			if match_start == -1 or columns_start == -1:
				raise ValueError("GRAPH_TABLE block is missing MATCH or COLUMNS")
			match_section = block[match_start + len("match"):columns_start]
			columns_body = block[columns_start + len("columns"):]
			columns_body = columns_body.strip()
			if columns_body.startswith("(") and columns_body.endswith(")"):
				columns_body = columns_body[1:-1]

		vertex_labels, edges = parse_match_section(match_section)
		column_map = parse_columns_section(columns_body) if columns_body else {}

		alias_info: Dict[str, AliasInfo] = {}
		for alias, label in vertex_labels.items():
			label_id = self.schema.get_label_id(label)
			alias_info[alias] = AliasInfo(
				alias=alias,
				kind="vertex",
				label=label,
				label_id=label_id,
				origin="match_graph",
			)

		for edge in edges:
			rel_alias = edge.get("alias")
			if not rel_alias:
				continue
			source_alias = edge["source_alias"]
			target_alias = edge["target_alias"]
			source_label = vertex_labels.get(source_alias)
			target_label = vertex_labels.get(target_alias)
			if not source_label or not target_label:
				continue
			relation_id, relation_label, _, rel_info, _, _ = self._resolve_relation(
				edge["type"],
				source_label,
				target_label,
			)
			alias_info[rel_alias] = AliasInfo(
				alias=rel_alias,
				kind="edge",
				relationship_key=rel_info.key if rel_info else None,
				relationship_type=edge["type"],
				relationship_label=relation_label,
				relation_id=relation_id,
				schema_label=relation_label,
				source_alias=source_alias,
				target_alias=target_alias,
				origin="match_edge",
			)

		join_aliases = collect_join_aliases(sql)
		for alias, table in join_aliases.items():
			if alias in alias_info:
				continue
			node_info = self.catalog.get_node(table)
			if node_info:
				label_id = self.schema.get_label_id(node_info.label)
				alias_info[alias] = AliasInfo(
					alias=alias,
					kind="vertex",
					label=node_info.label,
					label_id=label_id,
					origin="sql_join",
					dataset_hint=table,
				)
				continue
			rel_info = self.catalog.get_relationship_by_key(table)
			if rel_info:
				relation_label = self.schema.get_relation_label(rel_info.type, rel_info.source_label, rel_info.target_label)
				relation_id = self.schema.get_relation_id(rel_info.type, rel_info.source_label, rel_info.target_label)
				alias_info[alias] = AliasInfo(
					alias=alias,
					kind="table",
					relationship_key=rel_info.key,
					relationship_type=rel_info.type,
					relationship_label=relation_label,
					relation_id=relation_id,
					schema_label=relation_label,
					label=relation_label or rel_info.type,
					dataset_hint=table,
					origin="sql_join",
				)

		params_for_query = ParameterResolver(self.params.get(query_name, {}))

		alias_predicates: Dict[str, List[PredicateCondition]] = {}
		unresolved_conditions: List[str] = []

		where_clause = extract_where_clause(sql)
		on_clauses = extract_join_on_clauses(sql)
		# Only extract parameter predicates from WHERE + JOIN ON:
		# - Covers ON-clause parameter conditions (e.g., ic-4: f.creationDate < $startDate)
		# - Avoids treating CASE WHEN ... = $param ... in SELECT/HAVING as filter predicates
		param_text = "\n".join([part for part in [where_clause, *on_clauses] if part])
		param_occurrences = parse_parameter_conditions(param_text or where_clause or "", graph_alias, column_map)
		sql_join_edges = extract_sql_join_edges(sql)
		found_params: set[str] = set()
		resolved_param_keys: set[str] = set()
		unmatched_param_names: set[str] = set()

		for lhs, op, _, param_names, expr in param_occurrences:
			for name in param_names:
				found_params.add(name)
				resolved = resolve_column_reference(lhs, graph_alias, column_map)
				if not resolved:
					unresolved_conditions.append(expr)
					continue
				target_alias, column = resolved
				column = self._canonicalize_column_name(target_alias, column, alias_info)
				values: List[Any] = []
				missing = False
				for param in param_names:
					value, canonical_key = params_for_query.resolve(param)
					if value is None:
						missing = True
						unmatched_param_names.add(ParameterResolver.normalize(param))
						break
					values.append(value)
					if canonical_key:
						resolved_param_keys.add(canonical_key)
				if missing:
					unresolved_conditions.append(expr)
					continue
				predicate = PredicateCondition(
					alias=target_alias,
					column=column,
					operator=op,
					values=values,
					expression=expr.strip(),
					parameter_names=param_names,
					source_segment=expr.strip(),
				)
				alias_predicates.setdefault(target_alias, []).append(predicate)

		if query_name.lower() == "ic-10":
			self._handle_ic10_month_clause(
				sql,
				graph_alias,
				column_map,
				params_for_query,
				found_params,
				resolved_param_keys,
				unmatched_param_names,
				alias_predicates,
			)

		for alias, predicates in list(alias_predicates.items()):
			alias_predicates[alias] = deduplicate_predicates(predicates)

		expected_params = set(self.params.get(query_name, {}).keys())
		expected_params_lower = {ParameterResolver.normalize(key) for key in expected_params}
		found_params_lower = {ParameterResolver.normalize(name) for name in found_params}
		resolved_params_lower = {ParameterResolver.normalize(key) for key in resolved_param_keys}
		missing_params = sorted(expected_params_lower - resolved_params_lower)
		extra_params = sorted(found_params_lower - expected_params_lower)
		unmatched_params = sorted(unmatched_param_names)
		found_list = sorted(found_params_lower)
		resolved_list = sorted(resolved_params_lower)

		# --- ic-10: count (c:Post)-[:HAS_TAG]->(d:Tag) even if implemented inside a derived-table subquery ---
		# The ic-10 SQL often computes per-post "hit" via a derived table `x` and only joins `x.c_id = g.c_id`.
		# In that form, `post_hasTag_tag pht` doesn't directly join to the graph alias, so the generic SQL-edge
		# inference cannot recover the (Post_hasTag_Tag) relationship endpoints.
		#
		# We add two synthetic equalities so `_infer_sql_table_edges` can infer:
		#   pht.postId = g.c_id   (connect pht to graph vertex c)
		#   pht.tagId  = d.id     (introduce Tag vertex d)
		# and we drop `hi` (hasInterest) as an edge because it's a scoring helper here.
		if query_name.lower() == "ic-10" and graph_alias:
			pht_alias: Optional[str] = None
			hi_alias: Optional[str] = None
			for alias, info in alias_info.items():
				if info.kind != "table":
					continue
				hint = (info.dataset_hint or info.relationship_key or "").lower()
				if hint == "post_hastag_tag":
					pht_alias = alias
				elif hint == "person_hasinterest_tag":
					hi_alias = alias
			if hi_alias and hi_alias in alias_info:
				alias_info.pop(hi_alias, None)
			if pht_alias:
				# Ensure Tag vertex exists (sql domain).
				if "d" not in alias_info:
					label_id = self.schema.get_label_id("Tag")
					alias_info["d"] = AliasInfo(
						alias="d",
						kind="vertex",
						label="Tag",
						label_id=label_id,
						origin="sql_join",
						dataset_hint="tag",
					)
				# Only add these if GRAPH_TABLE projected column exists.
				if "c_id" in column_map:
					sql_join_edges.append(
						{
							"left_alias": pht_alias,
							"left_column": "postId",
							"right_alias": graph_alias,
							"right_column": "c_id",
							"condition": f"{pht_alias}.postId = {graph_alias}.c_id (synthetic ic-10)",
						}
					)
					sql_join_edges.append(
						{
							"left_alias": pht_alias,
							"left_column": "tagId",
							"right_alias": "d",
							"right_column": "id",
							"condition": f"{pht_alias}.tagId = d.id (synthetic ic-10)",
						}
					)

		evaluation_errors: Dict[str, str] = {}
		identity_pairs = self._infer_sql_table_edges(
			alias_info,
			sql_join_edges,
			evaluation_errors,
			graph_alias,
			column_map,
		)

		aliases_output: Dict[str, Dict[str, Any]] = {}
		vertices: List[Dict[str, Any]] = []
		alias_to_tag: Dict[str, int] = {}
		vertex_aliases = [alias for alias, info in alias_info.items() if info.kind == "vertex"]
		for idx, alias in enumerate(vertex_aliases):
			alias_to_tag[alias] = idx
		domain_map: Dict[str, str] = {alias: classify_origin(info.origin) for alias, info in alias_info.items()}

		for alias, info in alias_info.items():
			predicates = alias_predicates.get(alias, [])
			try:
				_, combined = self.dataset.evaluate(info, predicates)
			except Exception as exc:
				evaluation_errors[alias] = f"{type(exc).__name__}: {exc}"
				combined = PredicateStats(
					expression="TRUE",
					matched_rows=0,
					total_rows=0,
					selectivity=1.0,
				)
			display_label = info.label or info.schema_label
			alias_entry: Dict[str, Any] = {
				"kind": info.kind,
				"domain": domain_map[alias],
				"label": display_label,
				"label_id": info.label_id,
				"relationship_type": info.relationship_type,
				"relationship_key": info.relationship_key,
				"relationship_label": info.relationship_label,
				"relation_id": info.relation_id,
				"dataset_key": info.dataset_hint,
				"combined": {
					"expression": combined.expression,
					"matched_rows": combined.matched_rows,
					"total_rows": combined.total_rows,
					"selectivity": combined.selectivity,
				},
			}
			if info.schema_label:
				alias_entry["schema_label"] = info.schema_label
			if predicates:
				alias_entry["filters"] = [
					{"expression": predicate.expression.strip()}
					for predicate in predicates
				]
			aliases_output[alias] = alias_entry
			if info.kind == "vertex":
				label_id = info.label_id
				if info.label and label_id is None:
					evaluation_errors.setdefault(alias, "Unknown label_id")
				vertices.append(
					{
						"tag_id": alias_to_tag[alias],
						"alias": alias,
						"label": info.label,
						"label_id": label_id,
						"domain": domain_map[alias],
						"combined_selectivity": combined.selectivity,
					}
				)

		edges_output: List[Dict[str, Any]] = []
		for idx, edge in enumerate(edges):
			source_alias = edge["source_alias"]
			target_alias = edge["target_alias"]
			source_label = vertex_labels.get(source_alias, "")
			target_label = vertex_labels.get(target_alias, "")
			relation_id = None
			relation_label = None
			is_reversed = False
			schema_source_label = source_label
			schema_target_label = target_label
			if edge.get("type") and source_label and target_label:
				relation_id, relation_label, is_reversed, _, schema_source_label, schema_target_label = self._resolve_relation(
					edge["type"],
					source_label,
					target_label,
				)
				if relation_id is None:
					evaluation_errors.setdefault(f"edge_{idx}", "Unknown relation_id")
			edges_output.append(
				{
					"edge_id": idx,
					"alias": edge.get("alias"),
					"type": edge.get("type"),
					"source_alias": source_alias,
					"target_alias": target_alias,
					"source_tag": alias_to_tag.get(source_alias),
					"target_tag": alias_to_tag.get(target_alias),
					"relation_id": relation_id,
					"relation_label": relation_label,
					"schema_source_label": schema_source_label,
					"schema_target_label": schema_target_label,
					"min_hops": edge.get("min_hops"),
					"max_hops": edge.get("max_hops"),
					"is_path": edge.get("is_path"),
					"path_alias": edge.get("path_alias"),
					"is_var_expand": edge.get("is_var_expand", False),
					"is_reversed": is_reversed,
					"is_identity": False,
					"origin": "match_edge",
				}
			)

		sql_edge_start_idx = len(edges_output)
		edge_counter = sql_edge_start_idx
		for alias, info in alias_info.items():
			if info.kind != "table":
				continue
			if not info.source_alias or not info.target_alias:
				continue
			if info.relation_id is None:
				evaluation_errors.setdefault(alias, "Missing relation_id")
				continue
			source_tag = alias_to_tag.get(info.source_alias)
			target_tag = alias_to_tag.get(info.target_alias)
			if source_tag is None or target_tag is None:
				evaluation_errors.setdefault(alias, "Endpoint is missing tag_id")
				continue
			schema_source_label = alias_info.get(info.source_alias).label if alias_info.get(info.source_alias) else None
			schema_target_label = alias_info.get(info.target_alias).label if alias_info.get(info.target_alias) else None
			edges_output.append(
				{
					"edge_id": edge_counter,
					"alias": alias,
					"type": info.relationship_type,
					"source_alias": info.source_alias,
					"target_alias": info.target_alias,
					"source_tag": source_tag,
					"target_tag": target_tag,
					"relation_id": info.relation_id,
					"relation_label": info.relationship_label,
					"schema_source_label": schema_source_label,
					"schema_target_label": schema_target_label,
					"min_hops": 1,
					"max_hops": 1,
					"is_path": False,
					"path_alias": None,
					"is_var_expand": False,
					"is_reversed": False,
					"is_identity": False,
					"origin": "sql_edge",
				}
			)
			edge_counter += 1

		for graph_vertex, sql_vertex in identity_pairs:
			source_tag = alias_to_tag.get(graph_vertex)
			target_tag = alias_to_tag.get(sql_vertex)
			graph_info = alias_info.get(graph_vertex)
			sql_info = alias_info.get(sql_vertex)
			if (
				source_tag is None
				or target_tag is None
				or graph_info is None
				or sql_info is None
			):
				continue
			edges_output.append(
				{
					"edge_id": edge_counter,
					"alias": f"{graph_vertex}__{sql_vertex}",
					"type": "identity",
					"source_alias": graph_vertex,
					"target_alias": sql_vertex,
					"source_tag": source_tag,
					"target_tag": target_tag,
					"relation_id": None,
					"relation_label": "IDENTITY_BRIDGE",
					"schema_source_label": graph_info.label,
					"schema_target_label": sql_info.label,
					"min_hops": 1,
					"max_hops": 1,
					"is_path": False,
					"path_alias": None,
					"is_var_expand": False,
					"is_reversed": False,
					"is_identity": True,
					"origin": "identity_edge",
				}
			)
			edge_counter += 1

		filter_output = {
			"query": query_name,
			"graph_alias": graph_alias,
			"top": extract_top_clause(sql) or {},
			"aliases": aliases_output,
			"vertices": vertices,
			"edges": edges_output,
			"unresolved_conditions": unresolved_conditions,
			"parameters": self.params.get(query_name, {}),
			"evaluation_errors": evaluation_errors,
		}

		match_vertices = []
		for alias in vertex_aliases:
			if domain_map.get(alias) != "match":
				continue
			info = alias_info[alias]
			label_name = info.label
			label_id = info.label_id
			match_vertices.append(
				{
					"tag_id": alias_to_tag[alias],
					"alias": alias,
					"label": label_name,
					"label_id": label_id,
				}
			)
		match_edges = [
			{
				"edge_id": edge["edge_id"],
				"alias": edge.get("alias"),
				"type": edge.get("type"),
				"relation_id": edge.get("relation_id"),
				"relation_label": edge.get("relation_label"),
				"schema_source_label": edge.get("schema_source_label"),
				"schema_target_label": edge.get("schema_target_label"),
				"source_tag": edge.get("source_tag"),
				"target_tag": edge.get("target_tag"),
				"min_hops": edge.get("min_hops"),
				"max_hops": edge.get("max_hops"),
				"is_var_expand": edge.get("is_var_expand", False),
				"is_reversed": edge.get("is_reversed", False),
				"is_identity": edge.get("is_identity", False),
			}
			for edge in edges_output
			if edge.get("origin") == "match_edge"
		]
		sql_vertices = []
		for alias in vertex_aliases:
			if domain_map.get(alias) != "sql":
				continue
			info = alias_info[alias]
			sql_vertices.append(
				{
					"tag_id": alias_to_tag[alias],
					"alias": alias,
					"label": info.label,
					"label_id": info.label_id,
				}
			)
		sql_edges = [
			{
				"edge_id": edge["edge_id"],
				"alias": edge.get("alias"),
				"type": edge.get("type"),
				"relation_id": edge.get("relation_id"),
				"relation_label": edge.get("relation_label"),
				"schema_source_label": edge.get("schema_source_label"),
				"schema_target_label": edge.get("schema_target_label"),
				"source_tag": edge.get("source_tag"),
				"target_tag": edge.get("target_tag"),
				"min_hops": edge.get("min_hops"),
				"max_hops": edge.get("max_hops"),
				"is_var_expand": edge.get("is_var_expand", False),
				"is_reversed": edge.get("is_reversed", False),
				"is_identity": edge.get("is_identity", False),
			}
			for edge in edges_output
			if edge.get("origin") in {"sql_edge", "identity_edge"}
		]

		pattern_output: Dict[str, Any] = {
			"query": query_name,
			"match": {
				"graph_alias": graph_alias,
				"vertices": match_vertices,
				"edges": match_edges,
			},
			"sql": {
				"vertices": sql_vertices,
				"edges": sql_edges,
			},
			"alias_domains": domain_map,
		}

		return filter_output, pattern_output


def load_params() -> Dict[str, Dict[str, Any]]:
	raw = json.loads(PARAMS_PATH.read_text(encoding="utf-8"))
	normalized: Dict[str, Dict[str, Any]] = {}
	for key, value in raw.items():
		normalized[key.lower()] = value
	return normalized


def build_argument_parser() -> argparse.ArgumentParser:
	parser = argparse.ArgumentParser(description="Compile LDBC IC queries into filter metadata")
	parser.add_argument("--query", dest="queries", action="append", help="Only process specified queries (e.g., ic-1)")
	parser.add_argument("--all", action="store_true", help="Process all queries")
	return parser


def main() -> None:
	parser = build_argument_parser()
	args = parser.parse_args()

	params = load_params()
	catalog = GraphCatalog(GRAPH_CATALOG_PATH)
	schema = GLogsSchema(GLOGS_SCHEMA_PATH)
	dataset = GraphDataset(catalog, DATASET_ROOT)
	compiler = ICQueryCompiler(catalog, schema, dataset, params)

	if args.queries and not args.all:
		targets = [q.lower() for q in args.queries]
	else:
		targets = [f"ic-{idx}" for idx in range(1, 13)]

	QUERY_FILTERS_DIR.mkdir(parents=True, exist_ok=True)
	QUERY_PATTERN_DIR.mkdir(parents=True, exist_ok=True)

	for target in targets:
		query_sql_path = IC_DIR / f"IC-{target.split('-')[-1].upper()}.sql"
		if query_sql_path.exists():
			sql = query_sql_path.read_text(encoding="utf-8")
		else:
			aggregate = (IC_DIR / "IC1~12.sql").read_text(encoding="utf-8")
			pattern = re.compile(rf"--\s*{re.escape(target)}:\s*(SELECT.*?);", re.IGNORECASE | re.DOTALL)
			match = pattern.search(aggregate)
			if not match:
				raise FileNotFoundError(f"Query not found: {target}")
			sql = match.group(1)

		filter_output, pattern_output = compiler.compile(target, sql)
		filter_path = QUERY_FILTERS_DIR / f"{target}_filters.json"
		pattern_path = QUERY_PATTERN_DIR / f"{target}.json"
		filter_path.write_text(json.dumps(filter_output, indent=2, ensure_ascii=False), encoding="utf-8")
		pattern_path.write_text(json.dumps(pattern_output, indent=2, ensure_ascii=False), encoding="utf-8")
		print(f"[INFO] Wrote {filter_path} and {pattern_path}")


if __name__ == "__main__":
	main()
