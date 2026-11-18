// Anki Leech Doctor & Mnemonic Studio Frontend Client

let state = {
  decks: [],
  selectedDeck: "",
  cards: [],
  currentIndex: 0,
  currentCard: null,
  currentConfusableCards: [],
  kanjiDetailsCache: {},
  chatHistories: {},
  currentGeneratedMnemonic: "",
  currentGeneratedSentence: null,
  jlptLevel: "N3",
  kanjiStrategy: "hybrid",
  // Real values come from /api/config (config_defaults.py); these only cover the first paint.
  kanjiDeckName: "",
  mnemonicStyle: "playful",
  targetMiningDeck: "Mining",
  grammarDeckBase: "Mining::Grammar",
  miningCardType: "vocab",
  leechSearchQuery: "tag:leech is:suspended",
  allPersonas: [
    "Software Engineering, Debugging & Tech Life",
    "Motorcycle Riding, Track Days & Garage Mechanics",
    "Witty & Absurd Tokyo Comedy",
    "Dark Sci-Fi & Cyberpunk Dystopia",
    "Gaming, RPGs & Anime Tropes",
    "Fitness, Weightlifting & Gym Life",
    "Tokyo Street Food, Izakayas & Nightlife"
  ],
  activePersonas: [
    "Software Engineering, Debugging & Tech Life",
    "Motorcycle Riding, Track Days & Garage Mechanics",
    "Witty & Absurd Tokyo Comedy",
    "Dark Sci-Fi & Cyberpunk Dystopia"
  ],
  config: {},
  pendingDeleteCard: null,
  notesEditorMode: "wysiwyg",
  personaPoolCollapsed: false,
  radarCollapsed: false,
  kanjiCollapsed: false,
  lastUnsuspendedCard: null,
  cardMnemonicChanged: false,
  cardSentenceChanged: false,
  cardInitialNotes: "",
  cardInitialSentKanji: "",
  cardInitialSentEng: "",
  unsuspendConfirmPending: false,
  leechStatusFilter: "suspended",
  searchQuery: "",
  cardsRequestId: 0,
  allLoadedCards: [],
  systemHealth: { anki: false, gemini: false, rag: false }
};

// DOM Elements
const el = {
  globalJlptSelect: document.getElementById("global-jlpt-select"),
  deckSelect: document.getElementById("deck-select"),
  btnPrev: document.getElementById("btn-prev-card"),
  btnNext: document.getElementById("btn-next-card"),
  cardCounter: document.getElementById("card-counter"),
  ankiStatus: document.getElementById("anki-status"),
  ragStatus: document.getElementById("rag-status"),
  aiStatus: document.getElementById("ai-status"),
  btnOpenSettings: document.getElementById("btn-open-settings"),
  btnCloseSettings: document.getElementById("btn-close-settings"),
  settingsModal: document.getElementById("settings-modal"),
  btnSaveSettings: document.getElementById("btn-save-settings"),

  // Health and Search navigation elements
  topNav: document.querySelector(".top-nav"),
  btnMobileMenuToggle: document.getElementById("btn-mobile-menu-toggle"),
  hamburgerIcon: document.getElementById("hamburger-icon"),
  mobileViewTabs: document.getElementById("mobile-view-tabs"),
  navSearchWrap: document.getElementById("nav-search-wrap"),
  globalStatusDot: document.getElementById("global-status-dot"),
  filterStatusSelect: document.getElementById("filter-status-select"),
  vocabSearchInput: document.getElementById("vocab-search-input"),
  btnClearSearch: document.getElementById("btn-clear-search"),
  settingsSummaryDot: document.getElementById("settings-summary-dot"),
  settingsSummaryBadge: document.getElementById("settings-summary-badge"),
  statusCardAnki: document.getElementById("status-card-anki"),
  dotAnki: document.getElementById("dot-anki"),
  detailAnki: document.getElementById("detail-anki"),
  statusCardGemini: document.getElementById("status-card-gemini"),
  dotGemini: document.getElementById("dot-gemini"),
  detailGemini: document.getElementById("detail-gemini"),
  statusCardRag: document.getElementById("status-card-rag"),
  dotRag: document.getElementById("dot-rag"),
  detailRag: document.getElementById("detail-rag"),

  // Card details
  deckBadge: document.getElementById("deck-badge"),
  statusBadge: document.getElementById("status-badge"),
  vocabFurigana: document.getElementById("vocab-furigana-display"),
  vocabKanji: document.getElementById("vocab-kanji-display"),
  vocabDef: document.getElementById("vocab-def-display"),
  btnToggleVocabEdit: document.getElementById("btn-toggle-vocab-edit"),
  vocabEditor: document.getElementById("vocab-editor"),
  editVocabKanji: document.getElementById("edit-vocab-kanji"),
  editVocabFurigana: document.getElementById("edit-vocab-furigana"),
  editVocabDef: document.getElementById("edit-vocab-def"),
  btnSaveInlineVocab: document.getElementById("btn-save-inline-vocab"),
  btnCancelInlineVocab: document.getElementById("btn-cancel-inline-vocab"),

  sentenceRuby: document.getElementById("sentence-ruby-display"),
  sentenceEng: document.getElementById("sentence-eng-display"),
  cardNotesPreview: document.getElementById("card-notes-preview"),

  // Collision Radar
  deckCollisionRadar: document.getElementById("deck-collision-radar"),
  radarHeader: document.getElementById("radar-header"),
  btnToggleRadarCollapse: document.getElementById("btn-toggle-radar-collapse"),
  radarCollapseChevron: document.getElementById("radar-collapse-chevron"),
  collisionCountBadge: document.getElementById("collision-count-badge"),
  radarCardsList: document.getElementById("radar-cards-list"),

  // Kanji Section
  kanjiStoriesSection: document.getElementById("kanji-stories-section"),
  kanjiSectionHeader: document.getElementById("kanji-section-header"),
  btnToggleKanjiCollapse: document.getElementById("btn-toggle-kanji-collapse"),
  kanjiCollapseChevron: document.getElementById("kanji-collapse-chevron"),
  kanjiCardsContainer: document.getElementById("kanji-cards-container"),
  kanjiCountBadge: document.getElementById("kanji-count-badge"),

  // Inline Sentence editor
  btnToggleSentenceEdit: document.getElementById("btn-toggle-sentence-edit"),
  sentenceEditor: document.getElementById("sentence-editor"),
  editSentKanji: document.getElementById("edit-sent-kanji"),
  editSentFurigana: document.getElementById("edit-sent-furigana"),
  editSentEng: document.getElementById("edit-sent-eng"),
  btnSaveInlineSentence: document.getElementById("btn-save-inline-sentence"),
  btnCancelInlineSentence: document.getElementById("btn-cancel-inline-sentence"),

  // Inline Notes editor (WYSIWYG & HTML)
  btnToggleNotesEdit: document.getElementById("btn-toggle-notes-edit"),
  notesEditor: document.getElementById("notes-editor"),
  notesModeToggle: document.getElementById("notes-mode-toggle"),
  btnModeWysiwyg: document.getElementById("btn-mode-wysiwyg"),
  btnModeHtml: document.getElementById("btn-mode-html"),
  notesWysiwygToolbar: document.getElementById("notes-wysiwyg-toolbar"),
  notesWysiwygEditor: document.getElementById("notes-wysiwyg-editor"),
  editCardNotes: document.getElementById("edit-card-notes"),
  btnSaveInlineNotes: document.getElementById("btn-save-inline-notes"),
  btnCancelInlineNotes: document.getElementById("btn-cancel-inline-notes"),

  // AI Tabs & Studio
  aiTabs: document.querySelectorAll(".ai-tab"),
  tabContents: document.querySelectorAll(".tab-content"),
  btnGenMnemonic: document.getElementById("btn-gen-mnemonic"),
  mnemonicStyleGroup: document.getElementById("mnemonic-style-group"),
  mnemonicStyleButtons: document.querySelectorAll(".btn-style-pill"),
  mnemonicCustomInstruction: document.getElementById("mnemonic-custom-instruction"),
  mnemonicOutput: document.getElementById("mnemonic-output-container"),
  mnemonicEditorWrap: document.getElementById("mnemonic-editor-wrap"),
  editMnemonicTextarea: document.getElementById("edit-mnemonic-textarea"),
  mnemonicActions: document.getElementById("mnemonic-actions"),
  btnSaveMnemonicAnki: document.getElementById("btn-save-mnemonic-anki"),
  btnEditMnemonic: document.getElementById("btn-edit-mnemonic"),
  btnCancelEditMnemonic: document.getElementById("btn-cancel-edit-mnemonic"),

  // Sentence Studio & Multi-Persona Pool
  btnGenSentence: document.getElementById("btn-gen-sentence"),
  personaPoolSection: document.getElementById("persona-pool-section"),
  personaPoolHeader: document.getElementById("persona-pool-header"),
  btnTogglePersonaPool: document.getElementById("btn-toggle-persona-pool"),
  personaCollapseChevron: document.getElementById("persona-collapse-chevron"),
  personaCollapsedSummary: document.getElementById("persona-collapsed-summary"),
  personaPoolActions: document.getElementById("persona-pool-actions"),
  personaChipsContainer: document.getElementById("persona-chips-container"),
  btnSelectAllPersonas: document.getElementById("btn-select-all-personas"),
  btnResetPersonas: document.getElementById("btn-reset-personas"),
  newPersonaInput: document.getElementById("new-persona-input"),
  btnAddPersona: document.getElementById("btn-add-persona"),
  activePersonaCount: document.getElementById("active-persona-count"),
  sentenceCustomTopic: document.getElementById("sentence-custom-topic"),
  sentenceOutput: document.getElementById("sentence-output-container"),
  sentenceActions: document.getElementById("sentence-actions"),
  btnApplySentenceAnki: document.getElementById("btn-apply-sentence-anki"),

  // Chat Studio
  chatForm: document.getElementById("chat-form"),
  chatInput: document.getElementById("chat-input"),
  chatMessages: document.getElementById("chat-messages-container"),
  btnClearChat: document.getElementById("btn-clear-chat"),
  quickQuestions: document.querySelectorAll(".quick-q"),

  // Bottom action bar
  btnFooterUndo: document.getElementById("btn-footer-undo"),
  btnFooterDeleteCard: document.getElementById("btn-footer-delete-card"),
  btnFooterDeleteDuplicate: document.getElementById("btn-footer-delete-duplicate"),
  btnFooterUnsuspend: document.getElementById("btn-footer-unsuspend"),
  btnFooterSkip: document.getElementById("btn-footer-skip"),
  btnFooterAddMined: document.getElementById("btn-footer-add-mined"),
  btnAddMinedLabel: document.getElementById("btn-add-mined-label"),
  btnFooterCancelDraft: document.getElementById("btn-footer-cancel-draft"),

  // Delete Confirmation Modal
  deleteConfirmModal: document.getElementById("delete-confirm-modal"),
  btnCloseDeleteConfirm: document.getElementById("btn-close-delete-confirm"),
  btnCancelDelete: document.getElementById("btn-cancel-delete"),
  btnConfirmDelete: document.getElementById("btn-confirm-delete"),
  deleteConfirmVocabKanji: document.getElementById("delete-confirm-vocab-kanji"),
  deleteConfirmVocabFurigana: document.getElementById("delete-confirm-vocab-furigana"),
  deleteConfirmVocabDef: document.getElementById("delete-confirm-vocab-def"),
  deleteConfirmDeckName: document.getElementById("delete-confirm-deck-name"),
  deleteConfirmCardId: document.getElementById("delete-confirm-card-id"),

  // Unsuspend Confirmation Modal
  unsuspendConfirmModal: document.getElementById("unsuspend-confirm-modal"),
  btnCloseUnsuspendConfirm: document.getElementById("btn-close-unsuspend-confirm"),
  btnCancelUnsuspendModal: document.getElementById("btn-cancel-unsuspend-modal"),
  btnConfirmOverrideUnsuspend: document.getElementById("btn-confirm-override-unsuspend"),
  unsuspendConfirmVocabKanji: document.getElementById("unsuspend-confirm-vocab-kanji"),
  unsuspendCheckMnemonic: document.getElementById("unsuspend-check-mnemonic"),
  unsuspendCheckSentence: document.getElementById("unsuspend-check-sentence"),
  unsuspendIconMnemonic: document.getElementById("unsuspend-icon-mnemonic"),
  unsuspendIconSentence: document.getElementById("unsuspend-icon-sentence"),
  unsuspendStatusMnemonic: document.getElementById("unsuspend-status-mnemonic"),
  unsuspendStatusSentence: document.getElementById("unsuspend-status-sentence"),

  // Mining Modal & Form
  btnOpenMineModal: document.getElementById("btn-open-mine-modal"),
  miningModal: document.getElementById("mining-modal"),
  miningModalTargetDeck: document.getElementById("mining-modal-target-deck"),
  btnCloseMining: document.getElementById("btn-close-mining"),
  btnCancelMining: document.getElementById("btn-cancel-mining"),
  miningForm: document.getElementById("mining-form"),
  miningInputVocab: document.getElementById("mining-input-vocab"),
  miningInputHint: document.getElementById("mining-input-hint"),
  miningModalTitle: document.getElementById("mining-modal-title"),
  miningTypeButtons: document.querySelectorAll(".btn-mining-type"),
  miningGrammarLevel: document.getElementById("mining-grammar-level"),
  miningInputVocabLabel: document.getElementById("mining-input-vocab-label"),
  miningInputVocabHelp: document.getElementById("mining-input-vocab-help"),
  miningInputHintHelp: document.getElementById("mining-input-hint-help"),
  btnSubmitMining: document.getElementById("btn-submit-mining"),

  // Settings form
  settingApiKey: document.getElementById("setting-api-key"),
  settingModel: document.getElementById("setting-model"),
  settingPersona: document.getElementById("setting-persona"),
  settingTone: document.getElementById("setting-tone"),
  settingJlptLevel: document.getElementById("setting-jlpt-level"),
  settingKanjiStrategy: document.getElementById("setting-kanji-strategy"),
  settingKanjiDeck: document.getElementById("setting-kanji-deck"),
  settingKanjiDeckWrap: document.getElementById("setting-kanji-deck-wrap"),
  settingMnemonicStyle: document.getElementById("setting-mnemonic-style"),
  settingMiningDeck: document.getElementById("setting-mining-deck"),
  settingLeechQuery: document.getElementById("setting-leech-query"),
  settingGrammarDeck: document.getElementById("setting-grammar-deck"),
  settingReviewScope: document.getElementById("setting-review-scope"),
  settingNoteType: document.getElementById("setting-note-type"),

  // RAG settings
  ragStatCount: document.getElementById("rag-stat-count"),
  ragStatSync: document.getElementById("rag-stat-sync"),
  btnSyncRagIndex: document.getElementById("btn-sync-rag-index"),
  ragSyncFeedback: document.getElementById("rag-sync-feedback"),
  ragDeckChecklist: document.getElementById("rag-deck-checklist"),
  btnRagSelectActive: document.getElementById("btn-rag-select-active"),
  btnRagSelectAll: document.getElementById("btn-rag-select-all"),
  btnRagSelectNone: document.getElementById("btn-rag-select-none"),
};

// Utilities

