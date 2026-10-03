"""Build/check the offline reader from the GitHub-first Markdown corpus."""
from __future__ import annotations

import argparse
import ast
from collections import Counter
from hashlib import sha256
from html import escape
import json
from pathlib import Path
import posixpath
import re
import sys
from urllib.parse import quote, unquote, urlencode, urlsplit

from markdown_it import MarkdownIt

ROOT = Path(__file__).resolve().parent
REPOSITORY_URL = "https://github.com/Damel91/flower-mcp"
ASSETS = (
    "flower-mcp-logo.png", "github-markdown.css", "github-markdown-LICENSE.txt",
    "reader.css", "reader.js", "ATTRIBUTION.md",
    "method-authorities.png", "method-plan.png", "method-campaigns.png",
)
LANGUAGES = {"ita": "it", "eng": "en"}
UI = {
    "it": {
        "skip": "Vai al contenuto", "quick": "Accesso rapido", "tools": "Tool",
        "sources": "Fonti", "index": "Indice del percorso", "chapters": "Capitoli",
        "other": "English", "other_folder": "eng",
        "missing_page": "La pagina richiesta non è presente. Puoi ripartire dall'indice.",
        "missing_section": "La sezione richiesta non è presente. Il capitolo resta disponibile.",
        "noscript": "Il percorso completo è disponibile anche nei file Markdown; abilita JavaScript per la navigazione nel reader.",
        "footer": "Percorso editoriale · Scenario illustrativo, non receipt live",
    },
    "en": {
        "skip": "Skip to content", "quick": "Quick access", "tools": "Tools",
        "sources": "Sources", "index": "Presentation index", "chapters": "Chapters",
        "other": "Italiano", "other_folder": "ita",
        "missing_page": "The requested page is unavailable. You can start again from the index.",
        "missing_section": "The requested section is unavailable. The chapter is still accessible.",
        "noscript": "The full presentation is also available as Markdown files; enable JavaScript to navigate this reader.",
        "footer": "Editorial presentation · Illustrative scenario, not live receipts",
    },
}


def heading_slug(text: str) -> str:
    text = text.lower().strip()
    text = "".join(char for char in text if char.isalnum() or char in "-_ ")
    return re.sub(r"\s+", "-", text)


def anchor_prefix(path: str) -> str:
    return "doc-" + sha256(path.encode()).hexdigest()[:12]


def inline_text(token) -> str:
    return "".join(
        child.content for child in token.children or ()
        if child.type in {"text", "code_inline", "image"}
    )


def parse_document(parser: MarkdownIt, source: str):
    tokens = parser.parse(source)
    counts: Counter[str] = Counter()
    anchors = set()
    title = None
    for index, token in enumerate(tokens):
        if token.type == "heading_open":
            text = inline_text(tokens[index + 1])
            slug = heading_slug(text)
            number = counts[slug]
            counts[slug] += 1
            anchor = slug + (f"-{number}" if number else "")
            token.attrSet("id", anchor)
            anchors.add(anchor)
            if title is None and token.tag == "h1":
                title = text
    if not title:
        raise ValueError("Every reader page must have a Markdown H1")
    return tokens, anchors, title


def children(tokens):
    for token in tokens:
        yield token
        if token.children:
            yield from children(token.children)


def route(path: str, section: str = "") -> str:
    values = {"page": path}
    if section:
        values["section"] = section
    return "#" + urlencode(values, quote_via=quote)


def validate_public_catalog(repository: Path, source: str) -> int | None:
    registry = repository / "src/flow_of_work_mcp/application/operation_contracts.py"
    if not registry.is_file():
        return None  # A portable folder does not contain the product checkout.
    tree = ast.parse(registry.read_text(encoding="utf-8"))
    declared = {
        node.args[0].value
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "ToolDescriptor"
        and node.args and isinstance(node.args[0], ast.Constant)
    }
    rows = re.findall(r"^\| `([^`]+)` \|", source, re.MULTILINE)
    if set(rows) != declared or len(rows) != len(declared):
        raise ValueError(
            f"Public tool table drift: missing={sorted(declared - set(rows))}, "
            f"extra={sorted(set(rows) - declared)}, duplicate rows={len(rows) - len(set(rows))}"
        )
    return len(declared)


