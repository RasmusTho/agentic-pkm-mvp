"""MVR-05A2 (#4576): the durable-table binding-classification mechanism.

This module is the shared half of the classification gate. It derives three
things from the repository itself and never from a hand-maintained list:

1. **The durable-table population** — every table the Alembic revision chain
   creates (``discover_durable_tables``). MVR-05A2's contract is that the gate
   fails on ``discovered_durable_tables - classified_tables``, so a table
   introduced by a revision *that does not exist yet* fails the gate until a
   human classifies it. A gate that enumerated today's tables would be
   satisfied forever the moment that list was cleared; this one is not.
2. **Every durable mutation path** — every ``INSERT`` / ``UPDATE`` /
   ``DELETE`` / ``TRUNCATE`` / ``COPY`` under ``app/**`` that targets a
   discovered durable table (``discover_durable_mutation_paths``).
3. **Every durable DDL seam outside the revision chain** —
   ``discover_runtime_ddl_seams``, the derived successor to MVR-05A1's
   hand-named ``app/db/db.py`` check. It is a *backstop*: the two seams that
   matter most are proved behaviourally instead, by running them against a
   recording connection and reading the statement list
   (``tests/architecture/test_durable_table_ownership.py``). Three review
   rounds each found a new way to satisfy a structural read of
   ``app/stores/pg.py`` while the runtime still reshaped a migration-owned
   table; none of those survives being asked what the function executes.

Why an AST resolver rather than a plain regex
---------------------------------------------
The three real spellings in this repository are not all literal:

* ``op.create_table("standing_questions", ...)`` — an Alembic operation call;
* ``CREATE TABLE IF NOT EXISTS public.objects (...)`` — a literal SQL string;
* ``f"CREATE TABLE IF NOT EXISTS {_TABLE} ("`` — an f-string over a
  module-level constant (`app/heimdal/**`, `app/knowledge_acquisition/**`,
  three Alembic revisions, and every replay projection producer).

A regex over raw source sees ``{_TABLE}`` and silently attributes nothing, so
a whole class of durable tables and producers would be invisible to the gate
while it still reported green. The resolver below therefore reads the *values*
statically: module constants, function-local constants, ``for`` targets bound
to a literal sequence, and one level of parameter resolution from same-module
call sites.

The load-bearing rule is the failure mode, not the coverage: an expression the
resolver cannot reduce to literal table names raises
:class:`UnresolvedTableExpression`. An unattributable durable statement stops
the build; it is never skipped. Widening the resolver is a real change with a
real diff — silently dropping a statement is not.
"""

from __future__ import annotations

import ast
import json
import re
from dataclasses import dataclass
from functools import lru_cache
from types import MappingProxyType
from pathlib import Path
from typing import Iterable, Iterator, Mapping, Sequence

REPO_ROOT = Path(__file__).resolve().parents[2]
ALEMBIC_VERSIONS = REPO_ROOT / "app" / "alembic" / "versions"
APP_ROOT = REPO_ROOT / "app"
TESTS_ROOT = REPO_ROOT / "tests"
MANIFEST_PATH = Path(__file__).with_name("durable_table_classification.json")

#: The two classifications a durable table may carry. There is no third value,
#: no default, and no wildcard: `explicitly-global` is a written claim with a
#: reason, never a fallback for "nobody looked at this one".
CLASSIFICATIONS = ("binding-scoped", "explicitly-global")

#: Whether the row identity already carries a binding/vault identity.
#: `pending` is what puts a row on the cutover worklist.
BINDING_KEY_STATES = ("keyed", "pending", "not-applicable")

#: The three checkable conditions that route the downstream table-group
#: children (`docs/MULTI_VAULT_RUNTIME/ROUTE_REQUESTS_THROUGH_ACTIVE_CONTEXT.md
#: :: 05A child decomposition`). "Needs a schema-parity proof written from
#: scratch" is deliberately **not** one of them: nine of the fifteen tables the
#: three table groups own need one — `parity_pins` measures seven pins across
#: the whole pending worklist — so it would escalate every group and
#: discriminate between none of them. These three do discriminate: MVR-05A3
#: trips on all five of its tables, MVR-05A4 on two of four, MVR-05A5 on all
#: six but for two different reasons.
ESCALATION_CONDITIONS = (
    # A primary key or unique constraint must be rewritten, rather than an
    # additive binding column plus an additive index being sufficient.
    "key-rewrite",
    # An inbound foreign-key target whose consumer set must be re-derived
    # before its key can move.
    "inbound-fk-target",
    # Rows carry authority or receipt provenance.
    "authority-or-receipt-rows",
)

#: How a producer replaces the table's contents. Derived, not declared:
#: `whole-table-replacement` is exactly "some producer issues TRUNCATE".
REBUILD_MECHANISMS = ("whole-table-replacement", "row-scoped", "no-producer")

_MUTATION_VERB_PATTERNS: tuple[tuple[str, str], ...] = (
    ("insert", r"insert\s+into\s+"),
    ("update", r"update\s+(?:only\s+)?"),
    ("delete", r"delete\s+from\s+(?:only\s+)?"),
    ("truncate", r"truncate\s+(?:table\s+)?(?:only\s+)?"),
    ("copy", r"copy\s+"),
)

_DDL_VERB_PATTERNS: tuple[tuple[str, str], ...] = (
    (
        "create table",
        r"create\s+(?:unlogged\s+|temporary\s+|temp\s+)?table\s+(?:if\s+not\s+exists\s+)?",
    ),
    ("alter table", r"alter\s+table\s+(?:if\s+exists\s+)?(?:only\s+)?"),
    ("drop table", r"drop\s+table\s+(?:if\s+exists\s+)?"),
)

#: DDL that reshapes an object *attached to* a durable table rather than the
#: table itself. An index, trigger or rule dropped and recreated against a
#: migration-owned table is the same drop-and-re-add mechanism MVR-05A1 (#4560)
#: removed from `objects_pkey`, so it cannot be outside the scan's vocabulary.
#: These take the table after `ON`, not in first position.
_ATTACHED_DDL_VERB_PATTERNS: tuple[tuple[str, str], ...] = (
    (
        "create index",
        r"create\s+(?:unique\s+)?index\s+(?:concurrently\s+)?(?:if\s+not\s+exists\s+)?"
        r"[\w\"]+\s+on\s+",
    ),
    ("drop index", r"drop\s+index\s+(?:concurrently\s+)?(?:if\s+exists\s+)?[\w\"]+\s*(?:on\s+)?"),
    ("create trigger", r"create\s+(?:or\s+replace\s+)?(?:constraint\s+)?trigger\s+[^;]*?\bon\s+"),
    ("drop trigger", r"drop\s+trigger\s+(?:if\s+exists\s+)?[\w\"]+\s+on\s+"),
    ("create rule", r"create\s+(?:or\s+replace\s+)?rule\s+[^;]*?\bon\s+"),
)

# A table reference the resolver could not reduce to a literal. It is spelled
# so that it can never collide with a real identifier.
_UNRESOLVED = "\x00unresolved\x00"

