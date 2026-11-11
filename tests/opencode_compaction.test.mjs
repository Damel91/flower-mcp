import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { test } from "node:test";

const modulePath = new URL("../src/flow_of_work_mcp/resources/opencode/flower-compaction.js", import.meta.url);
const { createPlugin } = await import(`data:text/javascript;base64,${(await readFile(modulePath)).toString("base64")}`);

async function host(read, config = { type: "remote", oauth: false, url: "http://127.0.0.1:8010/mcp" }) {
  const hooks = {};
  let messages = [];
  const registration = { dispose() {} };
  const hook = async (name, callback) => { hooks[name] = callback; return registration; };
  const dispose = await createPlugin(read).setup({
    mcp: { async transform(callback) { callback({ get: () => config }); return registration; } },
    session: { hook, async context() { return messages; } },
    tool: { hook },
  });
  return {
    hooks,
    dispose,
    checkpoint(status, id) { messages = [{ type: "compaction", status, id }]; },
    async context(sessionID = "ses_owned") {
      const event = { sessionID, system: [] };
      await hooks.context(event);
      return event.system.map((part) => part.text).join("\n");
    },
  };
}

test("manual or automatic completion and reopen publish a fresh scoped brief once", async () => {
  const refs = [];
  const read = async (endpoint, ref) => {
    assert.equal(endpoint.url, "http://127.0.0.1:8010/mcp");
    refs.push(ref);
    return { status: "current", text: `Current scope ${refs.length}` };
  };
  const first = await host(read);
  assert.match(await first.context(), /opencode:ses_owned/);
  first.hooks.compaction({ sessionID: "ses_owned" });
  first.checkpoint("running", "msg_compaction_1");
  assert.doesNotMatch(await first.context(), /Current scope/);
  first.checkpoint("completed", "msg_compaction_1");
  assert.match(await first.context(), /Current scope 1/);
  assert.doesNotMatch(await first.context(), /Current scope/);
  first.hooks.compaction({ sessionID: "ses_owned" });
  first.checkpoint("failed", "msg_compaction_2");
  assert.doesNotMatch(await first.context(), /Current scope/);
  await first.dispose();

  const reopened = await host(read);
  reopened.checkpoint("completed", "msg_compaction_1");
  assert.match(await reopened.context(), /Current scope 2/);
  assert.deepEqual(refs, ["opencode:ses_owned", "opencode:ses_owned"]);
  await reopened.dispose();
});

test("a project switch invalidates a pending read and retries against current scope", async () => {
  let finish;
  let announce;
  const started = new Promise((resolve) => { announce = resolve; });
  let count = 0;
  const scoped = await host(async () => {
    count += 1;
    if (count > 1) return { status: "current", text: "new project" };
    return new Promise((resolve) => { finish = resolve; announce(); });
  });
  scoped.checkpoint("completed", "msg_compaction");
  const pending = scoped.context();
  await started;
  scoped.hooks["execute.before"]({ tool: "flower_fow_interaction", input: { operation: "switch_project" }, sessionID: "ses_owned" });
  finish({ status: "current", text: "old project" });
  assert.doesNotMatch(await pending, /old project/);
  assert.match(await scoped.context(), /new project/);
  await scoped.dispose();
});

test("unbound and unsupported transports provide manual recovery and leave other tool results alone", async () => {
  const disconnected = await host(() => assert.fail("unexpected read"), { type: "local" });
  disconnected.checkpoint("completed", "msg_compaction");
  assert.match(await disconnected.context(), /transport unavailable.*fow_handover/);
  await disconnected.dispose();

  const unbound = await host(async () => ({ status: "unbound" }));
  unbound.checkpoint("completed", "msg_compaction");
  assert.match(await unbound.context(), /unbound.*confirm the project/);
  const parts = [{ type: "text", text: "# Campaign work\nCurrent gate" }, { type: "text", text: '{"status":"success"}' }];
  const tool = { tool: "flower_fow_campaign_inspect", status: "completed", result: { content: parts, output: { receipt: 1 } } };
  unbound.hooks["execute.after"](tool);
  assert.deepEqual(tool.result, { content: [parts[0]], output: { receipt: 1 } });
  const other = { ...tool, tool: "other_fow_campaign_inspect", result: { content: parts } };
  unbound.hooks["execute.after"](other);
  assert.deepEqual(other.result.content, parts);
  await unbound.dispose();
});
