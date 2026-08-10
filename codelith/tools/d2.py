"""
Building D2 source, one node at a time.

Diagrams were switched off (`DIAGRAMS_ENABLED=False`) because generated Mermaid was
unreliable, and the cause is structural rather than bad luck: Mermaid is roughly
eight grammars under one name — `flowchart`, `sequenceDiagram`, `classDiagram`,
`erDiagram` — with different arrow syntax and node rules, so a model blends them.
A `-->` from flowchart inside a `classDiagram`, `end` used as a node id, unescaped
parentheses in a label. Our only check was a best-effort regex.

D2 is one uniform grammar, which helps. But the real fix is not a friendlier syntax
for a model to get wrong — **it is not asking a model for syntax at all.** This
module is a builder: the caller supplies subjects and labels, and valid D2 comes out
by construction. A diagram built from the code graph is then also *grounded* by
construction, because every node in it corresponds to a file or module that exists.

Two rules the builder exists to enforce:

* **Identifiers are sanitised, labels are not.** In D2 a dot is nesting, so a node
  keyed `app/db/session.py` silently becomes four nested containers. Every id here is
  reduced to `[A-Za-z0-9_]` and the real text is carried in `label`.
* **Nothing is emitted that was not added.** There is no free text path, so a
  diagram cannot contain a node the caller did not put there.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

#: D2 keys are dot-separated paths, so anything else has to go.
_UNSAFE = re.compile(r"[^A-Za-z0-9_]+")

#: Shapes carrying meaning the reader already knows.
SHAPE_STORE = "cylinder"
SHAPE_QUEUE = "queue"
SHAPE_PACKAGE = "package"
SHAPE_PERSON = "person"
SHAPE_DOCUMENT = "document"


def ident(text: str) -> str:
    """
    A D2-safe identifier for arbitrary text.

    `app/db/session.py` must not become `app` → `db` → `session` → `py`, which is
    what an unescaped dot does. Collisions are possible in principle and harmless in
    practice: two names reducing to one id also read as one node, which is what a
    reader wants from `foo-bar` and `foo_bar`.
    """
    cleaned = _UNSAFE.sub("_", text).strip("_")
    if not cleaned:
        return "n"
    # A leading digit is legal in D2 but reads as a number in some positions.
    return cleaned if not cleaned[0].isdigit() else f"n_{cleaned}"


def _quote(text: str) -> str:
    """A label, safe to place after `label:`."""
    return '"' + str(text).replace("\\", "\\\\").replace('"', '\\"').replace("\n", " ") + '"'


@dataclass(slots=True)
class Node:
    id: str
    label: str
    shape: str | None = None
    tooltip: str | None = None
    #: Container this node lives inside, by id.
    parent: str | None = None


@dataclass(slots=True)
class Edge:
    source: str
    target: str
    label: str = ""
    #: `->` by default; `--` for an association with no direction.
    arrow: str = "->"


@dataclass(slots=True)
class D2Diagram:
    """
    A diagram under construction.

    Deliberately dumb: it holds nodes and edges and prints them. Every decision about
    *what* to draw belongs to the caller, so this stays testable without a graph, a
    database or a model.
    """

    title: str = ""
    direction: str = "right"
    nodes: dict[str, Node] = field(default_factory=dict)
    edges: list[Edge] = field(default_factory=list)
    containers: dict[str, Node] = field(default_factory=dict)

    def container(self, label: str, *, shape: str | None = None) -> str:
        node = Node(id=ident(label), label=label, shape=shape)
        self.containers[node.id] = node
        return node.id

    def node(
        self,
        label: str,
        *,
        shape: str | None = None,
        tooltip: str | None = None,
        parent: str | None = None,
        key: str | None = None,
    ) -> str:
        """Add a node and return its id. Re-adding a key is a no-op, not a duplicate."""
        node_id = ident(key or label)
        if node_id not in self.nodes:
            self.nodes[node_id] = Node(
                id=node_id, label=label, shape=shape, tooltip=tooltip, parent=parent
            )
        return node_id

    def edge(self, source: str, target: str, label: str = "", arrow: str = "->") -> None:
        """
        Connect two nodes that already exist.

        An edge to a node nobody added is dropped rather than drawn: D2 would create
        the missing node implicitly, and an implicitly-created node is exactly the
        ungrounded box this whole approach exists to prevent.
        """
        if source not in self.nodes and source not in self.containers:
            return
        if target not in self.nodes and target not in self.containers:
            return
        if source == target:
            return
        edge = Edge(source=source, target=target, label=label, arrow=arrow)
        if edge not in self.edges:
            self.edges.append(edge)

    @property
    def is_empty(self) -> bool:
        return not self.nodes and not self.containers

    def render(self) -> str:
        """The D2 source. Valid by construction — there is no path that emits free text."""
        lines: list[str] = []
        if self.title:
            lines.append(f"title: {_quote(self.title)} {{ near: top-center; shape: text }}")
        lines.append(f"direction: {self.direction}")
        lines.append("")

        # Containers first, with their children nested inside.
        for container in self.containers.values():
            children = [n for n in self.nodes.values() if n.parent == container.id]
            lines.append(f"{container.id}: {{")
            lines.append(f"  label: {_quote(container.label)}")
            for child in children:
                lines.extend(f"  {line}" for line in self._node_lines(child, nested=True))
            lines.append("}")

        for node in self.nodes.values():
            if node.parent is None:
                lines.extend(self._node_lines(node))

        if self.edges:
            lines.append("")
        for edge in self.edges:
            source = self._path(edge.source)
            target = self._path(edge.target)
            suffix = f": {_quote(edge.label)}" if edge.label else ""
            lines.append(f"{source} {edge.arrow} {target}{suffix}")

        return "\n".join(lines).strip() + "\n"

    def _node_lines(self, node: Node, nested: bool = False) -> list[str]:
        body: list[str] = [f"label: {_quote(node.label)}"]
        if node.shape:
            body.append(f"shape: {node.shape}")
        if node.tooltip:
            body.append(f"tooltip: {_quote(node.tooltip)}")
        return [f"{node.id}: {{", *[f"  {line}" for line in body], "}"]

    def _path(self, node_id: str) -> str:
        """A child of a container is addressed as `container.child`."""
        node = self.nodes.get(node_id)
        if node is not None and node.parent:
            return f"{node.parent}.{node_id}"
        return node_id


__all__ = [
    "D2Diagram",
    "ident",
    "SHAPE_STORE",
    "SHAPE_QUEUE",
    "SHAPE_PACKAGE",
    "SHAPE_PERSON",
    "SHAPE_DOCUMENT",
]
