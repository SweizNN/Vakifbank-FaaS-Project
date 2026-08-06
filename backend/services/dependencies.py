import json
import re
from pathlib import Path
from xml.sax.saxutils import escape as xml_escape

# A single dependency spec is one token: no whitespace, no quotes/backslash
# (never legitimately needed by pip/npm/go/cargo/maven specifiers, and
# excluding them rules out breaking out of a TOML/go.mod insertion point).
_SPEC_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.\-/@:+<>=!~,\[\]]{0,199}$")


def _valid(spec: str) -> bool:
    return bool(_SPEC_RE.match(spec))


def apply_dependencies(fn_dir: Path, language: str, deps: list[str]) -> list[str]:
    """
    Writes `deps` into the manifest file for `language` inside `fn_dir`.
    Returns the specs actually applied (invalid entries are dropped silently).
    """
    clean = [d.strip() for d in (deps or []) if _valid(d.strip())]
    if not clean:
        return []
    handler = _HANDLERS.get(language)
    if handler:
        handler(fn_dir, clean)
    return clean


def _base_name(spec: str) -> str:
    """Package name portion of a spec, stripping version/extras markers."""
    return re.split(r"[=<>!~\[]", spec, maxsplit=1)[0].strip().lower()


# ── Python: pyproject.toml `dependencies = [...]` array ───────────────────

def _apply_python(fn_dir: Path, deps: list[str]) -> None:
    path = fn_dir / "pyproject.toml"
    if not path.exists():
        return
    text = path.read_text(encoding="utf-8")
    m = re.search(r"dependencies\s*=\s*\[(.*?)\]", text, re.S)
    if not m:
        return

    new_names = {_base_name(d) for d in deps}
    kept = []
    for line in m.group(1).splitlines():
        item = line.strip().rstrip(",").strip()
        if not item:
            continue
        if _base_name(item.strip("\"'")) in new_names:
            continue
        kept.append(item if item.endswith(",") else item + ",")

    new_entries = [f'  "{d}",' for d in deps]
    new_block = "\n" + "\n".join(kept + new_entries) + "\n"
    text = text[: m.start(1)] + new_block + text[m.end(1) :]
    path.write_text(text, encoding="utf-8")


# ── Node / TypeScript: package.json `dependencies` object ─────────────────

def _apply_node(fn_dir: Path, deps: list[str]) -> None:
    path = fn_dir / "package.json"
    if not path.exists():
        return
    data = json.loads(path.read_text(encoding="utf-8"))
    data.setdefault("dependencies", {})

    for spec in deps:
        if spec.startswith("@"):
            # scoped package: @scope/name[@version]
            at_idx = spec.find("@", 1)
            name, version = (spec[:at_idx], spec[at_idx + 1 :]) if at_idx != -1 else (spec, "latest")
        else:
            name, _, version = spec.partition("@")
            version = version or "latest"
        data["dependencies"][name] = version

    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")

    # A stale lockfile makes the npm buildpack run `npm ci`, which hard-fails
    # on any mismatch. Delete it so `npm install` resolves fresh instead.
    lock = fn_dir / "package-lock.json"
    if lock.exists():
        lock.unlink()


# ── Go: go.mod `require` lines ─────────────────────────────────────────────

def _apply_go(fn_dir: Path, deps: list[str]) -> None:
    path = fn_dir / "go.mod"
    if not path.exists():
        return

    modules: dict[str, str] = {}
    for spec in deps:
        if "@" not in spec:
            continue  # Go modules require an explicit pinned version
        mod, _, version = spec.partition("@")
        modules[mod] = version
    if not modules:
        return

    lines = path.read_text(encoding="utf-8").splitlines()
    lines = [l for l in lines if not any(l.strip().startswith(f"require {m} ") for m in modules)]
    for mod, version in modules.items():
        lines.append(f"require {mod} {version}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    # go.sum won't have entries for the new modules; let the Go buildpack
    # auto-resolve them at build time instead of failing under -mod=readonly.
    gosum = fn_dir / "go.sum"
    if gosum.exists():
        gosum.unlink()

    project_toml = fn_dir / "project.toml"
    project_toml.write_text(
        '[[io.buildpacks.build.env]]\nname = "BP_GO_BUILD_FLAGS"\nvalue = "-mod=mod"\n',
        encoding="utf-8",
    )


# ── Rust: Cargo.toml `[dependencies]` table ────────────────────────────────

def _apply_rust(fn_dir: Path, deps: list[str]) -> None:
    path = fn_dir / "Cargo.toml"
    if not path.exists():
        return
    text = path.read_text(encoding="utf-8")

    names, new_lines = set(), []
    for spec in deps:
        name, _, version = spec.partition("@")
        name = name.strip()
        names.add(name)
        new_lines.append(f'{name} = "{version.strip() or "*"}"')

    marker = "[dependencies]"
    idx = text.find(marker)
    if idx == -1:
        text = text.rstrip() + f"\n\n{marker}\n" + "\n".join(new_lines) + "\n"
    else:
        start = idx + len(marker)
        rest = text[start:]
        next_section = re.search(r"\n\[", rest)
        section_end = start + (next_section.start() if next_section else len(rest))
        section = text[start:section_end]

        kept = []
        for line in section.splitlines():
            m = re.match(r"\s*([A-Za-z0-9_\-]+)\s*=", line)
            if m and m.group(1) in names:
                continue
            if line.strip():
                kept.append(line)

        new_section = "\n" + "\n".join(kept + new_lines) + "\n"
        text = text[:start] + new_section + text[section_end:]
    path.write_text(text, encoding="utf-8")


# ── Quarkus: pom.xml `<dependencies>` block ────────────────────────────────

def _apply_quarkus(fn_dir: Path, deps: list[str]) -> None:
    path = fn_dir / "pom.xml"
    if not path.exists():
        return
    text = path.read_text(encoding="utf-8")

    blocks = []
    for spec in deps:
        parts = spec.split(":")
        if len(parts) < 2:
            continue  # need at least groupId:artifactId
        group_id, artifact_id = xml_escape(parts[0]), xml_escape(parts[1])
        version_xml = f"\n      <version>{xml_escape(parts[2])}</version>" if len(parts) > 2 else ""
        blocks.append(
            f"    <dependency>\n      <groupId>{group_id}</groupId>\n"
            f"      <artifactId>{artifact_id}</artifactId>{version_xml}\n    </dependency>"
        )
    if not blocks:
        return

    # The POM has two `</dependencies>` closing tags: one inside
    # <dependencyManagement> (BOM version imports only, doesn't add the dep
    # to the classpath) and the real project <dependencies> block. Target
    # whichever </dependencies> comes *after* </dependencyManagement> (or
    # the file's only one, if there's no dependencyManagement section).
    search_from = text.find("</dependencyManagement>")
    search_from = search_from + len("</dependencyManagement>") if search_from != -1 else 0
    close_idx = text.find("</dependencies>", search_from)
    if close_idx == -1:
        return

    insertion = "\n".join(blocks) + "\n  </dependencies>"
    text = text[:close_idx] + insertion + text[close_idx + len("</dependencies>") :]
    path.write_text(text, encoding="utf-8")


_HANDLERS = {
    "python": _apply_python,
    "node": _apply_node,
    "typescript": _apply_node,
    "go": _apply_go,
    "rust": _apply_rust,
    "quarkus": _apply_quarkus,
}
