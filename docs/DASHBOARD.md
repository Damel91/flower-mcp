# Local browser dashboard

Flower's dashboard lets you inspect registered projects and their engineering
state from a browser on the computer running Flower. It also provides explicit
project deletion under whole-instance maintenance.

The dashboard is included in Flower 0.9.1. It uses the selected Flower ledger
and leaves the MCP tool catalog unchanged.

## Start Flower and open the dashboard

Use the existing profile or configuration that owns the projects you want to
inspect. A different profile selects a different ledger. With Flower installed,
start the existing environment's executable in streamable HTTP mode. Replace the
illustrative configuration path and use a free port.

```sh
flower-mcp serve --config "/absolute/path/flower.yaml" --transport streamable-http --host 127.0.0.1 --port 8010
```

Use the executable's absolute path if it is not on `PATH`. Stop the current owner
of that profile before changing its transport. Keep the same database, YAML and
client settings, updating only the connection transport when necessary. A
client-managed stdio connection alone does not provide the browser dashboard.
See [installation](INSTALLATION.md) for client connection setup and
[upgrading](UPGRADING.md) when updating an existing environment.

An installed CLI can also select an existing profile with `--profile default`
instead of `--config`. Use `--profile-root` with that profile when its location is
explicit. Keep the same selected ledger as the clients that own your projects.

The console prints `Flower dashboard: <local-url>`. Open that stable `/dashboard`
address directly, for example `http://127.0.0.1:8010/dashboard` for the command
above. Flower serves the dashboard and `/mcp` from the same HTTP process,
selected ledger and port. Opening the dashboard does not start another instance.
The stdio entry point continues to serve MCP.

Flower 0.9.1 requires no activation link, access code, login, browser session cookie
or access expiry. Return to the same address later or open another browser while
Flower is running. A desktop launcher can open the address for convenience; it
is not required for access. After a restart, the same URL works again.

Dashboard requests remain restricted to the same computer and local origin.
Administrative requests retain automatic CSRF protection; the browser obtains
its request token from current server status without asking the operator.
This token is request protection, not authentication or proof that a worker
stopped. Network errors offer connection retry without an access-code form.
Browser navigation has its own project selection and leaves chat
project contexts and capability lenses alone.

## Inspect a project

Search the project list by name or ID, then open a row. The list and section
pages contain at most 25 top-level items per page. Use **Precedenti** and
**Successivi** to move through the results.

| Section | What you can inspect |
| --- | --- |
| **Panoramica** | Requirements, current work, the next gate, blockers and open decisions |
| **Roadmap** | Registered milestones, dependencies and their canonical progress dimensions |
| **Pacchetti** | Specification and plan revisions, execution gates, unit reports and pending dependencies |
| **Verifiche** | Campaigns, Oracles, questions and the available evidence |
| **Architettura** | Adopted components, interfaces and decisions |
| **Evidenze** | Retained documents, handovers and verification records |

Expand a row or **Contesto e stato registrato** for its details. Each section
shows its observation time. **Evento requisiti** is the latest requirement-event
ID in `requirement_events.max_event_id.v1`. This counter is scoped to requirement
events. Nested lists also expose their bounds. A partial view does not
establish that additional records are absent.

Use **Aggiorna** for a fresh observation. The page checks maintenance status while
visible. Reading a page does not start coding work, contact an inference provider
or change acceptance. Reported implementation, local checks, campaign verification
and human acceptance keep their separate meanings. A zero criterion denominator
appears as **Nessun criterio**, with the original numbers available in the details.

In **Evidenze**, **Apri contenuto conservato** retrieves an existing record.
**Scarica documento** saves the already retrieved content in the browser. These
actions do not create a new artifact generation or handover. The browser read
limit is 2 MiB; an oversized record retains its reference and reports that limit.

## Read retained Markdown

Markdown evidence opens in **Lettura**, with native headings, lists, tables, code
blocks and an outline under **Nel documento**. Click an outline entry or an
internal document link to reach its heading. **Sorgente** shows the original
Markdown, and **Scarica documento** downloads that same original content.
Switching presentation does not edit the artifact or create another generation.

The reader builds allowlisted document elements from a derived node projection.
Stored HTML remains literal source text; images appear as their alt text.
External HTTP/HTTPS links open only when selected, in a separate tab with opener
and referrer protection. The reader does not fetch image sources, repository
paths or arbitrary reference URLs automatically. JSON evidence keeps its source
presentation.