#: Subtrees that carry their own schema lineage, separate from
#: `app/alembic/versions/**`: the BuilderOps control plane
#: (`app/builderops/control_plane/migrations/**`, asserted to be outside
#: `app/alembic` by `tests/architecture/test_builderops_migration_boundary.py`)
#: and the dispatcher's local coordination database.
#:
#: They are exempt from the *unresolvable-expression* failure only — their
#: `DROP TABLE {table}` loops over `CKM_TABLE_NAMES` would otherwise force this
#: gate to grow a statement ignore-list. They are **not** exempt from the scan
#: itself: a statement in one of them that resolves to a durable table is still
#: reported and still has to be classified, and
#: `test_the_separate_schema_planes_hold_no_durable_statement` proves the
#: exemption is not currently hiding one.
SEPARATE_SCHEMA_PLANES = ("app/builderops", "app/dispatcher")

#: The one environment variable that turns create-on-demand on. Every
#: autocreate gate in this repository reads it, and a "gate" that does not
#: is not one.
_AUTOCREATE_FLAG = "STORE_SCHEMA_AUTOCREATE"

_TABLE_REFERENCE = r"(?:public\.)?[\"']?([A-Za-z_\x00][\w\x00]*)[\"']?"

# `UPDATE <t> SET` and `COPY <t> FROM|TO|(` are matched in their full statement
# shape on purpose. Bare `UPDATE <word>` and `copy <word>` also occur in
# English prose and in filename construction (`app/knowledge/multiwriter.py`
# builds a "(conflicted copy <writer> ...)" suffix), and a gate that fired on
# those would be repaired by an ignore-list — which is one of the three ways
# this gate silently degrades into the list gate it replaces.
_VERB_SUFFIXES: Mapping[str, str] = {
    "update": r"\s+set\b",
    "copy": r"\s*(?:\(|from\b|to\b)",
}


class UnresolvedTableExpression(AssertionError):
    """A durable SQL statement whose table name is not statically resolvable.

    Raised rather than skipped. An unattributable ``INSERT`` or ``CREATE
    TABLE`` is exactly the case a classification gate must not wave through:
    the table it targets would be absent from the population and from every
    producer entry while the gate still reported green.
    """


# --------------------------------------------------------------------------- #
# Static resolution of table-name expressions
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class SqlStatement:
    """One executed SQL string, resolved to literal text where possible."""

    path: str
    lineno: int
    text: str
    function: str | None
    autocreate_gated: bool
    existence_probed: bool
    reaches_durable_database: bool