// Escape text before putting it into innerHTML. Use for anything that is plain text:
// user input, deck names, error messages. (Anki field content is HTML by design.)
function escapeHtml(value) {
  return String(value ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

// Markdown from the AI or your notes, rendered and then sanitized
function renderMarkdown(text) {
  const html = marked.parse(text || "");
  return window.DOMPurify ? DOMPurify.sanitize(html) : escapeHtml(text);
}

function showToast(message, type = "info", action = null) {
  const container = document.getElementById("toast-container");
  const toast = document.createElement("div");
  toast.className = `toast toast-${type}`;
  toast.innerHTML = `<span>${type === "success" ? "✓" : type === "error" ? "⚠" : "ℹ"}</span> <span>${escapeHtml(message)}</span>`;
  if (action && action.label && action.onClick) {
    const actionBtn = document.createElement("button");
    actionBtn.className = "toast-action-btn";
    actionBtn.textContent = action.label;
    actionBtn.addEventListener("click", (e) => {
      e.stopPropagation();
      action.onClick();
      toast.remove();
    });
    toast.appendChild(actionBtn);
  }
  container.appendChild(toast);
  const timeoutMs = action ? 6000 : 3500;
  setTimeout(() => {
    toast.style.opacity = "0";
    setTimeout(() => toast.remove(), 200);
  }, timeoutMs);
}

// Convert bracket furigana syntax (e.g. 来週[らいしゅう]の 社員[しゃいん]) to HTML Ruby
function parseFuriganaRuby(text) {
  if (!text) return "";
  // Match Word[reading]
  const regex = /([^\s\[\]<>\n]+)\[([^\[\]]+)\]/g;
  return text.replace(regex, (match, kanji, kana) => {
    return `<ruby>${kanji}<rt>${kana}</rt></ruby>`;
  });
}

// Collapsible Section Management (Radar, Kanji Breakdown)
function initCollapsibleSections() {
  const savedRadarCollapse = localStorage.getItem("anki_radar_collapsed") === "true";
  setRadarCollapsed(savedRadarCollapse);

  const savedKanjiCollapse = localStorage.getItem("anki_kanji_collapsed") === "true";
  setKanjiCollapsed(savedKanjiCollapse);
}

function setRadarCollapsed(collapsed) {
  state.radarCollapsed = collapsed;
  if (!el.deckCollisionRadar) return;
  if (collapsed) {
    el.deckCollisionRadar.classList.add("collapsed");
    if (el.radarCollapseChevron) el.radarCollapseChevron.textContent = "▶";
    if (el.btnToggleRadarCollapse) el.btnToggleRadarCollapse.setAttribute("title", "Expand Collision Radar");
  } else {
    el.deckCollisionRadar.classList.remove("collapsed");
    if (el.radarCollapseChevron) el.radarCollapseChevron.textContent = "▼";
    if (el.btnToggleRadarCollapse) el.btnToggleRadarCollapse.setAttribute("title", "Collapse Collision Radar");
  }
  localStorage.setItem("anki_radar_collapsed", collapsed ? "true" : "false");
}

function toggleRadarCollapse() {
  setRadarCollapsed(!state.radarCollapsed);
}

function setKanjiCollapsed(collapsed) {
  state.kanjiCollapsed = collapsed;
  if (!el.kanjiStoriesSection) return;
  if (collapsed) {
    el.kanjiStoriesSection.classList.add("collapsed");
    if (el.kanjiCollapseChevron) el.kanjiCollapseChevron.textContent = "▶";
    if (el.btnToggleKanjiCollapse) el.btnToggleKanjiCollapse.setAttribute("title", "Expand Kanji Breakdown");
  } else {
    el.kanjiStoriesSection.classList.remove("collapsed");
    if (el.kanjiCollapseChevron) el.kanjiCollapseChevron.textContent = "▼";
    if (el.btnToggleKanjiCollapse) el.btnToggleKanjiCollapse.setAttribute("title", "Collapse Kanji Breakdown");
  }
  localStorage.setItem("anki_kanji_collapsed", collapsed ? "true" : "false");
}

function toggleKanjiCollapse() {
  setKanjiCollapsed(!state.kanjiCollapsed);
}

// Mobile View Navigation Helpers
function setMobileView(view) {
  document.body.setAttribute("data-mobile-view", view);
  if (el.mobileViewTabs) {
    el.mobileViewTabs.querySelectorAll(".mobile-view-tab").forEach(tab => {
      tab.classList.toggle("active", tab.dataset.view === view);
    });
  }
}

function initMobileEnhancements() {
  // 1. Mobile Hamburger Menu Toggle
  if (el.btnMobileMenuToggle && el.topNav) {
    el.btnMobileMenuToggle.addEventListener("click", (e) => {
      e.stopPropagation();
      const isOpen = el.topNav.classList.toggle("menu-open");
      if (el.hamburgerIcon) {
        el.hamburgerIcon.textContent = isOpen ? "✕" : "☰";
      }
    });

    // Close menu when tapping outside
    document.addEventListener("click", (e) => {
      if (el.topNav && el.topNav.classList.contains("menu-open") && !el.topNav.contains(e.target)) {
        el.topNav.classList.remove("menu-open");
        if (el.hamburgerIcon) el.hamburgerIcon.textContent = "☰";
      }
    });

    // Auto-close menu on selection
    if (el.deckSelect) {
      el.deckSelect.addEventListener("change", () => {
        el.topNav.classList.remove("menu-open");
        if (el.hamburgerIcon) el.hamburgerIcon.textContent = "☰";
      });
    }
    if (el.filterStatusSelect) {
      el.filterStatusSelect.addEventListener("change", () => {
        el.topNav.classList.remove("menu-open");
        if (el.hamburgerIcon) el.hamburgerIcon.textContent = "☰";
      });
    }
    if (el.btnOpenMineModal) {
      el.btnOpenMineModal.addEventListener("click", () => {
        el.topNav.classList.remove("menu-open");
        if (el.hamburgerIcon) el.hamburgerIcon.textContent = "☰";
      });
    }
    if (el.btnOpenSettings) {
      el.btnOpenSettings.addEventListener("click", () => {
        el.topNav.classList.remove("menu-open");
        if (el.hamburgerIcon) el.hamburgerIcon.textContent = "☰";
      });
    }
  }

  // 2. Mobile View Switcher Tabs (Study & AI | Kanji & Radar | Notes)
  if (el.mobileViewTabs) {
    const tabs = el.mobileViewTabs.querySelectorAll(".mobile-view-tab");
    tabs.forEach(tab => {
      tab.addEventListener("click", () => {
        const view = tab.dataset.view;
        setMobileView(view);
      });
    });
  }

  // 3. Touch Swipe Navigation for Cards
  initTouchSwipe();
}

function initTouchSwipe() {
  const target = document.querySelector(".workspace") || document.body;
  let startX = 0;
  let startY = 0;
  let startTime = 0;

  target.addEventListener("touchstart", (e) => {
    // Ignore touches inside inputs, textareas, buttons, selectors, contenteditable, or horizontal scrollers
    if (e.target.closest("input, textarea, select, [contenteditable='true'], button, .mnemonic-style-bar, .wysiwyg-toolbar")) {
      return;
    }
    const touch = e.changedTouches[0];
    startX = touch.clientX;
    startY = touch.clientY;
    startTime = Date.now();
  }, { passive: true });

  target.addEventListener("touchend", (e) => {
    if (!startX || !startY) return;
    const touch = e.changedTouches[0];
    const distX = touch.clientX - startX;
    const distY = touch.clientY - startY;
    const elapsedTime = Date.now() - startTime;

    startX = 0;
    startY = 0;

    // Minimum horizontal swipe distance of 50px, vertical drift <= 60px, elapsed time <= 600ms
    if (Math.abs(distX) >= 50 && Math.abs(distY) <= 60 && elapsedTime <= 600) {
      if (distX < 0) {
        // Swipe Left -> Next Card
        if (state.currentIndex < state.cards.length - 1) {
          if (navigator.vibrate) navigator.vibrate(12);
          state.currentIndex++;
          renderCurrentCard();
        }
      } else {
        // Swipe Right -> Prev Card
        if (state.currentIndex > 0) {
          if (navigator.vibrate) navigator.vibrate(12);
          state.currentIndex--;
          renderCurrentCard();
        }
      }
    }
  }, { passive: true });
}

// Initialize Application
async function init() {
  setupEventListeners();
  initPersonas();
  initCollapsibleSections();
  initMobileEnhancements();
  await checkStatus();
  await loadConfig();
  await loadDecks();
}

async function checkStatus() {
  try {
    const res = await fetch("/api/status");
    const data = await res.json();
    
    const ankiOk = Boolean(data.ankiOnline);
    const geminiOk = Boolean(data.hasApiKey);
    const ragStats = data.ragStats || {};
    const ragCount = ragStats.indexedCount || 0;
    const ragOk = ragCount > 0;
    const allOk = ankiOk && geminiOk;

    state.systemHealth = { anki: ankiOk, gemini: geminiOk, rag: ragOk };

    // Update global status dot in top navigation
    if (el.globalStatusDot) {
      if (allOk) {
        el.globalStatusDot.className = "global-status-dot status-dot-good";
        el.globalStatusDot.setAttribute("title", "All Systems Operational (Anki & Gemini Connected)");
      } else {
        el.globalStatusDot.className = "global-status-dot status-dot-bad";
        const issues = [];
        if (!ankiOk) issues.push("Anki Disconnected");
        if (!geminiOk) issues.push("Gemini API Key Needed");
        el.globalStatusDot.setAttribute("title", `System Attention Needed: ${issues.join(", ")}`);
      }
    }

    // Update Settings Modal Health Dashboard
    if (el.settingsSummaryDot) {
      el.settingsSummaryDot.className = allOk ? "global-status-dot status-dot-good" : "global-status-dot status-dot-bad";
    }
    if (el.settingsSummaryBadge) {
      if (allOk) {
        el.settingsSummaryBadge.className = "badge badge-success";
        el.settingsSummaryBadge.textContent = "All Healthy";
      } else {
        el.settingsSummaryBadge.className = "badge badge-danger";
        el.settingsSummaryBadge.textContent = "Attention Needed";
      }
    }

    // Anki card in settings
    if (el.dotAnki && el.detailAnki) {
      if (ankiOk) {
        el.dotAnki.className = "status-item-dot status-dot-good";
        el.detailAnki.textContent = "Connected (Port 8765)";
      } else {
        el.dotAnki.className = "status-item-dot status-dot-bad";
        el.detailAnki.textContent = "Disconnected (Port 8765)";
        showToast("Anki is not reachable. Ensure Anki is running with AnkiConnect enabled.", "error");
      }
    }

    // Gemini card in settings
    if (el.dotGemini && el.detailGemini) {
      if (geminiOk) {
        el.dotGemini.className = "status-item-dot status-dot-good";
        el.detailGemini.textContent = `Ready (${data.model || "Gemini"})`;
      } else {
        el.dotGemini.className = "status-item-dot status-dot-bad";
        el.detailGemini.textContent = "API Key Missing";
      }
    }

    // RAG card in settings
    if (el.dotRag && el.detailRag) {
      if (ragCount > 0) {
        el.dotRag.className = "status-item-dot status-dot-good";
        el.detailRag.textContent = `Active (${ragCount.toLocaleString()} cards)`;
      } else {
        el.dotRag.className = "status-item-dot status-dot-warning";
        el.detailRag.textContent = "Not indexed yet";
      }
    }

    // Legacy status elements fallback if present
    if (el.ankiStatus) {
      el.ankiStatus.className = ankiOk ? "status-pill status-online" : "status-pill status-offline";
      el.ankiStatus.innerHTML = `<span class="status-dot"></span> Anki ${ankiOk ? "Online" : "Disconnected"}`;
    }
    if (el.aiStatus) {
      el.aiStatus.className = geminiOk ? "status-pill status-online" : "status-pill status-warning";
      el.aiStatus.innerHTML = `<span class="status-dot"></span> Gemini ${geminiOk ? `Ready (${escapeHtml(data.model)})` : "API Key Needed"}`;
    }
    if (el.ragStatus) {
      el.ragStatus.className = ragCount > 0 ? "status-pill status-online" : "status-pill status-warning";
      el.ragStatus.innerHTML = `<span class="status-dot"></span> RAG (${ragCount.toLocaleString()} cards)`;
    }
  } catch (err) {
    console.error("Status check error:", err);
    if (el.globalStatusDot) {
      el.globalStatusDot.className = "global-status-dot status-dot-bad";
      el.globalStatusDot.setAttribute("title", "Server Error Checking Status");
    }
  }
}

async function loadConfig() {
  try {
    const res = await fetch("/api/config");
    const cfg = await res.json();
    state.config = cfg;
    
    state.jlptLevel = cfg.jlptLevel || "N3";
    state.kanjiStrategy = cfg.kanjiStrategy || "hybrid";
    state.kanjiDeckName = cfg.kanjiDeckName || "";
    state.mnemonicStyle = cfg.mnemonicStyle || "playful";
    state.targetMiningDeck = cfg.targetMiningDeck || state.targetMiningDeck;
    state.grammarDeckBase = cfg.grammarDeckBase || state.grammarDeckBase;
    state.leechSearchQuery = cfg.leechSearchQuery || state.leechSearchQuery;

    if (el.globalJlptSelect) el.globalJlptSelect.value = state.jlptLevel;
    if (el.settingJlptLevel) el.settingJlptLevel.value = state.jlptLevel;
    if (el.settingPersona) el.settingPersona.value = cfg.persona || "";
    if (el.settingTone) el.settingTone.value = cfg.mnemonicTone || "";
    if (el.settingKanjiStrategy) el.settingKanjiStrategy.value = state.kanjiStrategy;
    if (el.settingMnemonicStyle) el.settingMnemonicStyle.value = state.mnemonicStyle;
    if (el.settingMiningDeck) el.settingMiningDeck.value = state.targetMiningDeck;
    if (el.settingLeechQuery) el.settingLeechQuery.value = state.leechSearchQuery;
    if (el.settingGrammarDeck) el.settingGrammarDeck.value = state.grammarDeckBase;
    if (el.settingReviewScope) el.settingReviewScope.value = cfg.reviewScopeQuery || "";
    if (el.settingNoteType) el.settingNoteType.value = cfg.miningNoteType || "";
    if (el.settingRagExcludeSuspended) el.settingRagExcludeSuspended.checked = Boolean(cfg.ragExcludeSuspended);
    if (el.miningModalTargetDeck) el.miningModalTargetDeck.textContent = state.targetMiningDeck;
    if (el.btnAddMinedLabel) el.btnAddMinedLabel.textContent = `Add to ${state.targetMiningDeck.split("::").pop()}`;

    // RAG Stats
    if (cfg.ragStats) {
      if (el.ragStatCount) el.ragStatCount.textContent = cfg.ragStats.indexedCount || 0;
      if (el.ragStatSync) el.ragStatSync.textContent = cfg.ragStats.lastSync || "Never";
      if (el.ragStatus) {
        el.ragStatus.innerHTML = `<span class="status-dot"></span> RAG (${cfg.ragStats.indexedCount || 0} cards)`;
      }
    }

    // Update active style button in studio
    updateMnemonicStyleButtons(state.mnemonicStyle);

    // Load available models dynamically
    try {
      const mRes = await fetch("/api/models");
      const mData = await mRes.json();
      if (mData.models && mData.models.length > 0) {
        el.settingModel.innerHTML = "";
        mData.models.forEach(m => {
          const opt = document.createElement("option");
          opt.value = m;
          opt.textContent = m === "gemini-flash-latest" ? "gemini-flash-latest (Recommended)" : m;
          el.settingModel.appendChild(opt);
        });
      }
    } catch (e) {
      console.warn("Could not fetch dynamic models list", e);
    }
    el.settingModel.value = cfg.model || "gemini-flash-latest";
  } catch (err) {
    console.error("Error loading config:", err);
  }
}

function updateMnemonicStyleButtons(selectedStyle) {
  if (!el.mnemonicStyleButtons) return;
  el.mnemonicStyleButtons.forEach(btn => {
    if (btn.dataset.style === selectedStyle) {
      btn.classList.add("active");
    } else {
      btn.classList.remove("active");
    }
  });
}

function renderRagDeckChecklist(decks, savedSelection = null) {
  if (!el.ragDeckChecklist) return;
  el.ragDeckChecklist.innerHTML = "";

  if (!decks || decks.length === 0) {
    el.ragDeckChecklist.innerHTML = '<div style="color: var(--text-subtle); font-size: 0.8rem; padding: 0.5rem;">No Anki decks found.</div>';
    return;
  }

  // Find parent container folders (e.g. "Ankidrone Essentials V8") so we only render leaf study decks
  const allNames = decks.map(d => (d.name || d));
  const parentDecks = new Set();
  allNames.forEach(d => {
    const parts = d.split("::");
    for (let i = 1; i < parts.length; i++) {
      parentDecks.add(parts.slice(0, i).join("::"));
    }
  });

  const leafDecks = decks.filter(d => {
    const name = d.name || d;
    return !parentDecks.has(name);
  });

  leafDecks.forEach(d => {
    const deckName = d.name || d;
    const lower = deckName.toLowerCase();
    
    // Determine check state: if saved selection exists, respect it. Else default to N5, N4, N3, Mining, RTK.
    let isChecked = false;
    if (savedSelection && Array.isArray(savedSelection) && savedSelection.length > 0) {
      isChecked = savedSelection.includes(deckName);
    } else {
      if (lower.includes("tango n1") || lower.includes("tango n2") || lower.includes("jlpt n1") || lower.includes("jlpt n2")) {
        isChecked = false;
      } else {
        isChecked = true;
      }
    }

    const item = document.createElement("label");
    item.className = "rag-deck-item";
    
    let activeBadge = "";
    if (lower.includes("n5") || lower.includes("n4") || lower.includes("n3") || lower.includes("mining")) {
      activeBadge = '<span class="rag-deck-badge-active">Study Deck</span>';
    } else if (lower.includes("nihongoshark") || lower.includes("kanji")) {
      activeBadge = '<span class="rag-deck-badge-active" style="background: rgba(16, 185, 129, 0.15); color: #6ee7b7; border-color: rgba(16, 185, 129, 0.3);">Kanji Reference</span>';
    }

    item.innerHTML = `
      <input type="checkbox" class="rag-deck-checkbox" value="${escapeHtml(deckName)}" ${isChecked ? "checked" : ""}>
      <span class="rag-deck-item-name">${escapeHtml(deckName)}</span>
      ${activeBadge}
    `;
    el.ragDeckChecklist.appendChild(item);
  });
}

function getSelectedRagDecks() {
  if (!el.ragDeckChecklist) return [];
  const checkboxes = el.ragDeckChecklist.querySelectorAll(".rag-deck-checkbox");
  const selected = [];
  checkboxes.forEach(cb => {
    if (cb.checked) selected.push(cb.value);
  });
  return selected;
}

async function refreshDeckDropdownStats() {
  try {
    const res = await fetch("/api/decks");
    const data = await res.json();
    state.decks = data.decks || [];

    // Populate RAG deck checklist
    renderRagDeckChecklist(state.decks, state.config.ragDecks);

    const currentSelected = el.deckSelect.value;
    const selectedDeckObj = state.decks.find(d => d.name === currentSelected);

    // Calculate counts for the currently selected deck (or whole collection)
    const suspendedLeechCount = selectedDeckObj ? (selectedDeckObj.leechCount || 0) : (data.totalLeeches || 0);
    const suspendedCount = selectedDeckObj ? (selectedDeckObj.suspendedCount || 0) : (data.totalSuspended || 0);
    const activeLeechCount = selectedDeckObj ? (selectedDeckObj.activeLeechCount || 0) : (data.totalActiveLeeches || 0);
    const allLeechCount = selectedDeckObj
      ? ((selectedDeckObj.leechCount || 0) + (selectedDeckObj.activeLeechCount || 0))
      : (data.totalAllLeeches || ((data.totalLeeches || 0) + (data.totalActiveLeeches || 0)));
    const notReviewedCount = selectedDeckObj ? (selectedDeckObj.notReviewedCount || 0) : (data.totalNotReviewed || 0);

    // Update filter dropdown options with precise counts
    if (el.filterStatusSelect) {
      el.filterStatusSelect.innerHTML = `
        <option value="suspended_leech">🔴 Suspended + Leech (${suspendedLeechCount})</option>
        <option value="suspended">⏸️ Suspended (${suspendedCount})</option>
        <option value="active">⚡ Leech Tagged (Active) (${activeLeechCount})</option>
        <option value="all">🏷️ All Leech Tagged (${allLeechCount})</option>
        <option value="not_reviewed">⏳ Not Reviewed by AI (${notReviewedCount})</option>
      `;
      el.filterStatusSelect.value = state.leechStatusFilter;
    }

    // Header option based on current leechStatusFilter
    let totalFilterCount = data.totalLeeches || 0;
    let filterLabel = "suspended leeches";
    if (state.leechStatusFilter === "suspended") {
      totalFilterCount = data.totalSuspended || 0;
      filterLabel = "suspended cards";
    } else if (state.leechStatusFilter === "active") {
      totalFilterCount = data.totalActiveLeeches || 0;
      filterLabel = "active leeches";
    } else if (state.leechStatusFilter === "all") {
      totalFilterCount = data.totalAllLeeches || ((data.totalLeeches || 0) + (data.totalActiveLeeches || 0));
      filterLabel = "total leeches";
    } else if (state.leechStatusFilter === "not_reviewed") {
      totalFilterCount = data.totalNotReviewed || 0;
      filterLabel = "unreviewed cards";
    }
    el.deckSelect.innerHTML = `<option value="">All Review Cards (${totalFilterCount} ${filterLabel})</option>`;

    if (el.settingKanjiDeck) {
      el.settingKanjiDeck.innerHTML = "";
      const anyOpt = document.createElement("option");
      anyOpt.value = "";
      anyOpt.textContent = "(Any deck named *Kanji*)";
      anyOpt.selected = !state.kanjiDeckName;
      el.settingKanjiDeck.appendChild(anyOpt);
    }

    state.decks.forEach(d => {
      // Add to deck selector
      let countForFilter = d.leechCount || 0;
      if (state.leechStatusFilter === "suspended") countForFilter = d.suspendedCount || 0;
      else if (state.leechStatusFilter === "active") countForFilter = d.activeLeechCount || 0;
      else if (state.leechStatusFilter === "all") countForFilter = (d.leechCount || 0) + (d.activeLeechCount || 0);
      else if (state.leechStatusFilter === "not_reviewed") countForFilter = d.notReviewedCount || 0;

      const isGrammarDeck = Boolean(d.isGrammarDeck || (d.name && d.name.toLowerCase().includes("jlpt grammar")));
      if (countForFilter > 0 || d.leechCount > 0 || (d.suspendedCount || 0) > 0 || (d.notReviewedCount || 0) > 0 || d.isMiningDeck || isGrammarDeck || (d.name && d.name.toLowerCase().includes("mining"))) {
        const opt = document.createElement("option");
        opt.value = d.name;
        const label = d.name.split("::").pop();
        if (isGrammarDeck) {
          const grammarLabel = d.name.split("::").slice(-2).join(" › ");
          opt.textContent = countForFilter > 0
            ? `📘 ${grammarLabel} (${countForFilter})`
            : `📘 ${grammarLabel} (${d.totalCount || 0} cards)`;
        } else if (d.isMiningDeck || (d.name && d.name.toLowerCase().includes("mining"))) {
          opt.textContent = countForFilter > 0
            ? `⛏️ ${label} (${countForFilter})`
            : `⛏️ ${label} (${d.totalCount || 0} cards)`;
        } else {
          opt.textContent = `${label} (${countForFilter})`;
        }
        if (d.name === currentSelected) opt.selected = true;
        el.deckSelect.appendChild(opt);
      }

      // Add to kanji deck selector in settings
      if (el.settingKanjiDeck) {
        const kOpt = document.createElement("option");
        kOpt.value = d.name;
        kOpt.textContent = d.name;
        if (d.name === state.kanjiDeckName) kOpt.selected = true;
        el.settingKanjiDeck.appendChild(kOpt);
      }
    });
  } catch (err) {
    console.warn("Could not refresh deck dropdown stats", err);
  }
}

async function loadDecks() {
  // Card list and dropdown counts are independent: fetch them side by side.
  await Promise.all([loadCards(), refreshDeckDropdownStats()]);
}

function unsavedDrafts() {
  return (state.cards || []).filter(c => c && c.isDraft);
}

// Called before a deck/filter switch. Switching replaces the card list, so
// unsaved mined drafts would vanish silently; ask first.
function confirmDiscardDrafts() {
  const drafts = unsavedDrafts();
  if (drafts.length === 0) return true;
  const names = drafts.map(d => d.vocabKanji).slice(0, 3).join(", ");
  return window.confirm(`You have ${drafts.length} unsaved mined draft${drafts.length > 1 ? "s" : ""} (${names}). Switching will discard ${drafts.length > 1 ? "them" : "it"}. Continue?`);
}

function describeCurrentView() {
  const deckOpt = el.deckSelect && el.deckSelect.selectedOptions[0];
  const deck = state.selectedDeck ? state.selectedDeck.split("::").pop() : "All Review Cards";
  const statusOpt = el.filterStatusSelect && el.filterStatusSelect.selectedOptions[0];
  const status = statusOpt ? statusOpt.textContent.replace(/\s*\(\d+\)\s*$/, "") : "";
  return status ? `${deck} · ${status}` : (deckOpt ? deckOpt.textContent : deck);
}

function setCardsLoading(loading) {
  // Dim the card and lock the footer so actions can't hit the previous deck's card
  [".workspace", ".bottom-bar"].forEach(sel => {
    const node = document.querySelector(sel);
    if (node) node.classList.toggle("is-loading", loading);
  });
  if (el.deckSelect) el.deckSelect.setAttribute("aria-busy", loading ? "true" : "false");
  const indicator = document.getElementById("cards-loading-indicator");
  if (indicator) {
    indicator.classList.toggle("hidden", !loading);
    const label = indicator.querySelector(".cards-loading-label");
    if (label && loading) label.textContent = `Loading ${describeCurrentView()}…`;
  }
  if (loading && el.cardCounter) el.cardCounter.textContent = "Loading…";
}

async function loadCards(searchTerm = null) {
  // Only the newest request may render; older responses from fast switching are dropped.
  const requestId = ++state.cardsRequestId;
  setCardsLoading(true);
  const params = new URLSearchParams();
  if (state.selectedDeck) params.append("deck", state.selectedDeck);
  if (state.leechStatusFilter) params.append("status", state.leechStatusFilter);
  
  const term = searchTerm !== null ? searchTerm : state.searchQuery;
  if (term && term.trim()) {
    params.append("search", term.trim());
  }

  const qs = params.toString() ? `?${params.toString()}` : "";
  try {
    const res = await fetch(`/api/cards${qs}`);
    const data = await res.json();
    if (requestId !== state.cardsRequestId) return;
    if (!res.ok) throw new Error(data.detail || `HTTP ${res.status}`);
    state.allLoadedCards = data.cards || [];
    state.cards = [...state.allLoadedCards];
    state.currentIndex = 0;
    state.lastUnsuspendedCard = null;
    if (el.btnFooterUndo) el.btnFooterUndo.classList.add("hidden");
    renderCurrentCard();
  } catch (err) {
    if (requestId !== state.cardsRequestId) return;
    console.error("Error loading cards:", err);
    showToast(`Failed to load cards: ${err.message}`, "error");
    // Don't leave the previous deck's cards on screen as if they were this one's
    state.allLoadedCards = [];
    state.cards = [];
    renderCurrentCard();
  } finally {
    if (requestId === state.cardsRequestId) setCardsLoading(false);
  }
}

function filterCardsInMemory(query) {
  state.searchQuery = query || "";
  const q = (query || "").trim().toLowerCase();
  
  if (el.btnClearSearch) {
    if (q) el.btnClearSearch.classList.remove("hidden");
    else el.btnClearSearch.classList.add("hidden");
  }

  if (q) {
    el.navSearchWrap?.classList.add("has-query");
    el.topNav?.classList.add("has-search-query");
  } else {
    el.navSearchWrap?.classList.remove("has-query");
    el.topNav?.classList.remove("has-search-query");
  }
  
  if (!q) {
    state.cards = [...state.allLoadedCards];
  } else {
    state.cards = state.allLoadedCards.filter(c => {
      const k = (c.vocabKanji || "").toLowerCase();
      const f = (c.vocabFurigana || "").toLowerCase();
      const d = (c.vocabDef || "").toLowerCase();
      const sk = (c.sentKanji || "").toLowerCase();
      const se = (c.sentEng || "").toLowerCase();
      return k.includes(q) || f.includes(q) || d.includes(q) || sk.includes(q) || se.includes(q);
    });
  }
  state.currentIndex = 0;
  renderCurrentCard();
}

function clearSearch() {
  if (el.vocabSearchInput) el.vocabSearchInput.value = "";
  if (el.btnClearSearch) el.btnClearSearch.classList.add("hidden");
  el.navSearchWrap?.classList.remove("has-query", "expanded");
  el.topNav?.classList.remove("has-search-query", "search-expanded");
  state.searchQuery = "";
  state.cards = [...state.allLoadedCards];
  state.currentIndex = 0;
  renderCurrentCard();
}

async function renderCurrentCard() {
  if (!state.cards || state.cards.length === 0) {
    el.cardCounter.textContent = "0 of 0";
    el.vocabKanji.textContent = "No Cards Found";
    el.vocabFurigana.textContent = "";
    if (state.searchQuery) {
      el.vocabDef.textContent = `No cards found matching "${state.searchQuery}". Press Enter to search entire Anki collection, or clear search.`;
    } else {
      let filterLabel = "cards";
      if (state.leechStatusFilter === "suspended_leech") filterLabel = "suspended leeches (tag:leech is:suspended)";
      else if (state.leechStatusFilter === "suspended") filterLabel = "suspended cards (is:suspended)";
      else if (state.leechStatusFilter === "active") filterLabel = "active leeches (tag:leech -is:suspended)";
      else if (state.leechStatusFilter === "all") filterLabel = "leech-tagged cards (tag:leech)";
      else if (state.leechStatusFilter === "not_reviewed") filterLabel = "unreviewed cards (-tag:ai-mnemonic-reviewed)";
      el.vocabDef.textContent = `All caught up! No ${filterLabel} found in this deck. Switch filters above or click '+ Mine New Word'.`;
    }
    el.sentenceRuby.innerHTML = "";
    el.sentenceEng.textContent = "";
    el.kanjiCardsContainer.innerHTML = "";
    el.kanjiCountBadge.textContent = "0 Kanji";
    if (el.mnemonicCustomInstruction) el.mnemonicCustomInstruction.value = "";
    if (el.sentenceCustomTopic) el.sentenceCustomTopic.value = "";
    if (el.btnFooterAddMined) el.btnFooterAddMined.classList.add("hidden");
    if (el.btnFooterCancelDraft) el.btnFooterCancelDraft.classList.add("hidden");
    if (el.btnFooterUnsuspend) el.btnFooterUnsuspend.classList.add("hidden");
    if (el.btnFooterSkip) el.btnFooterSkip.classList.add("hidden");
    if (el.btnFooterDeleteCard) el.btnFooterDeleteCard.classList.add("hidden");
    return;
  }

  const card = state.cards[state.currentIndex];
  state.currentCard = card;

  // Reset card modification & confirmation state for this card
  state.cardInitialNotes = (card.notes || "").trim();
  state.cardInitialSentKanji = (card.sentKanji || "").trim();
  state.cardInitialSentEng = (card.sentEng || "").trim();
  // Content written while mining counts as this session's update, so a
  // just-saved card isn't treated as "nothing changed".
  state.cardMnemonicChanged = Boolean(card.justMined && (card.notes || "").trim());
  state.cardSentenceChanged = Boolean((card.justMined || card.personaSentence) && (card.sentKanji || "").trim());
  state.unsuspendConfirmPending = false;
  closeUnsuspendConfirmModal();
  resetUnsuspendButton();

  // Update Nav & Counter
  el.cardCounter.textContent = `Card ${state.currentIndex + 1} of ${state.cards.length}`;
  el.btnPrev.disabled = state.currentIndex === 0;
  el.btnNext.disabled = state.currentIndex === state.cards.length - 1;

  // Badge Status
  if (card.isDraft) {
    el.deckBadge.textContent = (card.deckName || state.targetMiningDeck).split("::").slice(-2).join(" › ");
    if (isGrammarCard(card)) {
      el.statusBadge.textContent = `📘 Grammar Draft · ${getCardJlptLevel(card)}`;
      el.statusBadge.className = "badge badge-grammar-draft";
    } else {
      el.statusBadge.textContent = "Draft (Unsaved)";
      el.statusBadge.className = "badge badge-mining-draft";
    }
    if (el.btnFooterAddMined) el.btnFooterAddMined.classList.remove("hidden");
    updateAddMinedLabel(card);
    if (el.btnFooterCancelDraft) el.btnFooterCancelDraft.classList.remove("hidden");
    if (el.btnFooterUnsuspend) el.btnFooterUnsuspend.classList.add("hidden");
    if (el.btnFooterSkip) el.btnFooterSkip.classList.add("hidden");
    if (el.btnFooterDeleteCard) el.btnFooterDeleteCard.classList.add("hidden");
  } else {
    el.deckBadge.textContent = isGrammarCard(card)
      ? card.deckName.split("::").slice(-2).join(" › ")
      : card.deckName.split("::").pop();
    const hasLeechTag = Boolean(card.isLeech || (card.tags && card.tags.some(t => t.toLowerCase() === "leech")));
    const isAiReviewed = Boolean(card.tags && card.tags.some(t => t.toLowerCase() === "ai-mnemonic-reviewed"));

    if (card.suspended && hasLeechTag) {
      el.statusBadge.textContent = "🔴 Suspended Leech";
      el.statusBadge.className = "badge badge-danger";
    } else if (card.suspended) {
      el.statusBadge.textContent = "⏸️ Suspended";
      el.statusBadge.className = "badge badge-suspended";
    } else if (hasLeechTag) {
      el.statusBadge.textContent = "⚡ Active Leech";
      el.statusBadge.className = "badge badge-leech";
    } else if (!isAiReviewed) {
      el.statusBadge.textContent = "⏳ Not Reviewed";
      el.statusBadge.className = "badge badge-warning";
    } else {
      el.statusBadge.textContent = "Active Card";
      el.statusBadge.className = "badge badge-info";
    }

    if (el.btnFooterAddMined) el.btnFooterAddMined.classList.add("hidden");
    if (el.btnFooterCancelDraft) el.btnFooterCancelDraft.classList.add("hidden");
    if (el.btnFooterUnsuspend) el.btnFooterUnsuspend.classList.remove("hidden");
    if (el.btnFooterSkip) el.btnFooterSkip.classList.remove("hidden");
    if (el.btnFooterDeleteCard) el.btnFooterDeleteCard.classList.remove("hidden");
  }

  // Vocab Display & Editor
  el.vocabKanji.textContent = card.vocabKanji;
  el.vocabFurigana.textContent = card.vocabFurigana || "";
  if (card.vocabDef && card.vocabDef.includes("<") && card.vocabDef.includes(">")) {
    el.vocabDef.innerHTML = card.vocabDef;
  } else {
    el.vocabDef.textContent = card.vocabDef || "No definition available";
  }
  if (el.editVocabKanji) el.editVocabKanji.value = card.vocabKanji || "";
  if (el.editVocabFurigana) el.editVocabFurigana.value = card.vocabFurigana || "";
  if (el.editVocabDef) el.editVocabDef.value = card.vocabDef || "";
  if (el.vocabEditor) el.vocabEditor.classList.add("hidden");
  if (el.btnToggleVocabEdit) el.btnToggleVocabEdit.textContent = "✏️ Edit Vocab";

  // Sentence Display
  if (card.sentFurigana || card.sentKanji) {
    el.sentenceRuby.innerHTML = parseFuriganaRuby(card.sentFurigana || card.sentKanji);
    el.sentenceEng.textContent = card.sentEng || "";
  } else {
    el.sentenceRuby.innerHTML = `
      <div class="no-sentence-box">
        <span>💡</span> <span>No sentence yet. Switch to the <strong>🏍️ Persona Sentences</strong> tab & click <strong>"Generate Sentence"</strong> to create a personalized example!</span>
      </div>
    `;
    el.sentenceEng.textContent = "";
  }

  // Populate inline editors
  el.editSentKanji.value = card.sentKanji || "";
  el.editSentFurigana.value = card.sentFurigana || "";
  el.editSentEng.value = card.sentEng || "";

  // Notes Preview & Editor
  if (card.notes) {
    el.cardNotesPreview.innerHTML = formatNotesHtml(card.notes);
  } else {
    el.cardNotesPreview.textContent = "No notes on this card yet.";
  }
  if (el.editCardNotes) el.editCardNotes.value = card.notes || "";
  if (el.notesWysiwygEditor) el.notesWysiwygEditor.innerHTML = card.notes || "";
  if (el.notesEditor) el.notesEditor.classList.add("hidden");
  if (el.btnToggleNotesEdit) el.btnToggleNotesEdit.textContent = "✏️ Edit Notes";

  applyCardTypeTabs(card);

  // Reset current generation outputs and custom hints
  state.currentGeneratedMnemonic = "";
  state.currentGeneratedSentence = null;
  el.mnemonicActions.style.display = "none";
  el.sentenceActions.style.display = "none";
  if (el.mnemonicCustomInstruction) el.mnemonicCustomInstruction.value = "";
  if (el.sentenceCustomTopic) el.sentenceCustomTopic.value = "";
  if (el.mnemonicEditorWrap) el.mnemonicEditorWrap.classList.add("hidden");
  if (el.mnemonicOutput) el.mnemonicOutput.classList.remove("hidden");
  if (el.btnCancelEditMnemonic) el.btnCancelEditMnemonic.classList.add("hidden");
  if (el.btnEditMnemonic) el.btnEditMnemonic.innerHTML = "✏️ Edit Before Saving";

  el.mnemonicOutput.innerHTML = `
    <div class="empty-state">
      <div class="empty-icon">🧠</div>
      <p>Click <strong>"Generate Mnemonic"</strong> to create a tailored memory anchor for <strong>${card.vocabKanji}</strong>.</p>
    </div>
  `;

  if (card.personaSentence && (card.sentKanji || "").trim()) {
    // Sentence was already written by the persona generator while mining
    el.sentenceOutput.innerHTML = sentenceResultHtml({ ...card.personaSentence, sentKanji: card.sentKanji, sentFurigana: card.sentFurigana, sentEng: card.sentEng }, { applied: true });
  } else {
    el.sentenceOutput.innerHTML = `
    <div class="empty-state">
      <div class="empty-icon">📝</div>
      <p>Click <strong>"Generate Sentence"</strong> to create a personalized Japanese sentence tailored to your interests.</p>
    </div>
  `;
  }

  // Restore or reset chat
  renderChatHistory();

  // Fetch and render constituent kanji cards
  await loadConstituentKanji(card);
}

function renderKanjiGrid(kanjiList, kanjiDetails) {
  el.kanjiCardsContainer.innerHTML = "";
  kanjiList.forEach(k => {
    const info = (kanjiDetails && kanjiDetails[k]) ? kanjiDetails[k] : null;
    const isFound = Boolean(info && info.found && info.keyword && info.keyword !== "Unknown" && info.keyword !== "Error");

    const keywordLabel = isFound ? info.keyword : "AI On-The-Fly";
    const badgeClass = isFound ? "kanji-keyword-badge" : "kanji-keyword-badge kanji-keyword-badge-missing";
    const storyLabel = isFound 
      ? (info.myStory ? "★ Your Custom Story" : "Heisig/Koohii Story") 
      : "✨ AI Dynamic Synthesis";
    const storyText = isFound
      ? (info.myStory || info.koohiiStory1 || info.heisigStory || "No custom story recorded in deck.")
      : "Kanji story not in deck. AI will decompose its constituent radicals and synthesize a memorable mnemonic on the fly!";

    const cardDiv = document.createElement("div");
    cardDiv.className = "kanji-card";
    cardDiv.innerHTML = `
      <div class="kanji-card-header">
        <div class="kanji-glyph">${k}</div>
        <div>
          <div class="${badgeClass}">${keywordLabel}</div>
          <div class="kanji-readings">
            ${isFound && info.onYomi ? `On: ${info.onYomi}` : ""} ${isFound && info.kunYomi ? `| Kun: ${info.kunYomi}` : ""}
          </div>
        </div>
      </div>
      <div class="kanji-story-box">
        <div class="story-label">${storyLabel}</div>
        <p>${storyText}</p>
      </div>
    `;
    el.kanjiCardsContainer.appendChild(cardDiv);
  });
}

function renderCollisionRadar(matches) {
  if (!el.deckCollisionRadar || !el.radarCardsList) return;
  
  const collisionMatches = (matches || []).filter(m => m.hasCollision || m.combinedScore > 0.45);
  state.allCollisionMatches = collisionMatches;

  const exacts = collisionMatches.filter(m => m.isExactDuplicate);

  // Toggle footer delete duplicate button (targets THIS card in question)
  if (el.btnFooterDeleteDuplicate) {
    if (exacts.length > 0 && state.currentCard) {
      el.btnFooterDeleteDuplicate.classList.remove("hidden");
      el.btnFooterDeleteDuplicate.innerHTML = `🗑️ Delete THIS Card (${state.currentCard.vocabKanji})`;
      el.btnFooterDeleteDuplicate.onclick = (e) => {
        e.preventDefault();
        openDeleteConfirmModal(state.currentCard, exacts[0]);
      };
    } else {
      el.btnFooterDeleteDuplicate.classList.add("hidden");
    }
  }

  if (collisionMatches.length === 0) {
    el.deckCollisionRadar.classList.add("hidden");
    el.radarCardsList.innerHTML = "";
    state.selectedContrastCardIds = new Set();
    state.currentConfusableCards = [];
    return;
  }

  el.deckCollisionRadar.classList.remove("hidden");
  if (state.radarCollapsed) {
    el.deckCollisionRadar.classList.add("collapsed");
  } else {
    el.deckCollisionRadar.classList.remove("collapsed");
  }
  
  if (el.collisionCountBadge) {
    if (exacts.length > 0) {
      el.collisionCountBadge.className = "badge badge-danger";
      el.collisionCountBadge.textContent = `⚠️ ${exacts.length} Exact Match${exacts.length > 1 ? "es" : ""}`;
    } else {
      el.collisionCountBadge.className = "badge badge-warning";
      el.collisionCountBadge.textContent = `${collisionMatches.length} Confusable Match${collisionMatches.length > 1 ? "es" : ""}`;
    }
  }

  // Initialize selection: default to all exact duplicates or the top 1 match
  state.selectedContrastCardIds = new Set();
  if (exacts.length > 0) {
    exacts.forEach(m => state.selectedContrastCardIds.add(m.cardId));
  } else if (collisionMatches.length > 0) {
    state.selectedContrastCardIds.add(collisionMatches[0].cardId);
  }

  updateContrastSelectionHeader();

  el.radarCardsList.innerHTML = "";

  // If there are exact duplicate matches, prepend a prominent alert banner
  if (exacts.length > 0) {
    const banner = document.createElement("div");
    banner.className = "exact-match-alert-banner";
    const exactDeck = exacts[0].deckName ? exacts[0].deckName.split("::").pop() : "Deck";
    const currentVocab = state.currentCard ? state.currentCard.vocabKanji : exacts[0].vocabKanji;
    banner.innerHTML = `
      <div class="exact-match-banner-info">
        <span class="exact-match-banner-icon">⚠️</span>
        <div>
          <strong>Exact Match Duplicate Found:</strong> "<span>${exacts[0].vocabKanji}</span>" already exists in <em>${escapeHtml(exactDeck)}</em>.
        </div>
      </div>
      <div style="display: flex; align-items: center; gap: 0.5rem; flex-wrap: wrap;">
        <button type="button" class="btn-delete-radar-card" id="btn-banner-delete-this" style="background: rgba(244, 63, 94, 0.28); color: #fff; border-color: #f43f5e;" title="Permanently delete THIS active card from Anki">
          🗑️ Delete THIS Card (${currentVocab})
        </button>
        <button type="button" class="btn-delete-radar-card" id="btn-banner-delete-other" style="font-size: 0.7rem;" title="Delete the other duplicate card from ${exactDeck}">
          🗑️ Delete from ${exactDeck}
        </button>
      </div>
    `;
    const btnDelThis = banner.querySelector("#btn-banner-delete-this");
    if (btnDelThis) {
      btnDelThis.addEventListener("click", (e) => {
        e.stopPropagation();
        openDeleteConfirmModal(state.currentCard, exacts[0]);
      });
    }
    const btnDelOther = banner.querySelector("#btn-banner-delete-other");
    if (btnDelOther) {
      btnDelOther.addEventListener("click", (e) => {
        e.stopPropagation();
        openDeleteConfirmModal(exacts[0], state.currentCard);
      });
    }
    el.radarCardsList.appendChild(banner);
  }

  collisionMatches.forEach(m => {
    const isSelected = state.selectedContrastCardIds.has(m.cardId);
    const item = document.createElement("div");
    let borderClass = "collision-semantic";
    if (m.isExactDuplicate) borderClass = "collision-exact";
    else if (m.isKanjiInversion) borderClass = "collision-inversion";
    else if (m.hasSharedKanji) borderClass = "collision-shared";
    else if (m.isVisualConfuser) borderClass = "collision-visual";
    else if (m.isPhoneticConfuser) borderClass = "collision-phonetic";

    item.className = `radar-card-item ${borderClass} ${isSelected ? "radar-card-selected" : ""}`;

    let badgesHtml = "";
    if (m.isExactDuplicate) {
      badgesHtml += `<span class="badge-sim badge-sim-exact">⚠️ Exact Match</span>`;
    }
    if (m.isKanjiInversion) {
      badgesHtml += `<span class="badge-sim badge-sim-inversion">🔄 Kanji Reversal</span>`;
    }
    if (m.isSpatialInversion) {
      badgesHtml += `<span class="badge-sim badge-sim-inversion" style="background: rgba(236, 72, 153, 0.15); color: #f472b6; border-color: rgba(236, 72, 153, 0.35);">🔀 Component Inversion</span>`;
    }
    if (m.hasSharedKanji && m.sharedKanji && m.sharedKanji.length > 0) {
      badgesHtml += `<span class="badge-sim badge-sim-shared">🀄 Shares ${m.sharedKanji.join(", ")}</span>`;
    }
    if (m.semanticScore > 0.45) {
      badgesHtml += `<span class="badge-sim badge-sim-semantic">📚 ${Math.round(m.semanticScore * 100)}% Meaning</span>`;
    }
    if (m.visualScore > 0.45) {
      badgesHtml += `<span class="badge-sim badge-sim-visual">👁️ ${Math.round(m.visualScore * 100)}% Visual</span>`;
    }
    if (m.phoneticScore > 0.45) {
      badgesHtml += `<span class="badge-sim badge-sim-phonetic">🔊 ${Math.round(m.phoneticScore * 100)}% Sound</span>`;
    }

    const reasonsText = (m.collisionReasons && m.collisionReasons.length > 0)
      ? m.collisionReasons.join(" • ")
      : `High similarity overlap with ${m.deckName.split("::").pop()}`;

    let deleteBtnHtml = "";
    if (m.isExactDuplicate) {
      deleteBtnHtml = `
        <button type="button" class="btn-delete-radar-card" data-card-id="${m.cardId}" title="Permanently delete this duplicate card from Anki">
          🗑️ Delete Duplicate
        </button>
      `;
    }

    item.innerHTML = `
      <div class="radar-match-header">
        <div style="display: flex; align-items: center; gap: 0.6rem;">
          <input type="checkbox" class="radar-contrast-checkbox" data-card-id="${m.cardId}" ${isSelected ? "checked" : ""} title="Toggle inclusion in mnemonic contrast">
          <div class="radar-vocab-text" style="user-select: text; -webkit-user-select: text;">
            <span class="radar-kanji">${m.vocabKanji}</span>
            <span class="radar-furigana">${m.vocabFurigana || ""}</span>
          </div>
        </div>
        <span class="radar-def" style="user-select: text; -webkit-user-select: text;">${m.vocabDef || ""}</span>
      </div>
      <div class="radar-badges-row">
        ${badgesHtml}
      </div>
      <div class="radar-reasons" style="user-select: text; -webkit-user-select: text;">${reasonsText}</div>
      <div class="radar-footer-row">
        <span style="font-size: 0.7rem; color: var(--text-subtle);">${m.deckName ? m.deckName.split("::").pop() : ""}</span>
        <div style="display: flex; align-items: center; gap: 0.5rem;">
          ${deleteBtnHtml}
          <button type="button" class="btn-contrast-action ${isSelected ? 'btn-contrast-active' : ''}" data-card-kanji="${m.vocabKanji}">
            ${isSelected ? '✓ Contrasted in Mnemonic' : '🔍 Contrast in Mnemonic'}
          </button>
        </div>
      </div>
    `;

    const cb = item.querySelector(".radar-contrast-checkbox");
    const contrastBtn = item.querySelector(".btn-contrast-action");
    const deleteBtn = item.querySelector(".btn-delete-radar-card");

    if (deleteBtn) {
      deleteBtn.addEventListener("click", (e) => {
        e.stopPropagation();
        openDeleteConfirmModal(m);
      });
    }

    const toggleSelection = () => {
      if (state.selectedContrastCardIds.has(m.cardId)) {
        state.selectedContrastCardIds.delete(m.cardId);
        item.classList.remove("radar-card-selected");
        if (cb) cb.checked = false;
        if (contrastBtn) {
          contrastBtn.classList.remove("btn-contrast-active");
          contrastBtn.textContent = "🔍 Contrast in Mnemonic";
        }
      } else {
        state.selectedContrastCardIds.add(m.cardId);
        item.classList.add("radar-card-selected");
        if (cb) cb.checked = true;
        if (contrastBtn) {
          contrastBtn.classList.add("btn-contrast-active");
          contrastBtn.textContent = "✓ Contrasted in Mnemonic";
        }
      }
      updateContrastSelectionHeader();
    };

    if (cb) {
      cb.addEventListener("change", (e) => {
        e.stopPropagation();
        toggleSelection();
      });
    }

    if (contrastBtn) {
      contrastBtn.addEventListener("click", (e) => {
        e.stopPropagation();
        if (!state.selectedContrastCardIds.has(m.cardId)) {
          toggleSelection();
        }
        const mnemonicTab = document.querySelector('.ai-tab[data-tab="tab-mnemonic"]');
        if (mnemonicTab) mnemonicTab.click();
        generateMnemonic();
      });
    }

    el.radarCardsList.appendChild(item);
  });
}

function updateContrastSelectionHeader() {
  const matches = state.allCollisionMatches || [];
  const selectedCards = matches.filter(m => state.selectedContrastCardIds && state.selectedContrastCardIds.has(m.cardId));
  state.currentConfusableCards = selectedCards;

  if (el.collisionCountBadge) {
    const total = matches.length;
    const selectedCount = selectedCards.length;
    if (selectedCount > 0) {
      el.collisionCountBadge.innerHTML = `${total} Match${total > 1 ? 'es' : ''} • <strong style="color: #6ee7b7;">${selectedCount} Selected to Contrast</strong>`;
    } else {
      el.collisionCountBadge.textContent = `${total} Confusable Match${total > 1 ? 'es' : ''}`;
    }
  }
}

function generateMnemonicWithContrast(targetCard) {
  state.selectedContrastCardIds = new Set([targetCard.cardId]);
  updateContrastSelectionHeader();
  if (el.mnemonicCustomInstruction) {
    el.mnemonicCustomInstruction.value = `Explicitly contrast this word with ${targetCard.vocabKanji} (${targetCard.vocabDef || ""})`;
  }
  // Switch to Mnemonic tab if not active
  const mnemonicTab = document.querySelector('.ai-tab[data-tab="tab-mnemonic"]');
  if (mnemonicTab) mnemonicTab.click();
  generateMnemonic();
}

async function loadConstituentKanji(card) {
  const kanjiList = card.kanjiChars || [];
  el.kanjiCountBadge.textContent = `${kanjiList.length} Kanji`;
  el.kanjiCardsContainer.innerHTML = '<div style="color: var(--text-muted); font-size: 0.85rem;">Fetching kanji stories...</div>';

  if (card.collisionMatches && card.collisionMatches.length > 0) {
    renderCollisionRadar(card.collisionMatches);
  } else {
    renderCollisionRadar([]);
  }

  if (isGrammarCard(card)) {
    el.kanjiCountBadge.textContent = "Grammar";
    el.kanjiCardsContainer.innerHTML = '<div style="color: var(--text-muted); font-size: 0.85rem;">📘 Grammar point: no kanji breakdown. Formation and nuance are in the card notes.</div>';
    return;
  }

  if (kanjiList.length === 0) {
    el.kanjiCardsContainer.innerHTML = '<div style="color: var(--text-muted); font-size: 0.85rem;">Kana-only vocabulary word (no constituent kanji).</div>';
    return;
  }

  if (card.kanjiDetails && Object.keys(card.kanjiDetails).length > 0) {
    state.kanjiDetailsCache[card.cardId] = card.kanjiDetails;
    renderKanjiGrid(kanjiList, card.kanjiDetails);
    return;
  }

  if (state.kanjiDetailsCache[card.cardId]) {
    renderKanjiGrid(kanjiList, state.kanjiDetailsCache[card.cardId]);
    return;
  }

  try {
    const deckQuery = state.kanjiDeckName ? `&deck=${encodeURIComponent(state.kanjiDeckName)}` : "";
    const vocabQuery = `&vocab_kanji=${encodeURIComponent(card.vocabKanji)}&vocab_furigana=${encodeURIComponent(card.vocabFurigana || '')}&vocab_def=${encodeURIComponent(card.vocabDef || '')}`;
    const res = await fetch(`/api/card/${card.cardId}/details?kanji=${encodeURIComponent(kanjiList.join(","))}${deckQuery}${vocabQuery}`);
    const data = await res.json();
    const kanjiDetails = data.kanjiDetails || {};
    state.kanjiDetailsCache[card.cardId] = kanjiDetails;
    renderKanjiGrid(kanjiList, kanjiDetails);

    if (data.confusableCards && data.confusableCards.length > 0) {
      renderCollisionRadar(data.confusableCards);
    }
  } catch (err) {
    console.error("Error fetching kanji details:", err);
    el.kanjiCardsContainer.innerHTML = '<div style="color: var(--accent-rose); font-size: 0.85rem;">Failed to load constituent kanji stories.</div>';
  }
}

// AI Mnemonic Generation
async function generateMnemonic() {
  if (!state.currentCard) return;
  const card = state.currentCard;

  el.btnGenMnemonic.disabled = true;
  el.btnGenMnemonic.innerHTML = '<span class="sparkle-icon">⏳</span> Synthesizing...';
  el.mnemonicOutput.innerHTML = '<div class="empty-state"><p>Analyzing radicals and synthesizing mnemonic...</p></div>';
  if (el.mnemonicEditorWrap) el.mnemonicEditorWrap.classList.add("hidden");
  if (el.mnemonicOutput) el.mnemonicOutput.classList.remove("hidden");

  try {
    const kanjiDetails = state.kanjiDetailsCache[card.cardId] || {};
    const payload = {
      vocabKanji: card.vocabKanji,
      vocabFurigana: card.vocabFurigana,
      vocabDef: card.vocabDef,
      kanjiDetails: kanjiDetails,
      notes: card.notes,
      customInstructions: el.mnemonicCustomInstruction.value.trim(),
      mnemonicStyle: state.mnemonicStyle,
      confusableCards: state.currentConfusableCards,
      cardType: getCardType(card)
    };

    const res = await fetch("/api/generate-mnemonic", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload)
    });

    if (!res.ok) {
      const err = await res.json();
      throw new Error(err.detail || "Failed to generate mnemonic");
    }

    const data = await res.json();
    state.currentGeneratedMnemonic = data.mnemonic;
    if (el.editMnemonicTextarea) el.editMnemonicTextarea.value = data.mnemonic;

    if (window.marked) {
      el.mnemonicOutput.innerHTML = renderMarkdown(data.mnemonic);
    } else {
      el.mnemonicOutput.textContent = data.mnemonic;
    }

    if (el.mnemonicEditorWrap) el.mnemonicEditorWrap.classList.add("hidden");
    if (el.mnemonicOutput) el.mnemonicOutput.classList.remove("hidden");
    if (el.btnCancelEditMnemonic) el.btnCancelEditMnemonic.classList.add("hidden");
    if (el.btnEditMnemonic) el.btnEditMnemonic.innerHTML = "✏️ Edit Before Saving";

    el.mnemonicActions.style.display = "flex";
    showToast("Mnemonic synthesized successfully!", "success");
  } catch (err) {
    console.error(err);
    el.mnemonicOutput.innerHTML = `<div style="color: var(--accent-rose); padding: 1rem;"><strong>Error:</strong> ${escapeHtml(err.message)}</div>`;
    showToast(err.message, "error");
  } finally {
    el.btnGenMnemonic.disabled = false;
    el.btnGenMnemonic.innerHTML = '<span class="sparkle-icon">✨</span> Generate Mnemonic';
  }
}

