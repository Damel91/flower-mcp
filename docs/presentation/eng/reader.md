# The same presentation, offline too

[Index](README.md) · [Sources](sources.md#reader-and-attribution)

## Read on GitHub

The entry point is [README.md](README.md). All chapters use relative links,
headings, tables, quotations and code blocks readable on GitHub. The reader
does not contain a second version of the story.

## Read locally

Open [index.html](index.html) in a browser. Reading the presentation needs no
HTTP server, Python, Node, Flower, model, login or Internet connection.

The `presentation` folder contains both editions, `ita` and `eng`, their generated
HTML, and shared scripts, stylesheets and logo. Copy the whole `presentation`
folder, not just one language, to read it without the rest of the repository.
The language selector opens the same chapter in the other edition. The reader
also includes the public English bootstrap as further reading. GitHub source
links and the product README are external references: they need a network when
clicked, but are never loaded automatically.

The index, chapter links, anchors and browser back/forward work in the reader.
Content styling follows GitHub Markdown; it is not an identical copy of GitHub's
UI. Navigation adapts to the viewport and the theme follows the system.
Fonts are not downloaded.

Editorial verification covered Chrome on macOS, offline, at widths of 1440,
390 and 320 pixels, and a copy containing only HTML and assets. It is not native
Windows/Linux certification or a Flower server campaign.

## Update the presentation

Edit Markdown in the appropriate language, not the content of `index.html`.
One builder regenerates both editions and the bilingual index. Rebuilding needs
Python 3.11+ and the editorial dependency in `requirements-reader.txt`.
Use an editorial virtual environment separate from Flower's runtime. From the
repository root, with that environment active:

```sh
python -m pip install -r docs/presentation/requirements-reader.txt
python docs/presentation/build_reader.py
python docs/presentation/build_reader.py --check
python -m unittest discover -s docs/presentation/tests
```

On macOS/Linux use `python3` if needed; on Windows you can use `py -3.11`.
The commands use Python and relative paths, not Bash scripts. No editorial
dependency is added to the server installation.

`--check` validates local links, anchors and generated-HTML consistency without
updating files. Tool names are compared with repository source when available.
The [sources page](sources.md) records the product snapshot behind this edition.

## The reader's boundary

This is a publication to read, not an MCP client: it does not call Flower,
execute code, write the ledger or generate acceptance evidence. Markdown
remains the source; HTML is its local projection.

[Index](README.md) · [Talk outline](talk.md)