def compile_reader(root: Path = ROOT / "ita") -> tuple[str, dict]:
    root = root.resolve()
    publication = root.parent
    repository = publication.parent.parent
    manifest = json.loads((root / "navigation.json").read_text(encoding="utf-8"))
    language = manifest["language"]
    if LANGUAGES.get(root.name) != language:
        raise ValueError("Edition directory and language must match")
    ui = UI[language]
    revision = manifest["product_revision"]
    if not re.fullmatch(r"[0-9a-f]{40}", revision):
        raise ValueError("product_revision must be a frozen Git commit")
    parser = MarkdownIt("commonmark", {"html": False}).enable("table")
    pages = {}
    digests = {}
    for entry in manifest["pages"]:
        path = entry["path"]
        if path in pages or path != posixpath.normpath(path) or "\\" in path:
            raise ValueError(f"Duplicate or noncanonical page: {path}")
        file = (root / path).resolve()
        if not file.is_relative_to(root) and path != "../../BOOTSTRAP.md":
            raise ValueError(f"Page escapes the publication boundary: {path}")
        content = file.read_text(encoding="utf-8")
        tokens, anchors, title = parse_document(parser, content)
        pages[path] = {**entry, "content": content, "tokens": tokens,
                       "anchors": anchors, "title": title}
        digests[path] = sha256(content.encode()).hexdigest()
    if "README.md" not in pages:
        raise ValueError("README.md must be the narrative entry point")
    for name in ASSETS:
        asset = publication / "assets" / name
        digests[f"../assets/{name}"] = sha256(asset.read_bytes()).hexdigest()
    catalog = validate_public_catalog(repository, pages["tools.md"]["content"]) if "tools.md" in pages else None
    links = 0
    external = set()
    articles = []
    for path, page in pages.items():
        for token in children(page["tokens"]):
            if token.type == "heading_open":
                token.attrSet("id", anchor_prefix(path) + "--" + token.attrGet("id"))
            if token.type not in {"link_open", "image"}:
                continue
            attribute = "src" if token.type == "image" else "href"
            value = token.attrGet(attribute)
            parts = urlsplit(value)
            links += 1
            if parts.scheme or parts.netloc:
                if token.type == "image" or parts.scheme not in {"https", "http", "mailto"}:
                    raise ValueError(f"Nonlocal image or unsafe link: {path}: {value}")
                if value.startswith(REPOSITORY_URL + "/blob/") and (repository / "src").is_dir():
                    tail = parts.path.split("/blob/", 1)[1]
                    frozen, relative = tail.split("/", 1)
                    if frozen != revision or not (repository / unquote(relative)).is_file():
                        raise ValueError(f"Unverifiable public source reference: {value}")
                token.attrSet("rel", "noopener noreferrer")
                external.add(value)
                continue
            if parts.query:
                raise ValueError(f"Use ordinary relative Markdown links: {value}")
            target = posixpath.normpath(posixpath.join(posixpath.dirname(path), unquote(parts.path))) if parts.path else path
            section = unquote(parts.fragment)
            if target in pages and token.type == "link_open":
                if section and section not in pages[target]["anchors"]:
                    raise ValueError(f"Missing Markdown anchor: {path}: {value}")
                token.attrSet("href", route(target, section))
                token.attrSet("data-page", target)
                if section:
                    token.attrSet("data-section", section)
            else:
                file = (root / target).resolve()
                if target != "index.html" and not file.is_file():
                    raise ValueError(f"Missing local destination: {path}: {value}")
                if file.is_relative_to(root):
                    token.attrSet(attribute, target)
                elif file.parent == publication / "assets" and file.name in ASSETS:
                    token.attrSet(attribute, target)
                elif token.type == "link_open" and target == "../README.md":
                    token.attrSet(attribute, "../index.html")
                elif token.type == "link_open" and target == f'../{ui["other_folder"]}/README.md':
                    token.attrSet(attribute, f'../{ui["other_folder"]}/index.html')
                elif file.is_relative_to(repository) and token.type == "link_open":
                    relative = file.relative_to(repository).as_posix()
                    url = f"{REPOSITORY_URL}/blob/{revision}/{quote(relative)}"
                    if section:
                        url += "#" + quote(section)
                    token.attrSet(attribute, url)
                    token.attrSet("rel", "noopener noreferrer")
                    external.add(url)
                else:
                    raise ValueError(f"Destination escapes the publication: {path}: {value}")
        body = parser.renderer.render(page["tokens"], parser.options, {})
        hidden = "" if path == "README.md" else " hidden"
        articles.append(
            f'<article class="markdown-body" data-document="{escape(path, quote=True)}" '
            f'data-title="{escape(page["title"], quote=True)}" '
            f'data-prefix="{anchor_prefix(path)}"{hidden}>{body}</article>'
        )
    navigation = []
    group = None
    for path, page in pages.items():
        if page["group"] != group:
            group = page["group"]
            navigation.append(f'<h2>{escape(group)}</h2>')
        current = ' aria-current="page"' if path == "README.md" else ""
        navigation.append(
            f'<a href="{escape(route(path), quote=True)}" data-page="{escape(path, quote=True)}"{current}>'
            f'{escape(page["label"])}</a>'
        )
    title = escape(manifest["title"])
    subtitle = escape(manifest["subtitle"])
    digest = sha256(json.dumps(digests, sort_keys=True).encode()).hexdigest()
    output = f'''<!doctype html>
<html lang="{language}">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; script-src 'self'; style-src 'self'; img-src 'self'; connect-src 'none'; base-uri 'none'; form-action 'none'">
<meta name="color-scheme" content="light dark">
<title>{title}: {subtitle}</title>
<link rel="stylesheet" href="../assets/github-markdown.css">
<link rel="stylesheet" href="../assets/reader.css">
<script src="../assets/reader.js" defer></script>
</head>
<body>
<!-- Generated from linked Markdown. Source digest: {digest}. -->
<a class="skip-link" href="#content">{ui['skip']}</a>
<header class="site-header">
<a class="brand" href="{route('README.md')}" data-page="README.md"><img src="../assets/flower-mcp-logo.png" alt="" width="48" height="48"><span><strong>{title}</strong><small>{subtitle}</small></span></a>
<nav aria-label="{ui['quick']}"><a href="{route('tools.md')}" data-page="tools.md">{ui['tools']}</a><a href="{route('sources.md')}" data-page="sources.md">{ui['sources']}</a><a id="language-switch" href="../{ui['other_folder']}/index.html">{ui['other']}</a></nav>
</header>
<div class="layout">
<aside><details id="navigation" open><summary>{ui['index']}</summary><nav aria-label="{ui['chapters']}">{''.join(navigation)}</nav></details></aside>
<main id="content" tabindex="-1"><p id="route-error" role="status" data-missing-page="{escape(ui['missing_page'], quote=True)}" data-missing-section="{escape(ui['missing_section'], quote=True)}" hidden></p>{''.join(articles)}
<noscript><p>{ui['noscript']}</p></noscript>
</main>
</div>
<footer>Flower MCP · {ui['footer']}</footer>
</body>
</html>
'''
    report = {"language": language, "pages": len(pages), "links_checked": links,
              "public_tools_checked": catalog, "product_revision": revision,
              "content_digest": digest, "html_sha256": sha256(output.encode()).hexdigest(),
              "sources": digests, "external_links": sorted(external),
              "scope": "Editorial link/catalog/package validation, not product or model qualification"}
    return output, report