// Toggle & Cancel Mnemonic Editor
function toggleMnemonicEdit() {
  if (!el.mnemonicEditorWrap) return;
  const isEditing = !el.mnemonicEditorWrap.classList.contains("hidden");
  if (isEditing) {
    // Commit edits
    state.currentGeneratedMnemonic = el.editMnemonicTextarea.value.trim();
    if (window.marked) {
      el.mnemonicOutput.innerHTML = renderMarkdown(state.currentGeneratedMnemonic);
    } else {
      el.mnemonicOutput.textContent = state.currentGeneratedMnemonic;
    }
    el.mnemonicEditorWrap.classList.add("hidden");
    el.mnemonicOutput.classList.remove("hidden");
    el.btnCancelEditMnemonic.classList.add("hidden");
    el.btnEditMnemonic.innerHTML = "✏️ Edit Before Saving";
    showToast("Mnemonic text updated!", "success");
  } else {
    // Open editor
    el.editMnemonicTextarea.value = state.currentGeneratedMnemonic;
    el.mnemonicOutput.classList.add("hidden");
    el.mnemonicEditorWrap.classList.remove("hidden");
    el.btnCancelEditMnemonic.classList.remove("hidden");
    el.btnEditMnemonic.innerHTML = "✓ Done Editing";
    setTimeout(() => el.editMnemonicTextarea.focus(), 50);
  }
}

