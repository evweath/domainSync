/**
 * domainSync — Frontend Alpine.js application v2.0
 * Covers all features F01-F74 (except F68 which was excluded).
 */

function app() {
  return {
    // Auth
    authenticated: false,
    loginForm: { username: 'admin', password: '' },
    loginError: '',

    // UI state
    darkMode: localStorage.getItem('darkMode') === 'true',
    currentView: 'dashboard',
    selectedProduct: null,
    productMatches: [],          // competitor matches for the selected product
    productMatchesLoading: false,
    selectedCompetitor: null,
    toasts: [],
    _toastId: 0,

    // Nav items
    navItems: [
      { id: 'dashboard',    icon: '📊', label: 'Dashboard',        badge: 0 },
      { id: 'scans',        icon: '🔍', label: 'Scans',             badge: 0 },
      { id: 'duplicates',   icon: '🔁', label: 'Duplicates',        badge: 0 },
      { id: 'store-compare',   icon: '🔀', label: 'Store Compare',      badge: 0 },
      { id: 'shopify-sync',     icon: '🛍️', label: 'Shopify Sync',        badge: 0 },
      { id: 'live-sync',        icon: '⚡', label: 'Live Sync',           badge: 0 },
      { id: 'sync',         icon: '🔄', label: 'Source Sync',        badge: 0 },
      { id: 'system-of-record', icon: '🏛️', label: 'System of Record',   badge: 0 },
      { id: 'scheduler',    icon: '⏰', label: 'Scheduler',         badge: 0 },
      { id: 'reports',      icon: '📋', label: 'Reports',           badge: 0 },
      { id: 'export',       icon: '📤', label: 'Export',            badge: 0 },
      { id: 'settings',     icon: '⚙️',  label: 'Settings',         badge: 0 },
    ],

    // Dashboard
    stats: {},

    // Scans
    scanSessions: { sessions: [] },
    sourceSites: [],
    scanRunning: false,
    activeScanId: null,
    scanStatus: { message: '', current: 0, total: 0 },

    // Duplicates
    duplicates: { candidates: [] },
    dupFilter: 'pending',
    dupSelected: {},
    dupDomainFilters: {},

    // Dashboard live log tail
    logTail: [],
    logLevelFilter: 'all',  // 'all' | 'INFO' | 'WARNING' | 'CRITICAL'
    _logPollTimer: null,

    // Store Comparison
    storeComp: { products: [], total: 0, page: 1, pages: 1, source_sites: [] },
    storeCompFilters: {
      search: '', manufacturer: '', category: '', source_site: '',
      min_price: '', max_price: '', in_stock: '',
      has_diffs: false, missing_from: '', has_empty: [],
      sort_by: 'title', sort_order: 'asc',
    },
    storeCompExpanded: {},
    storeCompSaving: {},

    // Shopify Live Sync (API-based)
    liveSyncStep: 'configure',   // 'configure' | 'scanning' | 'review' | 'executing' | 'done'
    liveSyncSource: '',
    liveSyncDest: '',
    liveSyncFields: ['title','body_html','vendor','product_type','tags','variants','images','collections'],
    liveSyncFieldOptions: [
      {id:'title',label:'Title'},
      {id:'body_html',label:'Description'},
      {id:'vendor',label:'Vendor'},
      {id:'product_type',label:'Product Type'},
      {id:'tags',label:'Tags'},
      {id:'variants',label:'Variants & Pricing'},
      {id:'images',label:'Images'},
      {id:'collections',label:'Collections'},
    ],
    liveSyncIncludeNew: true,
    liveSyncIncludeDeletes: false,
    liveSyncWarningsOn: true,    // default: always warn
    liveSyncScanStatus: {},      // domain -> {product_count, shop_name}
    liveSyncScanProgress: {},    // domain -> status string
    liveSyncTransactions: [],
    liveSyncRiskCounts: {},
    liveSyncFilter: 'all',       // 'all'|'pending'|'approved'|'rejected'|'LOW'|'MEDIUM'|'HIGH'|'CRITICAL'
    liveSyncSearch: '',
    liveSyncExecuting: false,
    liveSyncResults: null,
    liveSyncShowDisableWarning: false,

    // Shopify Sync (CSV export — existing)
    shopifySyncConfig: { attribute_groups: [], source_sites: [] },
    shopifySyncSource: '',
    shopifySyncGroups: {},   // group_id -> 'MERGE'|'REPLACE'|'SKIP'
    shopifySyncScope: 'all',
    shopifySyncSearch: '',
    shopifySyncPreview: null,
    shopifySyncLoading: false,
    shopifySyncExporting: false,

    // System of Record (primary = donut-equipment.com vs other source domains)
    sorPrimary: 'donut-equipment.com',
    sorCompareTo: 'donut-supplies.com',
    sorTab: 'missing',  // 'missing' | 'differing' | 'matching' | 'fuzzy'
    sorData: null,
    sorLoading: false,
    sorFuzzyData: null,
    sorFuzzyLoading: false,
    sorFuzzyThreshold: 60,

    // Source Sync / Domain Comparison
    domainComparison: { products: [], total: 0, all_domains: [], page: 1, pages: 1 },
    domainCompPage: 1,
    domainCompShowAll: false,
    syncSelected: {},   // { product_id: true/false }
    cycleStatus: { status: 'idle', domains_complete: [], domains_started: [], dedup_done: false, last_complete_at: null },
    taskList: [],
    parallelScanRunning: false,

    productSort: { col: '', dir: 'asc' },
    dupSort: { col: '', dir: 'asc' },
    sourceProductSort: { col: '', dir: 'asc' },

    // Scheduler
    jobs: [],
    newJob: {
      name: '', job_type: 'source_scan', target: '',
      schedule_type: 'daily', schedule_value: '09:00', config_json: ''
    },

    // Reports
    reportFrame: '',
    reportType: 'summary',
    reportParams: { threshold: 5.0, days: 7, competitor_id: '', product_id: '' },

    // Export
    exportHistory: { records: [] },
    exportForm: { fmt: 'xlsx', include_competitors: true, include_price_history: false },

    // Settings
    settingsData: {},
    webhookForm: { url: '', events: ['price_alert', 'scan_complete', 'competitor_scan_complete'], secret: '' },
    shopifyCredentials: {},    // domain -> { shopify_store_url, shopify_api_key, shopify_access_token }
    shopifyTestStatus: {},     // domain -> 'idle'|'testing'|'ok'|'error'
    shopifyConnLog: [],        // recent Shopify connection-attempt log lines
    shopifyConnLogTimer: null, // setInterval handle for polling the connection log
    shopifyTestMessage: {},    // domain -> string
    newSiteForm: { show: false, name: '', shopify_store_url: '', is_destination: false },
    removeSiteConfirm: null,   // domain pending removal confirmation

    // Shopify Webhook Management (per store)
    shopifyWebhooks: {},       // domain -> { live: [], saved: [], liveLoading, savedLoading, acting, error }

    managedLists: { manufacturers: [], excluded: [], competitors: [] },
    newManagedUrl: { manufacturer: '', excluded: '', competitor: '' },

    // WebSocket
    ws: null,
    wsConnected: false,
    _wsReconnectTimer: null,

    // -----------------------------------------------------------------------
    // Lifecycle
    // -----------------------------------------------------------------------
    async init() {
      this.$watch('darkMode', v => localStorage.setItem('darkMode', v));
      await this.checkAuth();
      if (this.authenticated) await this.postLoginInit();
    },

    async postLoginInit() {
      await Promise.all([
        this.loadStats(),
        this.loadScanSessions(),
        this.loadSettings(),
        this.loadManagedLists(),
        this.loadJobs(),
        this.loadExportHistory(),
        this.loadCycleStatus(),
      ]);
      this.loadDuplicates();
      this.loadSourceSites();
      this.connectWebSocket();
      // Initial population; subsequent updates arrive via the WebSocket
      // 'log_tail' event (see handleWsMessage). The setInterval poll is a
      // safety net in case the WS disconnects and the reconnect lags.
      this.loadLogTail();
      this._logPollTimer = setInterval(() => {
        if (!this.wsConnected) this.loadLogTail();
      }, 5000);
      // Poll the Shopify connection log while the Settings view is open.
      this.startShopifyConnLog();
      // Wire up column resizers for every current and future table.
      this._initColumnResize();
    },

    // -----------------------------------------------------------------------
    // Resizable table columns
    // Drag the right edge of any <th> to resize. Widths persist per
    // (table-key, column-index) in localStorage so reloads keep user choices.
    // -----------------------------------------------------------------------
    _initColumnResize() {
      if (this._colResizeInit) return;
      this._colResizeInit = true;
      const wire = () => document.querySelectorAll('table').forEach(t => this._wireTableResize(t));
      wire();
      // Re-wire when new tables/rows appear from x-for templates.
      const obs = new MutationObserver(muts => {
        let touched = false;
        for (const m of muts) {
          for (const n of m.addedNodes) {
            if (n.nodeType !== 1) continue;
            if (n.tagName === 'TABLE' || n.querySelector?.('table')) { touched = true; break; }
          }
          if (touched) break;
        }
        if (touched) wire();
      });
      obs.observe(document.body, { childList: true, subtree: true });
    },

    _tableKey(table) {
      // Identify a table by its closest view container (x-show="currentView === '...'")
      // plus its position within that container, so persisted widths survive re-renders.
      let view = 'global';
      let el = table.parentElement;
      while (el) {
        const m = (el.getAttribute?.('x-show') || '').match(/currentView\s*===\s*'([^']+)'/);
        if (m) { view = m[1]; break; }
        el = el.parentElement;
      }
      const sameViewTables = Array.from(document.querySelectorAll(`[x-show*="${view}"] table, [x-show*="'${view}'"] table`));
      const idx = sameViewTables.indexOf(table);
      return `colw:${view}:${idx >= 0 ? idx : 0}`;
    },

    _wireTableResize(table) {
      if (table.__colResizeWired) return;
      const ths = table.querySelectorAll(':scope > thead > tr > th');
      if (!ths.length) return;
      table.__colResizeWired = true;

      const key = this._tableKey(table);
      let saved = {};
      try { saved = JSON.parse(localStorage.getItem(key) || '{}'); } catch {}
      const hasSaved = Object.keys(saved).length > 0;

      // Pin the table to fixed layout (using either saved widths or each
      // column's current natural width). Called once, before the first
      // resize event or immediately if there are persisted widths.
      const pinTable = () => {
        if (table.__pinned) return;
        ths.forEach((th, i) => {
          const w = saved[i] || th.offsetWidth;
          if (w > 0) {
            th.style.width = w + 'px';
            th.style.minWidth = w + 'px';
          }
        });
        table.style.tableLayout = 'fixed';
        table.classList.add('col-resize-active');
        table.__pinned = true;
      };
      if (hasSaved) pinTable();

      ths.forEach((th, i) => {
        const cs = getComputedStyle(th);
        if (cs.position === 'static') th.style.position = 'relative';
        if (i === ths.length - 1) return;  // skip grip on last column
        const grip = document.createElement('span');
        grip.className = 'col-resize-grip';
        grip.title = 'Drag to resize · double-click to reset';
        th.appendChild(grip);

        let startX = 0, startW = 0;
        const onMove = e => {
          const dx = e.pageX - startX;
          const w = Math.max(40, startW + dx);
          th.style.width = w + 'px';
          th.style.minWidth = w + 'px';
        };
        const onUp = () => {
          document.removeEventListener('mousemove', onMove);
          document.removeEventListener('mouseup', onUp);
          document.body.style.cursor = '';
          document.body.classList.remove('col-resizing');
          try {
            const cur = JSON.parse(localStorage.getItem(key) || '{}');
            cur[i] = Math.round(th.offsetWidth);
            localStorage.setItem(key, JSON.stringify(cur));
          } catch {}
        };
        grip.addEventListener('mousedown', e => {
          e.preventDefault();
          e.stopPropagation();
          pinTable();
          startX = e.pageX;
          startW = th.offsetWidth;
          document.body.style.cursor = 'col-resize';
          document.body.classList.add('col-resizing');
          document.addEventListener('mousemove', onMove);
          document.addEventListener('mouseup', onUp);
        });
        grip.addEventListener('dblclick', e => {
          e.preventDefault();
          e.stopPropagation();
          th.style.width = '';
          th.style.minWidth = '';
          try {
            const cur = JSON.parse(localStorage.getItem(key) || '{}');
            delete cur[i];
            localStorage.setItem(key, JSON.stringify(cur));
          } catch {}
        });
      });
    },

    // -----------------------------------------------------------------------
    // Auth
    // -----------------------------------------------------------------------
    async checkAuth() {
      try {
        const r = await fetch('/api/auth/status');
        const d = await r.json();
        if (d.authenticated || !d.auth_enabled) this.authenticated = true;
      } catch {}
    },

    async doLogin() {
      this.loginError = '';
      try {
        const r = await fetch('/api/auth/login', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(this.loginForm),
        });
        if (r.ok) {
          this.authenticated = true;
          await this.postLoginInit();
        } else {
          this.loginError = (await r.json()).detail || 'Invalid credentials';
        }
      } catch { this.loginError = 'Could not reach server.'; }
    },

    async doLogout() {
      await fetch('/api/auth/logout', { method: 'POST' });
      this.authenticated = false;
      if (this.ws) this.ws.close();
    },

    // -----------------------------------------------------------------------
    // Toasts
    // -----------------------------------------------------------------------
    toast(message, type = 'info', duration = 4000) {
      const id = ++this._toastId;
      const icons = { success: '✅', error: '❌', info: 'ℹ️', warning: '⚠️' };
      this.toasts.push({ id, message, type, icon: icons[type] || 'ℹ️' });
      setTimeout(() => this.removeToast(id), duration);
    },
    removeToast(id) { this.toasts = this.toasts.filter(t => t.id !== id); },

    // -----------------------------------------------------------------------
    // API helper
    // -----------------------------------------------------------------------
    async api(path, options = {}) {
      const r = await fetch(path, {
        headers: { 'Content-Type': 'application/json', ...(options.headers || {}) },
        ...options,
      });
      if (r.status === 401) { this.authenticated = false; return null; }
      if (!r.ok) {
        let msg = `HTTP ${r.status}`;
        try { msg = (await r.json()).detail || msg; } catch {}
        throw new Error(msg);
      }
      const ct = r.headers.get('content-type') || '';
      if (ct.includes('text/html')) return r.text();
      if (ct.includes('application/json')) return r.json();
      return r.blob();
    },

    // -----------------------------------------------------------------------
    // Dashboard
    // -----------------------------------------------------------------------
    async loadStats() {
      try {
        this.stats = await this.api('/api/stats') || {};
        const dupBadge = this.stats.pending_duplicates || 0;
        const nav = this.navItems.find(n => n.id === 'duplicates');
        if (nav) nav.badge = dupBadge;
      } catch (e) { this.toast('Failed to load stats: ' + e.message, 'error'); }
    },

    // -----------------------------------------------------------------------
    // Scans
    // -----------------------------------------------------------------------
    loadSourceSites() {
      if (this.settingsData?.source_sites) {
        this.sourceSites = this.settingsData.source_sites.filter(s => s.enabled);
        if (!Object.keys(this.dupDomainFilters).length) {
          const filters = {};
          this.sourceSites.forEach(s => { filters[s.domain] = true; });
          this.dupDomainFilters = filters;
        }
      }
    },

    async startScan(siteFilter = null) {
      if (this.scanRunning) return;
      this.scanRunning = true;
      this.scanStatus = { message: 'Starting scan...', current: 0, total: 0 };
      try {
        const body = siteFilter ? { site_filter: siteFilter } : {};
        const r = await this.api('/api/scan/sources', { method: 'POST', body: JSON.stringify(body) });
        if (r) {
          this.activeScanId = r.scan_session_id;
          this.toast('Source scan started', 'info');
          await this.loadScanSessions();
        }
      } catch (e) {
        this.scanRunning = false;
        this.toast('Failed to start scan: ' + e.message, 'error');
      }
    },

    async loadScanSessions() {
      try {
        this.scanSessions = await this.api('/api/scan/sessions?per_page=20') || { sessions: [] };
        const running = (this.scanSessions.sessions || []).find(s => s.status === 'running');
        if (running && !this.scanRunning) {
          this.scanRunning = true;
          this.activeScanId = running.id;
          this.scanStatus = { message: 'Scan in progress...' };
        } else if (!running && this.scanRunning) {
          this.scanRunning = false;
          this.scanStatus = {};
          await this.loadStats();
          this.toast('Scan completed', 'success');
        }
      } catch {}
    },

    // -----------------------------------------------------------------------
    // Deduplication
    // -----------------------------------------------------------------------
    async runDedup() {
      try {
        const selected = Object.entries(this.dupDomainFilters).filter(([, v]) => v).map(([k]) => k);
        const body = selected.length && selected.length < this.sourceSites.length
          ? { domain_filters: selected }
          : {};
        await this.api('/api/dedup/run', { method: 'POST', body: JSON.stringify(body) });
        this.toast('Deduplication started in background...', 'info');
      } catch (e) { this.toast('Failed to start dedup: ' + e.message, 'error'); }
    },

    async loadDuplicates() {
      try {
        const params = new URLSearchParams({ status: this.dupFilter, per_page: 50 });
        this.duplicates = await this.api(`/api/dedup/candidates?${params}`) || { candidates: [] };
        this.dupSelected = {};
      } catch {}
    },

    async resolvedup(candidateId, action) {
      try {
        await this.api(`/api/dedup/candidates/${candidateId}/resolve`, {
          method: 'POST', body: JSON.stringify({ action }),
        });
        this.toast(action === 'merge' ? 'Products merged' : 'Duplicate rejected', 'success');
        await this.loadDuplicates();
        await this.loadStats();
      } catch (e) { this.toast('Failed to resolve: ' + e.message, 'error'); }
    },

    dupSelectedCount() {
      return Object.values(this.dupSelected).filter(Boolean).length;
    },

    dupAllSelected() {
      const candidates = this.duplicates.candidates || [];
      return candidates.length > 0 && candidates.every(d => this.dupSelected[d.id]);
    },

    dupToggleSelectAll() {
      const candidates = this.duplicates.candidates || [];
      const selectAll = !this.dupAllSelected();
      const updated = {};
      candidates.forEach(d => { updated[d.id] = selectAll; });
      this.dupSelected = updated;
    },

    async deleteSelectedDups() {
      const ids = Object.entries(this.dupSelected).filter(([, v]) => v).map(([k]) => parseInt(k));
      if (!ids.length) return;
      try {
        const res = await this.api('/api/dedup/candidates/bulk-delete', {
          method: 'POST', body: JSON.stringify({ candidate_ids: ids }),
        });
        this.toast(`Deleted ${res.deleted} duplicate${res.deleted !== 1 ? 's' : ''}`, 'success');
        await this.loadDuplicates();
        await this.loadStats();
      } catch (e) { this.toast('Failed to delete: ' + e.message, 'error'); }
    },

    async dupSelectAllPages() {
      try {
        const res = await this.api(`/api/dedup/candidates/ids?status=${this.dupFilter}`);
        const all = {};
        (res.ids || []).forEach(id => { all[id] = true; });
        this.dupSelected = all;
        this.toast(`Selected ${res.ids.length} duplicate${res.ids.length !== 1 ? 's' : ''} across all pages`, 'info');
      } catch (e) { this.toast('Failed to select all: ' + e.message, 'error'); }
    },

    // -----------------------------------------------------------------------
    // Dashboard — live log tail + cycle status helpers
    // -----------------------------------------------------------------------
    async loadLogTail() {
      try {
        const r = await this.api('/api/logs/tail?lines=50');
        if (r === null) {
          // 401 — session expired, stop polling
          if (this._logPollTimer) { clearInterval(this._logPollTimer); this._logPollTimer = null; }
          return;
        }
        this.logTail = r.lines || [];
      } catch {}
    },

    logLineClass(line) {
      // Color-code by Python logging level — formatter writes "[LEVEL]" tokens.
      if (!line) return 'text-gray-400';
      if (/\[CRITICAL\]/.test(line)) return 'bg-red-900 text-red-200 font-bold';
      if (/\[ERROR\]|\bTraceback\b/.test(line)) return 'text-red-400';
      if (/\[WARNING\]|\[WARN\]/.test(line)) return 'text-amber-300';
      if (/\[DEBUG\]/.test(line)) return 'text-gray-500';
      if (/\[INFO\]/.test(line)) return 'text-sky-300';
      return 'text-gray-200';
    },

    // Detect a log level token at the start of a record line. Continuation
    // lines (no timestamp) return null and inherit the previous record's level.
    _lineLevel(line) {
      if (!line) return null;
      if (/\[CRITICAL\]/.test(line)) return 'CRITICAL';
      if (/\[ERROR\]|\bTraceback\b/.test(line)) return 'ERROR';
      if (/\[WARNING\]|\[WARN\]/.test(line)) return 'WARNING';
      if (/\[INFO\]/.test(line)) return 'INFO';
      if (/\[DEBUG\]/.test(line)) return 'DEBUG';
      return null;
    },

    get filteredLogTail() {
      const lines = this.logTail || [];
      if (this.logLevelFilter === 'all') return lines;
      const target = this.logLevelFilter;
      const out = [];
      let currentLevel = null;
      for (const ln of lines) {
        const lvl = this._lineLevel(ln);
        if (lvl) currentLevel = lvl;
        if (currentLevel === target) out.push(ln);
      }
      return out;
    },

    cycleStatusLabel() {
      const s = this.cycleStatus?.status || 'idle';
      if (s === 'scanning' && this.scanStatus?.message) return this.scanStatus.message;
      const started = this.cycleStatus?.domains_started?.length || 0;
      const done = this.cycleStatus?.domains_complete?.length || 0;
      return {
        idle: 'No scan running',
        scanning: `Scanning source domains (${done}/${started} complete)`,
        dedup_running: 'Running deduplication across all domains...',
        review_pending: 'Awaiting duplicate review',
        complete: 'Scan cycle complete',
      }[s] || s;
    },

    cycleNextStep() {
      const s = this.cycleStatus?.status || 'idle';
      const done = this.cycleStatus?.domains_complete?.length || 0;
      const total = this.cycleStatus?.domains_started?.length || 0;
      const pending = this.stats?.pending_duplicates || 0;
      const ts = this.cycleStatus?.last_complete_at
        ? new Date(this.cycleStatus.last_complete_at).toLocaleString() : '';
      return {
        idle: 'Click "Scan All Sources" to begin a full data collection cycle.',
        scanning: done < total
          ? `${total - done} domain${total - done !== 1 ? 's' : ''} still scanning — deduplication will start automatically when all finish.`
          : 'All domains scanned — deduplication starting...',
        dedup_running: 'Identifying duplicate products across all source domains. This may take a few minutes.',
        review_pending: pending
          ? `${pending} duplicate${pending !== 1 ? 's' : ''} need review. Go to Duplicates, resolve them, then approve the cycle.`
          : 'Deduplication complete. Approve the cycle to finalize.',
        complete: `Last cycle finished${ts ? ' at ' + ts : ''}. Start a new scan when ready.`,
      }[s] || '';
    },

        // Returns an array of comparison rows for the duplicate card.
    // Each row: { label, primary, secondary, score, mono }
    dupFields(dup) {
      const r = dup.match_reasons || {};
      const p = dup.primary;
      const s = dup.secondary;
      const fp = v => v != null ? '$' + Number(v).toFixed(2) : '—';
      return [
        { label: 'Title',        primary: p.title        || '—', secondary: s.title        || '—', score: r.title_fuzzy,   mono: false },
        { label: 'Price',        primary: fp(p.price),           secondary: fp(s.price),           score: r.price,         mono: false },
        { label: 'Manufacturer', primary: p.manufacturer  || '—', secondary: s.manufacturer  || '—', score: r.manufacturer, mono: false },
        { label: 'Model #',      primary: p.model_number  || '—', secondary: s.model_number  || '—', score: r.model_number, mono: true  },
        { label: 'SKU',          primary: p.sku            || '—', secondary: s.sku            || '—', score: r.sku,          mono: true  },
        { label: 'Sources',      primary: (p.sources||[]).join(', ')||'—', secondary: (s.sources||[]).join(', ')||'—', score: null, mono: false },
      ];
    },

    // Row background class based on match score.
    dupRowClass(score, hasBoth) {
      if (score === null || score === undefined) return 'bg-blue-50 dark:bg-blue-900/20';
      if (!hasBoth) return 'bg-gray-50 dark:bg-gray-700/30';
      if (score >= 80) return 'bg-green-50 dark:bg-green-900/20';
      if (score >= 40) return 'bg-yellow-50 dark:bg-yellow-900/20';
      return 'bg-red-50 dark:bg-red-900/20';
    },

    // One-line explanation of why the confidence score is what it is.
    dupSummary(dup) {
      const r = dup.match_reasons || {};
      if (r.disqualifier === 'model_number_mismatch')
        return 'Model numbers present but conflict — score capped at 5%.';
      if (r.disqualifier === 'sku_mismatch')
        return 'SKUs present but conflict — score capped at 5%.';
      const factors = [
        { name: 'model number', score: r.model_number  || 0 },
        { name: 'price',        score: r.price         || 0 },
        { name: 'manufacturer', score: r.manufacturer  || 0 },
        { name: 'title',        score: r.title_fuzzy   || 0 },
        { name: 'description',  score: r.description   || 0 },
      ].filter(f => f.score > 0).sort((a, b) => b.score - a.score);
      if (!factors.length) return 'No matching signals found.';
      const top = factors.slice(0, 2).map(f => `${f.name} (${Math.round(f.score)}%)`);
      const missing = [
        r.model_number === 0 && dup.primary.model_number && dup.secondary.model_number ? 'model mismatch' : null,
        r.price        === 0 && dup.primary.price        && dup.secondary.price        ? 'price gap'      : null,
      ].filter(Boolean);
      let note = 'Driven by ' + top.join(' and ') + '.';
      if (missing.length) note += ' Limited by ' + missing.join(', ') + '.';
      return note;
    },

    // -----------------------------------------------------------------------
    // Source Sync / Domain Comparison
    // -----------------------------------------------------------------------
    // -----------------------------------------------------------------------
    // System of Record — primary domain vs another source domain
    // -----------------------------------------------------------------------
    async loadSystemOfRecord() {
      this.sorLoading = true;
      this.sorFuzzyData = null;  // invalidate fuzzy results when the pair changes
      try {
        const params = new URLSearchParams({
          primary: this.sorPrimary,
          compare_to: this.sorCompareTo,
        });
        this.sorData = await this.api(`/api/system-of-record?${params}`);
      } catch (e) {
        this.toast('System of Record query failed: ' + e.message, 'error');
        this.sorData = null;
      } finally {
        this.sorLoading = false;
      }
    },

    async loadSystemOfRecordFuzzy() {
      this.sorFuzzyLoading = true;
      try {
        const params = new URLSearchParams({
          primary: this.sorPrimary,
          compare_to: this.sorCompareTo,
          threshold: this.sorFuzzyThreshold,
          limit: 200,
        });
        this.sorFuzzyData = await this.api(`/api/system-of-record/fuzzy?${params}`);
        this.sorTab = 'fuzzy';
      } catch (e) {
        this.toast('Fuzzy match query failed: ' + e.message, 'error');
        this.sorFuzzyData = null;
      } finally {
        this.sorFuzzyLoading = false;
      }
    },

    sorDiffCell(p_val, c_val, field) {
      // Render a single (primary, compare) value pair, highlighting mismatches.
      const fmt = v => {
        if (v == null || v === '') return '—';
        if (field === 'price') return '$' + Number(v).toFixed(2);
        return v;
      };
      return { p: fmt(p_val), c: fmt(c_val) };
    },

    async loadDomainComparison(page = 1) {
      this.domainCompPage = page;
      try {
        const params = new URLSearchParams({ page, per_page: 50, show_all: this.domainCompShowAll });
        this.domainComparison = await this.api(`/api/domain-comparison?${params}`) || { products: [], total: 0, all_domains: [] };
      } catch (e) { this.toast('Failed to load domain comparison: ' + e.message, 'error'); }
    },

    toggleSyncSelect(productId) {
      this.syncSelected[productId] = !this.syncSelected[productId];
    },

    selectAllSync() {
      this.domainComparison.products.forEach(p => { this.syncSelected[p.product_id] = true; });
    },

    clearSyncSelect() {
      this.syncSelected = {};
    },

    syncSelectedCount() {
      return Object.values(this.syncSelected).filter(Boolean).length;
    },

    // -----------------------------------------------------------------------
    // Store Comparison
    // -----------------------------------------------------------------------
    async loadStoreComparison(page = 1) {
      try {
        const f = this.storeCompFilters;
        const params = new URLSearchParams({ page, per_page: 25 });
        if (f.search)       params.set('search', f.search);
        if (f.manufacturer) params.set('manufacturer', f.manufacturer);
        if (f.category)     params.set('category', f.category);
        if (f.source_site)  params.set('source_site', f.source_site);
        if (f.min_price !== '') params.set('min_price', f.min_price);
        if (f.max_price !== '') params.set('max_price', f.max_price);
        if (f.in_stock !== '')  params.set('in_stock', f.in_stock);
        if (f.has_diffs)        params.set('has_diffs', 'true');
        if (f.missing_from !== '') params.set('missing_from', f.missing_from);
        if (f.has_empty.length)    params.set('has_empty', f.has_empty.join(','));
        params.set('sort_by', f.sort_by);
        params.set('sort_order', f.sort_order);
        this.storeComp = await this.api(`/api/products/store-comparison?${params}`) || { products: [], total: 0, page: 1, pages: 1, source_sites: [] };
      } catch (e) { this.toast('Failed to load store comparison: ' + e.message, 'error'); }
    },

    toggleStoreCompExpanded(productId) {
      this.storeCompExpanded = { ...this.storeCompExpanded, [productId]: !this.storeCompExpanded[productId] };
    },

    storeCompCellStatus(canonVal, srcVal, siteExists, fieldType = 'text') {
      if (!siteExists) return 'absent';
      const norm = v => fieldType === 'price'
        ? Number(v || 0).toFixed(2)
        : String(v || '').trim().toLowerCase();
      const cNorm = norm(canonVal);
      const sNorm = norm(srcVal);
      if (!sNorm) return cNorm ? 'missing' : 'empty';
      return sNorm !== cNorm ? 'diff' : 'match';
    },

    storeCompCellClass(canonVal, srcVal, siteExists, fieldType = 'text') {
      const s = this.storeCompCellStatus(canonVal, srcVal, siteExists, fieldType);
      if (s === 'match')   return 'bg-green-50 dark:bg-green-900/10';
      if (s === 'diff')    return 'bg-amber-50 dark:bg-amber-900/30 ring-1 ring-inset ring-amber-300';
      if (s === 'missing') return 'bg-red-50 dark:bg-red-900/20';
      return '';
    },

    storeCompCellIcon(canonVal, srcVal, siteExists, fieldType = 'text') {
      const s = this.storeCompCellStatus(canonVal, srcVal, siteExists, fieldType);
      if (s === 'match')   return '✓';
      if (s === 'diff')    return '≠';
      if (s === 'missing') return '✕';
      return '';
    },

    storeCompSiteSummary(row, site) {
      if (!row.sources[site]) return null;
      const checks = [
        ['title', 'text'], ['manufacturer', 'text'], ['model_number', 'text'],
        ['sku', 'text'], ['category', 'text'], ['description', 'text'],
        ['price', 'price'],
      ];
      const counts = { match: 0, diff: 0, missing: 0 };
      for (const [field, type] of checks) {
        const cVal = field === 'price' ? row.canonical.price_canonical : row.canonical[field];
        const sVal = field === 'price' ? row.sources[site].price : row.sources[site][field];
        const s = this.storeCompCellStatus(cVal, sVal, true, type);
        if (s in counts) counts[s]++;
      }
      return counts;
    },

    storeCompHasActiveFilters() {
      const f = this.storeCompFilters;
      return f.search || f.manufacturer || f.category || f.source_site ||
             f.min_price !== '' || f.max_price !== '' || f.in_stock !== '' ||
             f.has_diffs || f.missing_from !== '' || f.has_empty.length > 0;
    },

    storeCompClearFilters() {
      this.storeCompFilters = {
        search: '', manufacturer: '', category: '', source_site: '',
        min_price: '', max_price: '', in_stock: '',
        has_diffs: false, missing_from: '', has_empty: [],
        sort_by: 'title', sort_order: 'asc',
      };
      this.loadStoreComparison(1);
    },

    async adoptSourceValue(productId, field, value) {
      const payload = { [field]: value };
      this.storeCompSaving = { ...this.storeCompSaving, [productId]: true };
      try {
        await this.api(`/api/products/${productId}/canonical`, {
          method: 'PUT', body: JSON.stringify(payload),
        });
        this.toast(`Updated ${field}`, 'success');
        await this.loadStoreComparison(this.storeComp.page);
      } catch (e) {
        this.toast('Update failed: ' + e.message, 'error');
      } finally {
        this.storeCompSaving = { ...this.storeCompSaving, [productId]: false };
      }
    },

    storeCompFmt(val, field) {
      if (val == null || val === '') return '—';
      if (field === 'price' || field === 'price_canonical' || field === 'price_min' || field === 'price_max')
        return '$' + Number(val).toFixed(2);
      if (field === 'weight') return val + ' lbs';
      if (field === 'in_stock') return val ? 'In Stock' : 'Out of Stock';
      if (typeof val === 'object') return JSON.stringify(val).slice(0, 80);
      return String(val);
    },

    // -----------------------------------------------------------------------
    // Shopify Live Sync (API-based scan → diff → execute)
    // -----------------------------------------------------------------------
    async loadLiveSyncScanStatus() {
      try {
        this.liveSyncScanStatus = await this.api('/api/shopify-live/scan-status') || {};
      } catch {}
    },

    async runLiveScan(domain) {
      if (!domain) return;
      this.liveSyncScanProgress = { ...this.liveSyncScanProgress, [domain]: 'Scanning…' };
      try {
        const result = await this.api('/api/shopify-live/scan', { method: 'POST', body: JSON.stringify({ domain }) });
        this.liveSyncScanStatus = {
          ...this.liveSyncScanStatus,
          [domain]: { product_count: result.product_count, shop_name: result.shop_name },
        };
        this.liveSyncScanProgress = { ...this.liveSyncScanProgress, [domain]: `✓ ${result.product_count} products` };
      } catch (e) {
        this.liveSyncScanProgress = { ...this.liveSyncScanProgress, [domain]: `✗ ${e.message}` };
        this.toast('Scan failed: ' + e.message, 'error');
      }
    },

    async runLiveDiff() {
      if (!this.liveSyncSource || !this.liveSyncDest) {
        this.toast('Select both source and destination stores.', 'error'); return;
      }
      if (this.liveSyncSource === this.liveSyncDest) {
        this.toast('Source and destination must be different stores.', 'error'); return;
      }
      this.liveSyncStep = 'scanning';
      this.liveSyncTransactions = [];
      this.liveSyncResults = null;
      try {
        const result = await this.api('/api/shopify-live/diff', {
          method: 'POST',
          body: JSON.stringify({
            source_domain: this.liveSyncSource,
            dest_domain: this.liveSyncDest,
            selected_fields: this.liveSyncFields,
            include_deletes: this.liveSyncIncludeDeletes,
            include_new: this.liveSyncIncludeNew,
          }),
        });
        this.liveSyncTransactions = result.transactions || [];
        this.liveSyncRiskCounts = result.risk_counts || {};
        // If warnings off: auto-approve all non-CRITICAL
        if (!this.liveSyncWarningsOn) {
          this.liveSyncTransactions.forEach(t => {
            t.approved = t.risk_level !== 'CRITICAL';
          });
        }
        this.liveSyncStep = 'review';
      } catch (e) {
        this.liveSyncStep = 'configure';
        this.toast('Diff failed: ' + e.message, 'error');
      }
    },

    liveSyncFilteredTransactions() {
      let txns = this.liveSyncTransactions;
      if (this.liveSyncFilter === 'pending') txns = txns.filter(t => t.approved === null);
      else if (this.liveSyncFilter === 'approved') txns = txns.filter(t => t.approved === true);
      else if (this.liveSyncFilter === 'rejected') txns = txns.filter(t => t.approved === false);
      else if (['LOW','MEDIUM','HIGH','CRITICAL'].includes(this.liveSyncFilter)) {
        txns = txns.filter(t => t.risk_level === this.liveSyncFilter);
      }
      if (this.liveSyncSearch) {
        const q = this.liveSyncSearch.toLowerCase();
        txns = txns.filter(t =>
          (t.title || '').toLowerCase().includes(q) ||
          (t.handle || '').toLowerCase().includes(q) ||
          (t.field || '').toLowerCase().includes(q)
        );
      }
      return txns;
    },

    liveSyncApproveAll(filter) {
      const txns = filter ? this.liveSyncFilteredTransactions() : this.liveSyncTransactions;
      txns.forEach(t => { t.approved = true; });
      this.liveSyncTransactions = [...this.liveSyncTransactions];
    },

    liveSyncRejectAll(filter) {
      const txns = filter ? this.liveSyncFilteredTransactions() : this.liveSyncTransactions;
      txns.forEach(t => { t.approved = false; });
      this.liveSyncTransactions = [...this.liveSyncTransactions];
    },

    liveSyncToggle(txnId) {
      const t = this.liveSyncTransactions.find(x => x.id === txnId);
      if (!t) return;
      t.approved = t.approved === true ? false : t.approved === false ? null : true;
      this.liveSyncTransactions = [...this.liveSyncTransactions];
    },

    liveSyncApprovedCount() {
      return this.liveSyncTransactions.filter(t => t.approved === true).length;
    },

    liveSyncPendingCount() {
      return this.liveSyncTransactions.filter(t => t.approved === null).length;
    },

    async runLiveExecute() {
      const approvedCount = this.liveSyncApprovedCount();
      if (approvedCount === 0) { this.toast('No transactions approved.', 'error'); return; }
      if (!confirm(`Execute ${approvedCount} approved transaction(s) against ${this.liveSyncDest}? This will make real changes to the destination store.`)) return;
      this.liveSyncExecuting = true;
      this.liveSyncStep = 'executing';
      try {
        const result = await this.api('/api/shopify-live/execute', {
          method: 'POST',
          body: JSON.stringify({
            dest_domain: this.liveSyncDest,
            transactions: this.liveSyncTransactions,
          }),
        });
        this.liveSyncResults = result;
        this.liveSyncStep = 'done';
      } catch (e) {
        this.liveSyncStep = 'review';
        this.toast('Execution failed: ' + e.message, 'error');
      } finally {
        this.liveSyncExecuting = false;
      }
    },

    liveSyncRiskClass(risk) {
      return {
        'LOW':      'bg-green-50 dark:bg-green-900/20 border-green-200 dark:border-green-800',
        'MEDIUM':   'bg-yellow-50 dark:bg-yellow-900/20 border-yellow-200 dark:border-yellow-800',
        'HIGH':     'bg-orange-50 dark:bg-orange-900/20 border-orange-200 dark:border-orange-800',
        'CRITICAL': 'bg-red-50 dark:bg-red-900/20 border-red-200 dark:border-red-800',
      }[risk] || '';
    },

    liveSyncRiskBadge(risk) {
      return {
        'LOW':      'bg-green-100 text-green-700 dark:bg-green-900 dark:text-green-300',
        'MEDIUM':   'bg-yellow-100 text-yellow-700 dark:bg-yellow-900 dark:text-yellow-300',
        'HIGH':     'bg-orange-100 text-orange-700 dark:bg-orange-900 dark:text-orange-300',
        'CRITICAL': 'bg-red-100 text-red-700 dark:bg-red-900 dark:text-red-300',
      }[risk] || '';
    },

    // -----------------------------------------------------------------------
    // Shopify Sync (CSV export)
    // -----------------------------------------------------------------------
    async loadShopifySyncConfig() {
      try {
        const data = await this.api('/api/shopify-sync/config');
        this.shopifySyncConfig = data || { attribute_groups: [], source_sites: [] };
        if (!this.shopifySyncSource && this.shopifySyncConfig.source_sites.length > 0) {
          this.shopifySyncSource = this.shopifySyncConfig.source_sites[0].domain;
        }
        if (Object.keys(this.shopifySyncGroups).length === 0) {
          const defaults = {};
          for (const g of this.shopifySyncConfig.attribute_groups) {
            defaults[g.id] = g.default_command;
          }
          this.shopifySyncGroups = defaults;
        }
      } catch (e) {
        console.error('loadShopifySyncConfig failed', e);
      }
    },

    async toggleShopifySyncDestination(domain, isDestination) {
      try {
        await this.api(`/api/source-sites/${domain}/destination`, {
          method: 'PUT',
          body: JSON.stringify({ is_destination: isDestination }),
        });
        const site = this.shopifySyncConfig.source_sites.find(s => s.domain === domain);
        if (site) site.is_destination = isDestination;
      } catch (e) {
        alert('Failed to save destination setting: ' + e.message);
      }
    },

    async runShopifySyncPreview() {
      if (!this.shopifySyncSource) { alert('Select a source store first.'); return; }
      this.shopifySyncLoading = true;
      this.shopifySyncPreview = null;
      try {
        const body = {
          source_site: this.shopifySyncSource,
          selected_groups: this.shopifySyncGroups,
          product_scope: this.shopifySyncScope,
          search: this.shopifySyncSearch || null,
        };
        this.shopifySyncPreview = await this.api('/api/shopify-sync/preview', { method: 'POST', body: JSON.stringify(body) });
      } catch (e) {
        console.error('shopify sync preview failed', e);
      } finally {
        this.shopifySyncLoading = false;
      }
    },

    async runShopifySyncExport() {
      if (!this.shopifySyncSource) { alert('Select a source store first.'); return; }
      this.shopifySyncExporting = true;
      try {
        const body = {
          source_site: this.shopifySyncSource,
          selected_groups: this.shopifySyncGroups,
          product_scope: this.shopifySyncScope,
          search: this.shopifySyncSearch || null,
        };
        const resp = await fetch('/api/shopify-sync/export', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json', 'Authorization': 'Bearer ' + this.token },
          body: JSON.stringify(body),
        });
        if (!resp.ok) throw new Error(await resp.text());
        const blob = await resp.blob();
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = 'shopify_sync_export.csv';
        a.click();
        URL.revokeObjectURL(url);
      } catch (e) {
        alert('Export failed: ' + e.message);
      } finally {
        this.shopifySyncExporting = false;
      }
    },

    // -----------------------------------------------------------------------
    // Scan Cycle & Parallel Tasks
    // -----------------------------------------------------------------------
    async loadCycleStatus() {
      try {
        this.cycleStatus = await this.api('/api/scan/cycle-status') || { status: 'idle' };
      } catch {}
    },

    async loadTaskList() {
      try {
        this.taskList = (await this.api('/api/tasks')).tasks || [];
      } catch {}
    },

    async startParallelScan() {
      if (this.parallelScanRunning) return;
      if (!confirm('Start a full parallel scan of all source domains? This will scrape all domains simultaneously, then auto-run deduplication.')) return;
      this.parallelScanRunning = true;
      try {
        await this.api('/api/scan/all-sources', { method: 'POST', body: JSON.stringify({}) });
        this.toast('Parallel scan started — all domains scanning simultaneously', 'info');
        await this.loadCycleStatus();
        await this.loadTaskList();
      } catch (e) {
        this.toast('Failed to start scan: ' + e.message, 'error');
        this.parallelScanRunning = false;
      }
    },

    async approveCycle() {
      if (!confirm('Mark this scan cycle as complete and approved? This will allow a new full scan to begin.')) return;
      try {
        await this.api('/api/scan/cycle/approve', { method: 'POST', body: JSON.stringify({}) });
        this.toast('Scan cycle approved — ready for next scan', 'success');
        await this.loadCycleStatus();
        this.parallelScanRunning = false;
      } catch (e) { this.toast('Failed: ' + e.message, 'error'); }
    },

    diffClass(hasDiff) {
      return hasDiff ? 'text-red-600 dark:text-red-400 font-semibold' : 'text-green-600 dark:text-green-400';
    },

    // -----------------------------------------------------------------------
    // Scheduler (F43-F47)
    // -----------------------------------------------------------------------
    async loadJobs() {
      try {
        const r = await this.api('/api/scheduler/jobs');
        this.jobs = r?.jobs || [];
      } catch {}
    },

    async createJob() {
      try {
        const r = await this.api('/api/scheduler/jobs', {
          method: 'POST', body: JSON.stringify(this.newJob),
        });
        this.toast(`Job "${this.newJob.name}" scheduled (next: ${r.next_run || 'N/A'})`, 'success');
        this.newJob = { name: '', job_type: 'source_scan', target: '', schedule_type: 'daily', schedule_value: '09:00', config_json: '' };
        await this.loadJobs();
      } catch (e) { this.toast('Failed to create job: ' + e.message, 'error'); }
    },

    async deleteJob(id) {
      if (!confirm('Delete this scheduled job?')) return;
      try {
        await this.api(`/api/scheduler/jobs/${id}`, { method: 'DELETE' });
        this.toast('Job deleted', 'success');
        await this.loadJobs();
      } catch (e) { this.toast('Failed to delete job: ' + e.message, 'error'); }
    },

    async runJobNow(id) {
      try {
        await this.api(`/api/scheduler/jobs/${id}/run-now`, { method: 'POST' });
        this.toast('Job queued to run now', 'info');
      } catch (e) { this.toast('Failed to run job: ' + e.message, 'error'); }
    },

    async toggleJob(id, active) {
      try {
        await this.api(`/api/scheduler/jobs/${id}/toggle?active=${active}`, { method: 'PUT' });
        await this.loadJobs();
      } catch (e) { this.toast('Failed to toggle job: ' + e.message, 'error'); }
    },

    // -----------------------------------------------------------------------
    // Reports (F61-F63)
    // -----------------------------------------------------------------------
    async loadReport() {
      this.reportFrame = '';
      try {
        let url = '';
        if (this.reportType === 'summary') url = `/api/reports/summary?days=${this.reportParams.days}`;
        else if (this.reportType === 'price_disparity') url = `/api/reports/price-disparity?threshold=${this.reportParams.threshold}`;
        else if (this.reportType === 'competitor' && this.reportParams.competitor_id)
          url = `/api/reports/competitor/${this.reportParams.competitor_id}`;
        else if (this.reportType === 'price_comparison' && this.reportParams.product_id)
          url = `/api/reports/price-comparison/${this.reportParams.product_id}`;
        if (!url) { this.toast('Please fill in required parameters', 'warning'); return; }
        this.reportFrame = await this.api(url);
      } catch (e) { this.toast('Report failed: ' + e.message, 'error'); }
    },

    // -----------------------------------------------------------------------
    // Export (F39-F42)
    // -----------------------------------------------------------------------
    async doExport() {
      const fmt = this.exportForm.fmt;
      const params = new URLSearchParams({ fmt });
      if (fmt === 'xlsx') {
        params.set('include_competitors', this.exportForm.include_competitors);
        params.set('include_price_history', this.exportForm.include_price_history);
      }
      try {
        const r = await fetch(`/api/export/products?${params}`);
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        const blob = await r.blob();
        const disp = r.headers.get('content-disposition') || '';
        const filename = disp.match(/filename=(.+)/)?.[1] || `export.${fmt}`;
        const a = document.createElement('a');
        a.href = URL.createObjectURL(blob);
        a.download = filename;
        a.click();
        URL.revokeObjectURL(a.href);
        this.toast(`Exported as ${filename}`, 'success');
        await this.loadExportHistory();
      } catch (e) { this.toast('Export failed: ' + e.message, 'error'); }
    },

    async loadExportHistory() {
      try { this.exportHistory = await this.api('/api/export/history') || { records: [] }; } catch {}
    },

    // -----------------------------------------------------------------------
    // Settings (F56)
    // -----------------------------------------------------------------------
    async loadShopifyConnLog() {
      try {
        const r = await this.api('/api/shopify/connection-log?n=150');
        const box = document.getElementById('shopifyConnLogBox');
        const atBottom = box ? (box.scrollHeight - box.scrollTop - box.clientHeight < 24) : true;
        this.shopifyConnLog = (r && r.lines) || [];
        // Keep the view pinned to the newest line unless the user scrolled up.
        if (atBottom) this.$nextTick(() => { const b = document.getElementById('shopifyConnLogBox'); if (b) b.scrollTop = b.scrollHeight; });
      } catch (e) { /* panel is best-effort; ignore transient errors */ }
    },

    startShopifyConnLog() {
      this.loadShopifyConnLog();
      if (this.shopifyConnLogTimer) return;
      this.shopifyConnLogTimer = setInterval(() => {
        if (this.currentView === 'settings') this.loadShopifyConnLog();
      }, 3000);
    },

    async clearShopifyConnLog() {
      try { await this.api('/api/shopify/connection-log/clear', { method: 'POST' }); } catch (e) {}
      this.shopifyConnLog = [];
    },

    async loadSettings() {
      try {
        this.settingsData = await this.api('/api/settings') || {};
        this.loadSourceSites();
        // Populate Shopify credential forms from saved settings
        const creds = {};
        for (const site of (this.settingsData.source_sites || [])) {
          creds[site.domain] = {
            shopify_store_url: site.shopify_store_url || '',
            shopify_client_id: site.shopify_client_id || site.shopify_api_key || '',
            shopify_client_secret: site.shopify_client_secret || '',
            shopify_access_token: site.shopify_access_token || '',
            sync_draft: site.sync_draft || false,
            sync_archived: site.sync_archived || false,
          };
        }
        this.shopifyCredentials = creds;
        // Load webhook settings
        const wh = await this.api('/api/settings/webhook');
        if (wh) {
          this.webhookForm.url = wh.url || '';
          this.webhookForm.events = wh.events || [];
        }
      } catch {}
    },

    async loadManagedLists() {
      try {
        this.managedLists = await this.api('/api/competitors/managed-lists') || { manufacturers: [], excluded: [], competitors: [] };
      } catch {}
    },

    async addManagedUrl(type, raw) {
      const url = (raw || '').trim();
      if (!url) return;
      try {
        await this.api('/api/competitors/managed-domain', {
          method: 'POST',
          body: JSON.stringify({ domain: url, domain_type: type }),
        });
        this.newManagedUrl[type] = '';
        await this.loadManagedLists();
        this.toast(`Added to ${type} list`, 'success', 2000);
      } catch (e) { this.toast('Failed to add URL: ' + e.message, 'error'); }
    },

    async removeManagedDomain(domain) {
      try {
        await this.api(`/api/competitors/managed-domain?domain=${encodeURIComponent(domain)}`, {
          method: 'DELETE',
        });
        await this.loadManagedLists();
        this.toast(`Removed ${domain}`, 'success', 2000);
      } catch (e) { this.toast('Failed to remove: ' + e.message, 'error'); }
    },

    async saveSetting(keys, value) {
      try {
        await this.api('/api/settings', { method: 'PUT', body: JSON.stringify({ keys, value }) });
        this.toast('Setting saved', 'success', 2000);
        await this.loadSettings();
      } catch (e) { this.toast('Failed to save setting: ' + e.message, 'error'); }
    },

    async saveShopifyCredentials(domain) {
      const creds = this.shopifyCredentials[domain] || {};
      try {
        await this.api(`/api/source-sites/${encodeURIComponent(domain)}/credentials`, {
          method: 'PUT',
          body: JSON.stringify({
            shopify_store_url: creds.shopify_store_url || '',
            shopify_client_id: creds.shopify_client_id || '',
            shopify_client_secret: creds.shopify_client_secret || '',
            shopify_access_token: creds.shopify_access_token || '',
            sync_draft: creds.sync_draft || false,
            sync_archived: creds.sync_archived || false,
          }),
        });
        this.toast(`Credentials saved for ${domain}`, 'success', 2500);
        await this.loadSettings();
      } catch (e) { this.toast('Failed to save credentials: ' + e.message, 'error'); }
    },

    async addSourceSite() {
      const url = (this.newSiteForm.shopify_store_url || '').trim().replace(/^https?:\/\//, '').replace(/\/$/, '');
      if (!this.newSiteForm.name.trim() || !url) {
        this.toast('Name and Store URL are required', 'error'); return;
      }
      // Derive domain from the myshopify URL (strip scheme, keep host)
      const domain = url.split('/')[0].toLowerCase();
      try {
        await this.api('/api/source-sites', {
          method: 'POST',
          body: JSON.stringify({
            name: this.newSiteForm.name.trim(),
            domain,
            shopify_store_url: 'https://' + url,
            is_destination: this.newSiteForm.is_destination,
          }),
        });
        this.newSiteForm = { show: false, name: '', shopify_store_url: '', is_destination: false };
        this.toast(`Store "${domain}" added`, 'success', 3000);
        await this.loadSettings();
      } catch (e) { this.toast('Failed to add store: ' + e.message, 'error'); }
    },

    async removeSourceSite(domain) {
      if (this.removeSiteConfirm !== domain) {
        this.removeSiteConfirm = domain;
        setTimeout(() => { if (this.removeSiteConfirm === domain) this.removeSiteConfirm = null; }, 4000);
        return;
      }
      this.removeSiteConfirm = null;
      try {
        await this.api(`/api/source-sites/${encodeURIComponent(domain)}`, { method: 'DELETE' });
        this.toast(`Removed ${domain}`, 'success', 2500);
        await this.loadSettings();
      } catch (e) { this.toast('Failed to remove: ' + e.message, 'error'); }
    },

    async testShopifyConnection(domain) {
      this.shopifyTestStatus = { ...this.shopifyTestStatus, [domain]: 'testing' };
      try {
        const result = await this.api(`/api/source-sites/${encodeURIComponent(domain)}/test-connection`, { method: 'POST' });
        this.shopifyTestStatus = {
          ...this.shopifyTestStatus,
          [domain]: result.ok ? 'ok' : 'error',
        };
        this.shopifyTestMessage = {
          ...this.shopifyTestMessage,
          [domain]: result.ok ? `Connected — ${result.shop_name} (${result.plan})` : result.error,
        };
      } catch (e) {
        this.shopifyTestStatus = { ...this.shopifyTestStatus, [domain]: 'error' };
        this.shopifyTestMessage = { ...this.shopifyTestMessage, [domain]: e.message };
      }
    },

    async saveWebhook() {
      try {
        await this.api('/api/settings/webhook', { method: 'PUT', body: JSON.stringify(this.webhookForm) });
        this.toast('Webhook configured', 'success');
      } catch (e) { this.toast('Webhook save failed: ' + e.message, 'error'); }
    },

    // -----------------------------------------------------------------------
    // Shopify Webhook Management
    // -----------------------------------------------------------------------
    _shopifyWebhookState(domain) {
      if (!this.shopifyWebhooks[domain]) {
        this.shopifyWebhooks = {
          ...this.shopifyWebhooks,
          [domain]: { live: [], saved: [], liveLoading: false, savedLoading: false, acting: false, error: null },
        };
      }
      return this.shopifyWebhooks[domain];
    },

    async loadShopifyWebhooksLive(domain) {
      const s = this._shopifyWebhookState(domain);
      s.liveLoading = true; s.error = null;
      try {
        const r = await this.api(`/api/shopify-webhooks/${encodeURIComponent(domain)}/live`);
        s.live = r.webhooks || [];
      } catch (e) { s.error = e.message; }
      finally { s.liveLoading = false; }
    },

    async loadShopifyWebhooksSaved(domain) {
      const s = this._shopifyWebhookState(domain);
      s.savedLoading = true;
      try {
        const r = await this.api(`/api/shopify-webhooks/${encodeURIComponent(domain)}/saved`);
        s.saved = r.webhooks || [];
      } catch (e) { /* silent */ }
      finally { s.savedLoading = false; }
    },

    async loadShopifyWebhooks(domain) {
      await Promise.all([this.loadShopifyWebhooksLive(domain), this.loadShopifyWebhooksSaved(domain)]);
    },

    async saveAndDisableWebhooks(domain) {
      if (!confirm(`Save all webhooks for ${domain} to the local database, then delete them from Shopify?\n\nUse this before a bulk import to prevent webhook triggers.`)) return;
      const s = this._shopifyWebhookState(domain);
      s.acting = true;
      try {
        const r = await this.api(`/api/shopify-webhooks/${encodeURIComponent(domain)}/save-and-disable`, { method: 'POST' });
        this.toast(`Saved ${r.saved} and disabled ${r.deleted} webhooks for ${domain}`, 'success');
        await this.loadShopifyWebhooks(domain);
      } catch (e) { this.toast('Save & disable failed: ' + e.message, 'error'); }
      finally { s.acting = false; }
    },

    async restoreWebhooks(domain) {
      const s = this._shopifyWebhookState(domain);
      const disabledCount = (s.saved || []).filter(w => !w.is_active_in_shopify).length;
      if (disabledCount === 0) { this.toast('No disabled webhooks to restore', 'info'); return; }
      if (!confirm(`Re-create ${disabledCount} saved webhooks in ${domain}?`)) return;
      s.acting = true;
      try {
        const r = await this.api(`/api/shopify-webhooks/${encodeURIComponent(domain)}/restore`, { method: 'POST' });
        this.toast(`Restored ${r.restored} webhooks for ${domain}`, 'success');
        await this.loadShopifyWebhooks(domain);
      } catch (e) { this.toast('Restore failed: ' + e.message, 'error'); }
      finally { s.acting = false; }
    },

    async deleteShopifyWebhookLive(domain, webhookId) {
      if (!confirm(`Delete webhook ${webhookId} from ${domain}? This cannot be undone unless you saved it first.`)) return;
      const s = this._shopifyWebhookState(domain);
      s.acting = true;
      try {
        await this.api(`/api/shopify-webhooks/${encodeURIComponent(domain)}/live/${webhookId}`, { method: 'DELETE' });
        this.toast('Webhook deleted', 'success');
        await this.loadShopifyWebhooks(domain);
      } catch (e) { this.toast('Delete failed: ' + e.message, 'error'); }
      finally { s.acting = false; }
    },

    // -----------------------------------------------------------------------
    // WebSocket
    // -----------------------------------------------------------------------
    connectWebSocket() {
      if (this.ws && this.ws.readyState === WebSocket.OPEN) return;
      const proto = location.protocol === 'https:' ? 'wss' : 'ws';
      try {
        this.ws = new WebSocket(`${proto}://${location.host}/ws/scan-progress`);
        this.ws.onopen = () => { this.wsConnected = true; clearTimeout(this._wsReconnectTimer); };
        this.ws.onmessage = (evt) => {
          try { this.handleWsMessage(JSON.parse(evt.data)); } catch {}
        };
        this.ws.onclose = () => {
          this.wsConnected = false;
          this._wsReconnectTimer = setTimeout(() => this.connectWebSocket(), 5000);
        };
        this.ws.onerror = () => { this.wsConnected = false; };
      } catch {}
    },

    handleWsMessage(msg) {
      switch (msg.event) {
        case 'log_tail':
          this.logTail = msg.lines || [];
          break;
        case 'site_start':
          this.scanStatus.message = `Scanning ${msg.site}...`; break;
        case 'urls_found':
          this.scanStatus.message = `${msg.site}: found ${msg.count} products`;
          this.scanStatus.total = msg.count; this.scanStatus.current = 0; break;
        case 'product_progress':
          this.scanStatus.current = msg.current; this.scanStatus.total = msg.total;
          this.scanStatus.message = `${msg.site}: scraping ${msg.current}/${msg.total}`; break;
        case 'site_complete':
          this.scanStatus.message = `${msg.site} done — ${msg.new} new, ${msg.updated} updated`; break;
        case 'scan_complete':
          this.scanRunning = false; this.scanStatus = {};
          this.toast('Source scan completed!', 'success');
          this.loadStats(); this.loadScanSessions(); break;
        case 'scan_error':
          this.scanRunning = false; this.scanStatus = {};
          this.toast('Scan error: ' + (msg.error || 'Unknown'), 'error');
          this.loadScanSessions(); break;
        case 'dedup_started':
          this.toast('Deduplication started — this may take several minutes on a large catalog.', 'info', 5000);
          break;
        case 'dedup_complete':
          this.toast(`Dedup done — ${msg.stats?.auto_merged || 0} merged, ${msg.stats?.flagged_for_review || 0} need review`, 'success');
          this.loadDuplicates(); this.loadStats(); break;
        case 'dedup_error':
          this.toast('Deduplication failed: ' + (msg.error || 'Unknown'), 'error');
          break;
        case 'crawl_progress':
          if (msg.pages_visited % 10 === 0)
            this.scanStatus.message = `Crawling... ${msg.pages_visited} pages, ${msg.products_found} found`;
          break;
        case 'task_update':
          this.loadTaskList();
          if (msg.task?.name === 'Deduplication' && msg.task?.status === 'complete')
            this.loadCycleStatus();
          if (msg.task?.name?.startsWith('Scan ') && msg.task?.status === 'complete')
            this.loadCycleStatus();
          break;
        case 'cycle_status':
          this.cycleStatus = { ...this.cycleStatus, ...msg };
          if (msg.status === 'complete' || msg.status === 'idle') this.parallelScanRunning = false;
          break;
        case 'parallel_scan_complete':
          this.parallelScanRunning = false;
          this.loadCycleStatus();
          break;
      }
    },

    // -----------------------------------------------------------------------
    // Utilities
    // -----------------------------------------------------------------------
    fmtPrice(v) { return v != null ? `$${Number(v).toFixed(2)}` : '—'; },
    fmtDate(iso) { return iso ? new Date(iso).toLocaleString() : '—'; },
    fmtDateShort(iso) { return iso ? new Date(iso).toLocaleDateString() : '—'; },
    statusColor(s) {
      const m = { completed: 'text-green-500', running: 'text-blue-500', failed: 'text-red-500',
                  pending: 'text-yellow-500', cancelled: 'text-gray-400' };
      return m[s] || 'text-gray-400';
    },
  };
}
