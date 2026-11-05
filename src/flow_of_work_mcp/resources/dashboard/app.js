"use strict";

(() => {
  const sections = {
    overview: { label: "Panoramica", description: "L’intento, il lavoro attuale e i punti che richiedono attenzione." },
    roadmap: { label: "Roadmap", description: "Milestone e dipendenze nel loro ordine di realizzazione." },
    packets: { label: "Pacchetti", description: "Il lavoro dichiarato, le unità e le condizioni per procedere." },
    verification: { label: "Verifiche", description: "Campaign, Oracle ed evidenze con il loro stato effettivo." },
    architecture: { label: "Architettura", description: "Componenti, interfacce e decisioni adottate per il progetto." },
    evidence: { label: "Evidenze", description: "Riferimenti, documenti e handover conservati da Flower." },
  };
  const labels = {
    project_id: "ID progetto", name: "Nome", title: "Titolo", description: "Descrizione", status: "Stato",
    objective: "Obiettivo", purpose: "Scopo", rationale: "Motivazione", goal: "Goal", goals: "Goal",
    current_scope: "Ambito attuale", scope: "Ambito", next_gate: "Prossimo punto di controllo",
    next_action: "Prossima azione", reason: "Motivo", resolution: "Come procedere", message: "Dettaglio",
    requirement_ids: "Requisiti", requirements: "Requisiti", requirement_id: "ID requisito",
    goal_node_id: "ID goal", milestone_id: "ID milestone", milestones: "Milestone", milestone: "Milestone",
    change_id: "ID change", packet_id: "ID pacchetto", packets: "Pacchetti", packet: "Pacchetto",
    spec_revision: "Revisione specifica", plan_revision: "Revisione piano", revision: "Revisione",
    state: "Stato", consumption_mode: "Modalità di esecuzione", acceptance: "Accettazione",
    implementation: "Implementazione dichiarata", local_verification: "Verifica locale", verification: "Verifica",
    verification_state: "Stato della verifica", acceptance_state: "Stato dell’accettazione",
    completed: "Completati", total: "Totale", pending: "In attesa", remaining: "Rimanenti",
    units: "Unità", todos: "TODO", current_unit: "Unità attuale", unit_key: "Chiave unità",
    client_unit_key: "Chiave unità", unit_number: "Numero unità", report_key: "Report",
    instructions: "Istruzioni", unit_checks: "Controlli locali", implements: "Criteri realizzati",
    provides: "Contratti prodotti", requires: "Contratti richiesti", verifies: "Obblighi di verifica",
    depends_on: "Dipendenze", dependencies_pending: "Dipendenze aperte", unresolved: "Obblighi aperti",
    unresolved_questions: "Domande aperte", completion_criteria: "Criteri di completamento",
    in_scope: "Ambito incluso", out_of_scope: "Ambito escluso", invariants: "Invarianti",
    execution_allowed: "Esecuzione ammissibile", plan_executable: "Piano eseguibile",
    validation: "Validazione", repository_review: "Review del repository", deferred_verification: "Verifiche differite",
    campaign_id: "ID campaign", campaigns: "Campaign", case_id: "ID caso", cases: "Casi",
    oracle_id: "ID Oracle", oracles: "Oracle", oracle_kind: "Tipo Oracle", questions: "Domande",
    oracle_ir_questions: "Domande IR", constructibility: "Costruibilità", qualification: "Qualifica",
    field_name: "Campo", prompt: "Domanda", answer: "Risposta", required: "Richiesto",
    source: "Fonte", provenance: "Provenienza", actor: "Autore", reference: "Riferimento",
    evidence_reference: "Riferimento evidenza", evidence_refs: "Riferimenti evidenza", evidence: "Evidenze",
    evidence_id: "ID evidenza", kind: "Tipo", outcome: "Esito", summary: "Riepilogo",
    recorded_at: "Registrato", created_at: "Creato", updated_at: "Aggiornato", occurred_at: "Data",
    observed_at: "Osservato", source_revision: "Revisione sorgente", source_ledger_version: "Evento requisiti",
    authority_fingerprint: "Fingerprint dell’autorità", current: "Corrente", fingerprint: "Fingerprint",
    components: "Componenti", interfaces: "Interfacce", decisions: "Decisioni", definition: "Definizione",
    responsibility: "Responsabilità", boundaries: "Confini", links: "Collegamenti", clauses: "Clausole",
    statement: "Dichiarazione", signature: "Firma", file_path: "Percorso", symbol: "Simbolo",
    entry_policy: "Condizioni di ingresso", exit_policy: "Condizioni di uscita", prerequisite_requirement_ids: "Requisiti preliminari",
    prerequisite_producers: "Produttori preliminari", risk_disposition: "Gestione del rischio",
    generation_id: "Generazione", artifact_kind: "Tipo documento", artifact_id: "ID documento",
    content_sha256: "Impronta del contenuto", handover_id: "ID handover", content: "Contenuto",
    bounds: "Limiti della vista", truncated: "Vista parziale", count: "Elementi", offset: "Posizione",
    more_available: "Altri elementi disponibili", diagnostics: "Diagnostica", blockers: "Blocchi",
    tool: "Operazione MCP", operation: "Operazione", contract_version: "Contratto", obligations: "Obblighi",
  };
  const states = {
    planned: "Pianificato", partial: "Parziale", implemented: "Implementato", complete: "Completato",
    completed: "Completato", pending: "In attesa", ready: "Pronto", blocked: "Bloccato", failed: "Fallito",
    success: "Riuscito", passed: "Passato", accepted: "Accettato", rejected: "Rifiutato", stale: "Da rivalutare",
    current: "Corrente", closed: "Chiuso", open: "Aperto", draft: "Bozza", unknown: "Sconosciuto",
    not_recorded: "Non registrato", not_inferred: "Non dedotta", not_run: "Non eseguito", unsupported: "Non supportato",
    constructible: "Costruibile", needs_oracle: "Oracle da completare", unqualified: "Da qualificare",
    running: "In esecuzione", proposed: "Proposto", external_agent: "Agente esterno", deferred: "Differito",
    removed: "Ritirato", maintenance: "Manutenzione", recovery_required: "Recupero necessario",
    prepared: "Preparato", deleting: "Eliminazione in corso", ledger_deleted: "Dati rimossi, pulizia da completare",
    scrubbed: "Pulizia verificata", absent: "Assente", unprepared: "Da preparare",
    host_reported: "Dichiarata dall’host", external_agent_report: "Report dell’agente esterno",
    deterministic: "Deterministica", live: "Live", unit_check: "Controllo locale", human: "Umana",
    visible_milestones: "Milestone visibili in questa pagina",
  };
  const errorMessages = {
    dashboard_delete_password_required: "Inserisci la password dell’account locale per confermare l’eliminazione.",
    dashboard_delete_password_denied: "La password dell’account locale non è stata accettata. Inseriscila di nuovo per riprovare.",
    dashboard_login_denied: "Nome utente o password non validi per l’account locale proprietario dei dati.",
    dashboard_session_required: "Accedi con il tuo account locale per aprire Flower.",
    dashboard_session_changed: "L’accesso è cambiato. Accedi di nuovo per continuare.",
    dashboard_owner_changed: "La proprietà dei dati è cambiata. Controlla configurazione e permessi prima di riprovare.",
    dashboard_auth_rate_limited: "Troppi tentativi di accesso. Attendi prima di riprovare.",
    dashboard_auth_busy: "È già in corso una verifica dell’account. Attendi e riprova.",
    dashboard_auth_unavailable: "La verifica dell’account locale non è disponibile. Controlla i prerequisiti di autenticazione del tuo sistema operativo nella guida di Flower, poi riprova.",
    dashboard_csrf_invalid: "Flower è stato riavviato o lo stato della richiesta è cambiato. Aggiorna la vista e controlla lo stato dell’operazione prima di riprovare.",
    dashboard_project_conflict: "Questo ID è già in uso. Scegli un altro identificativo.",
    settings_configuration_changed: "Il file del profilo è cambiato. Riavvia Flower per rileggerlo.",
    settings_draft_changed: "La bozza è cambiata. Rileggi il profilo prima di salvare.",
    dashboard_project_not_found: "Il progetto non è più presente in questo profilo. Torna ai progetti e aggiorna l’elenco.",
    dashboard_evidence_too_large: "L’evidenza supera il limite di 2 MiB di questa vista. Il suo riferimento rimane visibile nel progetto.",
    dashboard_archive_busy: "È già in corso la preparazione o il download di un archivio. Attendi che finisca e riprova.",
    dashboard_archive_failed: "Flower non ha potuto preparare l’archivio. Controlla lo spazio disponibile e riprova.",
    dashboard_backup_failed: "Flower non ha potuto completare l’operazione sui backup. Rileggi l’elenco prima di riprovare.",
    archive_backup_not_found: "Il backup non è più presente. Aggiorna l’elenco.",
    archive_backup_id_invalid: "L’identificativo del backup non è valido. Aggiorna l’elenco e seleziona un backup.",
    archive_backup_changed: "Il backup è cambiato. Aggiorna l’elenco prima di riprovare.",
    archive_backup_limit: "Hai raggiunto il limite dei backup conservati. Scarica le copie che ti servono e rimuovine una prima di crearne un’altra.",
    archive_backup_inventory_limit: "Flower non può mostrare tutti i backup conservati. Controlla la cartella dei backup del profilo.",
    archive_project_not_found: "Il progetto non è più presente. Aggiorna l’elenco prima di esportarlo.",
    archive_size_exceeded: "I dati superano il limite di dimensione dell’archivio.",
    archive_scope_invalid: "Non è possibile esportare il progetto senza i riferimenti necessari. Controlla i dati del profilo.",
    archive_schema_unsupported: "Il formato del registro non è supportato da questa versione di Flower.",
    archive_source_unavailable: "Il registro non è disponibile. Controlla il profilo e riprova.",
    archive_io_failure: "Flower non ha potuto leggere o scrivere l’archivio. Controlla lo spazio disponibile e i permessi del profilo.",
    archive_invalid: "L’archivio non ha superato il controllo di integrità.",
  };
  const markdownTags = new Set(["p", "h1", "h2", "h3", "h4", "h5", "h6", "ul", "ol", "li", "blockquote",
    "pre", "code", "strong", "em", "s", "hr", "br", "a", "table", "thead", "tbody", "tr", "th", "td", "span"]);
  const markdownHeadingId = /^flower-md-heading-[1-9][0-9]*$/;
  const markdownLimits = {
    reader_source_limit: "La lettura strutturata è limitata a documenti Markdown di 256 KiB. Il sorgente completo e il download restano disponibili.",
    reader_node_limit: "Il documento supera il limite di 25.000 nodi della vista di lettura. Il sorgente completo e il download restano disponibili.",
    reader_response_limit: "La vista di lettura supera il limite della risposta. Il sorgente completo e il download restano disponibili.",
  };
  const upgradePhases = {
    queued: "Richiesta registrata", stopping: "Arresto del servizio",
    installing: "Backup e installazione in corso", restarting: "Verifica del riavvio",
    complete: "Aggiornamento completato", preflight_failed: "Controlli preliminari non superati",
    failed: "Aggiornamento interrotto",
  };
  const upgradeErrors = {
    dashboard_upgrade_password_required: "Inserisci la password dell’account locale.",
    dashboard_upgrade_password_denied: "La password dell’account locale non è stata accettata.",
    upgrade_version_invalid: "Inserisci una versione stabile nel formato X.Y.Z.",
    upgrade_version_not_newer: "Scegli una versione successiva a quella installata.",
    upgrade_asset_unavailable: "Gli asset della versione scelta non sono raggiungibili.",
    upgrade_already_pending: "Il servizio ha già un aggiornamento da completare o verificare.",
    upgrade_platform_unsupported: "L’aggiornamento automatico del servizio è disponibile su macOS.",
    upgrade_service_not_ready: "Avvia il servizio gestito e controlla di nuovo lo stato.",
    upgrade_preview_expired: "L’anteprima è scaduta. Verifica di nuovo la versione.",
    upgrade_selection_changed: "Il servizio o la configurazione sono cambiati. Verifica di nuovo la versione.",
    upgrade_dispatch_failed: "Flower non ha potuto avviare il processo di aggiornamento.",
    upgrade_worker_unconfirmed: "Flower non riesce a confermare che l’aggiornamento sia ancora in corso. Leggi la ricevuta con flower-mcp service upgrade-status usando lo stesso profilo e la stessa porta.",
  };
  const state = {
    ready: false, initializing: false, authBusy: false, authGeneration: 0, availability: "unavailable", retryUntil: 0, retryTimer: null, csrf: "", maintenance: { state: "ready" }, project: null,
    section: "overview", projectOffset: 0, sectionOffset: 0, projects: null, sectionData: null,
    createBusy: false, createUncertain: "", createIdEdited: false,
    settings: null, settingsBusy: false, settingsEpoch: 0,
    upgradeStatus: null, upgradePreview: null, upgradeBusy: false, upgradeReading: false, upgradeEpoch: 0, rememberedUpgrade: null,
    archive: null, archiveBusy: false, backupDeletion: null,
    loadingEpoch: 0, deletion: null, adminBusy: false, connectionWarning: false, rememberedIntent: null,
  };
  const $ = (id) => document.getElementById(id);

  function element(tag, className, text) {
    const item = document.createElement(tag);
    if (className) item.className = className;
    if (text !== undefined) item.textContent = String(text);
    return item;
  }

  function button(text, className, handler) {
    const item = element("button", `button ${className}`, text);
    item.type = "button";
    item.addEventListener("click", handler);
    return item;
  }

  function label(key) {
    if (String(key).endsWith("_bounds")) return `Limiti di ${label(String(key).slice(0, -7)).toLowerCase()}`;
    return labels[key] || String(key).replace(/_/g, " ").replace(/^./, (letter) => letter.toUpperCase());
  }

  function display(value) {
    if (value === null || value === undefined || value === "") return "Non disponibile";
    if (typeof value === "boolean") return value ? "Sì" : "No";
    return states[value] || String(value);
  }

  function observed(value, revision) {
    if (!value) return "";
    const date = new Date(value);
    const time = Number.isNaN(date.getTime()) ? value : date.toLocaleString("it-IT", { dateStyle: "short", timeStyle: "medium" });
    return `Osservato ${time}${revision === undefined ? "" : ` · evento requisiti ${revision}`}`;
  }

  function notice(message, error = false) {
    $("notice").textContent = message;
    $("notice").className = error ? "notice notice-error" : "notice";
    $("notice").hidden = !message;
  }

  function connection(available) {
    $("connection-dot").dataset.state = available ? "available" : "unavailable";
    $("connection-status").textContent = available ? "Flower locale collegato" : "Flower non raggiungibile";
  }

  function applyTheme(value) {
    const theme = ["light", "dark", "system"].includes(value) ? value : "system";
    if (theme === "system") delete document.documentElement.dataset.theme;
    else document.documentElement.dataset.theme = theme;
    $("theme-select").value = theme;
    try { localStorage.setItem("flower.dashboard.theme", theme); } catch (_) { /* The selected theme still works without storage. */ }
  }

  let initialTheme = "system";
  try { initialTheme = localStorage.getItem("flower.dashboard.theme") || "system"; } catch (_) { /* OS preference remains available. */ }
  applyTheme(initialTheme);
  $("theme-select").addEventListener("change", (event) => applyTheme(event.target.value));

  async function request(path, body, { timeoutMs = 15000, archive = false } = {}) {
    const generation = state.authGeneration;
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), timeoutMs);
    const options = { credentials: "same-origin", cache: "no-store", signal: controller.signal,
      headers: { Accept: archive ? "application/zip, application/json" : "application/json" } };
    if (body !== undefined) {
      options.method = "POST";
      options.headers["Content-Type"] = "application/json";
      if (state.csrf) options.headers["X-Flower-CSRF"] = state.csrf;
      options.body = JSON.stringify(body);
    }
    try {
      const response = await fetch(`/dashboard/api/${path}`, options);
      const isZip = archive && response.ok && response.headers.get("Content-Type")?.split(";", 1)[0].trim() === "application/zip";
      const payload = isZip ? await response.blob() : await response.json();
      connection(true);
      if (generation !== state.authGeneration && path !== "logout") {
        throw Object.assign(new Error(errorMessages.dashboard_session_changed), { reason: "dashboard_session_changed", stale: true });
      }
      if (isZip) return payload;
      const envelope = payload;
      if (!response.ok || envelope.status !== "success") {
        const retryAfter = Number(response.headers.get("Retry-After"));
        const message = response.status === 429 && retryAfter > 0 && retryAfter <= 60
          ? `Attendi ${Math.ceil(retryAfter)} secondi prima di riprovare.`
          : errorMessages[envelope.reason] || envelope.message || display(envelope.reason) || "La richiesta richiede attenzione.";
        const error = Object.assign(new Error(message), { reason: envelope.reason, status: response.status, retryAfter, envelope });
        if (path !== "auth" && path !== "login" && (response.status === 401 || envelope.reason === "dashboard_owner_changed")) {
          showLogin(error.message);
          try { applyAuth(await request("auth")); } catch (_) { /* The login panel retains the original failure. */ }
        }
        throw error;
      }
      if (archive) throw new Error("Flower non ha restituito il file ZIP richiesto.");
      if (["auth", "status", "login"].includes(path)) state.csrf = envelope.result.csrf_token;
      return envelope.result;
    } catch (error) {
      if (error.name === "AbortError") {
        connection(false);
        throw Object.assign(new Error("Flower non ha risposto in tempo. Controlla lo stato dell’operazione."), { reason: "response_timeout" });
      }
      if (error instanceof TypeError) {
        connection(false);
        throw Object.assign(new Error("Flower non è raggiungibile. Controlla che il processo locale sia attivo."), { reason: "connection_unavailable" });
      }
      throw error;
    } finally {
      clearTimeout(timeout);
    }
  }

  function loginMessage(text, information = false) {
    $("login-message").textContent = text || "";
    $("login-message").dataset.kind = information ? "information" : "error";
    $("login-message").hidden = !text;
  }

  function updateLoginControls() {
    const unavailable = state.availability !== "ready";
    $("login-username").disabled = unavailable || state.authBusy;
    $("login-password").disabled = unavailable || state.authBusy;
    $("login-button").disabled = unavailable || state.authBusy || state.initializing || Date.now() < state.retryUntil;
    $("login-button").textContent = state.authBusy ? "Verifica in corso…" : "Accedi";
    $("login-retry").disabled = state.authBusy || state.initializing;
    $("logout-button").disabled = state.authBusy;
    $("login-form").setAttribute("aria-busy", String(state.authBusy));
  }

  function applyAuth(auth) {
    state.csrf = auth.csrf_token;
    state.availability = auth.availability;
    const availability = $("login-availability");
    availability.hidden = auth.availability === "ready";
    availability.textContent = auth.reason === "pam_policy_missing"
      ? "Il login su Linux richiede la configurazione PAM di Flower. Segui la guida di configurazione per Linux, poi riprova."
      : errorMessages.dashboard_auth_unavailable;
    updateLoginControls();
  }

  function formMessage(id, message, error = false) {
    const node = $(id);
    node.textContent = message;
    node.dataset.error = String(error);
    node.hidden = !message;
  }

  const projectIdPattern = /^[a-z0-9][a-z0-9_-]{0,63}$/;
  const archiveTimeoutMs = 120000;

  function updateArchiveControls() {
    const disabled = state.archiveBusy || state.maintenance.state !== "ready";
    $("backup-create").disabled = disabled;
    $("backups-refresh").disabled = state.archiveBusy;
    $("export-open").disabled = disabled || !state.project;
    $("archive-download").disabled = disabled;
    $("backup-delete-submit").disabled = disabled || !$("backup-delete-password").value;
    $("backup-delete-password").readOnly = state.archiveBusy;
    $("backup-delete-close").disabled = state.archiveBusy;
    for (const item of $("backups-content").querySelectorAll("button[data-backup-action]")) item.disabled = disabled;
  }

  function openArchive(project) {
    if (!project || !state.ready || state.archiveBusy || state.maintenance.state !== "ready") return;
    const projectId = project.project_id;
    state.archive = { projectId };
    $("archive-scope").textContent = project.name === projectId ? projectId : `${project.name} (${projectId})`;
    $("archive-restore-guide").querySelector("details").open = false;
    formMessage("archive-message", "");
    $("archive-dialog").showModal();
  }

  function downloadBlob(blob, filename) {
    const link = element("a");
    const objectUrl = URL.createObjectURL(blob);
    link.href = objectUrl;
    link.download = filename;
    document.body.append(link);
    link.click();
    link.remove();
    setTimeout(() => URL.revokeObjectURL(objectUrl), 1000);
  }

  async function archiveTask(action) {
    if (!state.ready || state.authBusy || state.archiveBusy || state.maintenance.state !== "ready") return;
    state.archiveBusy = true;
    updateArchiveControls();
    try { await action(); }
    finally {
      state.archiveBusy = false;
      updateArchiveControls();
    }
  }

  function archiveError(error, changesBackups = false) {
    if (error.reason === "server_maintenance") return "Flower è in manutenzione. Riprova al termine.";
    if (error.reason === "dashboard_input_invalid") return "Flower non ha riconosciuto la richiesta. Aggiorna la vista e riprova.";
    if (changesBackups && (!error.status || error.status >= 500)) {
      return "L’esito non è confermato. Aggiorna l’elenco dei backup prima di riprovare.";
    }
    if (error.reason === "response_timeout") return "Il download ha richiesto troppo tempo. Riprova fra poco.";
    if (error instanceof SyntaxError) return "Flower non ha restituito il file ZIP richiesto.";
    return error.message;
  }

  function downloadArchive() {
    const selection = state.archive;
    const dialog = $("archive-dialog");
    if (!selection || !dialog.open) return;
    return archiveTask(async () => {
      formMessage("archive-message", "Preparazione dell’archivio in corso…");
      try {
        const blob = await request("archive", { project_id: selection.projectId }, { archive: true, timeoutMs: archiveTimeoutMs });
        if (state.authBusy || state.archive !== selection || !dialog.open) return;
        downloadBlob(blob, "flower-project.flower.zip");
        formMessage("archive-message", "Archivio pronto. Controlla i download del browser.");
      } catch (error) {
        if (state.archive === selection && dialog.open && !error.stale) formMessage("archive-message", archiveError(error), true);
      }
    });
  }

  function backupDate(backup) {
    const value = new Date(backup.created_at);
    return Number.isNaN(value.getTime()) ? "Data non disponibile" : value.toLocaleString("it-IT", { dateStyle: "short", timeStyle: "medium" });
  }

  function backupSize(bytes) {
    const units = ["B", "KiB", "MiB", "GiB"];
    let unit = 0;
    while (bytes >= 1024 && unit < units.length - 1) { bytes /= 1024; unit += 1; }
    return `${bytes.toLocaleString("it-IT", { maximumFractionDigits: 1 })} ${units[unit]}`;
  }

  async function loadBackups() {
    if ($("backups-view").hidden) return;
    const epoch = ++state.loadingEpoch;
    const content = $("backups-content");
    loading(content, "Lettura dei backup…");
    try {
      const result = await request("backups");
      if (epoch !== state.loadingEpoch) return;
      if (!result.backups.length) {
        content.replaceChildren(empty("Nessun backup conservato", "Usa Crea backup per salvare una copia del registro."));
        return;
      }
      const list = element("ul", "backup-list");
      for (const backup of result.backups) {
        const row = element("li", "backup-row");
        const identity = element("div", "backup-identity");
        const date = element("time", "", backupDate(backup));
        date.dateTime = backup.created_at;
        identity.id = `backup-${encodeURIComponent(backup.id)}`;
        identity.append(date, element("span", "muted identifier", backup.id));
        const actions = element("div", "project-actions");
        actions.append(button("Scarica", "button-secondary", () => downloadBackup(backup)),
          button("Elimina", "button-danger-quiet", () => openBackupDeletion(backup)));
        for (const item of actions.children) {
          item.dataset.backupAction = "true";
          item.setAttribute("aria-describedby", identity.id);
        }
        row.append(identity, element("span", "backup-size muted small", backupSize(backup.size)), actions);
        list.append(row);
      }
      content.replaceChildren(list);
      updateArchiveControls();
    } catch (error) {
      if (!error.stale && epoch === state.loadingEpoch && state.ready) content.replaceChildren(errorPanel(error, loadBackups));
    }
  }

  function createBackup() {
    return archiveTask(async () => {
      notice("Creazione del backup in corso…");
      try {
        await request("backups", {}, { timeoutMs: archiveTimeoutMs });
        notice("Backup creato. Puoi scaricarlo dall’elenco.");
        await loadBackups();
      } catch (error) {
        if (state.ready && !error.stale) notice(archiveError(error, true), true);
      }
    });
  }

  function downloadBackup(backup) {
    return archiveTask(async () => {
      notice("Preparazione del download in corso…");
      try {
        const blob = await request(`backups/${encodeURIComponent(backup.id)}/download`, {}, { archive: true, timeoutMs: archiveTimeoutMs });
        if (state.authBusy) return;
        downloadBlob(blob, "flower-backup.flower.zip");
        notice("Archivio pronto. Controlla i download del browser.");
      } catch (error) {
        if (state.ready && !error.stale) notice(archiveError(error), true);
      }
    });
  }

  function openBackupDeletion(backup) {
    if (!state.ready || state.archiveBusy || state.maintenance.state !== "ready") return;
    state.backupDeletion = backup;
    $("backup-delete-selection").textContent = `${backupDate(backup)} · ${backupSize(backup.size)} · ${backup.id}`;
    $("backup-delete-password").value = "";
    formMessage("backup-delete-message", "");
    updateArchiveControls();
    $("backup-delete-dialog").showModal();
  }

  function deleteBackup(event) {
    event.preventDefault();
    const selected = state.backupDeletion;
    const input = $("backup-delete-password");
    if (!selected || $("backup-delete-submit").disabled) return;
    return archiveTask(async () => {
      const password = input.value;
      input.value = "";
      formMessage("backup-delete-message", "Verifica e rimozione in corso…");
      try {
        const result = await request(`backups/${encodeURIComponent(selected.id)}/delete`, { password });
        if (result.deleted !== true) throw new Error("Eliminazione non confermata.");
        $("backup-delete-dialog").close();
        notice("Backup eliminato.");
        await loadBackups();
        if (state.ready && !$("backups-view").hidden) $("backups-title").focus();
      } catch (error) {
        if ($("backup-delete-dialog").open && !error.stale) {
          formMessage("backup-delete-message", archiveError(error, true), true);
          input.readOnly = false;
          input.focus();
        }
      }
    });
  }

  function updateCreateControls() {
    const waiting = state.createBusy || !!state.createUncertain;
    const available = state.maintenance.state === "ready";
    $("create-open").disabled = !available;
    $("create-name").readOnly = waiting;
    $("create-id").readOnly = waiting;
    $("create-submit").disabled = waiting || !available || !$("create-name").value.trim() ||
      !projectIdPattern.test($("create-id").value.trim());
    $("create-check").hidden = !state.createUncertain;
    $("create-check").disabled = state.createBusy || !available;
    $("create-close").disabled = state.createBusy;
  }

  function openCreateProject() {
    if (!state.createUncertain) {
      $("create-form").reset();
      state.createIdEdited = false;
      formMessage("create-message", "");
    }
    updateCreateControls();
    $("create-dialog").showModal();
  }

  async function createProject(event) {
    event.preventDefault();
    if ($("create-submit").disabled) return;
    const projectId = $("create-id").value.trim();
    const name = $("create-name").value.trim();
    state.createBusy = true;
    updateCreateControls();
    formMessage("create-message", "Creazione in corso…");
    try {
      const result = await request("projects", { project_id: projectId, name });
      $("create-dialog").close();
      navigate(result.project_id);
      notice("Progetto creato.");
    } catch (error) {
      if (error.stale || !state.ready) return;
      if (!error.status || error.status >= 500 && !["server_maintenance", "maintenance_requests_busy"].includes(error.reason)) {
        state.createUncertain = projectId;
        formMessage("create-message", "Controlla l’ID nel catalogo prima di riprovare.", true);
      } else {
        formMessage("create-message", error.message, true);
      }
    } finally {
      state.createBusy = false;
      updateCreateControls();
    }
  }

  async function checkCreatedProject() {
    if ($("create-check").disabled || !state.createUncertain) return;
    const projectId = state.createUncertain;
    state.createBusy = true;
    updateCreateControls();
    try {
      await request(`projects/${encodeURIComponent(projectId)}/sections/overview?limit=1`);
      state.createUncertain = "";
      $("create-dialog").close();
      navigate(projectId);
      notice("L’ID è presente nel catalogo.");
    } catch (error) {
      if (error.stale || !state.ready) return;
      if (error.reason === "dashboard_project_not_found") {
        state.createUncertain = "";
        formMessage("create-message", "Il progetto non è presente. Puoi riprovare.");
      } else {
        formMessage("create-message", error.message, true);
      }
    } finally {
      state.createBusy = false;
      updateCreateControls();
    }
  }

  const settingsGroups = {
    runtime: "Esecuzione", logging: "Log", model: "Modello",
    "providers.implementation_graph": "Provider del grafo di implementazione",
    "providers.bootstrap_behavior": "Provider del bootstrap",
    "providers.packet_evidence": "Provider delle evidenze",
    packet_provider: "Provider dei pacchetti", test_provider: "Provider dei test",
  };
  const settingLabels = {
    import_root: "Cartella di importazione", job_workers: "Worker concorrenti",
    backend: "Backend del modello", kind: "Tipo di provider", level: "Livello di log", enable_console: "Log in console", logs_path: "Cartella dei log",
    enabled: "Abilitato", model: "Nome del modello", base_url: "Endpoint del modello",
    context_length: "Lunghezza del contesto", api_key_env: "Variabile d’ambiente della chiave API",
    idle_timeout_sec: "Attesa di inattività (secondi)", verify_ssl: "Verifica certificato TLS",
    temperature: "Temperatura", reasoning: "Ragionamento", url: "Endpoint", endpoint: "Endpoint",
    tool: "Tool", invocation: "Tipo di invocazione", session_id: "ID sessione",
    domain: "Dominio", operation: "Operazione", mode: "Modalità", timeout_seconds: "Timeout (secondi)",
  };

  function showSettingsSection(section) {
    for (const name of ["basic", "advanced"]) {
      $(`settings-${name}`).setAttribute("aria-pressed", String(name === section));
      $(`settings-${name}-fields`).hidden = name !== section;
    }
  }

  function updateSettingsControls() {
    const available = state.maintenance.state === "ready";
    $("settings-refresh").disabled = state.settingsBusy || !available;
    $("settings-save").disabled = state.settingsBusy || !available;
    $("settings-discard").disabled = state.settingsBusy || !available;
    for (const input of $("settings-form").querySelectorAll("[data-setting]")) {
      input.disabled = state.settingsBusy || !available || input.dataset.readonly === "true";
    }
  }

  function renderSettings(snapshot) {
    state.settings = snapshot;
    const info = element("div", "summary-block settings-meta");
    const profileInfo = { "File del profilo": snapshot.config_path, "Ledger": snapshot.database_path,
      "Revisione del file": snapshot.revision.slice(0, 12) };
    if (snapshot.loaded_revision) profileInfo["Revisione caricata"] = snapshot.loaded_revision.slice(0, 12);
    info.append(fields(profileInfo));
    const draft = snapshot.draft;
    if (draft?.state === "pending") {
      info.append(element("p", "", "Bozza validata. Arresta Flower, usa il percorso indicato sopra nel comando e riavvia dopo l’applicazione."));
      info.append(element("pre", "", `flower-mcp settings apply --draft-id ${draft.id} --config "<file del profilo>"`));
    } else if (draft?.state === "stale") {
      info.append(element("p", "", "La bozza appartiene a una revisione precedente. Puoi scartarla o salvare una nuova bozza."));
    } else if (draft?.state === "applied") {
      info.append(element("p", "", "La bozza risulta applicata al profilo."));
    } else {
      info.append(element("p", "muted small", "Nessuna bozza salvata."));
    }
    $("settings-content").replaceChildren(info);

    for (const section of ["basic", "advanced"]) {
      const container = $(`settings-${section}-fields`);
      container.replaceChildren();
      const groups = new Map();
      for (const field of snapshot.fields.filter((item) => item.section === section)) {
        const parts = field.key.split(".");
        const key = parts.slice(0, -1).join(".");
        if (!groups.has(key)) {
          const fieldset = element("fieldset", "settings-group");
          const grid = element("div", "settings-grid");
          fieldset.append(element("legend", "", settingsGroups[key] || key), grid);
          groups.set(key, grid);
          container.append(fieldset);
        }
        const value = draft?.state === "pending" && Object.hasOwn(draft.changes, field.key)
          ? draft.changes[field.key] : field.value;
        const wrapper = element("div", "settings-field");
        const input = element(field.type === "select" ? "select" : "input");
        input.id = `setting-${field.key}`;
        input.dataset.setting = field.key;
        input.dataset.readonly = String(!!field.readonly);
        if (field.type === "select") {
          for (const option of field.options) {
            const choice = element("option", "", option);
            choice.value = option;
            input.append(choice);
          }
        } else if (field.type === "boolean") {
          input.type = "checkbox";
          input.checked = value === true;
        } else if (field.type === "number" || field.type === "integer") {
          input.type = "number";
          input.step = field.type === "integer" ? "1" : "any";
        } else {
          input.type = "text";
          input.autocomplete = "off";
          input.spellcheck = false;
        }
        if (field.type !== "boolean") input.value = value ?? "";
        if (field.readonly && value == null) input.placeholder = "Valore protetto";
        const title = element("label", "", settingLabels[parts.at(-1)] || parts.at(-1));
        title.htmlFor = input.id;
        wrapper.append(title, input);
        groups.get(key).append(wrapper);
      }
    }
    $("settings-discard").hidden = !draft || draft.state === "applied";
    $("settings-form").hidden = false;
    updateSettingsControls();
  }

  async function loadSettings() {
    if ($("settings-view").hidden || state.settingsBusy) return;
    const epoch = ++state.settingsEpoch;
    state.settings = null;
    $("settings-form").hidden = true;
    formMessage("settings-message", "");
    loading($("settings-content"), "Lettura del profilo…");
    try {
      const snapshot = await request("settings");
      if (epoch === state.settingsEpoch && !$("settings-view").hidden) renderSettings(snapshot);
    } catch (error) {
      if (!error.stale && epoch === state.settingsEpoch && !$("settings-view").hidden) {
        $("settings-content").replaceChildren(errorPanel(error, loadSettings));
      }
    }
  }

  async function saveSettings(discard = false) {
    if (!state.settings || state.settingsBusy || state.maintenance.state !== "ready") return;
    const snapshot = state.settings;
    const changes = {};
    if (!discard) {
      for (const field of snapshot.fields) {
        if (field.readonly) continue;
        const input = $(`setting-${field.key}`);
        let value = field.nullable && !input.value && !input.validity.badInput ? null : input.value;
        if (field.type === "boolean") value = input.checked;
        if (value !== null && (field.type === "number" || field.type === "integer")) {
          if (input.validity.badInput || input.validity.stepMismatch || !Number.isFinite(input.valueAsNumber)) {
            showSettingsSection(field.section);
            input.focus();
            formMessage("settings-message", "Inserisci un valore numerico valido.", true);
            return;
          }
          value = input.valueAsNumber;
        }
        if (value !== field.value) changes[field.key] = value;
      }
      if (!Object.keys(changes).length) {
        formMessage("settings-message", snapshot.draft?.state === "pending"
          ? "I valori corrispondono al profilo. Usa Scarta bozza per rimuovere le modifiche in attesa."
          : "I valori corrispondono al profilo salvato.");
        return;
      }
    }
    const epoch = state.settingsEpoch;
    state.settingsBusy = true;
    updateSettingsControls();
    formMessage("settings-message", discard ? "Rimozione in corso…" : "Validazione in corso…");
    try {
      const result = await request("settings/draft", { revision: snapshot.revision, draft_id: snapshot.draft?.id ?? null, changes });
      if (epoch === state.settingsEpoch && !$("settings-view").hidden) {
        renderSettings(result);
        formMessage("settings-message", discard ? "Bozza scartata." : "Bozza salvata.");
      }
    } catch (error) {
      if (!error.stale && epoch === state.settingsEpoch && !$("settings-view").hidden) {
        const message = !error.status ? "Rileggi il profilo per verificare se la bozza è stata salvata." : error.message;
        formMessage("settings-message", message, true);
      }
    } finally {
      state.settingsBusy = false;
      updateSettingsControls();
      if (state.ready && epoch !== state.settingsEpoch && !$("settings-view").hidden) loadSettings();
    }
  }

  const upgradeStorageKey = "flower.dashboard.upgrade";
  const terminalUpgradePhases = new Set(["complete", "preflight_failed", "failed"]);

  function rememberUpgrade(id) {
    state.rememberedUpgrade = id;
    try {
      if (id) sessionStorage.setItem(upgradeStorageKey, id);
      else sessionStorage.removeItem(upgradeStorageKey);
    } catch (_) { /* Flower also retains the operation receipt. */ }
  }

  function restoreUpgrade() {
    try {
      const saved = sessionStorage.getItem(upgradeStorageKey);
      if (saved && /^[A-Za-z0-9_-]{1,128}$/.test(saved)) state.rememberedUpgrade = saved;
    } catch (_) { /* Read the service receipt when browser storage is unavailable. */ }
  }

  function upgradeInProgress() {
    const operation = state.upgradeStatus?.operation;
    return Boolean(operation && !terminalUpgradePhases.has(operation.phase));
  }

  function canPreviewUpgrade() {
    return state.ready && state.maintenance.state === "ready" && state.upgradeStatus?.available === true
      && !state.upgradeBusy && !state.rememberedUpgrade && !upgradeInProgress();
  }

  function updateUpgradeControls() {
    const available = state.upgradeStatus?.available === true;
    const enabled = canPreviewUpgrade();
    $("upgrade-preview-form").hidden = !available;
    $("upgrade-version").disabled = !enabled;
    $("upgrade-preview-submit").disabled = !enabled;
    $("upgrade-open").disabled = !enabled;
    $("upgrade-refresh").disabled = state.upgradeBusy || state.upgradeReading;
    $("upgrade-preview").hidden = !state.upgradePreview || !available;
    $("upgrade-password").readOnly = state.upgradeBusy;
    $("upgrade-apply-submit").disabled = !enabled || !state.upgradePreview || !$("upgrade-password").value;
    $("upgrade-close").disabled = state.upgradeBusy;
  }

  function renderUpgradeStatus(snapshot) {
    const previous = state.upgradeStatus?.operation;
    state.upgradeStatus = snapshot;
    $("upgrade-installed").textContent = snapshot.installed_version ? `Versione installata ${snapshot.installed_version}` : "";
    $("upgrade-availability").textContent = snapshot.available === false
      ? upgradeErrors[snapshot.reason] || "L’aggiornamento automatico richiede un servizio Flower compatibile e un’installazione dedicata."
      : "";
    const receipt = $("upgrade-receipt");
    const operation = snapshot.operation;
    receipt.hidden = !operation;
    if (JSON.stringify(previous) !== JSON.stringify(operation)) {
      receipt.replaceChildren();
      if (operation) {
        receipt.append(element("p", "archive-scope", upgradePhases[operation.phase] || "Stato da verificare"));
        const versions = operation.previous_version ? `Da ${operation.previous_version} a ${operation.version}` : `Versione ${operation.version}`;
        receipt.append(element("p", "small", `${versions}. Operazione ${operation.id}.`));
        if (operation.backup_directory) {
          const backup = element("p", "small", "Backup ");
          backup.append(element("code", "", operation.backup_directory));
          receipt.append(backup);
        }
        if (operation.reason) {
          receipt.append(element("p", "small", upgradeErrors[operation.reason] || operation.reason));
        }
      }
    }
    if (!snapshot.available || upgradeInProgress()
        || (state.upgradePreview && state.upgradePreview.installed_version !== snapshot.installed_version)) {
      state.upgradePreview = null;
    }
    updateUpgradeControls();
  }

  async function loadUpgrade() {
    if (!state.ready || $("settings-view").hidden || state.upgradeBusy || state.upgradeReading) return;
    const epoch = state.upgradeEpoch;
    const expected = state.rememberedUpgrade;
    state.upgradeReading = true;
    updateUpgradeControls();
    try {
      const snapshot = await request("upgrade");
      if (epoch !== state.upgradeEpoch) return;
      if (expected && expected === state.rememberedUpgrade) {
        if (snapshot.operation?.id !== expected) {
          formMessage("upgrade-message", "Flower non riporta una ricevuta per questa richiesta. Verifica lo stato prima di un nuovo aggiornamento.", true);
          state.upgradePreview = null;
          rememberUpgrade(null);
        } else {
          formMessage("upgrade-message", "");
          if (terminalUpgradePhases.has(snapshot.operation.phase)) rememberUpgrade(null);
        }
      }
      renderUpgradeStatus(snapshot);
    } catch (error) {
      if (!error.stale && epoch === state.upgradeEpoch) {
        formMessage("upgrade-message", state.rememberedUpgrade
          ? "La ricevuta sarà disponibile al ritorno del servizio. Se il servizio resta fermo, usa flower-mcp service upgrade-status con lo stesso profilo e la stessa porta." : error.message, true);
      }
    } finally {
      state.upgradeReading = false;
      updateUpgradeControls();
    }
  }

  function changeUpgradeVersion() {
    state.upgradePreview = null;
    formMessage("upgrade-message", "");
    updateUpgradeControls();
  }

  async function previewUpgrade(event) {
    event.preventDefault();
    if (!canPreviewUpgrade()) return;
    changeUpgradeVersion();
    const version = $("upgrade-version").value.trim();
    if (!/^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$/.test(version)) {
      formMessage("upgrade-message", upgradeErrors.upgrade_version_invalid, true);
      return;
    }
    const epoch = ++state.upgradeEpoch;
    state.upgradeBusy = true;
    updateUpgradeControls();
    try {
      const preview = await request("upgrade/preview", { version });
      if (epoch !== state.upgradeEpoch) return;
      state.upgradePreview = preview;
      $("upgrade-preview-version").textContent = `Da ${preview.installed_version} a ${preview.version}`;
    } catch (error) {
      if (!error.stale && epoch === state.upgradeEpoch) {
        formMessage("upgrade-message", upgradeErrors[error.reason] || error.message, true);
      }
    } finally {
      state.upgradeBusy = false;
      updateUpgradeControls();
    }
  }

  function openUpgrade() {
    if (!canPreviewUpgrade() || !state.upgradePreview) return;
    $("upgrade-dialog-version").textContent = `Versione ${state.upgradePreview.version}`;
    $("upgrade-password").value = "";
    formMessage("upgrade-dialog-message", "");
    $("upgrade-dialog").showModal();
    $("upgrade-password").focus();
    updateUpgradeControls();
  }

  async function applyUpgrade(event) {
    event.preventDefault();
    if ($("upgrade-apply-submit").disabled) return;
    const { id } = state.upgradePreview;
    const input = $("upgrade-password");
    const password = input.value;
    input.value = "";
    const epoch = ++state.upgradeEpoch;
    state.upgradeBusy = true;
    rememberUpgrade(id);
    updateUpgradeControls();
    let refresh = false;
    try {
      const result = await request("upgrade/apply", { id, password });
      if (epoch !== state.upgradeEpoch) return;
      renderUpgradeStatus({ ...state.upgradeStatus, operation: result.operation });
      $("upgrade-dialog").close();
      state.upgradePreview = null;
      if (result.operation.phase === "preflight_failed") {
        rememberUpgrade(null);
        formMessage("upgrade-message", "Il servizio è ancora disponibile. Consulta la ricevuta prima di riprovare.", true);
      } else {
        formMessage("upgrade-message", "Richiesta registrata. Accedi di nuovo dopo il riavvio per vedere il risultato.");
      }
    } catch (error) {
      if (error.stale || epoch !== state.upgradeEpoch) return;
      const rejected = error.status >= 400 && error.status < 500 && error.status !== 401;
      if (rejected) {
        rememberUpgrade(null);
        formMessage("upgrade-dialog-message", upgradeErrors[error.reason] || error.message, true);
        if (error.status === 409) {
          state.upgradePreview = null;
          $("upgrade-dialog").close();
          formMessage("upgrade-message", upgradeErrors[error.reason] || error.message, true);
          refresh = true;
        }
      } else {
        $("upgrade-dialog").close();
        state.upgradePreview = null;
        formMessage("upgrade-message", "La conferma non è arrivata. Consulta lo stato prima di una nuova richiesta.", true);
      }
    } finally {
      state.upgradeBusy = false;
      updateUpgradeControls();
      if (state.rememberedUpgrade || refresh) loadUpgrade();
    }
  }

  function closePrivateDialogs() {
    if (state.deletion) rememberIntent();
    for (const name of ["create-dialog", "delete-dialog", "evidence-dialog", "archive-dialog", "backup-delete-dialog", "upgrade-dialog"]) {
      if ($(name).open) $(name).close();
    }
  }

  function showLogin(message) {
    const changed = state.ready || $("login-panel").hidden;
    closePrivateDialogs();
    if (changed) {
      state.authGeneration += 1;
      state.loadingEpoch += 1;
      state.csrf = "";
      state.project = null;
      state.projects = null;
      state.sectionData = null;
      state.archive = null;
      state.backupDeletion = null;
      $("backup-delete-password").value = "";
      state.createUncertain = "";
      $("create-form").reset();
      formMessage("create-message", "");
      state.settingsEpoch += 1;
      state.upgradeEpoch += 1;
      state.upgradePreview = null;
      $("upgrade-version").value = "";
      $("upgrade-password").value = "";
      formMessage("upgrade-message", "");
      renderUpgradeStatus({});
      state.settings = null;
      $("settings-form").hidden = true;
      for (const name of ["settings-content", "settings-basic-fields", "settings-advanced-fields"]) $(name).replaceChildren();
      formMessage("settings-message", "");
      state.deletion = null;
      state.maintenance = { state: "ready" };
      for (const name of ["catalog-content", "section-content", "evidence-content", "delete-content", "delete-actions", "section-navigation", "backups-content"]) $(name).replaceChildren();
      for (const name of ["sidebar-project-name", "sidebar-project-id", "project-title", "section-title", "section-observed", "catalog-count", "catalog-observed", "section-bounds", "archive-scope", "backup-delete-selection"]) $(name).textContent = "";
      formMessage("archive-message", "");
      formMessage("backup-delete-message", "");
      $("login-password").value = "";
      notice("");
    }
    state.ready = false;
    $("workspace").hidden = true;
    $("logout-button").hidden = true;
    $("maintenance-banner").hidden = true;
    $("login-panel").hidden = false;
    $("initial-loading").hidden = true;
    $("skip-link").href = "#login-panel";
    document.title = "Flower MCP · Accesso";
    if (message !== undefined) loginMessage(message);
    updateLoginControls();
  }

  function showWorkspace() {
    state.ready = true;
    $("login-panel").hidden = true;
    $("logout-button").hidden = false;
    $("workspace").hidden = false;
    $("initial-loading").hidden = true;
    $("skip-link").href = "#main-content";
    loginMessage("");
  }

  function route() {
    const parameters = new URLSearchParams(location.search);
    const projectId = parameters.get("project");
    const view = parameters.get("view");
    const settings = !projectId && view === "settings";
    const backups = !projectId && view === "backups";
    state.settingsEpoch += 1;
    $("settings-view").hidden = !settings;
    $("backups-view").hidden = !backups;
    $("settings-button").removeAttribute("aria-current");
    $("backups-button").removeAttribute("aria-current");
    if (settings || backups) {
      state.project = null;
      state.loadingEpoch += 1;
      $("catalog-view").hidden = true;
      $("project-view").hidden = true;
      $("project-navigation").hidden = true;
      $("home-button").removeAttribute("aria-current");
      $(settings ? "settings-button" : "backups-button").setAttribute("aria-current", "page");
      document.title = settings ? "Flower MCP · Impostazioni" : "Flower MCP · Backup";
      if (settings) {
        loadSettings();
        loadUpgrade();
      }
      else loadBackups();
      return;
    }
    state.section = Object.hasOwn(sections, view) ? view : "overview";
    state.sectionOffset = 0;
    state.sectionData = null;
    if (projectId) {
      state.project = { project_id: projectId, name: projectId };
      openProjectView();
      loadSection();
    } else {
      state.project = null;
      $("catalog-view").hidden = false;
      $("project-view").hidden = true;
      $("project-navigation").hidden = true;
      $("home-button").setAttribute("aria-current", "page");
      document.title = "Flower MCP · Progetti";
      loadProjects();
    }
    updateArchiveControls();
  }

  function navigate(projectId, section = "overview") {
    const url = new URL(location.href);
    url.search = "";
    if (projectId) {
      url.searchParams.set("project", projectId);
      url.searchParams.set("view", section);
    }
    if (!projectId && (section === "settings" || section === "backups")) url.searchParams.set("view", section);
    history.pushState(null, "", url);
    route();
  }

  function openProjectView() {
    $("catalog-view").hidden = true;
    $("project-view").hidden = false;
    $("project-navigation").hidden = false;
    $("home-button").removeAttribute("aria-current");
    $("project-identity").textContent = state.project.project_id;
    $("project-title").textContent = state.project.name;
    $("sidebar-project-name").textContent = state.project.name;
    $("sidebar-project-id").textContent = state.project.project_id;
    $("section-title").textContent = sections[state.section].label;
    $("project-subtitle").textContent = "Lo stato registrato del progetto, con i suoi riferimenti e le sue verifiche.";
    $("section-navigation").replaceChildren();
    for (const [key, section] of Object.entries(sections)) {
      const item = element("button", "", section.label);
      item.type = "button";
      if (key === state.section) item.setAttribute("aria-current", "page");
      item.addEventListener("click", () => navigate(state.project.project_id, key));
      $("section-navigation").append(item);
    }
  }

  function loading(container, text) {
    const item = element("div", "loading-panel");
    item.append(element("span", "loader"), element("span", "", text));
    container.replaceChildren(item);
  }

  function errorPanel(error, retry) {
    const panel = element("div", "error-panel");
    panel.append(element("h3", "", "La vista richiede attenzione"), element("p", "", error.message));
    if (error.reason) panel.append(element("span", "error-code", error.reason));
    if (retry) panel.append(button("Riprova lettura", "button-secondary", retry));
    return panel;
  }

  function empty(title, text) {
    const panel = element("div", "empty-state");
    panel.append(element("span", "empty-mark"), element("h3", "", title), element("p", "", text));
    return panel;
  }

  async function loadProjects() {
    const epoch = ++state.loadingEpoch;
    loading($("catalog-content"), "Lettura dei progetti…");
    try {
      const parameters = new URLSearchParams({ search: $("project-search").value, offset: state.projectOffset, limit: 25 });
      const result = await request(`projects?${parameters}`);
      if (epoch !== state.loadingEpoch) return;
      state.projects = result;
      $("catalog-content").replaceChildren();
      $("catalog-count").textContent = `${result.total} ${result.total === 1 ? "progetto" : "progetti"}`;
      $("catalog-observed").textContent = observed(result.observed_at);
      $("projects-previous").disabled = !result.offset;
      $("projects-next").disabled = result.next_offset === null || result.next_offset === undefined;
      if (!result.projects.length) {
        $("catalog-content").append(empty($("project-search").value ? "Nessun progetto corrispondente" : "Questo profilo è pronto per il primo progetto",
          $("project-search").value ? "Prova un altro nome o ID." : "Usa Nuovo progetto per iniziare."));
        return;
      }
      const table = element("table", "project-table");
      const heading = element("tr");
      for (const [title, className] of [["Progetto", ""], ["Creato", "created-column"], ["Evento requisiti", "revision-column"], ["Azioni", "table-action"]]) {
        const cell = element("th", className, title);
        cell.scope = "col";
        heading.append(cell);
      }
      const head = element("thead");
      head.append(heading);
      const body = element("tbody");
      for (const project of result.projects) {
        const row = element("tr");
        const titleCell = element("td");
        const title = element("button", "project-name-button", project.name);
        title.type = "button";
        title.addEventListener("click", () => navigate(project.project_id));
        titleCell.append(title, element("span", "project-row-id identifier", project.project_id));
        const date = new Date(project.created_at);
        const created = Number.isNaN(date.getTime()) ? display(project.created_at) : date.toLocaleDateString("it-IT");
        row.append(titleCell, element("td", "created-column muted", created), element("td", "revision-column muted", project.source_ledger_version));
        const actions = element("td", "table-action");
        const remove = element("button", "button button-quiet", "Elimina");
        remove.type = "button";
        remove.setAttribute("aria-label", `Elimina il progetto ${project.name}`);
        remove.addEventListener("click", () => openDeletion(project));
        actions.append(remove);
        row.append(actions);
        body.append(row);
      }
      table.append(head, body);
      $("catalog-content").append(table);
    } catch (error) {
      if (epoch === state.loadingEpoch && state.ready) $("catalog-content").replaceChildren(errorPanel(error, loadProjects));
    }
  }

  function badge(value) {
    const kind = String(value || "unknown");
    let tone = "";
    if (["complete", "completed", "implemented", "passed", "success", "accepted", "scrubbed"].includes(kind)) tone = "badge-positive";
    if (["pending", "partial", "open", "draft", "stale", "unknown", "needs_oracle", "maintenance", "recovery_required"].includes(kind)) tone = "badge-warning";
    if (["blocked", "failed", "rejected", "removed"].includes(kind)) tone = "badge-danger";
    if (["ready", "current", "closed", "running", "constructible"].includes(kind)) tone = "badge-accent";
    return element("span", `badge ${tone}`, display(kind));
  }

  function appendValue(container, value, depth = 0) {
    if (value === null || typeof value !== "object") {
      container.append(element("span", "", display(value)));
      return;
    }
    if (depth > 5) {
      container.append(element("span", "muted", "Apri il riferimento specifico per i dettagli successivi."));
      return;
    }
    if (Array.isArray(value)) {
      if (!value.length) { container.append(element("span", "muted", "Nessun elemento registrato")); return; }
      const list = element("ul", "value-list");
      for (const [index, item] of value.slice(0, 30).entries()) {
        const entry = element("li");
        if (item && typeof item === "object" && !Array.isArray(item)) {
          const details = element("details", "nested-detail");
          details.append(element("summary", "", itemTitle(item, index)));
          details.append(fields(item, depth + 1));
          entry.append(details);
        } else appendValue(entry, item, depth + 1);
        list.append(entry);
      }
      container.append(list);
      if (value.length > 30) container.append(element("p", "truncation-note", `Mostrati 30 dei ${value.length} elementi ricevuti.`));
      return;
    }
    container.append(fields(value, depth + 1));
  }

  function fields(value, depth = 0) {
    const list = element("dl", "detail-fields");
    const entries = Object.entries(value).filter(([, item]) => item !== undefined);
    for (const [key, item] of entries.slice(0, 45)) {
      const row = element("div", "detail-field");
      const description = element("dd");
      appendValue(description, item, depth);
      row.append(element("dt", "", label(key)), description);
      list.append(row);
    }
    if (entries.length > 45) list.append(element("p", "truncation-note", "Questa vista mostra i primi 45 campi ricevuti."));
    return list;
  }

  function itemTitle(item, index) {
    return item.title || item.name || item.entity?.name || item.entity?.statement || item.entity?.id || item.packet?.title || item.milestone?.name ||
      item.statement || item.prompt || item.reference || item.unit_key || item.oracle_id || item.campaign_id || item.case_id || item.question_id ||
      item.requirement_id || item.handover_id || item.artifact_kind || item.reason || item.code || item.kind || `Elemento ${index + 1}`;
  }

  function itemState(item) {
    return item.status || item.state || item.packet?.status || item.lifecycle_status || item.qualification;
  }

  function renderItem(item, index) {
    if (!item || typeof item !== "object") {
      const simple = element("div", "summary-block");
      appendValue(simple, item);
      return simple;
    }
    const details = element("details", "item");
    const heading = element("summary", "item-summary");
    const main = element("div", "item-main");
    if (state.section === "architecture" && item.kind) main.append(element("span", "item-kind", label(item.kind)));
    main.append(element("div", "item-title", itemTitle(item, index)));
    const identity = item.packet_id || item.milestone_id || item.campaign_id || item.oracle_id || item.requirement_id || item.handover_id || item.evidence_id;
    if (identity && identity !== itemTitle(item, index)) main.append(element("div", "item-caption identifier", identity));
    heading.append(main);
    const status = itemState(item);
    if (typeof status === "string") heading.append(badge(status));
    const dimensions = element("div", "dimension-line");
    for (const [key, title] of [["reported_units", "Unità dichiarate"], ["implementation", "Implementazione"], ["local_verification", "Verifica locale"]]) {
      const value = item[key];
      if (value && typeof value.completed === "number" && typeof value.total === "number") {
        const dimension = element("span", "", title);
        let result = `${value.completed}/${value.total}`;
        if (value.total === 0) result = key === "reported_units" ? "Nessuna unità" : "Nessun criterio";
        dimension.append(element("strong", "", result));
        dimensions.append(dimension);
      }
    }
    if (dimensions.childElementCount) main.append(dimensions);
    const body = element("div", "item-body");
    body.append(fields(item));
    const retained = evidenceAddress(item);
    if (retained) body.append(button("Apri contenuto conservato", "button-secondary evidence-action", () => loadEvidence(retained)));
    details.append(heading, body);
    return details;
  }

  function evidenceAddress(item) {
    if (state.section !== "evidence") return null;
    if (item.kind && item.identity !== undefined) return { kind: item.kind, identity: item.identity };
    if (item.evidence_id !== undefined) return { kind: "verification", identity: item.evidence_id };
    if (item.handover_id) return { kind: "handover", identity: item.handover_id };
    if (item.generation_id !== undefined) return { kind: "artifact", identity: item.generation_id };
    return null;
  }

  function markdownLink(href) {
    if (typeof href !== "string" || href.length > 2048 || /[\u0000-\u001f\u007f]/.test(href)) throw new Error("reader_link_invalid");
    if (href.startsWith("#")) {
      if (!markdownHeadingId.test(href.slice(1))) throw new Error("reader_anchor_invalid");
      return { local: true, href };
    }
    const parsed = new URL(href);
    if (!["http:", "https:"].includes(parsed.protocol) || !parsed.hostname) throw new Error("reader_link_invalid");
    return { local: false, href: parsed.href };
  }

  function focusMarkdownHeading(target) {
    target.tabIndex = -1;
    const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    target.scrollIntoView({ behavior: reducedMotion ? "auto" : "smooth", block: "start" });
    target.focus({ preventScroll: true });
  }

  function buildMarkdownReader(reader) {
    if (reader.contract_version !== "flow.dashboard.markdown.v1" || reader.status !== "ready" ||
        !Array.isArray(reader.nodes) || !Array.isArray(reader.outline)) throw new Error("reader_contract_invalid");
    const headings = new Map();
    const anchorTargets = [];
    let nodeCount = 0;

    function renderNode(value, depth) {
      nodeCount += 1;
      if (nodeCount > 25000 || depth > 64 || !value || typeof value !== "object" || Array.isArray(value)) throw new Error("reader_node_invalid");
      const keys = Object.keys(value);
      if (keys.length === 1 && keys[0] === "text" && typeof value.text === "string") return document.createTextNode(value.text);
      if (!markdownTags.has(value.tag) || !Array.isArray(value.children) ||
          keys.some((key) => !["tag", "children", "id", "href", "start", "align"].includes(key))) throw new Error("reader_node_invalid");
      const item = element(value.tag);
      if (value.id !== undefined) {
        if (!/^h[1-6]$/.test(value.tag) || typeof value.id !== "string" || value.id.length > 40 || !markdownHeadingId.test(value.id) ||
            headings.has(value.id)) throw new Error("reader_heading_invalid");
        item.id = value.id;
        headings.set(value.id, item);
      }
      if (value.start !== undefined) {
        if (value.tag !== "ol" || !Number.isInteger(value.start) || value.start < 0 || value.start > 999999999) throw new Error("reader_list_invalid");
        item.start = value.start;
      }
      if (value.align !== undefined) {
        if (!["th", "td"].includes(value.tag) || !["left", "center", "right"].includes(value.align)) throw new Error("reader_alignment_invalid");
        item.className = `markdown-align-${value.align}`;
      }
      if (value.href !== undefined) {
        if (value.tag !== "a") throw new Error("reader_link_invalid");
        const link = markdownLink(value.href);
        item.href = link.href;
        if (link.local) {
          const targetId = link.href.slice(1);
          anchorTargets.push(targetId);
          item.addEventListener("click", (event) => { event.preventDefault(); focusMarkdownHeading(headings.get(targetId)); });
        } else {
          item.target = "_blank";
          item.rel = "noopener noreferrer";
        }
      }
      for (const child of value.children) item.append(renderNode(child, depth + 1));
      if (value.tag === "table") {
        const scrolling = element("div", "markdown-table-scroll");
        scrolling.tabIndex = 0;
        scrolling.setAttribute("aria-label", "Tabella del documento, scorrimento orizzontale disponibile");
        scrolling.append(item);
        return scrolling;
      }
      return item;
    }

    const article = element("article", "markdown-document");
    for (const value of reader.nodes) article.append(renderNode(value, 0));
    if (anchorTargets.some((id) => !headings.has(id))) throw new Error("reader_anchor_missing");
    const layout = element("div", "markdown-layout");
    if (reader.outline.length) {
      if (reader.outline.length > headings.size) throw new Error("reader_outline_invalid");
      const outline = element("details", "markdown-outline");
      outline.open = true;
      outline.append(element("summary", "", "Nel documento"));
      const navigation = element("nav");
      navigation.setAttribute("aria-label", "Indice del documento");
      const list = element("ol");
      const outlineIds = new Set();
      for (const entry of reader.outline) {
        if (!entry || typeof entry.id !== "string" || !headings.has(entry.id) || typeof entry.text !== "string" ||
            outlineIds.has(entry.id) || !Number.isInteger(entry.level) || entry.level < 1 || entry.level > 6 ||
            headings.get(entry.id).tagName !== `H${entry.level}`) throw new Error("reader_outline_invalid");
        outlineIds.add(entry.id);
        const row = element("li", `markdown-outline-level-${entry.level}`);
        const link = element("a", "", entry.text);
        link.href = `#${entry.id}`;
        link.addEventListener("click", (event) => { event.preventDefault(); focusMarkdownHeading(headings.get(entry.id)); });
        row.append(link);
        list.append(row);
      }
      navigation.append(list);
      outline.append(navigation);
      layout.append(outline);
      layout.classList.add("markdown-layout-with-outline");
    }
    layout.append(article);
    return layout;
  }

  function evidenceDocument(result) {
    if (result.content_type !== "text/markdown") return element("div", "evidence-content", result.content);
    const container = element("div", "markdown-reader");
    const toolbar = element("div", "markdown-toolbar");
    const modes = element("div", "markdown-mode-control");
    modes.setAttribute("role", "group");
    modes.setAttribute("aria-label", "Modalità del documento");
    const source = element("pre", "markdown-source");
    source.append(element("code", "", result.content));
    let reading = null;
    let limitation = "";
    if (result.reader?.status === "ready") {
      try { reading = buildMarkdownReader(result.reader); }
      catch (_) { limitation = "La proiezione di lettura non è compatibile. Il sorgente completo e il download restano disponibili."; }
    } else if (result.reader?.status === "limited") {
      limitation = markdownLimits[result.reader.reason] || "La vista di lettura ha raggiunto un limite di presentazione. Il sorgente completo e il download restano disponibili.";
    } else {
      limitation = "Per questo documento non è stata fornita una proiezione di lettura. Il sorgente completo e il download restano disponibili.";
    }
    const readingButton = button("Lettura", "", () => selectMode(true));
    const sourceButton = button("Sorgente", "", () => selectMode(false));
    readingButton.disabled = !reading;
    modes.append(readingButton, sourceButton);
    toolbar.append(modes);
    container.append(toolbar);
    if (limitation) container.append(element("p", "markdown-limit", limitation));
    if (reading) container.append(reading);
    container.append(source);

    function selectMode(useReader) {
      if (reading) reading.hidden = !useReader;
      source.hidden = useReader;
      readingButton.setAttribute("aria-pressed", String(useReader));
      sourceButton.setAttribute("aria-pressed", String(!useReader));
    }

    selectMode(Boolean(reading));
    return container;
  }

  async function loadEvidence(address) {
    $("evidence-title").textContent = "Dettaglio";
    loading($("evidence-content"), "Lettura dell’evidenza…");
    if (!$("evidence-dialog").open) $("evidence-dialog").showModal();
    try {
      const result = await request(`projects/${encodeURIComponent(state.project.project_id)}/evidence/${encodeURIComponent(address.kind)}/${encodeURIComponent(address.identity)}`);
      $("evidence-title").textContent = display(result.title || result.artifact_kind || result.handover_id || result.evidence_id || "Contenuto conservato");
      $("evidence-content").replaceChildren();
      if (typeof result.content === "string") {
        $("evidence-content").append(evidenceDocument(result));
        $("evidence-content").append(button("Scarica documento", "button-secondary evidence-action", () => {
          const extension = result.content_type === "text/markdown" ? "md" : "json";
          downloadBlob(new Blob([result.content], { type: result.content_type || "text/plain" }),
            `flower-${address.kind}-${String(address.identity).replace(/[^A-Za-z0-9_-]/g, "_")}.${extension}`);
        }));
      } else $("evidence-content").append(fields(result));
    } catch (error) {
      if (!state.ready || error.stale) return;
      $("evidence-content").replaceChildren(errorPanel(error, () => loadEvidence(address)));
    }
  }

  function renderSection(result) {
    const container = $("section-content");
    container.replaceChildren(element("p", "section-intro", sections[state.section].description));
    const summary = result.summary || {};
    if (state.section === "overview" && summary.next_gate) {
      const attention = element("section", "attention");
      attention.append(element("h3", "", "Prossimo punto di controllo"));
      const gate = summary.next_gate;
      const explanation = gate.message || gate.resolution || gate.reason || gate.operation || "Apri il dettaglio del punto di controllo.";
      attention.append(element("p", "", display(explanation)));
      const detail = element("details", "nested-detail");
      detail.append(element("summary", "", "Vedi obbligo e riferimenti"), fields(gate));
      attention.append(detail);
      container.append(attention);
    }
    if (Object.keys(summary).length) {
      const block = element("details", "summary-block");
      block.append(element("summary", "summary-disclosure", "Contesto e stato registrato"), fields(summary));
      container.append(block);
    }
    if (["roadmap", "packets", "verification"].includes(state.section)) {
      container.append(element("p", "state-note", "Il completamento riportato, le verifiche e l’accettazione descrivono aspetti distinti."));
    }
    if (result.items?.length) {
      const list = element("div", state.section === "roadmap" ? "item-list roadmap" : "item-list");
      result.items.forEach((item, index) => list.append(renderItem(item, index)));
      container.append(list);
    } else if (!Object.keys(summary).length) {
      container.append(empty("Nessun elemento registrato in questa sezione", "La vista si popolerà quando Flower avrà registrato le relative autorità o evidenze."));
    }
    const bounds = result.bounds || {};
    const count = result.items?.length || 0;
    const shown = count === 1 ? "elemento mostrato" : "elementi mostrati";
    $("section-bounds").textContent = bounds.total === undefined ? "" : `${count} ${shown} su ${bounds.total}${bounds.truncated ? " · vista parziale" : ""}`;
    $("section-previous").disabled = !bounds.offset;
    $("section-next").disabled = bounds.next_offset === null || bounds.next_offset === undefined;
    $("section-observed").textContent = observed(result.observed_at, result.source_ledger_version);
  }

  async function loadSection() {
    if (!state.project) return;
    const epoch = ++state.loadingEpoch;
    const projectId = state.project.project_id;
    const section = state.section;
    loading($("section-content"), "Lettura dello stato registrato…");
    try {
      const result = await request(`projects/${encodeURIComponent(projectId)}/sections/${section}?offset=${state.sectionOffset}&limit=25`);
      if (epoch !== state.loadingEpoch) return;
      state.sectionData = result;
      state.project = result.project || state.project;
      openProjectView();
      document.title = `${state.project.name} · Flower MCP`;
      renderSection(result);
    } catch (error) {
      if (epoch === state.loadingEpoch && state.ready) $("section-content").replaceChildren(errorPanel(error, loadSection));
    }
  }

  function updateMaintenance(maintenance) {
    state.maintenance = maintenance || { state: "ready" };
    updateCreateControls();
    updateSettingsControls();
    updateArchiveControls();
    updateUpgradeControls();
    const banner = $("maintenance-banner");
    banner.replaceChildren();
    banner.hidden = state.maintenance.state === "ready" && !state.rememberedIntent;
    if (banner.hidden) return;
    if (state.maintenance.state === "ready") {
      banner.append(element("span", "", "È conservato il riferimento a una precedente gestione del progetto."));
      banner.append(button("Apri stato dell’operazione", "button-secondary", () => {
        const saved = state.rememberedIntent;
        state.deletion = { project: saved.project, deletion_id: saved.deletion_id, result: null,
          error: "", confirm: "", hostRef: "", stoppedRuns: "", unknown: true };
        showDeleteDialog();
      }));
      return;
    }
    const text = state.maintenance.state === "recovery_required"
      ? "Flower richiede il recupero di un’eliminazione. Le operazioni sui progetti restano sospese."
      : "Flower è in manutenzione per la gestione di un progetto. Le chat possono riprovare al termine.";
    banner.append(element("span", "", text));
    if (state.maintenance.project_id && state.maintenance.deletion_id) {
      banner.append(button("Apri stato e recupero", "button-secondary", () => {
        state.deletion = { project: { project_id: state.maintenance.project_id, name: state.maintenance.project_id },
          deletion_id: state.maintenance.deletion_id, result: state.maintenance.result?.deletion || null, error: "", confirm: "", hostRef: "", stoppedRuns: "" };
        showDeleteDialog();
        adminAction("inspect");
      }));
    }
  }

  async function checkMaintenance() {
    if (document.visibilityState !== "visible" || state.adminBusy || state.authBusy) return;
    if (!state.ready) { await startDashboard(); return; }
    try {
      const result = await request("status");
      updateMaintenance(result.maintenance || result);
      if (state.upgradeStatus?.operation?.reason !== "upgrade_worker_unconfirmed"
          && (state.rememberedUpgrade || upgradeInProgress())) loadUpgrade();
      if (state.connectionWarning) { notice(""); state.connectionWarning = false; }
    } catch (error) {
      notice(error.message, true);
      state.connectionWarning = true;
    }
  }

  function rememberIntent() {
    if (!state.deletion) return;
    state.rememberedIntent = { project: { project_id: state.deletion.project.project_id, name: state.deletion.project.project_id }, deletion_id: state.deletion.deletion_id,
      prepared_fingerprint: state.deletion.result?.prepared_fingerprint };
    try {
      sessionStorage.setItem("flower.dashboard.deletion", JSON.stringify(state.rememberedIntent));
    } catch (_) { /* The running server also retains the maintenance intent. */ }
  }

  function forgetIntent() {
    state.rememberedIntent = null;
    try { sessionStorage.removeItem("flower.dashboard.deletion"); } catch (_) { /* No browser state is required to retain the server journal. */ }
    updateMaintenance(state.maintenance);
  }

  function restoreIntent() {
    try {
      const saved = JSON.parse(sessionStorage.getItem("flower.dashboard.deletion") || "null");
      if (saved && typeof saved.deletion_id === "string" && saved.deletion_id.length <= 64 &&
          typeof saved.project?.project_id === "string" && saved.project.project_id.length <= 128) {
        state.rememberedIntent = { project: { project_id: saved.project.project_id, name: saved.project.project_id }, deletion_id: saved.deletion_id,
          prepared_fingerprint: saved.prepared_fingerprint };
      }
    } catch (_) { /* Server status remains the authority when local UI state is unavailable. */ }
  }

  function openDeletion(project) {
    notice("");
    if (state.maintenance.state !== "ready" && state.maintenance.deletion_id) {
      state.deletion = { project: { project_id: state.maintenance.project_id, name: state.maintenance.project_id },
        deletion_id: state.maintenance.deletion_id, result: null, error: "", confirm: "", hostRef: "", stoppedRuns: "" };
      showDeleteDialog();
      adminAction("inspect");
      return;
    }
    state.deletion = { project, deletion_id: crypto.randomUUID(), result: null, error: "", confirm: "", hostRef: "", stoppedRuns: "" };
    showDeleteDialog();
  }

  function showDeleteDialog() {
    renderDeletion();
    if (!$("delete-dialog").open) $("delete-dialog").showModal();
  }

  function deleteField(id, title, value, description, handler, type = "text") {
    const field = element("div", "delete-form-field");
    const labelElement = element("label", "", title);
    labelElement.htmlFor = id;
    const input = element("input");
    input.id = id;
    input.type = type;
    input.autocomplete = "off";
    input.spellcheck = false;
    input.maxLength = type === "password" ? 8192 : id === "host-stop-reference" ? 256 : 2048;
    input.value = value || "";
    input.addEventListener("input", (event) => handler(event.target.value));
    field.append(labelElement, input);
    if (description) field.append(element("small", "", description));
    return field;
  }

  function renderDeletion() {
    const deletion = state.deletion;
    if (!deletion) return;
    const content = $("delete-content");
    const actions = $("delete-actions");
    content.replaceChildren();
    actions.replaceChildren();
    $("delete-close").disabled = state.adminBusy;
    content.append(element("div", "delete-project-name", deletion.project.name), element("span", "delete-project-id identifier", deletion.project.project_id));
    const result = deletion.result;
    const stage = result?.deletion_state;
    if (state.adminBusy) {
      const progress = element("div", "loading-panel");
      progress.append(element("span", "loader"), element("span", "", "Operazione in corso. Mantieni questa finestra aperta."));
      content.append(progress);
      return;
    }
    if (deletion.error) content.append(errorPanel({ message: deletion.error, reason: deletion.reason }));
    if (stage === "scrubbed" || stage === "acknowledged") {
      content.append(element("div", "dialog-notice dialog-success", "I dati del progetto in Flower sono stati eliminati e la pulizia è verificata."));
      content.append(element("p", "delete-explanation", "File del repository, backup e chat dell’host restano nel rispettivo ambiente. Il journal di recupero conserva lo stato dell’operazione."));
      actions.append(button("Torna ai progetti", "button-primary", () => { $("delete-dialog").close(); state.deletion = null; forgetIntent(); navigate(null); }));
      return;
    }
    const recovering = ["deleting", "ledger_deleted", "unknown"].includes(stage) || deletion.unknown || state.maintenance.state === "recovery_required";
    if (recovering) {
      const explanation = state.maintenance.state === "ready"
        ? "L’esito richiede una verifica. Ispeziona l’intento originale prima di continuare."
        : "L’esito richiede una verifica. Flower mantiene la manutenzione finché il recupero è completato.";
      content.append(element("div", "dialog-notice", explanation));
      if (stage) content.append(badge(stage));
      if (result) content.append(fields(result));
      actions.append(button("Ispeziona stato", "button-secondary", () => adminAction("inspect")), button("Riconcilia operazione", "button-primary", () => adminAction("reconcile")));
      return;
    }
    content.append(element("p", "delete-explanation", "La preparazione mette in manutenzione questa istanza di Flower. Mostrerà i dati coinvolti e gli eventuali blocchi prima della conferma finale."));
    if (!result) {
      content.append(element("div", "dialog-notice", "Durante la manutenzione le operazioni di tutte le chat collegate a questa istanza saranno sospese."));
      actions.append(button("Indietro", "button-secondary", () => $("delete-dialog").close()), button("Prepara eliminazione", "button-danger-quiet", () => adminAction("prepare")));
      return;
    }
    const counts = Object.entries(result.counts || {}).filter(([, value]) => typeof value === "number" && value > 0);
    if (counts.length) {
      content.append(element("h3", "", "Inventario del progetto"));
      const box = element("div", "inventory");
      const table = element("table");
      const heading = element("tr");
      heading.append(element("th", "", "Categoria"), element("th", "", "Record"));
      const head = element("thead"); head.append(heading); table.append(head);
      const body = element("tbody");
      for (const [key, count] of counts) { const row = element("tr"); row.append(element("td", "", label(key)), element("td", "", count)); body.append(row); }
      table.append(body); box.append(table); content.append(box);
    }
    if (result.blockers?.length) {
      const warning = element("div", "dialog-notice");
      warning.append(element("h3", "", "L’eliminazione è bloccata"));
      appendValue(warning, result.blockers);
      content.append(warning);
    }
    if (result.diagnostics?.length) {
      const diagnostics = element("details", "nested-detail");
      diagnostics.append(element("summary", "", "Diagnostica dell’operazione"));
      appendValue(diagnostics, result.diagnostics);
      content.append(diagnostics);
    }
    const identity = element("details", "nested-detail");
    identity.append(element("summary", "", "Riferimento della preparazione"), fields({ deletion_id: deletion.deletion_id, prepared_fingerprint: result.prepared_fingerprint }));
    content.append(identity);
    const canConfirm = stage === "prepared" && !result.blockers?.length && result.prepared_fingerprint;
    if (canConfirm) {
      content.append(deleteField("confirm-project", "Riscrivi l’ID del progetto", deletion.confirm, deletion.project.project_id,
        (value) => { deletion.confirm = value; updateDeleteButton(); }));
      content.append(deleteField("host-stop-reference", "Riferimento di arresto dell’host", deletion.hostRef,
        "Indica il riferimento effettivo alla verifica dei worker o delle sessioni che possiedi.",
        (value) => { deletion.hostRef = value; updateDeleteButton(); }));
      content.append(deleteField("host-stopped-runs", "Run dell’host arrestati, se presenti", deletion.stoppedRuns,
        "ID esatti separati da virgola. Compila soltanto per esecuzioni realmente arrestate dal tuo host.",
        (value) => { deletion.stoppedRuns = value; }));
      content.append(deleteField("delete-password", "Password dell’account locale", "",
        "Conferma l’eliminazione con la password usata per accedere a Flower.", updateDeleteButton, "password"));
    }
    actions.append(button("Annulla e riprendi Flower", "button-secondary", () => adminAction("cancel")), button("Ispeziona stato", "button-quiet", () => adminAction("inspect")));
    if (canConfirm) {
      const confirm = button("Elimina progetto", "button-danger", () => adminAction("delete"));
      confirm.id = "confirm-delete-button";
      actions.append(confirm);
      updateDeleteButton();
    }
  }

  function updateDeleteButton() {
    const confirm = $("confirm-delete-button");
    if (confirm) confirm.disabled = state.deletion.confirm !== state.deletion.project.project_id ||
      !state.deletion.hostRef.trim() || !$("delete-password").value;
  }

  async function adminAction(operation) {
    if (!state.deletion || state.adminBusy) return;
    notice("");
    const deletion = state.deletion;
    const body = { deletion_id: deletion.deletion_id };
    if (operation === "delete") {
      const password = $("delete-password");
      if (!password?.value) return;
      body.password = password.value;
      password.value = "";
      body.expected_fingerprint = deletion.result.prepared_fingerprint;
      body.confirm_project_id = deletion.confirm;
      body.host_quiescence_ref = deletion.hostRef.trim();
      body.host_stopped_run_ids = deletion.stoppedRuns.split(",").map((item) => item.trim()).filter(Boolean);
    }
    if (operation === "reconcile" && deletion.result?.prepared_fingerprint) body.expected_fingerprint = deletion.result.prepared_fingerprint;
    state.adminBusy = true;
    deletion.error = "";
    rememberIntent();
    renderDeletion();
    try {
      // Final deletion adds the native verifier budget to the ordinary request timeout.
      const result = await request(`projects/${encodeURIComponent(deletion.project.project_id)}/deletion/${operation}`, body,
        operation === "delete" ? { timeoutMs: 27000 } : undefined);
      if (result.deletion) {
        deletion.result = result.deletion;
        deletion.unknown = false;
        if (deletion.result.deletion_state === "scrubbed") notice("Eliminazione dei dati Flower del progetto completata.");
      }
      updateMaintenance(result.maintenance);
      if (operation === "cancel") {
        $("delete-dialog").close();
        state.deletion = null;
        forgetIntent();
        notice("Preparazione annullata; il journal dell’intento è conservato.");
      }
    } catch (error) {
      if (error.stale) return;
      deletion.error = error.message;
      deletion.reason = error.reason;
      const result = error.envelope?.result;
      if (result?.deletion) {
        deletion.result = result.deletion;
        deletion.unknown = false;
      } else {
        const passwordRefused = operation === "delete" && [
          "dashboard_delete_password_required", "dashboard_delete_password_denied",
          "dashboard_auth_busy", "dashboard_auth_rate_limited", "dashboard_auth_unavailable",
        ].includes(error.reason);
        deletion.unknown = !passwordRefused;
      }
      if (result?.maintenance) updateMaintenance(result.maintenance);
    } finally {
      state.adminBusy = false;
      if (state.deletion) { rememberIntent(); renderDeletion(); }
      await checkMaintenance();
    }
  }

  async function startDashboard({ clearMessage = false } = {}) {
    if (state.initializing || state.authBusy) return;
    state.initializing = true;
    updateLoginControls();
    if (!state.ready && $("login-panel").hidden) {
      loading($("initial-loading"), "Connessione a Flower…");
      $("initial-loading").hidden = false;
    }
    try {
      const auth = await request("auth");
      if (!auth.authenticated) showLogin(clearMessage ? "" : undefined);
      applyAuth(auth);
      if (!auth.authenticated) return;
      const status = await request("status");
      showWorkspace();
      restoreIntent();
      restoreUpgrade();
      updateMaintenance(status);
      notice("");
      route();
    } catch (error) {
      if (error.stale) return;
      state.availability = "unavailable";
      showLogin(error.message);
    } finally {
      state.initializing = false;
      updateLoginControls();
    }
  }

  async function signIn(event) {
    event.preventDefault();
    if (state.authBusy || state.initializing || state.availability !== "ready" || Date.now() < state.retryUntil) return;
    state.authBusy = true;
    loginMessage("Verifica dell’account locale…", true);
    updateLoginControls();
    const generation = state.authGeneration;
    try {
      const result = await request("login", { username: $("login-username").value, password: $("login-password").value });
      $("login-password").value = "";
      if (generation !== state.authGeneration) return;
      const status = await request("status");
      showWorkspace();
      restoreIntent();
      restoreUpgrade();
      updateMaintenance(status);
      route();
      if (result.evicted_session) notice("La sessione meno recente è stata chiusa perché è stato raggiunto il limite delle sessioni aperte.");
    } catch (error) {
      $("login-password").value = "";
      if (error.stale) return;
      loginMessage(error.message);
      if (error.status === 429 && error.retryAfter > 0 && error.retryAfter <= 60) {
        state.retryUntil = Date.now() + error.retryAfter * 1000;
        clearTimeout(state.retryTimer);
        state.retryTimer = setTimeout(updateLoginControls, error.retryAfter * 1000 + 50);
      }
      if (error.status === 403 || error.status === 503) {
        try { applyAuth(await request("auth")); } catch (_) { /* Keep the failed attempt visible; never resubmit its password. */ }
      }
    } finally {
      $("login-password").value = "";
      state.authBusy = false;
      updateLoginControls();
    }
  }

  async function signOut() {
    if (state.authBusy) return;
    state.authBusy = true;
    closePrivateDialogs();
    updateLoginControls();
    try {
      await request("logout", {});
      showLogin();
      $("login-username").value = "";
      loginMessage("Sei uscito da Flower.", true);
      try { applyAuth(await request("auth")); } catch (_) { /* Connection retry remains explicit in the login panel. */ }
    } catch (error) {
      if (state.ready) notice(error.message, true);
      else loginMessage(error.message);
    } finally {
      state.authBusy = false;
      updateLoginControls();
    }
  }

  $("login-form").addEventListener("submit", signIn);
  $("login-retry").addEventListener("click", () => startDashboard({ clearMessage: true }));
  $("logout-button").addEventListener("click", signOut);
  $("home-button").addEventListener("click", () => navigate(null));
  $("settings-button").addEventListener("click", () => {
    notice("");
    navigate(null, "settings");
  });
  $("settings-refresh").addEventListener("click", loadSettings);
  $("settings-basic").addEventListener("click", () => showSettingsSection("basic"));
  $("settings-advanced").addEventListener("click", () => showSettingsSection("advanced"));
  $("settings-form").addEventListener("submit", (event) => { event.preventDefault(); saveSettings(); });
  $("settings-discard").addEventListener("click", () => saveSettings(true));
  $("upgrade-refresh").addEventListener("click", loadUpgrade);
  $("upgrade-version").addEventListener("input", changeUpgradeVersion);
  $("upgrade-preview-form").addEventListener("submit", previewUpgrade);
  $("upgrade-open").addEventListener("click", openUpgrade);
  $("upgrade-apply-form").addEventListener("submit", applyUpgrade);
  $("upgrade-password").addEventListener("input", updateUpgradeControls);
  $("upgrade-close").addEventListener("click", () => $("upgrade-dialog").close());
  $("upgrade-dialog").addEventListener("cancel", (event) => { if (state.upgradeBusy) event.preventDefault(); });
  $("upgrade-dialog").addEventListener("close", () => { $("upgrade-password").value = ""; });
  for (const id of ["backups-restore-guide", "archive-restore-guide"]) {
    $(id).append($("archive-restore-template").content.cloneNode(true));
  }
  $("backups-button").addEventListener("click", () => {
    notice("");
    navigate(null, "backups");
  });
  $("backups-refresh").addEventListener("click", loadBackups);
  $("backup-create").addEventListener("click", createBackup);
  $("backup-delete-form").addEventListener("submit", deleteBackup);
  $("backup-delete-password").addEventListener("input", updateArchiveControls);
  $("backup-delete-close").addEventListener("click", () => $("backup-delete-dialog").close());
  $("backup-delete-dialog").addEventListener("cancel", (event) => { if (state.archiveBusy) event.preventDefault(); });
  $("backup-delete-dialog").addEventListener("close", () => {
    state.backupDeletion = null;
    $("backup-delete-password").value = "";
  });
  $("create-open").addEventListener("click", openCreateProject);
  $("create-name").addEventListener("input", () => {
    if (!state.createIdEdited) {
      $("create-id").value = $("create-name").value.trim().toLowerCase().normalize("NFKD")
        .replace(/\p{Mark}/gu, "").replace(/[^a-z0-9_-]+/g, "-").replace(/^[^a-z0-9]+|-+$/g, "").slice(0, 64);
    }
    updateCreateControls();
  });
  $("create-id").addEventListener("input", () => { state.createIdEdited = true; updateCreateControls(); });
  $("create-form").addEventListener("submit", createProject);
  $("create-check").addEventListener("click", checkCreatedProject);
  $("create-close").addEventListener("click", () => $("create-dialog").close());
  $("create-dialog").addEventListener("cancel", (event) => { if (state.createBusy) event.preventDefault(); });
  $("catalog-refresh").addEventListener("click", loadProjects);
  $("export-open").addEventListener("click", () => { if (state.project) openArchive(state.project); });
  $("archive-close").addEventListener("click", () => $("archive-dialog").close());
  $("archive-dialog").addEventListener("close", () => { state.archive = null; });
  $("archive-download").addEventListener("click", downloadArchive);
  $("project-refresh").addEventListener("click", loadSection);
  $("project-delete").addEventListener("click", () => openDeletion(state.project));
  $("projects-previous").addEventListener("click", () => { state.projectOffset = Math.max(0, state.projectOffset - 25); loadProjects(); });
  $("projects-next").addEventListener("click", () => { state.projectOffset = state.projects.next_offset; loadProjects(); });
  $("section-previous").addEventListener("click", () => { state.sectionOffset = Math.max(0, state.sectionOffset - 25); loadSection(); });
  $("section-next").addEventListener("click", () => { state.sectionOffset = state.sectionData.bounds.next_offset; loadSection(); });
  $("delete-close").addEventListener("click", () => $("delete-dialog").close());
  $("delete-dialog").addEventListener("close", () => {
    const password = $("delete-password");
    if (password) password.value = "";
  });
  $("delete-dialog").addEventListener("cancel", (event) => { if (state.adminBusy) event.preventDefault(); });
  $("evidence-close").addEventListener("click", () => $("evidence-dialog").close());
  window.addEventListener("popstate", () => { if (state.ready) route(); });
  let searchTimer;
  $("project-search").addEventListener("input", () => { clearTimeout(searchTimer); searchTimer = setTimeout(() => { state.projectOffset = 0; loadProjects(); }, 250); });
  document.addEventListener("visibilitychange", checkMaintenance);
  setInterval(checkMaintenance, 15000);

  startDashboard();
})();