function cancelMnemonicEdit() {
  if (!el.mnemonicEditorWrap) return;
  el.mnemonicEditorWrap.classList.add("hidden");
  el.mnemonicOutput.classList.remove("hidden");
  el.btnCancelEditMnemonic.classList.add("hidden");
  el.btnEditMnemonic.innerHTML = "✏️ Edit Before Saving";
}

// Save Mnemonic to Anki Notes
async function saveMnemonicToAnki() {
  if (!state.currentCard) return;

  // If currently in edit mode, sync from textarea first
  if (el.mnemonicEditorWrap && !el.mnemonicEditorWrap.classList.contains("hidden")) {
    state.currentGeneratedMnemonic = el.editMnemonicTextarea.value.trim();
    cancelMnemonicEdit();
  }

  if (!state.currentGeneratedMnemonic) return;
  const card = state.currentCard;

  const combinedNotes = (card.notes ? card.notes + "\n\n---\n\n" : "") + state.currentGeneratedMnemonic;

  if (card.isDraft) {
    const mnemonicHtml = formatNotesHtml(state.currentGeneratedMnemonic);
    card.notes = card.notes ? `${formatNotesHtml(card.notes)}<hr>${mnemonicHtml}` : mnemonicHtml;
    el.cardNotesPreview.innerHTML = card.notes;
    if (el.editCardNotes) el.editCardNotes.value = card.notes;
    if (el.notesWysiwygEditor) el.notesWysiwygEditor.innerHTML = card.notes;
    showToast("Mnemonic attached to draft notes!", "success");
    return;
  }

  try {
    const res = await fetch("/api/sync/save-notes", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        noteId: card.noteId,
        notes: combinedNotes
      })
    });

    if (!res.ok) throw new Error("Failed to update notes in Anki");

    const data = await res.json();
    const formattedNotes = data.notes || combinedNotes;
    card.notes = formattedNotes;
    el.cardNotesPreview.innerHTML = formattedNotes;
    if (el.editCardNotes) el.editCardNotes.value = formattedNotes;
    state.cardMnemonicChanged = true;
    if (hasBothMnemonicAndSentenceChanged()) {
      resetUnsuspendButton();
      closeUnsuspendConfirmModal();
    }
    showToast("Mnemonic successfully saved to Anki Notes!", "success");
  } catch (err) {
    console.error(err);
    showToast("Failed to save to Anki notes.", "error");
  }
}