def compile_selector(root: Path = ROOT) -> str:
    parser = MarkdownIt("commonmark", {"html": False}).enable("table")
    tokens, _, _ = parse_document(parser, (root / "README.md").read_text(encoding="utf-8"))
    allowed = {"index.html", "assets/flower-mcp-logo.png"}
    for folder in LANGUAGES:
        allowed.update({f"{folder}/README.md", f"{folder}/index.html"})
    for token in children(tokens):
        if token.type not in {"image", "link_open"}:
            continue
        attribute = "src" if token.type == "image" else "href"
        target = token.attrGet(attribute)
        if target not in allowed:
            raise ValueError(f"Invalid language-index destination: {target}")
        if target.endswith("README.md"):
            target = target.removesuffix("README.md") + "index.html"
        token.attrSet(attribute, target)
    body = parser.renderer.render(tokens, parser.options, {})
    return f'''<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'self'; img-src 'self'; connect-src 'none'; base-uri 'none'; form-action 'none'">
<meta name="color-scheme" content="light dark">
<title>Flower MCP: Italiano / English</title>
<link rel="stylesheet" href="assets/github-markdown.css">
<link rel="stylesheet" href="assets/reader.css">
</head>
<body><main class="language-home"><article class="markdown-body">{body}</article></main></body>
</html>
'''


def main() -> int:
    arguments = argparse.ArgumentParser(description=__doc__)
    arguments.add_argument("--check", action="store_true", help="validate without writing")
    args = arguments.parse_args()
    try:
        expected = {}
        reports = {}
        page_paths = []
        for folder in LANGUAGES:
            output, report = compile_reader(ROOT / folder)
            reports[folder] = report
            expected[f"{folder}/index.html"] = output
            expected[f"{folder}/build-report.json"] = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
            manifest = json.loads((ROOT / folder / "navigation.json").read_text(encoding="utf-8"))
            page_paths.append([page["path"] for page in manifest["pages"]])
        if page_paths[0] != page_paths[1]:
            raise ValueError("Language editions must contain the same page identities")
        expected["index.html"] = compile_selector()
        summary = {"editions": reports, "index_sha256": sha256(expected["index.html"].encode()).hexdigest()}
        expected["build-report.json"] = json.dumps(summary, ensure_ascii=False, indent=2) + "\n"
        if args.check:
            for filename, content in expected.items():
                file = ROOT / filename
                if not file.is_file() or file.read_text(encoding="utf-8") != content:
                    raise ValueError(f"Stale generated {filename}; run build_reader.py")
        else:
            for filename, content in expected.items():
                (ROOT / filename).write_text(content, encoding="utf-8", newline="\n")
        print(json.dumps({folder: {key: report[key] for key in ("pages", "links_checked", "public_tools_checked")} for folder, report in reports.items()}, indent=2))
        return 0
    except (ValueError, OSError, KeyError) as error:
        print(f"Reader validation failed: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