class _ModuleResolver:
    """Resolves string-valued expressions inside one Python module.

    Handles the four binding forms this repository actually uses. Anything
    else resolves to nothing, and the caller turns that into
    :class:`UnresolvedTableExpression` when it sits inside a durable
    statement.
    """

    _MAX_ALTERNATIVES = 16

    def __init__(self, path: Path, tree: ast.Module) -> None:
        self.path = path
        self.tree = tree
        self._parent: dict[ast.AST, ast.AST] = {}
        for parent in ast.walk(tree):
            for child in ast.iter_child_nodes(parent):
                self._parent[child] = parent
        self._literal_line_cache: dict[str, int] | None = None
        self._functions: dict[str, list[ast.FunctionDef | ast.AsyncFunctionDef]] = {}
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                self._functions.setdefault(node.name, []).append(node)

    # -- scope walking ----------------------------------------------------- #

    def enclosing_function(self, node: ast.AST) -> ast.FunctionDef | ast.AsyncFunctionDef | None:
        current = self._parent.get(node)
        while current is not None:
            if isinstance(current, (ast.FunctionDef, ast.AsyncFunctionDef)):
                return current
            current = self._parent.get(current)
        return None

    def _module_bindings(self, name: str) -> list[ast.expr]:
        values: list[ast.expr] = []
        for node in self.tree.body:
            targets: list[ast.expr] = []
            if isinstance(node, ast.Assign):
                targets = list(node.targets)
            elif isinstance(node, ast.AnnAssign):
                targets = [node.target]
            for target in targets:
                if isinstance(target, ast.Name) and target.id == name and node.value is not None:
                    values.append(node.value)
        return values

    def _imported_bindings(self, name: str, depth: int) -> frozenset[str]:
        """Resolve ``from app.x.y import NAME`` against the defining module.

        `app/episodes/closure.py` reaches its table name this way
        (``from app.jobs.episodes_projection import EPISODES_TABLE``), and a
        resolver that stopped at the module boundary would report that
        producer's ``UPDATE episodes`` as unattributable.
        """
        if depth <= 0:
            return frozenset()
        values: set[str] = set()
        for node in self.tree.body:
            if not isinstance(node, ast.ImportFrom) or node.level or not node.module:
                continue
            if not node.module.startswith("app."):
                continue
            for alias in node.names:
                if (alias.asname or alias.name) != name:
                    continue
                source = REPO_ROOT / Path(*node.module.split(".")).with_suffix(".py")
                if not source.exists():
                    continue
                imported = _resolver(source)
                for bound in imported._module_bindings(alias.name):
                    values |= imported.resolve(bound, None, depth=depth - 1)
        return frozenset(values)

    def _function_bindings(
        self,
        name: str,
        func: ast.FunctionDef | ast.AsyncFunctionDef,
        _seen: frozenset[tuple[int, str]] = frozenset(),
    ) -> list[ast.expr]:
        values: list[ast.expr] = []
        for node in ast.walk(func):
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name) and target.id == name:
                        values.append(node.value)
            elif isinstance(node, ast.AnnAssign):
                if isinstance(node.target, ast.Name) and node.target.id == name and node.value:
                    values.append(node.value)
            elif isinstance(node, (ast.For, ast.AsyncFor)):
                values.extend(self._loop_bindings(name, node, func, _seen))
        return values

    def _loop_bindings(
        self,
        name: str,
        loop: ast.For | ast.AsyncFor,
        func: ast.FunctionDef | ast.AsyncFunctionDef | None,
        _seen: frozenset[tuple[int, str]] = frozenset(),
    ) -> list[ast.expr]:
        """Values ``name`` takes when it is a target of ``loop``.

        Handles the plain form (``for table in ("store_objects", ...)``) and the
        unpacking form over a table-grouped literal
        (``for table, statements in _MIGRATION_OWNED_AUTOCREATE_SQL``), which is
        how both `app/db/db.py` and `app/stores/pg.py` drive their per-table
        autocreate groups. Without the unpacking form those two seams resolve to
        nothing and drop out of the scan silently, which is exactly the failure
        this gate exists to make impossible: `app/db/db.py` is the seam MVR-05A1
        named by hand, and it would have been invisible to its derived
        successor.
        """
        target = loop.target
        wanted = (isinstance(target, ast.Name) and target.id == name) or (
            isinstance(target, ast.Tuple)
            and any(isinstance(item, ast.Name) and item.id == name for item in target.elts)
        )
        if not wanted:
            return []
        key = (id(func) if func is not None else 0, name)
        if key in _seen:
            return []
        seen = _seen | {key}
        elements = self._iterable_elements(loop.iter, func, seen)
        if elements is None:
            return []
        if isinstance(target, ast.Name):
            return list(elements)
        assert isinstance(target, ast.Tuple)
        indexes = [
            position
            for position, item in enumerate(target.elts)
            if isinstance(item, ast.Name) and item.id == name
        ]
        values: list[ast.expr] = []
        for element in elements:
            row = self._iterable_elements(element, func, seen)
            if row is None:
                continue
            for index in indexes:
                if index < len(row):
                    values.append(row[index])
        return values

    def _iterable_elements(
        self,
        node: ast.expr,
        func: ast.FunctionDef | ast.AsyncFunctionDef | None,
        _seen: frozenset[tuple[int, str]] = frozenset(),
    ) -> list[ast.expr] | None:
        """The element expressions of a literal sequence, following names."""
        if isinstance(node, (ast.Tuple, ast.List, ast.Set)):
            return list(node.elts)
        if isinstance(node, ast.Call):
            called = node.func
            name = (
                called.attr
                if isinstance(called, ast.Attribute)
                else called.id
                if isinstance(called, ast.Name)
                else ""
            )
            # Order- and type-preserving wrappers: `for table in
            # reversed(CKM_TABLE_NAMES)` iterates exactly the same names.
            if name in {"reversed", "sorted", "tuple", "list", "set", "frozenset"} and node.args:
                return self._iterable_elements(node.args[0], func, _seen)
            # `for table, columns in additions.items()` over a dict literal.
            if name == "items" and isinstance(called, ast.Attribute):
                mapping = called.value
                if isinstance(mapping, ast.Name):
                    resolved_mapping = None
                    for bound in [
                        *(self._function_bindings(mapping.id, func, _seen) if func else []),
                        *self._module_bindings(mapping.id),
                    ]:
                        if isinstance(bound, ast.Dict):
                            resolved_mapping = bound
                            break
                    mapping = resolved_mapping if resolved_mapping is not None else mapping
                if isinstance(mapping, ast.Dict):
                    pairs: list[ast.expr] = []
                    for key, value in zip(mapping.keys, mapping.values):
                        if key is None:
                            continue
                        pair = ast.Tuple(elts=[key, value], ctx=ast.Load())
                        pair.lineno = key.lineno
                        pair.col_offset = key.col_offset
                        pairs.append(pair)
                    return pairs
            return None
        if isinstance(node, ast.Name):
            key = (id(func) if func is not None else 0, node.id)
            if key in _seen:
                return None
            seen = _seen | {key}
            bindings: list[ast.expr] = []
            if func is not None:
                # `_seen`, not `seen`: this name has just been marked, and
                # `_loop_bindings` needs to look up that very name's loop
                # binding. `_loop_bindings` carries its own guard, and the
                # recursion still terminates because the loop's *iterable* is
                # resolved against the extended set.
                bindings.extend(self._function_bindings(node.id, func, _seen))
            bindings.extend(self._module_bindings(node.id))
            # The union of every binding, not the first that resolves: a name
            # bound once per iteration of an outer loop takes one value per
            # group, and returning only the first would quietly scan the first
            # table's statements and drop the other four.
            collected: list[ast.expr] | None = None
            for bound in bindings:
                elements = self._iterable_elements(bound, func, seen)
                if elements is not None:
                    collected = [*(collected or []), *elements]
            return collected
        return None

    def parameter_bindings(
        self, name: str, func: ast.FunctionDef | ast.AsyncFunctionDef
    ) -> list[tuple[ast.expr, ast.FunctionDef | ast.AsyncFunctionDef | None]] | None:
        """Values passed for parameter ``name`` at same-module call sites.

        Returns ``None`` when ``name`` is not a parameter of ``func``, and an
        empty list when it is a parameter with no resolvable call site — which
        the caller reports as unresolved rather than as "no tables".
        """
        args = func.args
        positional = [*args.posonlyargs, *args.args]
        index: int | None = None
        for position, arg in enumerate(positional):
            if arg.arg == name:
                index = position
                break
        is_keyword_only = any(arg.arg == name for arg in args.kwonlyargs)
        if index is None and not is_keyword_only:
            return None

        bindings: list[tuple[ast.expr, ast.FunctionDef | ast.AsyncFunctionDef | None]] = []
        for node in ast.walk(self.tree):
            if not isinstance(node, ast.Call):
                continue
            called = node.func
            called_name = (
                called.id
                if isinstance(called, ast.Name)
                else called.attr
                if isinstance(called, ast.Attribute)
                else None
            )
            if called_name != func.name:
                continue
            caller = self.enclosing_function(node)
            for keyword in node.keywords:
                if keyword.arg == name:
                    bindings.append((keyword.value, caller))
            if index is not None and index < len(node.args):
                bindings.append((node.args[index], caller))
        return bindings

    # -- value resolution -------------------------------------------------- #

    def resolve(
        self,
        node: ast.expr,
        func: ast.FunctionDef | ast.AsyncFunctionDef | None,
        _seen: frozenset[tuple[int, str]] = frozenset(),
        *,
        depth: int = 4,
    ) -> frozenset[str]:
        """Every literal string ``node`` can evaluate to, or an empty set."""
        if isinstance(node, ast.Constant):
            return frozenset({node.value}) if isinstance(node.value, str) else frozenset()

        if isinstance(node, ast.JoinedStr):
            parts: list[frozenset[str]] = []
            for value in node.values:
                if isinstance(value, ast.Constant) and isinstance(value.value, str):
                    parts.append(frozenset({value.value}))
                elif isinstance(value, ast.FormattedValue):
                    resolved = self.resolve(value.value, func, _seen, depth=depth)
                    parts.append(resolved or frozenset({_UNRESOLVED}))
                else:  # pragma: no cover - defensive
                    parts.append(frozenset({_UNRESOLVED}))
            combined = {""}
            for part in parts:
                if len(combined) * len(part) > self._MAX_ALTERNATIVES:
                    return frozenset({_UNRESOLVED})
                combined = {prefix + suffix for prefix in combined for suffix in part}
            return frozenset(combined)

        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
            # An unresolvable operand becomes the marker rather than collapsing
            # the whole expression to nothing: `"CREATE TABLE " + name + " (...)"`
            # must still be recognised as CREATE TABLE, with an unresolvable
            # table name that raises, instead of vanishing from discovery.
            left = self.resolve(node.left, func, _seen, depth=depth) or frozenset({_UNRESOLVED})
            right = self.resolve(node.right, func, _seen, depth=depth) or frozenset({_UNRESOLVED})
            if len(left) * len(right) > self._MAX_ALTERNATIVES:
                return frozenset({_UNRESOLVED})
            return frozenset(a + b for a in left for b in right)

        if isinstance(node, ast.Call):
            return self._resolve_composed_sql(node, func, _seen, depth)

        if isinstance(node, ast.Name):
            key = (id(func) if func is not None else 0, node.id)
            if key in _seen:
                return frozenset()
            seen = _seen | {key}
            values: set[str] = set()
            if func is not None:
                for bound in self._function_bindings(node.id, func):
                    values |= self.resolve(bound, func, seen, depth=depth)
                parameter = self.parameter_bindings(node.id, func)
                if parameter is not None:
                    for bound, caller in parameter:
                        values |= self.resolve(bound, caller, seen, depth=depth)
            for bound in self._module_bindings(node.id):
                values |= self.resolve(bound, None, seen, depth=depth)
            values |= self._imported_bindings(node.id, depth)
            return frozenset(values)

        return frozenset()

    def _resolve_composed_sql(
        self,
        node: ast.Call,
        func: ast.FunctionDef | ast.AsyncFunctionDef | None,
        _seen: frozenset[tuple[int, str]],
        depth: int,
    ) -> frozenset[str]:
        """Resolve the composable-SQL idiom to its literal template.

        `psycopg.sql.SQL("SELECT ... FROM {table}").format(table=Identifier(t))`
        and SQLAlchemy's `text("...")` are the two ways this repository builds a
        statement out of something other than a plain string. Without this, the
        whole statement resolves to nothing and is dropped from the scan in
        silence — and "silently dropped" is precisely the outcome this gate
        must not have. Every such site is a `SELECT` today; the point is that a
        `DELETE FROM {table}` written this way tomorrow resolves to
        `DELETE FROM <unresolved>` and raises, instead of disappearing.
        """
        called = node.func
        name = (
            called.attr
            if isinstance(called, ast.Attribute)
            else called.id
            if isinstance(called, ast.Name)
            else ""
        )

        if name in {"SQL", "text"} and node.args:
            return self.resolve(node.args[0], func, _seen, depth=depth)

        if name == "replace" and isinstance(called, ast.Attribute) and len(node.args) >= 2:
            # `"""... __PLACEHOLDER__ ...""".replace("__PLACEHOLDER__", rows())`
            # is how `7e4f2a1c9d30` renders its reviewed consumer allowlist into a
            # DO block. Without this the whole revision resolves to nothing.
            templates = self.resolve(called.value, func, _seen, depth=depth)
            needles = self.resolve(node.args[0], func, _seen, depth=depth)
            values = self.resolve(node.args[1], func, _seen, depth=depth) or frozenset(
                {_UNRESOLVED}
            )
            if not templates or len(needles) != 1 or len(values) != 1:
                return templates
            needle = next(iter(needles))
            value = next(iter(values))
            return frozenset(template.replace(needle, value) for template in templates)

        if name == "format" and isinstance(called, ast.Attribute):
            templates = self.resolve(called.value, func, _seen, depth=depth)
            if not templates:
                return frozenset()
            replacements: dict[str, str] = {}
            for position, argument in enumerate(node.args):
                replacements[str(position)] = self._identifier_text(argument, func, _seen, depth)
            for keyword in node.keywords:
                if keyword.arg:
                    replacements[keyword.arg] = self._identifier_text(
                        keyword.value, func, _seen, depth
                    )
            rendered: set[str] = set()
            for template in templates:
                rendered.add(
                    re.sub(
                        r"\{([A-Za-z_][\w]*|\d*)\}",
                        lambda match: replacements.get(match.group(1) or "0", _UNRESOLVED),
                        template,
                    )
                )
            return frozenset(rendered)

        return frozenset()

    def _identifier_text(
        self,
        node: ast.expr,
        func: ast.FunctionDef | ast.AsyncFunctionDef | None,
        _seen: frozenset[tuple[int, str]],
        depth: int,
    ) -> str:
        """`sql.Identifier(x)` / a literal, rendered as a table name or marker."""
        target = node
        if isinstance(node, ast.Call):
            called = node.func
            name = (
                called.attr
                if isinstance(called, ast.Attribute)
                else called.id
                if isinstance(called, ast.Name)
                else ""
            )
            if name in {"Identifier", "SQL", "Literal"} and node.args:
                target = node.args[0]
        values = self.resolve(target, func, _seen, depth=depth)
        return next(iter(values)) if len(values) == 1 else _UNRESOLVED

    # -- executed SQL ------------------------------------------------------ #

    def sql_statements(self) -> Iterator[SqlStatement]:
        """Every SQL string handed to a statement-executing call.

        Scoped to executed strings so that a docstring quoting DDL, or a
        constant that nothing runs, is not mistaken for a live seam.

        A statement passed *through* a thin executor helper is attributed to
        the call site that supplied it, not to the helper. Both
        `app/services/outbox.py` and `app/heimdal/entity_review_operation_journal.py`
        route their DDL through a two-line ``_exec(conn, sql)``, and that helper
        also carries every ordinary ``INSERT``. Attributing to the helper would
        report the outbox bootstrap DDL as ungated while the branch that
        actually issues it is behind ``STORE_SCHEMA_AUTOCREATE``.
        """
        relative = self.path.relative_to(REPO_ROOT).as_posix()
        literal_lines = self._literal_linenos()
        for node in ast.walk(self.tree):
            if not isinstance(node, ast.Call):
                continue
            called = node.func
            name = (
                called.attr
                if isinstance(called, ast.Attribute)
                else called.id
                if isinstance(called, ast.Name)
                else ""
            )
            if name not in {"execute", "executemany", "_exec", "execute_values"}:
                continue
            func = self.enclosing_function(node)
            for argument in [*node.args, *(keyword.value for keyword in node.keywords)]:
                origins: list[tuple[ast.expr, ast.FunctionDef | ast.AsyncFunctionDef | None]]
                if isinstance(argument, ast.Name) and func is not None:
                    passed_in = self.parameter_bindings(argument.id, func)
                    origins = list(passed_in) if passed_in else [(argument, func)]
                else:
                    origins = [(argument, func)]
                for expression, origin in origins:
                    for text in self.resolve(expression, origin):
                        if not isinstance(text, str) or len(text) < 6:
                            continue
                        yield SqlStatement(
                            path=relative,
                            # The literal's own line when the statement reached
                            # this call through a name — otherwise every seam in
                            # a `for statement in statements:` loop reports the
                            # loop line, and a failure message points at the
                            # loop rather than at the offending DDL.
                            lineno=literal_lines.get(text, expression.lineno),
                            text=text,
                            function=origin.name if origin is not None else None,
                            autocreate_gated=self.autocreate_gated(expression, origin),
                            existence_probed=self.existence_probed(expression, origin),
                            reaches_durable_database=_reaches_durable_database(
                                relative, self, origin
                            ),
                        )

    def _literal_linenos(self) -> Mapping[str, int]:
        """First line of each distinct string literal in this module."""
        if self._literal_line_cache is None:
            lines: dict[str, int] = {}
            for node in ast.walk(self.tree):
                if isinstance(node, ast.Constant) and isinstance(node.value, str):
                    lines.setdefault(node.value, node.lineno)
            self._literal_line_cache = lines
        return self._literal_line_cache

    def autocreate_gated(
        self, node: ast.AST, func: ast.FunctionDef | ast.AsyncFunctionDef | None
    ) -> bool:
        """True when ``node`` only executes under the test-fixture opt-in.

        Two shapes, both of which this repository uses, and both of which are
        checked structurally — the mere presence of the word ``autocreate``
        somewhere in the file proves nothing about the branch the statement
        actually sits in:

            if not _schema_autocreate_enabled():   # early exit
                _assert_pg_schema(conn)
                return
            ...                                    # node is here

            if _schema_autocreate_enabled():       # positive branch
                ...                                # node is here
            else:
                _assert_pg_schema(conn)
        """
        if func is None:
            return False
        for candidate in ast.walk(func):
            if not isinstance(candidate, ast.If):
                continue
            test = candidate.test
            negated = isinstance(test, ast.UnaryOp) and isinstance(test.op, ast.Not)
            call = test.operand if negated else test
            if not isinstance(call, ast.Call):
                continue
            called = call.func
            called_name = (
                called.id
                if isinstance(called, ast.Name)
                else called.attr
                if isinstance(called, ast.Attribute)
                else ""
            )
            if not self._reads_the_autocreate_flag(called_name):
                continue
            in_body = any(self._contains(branch, node) for branch in candidate.body)
            if negated:
                # The guarded branch must terminate, not merely contain a
                # `return` somewhere inside a further conditional — otherwise
                # it falls through and the statements after it run in
                # production too.
                if not isinstance(candidate.body[-1], (ast.Return, ast.Raise)):
                    continue
                if not in_body and node.lineno > candidate.lineno:
                    return True
            elif in_body:
                return True
        return False

    def _reads_the_autocreate_flag(self, called_name: str) -> bool:
        """True when ``called_name`` is a predicate that reads the fixture flag.

        Structural in both directions. Matching the callee's *name* lets
        `_vector_autocreate_probe()` returning `True` mark production DDL as
        gated; matching the flag as a *substring* of the function's dump or of
        the defining module's source lets a docstring or a comment do the same.
        So the flag must appear as an argument of an environment read —
        ``os.getenv(...)``, ``os.environ.get(...)`` or ``os.environ[...]`` —
        inside the named function, with its docstring excluded. All twenty
        production predicates in this repository are exactly that one-liner.
        """
        if "autocreate" not in called_name.lower():
            return False
        for function in self._functions.get(called_name, []):
            if _reads_environment_flag(function):
                return True
        for node in self.tree.body:
            if not isinstance(node, ast.ImportFrom) or node.level or not node.module:
                continue
            if not node.module.startswith("app."):
                continue
            if not any((alias.asname or alias.name) == called_name for alias in node.names):
                continue
            source = REPO_ROOT / Path(*node.module.split(".")).with_suffix(".py")
            if not source.exists():
                continue
            for function in _resolver(source)._functions.get(called_name, []):
                if _reads_environment_flag(function):
                    return True
        return False

    def existence_probed(
        self, node: ast.AST, func: ast.FunctionDef | ast.AsyncFunctionDef | None
    ) -> bool:
        """True when *this statement* is skipped if its table already exists.

        A **per-statement** property, deliberately. Asking only whether the
        enclosing function mentions ``to_regclass`` somewhere and contains some
        early return is a different question, and `app/stores/pg.py` answers
        that one "yes" for free: `if _TABLES_READY: return` supplies the branch
        and the probe sits in a loop the statement need not be in. Under that
        weaker check, moving the three `ALTER TABLE store_vector_index`
        statements back out of the group and issuing them unconditionally — the
        exact defect this slice closed — left the gate green.

        The real mechanism is a loop that probes ``to_regclass`` per table and
        ``continue``s past the whole group when it resolves, which is what
        `app/db/db.py::_run_migration_sql` established. So: the statement must
        sit inside such a loop.
        """
        if func is None:
            return False
        for loop in self._enclosing_loops(node, func):
            if self._loop_skips_existing_tables(loop, node):
                return True
        return False

    def _enclosing_loops(
        self, node: ast.AST, func: ast.FunctionDef | ast.AsyncFunctionDef
    ) -> list[ast.For | ast.AsyncFor]:
        loops: list[ast.For | ast.AsyncFor] = []
        current: ast.AST | None = self._parent.get(node)
        while current is not None and current is not func:
            if isinstance(current, (ast.For, ast.AsyncFor)):
                loops.append(current)
            current = self._parent.get(current)
        return loops

    def _loop_skips_existing_tables(self, loop: ast.For | ast.AsyncFor, node: ast.AST) -> bool:
        """True when ``node`` runs only for a table the loop found absent.

        Positional and causal, because "somewhere in this loop there is a
        `to_regclass` and somewhere there is a `continue`" is satisfied by
        arrangements that reshape an existing table on every boot:

        * the statement placed *before* the `if present: continue` guard;
        * a probe whose result is discarded plus a `continue` on an unrelated
          condition (`if table == "never_matches": continue`).

        Both were green under the previous check. So all three facts are pinned
        to the loop's own statement list, in order:

        1. a probe executing `to_regclass` at some index `p`;
        2. a guard `if <name>: ... continue` at index `g > p`, whose test is a
           plain name — a comparison asks a different question than "did the
           probe find it";
        3. ``node`` under a statement at index `s > g`.

        Both real seams — `app/stores/pg.py::_ensure_tables` and
        `app/db/db.py::_run_migration_sql` — are exactly this shape.
        """
        body = list(loop.body)
        probe_at: int | None = None
        guard_at: int | None = None
        assigned_after_probe: set[str] = set()
        for index, statement in enumerate(body):
            if probe_at is None and self._executes_existence_probe(statement):
                probe_at = index
                continue
            if probe_at is None:
                continue
            if guard_at is None and self._is_skip_guard(statement, assigned_after_probe):
                guard_at = index
            for assignment in ast.walk(statement):
                # Not `node`: that is this method's parameter, and rebinding it
                # here silently changed which statement the containment check
                # below was asking about.
                if isinstance(assignment, ast.Assign):
                    assigned_after_probe.update(
                        target.id for target in assignment.targets if isinstance(target, ast.Name)
                    )
        if probe_at is None or guard_at is None:
            return False
        return any(
            index > guard_at and self._contains(statement, node)
            for index, statement in enumerate(body)
        )

    def _executes_existence_probe(self, statement: ast.stmt) -> bool:
        for inner in ast.walk(statement):
            if not isinstance(inner, ast.Call):
                continue
            called = inner.func
            name = (
                called.attr
                if isinstance(called, ast.Attribute)
                else called.id
                if isinstance(called, ast.Name)
                else ""
            )
            if name not in {"execute", "executemany", "_exec", "execute_values"}:
                continue
            enclosing = self.enclosing_function(inner)
            for argument in inner.args:
                if any(
                    isinstance(text, str) and "to_regclass" in text.lower()
                    for text in self.resolve(argument, enclosing)
                ):
                    return True
        return False

    @staticmethod
    def _is_skip_guard(statement: ast.stmt, assigned_after_probe: set[str]) -> bool:
        """`if <name>: continue`, where ``name`` came from the probe.

        The name has to be one the loop assigned *after* the probe ran.
        Otherwise `if _NEVER_SKIP: continue` over a module constant that is
        always false reads as a skip guard while every statement below it runs
        on every boot.
        """
        if not isinstance(statement, ast.If):
            return False
        if not isinstance(statement.test, ast.Name):
            return False
        if statement.test.id not in assigned_after_probe:
            return False
        return bool(statement.body) and isinstance(statement.body[-1], ast.Continue)

    def _contains(self, ancestor: ast.AST, node: ast.AST) -> bool:
        current: ast.AST | None = node
        while current is not None:
            if current is ancestor:
                return True
            current = self._parent.get(current)
        return False