// Persona Management Functions
function initPersonas() {
  const savedAll = localStorage.getItem("anki_leech_all_personas");
  const savedActive = localStorage.getItem("anki_leech_active_personas");
  
  if (savedAll) {
    try { state.allPersonas = JSON.parse(savedAll); } catch (e) {}
  }
  if (savedActive) {
    try { state.activePersonas = JSON.parse(savedActive); } catch (e) {}
  }
  renderPersonaChips();

  // Restore collapsed state (defaults to false or saved preference)
  const isCollapsed = localStorage.getItem("anki_persona_pool_collapsed") === "true";
  setPersonaPoolCollapsed(isCollapsed);
}

function setPersonaPoolCollapsed(collapsed) {
  state.personaPoolCollapsed = collapsed;
  if (!el.personaPoolSection) return;

  if (collapsed) {
    el.personaPoolSection.classList.add("collapsed");
    if (el.personaCollapseChevron) el.personaCollapseChevron.textContent = "▶";
    if (el.personaCollapsedSummary) el.personaCollapsedSummary.classList.remove("hidden");
    if (el.btnTogglePersonaPool) el.btnTogglePersonaPool.setAttribute("title", "Expand Persona Pool");
  } else {
    el.personaPoolSection.classList.remove("collapsed");
    if (el.personaCollapseChevron) el.personaCollapseChevron.textContent = "▼";
    if (el.personaCollapsedSummary) el.personaCollapsedSummary.classList.add("hidden");
    if (el.btnTogglePersonaPool) el.btnTogglePersonaPool.setAttribute("title", "Collapse Persona Pool");
  }
  localStorage.setItem("anki_persona_pool_collapsed", collapsed ? "true" : "false");
}

function togglePersonaPoolCollapse() {
  setPersonaPoolCollapsed(!state.personaPoolCollapsed);
}

function renderPersonaChips() {
  if (!el.personaChipsContainer) return;
  el.personaChipsContainer.innerHTML = "";
  state.allPersonas.forEach(p => {
    const isActive = state.activePersonas.includes(p);
    const chip = document.createElement("button");
    chip.className = `topic-chip ${isActive ? "active" : ""}`;
    chip.textContent = p;
    chip.addEventListener("click", () => togglePersona(p));
    el.personaChipsContainer.appendChild(chip);
  });
  
  if (el.activePersonaCount) {
    el.activePersonaCount.textContent = state.activePersonas.length;
  }

  // Update collapsed summary indicator
  if (el.personaCollapsedSummary) {
    const count = state.activePersonas.length;
    const summaryNames = state.activePersonas.slice(0, 3).map(p => p.split(",")[0].trim()).join(", ");
    const more = count > 3 ? ` +${count - 3} more` : "";
    el.personaCollapsedSummary.innerHTML = `<span class="badge-count">${count} active</span> <span class="summary-text">${escapeHtml(summaryNames)}${more}</span>`;
  }
  
  localStorage.setItem("anki_leech_all_personas", JSON.stringify(state.allPersonas));
  localStorage.setItem("anki_leech_active_personas", JSON.stringify(state.activePersonas));
}

function togglePersona(persona) {
  if (state.activePersonas.includes(persona)) {
    if (state.activePersonas.length <= 1) {
      showToast("Keep at least one persona active for generation.", "info");
      return;
    }
    state.activePersonas = state.activePersonas.filter(p => p !== persona);
  } else {
    state.activePersonas.push(persona);
  }
  renderPersonaChips();
}

function selectAllPersonas() {
  state.activePersonas = [...state.allPersonas];
  renderPersonaChips();
}

function resetPersonas() {
  state.activePersonas = state.allPersonas.slice(0, 4);
  renderPersonaChips();
}

function addCustomPersona() {
  const val = el.newPersonaInput.value.trim();
  if (!val) return;
  if (!state.allPersonas.includes(val)) {
    state.allPersonas.push(val);
  }
  if (!state.activePersonas.includes(val)) {
    state.activePersonas.push(val);
  }
  el.newPersonaInput.value = "";
  renderPersonaChips();
  showToast(`Added persona: "${val}"`, "success");
}

// AI Sentence Generation
async function generatePersonalizedSentence() {
  if (!state.currentCard) return;
  const card = state.currentCard;

  if (state.activePersonas.length === 0) {
    showToast("Please select at least one persona tag.", "warning");
    return;
  }

  el.btnGenSentence.disabled = true;
  el.btnGenSentence.innerHTML = '<span class="sparkle-icon">⏳</span> Writing...';
  el.sentenceOutput.innerHTML = '<div class="empty-state"><p>Evaluating vocabulary context and picking the best persona story...</p></div>';

  try {
    const customTopic = el.sentenceCustomTopic.value.trim();
    const payload = {
      vocabKanji: card.vocabKanji,
      vocabFurigana: card.vocabFurigana,
      vocabDef: card.vocabDef,
      currentSentence: card.sentKanji,
      personas: state.activePersonas,
      customTopic: customTopic,
      jlptLevel: isGrammarCard(card) ? getCardJlptLevel(card) : state.jlptLevel,
      cardType: getCardType(card)
    };

    const res = await fetch("/api/generate-sentence", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload)
    });

    if (!res.ok) {
      const err = await res.json();
      throw new Error(err.detail || "Failed to generate sentence");
    }

    const data = await res.json();
    state.currentGeneratedSentence = data;
    el.sentenceOutput.innerHTML = sentenceResultHtml(data);

    el.sentenceActions.style.display = "flex";
    showToast(`Generated via ${data.themeUsed || "Persona"}!`, "success");
  } catch (err) {
    console.error(err);
    el.sentenceOutput.innerHTML = `<div style="color: var(--accent-rose); padding: 1rem;"><strong>Error:</strong> ${escapeHtml(err.message)}</div>`;
    showToast(err.message, "error");
  } finally {
    el.btnGenSentence.disabled = false;
    el.btnGenSentence.innerHTML = '<span class="sparkle-icon">🏍️</span> Generate Sentence';
  }
}

function sentenceResultHtml(data, { applied = false } = {}) {
  return `
      <div style="background: rgba(30, 41, 59, 0.8); padding: 1.25rem; border-radius: var(--radius-md); border: 1px solid var(--border-focus);">
        <div style="display: flex; justify-content: space-between; align-items: center; gap: 0.5rem; flex-wrap: wrap; margin-bottom: 0.75rem;">
          <div class="theme-picked-badge">🎯 Theme Chosen: ${data.themeUsed || "Personalized Story"}</div>
          ${applied ? '<div class="sentence-applied-badge">✓ Generated while mining · already on card</div>' : ""}
        </div>
        <div style="font-family: var(--font-japanese); font-size: 1.35rem; line-height: 1.8; color: #ffffff; margin-bottom: 0.5rem;">
          ${parseFuriganaRuby(data.sentFurigana || data.sentKanji || "")}
        </div>
        <div style="font-size: 1rem; color: #cbd5e1; font-style: italic; margin-bottom: 0.75rem;">
          ${data.sentEng || ""}
        </div>
        ${data.rationale ? `<div class="rationale-box">💡 <em>${data.rationale}</em></div>` : ""}
        ${applied ? '<div class="form-help" style="margin-top: 0.75rem;">Click <strong>"Generate Sentence"</strong> only if you want a different one.</div>' : ""}
      </div>
    `;
}

// Apply Generated Sentence to Anki
async function applySentenceToAnki() {
  if (!state.currentCard || !state.currentGeneratedSentence) return;
  const card = state.currentCard;
  const sent = state.currentGeneratedSentence;

  if (card.isDraft) {
    card.sentKanji = sent.sentKanji;
    card.sentFurigana = sent.sentFurigana;
    card.sentEng = sent.sentEng;
    card.personaSentence = { themeUsed: sent.themeUsed || "", rationale: sent.rationale || "" };
    card.sentenceSource = "persona";
    state.cardSentenceChanged = true;

    el.sentenceRuby.innerHTML = parseFuriganaRuby(sent.sentFurigana);
    el.sentenceEng.textContent = sent.sentEng;
    el.editSentKanji.value = sent.sentKanji;
    el.editSentFurigana.value = sent.sentFurigana;
    el.editSentEng.value = sent.sentEng;

    showToast("Sentence applied to draft card!", "success");
    return;
  }

  try {
    const res = await fetch("/api/sync/save-sentence", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        noteId: card.noteId,
        sentKanji: sent.sentKanji,
        sentFurigana: sent.sentFurigana,
        sentEng: sent.sentEng
      })
    });

    if (!res.ok) throw new Error("Failed to update sentence in Anki");

    card.sentKanji = sent.sentKanji;
    card.sentFurigana = sent.sentFurigana;
    card.sentEng = sent.sentEng;

    el.sentenceRuby.innerHTML = parseFuriganaRuby(sent.sentFurigana);
    el.sentenceEng.textContent = sent.sentEng;
    el.editSentKanji.value = sent.sentKanji;
    el.editSentFurigana.value = sent.sentFurigana;
    el.editSentEng.value = sent.sentEng;

    state.cardSentenceChanged = true;
    if (hasBothMnemonicAndSentenceChanged()) {
      resetUnsuspendButton();
      closeUnsuspendConfirmModal();
    }

    showToast("New example sentence applied to Anki card!", "success");
  } catch (err) {
    console.error("Error applying sentence:", err);
    showToast("Failed to save sentence to Anki.", "error");
  }
}

// Inline Sentence Editing Functions
function toggleSentenceEdit() {
  if (!el.sentenceEditor) return;
  const isHidden = el.sentenceEditor.classList.contains("hidden");
  if (isHidden) {
    if (state.currentCard) {
      el.editSentKanji.value = state.currentCard.sentKanji || "";
      el.editSentFurigana.value = state.currentCard.sentFurigana || "";
      el.editSentEng.value = state.currentCard.sentEng || "";
    }
    el.sentenceEditor.classList.remove("hidden");
    el.btnToggleSentenceEdit.textContent = "✕ Close";
  } else {
    el.sentenceEditor.classList.add("hidden");
    el.btnToggleSentenceEdit.textContent = "✏️ Edit";
  }
}

async function saveInlineSentence() {
  if (!state.currentCard) return;
  const card = state.currentCard;

  const newKanji = el.editSentKanji.value.trim();
  const newFuri = el.editSentFurigana.value.trim();
  const newEng = el.editSentEng.value.trim();

  if (card.isDraft) {
    card.sentKanji = newKanji;
    card.sentFurigana = newFuri;
    card.sentEng = newEng;

    el.sentenceRuby.innerHTML = parseFuriganaRuby(newFuri || newKanji);
    el.sentenceEng.textContent = newEng;
    el.sentenceEditor.classList.add("hidden");
    el.btnToggleSentenceEdit.textContent = "✏️ Edit";
    showToast("Draft sentence updated!", "success");
    return;
  }

  try {
    const res = await fetch("/api/sync/save-sentence", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        noteId: card.noteId,
        sentKanji: newKanji,
        sentFurigana: newFuri,
        sentEng: newEng
      })
    });

    if (!res.ok) throw new Error("Failed to update sentence in Anki");

    card.sentKanji = newKanji;
    card.sentFurigana = newFuri;
    card.sentEng = newEng;

    el.sentenceRuby.innerHTML = parseFuriganaRuby(newFuri || newKanji);
    el.sentenceEng.textContent = newEng;
    el.sentenceEditor.classList.add("hidden");
    el.btnToggleSentenceEdit.textContent = "✏️ Edit";

    state.cardSentenceChanged = true;
    if (hasBothMnemonicAndSentenceChanged()) {
      resetUnsuspendButton();
      closeUnsuspendConfirmModal();
    }

    showToast("Sentence saved to Anki!", "success");
  } catch (err) {
    console.error("Error saving sentence:", err);
    showToast("Failed to save sentence to Anki.", "error");
  }
}

// Inline Vocab / Meaning Editing Functions
function toggleVocabEdit() {
  if (!el.vocabEditor) return;
  const isHidden = el.vocabEditor.classList.contains("hidden");
  if (isHidden) {
    if (state.currentCard) {
      if (el.editVocabKanji) el.editVocabKanji.value = state.currentCard.vocabKanji || "";
      if (el.editVocabFurigana) el.editVocabFurigana.value = state.currentCard.vocabFurigana || "";
      if (el.editVocabDef) el.editVocabDef.value = state.currentCard.vocabDef || "";
    }
    el.vocabEditor.classList.remove("hidden");
    if (el.btnToggleVocabEdit) el.btnToggleVocabEdit.textContent = "✕ Close";
    setTimeout(() => el.editVocabDef?.focus(), 50);
  } else {
    el.vocabEditor.classList.add("hidden");
    if (el.btnToggleVocabEdit) el.btnToggleVocabEdit.textContent = "✏️ Edit Vocab";
  }
}

function cancelVocabEdit() {
  if (!el.vocabEditor) return;
  el.vocabEditor.classList.add("hidden");
  if (el.btnToggleVocabEdit) el.btnToggleVocabEdit.textContent = "✏️ Edit Vocab";
}

async function saveInlineVocab() {
  if (!state.currentCard) return;
  const card = state.currentCard;
  const newKanji = el.editVocabKanji ? el.editVocabKanji.value.trim() : card.vocabKanji;
  const newFuri = el.editVocabFurigana ? el.editVocabFurigana.value.trim() : card.vocabFurigana;
  const newDef = el.editVocabDef ? el.editVocabDef.value.trim() : card.vocabDef;

  if (!newDef && !newKanji) {
    showToast("Vocabulary definition cannot be empty.", "warning");
    return;
  }

  if (card.isDraft) {
    card.vocabKanji = newKanji || card.vocabKanji;
    card.vocabFurigana = newFuri || card.vocabFurigana;
    card.vocabDef = newDef;
    el.vocabKanji.textContent = card.vocabKanji;
    el.vocabFurigana.textContent = card.vocabFurigana;
    el.vocabDef.textContent = card.vocabDef || "No definition available";
    el.vocabEditor.classList.add("hidden");
    if (el.btnToggleVocabEdit) el.btnToggleVocabEdit.textContent = "✏️ Edit Vocab";
    showToast("Draft vocabulary updated!", "success");
    return;
  }

  try {
    const res = await fetch("/api/sync/save-vocab", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        noteId: card.noteId,
        vocabKanji: newKanji || card.vocabKanji,
        vocabFurigana: newFuri || card.vocabFurigana,
        vocabDef: newDef
      })
    });

    if (!res.ok) throw new Error("Failed to update vocabulary definition in Anki");

    card.vocabKanji = newKanji || card.vocabKanji;
    card.vocabFurigana = newFuri || card.vocabFurigana;
    card.vocabDef = newDef;

    el.vocabKanji.textContent = card.vocabKanji;
    el.vocabFurigana.textContent = card.vocabFurigana;
    el.vocabDef.textContent = card.vocabDef || "No definition available";

    el.vocabEditor.classList.add("hidden");
    if (el.btnToggleVocabEdit) el.btnToggleVocabEdit.textContent = "✏️ Edit Vocab";
    showToast("Vocabulary definition updated in Anki!", "success");
  } catch (err) {
    console.error("Error saving vocabulary:", err);
    showToast("Failed to save vocabulary definition to Anki.", "error");
  }
}

// Inline Notes Editing Functions (WYSIWYG & HTML Modes)
function setNotesEditorMode(mode) {
  state.notesEditorMode = mode;

  if (mode === "wysiwyg") {
    if (el.btnModeWysiwyg) el.btnModeWysiwyg.classList.add("active");
    if (el.btnModeHtml) el.btnModeHtml.classList.remove("active");

    // Sync raw HTML textarea value into WYSIWYG editor
    if (el.editCardNotes && el.notesWysiwygEditor) {
      el.notesWysiwygEditor.innerHTML = el.editCardNotes.value;
    }

    if (el.notesWysiwygToolbar) el.notesWysiwygToolbar.classList.remove("hidden");
    if (el.notesWysiwygEditor) el.notesWysiwygEditor.classList.remove("hidden");
    if (el.editCardNotes) el.editCardNotes.classList.add("hidden");
  } else {
    if (el.btnModeHtml) el.btnModeHtml.classList.add("active");
    if (el.btnModeWysiwyg) el.btnModeWysiwyg.classList.remove("active");

    // Sync WYSIWYG HTML into raw textarea
    if (el.notesWysiwygEditor && el.editCardNotes) {
      el.editCardNotes.value = el.notesWysiwygEditor.innerHTML;
    }

    if (el.notesWysiwygToolbar) el.notesWysiwygToolbar.classList.add("hidden");
    if (el.notesWysiwygEditor) el.notesWysiwygEditor.classList.add("hidden");
    if (el.editCardNotes) el.editCardNotes.classList.remove("hidden");
  }
}

