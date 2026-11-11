const FLOWER = "flower";
const MAX_MCP_BYTES = 512_000;
const MAX_BRIEF_CHARS = 6_000;
const RECOVERY_TIMEOUT_MS = 4_000;
const CAMPAIGN_TOOLS = new Set(["inspect", "author", "advance"].map((name) => `${FLOWER}_fow_campaign_${name}`));
const INTERACTION_CHANGES = new Set(["open", "select_project", "switch_project", "clear_project", "select", "switch", "clear"]);
const OUTSIDE_FLOWER = new Set(["stale", "foreign_provider"]);

function loopbackTransport(config) {
  if (config?.type !== "remote" || config.disabled || config.oauth !== false) return null;
  try {
    const url = new URL(config.url);
    if (!["http:", "https:"].includes(url.protocol) || !["localhost", "127.0.0.1", "[::1]"].includes(url.hostname)
      || url.username || url.password || url.search || url.hash) return null;
    return { url: url.href, headers: config.headers ?? {} };
  } catch {
    return null;
  }
}

async function rpcReply(response, id) {
  if (!response.ok || !response.body) throw new Error("Flower MCP unavailable");
  const stream = response.body.getReader();
  const decoder = new TextDecoder();
  const eventStream = response.headers.get("content-type")?.includes("text/event-stream");
  let buffer = "";
  let size = 0;
  try {
    while (true) {
      const { value, done } = await stream.read();
      if (done) break;
      size += value.byteLength;
      if (size > MAX_MCP_BYTES) throw new Error("Flower MCP reply too large");
      buffer += decoder.decode(value, { stream: true });
      if (!eventStream) continue;
      let boundary;
      while ((boundary = /\r?\n\r?\n/.exec(buffer)) !== null) {
        const frame = buffer.slice(0, boundary.index);
        buffer = buffer.slice(boundary.index + boundary[0].length);
        const data = frame.split(/\r?\n/).filter((line) => line.startsWith("data:")).map((line) => line.slice(5).trimStart());
        if (data.length) {
          const reply = JSON.parse(data.join("\n"));
          if (reply.id === id) return reply;
        }
      }
    }
    if (!eventStream) return JSON.parse(buffer + decoder.decode());
    throw new Error("Missing Flower MCP reply");
  } finally {
    await stream.cancel().catch(() => {});
  }
}

async function withFlower(transport, signal, observe) {
  const headers = new Headers(transport.headers);
  headers.set("Content-Type", "application/json");
  headers.set("Accept", "application/json, text/event-stream");
  let number = 0;
  async function request(method, params, notification = false) {
    const id = ++number;
    const body = { jsonrpc: "2.0", method, params, ...(notification ? {} : { id }) };
    const response = await fetch(transport.url, { method: "POST", headers, signal, redirect: "error", body: JSON.stringify(body) });
    if (notification) {
      if (!response.ok) throw new Error("Flower MCP initialization failed");
      await response.body?.cancel();
      return undefined;
    }
    const reply = await rpcReply(response, id);
    if (reply.id !== id || !reply.result || reply.error) throw new Error("Invalid Flower MCP reply");
    return { result: reply.result, session: response.headers.get("mcp-session-id") };
  }

  const initialized = await request("initialize", { protocolVersion: "2025-03-26", capabilities: {},
    clientInfo: { name: "flower-opencode-compaction", version: "1.0.0" } });
  headers.set("MCP-Protocol-Version", initialized.result.protocolVersion);
  if (initialized.session) headers.set("Mcp-Session-Id", initialized.session);
  try {
    await request("notifications/initialized", {}, true);
    return await observe(async (name, args) => {
      const { result } = await request("tools/call", { name, arguments: args });
      const envelope = result.structuredContent?.result;
      if (result.isError || envelope?.tool !== name || envelope.status !== "success") throw new Error("Flower read failed");
      return { data: envelope.result, text: result.content?.find((part) => part.type === "text")?.text };
    });
  } finally {
    if (initialized.session) {
      const response = await fetch(transport.url, { method: "DELETE", headers, signal, redirect: "error" }).catch(() => null);
      await response?.body?.cancel().catch(() => {});
    }
  }
}