Native reading supports up to 256 KiB of Markdown and 25,000 derived nodes. If a
presentation exceeds those limits or would make the complete evidence response
exceed 2 MiB, Flower keeps the valid original and reports the reader limitation.
**Sorgente** and the original download remain available. A valid original can also
arrive without reader metadata when even a limited descriptor would exceed the
response ceiling; the interface explains that no reader projection was supplied.
These limits describe the derived presentation, without truncating the retained
document.

## Choose the appearance

The **Tema** control offers **Sistema**, **Chiaro** and **Scuro**. The initial
choice is **Sistema**, which follows the operating system's preferred color
scheme and tracks changes to it. Choosing a manual theme overrides that
preference. The selection is stored locally for this browser and origin. Select
**Sistema** again to restore automatic behavior.

## Delete a project

Use **Elimina** in the project list or **Elimina progetto** in the open project.
The flow has a separate preparation and final confirmation.

1. Select **Prepara eliminazione**. Flower stops admitting database operations
   from the dashboard and MCP, drains admitted work for up to five seconds and
   pauses the job service only if it is idle. Active requests or jobs can refuse
   preparation. Let the owning work settle before trying again.
2. Review the project inventory and all blockers. The maintenance affects every
   project on this Flower instance. Chats receive `blocked/server_maintenance`
   with retry guidance while it is held.
3. If you decide to continue, type the exact project ID. Enter the actual
   reference to your host's stopped-worker or session evidence. Add stopped run
   IDs only for runs your host owns and has actually stopped.
4. Select **Elimina progetto** to submit the same prepared intent and fingerprint.
   Flower rechecks the inventory and native deletion guards before removal.
   A changed inventory requires a fresh explicit preparation and confirmation.

The host-stop reference is an operator declaration with its declared provenance.
The dashboard does not establish that OpenCode, another host or an external
provider stopped merely because the field was filled in. Active or uncertain
external work, missing terminal provider evidence, unsupported schema/storage and
unsafe ownership remain blockers. A host declaration cannot waive another
provider's outstanding work.

Before destructive work, **Annulla e riprendi Flower** ends the browser flow and
resumes service when safe. The native prepared journal remains intact. Closing
the dialog alone leaves the current maintenance state in place; the page's
maintenance banner provides **Apri stato e recupero**.

Deletion uses the runtime's existing exclusive ledger lease throughout. It
preserves other projects, configuration, global sequences, repositories, external
documents, backups and host chats. Flower does not create an archive of the
deleted project's contents.

## Recover an interrupted operation

A missing response is a reason to inspect the existing intent. Keep its deletion
ID and use **Ispeziona stato** before any further destructive action. The browser
retains a reminder for the intent across page reloads and offers recovery instead
of automatically submitting another deletion.

| Observed state | Meaning and operator action |
| --- | --- |
| `prepared` | The inventory is retained. Review the same intent before confirming, or cancel the browser flow |
| `deleting` or `unknown` | The result needs inspection. Keep maintenance and inspect/reconcile the same intent |
| `ledger_deleted` | Ledger removal applied, with cleanup still incomplete. Use **Riconcilia operazione** to recover that intent |
| `scrubbed` | Flower verified cleanup, project absence and database integrity. Normal service can resume when no other unfinished destructive intent remains |

Flower resumes jobs and request admissions after verified cleanup. It does not
rebuild a second runtime or release the ledger lease during maintenance. On
startup, an unfinished destructive journal holds admissions and presents its
recovery state. Prepared and fully scrubbed historical intents do not execute
automatically.

The minimal native journal remains until the relevant host completes its own
cleanup. The dashboard never acknowledges host cleanup automatically. An unreadable
or invalid journal requires operator inspection through the native workflow;
preserve it while investigating.

The existing offline administration route is documented in
[Native project deletion](NATIVE-PROJECT-DELETION.md). Its actual command help is
available with `flower-mcp project-purge --help`. That route requires the relevant
runtime to be stopped and retains its existing ownership and recovery guards.

## Compatibility boundaries

The dashboard uses schema55 and adds no MCP tools to the current 37-tool catalog.
Browser resources are bundled locally and need no external CDN, font service,
model or provider. Theme preference and browser selection are presentation state.

Project deletion still requires supported filesystem durability. Windows native
purge durability is not qualified by browser consultation or by Flower's Windows
installation compatibility. An unavailable or unqualified destructive path stays
blocked. A `scrubbed` result establishes Flower cleanup, without certifying
physical forensic erasure, host-chat cleanup or human product acceptance.
