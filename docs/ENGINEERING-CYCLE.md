# The engineering cycle with Flower

Flower keeps the decisions that govern software work recoverable. Your coding
agent investigates the repository, chooses technical solutions, edits code and
runs checks with its host tools. Flower records requirements, Goals, milestones,
architecture, plans, findings, verification and handovers in its project ledger.
No internal model or implementation provider is required for this cycle.

## Start from the intended behavior

Describe scenarios: what someone should be able to do and what the software
should show. The agent investigates existing code and reusable solutions, fills
technical gaps, and asks progressive questions about intended behavior. It
presents a roadmap for your actual confirmation. Confirmation of a roadmap,
verification of software and human acceptance remain separate decisions.

Use the current `provider-agnostic-engineering-cycle` recipe through
`fow_capabilities`. Recipes give policy; the current interaction frame and
operation help give the next action and its exact inputs. A host chooses which
tools to present through its explicit lens. Flower does not replace that host's
agent loop or execute a suggested call automatically.

## Put governing architecture in Flower

Record and adopt components, interfaces and technical decisions through
`fow_architecture`; select the relevant canonical references in the packet.
Every newly accepted plan needs an adopted architecture containing at least one
component and valid selected references. Investigating technical architecture is
the engineer's responsibility. Ask the stakeholder when intended behavior is
unclear or when they requested participation in technical choices.

Repository Markdown can explain a design or hold a revision-linked export.
It must not become a competing mutable architecture authority. Project agents
using Flower need no development overlay or documentary implementation index.
The host's `AGENTS.md` contains operating rules and stable project locators, not
a duplicate lifecycle ledger. [Bootstrap](BOOTSTRAP.md) prints the complete
marked template; the host merges it when authorized.

## Execute complete, bounded work

For host coding, explicitly select external-agent execution. Use the accepted
plan, closed Packet Validation Projection (PVP), current guards and dependency-
ordered TODO frontier. Instructions, producer/consumer contracts, criterion
ownership and unit-local checks define the work. Future outputs are declarations,
not evidence that their files already exist. Deferred campaign, Oracle and
explicit-authority checks remain visible as separate obligations.

Report actual outcomes against the issued revisions and authority fingerprint.
A report records a host declaration; it does not become a provider audit or
human acceptance. When an effect or response is uncertain, read its original
identity before retrying. Existing code or historical evidence must be inspected
before creating replacement implementation work.

## Reconcile at a natural boundary

At completion of a packet/increment, and when recovering context, compare the
actual repository with the scoped requirements, adopted architecture, Goal
grounding, verification obligations and recorded outcomes. Do this at the bounded
work boundary, rather than after every tool call.

Distinguish implemented behavior, missing ledger registration, evidence valid on
its original revision, demonstrated drift and remaining current obligations.
A missing registration does not establish that code is missing. A changed
requirement does not erase the historical result or justify rerunning every test.
Reuse original evidence with its original date, revision and provenance; perform
new checks when a concrete change, failure or unresolved concern requires them.

Newly accepted plans carry engineering-cycle version 1. For external-agent work,
all unit reports may be complete while repository reconciliation is still open.
Flower preserves implementation and local-verification facts and holds overall
closure and dependent admission until the current scoped review is complete.
Historical accepted plans keep the contract under which they were issued; an
upgrade does not silently enroll or rewrite them.

Read `fow_external_work` validation with `payload: {"detail":"full"}`. Its
`repository_review` supplies the exact scope, requirement IDs, basis fingerprint
and next gate. Submit a real host observation through `fow_audit_phase` using
that template, an actor and a durable request ID. Cover requirements,
architecture, grounding, verification and outcomes. Each coverage row carries
its state, rationale and evidence references. Use the current schema rather
than inventing identifiers or claiming that Flower inspected the repository.

`aligned` and `reconciled` satisfy current coverage. `historical_on_pin` preserves
retrospective evidence but does not establish applicable current closure.
`unknown`, missing authority, compatibility review and current obligations remain
open. `not_applicable` is accepted only when the scoped canonical objects really
are absent. A relevant authority/report change makes the old review stale;
unrelated audit activity does not. Flower does not certify semantic truth from
host declarations.

The audit returns a durable job. Read it with `fow_get_job`; the original committed
audit remains recoverable even after a later audit or a post-commit job failure.
Identical review-request replay recovers its original job. Changed actor or
payload conflicts; inspect the original request before deciding a new action.
Default Markdown is concise, complete structured data remains available, and an
explicit full validation exposes complete rationale and original report history.
History can be read outside execution admission; it never bypasses its guards.

## Work offline and resume honestly

Export the complete plan using the existing artifact lifecycle, then have the
host save its Markdown. The artifact includes issued authority, architecture
references, ordered work, producer/consumer contracts, local and deferred checks,
cycle policy and reconciliation obligations. Flower need not stay online for
the host to execute that authorized work.

Keep actual outcomes and evidence with the exported revision/fingerprint. If a
new intent question, semantic mismatch or missing mutation authority prevents
continuation offline, stop the affected effects and retain the gap. An
interrupted handover is allowed with open obligations; it is not completion.
After reconnecting, inspect current state, report the original outcomes and
explicitly reconcile them. Do not manufacture current evidence or acceptance.

A discovered mismatch requires rereading canonical intent and an ordinary
finding-linked corrective packet with regression obligations. A genuinely new
behavior requires ordinary authority revision and the affected roadmap's actual
confirmation. [Continuous recovery](CONTINUOUS-RECOVERY.md) explains the public
read and recovery routes.

## Optional scoped semantic support

Host-executed intention grounding can explicitly select `requirement_ids` on
`fow_semantic` preparation with `role="intention_grounding"` and
`execution_mode="host"`. Omission retains the broad project selection; `[]`
explicitly selects no requirements. Supply up to 128 unique existing IDs from
the same project. The selected scope remains attached to that preparation and
its currentness comparison; it is not a whole-project completeness claim.
Actual truncation remains visible. Other roles/internal execution reject this
host-only scope field. Internal models are optional and configured separately in
[advanced configuration](ADVANCED-CONFIGURATION.md).
