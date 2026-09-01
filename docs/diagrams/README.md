# kaif-eval architecture diagrams

## Fix: "Unable to load initial data"

That error means the Excalidraw extension could not parse the file. Try in this order:

### 1. Smoke test (official format)

Open **`00-smoke-test.excalidraw`** first. This is copied from the [excalidraw-vscode](https://github.com/excalidraw/excalidraw-vscode) repo and should always open.

- If smoke test **fails** → extension setup issue (see step 2).
- If smoke test **works** but diagram 1–4 fail → tell us; we will fix the generator.

### 2. Extension setup (Cursor / VS Code)

1. Install **Excalidraw** extension: `pomdtr.excalidraw-editor`
2. Command palette → **Developer: Restart Extension Host**
3. Open files ending in **`.excalidraw`** only (not `.excalidraw.json`)
4. Right-click folder → **New File** → `test.excalidraw` often works better than renaming a text file

### 3. Browser (no extension)

1. Go to [excalidraw.com](https://excalidraw.com)
2. **Open** → select e.g. `docs/diagrams/01-kaif-eval-overview.excalidraw`

### 4. Markdown preview (always works)

Open **`preview.md`** and press **Cmd+Shift+V** (Mac) / **Ctrl+Shift+V** (Windows).

## Diagram files

| File | PNG | Content |
|------|-----|---------|
| `00-smoke-test.excalidraw` | — | Official example — use to verify extension |
| `01-kaif-eval-overview.excalidraw` | [01-kaif-eval-overview.png](01-kaif-eval-overview.png) | Signals → engine → kaif-value |
| `02-eval-designer.excalidraw` | [02-eval-designer.png](02-eval-designer.png) | Mother-file components |
| `03-worker-job.excalidraw` | [03-worker-job.png](03-worker-job.png) | Triggers + pipeline |
| `04-correlation-engine.excalidraw` | [04-correlation-engine.png](04-correlation-engine.png) | OTel + correlation + quality |

Regenerate: `python3 docs/build_excalidraw_diagrams.py`