function toggleNotesEdit() {
  if (!el.notesEditor) return;
  const isHidden = el.notesEditor.classList.contains("hidden");
  if (isHidden) {
    if (window.innerWidth <= 768) {
      setMobileView("notes");
    }
    const rawNotes = (state.currentCard && state.currentCard.notes) ? state.currentCard.notes : "";
    if (el.editCardNotes) el.editCardNotes.value = rawNotes;
    if (el.notesWysiwygEditor) el.notesWysiwygEditor.innerHTML = rawNotes;

    // Default to WYSIWYG mode
    setNotesEditorMode("wysiwyg");

    el.notesEditor.classList.remove("hidden");
    if (el.btnToggleNotesEdit) el.btnToggleNotesEdit.textContent = "✕ Close";
    setTimeout(() => el.notesWysiwygEditor?.focus(), 50);
  } else {
    el.notesEditor.classList.add("hidden");
    if (el.btnToggleNotesEdit) el.btnToggleNotesEdit.textContent = "✏️ Edit Notes";
    if (window.innerWidth <= 768) {
      setMobileView("study");
    }
  }
}

function cancelNotesEdit() {
  if (!el.notesEditor) return;
  el.notesEditor.classList.add("hidden");
  if (el.btnToggleNotesEdit) el.btnToggleNotesEdit.textContent = "✏️ Edit Notes";
  if (window.innerWidth <= 768) {
    setMobileView("study");
  }
}

async function saveInlineNotes() {
  if (!state.currentCard) return;
  const card = state.currentCard;

  // Retrieve current content according to active mode
  let newNotes = "";
  if (state.notesEditorMode === "wysiwyg" && el.notesWysiwygEditor) {
    newNotes = el.notesWysiwygEditor.innerHTML.trim();
  } else if (el.editCardNotes) {
    newNotes = el.editCardNotes.value.trim();
  }

  if (card.isDraft) {
    card.notes = newNotes;
    el.cardNotesPreview.innerHTML = newNotes || "No notes on this card yet.";
    el.notesEditor.classList.add("hidden");
    if (el.btnToggleNotesEdit) el.btnToggleNotesEdit.textContent = "✏️ Edit Notes";
    showToast("Draft card notes updated!", "success");
    return;
  }

  try {
    const res = await fetch("/api/sync/save-notes", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        noteId: card.noteId,
        notes: newNotes
      })
    });

    if (!res.ok) throw new Error("Failed to update notes in Anki");

    const data = await res.json();
    const formattedNotes = data.notes || newNotes;
    card.notes = formattedNotes;
    el.cardNotesPreview.innerHTML = formattedNotes || "No notes on this card yet.";
    if (el.notesWysiwygEditor) el.notesWysiwygEditor.innerHTML = formattedNotes;
    if (el.editCardNotes) el.editCardNotes.value = formattedNotes;
    el.notesEditor.classList.add("hidden");
    if (el.btnToggleNotesEdit) el.btnToggleNotesEdit.textContent = "✏️ Edit Notes";
    if (window.innerWidth <= 768) {
      setMobileView("study");
    }

    state.cardMnemonicChanged = true;
    if (hasBothMnemonicAndSentenceChanged()) {
      resetUnsuspendButton();
      closeUnsuspendConfirmModal();
    }

    showToast("Card notes updated in Anki!", "success");
  } catch (err) {
    console.error("Error saving notes:", err);
    showToast("Failed to save notes to Anki.", "error");
  }
}

// Chat Tutor Functions
function renderChatHistory() {
  if (!state.currentCard) return;
  const cardId = state.currentCard.cardId;
  const history = state.chatHistories[cardId] || [];

  el.chatMessages.innerHTML = `
    <div class="chat-bubble chat-sensei">
      <div class="bubble-author">Sensei AI</div>
      <div class="bubble-text">Konnichiwa! I am ready to review <strong>${state.currentCard.vocabKanji}</strong> (${state.currentCard.vocabFurigana}) with you. Tell me what makes this card slip from memory, or ask any question!</div>
    </div>
  `;

  history.forEach(msg => {
    appendChatBubble(msg.role === "user" ? "user" : "sensei", msg.content);
  });
}

function appendChatBubble(sender, text) {
  const bubble = document.createElement("div");
  bubble.className = `chat-bubble ${sender === "user" ? "chat-user" : "chat-sensei"}`;
  
  let formattedText = text;
  if (sender === "sensei" && window.marked) {
    formattedText = renderMarkdown(text);
  } else {
    formattedText = text.replace(/\n/g, "<br>");
  }

  bubble.innerHTML = `
    <div class="bubble-author">${sender === "user" ? "You" : "Sensei AI"}</div>
    <div class="bubble-text">${formattedText}</div>
  `;
  el.chatMessages.appendChild(bubble);
  el.chatMessages.scrollTop = el.chatMessages.scrollHeight;
}

async function sendChatMessage(customMsg = null) {
  if (!state.currentCard) return;
  const message = customMsg || el.chatInput.value.trim();
  if (!message) return;

  const card = state.currentCard;
  const cardId = card.cardId;

  if (!state.chatHistories[cardId]) {
    state.chatHistories[cardId] = [];
  }

  appendChatBubble("user", message);
  state.chatHistories[cardId].push({ role: "user", content: message });
  if (!customMsg) el.chatInput.value = "";

  const typingId = "typing-" + Date.now();
  const typingBubble = document.createElement("div");
  typingBubble.id = typingId;
  typingBubble.className = "chat-bubble chat-sensei";
  typingBubble.innerHTML = '<div class="bubble-author">Sensei AI</div><div class="bubble-text"><em>Sensei is typing...</em></div>';
  el.chatMessages.appendChild(typingBubble);
  el.chatMessages.scrollTop = el.chatMessages.scrollHeight;

  try {
    const kanjiDetails = state.kanjiDetailsCache[cardId] || {};
    const res = await fetch("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        vocabKanji: card.vocabKanji,
        vocabFurigana: card.vocabFurigana,
        vocabDef: card.vocabDef,
        kanjiDetails: kanjiDetails,
        conversationHistory: state.chatHistories[cardId],
        userMessage: message,
        jlptLevel: state.jlptLevel,
        confusableCards: state.currentConfusableCards
      })
    });

    if (!res.ok) throw new Error("Failed to get response from Sensei");

    const data = await res.json();
    typingBubble.remove();

    appendChatBubble("sensei", data.reply);
    state.chatHistories[cardId].push({ role: "model", content: data.reply });
  } catch (err) {
    console.error(err);
    typingBubble.remove();
    appendChatBubble("sensei", `⚠️ Gomen! Error: ${err.message}`);
  }
}

// Mining Modal Functions
// Mirrors utils.format_notes_for_anki so draft notes look exactly like saved ones.
function looksLikeFormattedHtml(text) {
  return /^\s*<(p|h[1-6]|div|ul|ol|hr|br|b|strong)\b/i.test(text) && !/(\*\*|^#{1,6}\s|^[-*•]\s)/m.test(text);
}

function formatInlineMarkdown(line) {
  return line
    .replace(/\*\*(.+?)\*\*/g, "<b>$1</b>")
    .replace(/__(.+?)__/g, "<b>$1</b>")
    .replace(/(^|[^*])\*([^*]+?)\*(?!\*)/g, "$1<i>$2</i>")
    .replace(/`([^`]+?)`/g, "<code>$1</code>");
}

function formatNotesHtml(notesText) {
  const text = String(notesText || "").trim();
  if (!text) return "";
  if (looksLikeFormattedHtml(text)) return text;

  const out = [];
  for (const rawBlock of text.split(/\n\s*\n/)) {
    const block = rawBlock.trim();
    if (!block) continue;
    if (/^(?:---|\*\*\*|___)$/.test(block)) { out.push("<hr>"); continue; }
    let para = [];
    const flush = () => { if (para.length) { out.push("<p>" + para.join("<br>") + "</p>"); para = []; } };
    for (const rawLine of block.split("\n")) {
      const line = rawLine.trim();
      if (!line) continue;
      const h = line.match(/^(#{1,6})\s+(.*)$/);
      if (h) { flush(); out.push(`<h${h[1].length}>${formatInlineMarkdown(h[2].trim())}</h${h[1].length}>`); continue; }
      if (/^(?:---|\*\*\*|___)$/.test(line)) { flush(); out.push("<hr>"); continue; }
      const li = line.match(/^[-*•]\s+(.*)$/);
      if (li) { para.push("• " + formatInlineMarkdown(li[1].trim())); continue; }
      para.push(formatInlineMarkdown(line));
    }
    flush();
  }
  return out.join("");
}

// Grammar cards skip the mnemonic step: hide Mnemonic Studio and open Persona Sentences.
function applyCardTypeTabs(card) {
  const mnemonicTab = document.querySelector('.ai-tab[data-tab="tab-mnemonic"]');
  const sentenceTab = document.querySelector('.ai-tab[data-tab="tab-sentence"]');
  if (!mnemonicTab || !sentenceTab) return;
  const grammar = isGrammarCard(card);
  mnemonicTab.classList.toggle("hidden", grammar);
  if (grammar && mnemonicTab.classList.contains("active")) sentenceTab.click();
  if (!grammar && state.lastCardWasGrammar && sentenceTab.classList.contains("active")) mnemonicTab.click();
  state.lastCardWasGrammar = grammar;
}

function addMinedButtonLabel(card) {
  const deck = isGrammarCard(card) ? (card.deckName || grammarDeckFor(getCardJlptLevel(card))) : state.targetMiningDeck;
  const parts = deck.split("::");
  return `Add to ${isGrammarCard(card) ? parts.slice(-2).join(" › ") : parts.pop()}`;
}

function updateAddMinedLabel(card) {
  const label = document.getElementById("btn-add-mined-label");
  if (label) label.textContent = addMinedButtonLabel(card);
}

// Grammar card helpers
function isGrammarCard(card) {
  if (!card) return false;
  if (card.cardType === "grammar") return true;
  return Boolean(card.tags && card.tags.some(t => t.toLowerCase() === "grammar"));
}

function getCardJlptLevel(card) {
  if (card && card.jlptLevel) return card.jlptLevel;
  const tag = card && card.tags ? card.tags.find(t => /^jlpt::n[1-5]$/i.test(t)) : null;
  return tag ? tag.split("::")[1].toUpperCase() : state.jlptLevel;
}

function getCardType(card) {
  return isGrammarCard(card) ? "grammar" : "vocab";
}

function grammarDeckFor(level) {
  return `${state.grammarDeckBase}::${level || "N4"}`;
}

function selectedGrammarLevel() {
  const v = el.miningGrammarLevel ? el.miningGrammarLevel.value : "auto";
  return ["N5", "N4", "N3"].includes(v) ? v : "auto";
}

function updateMiningTargetLabel() {
  if (!el.miningModalTargetDeck) return;
  if (state.miningCardType !== "grammar") {
    el.miningModalTargetDeck.textContent = state.targetMiningDeck;
    return;
  }
  const level = selectedGrammarLevel();
  el.miningModalTargetDeck.textContent = level === "auto"
    ? `${state.grammarDeckBase}::(AI picks the level)`
    : grammarDeckFor(level);
}

function setMiningCardType(type) {
  state.miningCardType = type === "grammar" ? "grammar" : "vocab";
  const isGrammar = state.miningCardType === "grammar";
  el.miningTypeButtons.forEach(btn => {
    const active = btn.dataset.cardType === state.miningCardType;
    btn.classList.toggle("active", active);
    btn.setAttribute("aria-checked", active ? "true" : "false");
  });
  if (el.miningGrammarLevel) el.miningGrammarLevel.classList.toggle("hidden", !isGrammar);
  if (el.miningModalTitle) el.miningModalTitle.textContent = isGrammar ? "Mine New Grammar Point" : "Mine New Vocabulary Word";
  if (el.miningInputVocabLabel) {
    el.miningInputVocabLabel.innerHTML = `${isGrammar ? "Grammar Pattern" : "Japanese Word or Phrase"} <span class="required-star">*</span>`;
  }
  el.miningInputVocab.placeholder = isGrammar
    ? "e.g. 〜ばかり, 〜ようにする, 〜わけではない, 〜てしまう..."
    : "e.g. 限界, 見失う, 一目惚れ, バイク...";
  el.miningInputHint.placeholder = isGrammar
    ? "Paste the sentence where you saw it (from your decks, a textbook, anime...)"
    : "e.g., specific nuance, scene from anime/manga, or sentence you encountered...";
  if (el.miningInputVocabHelp) {
    el.miningInputVocabHelp.textContent = isGrammar
      ? "Use 〜 for the attachment slot. The AI will fill in meaning, formation, nuance and an example sentence."
      : "Enter in kanji, kana, or dictionary form.";
  }
  if (el.miningInputHintHelp) {
    el.miningInputHintHelp.textContent = isGrammar
      ? "Used as context for meaning and nuance. The card's example sentence is written from your active personas."
      : "The AI will automatically look up furigana, English definition, constituent kanji stories, and pitch accent.";
  }
  updateMiningTargetLabel();
}

function openMiningModal() {
  if (!el.miningModal) return;
  updateMiningTargetLabel();
  el.miningModal.classList.remove("hidden");
  setTimeout(() => el.miningInputVocab.focus(), 50);
}

function closeMiningModal() {
  if (!el.miningModal) return;
  el.miningModal.classList.add("hidden");
  if (el.miningForm) el.miningForm.reset();
}

// Delete Confirmation Modal Functions
function openDeleteConfirmModal(cardData, referenceMatch = null) {
  if (!cardData) return;
  state.pendingDeleteCard = cardData;

  const isCurrentCard = Boolean(state.currentCard && (cardData === state.currentCard || (cardData.cardId && cardData.cardId === state.currentCard.cardId)));

  const modalTitle = document.querySelector("#delete-confirm-modal .modal-header h2");
  const modalSub = document.querySelector("#delete-confirm-modal .modal-header .subtitle");
  const warnText = document.querySelector("#delete-confirm-modal .delete-warning-text");

  if (isCurrentCard) {
    if (modalTitle) modalTitle.textContent = "Delete THIS Card from Anki?";
    if (referenceMatch && referenceMatch.deckName) {
      const matchedDeck = referenceMatch.deckName.split("::").pop();
      if (modalSub) modalSub.textContent = `Removing active duplicate card (already exists in ${matchedDeck})`;
      if (warnText) {
        warnText.innerHTML = `An exact match already exists in <strong>${escapeHtml(matchedDeck)}</strong>. Are you sure you want to delete <strong>THIS card (${cardData.vocabKanji})</strong>? <strong>This action cannot be undone.</strong>`;
      }
    } else {
      const deck = cardData.deckName ? cardData.deckName.split("::").pop() : "Anki collection";
      if (modalSub) modalSub.textContent = `Permanently delete this card from ${deck}`;
      if (warnText) {
        warnText.innerHTML = `Are you sure you want to permanently delete <strong>${cardData.vocabKanji}</strong> from <strong>${escapeHtml(deck)}</strong>? <strong>This action cannot be undone.</strong>`;
      }
    }
  } else {
    if (modalTitle) modalTitle.textContent = "Delete Matched Card from Anki?";
    const deck = cardData.deckName ? cardData.deckName.split("::").pop() : "Anki collection";
    if (modalSub) modalSub.textContent = `Permanently delete the duplicate card from ${deck}`;
    if (warnText) {
      warnText.innerHTML = `Are you sure you want to permanently delete this duplicate card from <strong>${escapeHtml(deck)}</strong>? <strong>This action cannot be undone.</strong>`;
    }
  }

  if (el.deleteConfirmVocabKanji) el.deleteConfirmVocabKanji.textContent = cardData.vocabKanji || "Vocabulary";
  if (el.deleteConfirmVocabFurigana) el.deleteConfirmVocabFurigana.textContent = cardData.vocabFurigana || "";
  if (el.deleteConfirmVocabDef) el.deleteConfirmVocabDef.textContent = cardData.vocabDef || "No definition available";
  if (el.deleteConfirmDeckName) {
    const rawDeck = cardData.deckName || "";
    el.deleteConfirmDeckName.textContent = rawDeck ? `Deck: ${rawDeck.split("::").pop()}` : "Anki Collection";
  }
  const idLabel = cardData.cardId && cardData.cardId > 0 ? `Card ID: #${cardData.cardId}` : (cardData.noteId ? `Note ID: #${cardData.noteId}` : (cardData.isDraft ? "Draft (Unsaved)" : ""));
  if (el.deleteConfirmCardId) el.deleteConfirmCardId.textContent = idLabel;

  if (el.btnConfirmDelete) {
    el.btnConfirmDelete.disabled = false;
    el.btnConfirmDelete.innerHTML = isCurrentCard ? '<span class="btn-icon-text">🗑️</span> Yes, Delete THIS Card' : '<span class="btn-icon-text">🗑️</span> Yes, Permanently Delete';
  }

  if (el.deleteConfirmModal) {
    el.deleteConfirmModal.classList.remove("hidden");
  }
}

function closeDeleteConfirmModal() {
  state.pendingDeleteCard = null;
  if (el.deleteConfirmModal) {
    el.deleteConfirmModal.classList.add("hidden");
  }
  if (el.btnConfirmDelete) {
    el.btnConfirmDelete.disabled = false;
    el.btnConfirmDelete.innerHTML = '<span class="btn-icon-text">🗑️</span> Yes, Permanently Delete';
  }
}

