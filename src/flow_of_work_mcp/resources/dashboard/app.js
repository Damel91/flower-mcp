"use strict";

(() => {
  const sections = {
    overview: { label: "Panoramica", description: "L’intento, il lavoro attuale e i punti che richiedono attenzione." },
    roadmap: { label: "Roadmap", description: "Milestone e dipendenze nel loro ordine di realizzazione." },
    packets: { label: "Pacchetti", description: "Il lavoro dichiarato, le unità e le condizioni per procedere." },
    verification: { label: "Verifiche", description: "Campagne, prove di requisito, report delle unità e review del repository." },
    architecture: { label: "Architettura", description: "Componenti, interfacce e decisioni adottate per il progetto." },
    evidence: { label: "Evidenze", description: "Riferimenti, documenti e handover conservati da Flower." },
  };
  const verificationChannels = {
    campaign: "Campagne", verification: "Prove di requisito", external_report: "Report delle unità",
    repository_review: "Review del repository",
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
    recorded_disposition: "Classificazione registrata all’origine", currentness: "Applicabilità attuale",
    reported_units: "Unità complete sul pin corrente", report_history: "Report conservati sui rispettivi pin",
    requirement_evidence: "Prove dirette per requisito", recorded_count: "Prove registrate",
    historical_outcome: "Esito storico", original_report: "Report originale", effect_policy: "Effetti consentiti",
    verification_recovery: "Recupero della verifica", failed_evidence: "Prove fallite",
    linked_exception: "Eccezione collegata", live_execution_authorized: "Nuova esecuzione live autorizzata",
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
    host_declared: "Dichiarata dall’host", recorded_verification_evidence: "Prova di requisito registrata",
    historical_on_original_pin: "Storico sul pin originale", current_authority: "Autorità attuale",
    inspect_historical_outcome: "Esamina l’esito storico", inspection_and_review_only: "Sola ispezione e revisione",
    not_evaluated: "Non valutata",
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
    dashboard_network_input_invalid: "Controlla i valori di rete e usa una porta intera da 1 a 65535.",
    dashboard_network_port_conflict: "La porta HTTPS coincide con la porta MCP. Scegli una porta diversa.",
    dashboard_network_mcp_host_invalid: "L’accesso dalla LAN richiede che l’endpoint MCP ascolti in locale.",
    dashboard_network_changed: "La configurazione di rete è cambiata. Rileggi il profilo prima di salvare.",
    dashboard_network_state_invalid: "La configurazione di rete salvata non è leggibile o non è valida.",
    settings_configuration_changed: "Il file del profilo è cambiato. Riavvia Flower per rileggerlo.",
    settings_draft_changed: "La bozza è cambiata. Rileggi il profilo prima di salvare.",
    dashboard_project_not_found: "Il progetto non è più presente in questo profilo. Torna ai progetti e aggiorna l’elenco.",
    dashboard_evidence_too_large: "L’evidenza supera il limite di 2 MiB di questa vista. Il suo riferimento rimane visibile nel progetto.",
    dashboard_document_not_found: "Il documento selezionato non è disponibile in questo progetto. Aggiorna la vista e selezionalo di nuovo.",
    dashboard_document_too_large: "Il documento completo supera il limite di 2 MiB. Se disponibile, seleziona un ambito più piccolo.",
    dashboard_archive_busy: "È già in corso un’altra operazione su un archivio. Attendi che finisca e riprova.",
    dashboard_archive_failed: "Flower non ha potuto preparare l’archivio. Controlla lo spazio disponibile e riprova.",
    dashboard_backup_failed: "Flower non ha potuto completare l’operazione sui backup. Rileggi l’elenco prima di riprovare.",
    archive_backup_not_found: "Il backup non è più presente. Aggiorna l’elenco.",
    archive_backup_id_invalid: "L’identificativo del backup non è valido. Aggiorna l’elenco e seleziona un backup.",
    archive_backup_changed: "Il backup è cambiato. Aggiorna l’elenco prima di riprovare.",
    archive_backup_limit: "Hai raggiunto il limite dei backup conservati. Scarica le copie che ti servono e rimuovine una prima di crearne un’altra.",
    archive_backup_inventory_limit: "Flower non può mostrare tutti i backup conservati. Controlla la cartella dei backup del profilo.",
    archive_project_not_found: "Il progetto non è più presente. Aggiorna l’elenco prima di esportarlo.",
    archive_size_exceeded: "I dati superano il limite di dimensione dell’archivio.",
    archive_scope_invalid: "L’archivio o il progetto contiene riferimenti che Flower non può verificare.",
    archive_schema_unsupported: "Il formato del registro non è supportato da questa versione di Flower.",
    archive_source_unavailable: "Il registro non è disponibile. Controlla il profilo e riprova.",
    archive_io_failure: "Flower non ha potuto leggere o scrivere l’archivio. Controlla lo spazio disponibile e i permessi del profilo.",
    archive_invalid: "L’archivio non ha superato il controllo di integrità.",
    archive_profile_name_invalid: "Scegli un nome valido per il nuovo database.",
    archive_destination_exists: "Esiste già un database con questo nome. Scegli un altro nome.",
    archive_restore_media_type: "Seleziona un archivio ZIP di Flower.",
    archive_restore_timeout: "Il caricamento dell’archivio ha impiegato troppo tempo. Riprova.",
    archive_workspace_unsafe: "Flower non può preparare l’archivio in sicurezza. Controlla la configurazione e i permessi.",
    archive_project_required: "Scegli lo ZIP di un singolo progetto esportato da Flower.",
    archive_import_unsupported: "Questo progetto contiene attività da riconciliare o riferimenti che Flower non può trasferire. Puoi aprire l’archivio in un database separato.",
    archive_import_conflict: "Il database ha rifiutato l’importazione. Controlla lo stato del progetto e del database.",
    archive_import_busy: "Il database è occupato. Attendi la fine delle operazioni in corso e riprova.",
    maintenance_jobs_busy: "Ci sono lavori Flower in corso. Riprova quando terminano.",
    maintenance_requests_busy: "Ci sono richieste Flower in corso. Riprova fra poco.",
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
    queued: "Richiesta registrata", preparing: "Verifica del rilascio", stopping: "Arresto di Flower",
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
    upgrade_already_pending: "Flower ha già un aggiornamento da completare o verificare.",
    upgrade_platform_unsupported: "L’aggiornamento da questa dashboard è disponibile su macOS.",
    upgrade_service_not_ready: "Avvia il servizio gestito e controlla di nuovo lo stato.",
    upgrade_preview_expired: "L’anteprima è scaduta. Verifica di nuovo la versione.",
    upgrade_selection_changed: "Il servizio o la configurazione sono cambiati. Verifica di nuovo la versione.",
    upgrade_dispatch_failed: "Flower non ha potuto avviare il processo di aggiornamento.",
    upgrade_installation_unproved: "L’aggiornamento dalla dashboard richiede un’installazione ufficiale di Flower.",
    upgrade_profile_unproved: "L’aggiornamento richiede il file flower.yaml di un profilo Flower standard.",
    upgrade_stop_not_authorized: "Flower non ha ottenuto la conferma o non ha potuto fermarsi. Nessuna installazione è iniziata.",
    upgrade_shutdown_unconfirmed: "Flower non ha potuto confermare l’arresto. Nessuna installazione è iniziata.",
    upgrade_worker_unconfirmed: "Flower non riesce a confermare che l’aggiornamento sia ancora in corso. Leggi la ricevuta con flower-mcp service upgrade-status usando lo stesso profilo e la stessa porta.",
  };
  const state = {
    ready: false, initializing: false, authBusy: false, authGeneration: 0, availability: "unavailable", retryUntil: 0, retryTimer: null, csrf: "", maintenance: { state: "ready" }, project: null,
    section: "overview", projectOffset: 0, sectionOffset: 0, projects: null, sectionData: null,
    verificationChannel: "verification", verificationScope: "",
    createBusy: false, createUncertain: "", createIdEdited: false,
    settings: null, settingsBusy: false, settingsEpoch: 0,
    network: null, networkBusy: false, networkEpoch: 0,
    upgradeStatus: null, upgradePreview: null, upgradeBusy: false, upgradeReading: false, upgradeEpoch: 0, rememberedUpgrade: null,
    archive: null, archiveBusy: false, backupDeletion: null,
    loadingEpoch: 0, evidenceEpoch: 0, deletion: null, adminBusy: false, connectionWarning: false,
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

  const dashboardRequests = new Set();

  async function request(path, body, { timeoutMs = 15000, archive = false, zipUpload = false } = {}) {
    const generation = state.authGeneration;
    const controller = new AbortController();
    dashboardRequests.add(controller);
    const timeout = setTimeout(() => controller.abort(), timeoutMs);
    const options = { credentials: "same-origin", cache: "no-store", signal: controller.signal,
      headers: { Accept: archive ? "application/zip, application/json" : "application/json" } };
    if (state.csrf) options.headers["X-Flower-CSRF"] = state.csrf;
    if (body !== undefined) {
      options.method = "POST";
      options.headers["Content-Type"] = zipUpload ? "application/zip" : "application/json";
      options.body = zipUpload ? body : JSON.stringify(body);
    }
    try {
      const response = await fetch(`/dashboard/api/${path}`, options);
      const isZip = archive && response.ok && response.headers.get("Content-Type")?.split(";", 1)[0].trim() === "application/zip";
      const payload = isZip ? await response.blob() : await response.json();
      if (generation !== state.authGeneration) {
        throw Object.assign(new Error(errorMessages.dashboard_session_changed), { reason: "dashboard_session_changed", stale: true });
      }
      connection(true);
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
      if (generation !== state.authGeneration && !error.stale) {
        throw Object.assign(new Error(errorMessages.dashboard_session_changed), { reason: "dashboard_session_changed", stale: true });
      }
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
      dashboardRequests.delete(controller);
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
  const archiveProfilePattern = /^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$/;
  const archiveTimeoutMs = 120000;
  const restoreTimeoutMs = 330000;

  function updateArchiveControls() {
    const disabled = state.archiveBusy || state.maintenance.state !== "ready";
    $("backup-create").disabled = disabled;
    $("backups-refresh").disabled = state.archiveBusy;
    $("export-open").disabled = disabled || !state.project;
    $("archive-download").disabled = disabled;
    $("backup-delete-submit").disabled = disabled || !$("backup-delete-password").value;
    $("backup-delete-password").readOnly = state.archiveBusy;
    $("backup-delete-close").disabled = state.archiveBusy;
    $("import-open").disabled = disabled;
    $("import-submit").disabled = disabled || !$("import-file").files.length;
    $("import-file").disabled = state.archiveBusy;
    $("import-close").disabled = $("import-cancel").disabled = state.archiveBusy;
    const profileName = $("restore-profile").value.trim();
    $("restore-open").disabled = disabled;
    $("restore-submit").disabled = disabled || !$("restore-file").files.length
      || !archiveProfilePattern.test(profileName) || profileName.endsWith(".");
    $("restore-file").disabled = state.archiveBusy;
    $("restore-profile").readOnly = state.archiveBusy;
    $("restore-close").disabled = $("restore-cancel").disabled = state.archiveBusy;
    for (const item of $("backups-content").querySelectorAll("button[data-backup-action]")) item.disabled = disabled;
  }

  function openArchive(project) {
    if (!project || !state.ready || state.archiveBusy || state.maintenance.state !== "ready") return;
    const projectId = project.project_id;
    state.archive = { projectId };
    $("archive-scope").textContent = project.name === projectId ? projectId : `${project.name} (${projectId})`;
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

  function openImport() {
    if (!state.ready || $("import-open").disabled) return;
    $("import-form").reset();
    formMessage("import-message", "");
    updateArchiveControls();
    $("import-dialog").showModal();
    $("import-file").focus();
  }

  function importProject(event) {
    event.preventDefault();
    if ($("import-submit").disabled) return;
    const archive = $("import-file").files[0];
    const dialog = $("import-dialog");
    return archiveTask(async () => {
      formMessage("import-message", "Caricamento e verifica dell’archivio in corso…");
      try {
        const { project_id: projectId } = await request("projects/import", archive,
          { zipUpload: true, timeoutMs: restoreTimeoutMs });
        if (!dialog.open || state.authBusy) return;
        if (!projectIdPattern.test(projectId || "")) throw new Error("Importazione non confermata.");
        dialog.close();
        navigate(projectId);
        notice(`Progetto «${projectId}» importato.`);
      } catch (error) {
        if (!dialog.open || error.stale) return;
        const message = !error.status || error.status >= 500
          ? "L’importazione non è confermata. Controlla l’elenco dei progetti prima di riprovare."
          : archiveError(error);
        formMessage("import-message", message, true);
      }
    });
  }

  function openRestore() {
    if (!state.ready || $("restore-open").disabled) return;
    $("restore-form").reset();
    formMessage("restore-message", "");
    updateArchiveControls();
    $("restore-dialog").showModal();
    $("restore-file").focus();
  }

  function restoreArchive(event) {
    event.preventDefault();
    if ($("restore-submit").disabled) return;
    const profileName = $("restore-profile").value.trim();
    const archive = $("restore-file").files[0];
    const dialog = $("restore-dialog");
    return archiveTask(async () => {
      formMessage("restore-message", "Caricamento e verifica dell’archivio in corso…");
      try {
        const result = await request(`restore/${encodeURIComponent(profileName)}`, archive,
          { zipUpload: true, timeoutMs: restoreTimeoutMs });
        if (!dialog.open || state.authBusy) return;
        if (result.profile_name !== profileName) throw new Error("Ripristino non confermato.");
        dialog.close();
        notice(`Archivio ripristinato nel nuovo database «${profileName}». Per aprirlo, avvia un’istanza Flower con quel database.`);
        $("backups-title").focus();
      } catch (error) {
        if (!dialog.open || error.stale) return;
        const message = !error.status || error.status >= 500
          ? `Il ripristino del database «${profileName}» non è confermato. Controlla se il database esiste prima di riprovare.`
          : archiveError(error);
        formMessage("restore-message", message, true);
      }
    });
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

  function updateNetworkControls() {
    const editable = state.ready && state.network && !state.networkBusy && state.maintenance.state === "ready";
    const enabled = $("network-enabled");
    const port = $("network-port");
    enabled.disabled = port.disabled = !editable;
    $("network-save").disabled = !editable
      || (enabled.checked === state.network.enabled && port.valueAsNumber === state.network.port);
  }

  function renderNetworkLinks(urls) {
    const list = $("network-urls");
    list.replaceChildren();
    for (const address of Array.isArray(urls) ? urls : []) {
      if (typeof address !== "string") continue;
      let url;
      try { url = new URL(address); } catch (_) { continue; }
      if (url.protocol !== "https:" || url.username || url.password || url.search || url.hash
          || !["/", "/dashboard", "/dashboard/"].includes(url.pathname)) continue;
      const item = element("li");
      const link = element("a", "", url.href);
      link.href = url.href;
      link.target = "_blank";
      link.rel = "noopener";
      item.append(link);
      list.append(item);
    }
    list.hidden = !list.childElementCount;
  }

  function renderNetwork(snapshot) {
    state.network = snapshot;
    const { active, enabled, port } = snapshot;
    const running = {
      local: "Solo accesso locale",
      lan: `HTTPS su tutte le interfacce IPv4, porta ${active.port}`,
      explicit: `HTTPS su un indirizzo configurato, porta ${active.port}`,
    };
    $("network-active").textContent = running[active.mode];
    renderNetworkLinks(active.urls);
    $("network-saved").textContent = enabled ? `LAN abilitata, porta ${port}` : "LAN disattivata";
    $("network-override").hidden = !active.cli_override;
    $("network-enabled").checked = enabled;
    $("network-port").value = port;
    $("network-content").replaceChildren();
    $("network-form").hidden = false;
    updateNetworkControls();
  }

  async function loadNetwork() {
    if (!state.ready || $("settings-view").hidden || state.networkBusy) return;
    const epoch = ++state.networkEpoch;
    state.network = null;
    $("network-form").hidden = true;
    formMessage("network-message", "");
    loading($("network-content"), "Lettura della configurazione di rete…");
    try {
      const result = await request("network");
      if (epoch === state.networkEpoch) renderNetwork(result);
    } catch (error) {
      if (!error.stale && epoch === state.networkEpoch) {
        $("network-content").replaceChildren(errorPanel(error, loadNetwork));
      }
    }
  }

  async function saveNetwork(event) {
    event.preventDefault();
    if (!state.ready || $("settings-view").hidden || $("network-save").disabled
        || !$("network-form").reportValidity()) return;
    const epoch = state.networkEpoch;
    const body = { revision: state.network.revision, enabled: $("network-enabled").checked,
      port: $("network-port").valueAsNumber };
    state.networkBusy = true;
    updateNetworkControls();
    formMessage("network-message", "Salvataggio in corso…");
    try {
      const result = await request("network", body);
      if (epoch === state.networkEpoch) {
        renderNetwork(result);
        const { active, enabled, port } = result;
        const pendingRestart = !active.cli_override
          && (enabled !== (active.mode === "lan") || (enabled && port !== active.port));
        formMessage("network-message", pendingRestart
          ? "Configurazione di rete salvata. Riavvia Flower per applicarla."
          : "Configurazione di rete salvata.");
      }
    } catch (error) {
      if (!error.stale && epoch === state.networkEpoch) {
        const uncertain = !error.status || error.status >= 500 || error.reason === "dashboard_network_save_unconfirmed";
        if (uncertain || error.reason === "dashboard_network_changed") state.network = null;
        const message = uncertain ? "Rileggi il profilo per verificare se la configurazione è stata salvata." : error.message;
        formMessage("network-message", message, true);
      }
    } finally {
      state.networkBusy = false;
      updateNetworkControls();
      if (state.ready && epoch !== state.networkEpoch && !$("settings-view").hidden) loadNetwork();
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
      ? upgradeErrors[snapshot.reason] || "L’aggiornamento richiede un’installazione ufficiale compatibile di Flower."
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
        const manual = state.upgradeStatus?.mode === "manual";
        formMessage("upgrade-message", state.rememberedUpgrade
          ? manual
            ? "L’aggiornamento continua dopo l’arresto. Puoi controllare la ricevuta con flower-mcp upgrade-status e riaprire Flower al termine."
            : "La ricevuta sarà disponibile al ritorno del servizio. Se il servizio resta fermo, usa flower-mcp service upgrade-status con lo stesso profilo e la stessa porta."
          : error.message, true);
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
      $("upgrade-preview-help").textContent = preview.mode === "manual"
        ? "Flower verifica il rilascio, si arresta e crea un backup di SQLite e della configurazione prima di installare."
        : "Flower ferma il servizio, crea un backup di SQLite e della configurazione, installa la versione scelta e verifica il riavvio.";
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
    $("upgrade-dialog-help").textContent = state.upgradePreview.mode === "manual"
      ? "Flower verifica il rilascio, si arresta e salva un backup prima di installarlo. Al termine, riaprilo come fai di solito."
      : "La dashboard si disconnette durante l’aggiornamento. Accedi di nuovo per vedere il risultato.";
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
        formMessage("upgrade-message", result.mode === "manual"
          ? "Aggiornamento avviato. Flower si fermerà durante l’installazione. Riaprilo al termine."
          : "Richiesta registrata. Accedi di nuovo dopo il riavvio per vedere il risultato.");
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
    for (const name of ["create-dialog", "delete-dialog", "evidence-dialog", "archive-dialog", "backup-delete-dialog", "import-dialog", "restore-dialog", "upgrade-dialog"]) {
      if ($(name).open) $(name).close();
    }
  }

  function showLogin(message, { reset = false } = {}) {
    const changed = reset || state.ready || $("login-panel").hidden;
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
      state.networkEpoch += 1;
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
      state.network = null;
      $("network-form").reset();
      $("network-form").hidden = $("network-override").hidden = true;
      $("network-content").replaceChildren();
      renderNetworkLinks();
      $("network-active").textContent = $("network-saved").textContent = "";
      formMessage("network-message", "");
      state.deletion = null;
      $("delete-form").reset();
      formMessage("delete-message", "");
      state.maintenance = { state: "ready" };
      for (const name of ["catalog-content", "section-content", "evidence-content", "section-navigation", "backups-content"]) $(name).replaceChildren();
      for (const name of ["sidebar-project-name", "sidebar-project-id", "project-title", "section-title", "section-observed", "catalog-count", "catalog-observed", "section-bounds", "archive-scope", "backup-delete-selection", "delete-project-name", "delete-project-id"]) $(name).textContent = "";
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
    if ($("evidence-dialog").open) $("evidence-dialog").close();
    const parameters = new URLSearchParams(location.search);
    const projectId = parameters.get("project");
    const view = parameters.get("view");
    const settings = !projectId && view === "settings";
    const backups = !projectId && view === "backups";
    state.settingsEpoch += 1;
    state.networkEpoch += 1;
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
        loadNetwork();
        loadUpgrade();
      }
      else loadBackups();
      return;
    }
    state.section = Object.hasOwn(sections, view) ? view : "overview";
    const channel = parameters.get("channel");
    state.verificationChannel = Object.hasOwn(verificationChannels, channel) ? channel : "verification";
    state.verificationScope = state.verificationChannel === "campaign" ? "" : parameters.get("scope_id") || "";
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

  function navigate(projectId, section = "overview", { channel, scope } = {}) {
    const url = new URL(location.href);
    url.search = "";
    if (projectId) {
      url.searchParams.set("project", projectId);
      url.searchParams.set("view", section);
      if (section === "verification" && channel) url.searchParams.set("channel", channel);
      if (section === "verification" && scope) url.searchParams.set("scope_id", scope);
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
    return item.status || item.state || item.packet?.status || item.lifecycle_status || item.qualification || item.outcome;
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
    if (typeof status === "string") {
      const statusBadge = badge(status);
      if (state.section === "packets" || state.section === "roadmap") statusBadge.prepend("Stato registrato · ");
      heading.append(statusBadge);
    }
    const dimensions = element("div", "dimension-line");
    for (const [key, title] of [["reported_units", "Unità complete sul pin corrente"], ["implementation", "Implementazione dichiarata"], ["local_verification", "Verifica locale"]]) {
      const value = item[key];
      if (value && typeof value.completed === "number" && typeof value.total === "number") {
        const dimension = element("span", "", title);
        let result = `${value.completed}/${value.total}`;
        if (value.total === 0) result = key === "reported_units" ? "Nessuna unità" : "Nessun criterio";
        dimension.append(element("strong", "", result));
        dimensions.append(dimension);
      }
    }
    if (state.section === "packets" && item.acceptance === "not_inferred") {
      dimensions.append(element("span", "", item.next_gate?.external_operation === "request_human_acceptance"
        ? "Verifica gli obblighi prima dell’accettazione" : "Accettazione non dedotta"));
    }
    if (dimensions.childElementCount) main.append(dimensions);
    if (state.section === "packets" && item.next_gate?.external_operation === "inspect_historical_outcome") {
      main.append(element("p", "item-caption", "Recupero richiesto. Verifica l’esito conservato prima di procedere."));
    }
    const body = element("div", "item-body");
    if (state.section === "packets" && item.packet_id) {
      body.append(button("Vedi prove e accettazione", "button-secondary", () => loadAcceptance("packets", item.packet_id)));
    } else if (state.section === "roadmap" && item.milestone_id) {
      body.append(button("Vedi prove e accettazione", "button-secondary", () => loadAcceptance("roadmap", item.milestone_id)));
      body.append(button("Esporta requisiti della milestone", "button-secondary evidence-action", () =>
        loadRequirementsDocument("milestone", item.milestone_id, `Requisiti di ${item.milestone_id}`)));
    }
    const retained = evidenceAddress(item);
    if (retained) body.append(button("Apri contenuto conservato", "button-secondary evidence-action", () => loadEvidence(retained)));
    if (state.section === "overview" && item.requirement_id) {
      body.append(verificationLink("Apri prove di requisito", "verification", item.requirement_id));
      body.append(button("Esporta requisito", "button-secondary evidence-action", () =>
        loadRequirementsDocument("requirement", item.requirement_id, `Requisito ${item.requirement_id}`)));
    }
    if (state.section === "packets" && item.packet_id) {
      const links = element("div", "verification-channels");
      const original = item.next_gate?.original_report?.report_identity;
      if (original) {
        links.append(button("Apri il report originale da riesaminare", "button-secondary", () =>
          loadEvidence({ kind: "external_report", identity: original })));
      }
      if (item.report_history_bounds?.total) {
        links.append(verificationLink(`Apri report conservati (${item.report_history_bounds.total})`, "external_report", item.packet_id));
      }
      const auditId = item.repository_review?.latest_audit_id;
      if (auditId) {
        links.append(button("Apri review del repository", "button-secondary", () =>
          loadEvidence({ kind: "repository_review", identity: auditId })));
      }
      for (const proof of item.requirement_evidence || []) {
        const count = proof.recorded_count ? `${proof.recorded_count} prove dirette` : "Nessuna prova diretta registrata";
        links.append(verificationLink(`${proof.requirement_id} · ${count}`, "verification", proof.requirement_id));
      }
      if (links.childElementCount) body.append(links);
    }
    body.append(fields(item));
    details.append(heading, body);
    return details;
  }

  function evidenceAddress(item) {
    if (state.section === "verification") {
      return item.kind && item.identity !== undefined ? { kind: item.kind, identity: item.identity } : null;
    }
    if (state.section !== "evidence") return null;
    if (item.kind && item.identity !== undefined) return { kind: item.kind, identity: item.identity };
    if (item.evidence_id !== undefined) return { kind: "verification", identity: item.evidence_id };
    if (item.handover_id) return { kind: "handover", identity: item.handover_id };
    if (item.generation_id !== undefined) return { kind: "artifact", identity: item.generation_id };
    return null;
  }

  function verificationLink(title, channel, scope = "") {
    return button(title, "button-secondary", () => navigate(state.project.project_id, "verification", { channel, scope }));
  }

  function renderVerificationChannels(summary) {
    const nav = element("nav", "verification-channels");
    nav.setAttribute("aria-label", "Canali di verifica");
    for (const [channel, title] of Object.entries(verificationChannels)) {
      const count = summary.evidence_channels?.[channel] ?? 0;
      const link = verificationLink(`${title} (${count})`, channel);
      if (summary.channel === channel) link.setAttribute("aria-current", "page");
      nav.append(link);
    }
    if (summary.scope_id) {
      nav.append(verificationLink(`Mostra tutti · filtro ${summary.scope_id}`, summary.channel));
    }
    return nav;
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

  function renderDocument(result) {
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

  function loadRequirementsDocument(scope, scopeId, title) {
    const query = new URLSearchParams({ scope });
    if (scopeId) query.set("scope_id", scopeId);
    return loadDocument(`documents/requirements?${query}`, { title, label: "Esportazione Markdown" });
  }

  function loadEvidence(address) {
    const identity = String(address.identity).replace(/[^A-Za-z0-9_-]/g, "_");
    return loadDocument(`evidence/${encodeURIComponent(address.kind)}/${encodeURIComponent(address.identity)}`, {
      label: "Evidenza conservata", filename: `flower-${address.kind}-${identity}`,
    });
  }

  async function loadDocument(path, { title, label = "Esportazione Markdown", filename } = {}) {
    if (!state.project) return;
    const epoch = ++state.evidenceEpoch;
    const projectId = state.project.project_id;
    $("evidence-kind-label").textContent = label;
    $("evidence-title").textContent = title || "Dettaglio";
    loading($("evidence-content"), "Lettura del documento…");
    if (!$("evidence-dialog").open) $("evidence-dialog").showModal();
    try {
      const result = await request(`projects/${encodeURIComponent(projectId)}/${path}`);
      if (epoch !== state.evidenceEpoch || !$("evidence-dialog").open || state.project?.project_id !== projectId) return;
      $("evidence-title").textContent = display(title || result.title || result.artifact_kind || result.handover_id || result.evidence_id || "Contenuto conservato");
      $("evidence-content").replaceChildren();
      if (typeof result.content === "string") {
        $("evidence-content").append(renderDocument(result));
        $("evidence-content").append(button("Scarica documento", "button-secondary evidence-action", () => {
          const extension = result.content_type === "text/markdown" ? "md" : "json";
          downloadBlob(new Blob([result.content], { type: result.content_type || "text/plain" }),
            result.filename || `${filename || "flower-document"}.${extension}`);
        }));
      } else $("evidence-content").append(fields(result));
    } catch (error) {
      if (!state.ready || error.stale || epoch !== state.evidenceEpoch || !$("evidence-dialog").open || state.project?.project_id !== projectId) return;
      $("evidence-content").replaceChildren(errorPanel(error, () => loadDocument(path, { title, label, filename })));
    }
  }

  function acceptancePanel(context) {
    const scope = context.scope || {};
    const packet = context.packet_checkpoint;
    const acceptance = context.milestone_acceptance || {};
    const messages = {
      blocked: "La milestone ha obblighi aperti",
      awaiting_human: "La milestone attende la decisione umana",
      ready: "La milestone è pronta per l’accettazione",
      accepted: "La milestone è accettata",
      unavailable: "Accettazione della milestone non disponibile",
    };
    const blockers = {
      packet_unresolved: "Chiudi il pacchetto con le evidenze richieste",
      navigation_audit_blocker: "Completa le verifiche di navigazione richieste",
      campaign_missing: "Registra la campagna di verifica prevista",
      campaign_not_green: "Verifica gli esiti della campagna",
      finding_unresolved: "Esamina i problemi ancora aperti",
      external_milestone_scope_incomplete: "Verifica la copertura del lavoro e dei controlli locali",
      external_milestone_verification_pending: "Completa le verifiche differite richieste",
    };
    const panel = element("section", acceptance.state === "blocked" ? "attention" : "summary-block");
    panel.append(element("p", "item-caption", [scope.packet_id, scope.milestone_id].filter(Boolean).join(" · ")),
      element("h3", "", messages[acceptance.state] || messages.unavailable));
    if (packet?.reported_units) {
      const { completed, total } = packet.reported_units;
      panel.append(element("p", "", `Unità dichiarate complete dall’agente ${completed}/${total}. Stato registrato del pacchetto: ${display(packet.recorded_status)}.`));
    }
    if (packet?.next_gate?.external_operation === "request_human_acceptance") {
      panel.append(element("p", "item-caption", "Il pacchetto è arrivato al controllo prima dell’accettazione."));
    }
    if (packet?.repository_review?.latest_audit_id) {
      const review = packet.repository_review;
      panel.append(button(`Apri review ${review.latest_audit_id} · ${display(review.state)}`, "button-secondary evidence-action", () =>
        loadEvidence({ kind: "repository_review", identity: review.latest_audit_id })));
    }
    if (acceptance.blockers?.length) {
      const list = element("ul", "value-list");
      for (const blocker of acceptance.blockers) {
        const identity = blocker.packet_id || blocker.change_id;
        list.append(element("li", "", `${blockers[blocker.reason] || display(blocker.reason)}${identity ? ` · ${identity}` : ""}`));
      }
      panel.append(list);
    }
    if (context.requirements?.length || context.goal_grounding?.length || context.deferred_obligations?.length) {
      const details = element("details", "nested-detail");
      details.append(element("summary", "", "Vedi requisiti, prove e Goal"));
      for (const requirement of context.requirements || []) {
        const proof = requirement.direct_evidence_state === "unavailable" ? "Prove non disponibili"
          : requirement.direct_evidence_count ? `${requirement.direct_evidence_count} prove dirette registrate` : "Nessuna prova diretta registrata";
        details.append(element("p", "", `${requirement.requirement_id} · ${display(requirement.lifecycle_status)} · ${proof}`));
        for (const entry of requirement.direct_evidence || []) {
          if (entry.evidence_id) details.append(button(`Apri prova ${entry.evidence_id}`, "button-secondary evidence-action", () =>
            loadEvidence({ kind: "verification", identity: entry.evidence_id })));
        }
      }
      for (const goal of context.goal_grounding || []) {
        const grounding = goal.gaps?.includes("implementation_grounding_missing")
          ? "Collegamento al codice non registrato" : display(goal.state);
        details.append(element("p", "", `${goal.goal_node_id} · ${goal.title || "Goal"} · ${grounding}`));
      }
      for (const obligation of context.deferred_obligations || []) {
        const timing = obligation.applicability === "acceptance_prerequisite" ? "Richiesta per l’accettazione" : "Obbligo del pacchetto";
        details.append(element("p", "", `${timing} · ${obligation.statement} · ${display(obligation.state)}`));
      }
      panel.append(details);
    }
    if (context.truncated) panel.append(element("p", "truncation-note", "Vista parziale. Apri le prove collegate per il dettaglio."));
    return panel;
  }

  async function loadAcceptance(section, identity) {
    if (!state.project) return;
    const epoch = ++state.evidenceEpoch;
    const projectId = state.project.project_id;
    $("evidence-kind-label").textContent = "Evidenza conservata";
    $("evidence-title").textContent = "Prove e accettazione";
    loading($("evidence-content"), "Lettura degli obblighi registrati…");
    if (!$("evidence-dialog").open) $("evidence-dialog").showModal();
    try {
      const query = new URLSearchParams({ scope_id: identity, limit: 25 });
      const result = await request(`projects/${encodeURIComponent(projectId)}/sections/${section}?${query}`);
      if (epoch !== state.evidenceEpoch || !$("evidence-dialog").open || state.project?.project_id !== projectId) return;
      $("evidence-content").replaceChildren(acceptancePanel(result.summary.acceptance_context));
    } catch (error) {
      if (state.ready && !error.stale && epoch === state.evidenceEpoch && $("evidence-dialog").open && state.project?.project_id === projectId) {
        $("evidence-content").replaceChildren(errorPanel(error, () => loadAcceptance(section, identity)));
      }
    }
  }

  function renderArchitectureExports(current) {
    const panel = element("section", "summary-block");
    panel.append(element("h3", "", "Esporta architettura"));
    const open = (revision) => loadDocument(`documents/architecture?revision=${revision}`,
      { title: `Architettura · revisione ${revision}`, label: "Esportazione Markdown" });
    if (current > 0) {
      panel.append(button(`Apri revisione adottata r${current}`, "button-secondary evidence-action", () => open(current)));
    } else {
      panel.append(element("p", "state-note", "Nessuna revisione adottata. Consulta la cronologia per eventuali proposte."));
    }
    const history = element("details", "nested-detail");
    const list = element("div", "item-list");
    const status = element("p", "state-note");
    status.setAttribute("aria-live", "polite");
    let page = null;
    const project = state.project.project_id;
    const active = () => history.isConnected && state.section === "architecture" && state.project?.project_id === project;
    const previous = button("Revisioni precedenti", "button-secondary evidence-action",
      () => loadHistory(Math.max(0, page.offset - page.limit)));
    const next = button("Altre revisioni", "button-secondary evidence-action", () => loadHistory(page.next_offset));
    const retry = button("Riprova", "button-secondary evidence-action", () => loadHistory(requestedOffset));
    let requestedOffset = 0;
    previous.hidden = next.hidden = retry.hidden = true;
    history.append(element("summary", "", "Scegli revisione"), status, list, previous, next, retry);
    history.addEventListener("toggle", () => {
      if (history.open && !page && !next.disabled) loadHistory(0);
    });
    panel.append(history);
    return panel;

    async function loadHistory(offset) {
      if (!active()) return;
      requestedOffset = offset;
      previous.disabled = next.disabled = retry.disabled = true;
      retry.hidden = true;
      status.textContent = "Lettura delle revisioni…";
      try {
        const result = await request(`projects/${encodeURIComponent(project)}/documents/architecture/history?offset=${offset}`);
        if (!active()) return;
        list.replaceChildren();
        for (const item of result.items) {
          const tag = item.revision === result.current_adopted_revision ? "Adottata corrente"
            : item.state === "adopted" ? "Adottata storica" : "Proposta";
          const row = element("div");
          row.append(button(`Apri r${item.revision} · ${tag}`, "button-secondary evidence-action",
            () => open(item.revision)));
          list.append(row);
        }
        page = result.bounds;
        status.textContent = page.total === 0 ? "Nessuna revisione registrata." : "";
        previous.hidden = page.offset === 0;
        next.hidden = page.next_offset === null;
      } catch (error) {
        if (!active() || error.stale) return;
        status.textContent = error.message;
        retry.hidden = false;
      } finally {
        previous.disabled = next.disabled = retry.disabled = false;
      }
    }
  }

  function renderSection(result) {
    const container = $("section-content");
    container.replaceChildren(element("p", "section-intro", sections[state.section].description));
    if (state.section === "overview") {
      container.append(button("Esporta tutti i requisiti", "button-secondary evidence-action", () =>
        loadRequirementsDocument("project", "", "Catalogo dei requisiti")));
    }
    const { acceptance_context: acceptanceContext, ...summary } = result.summary || {};
    if (state.section === "architecture") container.append(renderArchitectureExports(summary.current_adopted_revision));
    if (state.section === "overview" && summary.next_gate) {
      const attention = element("section", "attention");
      attention.append(element("h3", "", "Prossimo punto di controllo"));
      const gate = summary.next_gate;
      const explanation = gate.message || gate.resolution || gate.reason || gate.operation || "Apri il dettaglio del punto di controllo.";
      attention.append(element("p", "", display(explanation)));
      const detail = element("details", "nested-detail");
      detail.append(element("summary", "", "Vedi obbligo e riferimenti"), fields(gate));
      attention.append(detail);
      const failures = gate.verification_recovery?.failed_evidence || [];
      for (const proof of failures) {
        if (proof.evidence_id) attention.append(button(`Apri prova fallita ${proof.evidence_id}`, "button-secondary evidence-action", () =>
          loadEvidence({ kind: "verification", identity: proof.evidence_id })));
      }
      container.append(attention);
    }
    if (state.section === "overview" && acceptanceContext) {
      container.append(acceptancePanel(acceptanceContext));
    }
    if (state.section === "verification") {
      container.append(renderVerificationChannels(summary));
      if (["external_report", "repository_review"].includes(summary.channel)) {
        container.append(element("p", "state-note", "Questi record conservano il pin e la provenienza originali. Il pacchetto mostra separatamente l’applicabilità attuale."));
      }
    } else if (Object.keys(summary).length) {
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
    } else if (state.section === "verification") {
      container.append(empty("Nessun elemento in questo canale", "Consulta gli altri canali per vedere le prove e le review già conservate."));
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
      const query = new URLSearchParams({ offset: state.sectionOffset, limit: 25 });
      if (section === "verification") {
        query.set("channel", state.verificationChannel);
        if (state.verificationScope) query.set("scope_id", state.verificationScope);
      }
      const result = await request(`projects/${encodeURIComponent(projectId)}/sections/${section}?${query}`);
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
    updateNetworkControls();
    updateArchiveControls();
    updateUpgradeControls();
    updateDeleteControls();
    const banner = $("maintenance-banner");
    banner.hidden = state.maintenance.state === "ready";
    banner.textContent = state.maintenance.state === "recovery_required"
      ? "Un’eliminazione precedente richiede il recupero da riga di comando."
      : "Flower è in manutenzione per la gestione di un progetto. Le chat possono riprovare al termine.";
  }

  function updateDashboardStatus(status) {
    const version = status.distribution?.distribution_version;
    $("sidebar-version").textContent = typeof version === "string" && version
      ? `Flower MCP ${version}` : "Versione Flower non disponibile";
    updateMaintenance(status.maintenance || status);
  }

  async function checkMaintenance() {
    if (document.visibilityState !== "visible" || state.adminBusy || state.authBusy) return;
    if (!state.ready) { await startDashboard(); return; }
    try {
      const result = await request("status");
      updateDashboardStatus(result);
      if (state.upgradeStatus?.operation?.reason !== "upgrade_worker_unconfirmed"
          && (state.rememberedUpgrade || upgradeInProgress())) loadUpgrade();
      if (state.connectionWarning) { notice(""); state.connectionWarning = false; }
    } catch (error) {
      notice(error.message, true);
      state.connectionWarning = true;
    }
  }

  function openDeletion(project) {
    if (!project || !state.ready || state.adminBusy || state.maintenance.state !== "ready") return;
    notice("");
    state.deletion = { projectId: project.project_id, readback: false };
    $("delete-project-name").textContent = project.name;
    $("delete-project-id").textContent = project.project_id;
    $("delete-form").reset();
    formMessage("delete-message", "");
    updateDeleteControls();
    $("delete-dialog").showModal();
    $("confirm-project").focus();
  }

  function updateDeleteControls() {
    const readback = state.deletion?.readback === true;
    const id = $("confirm-project");
    const password = $("delete-password");
    const confirm = $("confirm-delete-button");
    const cancel = $("delete-cancel");
    $("delete-close").disabled = cancel.disabled = state.adminBusy;
    id.readOnly = password.readOnly = state.adminBusy;
    $("delete-fields").hidden = confirm.hidden = readback;
    cancel.textContent = readback ? "Torna ai progetti" : "Annulla";
    confirm.disabled = !state.deletion || state.adminBusy || readback || state.maintenance.state !== "ready"
      || id.value !== state.deletion.projectId || !password.value;
  }

  function closeDeletion() {
    if (state.adminBusy) return;
    const deletion = state.deletion;
    $("delete-dialog").close();
    if (deletion?.readback) {
      $("project-search").value = deletion.projectId;
      state.projectOffset = 0;
      navigate(null);
    }
  }

  async function deleteProject(event) {
    event.preventDefault();
    if ($("confirm-delete-button").disabled) return;
    const deletion = state.deletion;
    const passwordInput = $("delete-password");
    const password = passwordInput.value;
    passwordInput.value = "";
    state.adminBusy = true;
    updateDeleteControls();
    formMessage("delete-message", "Eliminazione in corso…");
    let result;
    let error;
    try {
      result = await request(`projects/${encodeURIComponent(deletion.projectId)}/deletion/delete`,
        { confirm_project_id: $("confirm-project").value, password }, { timeoutMs: 27000 });
    } catch (failure) {
      error = failure;
      result = failure.envelope?.result;
    } finally {
      state.adminBusy = false;
    }
    if (deletion !== state.deletion || error?.stale) return;
    if (result?.maintenance) updateMaintenance(result.maintenance);
    const outcome = result?.deletion;
    if (!error && outcome?.deletion_state === "scrubbed") {
      $("delete-dialog").close();
      state.projectOffset = 0;
      navigate(null);
      notice("I dati del progetto in Flower sono stati eliminati.");
      return;
    }
    let message = error?.message || outcome?.diagnostics?.[0]?.message || "L’eliminazione non è stata eseguita.";
    if (outcome?.project_effect_state === "applied") {
      message = "I dati del progetto sono stati rimossi. La pulizia del database è rimasta incompleta.";
      deletion.readback = true;
    } else if (outcome?.deletion_state === "absent" || error?.reason === "dashboard_project_not_found") {
      message = "Il progetto non è più presente. Torna ai progetti per aggiornare l’elenco.";
      deletion.readback = true;
    } else if (outcome?.project_effect_state === "unknown"
        || (outcome?.project_effect_state !== "none" && (!error?.status || error.status >= 500))) {
      message = "L’esito dell’eliminazione è incerto. Rileggi l’elenco dei progetti prima di una nuova richiesta.";
      deletion.readback = true;
    }
    formMessage("delete-message", message, true);
    updateDeleteControls();
    $(deletion.readback ? "delete-cancel" : "delete-password").focus();
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
      restoreUpgrade();
      updateDashboardStatus(status);
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
      restoreUpgrade();
      updateDashboardStatus(status);
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
      if (error.stale) return;
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
  $("settings-refresh").addEventListener("click", () => {
    loadSettings();
    loadNetwork();
  });
  $("settings-basic").addEventListener("click", () => showSettingsSection("basic"));
  $("settings-advanced").addEventListener("click", () => showSettingsSection("advanced"));
  $("settings-form").addEventListener("submit", (event) => { event.preventDefault(); saveSettings(); });
  $("settings-discard").addEventListener("click", () => saveSettings(true));
  $("network-form").addEventListener("input", updateNetworkControls);
  $("network-form").addEventListener("submit", saveNetwork);
  $("upgrade-refresh").addEventListener("click", loadUpgrade);
  $("upgrade-version").addEventListener("input", changeUpgradeVersion);
  $("upgrade-preview-form").addEventListener("submit", previewUpgrade);
  $("upgrade-open").addEventListener("click", openUpgrade);
  $("upgrade-apply-form").addEventListener("submit", applyUpgrade);
  $("upgrade-password").addEventListener("input", updateUpgradeControls);
  $("upgrade-close").addEventListener("click", () => $("upgrade-dialog").close());
  $("upgrade-dialog").addEventListener("cancel", (event) => { if (state.upgradeBusy) event.preventDefault(); });
  $("upgrade-dialog").addEventListener("close", () => { $("upgrade-password").value = ""; });
  $("backups-button").addEventListener("click", () => {
    notice("");
    navigate(null, "backups");
  });
  $("backups-refresh").addEventListener("click", loadBackups);
  $("backup-create").addEventListener("click", createBackup);
  $("import-open").addEventListener("click", openImport);
  $("import-form").addEventListener("input", updateArchiveControls);
  $("import-form").addEventListener("submit", importProject);
  $("import-close").addEventListener("click", () => $("import-dialog").close());
  $("import-cancel").addEventListener("click", () => $("import-dialog").close());
  $("import-dialog").addEventListener("cancel", (event) => { if (state.archiveBusy) event.preventDefault(); });
  $("import-dialog").addEventListener("close", () => $("import-form").reset());
  $("restore-open").addEventListener("click", openRestore);
  $("restore-form").addEventListener("input", updateArchiveControls);
  $("restore-form").addEventListener("submit", restoreArchive);
  $("restore-close").addEventListener("click", () => $("restore-dialog").close());
  $("restore-cancel").addEventListener("click", () => $("restore-dialog").close());
  $("restore-dialog").addEventListener("cancel", (event) => { if (state.archiveBusy) event.preventDefault(); });
  $("restore-dialog").addEventListener("close", () => $("restore-form").reset());
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
  $("delete-form").addEventListener("input", updateDeleteControls);
  $("delete-form").addEventListener("submit", deleteProject);
  $("delete-close").addEventListener("click", closeDeletion);
  $("delete-cancel").addEventListener("click", closeDeletion);
  $("delete-dialog").addEventListener("close", () => {
    if ($("delete-dialog").open) return;
    state.deletion = null;
    $("delete-form").reset();
  });
  $("delete-dialog").addEventListener("cancel", (event) => {
    event.preventDefault();
    closeDeletion();
  });
  $("evidence-close").addEventListener("click", () => $("evidence-dialog").close());
  $("evidence-dialog").addEventListener("close", () => { if (!$("evidence-dialog").open) state.evidenceEpoch += 1; });
  window.addEventListener("popstate", () => { if (state.ready) route(); });
  let searchTimer;
  $("project-search").addEventListener("input", () => { clearTimeout(searchTimer); searchTimer = setTimeout(() => { state.projectOffset = 0; loadProjects(); }, 250); });
  document.addEventListener("visibilitychange", checkMaintenance);
  window.addEventListener("pagehide", () => {
    showLogin("", { reset: true });
    for (const controller of dashboardRequests) controller.abort();
  });
  window.addEventListener("pageshow", (event) => {
    if (event.persisted) {
      showLogin("", { reset: true });
      window.location.reload();
    }
  });
  setInterval(checkMaintenance, 15000);

  startDashboard();
})();
