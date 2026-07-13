/**
 * domainSync — Frontend Alpine.js application v2.0
 * Covers all features F01-F74 (except F68 which was excluded).
 */

function app() {
  return {
    // Auth (login removed — always authenticated)
    authenticated: true,

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
      { id: 'edit-products',   icon: '✏️', label: 'Edit Products',      badge: 0 },
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
    filterOptions: { manufacturers: [], categories: [], source_sites: [] },
    storeComp: { products: [], total: 0, page: 1, pages: 1, source_sites: [] },
    storeCompSummary: { total_products: 0, sor_site: '', missing_from_sor: 0, stores: [] },
    storeCompFilters: {
      search: '', manufacturer: '', category: '', source_site: '',
      store_a: '', store_b: '',
      min_price: '', max_price: '', in_stock: '',
      has_diffs: false, missing_from: '', has_empty: [],
      sort_by: 'title', sort_order: 'asc',
    },
    storeCompExpanded: {},
    storeCompSaving: {},

    // Edit Products (one row per variant from the most recent store scan)
    editStores: [],                 // [{domain, data_source, product_count, age_days, ...}]
    editStoreSel: {},               // {domain: bool} — which stores are selected
    editData: { rows: [], columns: [], total: 0, page: 1, pages: 1, per_page: 50, facets: {}, stores_meta: [] },
    editFacets: { vendors: [], product_types: [], statuses: [], collections: [], tags: [] },
    editLoading: false,
    editRowSel: {},                 // {row_id: rowObject} — selected rows (persists across pages)
    editBulkField: '',              // field chosen in the bulk-edit bar
    editBulkValue: '',              // value to apply across the selection
    editBulkMode: 'set',            // list fields (collections/tags): set | add | remove
    editShowFilters: false,         // advanced attribute filters expander

    // Inline editing (Phase 2). Row objects are never mutated; edits are held as
    // overlays and applied on top for display. Product-level fields are shared
    // by all variant rows of a product, so they're keyed by store|product_id and
    // propagate to siblings; variant-level fields are keyed by row_id.
    editEdits: {},                  // {row_id: {field: value}}          variant-level
    editProductEdits: {},           // {'store|product_id': {field: value}} product-level
    // Registries of the row object behind each edit, so Review can build the
    // change list even for edits made on pages no longer loaded.
    editEditRows: {},               // {row_id: rowObject}
    editProductRows: {},            // {'store|product_id': rowObject}
    editReview: { open: false, loading: false, executing: false, items: [], total: 0, pushable: 0, blocked: 0, risk_counts: {}, results: null, progress: { done: 0, total: 0 } },
    editActiveCell: null,           // 'row_id::col' currently being edited
    editDraft: '',                  // in-progress input value
    _suppressBlur: false,           // discard the blur that follows Escape
    // Which columns are editable + how to render/parse them.
    editColType: {
      title: 'text', vendor: 'text', product_type: 'text', category: 'text',
      status: 'select', tags: 'tags', collections: 'tags',
      sku: 'text', barcode: 'text', price: 'number', compare_at_price: 'number',
      weight: 'number',
    },
    editColScope: {
      title: 'product', vendor: 'product', product_type: 'product', category: 'product',
      status: 'product', tags: 'product', collections: 'product',
      sku: 'variant', barcode: 'variant', price: 'variant', compare_at_price: 'variant',
      weight: 'variant',
    },
    editStatusOptions: ['active', 'draft', 'archived'],
    // Existing values pulled from the DB + all scans, for datalist suggestions.
    editPools: { product_types: [], categories: [], collections: [] },
    // Column show/hide (persisted). Missing key = visible.
    editColVisible: {},
    editColChooserOpen: false,
    // "Select from existing" picker in the bulk bar (alternative to typing).
    editBulkPickerOpen: false,
    editBulkPickerSearch: '',
    // Every column defaults to a ~30-character width (drag a column's resize
    // grip to widen it past the default cap).
    editFilters: {
      search: '', title: '', sku: '', vendor: '', product_type: '', status: '',
      tag: '', collection: '', min_price: '', max_price: '',
      min_weight: '', max_weight: '', has_image: '',
      sort_by: 'title', sort_order: 'asc', per_page: 50,
    },
    // Human labels for the grid columns (order comes from the API `columns`).
    editColLabels: {
      store: 'Store', data_source: 'Src', status: 'Status', title: 'Title',
      vendor: 'Vendor', product_type: 'Product Type', category: 'Category', sku: 'SKU', barcode: 'Barcode',
      price: 'Price', compare_at_price: 'Compare $', weight: 'Weight',
      variant_title: 'Variant',
      option1: 'Option 1', option2: 'Option 2', option3: 'Option 3',
      tags: 'Tags', collections: 'Collections', image_count: 'Photos',
      description: 'Description', handle: 'Handle',
    },

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
    liveSyncChangeLog: [],        // applied changes: {time, domain, status, text, error}
    liveSyncExpandedGroups: {},   // collection group name -> expanded? (default: collapsed)
    liveSyncScanPrompt: null,     // {domain, info} when a recent saved scan exists
    liveSyncProgress: { done: 0, total: 0, ok: 0, errors: 0 },  // background execute progress
    _liveExecPollTimer: null,     // WS-drop fallback poll

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
    dupSort: { col: 'confidence_score', dir: 'desc' },
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

    // WebSocket
    ws: null,
    wsConnected: false,
    _wsReconnectTimer: null,

    // -----------------------------------------------------------------------
    // Lifecycle
    // -----------------------------------------------------------------------
    async init() {
      this.$watch('darkMode', v => localStorage.setItem('darkMode', v));
      await this.postLoginInit();
    },

    async postLoginInit() {
      await Promise.all([
        this.loadStats(),
        this.loadScanSessions(),
        this.loadSettings(),
        this.loadFilterOptions(),
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

    // A column's stable identity for persisted state (resize widths + the
    // long-col cap below) is its header LABEL, not its DOM position. Position
    // shifts every time a column is hidden/shown (the "Columns" chooser) or
    // added/removed — a positional index would silently reattach an old
    // saved width (or cap-lift) to whatever different column now sits at that
    // slot. The label is the first <span> in the header (Edit Products'
    // sortable headers put the label span before a conditional sort-arrow
    // span); falls back to the th's own text, then a positional placeholder
    // for label-less headers (e.g. the checkbox column) so keys stay unique.
    _colId(th, i) {
      const label = (th.querySelector(':scope > span') || th).textContent.trim();
      return label || `__col${i}`;
    },

    // The ~30-char default cap (`.edit-col-long` in style.css) must lift only
    // for columns the user actually dragged wider — never for the whole table
    // just because *some* column has a saved width (pinning is table-wide,
    // the cap is per-column). Injects one CSS rule per saved column, scoped to
    // this table via `data-resize-key` + `:nth-child` (colIds maps each saved
    // column name to its CURRENT position), so it survives Alpine re-rendering
    // rows/columns without needing per-cell JS bookkeeping.
    _syncLongColCaps(table, key, saved, colIds) {
      table.dataset.resizeKey = key;
      const id = 'colcap-' + key.replace(/[^a-zA-Z0-9_-]/g, '_');
      let styleEl = document.getElementById(id);
      if (!styleEl) {
        styleEl = document.createElement('style');
        styleEl.id = id;
        document.head.appendChild(styleEl);
      }
      styleEl.textContent = Object.keys(saved).map(name => {
        const i = colIds.indexOf(name);
        if (i < 0) return '';  // column currently hidden/absent — nothing to style
        return `table[data-resize-key="${key}"] :is(th,td):nth-child(${i + 1}) .edit-col-long { max-width: 100%; }`;
      }).filter(Boolean).join('\n');
    },

    _wireTableResize(table) {
      if (table.__colResizeWired) return;
      const ths = table.querySelectorAll(':scope > thead > tr > th');
      if (!ths.length) return;
      table.__colResizeWired = true;

      const key = this._tableKey(table);
      const colIds = Array.from(ths).map((th, i) => this._colId(th, i));
      let saved = {};
      try { saved = JSON.parse(localStorage.getItem(key) || '{}'); } catch {}
      const hasSaved = Object.keys(saved).length > 0;
      // Lift the cap for previously-resized columns BEFORE any width is
      // measured/pinned below, so their offsetWidth reflects the uncapped
      // content, not the still-capped 30ch default.
      this._syncLongColCaps(table, key, saved, colIds);

      // Pin the table to fixed layout (using either saved widths or each
      // column's current natural width). Called once, before the first
      // resize event or immediately if there are persisted widths.
      const pinTable = () => {
        if (table.__pinned) return;
        ths.forEach((th, i) => {
          const w = saved[colIds[i]] || th.offsetWidth;
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
        const colId = colIds[i];

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
            cur[colId] = Math.round(th.offsetWidth);
            localStorage.setItem(key, JSON.stringify(cur));
            this._syncLongColCaps(table, key, cur, colIds);
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
            delete cur[colId];
            localStorage.setItem(key, JSON.stringify(cur));
            this._syncLongColCaps(table, key, cur, colIds);
          } catch {}
        });
      });
    },

    // -----------------------------------------------------------------------
    // Auth
    // -----------------------------------------------------------------------
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
      const opts = {
        headers: { 'Content-Type': 'application/json', ...(options.headers || {}) },
        ...options,
      };
      // A reused keep-alive socket that the server already closed makes fetch()
      // reject with a TypeError ("Load failed"/"Failed to fetch") even though the
      // server is healthy. That's a dead connection, not a real error — retry once
      // on a fresh socket before surfacing it.
      let r;
      for (let attempt = 0; ; attempt++) {
        try { r = await fetch(path, opts); break; }
        catch (e) {
          if (attempt >= 1) throw e;
          await new Promise(res => setTimeout(res, 200));
        }
      }
      if (r.status === 401) { return null; }  // login removed — never bounce to a login screen
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
        // Load every candidate (across all pages) so the review list shows ALL
        // suspected duplicates; domain filtering and sorting are then applied
        // client-side in sortedDups()/dupFilteredCandidates().
        const perPage = 100;
        const all = [];
        let page = 1;
        let totalPages = 1;
        do {
          const params = new URLSearchParams({ status: this.dupFilter, per_page: perPage, page });
          const res = await this.api(`/api/dedup/candidates?${params}`) || { candidates: [], total: 0 };
          all.push(...(res.candidates || []));
          // Derive page count from the candidate total (a page may return fewer
          // rows than per_page when a product was deleted, so we can't rely on
          // batch length to know when to stop).
          totalPages = Math.max(1, Math.ceil((res.total || 0) / perPage));
          page += 1;
        } while (page <= totalPages && page <= 500);
        this.duplicates = { candidates: all, total: all.length };
        this.dupSelected = {};
      } catch {}
    },

    // Candidates filtered to the domain(s) ticked in the "Scan domains" bar.
    // A candidate is kept if either its primary or secondary product has a
    // source on a selected domain. With no domains selected (or before
    // settings load) no domain filtering is applied.
    dupFilteredCandidates() {
      const cands = (this.duplicates && this.duplicates.candidates) || [];
      const selected = Object.entries(this.dupDomainFilters || {})
        .filter(([, v]) => v).map(([k]) => k);
      if (selected.length === 0) return cands;
      const sel = new Set(selected);
      return cands.filter(d => {
        const domains = [
          ...((d.primary && d.primary.sources) || []),
          ...((d.secondary && d.secondary.sources) || []),
        ];
        return domains.some(x => sel.has(x));
      });
    },

    // Filtered candidates ordered by the active sort column (confidence %,
    // primary title, or secondary title).
    sortedDups() {
      const list = this.dupFilteredCandidates();
      const { col, dir } = this.dupSort;
      if (!col) return list;
      const mul = dir === 'desc' ? -1 : 1;
      const keyOf = (d) => {
        if (col === 'confidence_score') return d.confidence_score ?? 0;
        if (col === 'primary_title') return ((d.primary && d.primary.title) || '').toLowerCase();
        if (col === 'secondary_title') return ((d.secondary && d.secondary.title) || '').toLowerCase();
        return '';
      };
      return [...list].sort((a, b) => {
        const va = keyOf(a), vb = keyOf(b);
        if (va < vb) return -1 * mul;
        if (va > vb) return 1 * mul;
        return 0;
      });
    },

    // Toggle/activate a sort column on a sort-state object {col, dir}.
    // Clicking the active column flips direction; a new column starts desc for
    // confidence (highest first) and asc for titles (A→Z).
    setSort(state, col) {
      if (state.col === col) {
        state.dir = state.dir === 'asc' ? 'desc' : 'asc';
      } else {
        state.col = col;
        state.dir = col === 'confidence_score' ? 'desc' : 'asc';
      }
    },

    sortIcon(state, col) {
      if (state.col !== col) return '↕';
      return state.dir === 'asc' ? '↑' : '↓';
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
      const candidates = this.dupFilteredCandidates();
      return candidates.length > 0 && candidates.every(d => this.dupSelected[d.id]);
    },

    dupToggleSelectAll() {
      const candidates = this.dupFilteredCandidates();
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

    dupSelectAllPages() {
      // All candidates are already loaded client-side, so this selects the
      // entire filtered set (respecting the active domain filter).
      const candidates = this.dupFilteredCandidates();
      const all = {};
      candidates.forEach(d => { all[d.id] = true; });
      this.dupSelected = all;
      this.toast(`Selected ${candidates.length} duplicate${candidates.length !== 1 ? 's' : ''}`, 'info');
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
        if (f.store_a)      params.set('store_a', f.store_a);
        if (f.store_b)      params.set('store_b', f.store_b);
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

    // Per-store gap overview (SoR consolidation Stage 5).
    async loadStoreCompSummary() {
      try {
        this.storeCompSummary = await this.api('/api/products/store-comparison/summary')
          || { total_products: 0, sor_site: '', missing_from_sor: 0, stores: [] };
      } catch (e) { /* non-fatal: the comparison table still works without the summary */ }
    },

    // Click a gap chip → filter the table to products missing from that store.
    storeCompShowMissingFrom(site) {
      this.storeCompFilters.missing_from = (this.storeCompFilters.missing_from === site) ? '' : site;
      this.loadStoreComparison(1);
    },

    storeCompShortSite(site) {
      return (site || '').split('.')[0];
    },

    toggleStoreCompExpanded(productId) {
      this.storeCompExpanded = { ...this.storeCompExpanded, [productId]: !this.storeCompExpanded[productId] };
    },

    storeCompCellStatus(canonVal, srcVal, siteExists, fieldType = 'text') {
      if (!siteExists) return 'absent';
      // An absent price must stay absent — do NOT coerce null/'' to 0.00, or a
      // store with no price would falsely compare equal ("same price") to
      // another empty price. A real $0.00 is kept as "0.00".
      const norm = v => {
        if (fieldType === 'price')
          return (v === null || v === undefined || v === '') ? '' : Number(v).toFixed(2);
        return String(v || '').trim().toLowerCase();
      };
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
             f.store_a || f.store_b ||
             f.min_price !== '' || f.max_price !== '' || f.in_stock !== '' ||
             f.has_diffs || f.missing_from !== '' || f.has_empty.length > 0;
    },

    storeCompClearFilters() {
      this.storeCompFilters = {
        search: '', manufacturer: '', category: '', source_site: '',
        store_a: '', store_b: '',
        min_price: '', max_price: '', in_stock: '',
        has_diffs: false, missing_from: '', has_empty: [],
        sort_by: 'title', sort_order: 'asc',
      };
      this.loadStoreComparison(1);
    },

    async loadFilterOptions() {
      try {
        this.filterOptions = await this.api('/api/products/filters/options')
          || { manufacturers: [], categories: [], source_sites: [] };
      } catch {}
    },

    // -----------------------------------------------------------------------
    // Edit Products — bulk product editor over the most recent store scan.
    // -----------------------------------------------------------------------
    // Called when the view is first opened: load the store list, default-select
    // the scanned stores, then load the grid.
    async initEditProducts() {
      if (this._editInit) return;
      this._editInit = true;
      try { this.editColVisible = JSON.parse(localStorage.getItem('editColVisible') || '{}'); } catch {}
      try {
        const r = await this.api('/api/edit-products/stores') || { stores: [] };
        this.editStores = r.stores;
        // Default: select stores that have a real scan snapshot (the page's
        // reason for being). If none are scanned, select everything.
        const scanned = this.editStores.filter(s => s.data_source === 'scan');
        const pick = (scanned.length ? scanned : this.editStores);
        const sel = {};
        pick.forEach(s => { sel[s.domain] = true; });
        this.editStoreSel = sel;
      } catch (e) { this.toast('Failed to load stores: ' + e.message, 'error'); }
      try {
        this.editPools = await this.api('/api/edit-products/taxonomy') || this.editPools;
      } catch { /* suggestions are optional */ }
      await this.loadEditProducts(1);
    },

    // Which datalist (of existing values) backs a given editable column, if any.
    editListId(col) {
      if (col === 'product_type') return 'edit-pool-types';
      if (col === 'category') return 'edit-pool-categories';
      if (col === 'collections') return 'edit-pool-collections';
      return '';
    },

    // ---- Column show/hide -------------------------------------------------
    editVisibleColumns() {
      return (this.editData.columns || []).filter(c => this.editColVisible[c] !== false);
    },
    editToggleColumn(col) {
      this.editColVisible = { ...this.editColVisible, [col]: this.editColVisible[col] === false };
      try { localStorage.setItem('editColVisible', JSON.stringify(this.editColVisible)); } catch {}
      // Column set changed → re-measure/re-wire the resizable grid.
      this._editGridWired = false;
      this._wireEditGrid();
    },
    // ---- Bulk "select from existing" picker ------------------------------
    editBulkPool() {
      const f = this.editBulkField;
      if (f === 'product_type') return this.editPools.product_types;
      if (f === 'category') return this.editPools.categories;
      if (f === 'collections') return this.editPools.collections;
      if (f === 'tags') return this.editFacets.tags || [];
      return [];
    },
    editBulkHasPicker() { return this.editBulkPool().length > 0; },
    editBulkPickerFiltered() {
      const q = this.editBulkPickerSearch.trim().toLowerCase();
      const pool = this.editBulkPool();
      return q ? pool.filter(v => v.toLowerCase().includes(q)) : pool;
    },
    _bulkTokens() {
      return String(this.editBulkValue || '').split(',').map(s => s.trim()).filter(Boolean);
    },
    editBulkIsPicked(v) { return this._bulkTokens().includes(v); },
    editBulkTogglePick(v) {
      if (this.editBulkIsList()) {
        const toks = this._bulkTokens();
        const i = toks.indexOf(v);
        if (i >= 0) toks.splice(i, 1); else toks.push(v);
        this.editBulkValue = toks.join(', ');
      } else {
        // Single-value field: pick replaces and closes.
        this.editBulkValue = v;
        this.editBulkPickerOpen = false;
      }
    },

    editSelectedStores() {
      return this.editStores.filter(s => this.editStoreSel[s.domain]).map(s => s.domain);
    },

    editStoreShort(domain) { return (domain || '').split('.')[0]; },

    async loadEditProducts(page = 1) {
      const stores = this.editSelectedStores();
      if (!stores.length) {
        this.editData = { rows: [], columns: this.editData.columns || [], total: 0, page: 1, pages: 1, per_page: this.editFilters.per_page, facets: {}, stores_meta: [] };
        return;
      }
      this.editLoading = true;
      try {
        const f = this.editFilters;
        const params = new URLSearchParams({ page, per_page: f.per_page });
        params.set('stores', stores.join(','));
        if (f.search)        params.set('search', f.search);
        if (f.title)         params.set('title', f.title);
        if (f.sku)           params.set('sku', f.sku);
        if (f.vendor)        params.set('vendor', f.vendor);
        if (f.product_type)  params.set('product_type', f.product_type);
        if (f.status)        params.set('status', f.status);
        if (f.tag)           params.set('tag', f.tag);
        if (f.collection)    params.set('collection', f.collection);
        if (f.min_price !== '')  params.set('min_price', f.min_price);
        if (f.max_price !== '')  params.set('max_price', f.max_price);
        if (f.min_weight !== '') params.set('min_weight', f.min_weight);
        if (f.max_weight !== '') params.set('max_weight', f.max_weight);
        if (f.has_image !== '')  params.set('has_image', f.has_image);
        params.set('sort_by', f.sort_by);
        params.set('sort_order', f.sort_order);
        const data = await this.api(`/api/edit-products?${params}`);
        if (data) {
          this.editData = data;
          this.editFacets = data.facets || this.editFacets;
          this._wireEditGrid();
        }
      } catch (e) { this.toast('Failed to load products: ' + e.message, 'error'); }
      finally { this.editLoading = false; }
    },

    // The grid is a single static <table> whose ~23 data columns are filled in
    // by x-for AFTER load. _initColumnResize's MutationObserver only re-wires on
    // added <table> nodes, so it wired this table at page load with just the two
    // static columns (checkbox, Img). Once the real columns exist, drop the
    // stale wiring and re-wire so every data column gets a resize grip. The
    // column set is stable across reloads, so this runs once.
    _wireEditGrid() {
      if (this._editGridWired) return;
      this._editGridWired = true;
      this.$nextTick(() => {
        const t = document.querySelector('[x-show*="edit-products"] table');
        if (!t) { this._editGridWired = false; return; }
        t.__colResizeWired = false;
        t.__pinned = false;
        t.style.tableLayout = '';
        t.classList.remove('col-resize-active');
        t.querySelectorAll('th').forEach(th => { th.style.width = ''; th.style.minWidth = ''; });
        t.querySelectorAll('.col-resize-grip').forEach(g => g.remove());
        this._wireTableResize(t);
      });
    },

    // Toggle a store checkbox and reload.
    editToggleStore(domain) {
      this.editStoreSel = { ...this.editStoreSel, [domain]: !this.editStoreSel[domain] };
      this.loadEditProducts(1);
    },
    editSelectAllStores(on) {
      const sel = {};
      this.editStores.forEach(s => { sel[s.domain] = on; });
      this.editStoreSel = sel;
      this.loadEditProducts(1);
    },

    // Click a column header to sort by it (toggles direction on the active col).
    editSort(col) {
      const f = this.editFilters;
      if (f.sort_by === col) {
        f.sort_order = f.sort_order === 'asc' ? 'desc' : 'asc';
      } else {
        f.sort_by = col;
        f.sort_order = 'asc';
      }
      this.loadEditProducts(1);
    },

    editHasActiveFilters() {
      const f = this.editFilters;
      return f.search || f.title || f.sku || f.vendor || f.product_type || f.status ||
             f.tag || f.collection || f.min_price !== '' || f.max_price !== '' ||
             f.min_weight !== '' || f.max_weight !== '' || f.has_image !== '';
    },

    editClearFilters() {
      this.editFilters = {
        search: '', title: '', sku: '', vendor: '', product_type: '', status: '',
        tag: '', collection: '', min_price: '', max_price: '',
        min_weight: '', max_weight: '', has_image: '',
        sort_by: 'title', sort_order: 'asc', per_page: this.editFilters.per_page,
      };
      this.loadEditProducts(1);
    },

    // Render a cell value for display (arrays → comma list, null → blank).
    editCell(row, col) {
      const v = row[col];
      if (v === null || v === undefined || v === '') return '';
      if (Array.isArray(v)) return v.join(', ');
      if (col === 'price' || col === 'compare_at_price') return '$' + Number(v).toFixed(2);
      return v;
    },

    editNumericCol(col) {
      return ['price', 'compare_at_price', 'weight', 'image_count'].includes(col);
    },

    // Row selection. We store the whole row object (not just a boolean) so bulk
    // edits can reach rows selected on other pages, which are no longer loaded.
    editIsRowSelected(rowId) { return !!this.editRowSel[rowId]; },
    editSelectedCount() { return Object.keys(this.editRowSel).length; },
    editToggleRow(row) {
      const next = { ...this.editRowSel };
      if (next[row.row_id]) delete next[row.row_id]; else next[row.row_id] = row;
      this.editRowSel = next;
    },
    editAllOnPageSelected() {
      const rows = this.editData.rows || [];
      return rows.length > 0 && rows.every(r => this.editRowSel[r.row_id]);
    },
    editToggleAllOnPage(on) {
      const next = { ...this.editRowSel };
      (this.editData.rows || []).forEach(r => { if (on) next[r.row_id] = r; else delete next[r.row_id]; });
      this.editRowSel = next;
    },
    editClearSelection() { this.editRowSel = {}; },

    // -------------------------------------------------------------------
    // Inline editing (Phase 2) — staged locally, nothing sent to Shopify.
    // -------------------------------------------------------------------
    editIsEditable(col) { return Object.prototype.hasOwnProperty.call(this.editColType, col); },
    editPKey(row) { return row.store + '|' + row.product_id; },
    editCellKey(row, col) { return row.row_id + '::' + col; },

    // The overlay map + whether it carries an override for this field.
    _editOverride(row, col) {
      const scope = this.editColScope[col] || 'variant';
      const m = scope === 'product'
        ? this.editProductEdits[this.editPKey(row)]
        : this.editEdits[row.row_id];
      const has = !!m && Object.prototype.hasOwnProperty.call(m, col);
      return { has, value: has ? m[col] : row[col] };
    },
    editEffective(row, col) { return this._editOverride(row, col).value; },
    editIsDirty(row, col) { return this._editOverride(row, col).has; },

    // Effective value formatted for display (arrays → list, prices → $).
    editDisplay(row, col) {
      const v = this.editEffective(row, col);
      if (v === null || v === undefined || v === '') return '';
      if (Array.isArray(v)) return v.join(', ');
      if (col === 'price' || col === 'compare_at_price') return '$' + Number(v).toFixed(2);
      return v;
    },

    editSelectOptions(col) {
      return this.editStatusOptions;
    },

    editStartCell(row, col) {
      if (!this.editIsEditable(col)) return;
      this.editActiveCell = this.editCellKey(row, col);
      const v = this.editEffective(row, col);
      if (this.editColType[col] === 'tags') this.editDraft = Array.isArray(v) ? v.join(', ') : (v || '');
      else this.editDraft = (v === null || v === undefined) ? '' : String(v);
      this.$nextTick(() => {
        const el = document.getElementById('editcell-input');
        if (el) { el.focus(); if (el.select) el.select(); }
      });
    },

    _editEqual(a, b, type) {
      if (type === 'tags') {
        a = Array.isArray(a) ? a : [];
        b = Array.isArray(b) ? b : [];
        return a.join('') === b.join('');
      }
      if (type === 'number') {
        const na = (a === null || a === undefined || a === '') ? null : Number(a);
        const nb = (b === null || b === undefined || b === '') ? null : Number(b);
        return na === nb;
      }
      const sa = (a === null || a === undefined) ? '' : String(a);
      const sb = (b === null || b === undefined) ? '' : String(b);
      return sa === sb;
    },

    // Store (or clear, if reverted to original) an override for one field.
    _editSet(row, col, parsed) {
      const same = this._editEqual(row[col], parsed, this.editColType[col]);
      const scope = this.editColScope[col] || 'variant';
      if (scope === 'product') {
        const k = this.editPKey(row);
        const m = { ...(this.editProductEdits[k] || {}) };
        if (same) delete m[col]; else m[col] = parsed;
        const next = { ...this.editProductEdits };
        if (Object.keys(m).length) { next[k] = m; this.editProductRows[k] = row; } else delete next[k];
        this.editProductEdits = next;
      } else {
        const k = row.row_id;
        const m = { ...(this.editEdits[k] || {}) };
        if (same) delete m[col]; else m[col] = parsed;
        const next = { ...this.editEdits };
        if (Object.keys(m).length) { next[k] = m; this.editEditRows[k] = row; } else delete next[k];
        this.editEdits = next;
      }
    },

    // Parse a raw string input into the stored value for a field's type.
    editParseValue(col, raw) {
      const type = this.editColType[col];
      if (type === 'number') {
        const p = (raw === '' || raw === null || raw === undefined) ? null : parseFloat(raw);
        return (p !== null && isNaN(p)) ? null : p;
      }
      if (type === 'tags') {
        return String(raw || '').split(',').map(s => s.trim()).filter(Boolean);
      }
      return String(raw ?? '');
    },

    editCommitCell(row, col) {
      if (this._suppressBlur) { this._suppressBlur = false; return; }
      this._editSet(row, col, this.editParseValue(col, this.editDraft));
      this.editActiveCell = null;
    },

    // -------------------------------------------------------------------
    // Bulk edit (Phase 3) — set one field across every selected row.
    // -------------------------------------------------------------------
    editBulkFields() {
      return (this.editData.columns || []).filter(c => this.editIsEditable(c));
    },
    // When the field changes, seed a sensible default value (first option for
    // selects, empty otherwise) and reset the list mode.
    editBulkFieldChanged() {
      this.editBulkMode = 'set';
      this.editBulkValue = (this.editColType[this.editBulkField] === 'select')
        ? this.editSelectOptions(this.editBulkField)[0] : '';
    },
    editBulkIsList() { return this.editColType[this.editBulkField] === 'tags'; },
    editBulkApply() {
      if (!this.editBulkField) return;
      const field = this.editBulkField;
      const rows = Object.values(this.editRowSel);
      const label = this.editColLabels[field] || field;
      if (this.editBulkIsList() && this.editBulkMode !== 'set') {
        // Add/remove values into each row's own current list (collections/tags).
        const vals = this.editParseValue(field, this.editBulkValue);
        rows.forEach(row => {
          const cur = (this.editEffective(row, field) || []).slice();
          const next = this.editBulkMode === 'add'
            ? cur.concat(vals.filter(v => !cur.includes(v)))
            : cur.filter(v => !vals.includes(v));
          this._editSet(row, field, next);
        });
        const verb = this.editBulkMode === 'add' ? 'Added to' : 'Removed from';
        this.toast(`${verb} ${label} on ${rows.length} row${rows.length === 1 ? '' : 's'}`, 'success');
      } else {
        const parsed = this.editParseValue(field, this.editBulkValue);
        rows.forEach(row => this._editSet(row, field, parsed));
        this.toast(`Set ${label} on ${rows.length} row${rows.length === 1 ? '' : 's'}`, 'success');
      }
    },

    editCancelCell() { this._suppressBlur = true; this.editActiveCell = null; },
    editRevertCell(row, col) { this._editSet(row, col, row[col]); },

    editPendingCount() {
      let n = 0;
      for (const k in this.editProductEdits) n += Object.keys(this.editProductEdits[k]).length;
      for (const k in this.editEdits) n += Object.keys(this.editEdits[k]).length;
      return n;
    },
    editRevertAll() {
      this.editEdits = {}; this.editProductEdits = {};
      this.editEditRows = {}; this.editProductRows = {};
      this.editActiveCell = null;
    },

    // -------------------------------------------------------------------
    // Review & push to Shopify (Phase 4).
    // -------------------------------------------------------------------
    // Flatten the staged overlays into a change list the backend can turn into
    // Shopify transactions. Uses the row registries for context + original value.
    editBuildChanges() {
      const changes = [];
      const push = (row, field, scope, newVal) => changes.push({
        change_id: [row.store, row.product_id, row.variant_id, scope, field].join('|'),
        store: row.store, data_source: row.data_source,
        product_id: row.product_id, variant_id: row.variant_id, handle: row.handle,
        field, scope, old: row[field], new: newVal,
      });
      for (const k in this.editProductEdits) {
        const row = this.editProductRows[k]; if (!row) continue;
        const m = this.editProductEdits[k];
        for (const f in m) push(row, f, 'product', m[f]);
      }
      for (const k in this.editEdits) {
        const row = this.editEditRows[k]; if (!row) continue;
        const m = this.editEdits[k];
        for (const f in m) push(row, f, 'variant', m[f]);
      }
      return changes;
    },

    async editOpenReview() {
      if (this.editPendingCount() === 0) return;
      this.editReview = { ...this.editReview, open: true, loading: true, results: null };
      try {
        const r = await this.api('/api/edit-products/review', {
          method: 'POST', body: JSON.stringify({ changes: this.editBuildChanges() }),
        });
        this.editReview = { ...this.editReview, ...r, open: true, loading: false, executing: false, results: null };
      } catch (e) {
        this.editReview.loading = false;
        this.toast('Review failed: ' + e.message, 'error');
      }
    },

    editCloseReview() { this.editReview = { ...this.editReview, open: false }; },

    editRiskClass(risk) {
      if (risk === 'HIGH') return 'bg-red-100 text-red-800 dark:bg-red-900/40 dark:text-red-300';
      if (risk === 'MEDIUM') return 'bg-amber-100 text-amber-800 dark:bg-amber-900/40 dark:text-amber-300';
      return 'bg-gray-100 text-gray-600 dark:bg-gray-700 dark:text-gray-300';
    },

    editFmt(v) {
      if (v === null || v === undefined || v === '') return '—';
      if (Array.isArray(v)) return v.length ? v.join(', ') : '—';
      return v;
    },

    // Push runs in the background on the server (bulk pushes take minutes under
    // Shopify's rate limit). Start it, then poll for progress + final results.
    async editExecutePush() {
      if (this.editReview.pushable === 0) { this.toast('Nothing pushable to Shopify.', 'warning'); return; }
      this.editReview.executing = true;
      this.editReview.progress = { done: 0, total: this.editReview.pushable };
      try {
        const start = await this.api('/api/edit-products/execute', {
          method: 'POST', body: JSON.stringify({ changes: this.editBuildChanges() }),
        });
        if (start.status === 'already_running') {
          this.toast('A push is already running.', 'warning');
          this.editReview.executing = false;
          return;
        }
        if (start.status === 'nothing_to_push') {
          this._editApplyResults(start.results || {});
          return;
        }
        this.editReview.progress = { done: 0, total: start.total };
        this._editPoll();
      } catch (e) {
        this.editReview.executing = false;
        this.toast('Push failed: ' + e.message, 'error');
      }
    },

    async _editPoll() {
      try {
        const s = await this.api('/api/edit-products/execute-status');
        if (!s) return;
        this.editReview.progress = { done: s.done, total: s.total };
        if (s.finished) { this._editApplyResults(s.results || {}); return; }
      } catch (e) { /* transient — keep polling */ }
      this._editPollTimer2 = setTimeout(() => this._editPoll(), 1200);
    },

    _editApplyResults(results) {
      this.editReview = { ...this.editReview, executing: false, results };
      let ok = 0, errors = 0, skipped = 0;
      for (const cid in results) {
        const st = results[cid].status;
        if (st === 'ok') { ok++; this._editClearChangeById(cid); }
        else if (st === 'error') errors++;
        else if (st === 'skipped') skipped++;
      }
      const msg = `Pushed ${ok} change${ok === 1 ? '' : 's'}` +
        (errors ? `, ${errors} failed` : '') + (skipped ? `, ${skipped} skipped` : '');
      this.toast(msg, errors ? 'warning' : 'success');
    },

    // change_id = store|product_id|variant_id|scope|field
    _editClearChangeById(cid) {
      const [store, product_id, variant_id, scope, field] = cid.split('|');
      if (scope === 'product') {
        const k = store + '|' + product_id;
        if (this.editProductEdits[k]) {
          const m = { ...this.editProductEdits[k] }; delete m[field];
          const next = { ...this.editProductEdits };
          if (Object.keys(m).length) next[k] = m; else delete next[k];
          this.editProductEdits = next;
        }
      } else {
        const k = [store, product_id, variant_id].join('|');
        if (this.editEdits[k]) {
          const m = { ...this.editEdits[k] }; delete m[field];
          const next = { ...this.editEdits };
          if (Object.keys(m).length) next[k] = m; else delete next[k];
          this.editEdits = next;
        }
      }
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

    async runLiveScan(domain, force = false) {
      if (!domain) return;
      // If a saved scan for this domain is still fresh (< MAX_AGE_DAYS), ask the
      // user whether to reuse it or run a fresh scan — showing when it was taken.
      if (!force) {
        try {
          const info = await this.api('/api/shopify-live/scan-info/' + encodeURIComponent(domain));
          if (info && info.cached) {
            this.liveSyncScanPrompt = { domain, info };
            return;
          }
        } catch {}
      }
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

    // "Use existing scan" from the recent-scan prompt: keep the saved snapshot
    // (the diff will load it from the cache) and just reflect its counts.
    liveSyncUseExistingScan() {
      const p = this.liveSyncScanPrompt;
      if (!p) return;
      const { domain, info } = p;
      this.liveSyncScanStatus = {
        ...this.liveSyncScanStatus,
        [domain]: { product_count: info.product_count, shop_name: info.shop_name },
      };
      this.liveSyncScanProgress = {
        ...this.liveSyncScanProgress,
        [domain]: `✓ ${info.product_count} products (saved ${this.fmtDate(info.scanned_at)})`,
      };
      this.liveSyncScanPrompt = null;
    },

    // "Run fresh scan" from the recent-scan prompt.
    liveSyncFreshScan() {
      const p = this.liveSyncScanPrompt;
      if (!p) return;
      const domain = p.domain;
      this.liveSyncScanPrompt = null;
      this.runLiveScan(domain, true);
    },

    liveSyncScanAgeText(info) {
      if (!info) return '—';
      const s = Math.max(0, Math.floor(info.age_seconds || 0));
      const days = Math.floor(s / 86400);
      const hours = Math.floor((s % 86400) / 3600);
      const mins = Math.floor((s % 3600) / 60);
      if (days >= 1) return `${days} day${days > 1 ? 's' : ''}${hours ? `, ${hours} hr` : ''} ago`;
      if (hours >= 1) return `${hours} hour${hours > 1 ? 's' : ''} ago`;
      if (mins >= 1) return `${mins} minute${mins > 1 ? 's' : ''} ago`;
      return 'just now';
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

    // Map a transaction to a friendly product-characteristic group.
    liveSyncCharacteristic(txn) {
      const rt = txn.resource_type;
      if (rt === 'product') return 'Whole product';
      if (rt === 'tags') return 'Tags';
      if (rt === 'image') return 'Images';
      if (rt === 'variant' || rt === 'variant_field') return 'Variants & pricing';
      if (rt === 'collection' || rt === 'collection_membership') return 'Collections';
      if (rt === 'product_field') return (txn.field || 'Other').replace(' (HTML)', '');
      return 'Other';
    },

    // Distinct characteristics present in the current diff, for the filter dropdown.
    liveSyncCharacteristics() {
      const seen = new Set(this.liveSyncTransactions.map(t => this.liveSyncCharacteristic(t)));
      return Array.from(seen).sort();
    },

    liveSyncFilteredTransactions() {
      let txns = this.liveSyncTransactions;
      if (this.liveSyncFilter === 'pending') txns = txns.filter(t => t.approved === null);
      else if (this.liveSyncFilter === 'approved') txns = txns.filter(t => t.approved === true);
      else if (this.liveSyncFilter === 'rejected') txns = txns.filter(t => t.approved === false);
      else if (this.liveSyncFilter.startsWith('char:')) {
        const c = this.liveSyncFilter.slice(5);
        txns = txns.filter(t => this.liveSyncCharacteristic(t) === c);
      }
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

    // Short, friendly store label for buttons (e.g. "donut-equipment").
    liveSyncShortSite(site) {
      return (site || '').split('.')[0];
    },

    async runLiveExecute() {
      const approvedCount = this.liveSyncApprovedCount();
      if (approvedCount === 0) { this.toast('No transactions approved.', 'error'); return; }
      if (!confirm(`Execute ${approvedCount} approved transaction(s) against ${this.liveSyncDest}? This will make real changes to the destination store.`)) return;
      this.liveSyncExecuting = true;
      this.liveSyncProgress = { done: 0, total: approvedCount, ok: 0, errors: 0 };
      this.liveSyncStep = 'executing';
      try {
        // The execute now runs in the BACKGROUND — a large catalog can take
        // several minutes under Shopify's rate limit. This call returns right
        // away; progress + completion arrive over the WebSocket.
        const result = await this.api('/api/shopify-live/execute', {
          method: 'POST',
          body: JSON.stringify({
            dest_domain: this.liveSyncDest,
            transactions: this.liveSyncTransactions,
          }),
        });
        if (!result || result.status === 'nothing_to_do') {
          this.liveSyncExecuting = false;
          this.liveSyncStep = 'review';
          this.toast('Nothing to execute.', 'info');
          return;
        }
        if (result.status === 'already_running') {
          this.liveSyncProgress = { done: result.done || 0, total: result.total || approvedCount, ok: 0, errors: 0 };
          this.toast('A sync is already running — showing its progress.', 'info');
        }
        this._startLiveExecutePoll();  // WS-drop fallback
      } catch (e) {
        this.liveSyncExecuting = false;
        this.liveSyncStep = 'review';
        this.toast('Execution failed: ' + e.message, 'error');
      }
    },

    // Poll the server for progress in case the WebSocket drops during a long run.
    _startLiveExecutePoll() {
      clearInterval(this._liveExecPollTimer);
      this._liveExecPollTimer = setInterval(async () => {
        if (this.liveSyncStep !== 'executing') { clearInterval(this._liveExecPollTimer); return; }
        try {
          const s = await this.api('/api/shopify-live/execute-status');
          if (!s) return;
          if (s.running) {
            this.liveSyncProgress = { done: s.done, total: s.total, ok: s.ok, errors: s.errors };
          } else if (s.last_result) {
            this._finishLiveExecute(s.last_result);
          }
        } catch {}
      }, 4000);
    },

    // Finalize the execute (called by the WS 'live_sync_complete' event or the poll).
    _finishLiveExecute(payload) {
      clearInterval(this._liveExecPollTimer);
      if (this.liveSyncStep !== 'executing') return;  // already finalized
      this.liveSyncResults = payload;
      this._liveSyncLogRun(payload);
      this.liveSyncExecuting = false;
      this.liveSyncStep = 'done';
      if (payload.status === 'error') this.toast('Execution failed: ' + (payload.error || 'unknown'), 'error');
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

    // A transaction that creates a brand-new collection in the destination.
    _isCollectionCreate(t) {
      return t.action === 'CREATE' && t.resource_type === 'collection';
    },

    _collectionNameOf(t) {
      return (t.meta && t.meta.collection_title) || t.new_value || '(unnamed)';
    },

    // Group new-collection transactions (from the currently filtered set) by
    // collection name so they can be shown as one expandable/collapsible block.
    liveSyncCollectionGroups() {
      const groups = {};
      for (const t of this.liveSyncFilteredTransactions()) {
        if (!this._isCollectionCreate(t)) continue;
        const name = this._collectionNameOf(t);
        (groups[name] = groups[name] || []).push(t);
      }
      return Object.keys(groups).map(name => ({ name, key: name, txns: groups[name] }));
    },

    // Everything except the grouped collection creations (rendered as a flat list).
    liveSyncNonCollectionTransactions() {
      return this.liveSyncFilteredTransactions().filter(t => !this._isCollectionCreate(t));
    },

    liveSyncToggleGroup(name) {
      this.liveSyncExpandedGroups = { ...this.liveSyncExpandedGroups, [name]: !this.liveSyncExpandedGroups[name] };
    },

    liveSyncGroupSet(grp, approve) {
      const ids = new Set(grp.txns.map(t => t.id));
      this.liveSyncTransactions.forEach(t => { if (ids.has(t.id)) t.approved = approve; });
      this.liveSyncTransactions = [...this.liveSyncTransactions];
    },

    // Rename the collection that will be written to the destination store. Updates
    // every transaction in the group so the executor creates it under the new name.
    liveSyncRenameCollection(oldName, newName) {
      newName = (newName || '').trim();
      if (!newName || newName === oldName) return;
      for (const t of this.liveSyncTransactions) {
        if (this._isCollectionCreate(t) && this._collectionNameOf(t) === oldName) {
          t.new_value = newName;
          t.meta = { ...(t.meta || {}), collection_title: newName };
        }
      }
      if (oldName in this.liveSyncExpandedGroups) {
        this.liveSyncExpandedGroups[newName] = this.liveSyncExpandedGroups[oldName];
        delete this.liveSyncExpandedGroups[oldName];
      }
      this.liveSyncTransactions = [...this.liveSyncTransactions];
      this.toast(`Collection will be created as "${newName}"`, 'success', 2500);
    },

    // Append the results of an execute run to the change log (newest first).
    _liveSyncLogRun(result) {
      const byId = {};
      this.liveSyncTransactions.forEach(t => { byId[t.id] = t; });
      const stamp = new Date().toLocaleString();
      const entries = (result?.results || []).map(r => {
        const t = byId[r.id] || {};
        const field = t.field && t.field !== '*' ? ` (${t.field})` : '';
        return {
          time: stamp,
          domain: this.liveSyncDest,
          status: r.status,
          text: `${(t.action || '').toUpperCase()} ${(t.resource_type || '').replace('_', ' ')} — ${t.title || ''}${field}`,
          error: r.error || '',
        };
      });
      this.liveSyncChangeLog = [...entries, ...this.liveSyncChangeLog].slice(0, 300);
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
        // e.message carries the server detail — e.g. the list of unreachable
        // Shopify domains. Show it as-is (multi-line) and hold it longer so the
        // user can read every domain before it dismisses.
        this.toast(e.message, 'error', 9000);
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
        // Auth + shop read can succeed while product read is blocked by a missing
        // scope (products_ok === false) — surface that as a warning, not a green ✓.
        const status = !result.ok ? 'error' : (result.products_ok === false ? 'warn' : 'ok');
        this.shopifyTestStatus = { ...this.shopifyTestStatus, [domain]: status };
        this.shopifyTestMessage = {
          ...this.shopifyTestMessage,
          [domain]: !result.ok ? result.error
            : (result.products_ok === false ? result.warning : `Connected — ${result.shop_name} (${result.plan})`),
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
        case 'live_sync_progress':
          if (this.liveSyncStep === 'executing')
            this.liveSyncProgress = { done: msg.done, total: msg.total, ok: msg.ok, errors: msg.errors };
          break;
        case 'live_sync_complete':
          this._finishLiveExecute(msg);
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