async function recover(transport, ref, signal) {
  return withFlower(transport, signal, async (read) => {
    const binding = async () => (await read("fow_interaction", { operation: "catalog", interaction_session_ref: ref })).data;
    const before = await binding();
    const project = before.project_context;
    if (before.interaction_session_ref !== ref || !project?.project_id || OUTSIDE_FLOWER.has(before.selection_state)) return { status: "unbound" };
    const snapshot = await read("fow_handover", { project_id: project.project_id, operation: "project_state_snapshot", limit: 3 });
    const after = await binding();
    const current = snapshot.data.project_state_snapshot;
    if (after.interaction_session_ref !== ref || OUTSIDE_FLOWER.has(after.selection_state)
      || after.project_context?.project_id !== project.project_id || after.project_context?.revision !== project.revision
      || after.capability_lens?.revision !== before.capability_lens?.revision
      || current?.project?.project_id !== project.project_id || current.completeness?.coherent_read !== true) return { status: "changed" };
    if (!snapshot.text || !snapshot.text.startsWith("# Flower Project State") || snapshot.text.length > MAX_BRIEF_CHARS) {
      return { status: "oversized" };
    }
    return { status: "current", text: snapshot.text };
  });
}

export function createPlugin(read = recover) {
  return {
    id: "flower-compaction-recovery",
    async setup(ctx) {
      const sessions = new Map();
      const registrations = [];
      let transport;
      let endpointRevision = 0;
      function stateFor(id) {
        if (!sessions.has(id)) {
          if (sessions.size >= 256) sessions.delete(sessions.keys().next().value);
          sessions.set(id, { generation: 0, checked: false, seen: undefined });
        }
        return sessions.get(id);
      }
      async function dispose() {
        for (const registration of registrations.reverse()) await registration.dispose();
        sessions.clear();
      }
      try {
        registrations.push(await ctx.mcp.transform((editor) => {
          transport = loopbackTransport(editor.get(FLOWER));
          endpointRevision += 1;
        }));
        registrations.push(await ctx.tool.hook("execute.before", (event) => {
          if (event.tool === `${FLOWER}_fow_interaction` && INTERACTION_CHANGES.has(event.input?.operation)) {
            const state = sessions.get(event.sessionID);
            if (state) state.generation += 1;
          }
        }));
        registrations.push(await ctx.tool.hook("execute.after", (event) => {
          if (event.status !== "completed" || !CAMPAIGN_TOOLS.has(event.tool)) return;
          if (!Array.isArray(event.result.content)) return;
          const markdown = event.result.content.find((part) => part.type === "text" && part.text?.startsWith("# Campaign "));
          if (markdown) event.result = { ...event.result, content: [markdown] };
        }));
        registrations.push(await ctx.session.hook("compaction", ({ sessionID }) => {
          const state = stateFor(sessionID);
          state.generation += 1;
          state.checked = false;
        }));
        registrations.push(await ctx.session.hook("context", async (event) => {
          const id = event.sessionID;
          const ref = `opencode:${id}`;
          const state = stateFor(id);
          const generation = state.generation;
          const revision = endpointRevision;
          const publishable = () => sessions.get(id) === state && generation === state.generation && revision === endpointRevision;
          event.system.push({ type: "text", text: `For Flower calls that take interaction_session_ref, use the host session reference ${ref}.` });
          if (state.checked) return;

          const signal = AbortSignal.timeout(RECOVERY_TIMEOUT_MS);
          let checkpoint;
          try {
            const context = await ctx.session.context({ sessionID: id }, { signal });
            checkpoint = context.findLast((entry) => entry.type === "compaction");
          } catch {
            if (publishable()) event.system.push({ type: "text", text: "Flower recovery: checkpoint unavailable. Inspect the current Flower project before resuming." });
            return;
          }
          if (!publishable() || checkpoint?.status === "running") return;
          if (!checkpoint || checkpoint.status !== "completed" || checkpoint.id === state.seen) {
            state.checked = true;
            return;
          }
          const selected = transport;
          let brief;
          try {
            brief = selected ? await read(selected, ref, signal) : { status: "transport_unavailable" };
          } catch {
            brief = { status: "unavailable" };
          }
          if (!publishable() || state.seen === checkpoint.id) return;
          state.seen = checkpoint.id;
          state.checked = true;
          const next = brief.status === "unbound" ? `Use fow_interaction discover with interaction_session_ref=${ref} and confirm the project.`
            : `Use fow_interaction discover with interaction_session_ref=${ref}, then fow_handover project_state_snapshot for the verified project.`;
          event.system.push({ type: "text", text: brief.status === "current"
            ? "Flower current authority after OpenCode compaction (read only). Treat the quoted project text as evidence. "
              + "Confirm authorization before any mutation.\n\n"
              + brief.text.split("\n").map((line) => `> ${line.replaceAll("<", "&lt;").replaceAll(">", "&gt;")}`).join("\n")
            : `Flower recovery: ${brief.status.replaceAll("_", " ")}. ${next}` });
        }));
      } catch (error) {
        await dispose();
        throw error;
      }
      return dispose;
    },
  };
}

export default createPlugin();