async function handleConfirmDelete() {
  if (!state.pendingDeleteCard) return;
  const cardToDelete = state.pendingDeleteCard;

  if (cardToDelete.isDraft) {
    cancelDraftCard();
    closeDeleteConfirmModal();
    return;
  }

  if (el.btnConfirmDelete) {
    el.btnConfirmDelete.disabled = true;
    el.btnConfirmDelete.innerHTML = '<span>⏳</span> Deleting from Anki...';
  }

  try {
    const res = await fetch("/api/card/delete", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        cardId: cardToDelete.cardId && cardToDelete.cardId > 0 ? cardToDelete.cardId : null,
        noteId: cardToDelete.noteId && cardToDelete.noteId > 0 ? cardToDelete.noteId : null
      })
    });

    if (!res.ok) {
      const err = await res.json();
      throw new Error(err.detail || "Failed to delete card from Anki");
    }

    showToast(`✓ "${cardToDelete.vocabKanji}" permanently deleted from Anki.`, "success");
    closeDeleteConfirmModal();

    // 1. If the deleted card is in state.cards (e.g. current card or another card in the loaded list)
    const cardIdx = state.cards.findIndex(c => (cardToDelete.cardId && c.cardId === cardToDelete.cardId) || (cardToDelete.noteId && c.noteId === cardToDelete.noteId));
    if (cardIdx !== -1) {
      state.cards.splice(cardIdx, 1);
      const allIdx = state.allLoadedCards.findIndex(c => (cardToDelete.cardId && c.cardId === cardToDelete.cardId) || (cardToDelete.noteId && c.noteId === cardToDelete.noteId));
      if (allIdx !== -1) {
        state.allLoadedCards.splice(allIdx, 1);
      }
      if (state.currentIndex >= state.cards.length) {
        state.currentIndex = Math.max(0, state.cards.length - 1);
      }
      renderCurrentCard();
      await refreshDeckDropdownStats();
    }

    // 2. If the deleted card was in collision matches list
    if (state.allCollisionMatches) {
      state.allCollisionMatches = state.allCollisionMatches.filter(m => m.cardId !== cardToDelete.cardId && m.noteId !== cardToDelete.noteId);
      renderCollisionRadar(state.allCollisionMatches);
    }

    // 3. If currentCard has collisionMatches cached
    if (state.currentCard && state.currentCard.collisionMatches) {
      state.currentCard.collisionMatches = state.currentCard.collisionMatches.filter(m => m.cardId !== cardToDelete.cardId && m.noteId !== cardToDelete.noteId);
    }

    // Refresh deck counts in dropdowns
    refreshDeckDropdownStats();
  } catch (err) {
    console.error("Delete card error:", err);
    showToast(err.message || "Failed to delete card from Anki.", "error");
    if (el.btnConfirmDelete) {
      el.btnConfirmDelete.disabled = false;
      el.btnConfirmDelete.innerHTML = '<span class="btn-icon-text">🗑️</span> Yes, Permanently Delete';
    }
  }
}

async function handleMiningSubmit(e) {
  e.preventDefault();
  const vocab = el.miningInputVocab.value.trim();
  const hint = el.miningInputHint.value.trim();

  if (!vocab) {
    showToast("Please enter a Japanese word or phrase.", "warning");
    return;
  }

  const isGrammar = state.miningCardType === "grammar";
  el.btnSubmitMining.disabled = true;
  el.btnSubmitMining.innerHTML = isGrammar
    ? '<span class="sparkle-icon">⏳</span> Analyzing Grammar & Writing Persona Sentence...'
    : '<span class="sparkle-icon">⏳</span> Analyzing & Writing Persona Sentence...';

  try {
    const res = await fetch("/api/mining/analyze", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        vocab: vocab,
        customHint: hint,
        // Grammar: "auto" lets the AI place the pattern; N5/N4/N3 forces that deck.
        jlptLevel: isGrammar ? selectedGrammarLevel() : state.jlptLevel,
        cardType: state.miningCardType,
        personas: state.activePersonas
      })
    });

    if (!res.ok) {
      const err = await res.json();
      throw new Error(err.detail || "Failed to analyze vocabulary word");
    }

    const draftCard = await res.json();
    draftCard.notes = formatNotesHtml(draftCard.notes);
    
    if (draftCard.kanjiDetails) {
      state.kanjiDetailsCache[draftCard.cardId] = draftCard.kanjiDetails;
    }

    state.cards.unshift(draftCard);
    state.currentIndex = 0;

    closeMiningModal();
    renderCurrentCard();
    const sentNote = draftCard.personaSentence
      ? `persona sentence written (${draftCard.personaSentence.themeUsed || "persona"})`
      : "persona sentence unavailable, using the analysis example";
    showToast(`Draft ready for "${draftCard.vocabKanji}": ${sentNote}.`, draftCard.personaSentence ? "success" : "info");
  } catch (err) {
    console.error("Mining analysis error:", err);
    showToast(err.message || "Failed to analyze vocabulary.", "error");
  } finally {
    el.btnSubmitMining.disabled = false;
    el.btnSubmitMining.innerHTML = '<span class="sparkle-icon">⚡</span> Lookup & Prepare Card';
  }
}

async function saveMinedCardToAnki() {
  if (!state.currentCard || !state.currentCard.isDraft) return;
  const card = state.currentCard;

  if (el.btnFooterAddMined) {
    el.btnFooterAddMined.disabled = true;
    el.btnFooterAddMined.innerHTML = '<span>⏳</span> Adding to Anki...';
  }

  try {
    const payload = {
      vocabKanji: card.vocabKanji,
      vocabFurigana: card.vocabFurigana,
      vocabDef: card.vocabDef,
      sentKanji: card.sentKanji || card.vocabKanji,
      sentFurigana: card.sentFurigana || card.vocabFurigana || card.vocabKanji,
      sentEng: card.sentEng || card.vocabDef || "",
      notes: card.notes || "",
      pitchPattern: card.pitchPattern || "",
      pitchNum: card.pitchNum || "",
      deckName: isGrammarCard(card) ? card.deckName : state.targetMiningDeck,
      cardType: getCardType(card),
      jlptLevel: isGrammarCard(card) ? getCardJlptLevel(card) : null
    };

    const res = await fetch("/api/mining/create-card", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload)
    });

    if (!res.ok) {
      const err = await res.json();
      throw new Error(err.detail || "Failed to add card to Anki");
    }

    const data = await res.json();
    const created = data.card;

    // Merge the saved note into the existing in-memory card so the attached
    // mnemonic (server-formatted notes) and sentence stay on screen. Do NOT
    // reload the card list here: that replaced state.cards wholesale and threw
    // away this card's content until a full page refresh.
    Object.assign(card, created, { isDraft: false, suspended: false, justMined: true });
    if (!state.allLoadedCards.includes(card)) {
      state.allLoadedCards.unshift(card);
    }

    renderCurrentCard();
    showToast(`✓ "${card.vocabKanji}" saved to ${created.deckName || state.targetMiningDeck}!`, "success");
    refreshDeckDropdownStats();
  } catch (err) {
    console.error("Error saving mined card:", err);
    showToast(err.message || "Failed to save card to Anki.", "error");
  } finally {
    if (el.btnFooterAddMined) {
      el.btnFooterAddMined.disabled = false;
      el.btnFooterAddMined.innerHTML = `<span class="btn-icon-text">➕</span> <span id="btn-add-mined-label">${escapeHtml(addMinedButtonLabel(card))}</span>`;
    }
  }
}

function cancelDraftCard() {
  if (!state.currentCard || !state.currentCard.isDraft) return;
  state.cards.splice(state.currentIndex, 1);
  if (state.currentIndex >= state.cards.length) {
    state.currentIndex = Math.max(0, state.cards.length - 1);
  }
  renderCurrentCard();
  showToast("Draft card discarded.", "info");
}

// Mnemonic and Sentence Modification Tracking Helpers
function hasMnemonicChanged() {
  if (state.cardMnemonicChanged) return true;
  if (!state.currentCard) return false;
  const currentNotes = (state.currentCard.notes || "").trim();
  return currentNotes !== state.cardInitialNotes && currentNotes.length > 0;
}

function hasSentenceChanged() {
  if (state.cardSentenceChanged) return true;
  if (!state.currentCard) return false;
  const currentKanji = (state.currentCard.sentKanji || "").trim();
  const currentEng = (state.currentCard.sentEng || "").trim();
  return (
    (currentKanji !== state.cardInitialSentKanji && currentKanji.length > 0) ||
    (currentEng !== state.cardInitialSentEng && currentEng.length > 0)
  );
}

function hasBothMnemonicAndSentenceChanged() {
  if (isGrammarCard(state.currentCard)) return hasSentenceChanged();
  return hasMnemonicChanged() && hasSentenceChanged();
}

function resetUnsuspendButton() {
  state.unsuspendConfirmPending = false;
  if (el.btnFooterUnsuspend) {
    el.btnFooterUnsuspend.classList.remove("btn-unsuspend-confirming");
    const isSuspended = state.currentCard ? state.currentCard.suspended : true;
    const isLeech = state.currentCard ? Boolean(state.currentCard.isLeech || (state.currentCard.tags && state.currentCard.tags.some(t => t.toLowerCase() === "leech"))) : false;
    if (state.currentCard && state.currentCard.justMined) {
      el.btnFooterUnsuspend.innerHTML = "⛏️ Mine Another Word";
      el.btnFooterUnsuspend.title = "This card is saved. Open the mining dialog for the next one.";
    } else if (isSuspended) {
      el.btnFooterUnsuspend.innerHTML = "🟢 Unsuspend & Unleech";
      el.btnFooterUnsuspend.title = "Unsuspend card and remove leech tag";
    } else if (isLeech) {
      el.btnFooterUnsuspend.innerHTML = "🟢 Unleech Card";
      el.btnFooterUnsuspend.title = "Remove leech tag from active card";
    } else {
      el.btnFooterUnsuspend.innerHTML = "🟢 Complete Review & Save";
      el.btnFooterUnsuspend.title = "Save updates and mark card as AI reviewed";
    }
  }
}

function openUnsuspendConfirmModal() {
  if (!el.unsuspendConfirmModal || !state.currentCard) return;
  if (el.unsuspendConfirmVocabKanji) {
    el.unsuspendConfirmVocabKanji.textContent = `"${state.currentCard.vocabKanji}"`;
  }

  const grammar = isGrammarCard(state.currentCard);
  const mnemChanged = grammar || hasMnemonicChanged();
  const sentChanged = hasSentenceChanged();

  if (el.unsuspendCheckMnemonic) {
    el.unsuspendCheckMnemonic.className = `checklist-item ${mnemChanged ? "item-completed" : "item-missing"}`;
  }
  if (el.unsuspendIconMnemonic) {
    el.unsuspendIconMnemonic.textContent = mnemChanged ? "✓" : "⚠️";
  }
  if (el.unsuspendStatusMnemonic) {
    el.unsuspendStatusMnemonic.textContent = grammar ? "Not needed for grammar" : (mnemChanged ? "Updated & saved to card" : "Not updated yet");
  }

  if (el.unsuspendCheckSentence) {
    el.unsuspendCheckSentence.className = `checklist-item ${sentChanged ? "item-completed" : "item-missing"}`;
  }
  if (el.unsuspendIconSentence) {
    el.unsuspendIconSentence.textContent = sentChanged ? "✓" : "⚠️";
  }
  if (el.unsuspendStatusSentence) {
    el.unsuspendStatusSentence.textContent = sentChanged ? "Updated & saved to card" : "Not updated yet";
  }

  if (el.btnConfirmOverrideUnsuspend) {
    const isSuspended = state.currentCard.suspended;
    el.btnConfirmOverrideUnsuspend.textContent = isSuspended ? "Yes, Unsuspend & Unleech Anyway" : "Yes, Unleech Card Anyway";
  }

  el.unsuspendConfirmModal.classList.remove("hidden");
}

function closeUnsuspendConfirmModal() {
  if (el.unsuspendConfirmModal) {
    el.unsuspendConfirmModal.classList.add("hidden");
  }
}

// Unsuspend & Unleech
async function unsuspendAndUnleechCurrentCard(forceOverride = false) {
  if (!state.currentCard) return;
  const card = state.currentCard;
  if (card.isDraft) return;
  if (card.justMined) {
    // Freshly mined cards are already active and reviewed; unleeching them
    // (and its Undo, which re-suspends + adds a leech tag) makes no sense.
    openMiningModal();
    return;
  }

  const isSuspended = card.suspended;
  const actionLabel = isSuspended ? "Unsuspend & Unleech" : "Unleech";

  // Check if both mnemonic and sentence were updated
  const bothChanged = hasBothMnemonicAndSentenceChanged();

  if (!bothChanged && !forceOverride) {
    if (state.unsuspendConfirmPending) {
      // User clicked the warning button in the footer a second time -> proceed to override!
    } else {
      state.unsuspendConfirmPending = true;
      if (el.btnFooterUnsuspend) {
        el.btnFooterUnsuspend.classList.add("btn-unsuspend-confirming");
        el.btnFooterUnsuspend.innerHTML = `⚠️ Are you sure? ${actionLabel}`;
        el.btnFooterUnsuspend.title = "Mnemonic or sentence unchanged. Click again or confirm to override.";
      }
      openUnsuspendConfirmModal();
      showToast(isGrammarCard(card) ? "⚠️ Example sentence not updated. Confirm to override." : "⚠️ Mnemonic & sentence not both updated. Confirm to override.", "warning");
      return;
    }
  }

  closeUnsuspendConfirmModal();
  resetUnsuspendButton();
  const cardIndex = state.currentIndex;

  try {
    const res = await fetch("/api/sync/unsuspend", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        cardId: card.cardId,
        noteId: card.noteId
      })
    });

    if (!res.ok) {
      throw new Error(`Server returned ${res.status}`);
    }

    // Save for undo
    state.lastUnsuspendedCard = {
      card: { ...card },
      index: cardIndex
    };

    if (el.btnFooterUndo) {
      el.btnFooterUndo.innerHTML = `↺ Undo (${card.vocabKanji || "Card"})`;
      el.btnFooterUndo.classList.remove("hidden");
      el.btnFooterUndo.disabled = false;
    }

    const successMsg = isSuspended
      ? `✓ "${card.vocabKanji}" unsuspended & leech tag removed!`
      : `✓ "${card.vocabKanji}" unleached (tag removed)!`;

    showToast(
      successMsg,
      "success",
      {
        label: "↺ Undo",
        onClick: () => undoLastUnsuspend()
      }
    );

    // Remove the unsuspended card from queue and immediately advance to the next card
    state.cards.splice(state.currentIndex, 1);
    if (state.currentIndex >= state.cards.length) {
      state.currentIndex = Math.max(0, state.cards.length - 1);
    }
    renderCurrentCard();

    // Refresh deck counts in the background
    refreshDeckDropdownStats();
  } catch (err) {
    console.error("Error unsuspending card:", err);
    showToast("Failed to unsuspend card.", "error");
  }
}

// Re-suspend & Restore Card (Undo)
async function undoLastUnsuspend() {
  if (!state.lastUnsuspendedCard) {
    showToast("Nothing to undo.", "info");
    return;
  }

  const { card, index } = state.lastUnsuspendedCard;

  if (el.btnFooterUndo) {
    el.btnFooterUndo.disabled = true;
    el.btnFooterUndo.innerHTML = "⏳ Undoing...";
  }

  try {
    const res = await fetch("/api/sync/undo-unsuspend", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        cardId: card.cardId,
        noteId: card.noteId
      })
    });

    if (!res.ok) {
      const errData = await res.json().catch(() => ({}));
      throw new Error(errData.detail || `Server returned ${res.status}`);
    }

    // Re-insert card at the saved index
    const restoreIndex = Math.min(Math.max(0, index), state.cards.length);
    state.cards.splice(restoreIndex, 0, card);
    state.currentIndex = restoreIndex;

    // Reset undo tracker
    state.lastUnsuspendedCard = null;
    if (el.btnFooterUndo) {
      el.btnFooterUndo.classList.add("hidden");
      el.btnFooterUndo.disabled = false;
      el.btnFooterUndo.innerHTML = "↺ Undo Unsuspend";
    }

    renderCurrentCard();
    refreshDeckDropdownStats();
    showToast(`↺ Re-suspended "${card.vocabKanji}" and restored to review!`, "info");
  } catch (err) {
    console.error("Error undoing unsuspend:", err);
    showToast(`Failed to undo: ${err.message || err}`, "error");
    if (el.btnFooterUndo) {
      el.btnFooterUndo.disabled = false;
      el.btnFooterUndo.innerHTML = `↺ Undo (${card.vocabKanji || "Card"})`;
    }
  }
}

function skipCard() {
  if (state.currentIndex < state.cards.length - 1) {
    state.currentIndex++;
    renderCurrentCard();
  } else {
    showToast("You've reached the last card in this list!", "info");
  }
}