def _reads_environment_flag(function: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    """True when ``function`` reads ``STORE_SCHEMA_AUTOCREATE`` from the env."""
    body = list(function.body)
    if (
        body
        and isinstance(body[0], ast.Expr)
        and isinstance(body[0].value, ast.Constant)
        and isinstance(body[0].value.value, str)
    ):
        body = body[1:]  # the docstring is prose, not a read
    for statement in body:
        for node in ast.walk(statement):
            if isinstance(node, ast.Call):
                called = node.func
                name = called.attr if isinstance(called, ast.Attribute) else ""
                if name in {"getenv", "get"} and any(
                    isinstance(argument, ast.Constant) and argument.value == _AUTOCREATE_FLAG
                    for argument in node.args
                ):
                    return True
            elif isinstance(node, ast.Subscript):
                index = node.slice
                if isinstance(index, ast.Constant) and index.value == _AUTOCREATE_FLAG:
                    return True
    return False


@lru_cache(maxsize=None)
def _resolver(path: Path) -> _ModuleResolver:
    return _ModuleResolver(path, ast.parse(path.read_text(encoding="utf-8")))


def _statement_matches(
    text: str, patterns: Sequence[tuple[str, str]]
) -> Iterator[tuple[str, str, int]]:
    """Every (verb, table, offset) the patterns match in ``text``."""
    for verb, prefix in patterns:
        suffix = _VERB_SUFFIXES.get(verb, "")
        pattern = re.compile(rf"(?is)\b{prefix}{_TABLE_REFERENCE}{suffix}")
        for match in pattern.finditer(text):
            yield verb, match.group(1), match.start()


# --------------------------------------------------------------------------- #
# 1. The durable-table population, derived from the revision chain
# --------------------------------------------------------------------------- #


def discover_durable_tables(
    versions_dir: Path | None = None,
) -> dict[str, frozenset[str]]:
    """Every table the Alembic revision chain creates, mapped to its owners.

    ``downgrade()`` is excluded: a table this chain drops on the way *down* is
    still durable on the way up, and the drops live only there.

    Raises :class:`UnresolvedTableExpression` if a revision creates a table
    under a name that cannot be resolved statically. That is deliberate — a
    revision the gate cannot read is a revision whose table nobody classified.
    """
    directory = versions_dir if versions_dir is not None else ALEMBIC_VERSIONS
    owners: dict[str, set[str]] = {}
    for path in sorted(directory.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        resolver = _ModuleResolver(path, tree)
        for node in ast.walk(tree):
            if _inside_downgrade(resolver, node):
                continue
            for table in _created_tables(resolver, node, path):
                owners.setdefault(table, set()).add(path.name)
    return {table: frozenset(names) for table, names in owners.items()}


def _inside_downgrade(resolver: _ModuleResolver, node: ast.AST) -> bool:
    function = resolver.enclosing_function(node)
    while function is not None:
        if function.name == "downgrade":
            return True
        function = resolver.enclosing_function(function)
    return False


def _created_tables(resolver: _ModuleResolver, node: ast.AST, path: Path) -> Iterator[str]:
    if not isinstance(node, ast.Call):
        return
    called = node.func
    name = (
        called.attr
        if isinstance(called, ast.Attribute)
        else called.id
        if isinstance(called, ast.Name)
        else ""
    )
    func = resolver.enclosing_function(node)

    # `op.create_table("standing_questions", ...)` — the Alembic operation API.
    # The name may also arrive as a keyword: `op.create_table(table_name=...)`
    # with no positional argument at all would otherwise fall through to the
    # `execute` branch and return silently.
    if name == "create_table":
        candidates = [
            *node.args[:1],
            *(keyword.value for keyword in node.keywords if keyword.arg == "table_name"),
        ]
        argument = candidates[0] if candidates else None
        if argument is None:
            raise UnresolvedTableExpression(
                f"{path.name}:{node.lineno} calls create_table() with no table name this gate "
                "can find, so the table it creates would never enter the classified population."
            )
        # The keyword wins when the first positional is a column rather than a
        # name, which is the shape `op.create_table(sa.Column(...), table_name=...)`
        # takes.
        resolved: frozenset[str] = frozenset()
        for candidate in candidates:
            resolved = resolver.resolve(candidate, func)
            if resolved:
                break
        if not resolved:
            raise UnresolvedTableExpression(
                f"{path.name}:{node.lineno} calls create_table() with a table name this "
                "gate cannot resolve statically, so the table it creates would never "
                "enter the classified population."
            )
        for value in resolved:
            yield _normalize(value, path, node.lineno)
        return

    # Raw `CREATE TABLE` through `op.execute(...)` / `cur.execute(...)`.
    if name not in {"execute", "executemany", "_exec", "execute_values"}:
        return
    if not node.args and not node.keywords:
        return
    statement_resolved = False
    for argument in [*node.args, *(keyword.value for keyword in node.keywords)]:
        resolved = resolver.resolve(argument, func)
        for text in resolved:
            if not isinstance(text, str) or len(text) < 6:
                continue
            statement_resolved = True
            for _, table, _offset in _statement_matches(text, _DDL_VERB_PATTERNS[:1]):
                yield _normalize(table, path, node.lineno)
    if not statement_resolved:
        # No argument reduced to a statement at all. Inspecting the raw source
        # segment is not a substitute: for `sql = "CREATE TABLE " + name + ...;
        # op.execute(sql)` the segment is the single word `sql`, so a
        # segment-level check would let the revision — and the durable table it
        # creates — disappear from the population while the gate stayed green.
        # Every `op.execute` in the chain resolves today; a new one that does
        # not is a revision this gate cannot read, which is exactly a table
        # nobody has classified.
        raise UnresolvedTableExpression(
            f"{path.name}:{node.lineno} executes a statement this gate cannot resolve to "
            "literal SQL, so any table it creates would never enter the classified "
            "population. Bind the statement to a module constant, or widen the resolver."
        )


def _normalize(value: str, path: Path, lineno: int) -> str:
    table = value.strip().strip('"').removeprefix("public.")
    if _UNRESOLVED in table or not re.fullmatch(r"[a-z_][a-z0-9_]*", table):
        raise UnresolvedTableExpression(
            f"{path.name}:{lineno} creates a table whose name resolved to {value!r}, "
            "which is not a literal identifier."
        )
    return table


# --------------------------------------------------------------------------- #
# 2. Durable mutation paths under app/**
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class MutationPath:
    table: str
    module: str
    verb: str


def _in_separate_schema_plane(relative_path: str) -> bool:
    return any(relative_path.startswith(f"{plane}/") for plane in SEPARATE_SCHEMA_PLANES)


def _app_modules() -> Iterator[Path]:
    for path in sorted(APP_ROOT.rglob("*.py")):
        if ALEMBIC_VERSIONS in path.parents:
            continue
        yield path


def discover_durable_mutation_paths(tables: Iterable[str]) -> frozenset[MutationPath]:
    """Every mutation under ``app/**`` targeting a discovered durable table."""
    return _discover_durable_mutation_paths(frozenset(tables))


@lru_cache(maxsize=None)
def _discover_durable_mutation_paths(tables: frozenset[str]) -> frozenset[MutationPath]:
    known = set(tables)
    found: set[MutationPath] = set()
    for path in _app_modules():
        resolver = _resolver(path)
        for statement in resolver.sql_statements():
            for verb, table, _ in _statement_matches(statement.text, _MUTATION_VERB_PATTERNS):
                normalized = table.strip()
                if _UNRESOLVED in normalized:
                    # Only the *unresolvable* case is exempt outside the durable
                    # seam. A statement that resolves to a durable table is
                    # reported wherever it lives — pre-filtering the whole scan
                    # by reachability made the separate-plane bounding test
                    # vacuous, because the set it inspects could never contain a
                    # plane module.
                    if not statement.reaches_durable_database:
                        continue
                    raise UnresolvedTableExpression(
                        f"{statement.path}:{statement.lineno} issues {verb.upper()} against a "
                        "table name this gate cannot resolve statically, so the mutation "
                        "cannot be attributed to a classified producer."
                    )
                if normalized in known:
                    found.add(MutationPath(normalized, statement.path, verb))
    return frozenset(found)


# --------------------------------------------------------------------------- #
# 3. Durable DDL seams outside the revision chain
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class DdlSeam:
    table: str
    path: str
    lineno: int
    verb: str
    function: str | None
    autocreate_gated: bool
    existence_probed: bool
    #: The statement is issued from a file that can reach the durable
    #: PostgreSQL database, rather than from a SQLite-only local store or a
    #: separately-migrated schema plane.
    durable_database_source: bool
    #: The table it targets is created by the Alembic revision chain.
    owned_by_revision_chain: bool


def _executed_on_sqlite(
    resolver: "_ModuleResolver", func: ast.FunctionDef | ast.AsyncFunctionDef | None
) -> bool:
    """True when the enclosing function opens a SQLite connection itself.

    A **per-statement** question, not a per-module one. A module-level
    "imports sqlite3 and not psycopg" rule turns the whole gate off for a file
    with one extra import line — and `app/panel/confirmation.py` really does
    import both `sqlite3` and `app.services.outbox`, while
    `app/heimdal/meeting_ledger.py` carries a SQLite store and a PostgreSQL
    store side by side with byte-identical table names. Reading the connection
    the statement is actually executed on separates them; reading imports
    cannot.
    """
    if func is None:
        return False
    if _opens_sqlite(func):
        return True
    # One hop, because the connection is usually a helper:
    # `app/panel/confirmation.py::_initialize` runs its DDL through
    # `self._connect()`, which is annotated `-> sqlite3.Connection`.
    for node in ast.walk(func):
        if not isinstance(node, ast.Call):
            continue
        called = node.func
        name = (
            called.attr
            if isinstance(called, ast.Attribute)
            else called.id
            if isinstance(called, ast.Name)
            else ""
        )
        for candidate in resolver._functions.get(name, []):
            if _opens_sqlite(candidate) or _returns_sqlite_connection(candidate):
                return True
    return False


def _opens_sqlite(func: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    for node in ast.walk(func):
        if not isinstance(node, ast.Call):
            continue
        called = node.func
        if (
            isinstance(called, ast.Attribute)
            and called.attr == "connect"
            and isinstance(called.value, ast.Name)
            and called.value.id == "sqlite3"
        ):
            return True
    return False


def _returns_sqlite_connection(func: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    annotation = func.returns
    return (
        isinstance(annotation, ast.Attribute)
        and annotation.attr == "Connection"
        and isinstance(annotation.value, ast.Name)
        and annotation.value.id == "sqlite3"
    )


def _reaches_durable_database(
    relative_path: str,
    resolver: "_ModuleResolver | None" = None,
    func: ast.FunctionDef | ast.AsyncFunctionDef | None = None,
) -> bool:
    """Whether a statement can reach the durable PostgreSQL database."""
    if _in_separate_schema_plane(relative_path):
        return False
    if resolver is None:
        return True
    return not _executed_on_sqlite(resolver, func)


def discover_runtime_ddl_seams(tables: Iterable[str]) -> tuple[DdlSeam, ...]:
    """Every durable DDL statement outside ``app/alembic/versions/**``.

    Covers the Python seams (`app/db/db.py`, `app/stores/pg.py`, the Heimdal
    bootstrap modules, the outbox, the knowledge-acquisition stores) and any
    ``.sql`` file under ``app/``. A ``.sql`` file has no enclosing function and
    so can never be gated — which is exactly the finding that retired
    ``app/db/sql/relations_init.sql``.
    """
    known = set(tables)
    seams: list[DdlSeam] = []
    for path in _app_modules():
        resolver = _resolver(path)
        relative = path.relative_to(REPO_ROOT).as_posix()
        for statement in resolver.sql_statements():
            durable_source = statement.reaches_durable_database
            for verb, table, _ in _statement_matches(
                statement.text, _DDL_VERB_PATTERNS + _ATTACHED_DDL_VERB_PATTERNS
            ):
                normalized = table.strip()
                if _UNRESOLVED in normalized:
                    if not durable_source:
                        continue
                    raise UnresolvedTableExpression(
                        f"{statement.path}:{statement.lineno} issues {verb.upper()} against a "
                        "table name this gate cannot resolve statically."
                    )
                seams.append(
                    DdlSeam(
                        table=normalized,
                        path=statement.path,
                        lineno=statement.lineno,
                        verb=verb,
                        function=statement.function,
                        autocreate_gated=statement.autocreate_gated,
                        existence_probed=statement.existence_probed,
                        durable_database_source=durable_source,
                        owned_by_revision_chain=normalized in known,
                    )
                )
    for path in sorted(APP_ROOT.rglob("*.sql")):
        text = path.read_text(encoding="utf-8")
        relative = path.relative_to(REPO_ROOT).as_posix()
        durable_source = _reaches_durable_database(relative)
        for verb, table, offset in _statement_matches(
            text, _DDL_VERB_PATTERNS + _ATTACHED_DDL_VERB_PATTERNS
        ):
            normalized = table.strip()
            seams.append(
                DdlSeam(
                    table=normalized,
                    path=relative,
                    lineno=text[: text.lower().index(verb)].count("\n") + 1,
                    verb=verb,
                    function=None,
                    autocreate_gated=False,
                    existence_probed=False,
                    durable_database_source=durable_source,
                    owned_by_revision_chain=normalized in known,
                )
            )
    return tuple(seams)


# --------------------------------------------------------------------------- #
# 4. The manifest and the derived cutover worklist
# --------------------------------------------------------------------------- #


def load_manifest(path: Path | None = None) -> dict[str, dict]:
    """The checked-in classification manifest, keyed by table name.

    There is no ``.get(table, <default>)`` anywhere in this module and no
    wildcard key: a table absent from this mapping is unclassified, and the
    gate fails on it.
    """
    source = path if path is not None else MANIFEST_PATH
    document = json.loads(source.read_text(encoding="utf-8"))
    return dict(document["tables"])


@dataclass(frozen=True)
class WorklistRow:
    """One pending binding-scoped table, as the later slices consume it."""

    table: str
    owning_revision: str
    producers: tuple[str, ...]
    write_producers: tuple[str, ...]
    rebuild_mechanism: str
    escalation_conditions: tuple[str, ...]
    parity_pins: tuple[str, ...]

    @property
    def escalates(self) -> bool:
        return bool(self.escalation_conditions)


def cutover_worklist(manifest: Mapping[str, dict] | None = None) -> tuple[WorklistRow, ...]:
    """The derived worklist MVR-05A3/05A4/05A5 select their membership from.

    Pure function of the manifest: the rows classified ``binding-scoped``
    whose binding column is still absent. Nothing is stored separately, so the
    worklist cannot drift from the classification it is derived from — flip a
    table's ``binding_key`` to ``keyed`` and it leaves the worklist in the same
    commit.
    """
    entries = manifest if manifest is not None else load_manifest()
    rows: list[WorklistRow] = []
    for table in sorted(entries):
        entry = entries[table]
        if entry["classification"] != "binding-scoped" or entry["binding_key"] != "pending":
            continue
        producers = tuple(producer["module"] for producer in entry["producers"])
        writers = tuple(
            producer["module"]
            for producer in entry["producers"]
            if {"insert", "update"} & set(producer["operations"])
        )
        rows.append(
            WorklistRow(
                table=table,
                owning_revision=entry["owning_revision"],
                producers=producers,
                write_producers=writers,
                rebuild_mechanism=entry["rebuild_mechanism"],
                escalation_conditions=tuple(entry["escalation_conditions"]),
                parity_pins=parity_pins(table),
            )
        )
    return tuple(rows)


@lru_cache(maxsize=None)
def _parity_sources() -> tuple[tuple[str, str], ...]:
    return tuple(
        (path.relative_to(REPO_ROOT).as_posix(), path.read_text(encoding="utf-8"))
        for path in sorted((TESTS_ROOT / "migrations").rglob("*parity*.py"))
    )


def parity_pins(table: str) -> tuple[str, ...]:
    """Schema-parity tests that name ``table``.

    Derived so that "nine of the fifteen need a parity proof written from
    scratch" stays a measurement rather than a sentence in a document. It is
    reported on the worklist and deliberately is **not** an escalation
    condition.

    Matched as a quoted literal or a SQL statement target, never as a bare
    word: `sets`, `objects`, `relations` and `decisions` are all ordinary
    English, and a prose match would report a parity pin that does not exist.
    """
    escaped = re.escape(table)
    pattern = re.compile(
        rf"(?is)(?:[\"']{escaped}[\"']"
        rf"|\b(?:from|into|table|update|join)\s+(?:public\.)?{escaped}\b)"
    )
    return tuple(name for name, text in _parity_sources() if pattern.search(text))


# --------------------------------------------------------------------------- #
# 5. The gate's set differences
# --------------------------------------------------------------------------- #


def unclassified_tables(
    discovered: Mapping[str, frozenset[str]], manifest: Mapping[str, dict]
) -> frozenset[str]:
    """``discovered_durable_tables - classified_tables``.

    This one expression is the whole contract. It is a set *difference*, not a
    containment check against an expected list: a revision that does not exist
    yet contributes its table to ``discovered`` the moment it is written, and
    the difference is non-empty until a human adds a classification and a
    reason. Clearing today's entries does not make it permanently empty.
    """
    return frozenset(set(discovered) - set(manifest))


def stale_classifications(
    discovered: Mapping[str, frozenset[str]], manifest: Mapping[str, dict]
) -> frozenset[str]:
    """``classified_tables - discovered_durable_tables``.

    The other direction, so a table removed from the revision chain cannot
    leave a classification behind that quietly keeps the population looking
    covered.
    """
    return frozenset(set(manifest) - set(discovered))


def unclassified_mutation_paths(
    manifest: Mapping[str, dict], tables: Iterable[str]
) -> frozenset[MutationPath]:
    """Durable mutations that resolve to no classified producer entry."""
    declared = {
        MutationPath(table, producer["module"], operation)
        for table, entry in manifest.items()
        for producer in entry["producers"]
        for operation in producer["operations"]
    }
    return frozenset(discover_durable_mutation_paths(tables) - declared)


def stale_producer_entries(
    manifest: Mapping[str, dict], tables: Iterable[str]
) -> frozenset[MutationPath]:
    """Declared producer entries no statement under ``app/**`` supports."""
    found = discover_durable_mutation_paths(tables)
    declared = {
        MutationPath(table, producer["module"], operation)
        for table, entry in manifest.items()
        for producer in entry["producers"]
        for operation in producer["operations"]
    }
    return frozenset(declared - found)


@lru_cache(maxsize=None)
def foreign_key_target_candidates() -> frozenset[str]:
    """Tables named in a ``REFERENCES`` clause anywhere in the revision chain.

    A candidate set, not the effective one: `7e4f2a1c9d30` retargeted every
    live `objects` consumer onto `store_objects`, so membership here means "the
    chain has at some point pointed a foreign key at this table", which is
    exactly the bound needed to reject an `inbound-fk-target` claim for a table
    nothing has ever referenced. Deciding the *effective* consumer set is the
    re-derivation work the condition exists to route.
    """
    # The trailing `(` is load-bearing: `REFERENCES <table>(<column>)` is the
    # SQL shape, and without it the prose "references anywhere in the chain"
    # in a revision docstring registers a table named `anywhere`.
    pattern = re.compile(r"(?is)\breferences\s+(?:public\.)?[\"']?([a-z_][a-z0-9_]*)[\"']?\s*\(")
    targets: set[str] = set()
    for path in sorted(ALEMBIC_VERSIONS.glob("*.py")):
        targets.update(pattern.findall(path.read_text(encoding="utf-8")))
    return frozenset(targets)


def unresolvable_statement_sites() -> tuple[str, ...]:
    """Invisible SQL calls in files that can reach the durable database."""
    return _statement_sites(durable_source=True)


def exempted_statement_sites() -> tuple[str, ...]:
    """Invisible SQL calls the separate-schema-plane exemption hides.

    The exemption's measured cost, reported rather than assumed. A statement
    listed here is one this gate cannot read at all; the bounding test asserts
    the set of *files* it covers does not grow silently, and separately that
    nothing in those subtrees touches an Alembic-owned table.
    """
    return _statement_sites(durable_source=False)


@lru_cache(maxsize=None)
def _statement_sites(*, durable_source: bool) -> tuple[str, ...]:
    """Executed SQL calls under ``app/**`` whose statement resolves to nothing.

    The scans above raise when a *matched* durable statement carries an
    unresolvable table name. This closes the other half: a call whose SQL
    argument resolves to no literal at all never produces a statement to match,
    so it would be dropped in silence rather than loudly. Keeping this at zero
    is what makes "an unattributable durable statement stops the build" true
    rather than aspirational.
    """
    sites: list[str] = []
    for path in _app_modules():
        relative = path.relative_to(REPO_ROOT).as_posix()
        resolver = _resolver(path)
        source = path.read_text(encoding="utf-8")
        for node in ast.walk(resolver.tree):
            if not isinstance(node, ast.Call):
                continue
            called = node.func
            name = (
                called.attr
                if isinstance(called, ast.Attribute)
                else called.id
                if isinstance(called, ast.Name)
                else ""
            )
            if name not in {"execute", "executemany", "_exec", "execute_values"}:
                continue
            func = resolver.enclosing_function(node)
            if _reaches_durable_database(relative, resolver, func) is not durable_source:
                continue
            resolved = False
            for argument in [*node.args, *(keyword.value for keyword in node.keywords)]:
                origins: list[tuple[ast.expr, ast.FunctionDef | ast.AsyncFunctionDef | None]]
                if isinstance(argument, ast.Name) and func is not None:
                    passed_in = resolver.parameter_bindings(argument.id, func)
                    origins = list(passed_in) if passed_in else [(argument, func)]
                else:
                    origins = [(argument, func)]
                for expression, origin in origins:
                    if any(
                        isinstance(text, str) and len(text) >= 6
                        for text in resolver.resolve(expression, origin)
                    ):
                        resolved = True
            if not resolved:
                rendered = (
                    ", ".join(
                        (ast.get_source_segment(source, argument) or "?")
                        .strip()
                        .replace("\n", " ")[:60]
                        for argument in node.args
                    )
                    or "<no arguments>"
                )
                sites.append(f"{relative}:{node.lineno} {name}({rendered})")
    return tuple(sites)


# --------------------------------------------------------------------------- #
# 6. Attached-object DDL debt bound (retired by #4598)
# --------------------------------------------------------------------------- #

#: MVR-05A2 recorded forty-five attached-object statements that lacked an
#: absent-table probe. #4598 retired every entry by making Alembic the sole
#: production DDL owner and preserving complete fixture creation only for an
#: absent table under `STORE_SCHEMA_AUTOCREATE`. Keep this mapping empty: a new
#: unprobed index, trigger or rule must fail the gate, never grow the bound.
RECORDED_ATTACHED_DDL_DEBT: Mapping[tuple[str, str, str], int] = MappingProxyType({})


def observed_attached_ddl_debt(
    seams: Sequence[DdlSeam],
) -> Mapping[tuple[str, str, str], int]:
    """The attached-object DDL each module issues without an existence probe."""
    observed: dict[tuple[str, str, str], int] = {}
    for seam in seams:
        if not (seam.durable_database_source and seam.owned_by_revision_chain):
            continue
        if seam.verb == "create table" or seam.existence_probed:
            continue
        if not seam.autocreate_gated:
            continue  # a harder failure, reported by the ungated assertion
        key = (seam.path, seam.verb, seam.table)
        observed[key] = observed.get(key, 0) + 1
    return observed