// Setup Event Listeners
function setupEventListeners() {
  // Global JLPT Level Dropdown
  if (el.globalJlptSelect) {
    el.globalJlptSelect.addEventListener("change", async (e) => {
      state.jlptLevel = e.target.value;
      if (el.settingJlptLevel) el.settingJlptLevel.value = state.jlptLevel;
      try {
        await fetch("/api/config", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ jlptLevel: state.jlptLevel })
        });
        showToast(`Target calibrated to JLPT ${state.jlptLevel}`, "info");
      } catch (err) {
        console.error("Error saving JLPT level:", err);
      }
    });
  }

  // Card Status Filter Dropdown
  if (el.filterStatusSelect) {
    el.filterStatusSelect.addEventListener("change", async (e) => {
      const newStatus = e.target.value;
      if (state.leechStatusFilter === newStatus) return;
      if (!confirmDiscardDrafts()) {
        e.target.value = state.leechStatusFilter;
        return;
      }
      state.leechStatusFilter = newStatus;
      await loadDecks();
    });
  }

  // Delete Card Button in Footer
  if (el.btnFooterDeleteCard) {
    el.btnFooterDeleteCard.addEventListener("click", () => {
      if (state.currentCard && !state.currentCard.isDraft) {
        openDeleteConfirmModal(state.currentCard);
      }
    });
  }

  // Vocab Search Box
  if (el.vocabSearchInput) {
    if (el.navSearchWrap) {
      el.navSearchWrap.addEventListener("click", (e) => {
        if (e.target !== el.btnClearSearch) {
          el.vocabSearchInput.focus();
        }
      });
    }

    el.vocabSearchInput.addEventListener("focus", () => {
      el.navSearchWrap?.classList.add("expanded");
      el.topNav?.classList.add("search-expanded");
    });

    el.vocabSearchInput.addEventListener("blur", () => {
      el.navSearchWrap?.classList.remove("expanded");
      el.topNav?.classList.remove("search-expanded");
    });

    let debounceTimer = null;
    el.vocabSearchInput.addEventListener("input", (e) => {
      clearTimeout(debounceTimer);
      const val = e.target.value;
      debounceTimer = setTimeout(() => {
        filterCardsInMemory(val);
      }, 120);
    });

    el.vocabSearchInput.addEventListener("keydown", async (e) => {
      if (e.key === "Enter") {
        e.preventDefault();
        const val = el.vocabSearchInput.value.trim();
        await loadCards(val);
      } else if (e.key === "Escape") {
        clearSearch();
        el.vocabSearchInput.blur();
      }
    });
  }

  if (el.btnClearSearch) {
    el.btnClearSearch.addEventListener("click", () => {
      clearSearch();
      el.vocabSearchInput?.blur();
    });
  }

  // Deck selector dropdown
  el.deckSelect.addEventListener("change", async (e) => {
    if (!confirmDiscardDrafts()) {
      e.target.value = state.selectedDeck;
      return;
    }
    state.selectedDeck = e.target.value;
    await loadDecks();
  });

  // Navigation buttons
  el.btnPrev.addEventListener("click", () => {
    if (state.currentIndex > 0) {
      state.currentIndex--;
      renderCurrentCard();
    }
  });

  el.btnNext.addEventListener("click", () => {
    if (state.currentIndex < state.cards.length - 1) {
      state.currentIndex++;
      renderCurrentCard();
    }
  });

  // Inline Vocab editor toggle & save
  if (el.btnToggleVocabEdit) {
    el.btnToggleVocabEdit.addEventListener("click", toggleVocabEdit);
  }
  if (el.btnSaveInlineVocab) {
    el.btnSaveInlineVocab.addEventListener("click", saveInlineVocab);
  }
  if (el.btnCancelInlineVocab) {
    el.btnCancelInlineVocab.addEventListener("click", cancelVocabEdit);
  }

  // Inline Sentence editor toggle & save
  if (el.btnToggleSentenceEdit) {
    el.btnToggleSentenceEdit.addEventListener("click", toggleSentenceEdit);
  }
  if (el.btnSaveInlineSentence) {
    el.btnSaveInlineSentence.addEventListener("click", saveInlineSentence);
  }
  if (el.btnCancelInlineSentence) {
    el.btnCancelInlineSentence.addEventListener("click", toggleSentenceEdit);
  }

  // Inline Notes editor toggle, mode switch & WYSIWYG toolbar
  if (el.btnToggleNotesEdit) {
    el.btnToggleNotesEdit.addEventListener("click", toggleNotesEdit);
  }
  if (el.btnSaveInlineNotes) {
    el.btnSaveInlineNotes.addEventListener("click", saveInlineNotes);
  }
  if (el.btnCancelInlineNotes) {
    el.btnCancelInlineNotes.addEventListener("click", cancelNotesEdit);
  }
  if (el.btnModeWysiwyg) {
    el.btnModeWysiwyg.addEventListener("click", () => setNotesEditorMode("wysiwyg"));
  }
  if (el.btnModeHtml) {
    el.btnModeHtml.addEventListener("click", () => setNotesEditorMode("html"));
  }
  if (el.notesWysiwygToolbar) {
    el.notesWysiwygToolbar.querySelectorAll(".toolbar-btn").forEach(btn => {
      btn.addEventListener("click", (e) => {
        e.preventDefault();
        const cmd = btn.dataset.cmd;
        const arg = btn.dataset.arg || null;
        if (cmd) {
          document.execCommand(cmd, false, arg);
          if (el.notesWysiwygEditor) el.notesWysiwygEditor.focus();
        }
      });
    });
  }

  // Collision Radar Collapse Toggle
  if (el.radarHeader) {
    el.radarHeader.addEventListener("click", toggleRadarCollapse);
  }
  if (el.btnToggleRadarCollapse) {
    el.btnToggleRadarCollapse.addEventListener("click", (e) => {
      e.stopPropagation();
      toggleRadarCollapse();
    });
  }

  // Kanji Stories Collapse Toggle
  if (el.kanjiSectionHeader) {
    el.kanjiSectionHeader.addEventListener("click", toggleKanjiCollapse);
  }
  if (el.btnToggleKanjiCollapse) {
    el.btnToggleKanjiCollapse.addEventListener("click", (e) => {
      e.stopPropagation();
      toggleKanjiCollapse();
    });
  }

  // AI Tabs
  el.aiTabs.forEach(tab => {
    tab.addEventListener("click", () => {
      const tabId = tab.getAttribute("data-tab");
      el.aiTabs.forEach(t => t.classList.remove("active"));
      el.tabContents.forEach(c => c.classList.remove("active"));
      tab.classList.add("active");
      document.getElementById(tabId).classList.add("active");
    });
  });

  // Mnemonic Mode Style Buttons
  if (el.mnemonicStyleButtons) {
    el.mnemonicStyleButtons.forEach(btn => {
      btn.addEventListener("click", () => {
        const style = btn.dataset.style;
        state.mnemonicStyle = style;
        updateMnemonicStyleButtons(style);
        showToast(`Mnemonic mode set to ${btn.textContent}`, "info");
      });
    });
  }

  // Mnemonic Studio
  el.btnGenMnemonic.addEventListener("click", generateMnemonic);
  el.btnSaveMnemonicAnki.addEventListener("click", saveMnemonicToAnki);
  if (el.btnEditMnemonic) {
    el.btnEditMnemonic.addEventListener("click", toggleMnemonicEdit);
  }
  if (el.btnCancelEditMnemonic) {
    el.btnCancelEditMnemonic.addEventListener("click", cancelMnemonicEdit);
  }

  // Sentence Studio & Multi-Persona Pool
  el.btnGenSentence.addEventListener("click", generatePersonalizedSentence);
  el.btnApplySentenceAnki.addEventListener("click", applySentenceToAnki);

  // Persona Pool Collapse Toggle
  if (el.personaPoolHeader) {
    el.personaPoolHeader.addEventListener("click", (e) => {
      if (e.target.closest("#persona-pool-actions")) return;
      togglePersonaPoolCollapse();
    });
  }
  if (el.btnTogglePersonaPool) {
    el.btnTogglePersonaPool.addEventListener("click", (e) => {
      e.stopPropagation();
      togglePersonaPoolCollapse();
    });
  }

  if (el.btnSelectAllPersonas) {
    el.btnSelectAllPersonas.addEventListener("click", selectAllPersonas);
  }
  if (el.btnResetPersonas) {
    el.btnResetPersonas.addEventListener("click", resetPersonas);
  }
  if (el.btnAddPersona) {
    el.btnAddPersona.addEventListener("click", addCustomPersona);
  }
  if (el.newPersonaInput) {
    el.newPersonaInput.addEventListener("keydown", (e) => {
      if (e.key === "Enter") {
        e.preventDefault();
        addCustomPersona();
      }
    });
  }

  // Chat Studio
  el.chatForm.addEventListener("submit", (e) => {
    e.preventDefault();
    sendChatMessage();
  });

  el.btnClearChat.addEventListener("click", () => {
    if (state.currentCard) {
      state.chatHistories[state.currentCard.cardId] = [];
      renderChatHistory();
    }
  });

  el.quickQuestions.forEach(btn => {
    btn.addEventListener("click", () => {
      const q = btn.getAttribute("data-q");
      sendChatMessage(q);
    });
  });

  // Mining Modal Events
  el.miningTypeButtons.forEach(btn => {
    btn.addEventListener("click", () => setMiningCardType(btn.dataset.cardType));
  });
  if (el.miningGrammarLevel) {
    el.miningGrammarLevel.addEventListener("change", updateMiningTargetLabel);
  }
  if (el.btnOpenMineModal) {
    el.btnOpenMineModal.addEventListener("click", openMiningModal);
  }
  if (el.miningModal) {
    el.miningModal.addEventListener("click", (e) => {
      if (e.target === el.miningModal) {
        closeMiningModal();
      }
    });
  }
  if (el.btnCloseMining) {
    el.btnCloseMining.addEventListener("click", closeMiningModal);
  }
  if (el.btnCancelMining) {
    el.btnCancelMining.addEventListener("click", closeMiningModal);
  }
  if (el.miningForm) {
    el.miningForm.addEventListener("submit", handleMiningSubmit);
  }

  // Unsuspend Confirmation Modal Events
  if (el.btnConfirmOverrideUnsuspend) {
    el.btnConfirmOverrideUnsuspend.addEventListener("click", () => unsuspendAndUnleechCurrentCard(true));
  }
  if (el.btnCancelUnsuspendModal) {
    el.btnCancelUnsuspendModal.addEventListener("click", closeUnsuspendConfirmModal);
  }
  if (el.btnCloseUnsuspendConfirm) {
    el.btnCloseUnsuspendConfirm.addEventListener("click", closeUnsuspendConfirmModal);
  }
  if (el.unsuspendConfirmModal) {
    el.unsuspendConfirmModal.addEventListener("click", (e) => {
      if (e.target === el.unsuspendConfirmModal) {
        closeUnsuspendConfirmModal();
      }
    });
  }

  // Bottom action buttons
  if (el.btnFooterUndo) {
    el.btnFooterUndo.addEventListener("click", undoLastUnsuspend);
  }
  if (el.btnFooterAddMined) {
    el.btnFooterAddMined.addEventListener("click", saveMinedCardToAnki);
  }
  if (el.btnFooterCancelDraft) {
    el.btnFooterCancelDraft.addEventListener("click", cancelDraftCard);
  }
  el.btnFooterUnsuspend.addEventListener("click", () => unsuspendAndUnleechCurrentCard(false));
  el.btnFooterSkip.addEventListener("click", skipCard);

  // Settings modal
  el.btnOpenSettings.addEventListener("click", () => {
    el.settingsModal.classList.remove("hidden");
  });
  el.btnCloseSettings.addEventListener("click", () => {
    el.settingsModal.classList.add("hidden");
  });
  if (el.settingsModal) {
    el.settingsModal.addEventListener("click", (e) => {
      if (e.target === el.settingsModal) {
        el.settingsModal.classList.add("hidden");
      }
    });
  }

  // RAG Deck Selection Quick Buttons
  if (el.btnRagSelectActive) {
    el.btnRagSelectActive.addEventListener("click", () => {
      if (!el.ragDeckChecklist) return;
      const checkboxes = el.ragDeckChecklist.querySelectorAll(".rag-deck-checkbox");
      checkboxes.forEach(cb => {
        const val = cb.value.toLowerCase();
        if (val.includes("tango n1") || val.includes("tango n2") || val.includes("jlpt n1") || val.includes("jlpt n2")) {
          cb.checked = false;
        } else {
          cb.checked = true;
        }
      });
      showToast("Selected active study & mining decks (N5-N3)", "info");
    });
  }

  if (el.btnRagSelectAll) {
    el.btnRagSelectAll.addEventListener("click", () => {
      if (!el.ragDeckChecklist) return;
      el.ragDeckChecklist.querySelectorAll(".rag-deck-checkbox").forEach(cb => cb.checked = true);
      showToast("Selected all decks", "info");
    });
  }

  if (el.btnRagSelectNone) {
    el.btnRagSelectNone.addEventListener("click", () => {
      if (!el.ragDeckChecklist) return;
      el.ragDeckChecklist.querySelectorAll(".rag-deck-checkbox").forEach(cb => cb.checked = false);
      showToast("Cleared deck selection", "info");
    });
  }

  // Sync RAG Vector Index
  if (el.btnSyncRagIndex) {
    el.btnSyncRagIndex.addEventListener("click", syncRagIndex);
  }

  // Settings save
  el.btnSaveSettings.addEventListener("click", async () => {
    const selectedRagDecks = getSelectedRagDecks();
    const payload = {
      apiKey: el.settingApiKey.value.trim() || undefined,
      model: el.settingModel.value,
      persona: el.settingPersona.value.trim(),
      mnemonicTone: el.settingTone.value.trim(),
      jlptLevel: el.settingJlptLevel ? el.settingJlptLevel.value : undefined,
      kanjiStrategy: el.settingKanjiStrategy ? el.settingKanjiStrategy.value : undefined,
      kanjiDeckName: el.settingKanjiDeck ? el.settingKanjiDeck.value : undefined,
      mnemonicStyle: el.settingMnemonicStyle ? el.settingMnemonicStyle.value : undefined,
      targetMiningDeck: el.settingMiningDeck ? el.settingMiningDeck.value.trim() : undefined,
      leechSearchQuery: el.settingLeechQuery ? el.settingLeechQuery.value.trim() : undefined,
      grammarDeckBase: el.settingGrammarDeck ? el.settingGrammarDeck.value.trim() : undefined,
      reviewScopeQuery: el.settingReviewScope ? el.settingReviewScope.value.trim() : undefined,
      miningNoteType: el.settingNoteType ? el.settingNoteType.value.trim() : undefined,
      ragDecks: selectedRagDecks
    };

    try {
      const res = await fetch("/api/config", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload)
      });
      if (!res.ok) throw new Error("Failed to save settings");
      
      const data = await res.json();
      state.config = data.config;
      state.jlptLevel = data.config.jlptLevel;
      state.kanjiStrategy = data.config.kanjiStrategy;
      state.kanjiDeckName = data.config.kanjiDeckName;
      state.mnemonicStyle = data.config.mnemonicStyle;
      state.targetMiningDeck = data.config.targetMiningDeck;
      state.leechSearchQuery = data.config.leechSearchQuery;
      state.grammarDeckBase = data.config.grammarDeckBase || state.grammarDeckBase;

      if (el.globalJlptSelect) el.globalJlptSelect.value = state.jlptLevel;
      updateMnemonicStyleButtons(state.mnemonicStyle);
      if (el.miningModalTargetDeck) el.miningModalTargetDeck.textContent = state.targetMiningDeck;
      if (el.btnAddMinedLabel) el.btnAddMinedLabel.textContent = `Add to ${state.targetMiningDeck.split("::").pop()}`;

      showToast("Settings updated successfully!", "success");
      el.settingsModal.classList.add("hidden");
      await checkStatus();
    } catch (err) {
      showToast("Error saving settings.", "error");
    }
  });

  // Delete Confirmation Modal Events
  if (el.btnCloseDeleteConfirm) {
    el.btnCloseDeleteConfirm.addEventListener("click", closeDeleteConfirmModal);
  }
  if (el.btnCancelDelete) {
    el.btnCancelDelete.addEventListener("click", closeDeleteConfirmModal);
  }
  if (el.btnConfirmDelete) {
    el.btnConfirmDelete.addEventListener("click", handleConfirmDelete);
  }
  if (el.deleteConfirmModal) {
    el.deleteConfirmModal.addEventListener("click", (e) => {
      if (e.target === el.deleteConfirmModal) {
        closeDeleteConfirmModal();
      }
    });
  }

  // Keyboard Shortcuts
  window.addEventListener("keydown", (e) => {
    if (
      ["INPUT", "TEXTAREA", "SELECT"].includes(document.activeElement.tagName) ||
      document.activeElement.isContentEditable
    ) {
      return;
    }

    if (e.key === "Escape") {
      closeDeleteConfirmModal();
      closeUnsuspendConfirmModal();
      closeMiningModal();
      el.settingsModal.classList.add("hidden");
      return;
    }

    if (e.key === "Enter" && el.unsuspendConfirmModal && !el.unsuspendConfirmModal.classList.contains("hidden")) {
      e.preventDefault();
      unsuspendAndUnleechCurrentCard(true);
      return;
    }

    if (e.key === "Enter" && el.deleteConfirmModal && !el.deleteConfirmModal.classList.contains("hidden")) {
      e.preventDefault();
      handleConfirmDelete();
      return;
    }

    if (e.key === "ArrowLeft") {
      if (state.currentIndex > 0) {
        state.currentIndex--;
        renderCurrentCard();
      }
    } else if (e.key === "ArrowRight") {
      if (state.currentIndex < state.cards.length - 1) {
        state.currentIndex++;
        renderCurrentCard();
      }
    } else if (e.key === " " || e.code === "Space") {
      e.preventDefault();
      if (isGrammarCard(state.currentCard)) generatePersonalizedSentence();
      else generateMnemonic();
    } else if (e.key === "e" || e.key === "E") {
      e.preventDefault();
      toggleNotesEdit();
    } else if (e.key === "n" || e.key === "N" || e.key === "m" || e.key === "M") {
      e.preventDefault();
      openMiningModal();
    } else if (e.key === "a" || e.key === "A") {
      if (state.currentCard && state.currentCard.isDraft) {
        e.preventDefault();
        saveMinedCardToAnki();
      }
    } else if (e.key === "u" || e.key === "U") {
      if (state.currentCard && !state.currentCard.isDraft) {
        unsuspendAndUnleechCurrentCard();
      }
    } else if (e.key === "d" || e.key === "D") {
      if (state.currentCard && !state.currentCard.isDraft) {
        e.preventDefault();
        openDeleteConfirmModal(state.currentCard);
      }
    } else if (e.key === "z" || e.key === "Z") {
      e.preventDefault();
      undoLastUnsuspend();
    } else if (e.key === "s" || e.key === "S") {
      saveMnemonicToAnki();
    }
  });
}

async function syncRagIndex() {
  if (!el.btnSyncRagIndex) return;
  el.btnSyncRagIndex.disabled = true;
  el.btnSyncRagIndex.innerHTML = "⏳ Indexing Decks...";
  if (el.ragSyncFeedback) el.ragSyncFeedback.textContent = "Scanning selected Anki decks and generating vectors...";

  try {
    const selectedDecks = getSelectedRagDecks();
    const res = await fetch("/api/rag/sync", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ 
        deckNames: selectedDecks.length > 0 ? selectedDecks : undefined,
        excludeSuspended: false
      })
    });
    if (!res.ok) throw new Error("Sync failed");
    const data = await res.json();
    if (el.ragStatCount) el.ragStatCount.textContent = data.totalIndexed || data.indexed;
    if (el.ragStatSync) el.ragStatSync.textContent = data.lastSync || "Just now";
    if (el.ragSyncFeedback) el.ragSyncFeedback.textContent = `✓ Indexed ${data.indexed} cards from ${selectedDecks.length || 'active'} decks!`;
    if (el.ragStatus) {
      el.ragStatus.innerHTML = `<span class="status-dot"></span> RAG (${data.totalIndexed || data.indexed} cards)`;
    }
    showToast(`✓ Multi-Vector RAG indexed ${data.indexed} cards from selected decks!`, "success");
  } catch (err) {
    console.error("RAG sync error:", err);
    if (el.ragSyncFeedback) el.ragSyncFeedback.textContent = "⚠ Failed to sync with Anki.";
    showToast("RAG Sync Error: Make sure Anki is running with AnkiConnect.", "error");
  } finally {
    el.btnSyncRagIndex.disabled = false;
    el.btnSyncRagIndex.innerHTML = "🔄 Sync & Reindex Selected Decks";
  }
}

// Start app
document.addEventListener("DOMContentLoaded", init);

