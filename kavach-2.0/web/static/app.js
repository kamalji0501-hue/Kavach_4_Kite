(() => {
  const $ = (id) => document.getElementById(id);
  let page = "home";
  let live = {};
  const pageHtmlCache = Object.create(null);
  const pageCacheMeta = Object.create(null);

  const PAGE_LABELS = {
    home: "Home",
    status: "Status",
    summary: "Summary",
    ato: "ATO",
    register: "Register",
    deploy: "Deploy",
    payoff: "Payoff",
    token: "Token",
    alerts: "Alert logs",
  };

  function invalidatePageCache(keys) {
    if (keys == null) {
      for (const k of Object.keys(pageHtmlCache)) delete pageHtmlCache[k];
      for (const k of Object.keys(pageCacheMeta)) delete pageCacheMeta[k];
      return;
    }
    const list = Array.isArray(keys) ? keys : [keys];
    for (const k of list) {
      delete pageHtmlCache[k];
      delete pageCacheMeta[k];
    }
  }

  function invalidateHomeCache() {
    invalidatePageCache("home");
  }

  function savePageCache(key, html, meta) {
    pageHtmlCache[key] = html;
    if (meta !== undefined) pageCacheMeta[key] = meta;
  }

  function pageLabel(key) {
    return PAGE_LABELS[key] || String(key || "Page");
  }

  function showNavPerf(key, mode, ms) {
    return;
  }

  function finishPageRender(key, view, meta, navT0) {
    savePageCache(key, view.innerHTML, meta);
    playViewIn(view);
    showNavPerf(key, "fetch", Math.max(1, Math.round(performance.now() - navT0)));
  }

  function restorePageFromCache(view) {
    const html = pageHtmlCache[page];
    if (!html) return false;
    const t0 = performance.now();
    view.innerHTML = html;
    wirePageHandlers(page, pageCacheMeta[page]);
    playViewIn(view);
    applyChrome(live);
    showNavPerf(page, "cache", Math.max(1, Math.round(performance.now() - t0)));
    return true;
  }

  function wirePageHandlers(key, meta) {
    if (key === "register" && meta && meta.register) wireRegisterHandlers(meta.register);
    else if (key === "ato") wireAtoMgrHandlers();
    else if (key === "deploy") wireDeployHandlers();
    else if (key === "payoff" && meta) wirePayoffChart(meta);
    else if (key === "token") wireTokenHandlers($("view"));
  }
  let clockTimer = 0;
  let toggling = false;
  let toastTimer = 0;
  let goNotice = "";
  let goNoticeKind = "";
  let goNoticeTimer = 0;

  async function api(path, opts) {
    const res = await fetch(path, {
      credentials: "include",
      headers: { "Content-Type": "application/json" },
      ...opts,
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.error || res.statusText);
    return data;
  }


  function fmt(v, d) {
    const n = Number(v);
    if (!Number.isFinite(n)) return "—";
    return n.toLocaleString("en-IN", {
      minimumFractionDigits: d == null ? 2 : d,
      maximumFractionDigits: d == null ? 2 : d,
    });
  }
  function fmtPnl(v) {
    if (v == null || v === "" || Number.isNaN(Number(v))) return "—";
    const n = Number(v);
    const abs = Math.abs(n).toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
    return (n > 0 ? "+" : n < 0 ? "-" : "") + "₹" + abs;
  }

  function clsPnl(v) {
    const n = Number(v);
    if (!Number.isFinite(n) || n === 0) return "";
    return n > 0 ? "buy" : "sell";
  }

  function esc(s) {
    return String(s == null ? "" : s)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;");
  }

  function reduceMotion() {
    return window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  }

  function setBusy(on) {
    const g = $("busyGate");
    if (!g) return;
    g.classList.toggle("hidden", !on);
    g.setAttribute("aria-hidden", on ? "false" : "true");
  }


  const NOTICE_MS = { red: 4000, orange: 4000, green: 3000 };
  let _noticeShowing = null;
  let _pendingNonRed = null;
  let _redSoundStreak = false;
  let _redAudio = null;
  let _seenAlertIds = new Set();
  let _alertsPrimed = false;

  function _noticeSev(v) {
    const s = String(v || "").toLowerCase();
    if (s === "red" || s === "green") return s;
    return "orange";
  }

  function stopRedAlertSound() {
    _redSoundStreak = false;
    if (_redAudio) {
      try {
        _redAudio.pause();
        _redAudio.currentTime = 0;
      } catch (_) {}
    }
  }

  function playRedAlertSound() {
    if (_redSoundStreak) return;
    _redSoundStreak = true;
    try { unlockAudio(); } catch (_) {}
    try {
      if (!_redAudio) _redAudio = new Audio("/static/redAlert.wav");
      _redAudio.pause();
      _redAudio.currentTime = 0;
      _redAudio.volume = 1;
      _redAudio.play().catch(() => {});
    } catch (_) {}
  }

  function hideNoticeCard() {
    _noticeShowing = null;
    stopRedAlertSound();
    const el = $("toast");
    if (!el) return;
    const cat = $("noticeCat");
    const line = $("noticeLine");
    if (cat) cat.textContent = "";
    if (line) line.textContent = "";
    el.className = "toast";
  }

  function paintNoticeCard(item) {
    const el = $("toast");
    if (!el) return;
    const sev = _noticeSev(item.severity);
    const cat = $("noticeCat");
    const line = $("noticeLine");
    if (cat) cat.textContent = String(item.category || "Desk");
    if (line) line.textContent = String(item.alert || "");
    const cls = sev === "red" ? "bad" : sev === "green" ? "ok" : "warn";
    el.className = "toast " + cls;
    if (sev === "red") playRedAlertSound();
    else stopRedAlertSound();
  }

  function _scheduleNoticeClear() {
    if (toastTimer) {
      clearTimeout(toastTimer);
      toastTimer = 0;
    }
    const item = _noticeShowing;
    if (!item) return;
    const ms = NOTICE_MS[_noticeSev(item.severity)] || 4000;
    toastTimer = setTimeout(() => {
      toastTimer = 0;
      if (_pendingNonRed && _noticeShowing && _noticeSev(_noticeShowing.severity) === "red") {
        const nxt = _pendingNonRed;
        _pendingNonRed = null;
        _showNoticeNow(nxt);
        return;
      }
      hideNoticeCard();
    }, ms);
  }

  function _showNoticeNow(item) {
    _noticeShowing = item;
    paintNoticeCard(item);
    _scheduleNoticeClear();
  }

  function enqueueNotice(raw) {
    if (!raw) return;
    const alert = String(raw.alert || raw.text || "").trim();
    if (!alert) {
      hideNoticeCard();
      return;
    }
    const item = {
      id: raw.id || "",
      severity: _noticeSev(raw.severity),
      category: String(raw.category || "Desk"),
      alert: alert,
      log: String(raw.log || alert),
      side: raw.side || null,
    };
    if (item.severity === "red") {
      _showNoticeNow(item);
      return;
    }
    if (_noticeShowing && _noticeSev(_noticeShowing.severity) === "red") {
      _pendingNonRed = item;
      return;
    }
    _showNoticeNow(item);
  }

  function toastResult(r, fallbackOk) {
    if (r && r.desk_alert) {
      const id = String(r.desk_alert.id || "");
      if (id) _seenAlertIds.add(id);
      enqueueNotice(r.desk_alert);
      return;
    }
    const ok = fallbackOk != null ? !!fallbackOk : !!(r && r.ok);
    const text = r && (r.text || r.error) ? String(r.text || r.error) : (ok ? "Saved" : "Failed");
    toast(text, ok);
  }

  function drainDeskAlerts(s) {
    const rows = (s && s.desk_alerts) || [];
    if (!_alertsPrimed) {
      _alertsPrimed = true;
      for (const a of rows) {
        const id = String((a && a.id) || "");
        if (id) _seenAlertIds.add(id);
      }
      return;
    }
    for (const a of rows) {
      const id = String((a && a.id) || "");
      if (!id || _seenAlertIds.has(id)) continue;
      _seenAlertIds.add(id);
      enqueueNotice(a);
    }
    if (_seenAlertIds.size > 400) {
      _seenAlertIds = new Set(Array.from(_seenAlertIds).slice(-200));
    }
  }

  function toast(msg, ok) {
    const text = String(msg || "").trim();
    if (!text) {
      hideNoticeCard();
      return;
    }
    const low = text.toLowerCase();
    let sev = ok ? "green" : "orange";
    if (!ok && /halt|reject|timeout|mismatch|blocked|flatten|stop loss/.test(low)) sev = "red";
    enqueueNotice({ severity: sev, category: "Desk", alert: text, log: text });
  }

  function setGoNotice(msg, kind) {
    goNotice = msg || "";
    goNoticeKind = kind || "";
    if (goNoticeTimer) {
      clearTimeout(goNoticeTimer);
      goNoticeTimer = 0;
    }
    const el = $("goNotice");
    if (el) {
      el.textContent = goNotice;
      el.className = "go-notice" + (goNotice ? (goNoticeKind === "paused" ? " paused" : " ok") : " hidden");
    }
    if (goNotice && goNoticeKind !== "paused") {
      goNoticeTimer = setTimeout(() => {
        goNotice = "";
        goNoticeKind = "";
        const n = $("goNotice");
        if (n) {
          n.textContent = "";
          n.className = "go-notice hidden";
        }
      }, 8000);
    }
  }

  function skeleton() {
    return `<div>
      <div class="skel skel-title"></div>
      <p class="sub">Loading…</p>
      <div class="stats stats3">
        <div class="skel skel-card"></div>
        <div class="skel skel-card"></div>
        <div class="skel skel-card"></div>
      </div>
      <div class="skel skel-row"></div>
      <div class="skel skel-row"></div>
    </div>`;
  }

  function wrapPageFrame(view) {
    if (!view) return;
    if (view.querySelector(":scope > .home-dash, :scope > .page-frame")) return;
    const head = view.querySelector(":scope > .page-head");
    if (!head) return;
    const frame = document.createElement("div");
    frame.className = "page-frame";
    while (head.nextSibling) frame.appendChild(head.nextSibling);
    if (!frame.childNodes.length) return;
    view.appendChild(frame);
  }

  function playViewIn(view) {
    wrapPageFrame(view);
    if (!view || reduceMotion()) return;
    view.classList.remove("view-in");
    void view.offsetWidth;
    view.classList.add("view-in");
  }

  function tickClock() {
    const el = $("clock");
    if (!el) return;
    el.textContent = new Date().toLocaleTimeString("en-IN", {
      timeZone: "Asia/Kolkata",
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
      hour12: false,
    });
  }

  function isMobileUi() {
    return window.matchMedia("(max-width: 900px)").matches;
  }

  function paintToggle(el, lbl, on, onText, offText) {
    if (!el) return;
    if (document.activeElement !== el && !toggling) el.checked = !!on;
    const wrap = el.closest(".toggle");
    if (wrap) wrap.classList.toggle("is-on", !!on), wrap.classList.toggle("is-off", !on);
    if (lbl) lbl.textContent = on ? onText : offText;
  }


  function posRowsHtml(positions) {
    const rows = Array.isArray(positions) ? positions : [];
    if (!rows.length) {
      return '<tr><td colspan="6">No broker positions today.</td></tr>';
    }
    return rows.map((p) => {
      const qty = p.qty != null ? Number(p.qty) : 0;
      const closed = !!(p.closed || qty === 0);
      const avg = p.avg != null && p.avg !== "" ? fmt(p.avg) : "—";
      const ltp = p.ltp != null && p.ltp !== "" ? fmt(p.ltp) : "—";
      const typ = p.type || p.leg_type || "Extra";
      const pnl = p.pnl;
      const pnlTxt = pnl == null || pnl === "" ? "—" : fmtPnl(pnl);
      const pnlCls = clsPnl(pnl);
      const rowCls = closed ? "pos-closed" : (qty < 0 ? "hist-sell" : "hist-buy");
      return `<tr class="${rowCls}">
            <td>${esc(p.symbol || "")}</td>
            <td>${esc(String(typ))}</td>
            <td>${esc(String(qty))}</td>
            <td>${esc(avg)}</td>
            <td>${esc(ltp)}</td>
            <td class="${pnlCls}">${esc(pnlTxt)}</td>
          </tr>`;
    }).join("");
  }

  function posFootHtml(positions) {
    const rows = Array.isArray(positions) ? positions : [];
    if (!rows.length) return "";
    let total = 0;
    let any = false;
    for (const p of rows) {
      if (p.pnl == null || p.pnl === "") continue;
      const n = Number(p.pnl);
      if (!Number.isFinite(n)) continue;
      total += n;
      any = true;
    }
    const pnlCls = any ? clsPnl(total) : "";
    const pnlTxt = any ? esc(fmtPnl(total)) : "—";
    return `<tr class="hist-total"><td colspan="5"><b>TOTAL</b></td><td class="${pnlCls}"><b>${pnlTxt}</b></td></tr>`;
  }

  function paintPositions(positions) {
    const body = $("posBody");
    if (body) body.innerHTML = posRowsHtml(positions);
    const foot = $("posFoot");
    if (foot) foot.innerHTML = posFootHtml(positions);
  }


  function positionsCardHtml(positions) {
    return `<div class="card hist-wrap pos-card home-pos-card positions-page-card">
      <h4 class="sec-title positions-card-title">POSITIONS</h4>
      <div class="home-pos-table-wrap">
        <table class="hist-table pos-table"><thead><tr>
          <th>Symbol</th><th>Type</th><th>Qty</th><th>Avg</th><th>LTP</th><th>PnL</th>
        </tr></thead><tbody id="posBody">${posRowsHtml(positions)}</tbody><tfoot id="posFoot">${posFootHtml(positions)}</tfoot></table>
      </div>
    </div>`;
  }



  /* ---- ATO surety audio (always on; unlock on first gesture) ---- */
  const ATO_AUDIO = {
    down: "/static/audio/kavach_down_final.wav",
    up: "/static/audio/kavach_up_final.wav",
    welcome: "/static/audio/welcome_final.wav",
    register: "/static/audio/register_arm_final.wav",
    complete: "/static/audio/complete_final.wav",
    engage: "/static/audio/ato_engage_final.wav",
    exit: "/static/audio/ato_exit_final.wav",
  };
  let _audioUnlocked = false;
  let _lastArmed = null;
  let _lastBuyFillToken = null;
  let _lastSellFillToken = null;
  let _welcomePlayed = false;
  let _suppressReadinessAudioUntil = 0;
  const PROTECT_BOOK_BLOCK_REASONS = new Set([
    "pe_protect_in_book",
    "ce_protect_in_book",
  ]);

  function unlockAudio() {
    if (_audioUnlocked) return;
    _audioUnlocked = true;
    try {
      const a = new Audio(ATO_AUDIO.up);
      a.volume = 0.01;
      a.play().then(() => { a.pause(); a.currentTime = 0; }).catch(() => {});
    } catch (_) {}
  }

  function playAtoClip(kind) {
    const src = ATO_AUDIO[kind];
    if (!src) return;
    try {
      const a = new Audio(src);
      a.volume = 1;
      a.play().catch(() => {});
    } catch (_) {}
  }

  ["pointerdown", "keydown", "touchstart"].forEach((ev) => {
    window.addEventListener(ev, unlockAudio, { once: true, capture: true });
  });

  function feedAgeClass(age) {
    if (age == null || Number.isNaN(Number(age))) return "feed-bad";
    const n = Number(age);
    if (n <= 3) return "feed-ok";
    if (n <= 10) return "feed-amber";
    return "feed-bad";
  }

  function paintAtoBanner(s) {
    const el = $("atoBanner");
    if (!el) return;
    const ar = (s && s.ato_readiness) || {};
    const armed = !!ar.armed;
    const labels = ar.reason_labels || {};
    const hard = ar.hard_blocked_reasons || ar.blocked_reasons || [];
    const attention = ar.attention_reasons || [];
    const sideHalt = attention.filter((r) => r === "pe_side_halted" || r === "ce_side_halted" || r === "all_sides_halted");
    if (armed && !sideHalt.length) {
      el.classList.add("hidden");
      el.textContent = "";
      return;
    }
    const focus = (!armed ? hard : sideHalt).slice(0, 2);
    const top = focus.map((r) => labels[r] || r).filter(Boolean);
    const line = top.join(" · ") || (ar.summary_line || (armed ? "ATO PARTIAL" : "ATO BLOCKED"));
    let action = "Check Datafeedbot service / Feeder cache.";
    if (sideHalt.length) action = "Resume after checking broker book (Pause then Resume).";
    else if (hard.indexOf("deployment_not_confirmed") >= 0) action = "Register / Arm Kavach first.";
    else if (hard.indexOf("algo_paused") >= 0) action = "Tap RESUME when the feed is healthy.";
    else if (hard.indexOf("datafeedbot_down") >= 0 || hard.indexOf("kavach2_down") >= 0) {
      action = "Check VPS: datafeedbot.service / batman-kavach2.service.";
    }
    el.classList.remove("hidden");
    el.innerHTML = `<div class="ato-banner-line">${esc(line)}</div><div class="ato-banner-actions">${esc(action)}</div>`;
  }

  function _hardBlockReasons(s) {
    const ar = (s && s.ato_readiness) || {};
    return ar.hard_blocked_reasons || ar.blocked_reasons || [];
  }

  function _protectBookOnlyBlock(hard) {
    if (!hard || !hard.length) return false;
    return hard.every((r) => PROTECT_BOOK_BLOCK_REASONS.has(r));
  }

  /** Trade clips (#6/#7) win over readiness (#4/#5) on the same tick. */
  function onAtoDeskAudioEdges(s) {
    if (!s) return;
    const ar = (s && s.ato_readiness) || {};
    const buy = String(s.ato_buy_fill_token || "");
    const sell = String(s.ato_sell_fill_token || "");
    const now = Date.now();
    const initTokens = _lastBuyFillToken === null && _lastSellFillToken === null;
    const buyNew = !initTokens && buy && buy !== _lastBuyFillToken;
    const sellNew = !initTokens && sell && sell !== _lastSellFillToken;

    if (initTokens) {
      _lastBuyFillToken = buy;
      _lastSellFillToken = sell;
      if (typeof ar.armed === "boolean") _lastArmed = ar.armed;
      return;
    }

    if (buyNew) {
      playAtoClip("engage");
      _suppressReadinessAudioUntil = now + 6000;
    }
    if (sellNew) {
      playAtoClip("exit");
      _suppressReadinessAudioUntil = now + 6000;
    }

    if (typeof ar.armed === "boolean" && _lastArmed !== null) {
      const hard = _hardBlockReasons(s);
      const readinessSuppressed = now < _suppressReadinessAudioUntil;

      if (_lastArmed === true && ar.armed === false) {
        const incidentBlock = !buyNew && !_protectBookOnlyBlock(hard) && !readinessSuppressed;
        if (incidentBlock) playAtoClip("down");
      }
      if (_lastArmed === false && ar.armed === true) {
        const incidentRecovery = !sellNew && !readinessSuppressed;
        if (incidentRecovery) playAtoClip("up");
      }
      _lastArmed = ar.armed;
    }

    _lastBuyFillToken = buy;
    _lastSellFillToken = sell;
  }


  function fmtExitLevel(v) {
    if (v == null || v === "") return "";
    const n = Number(v);
    return Number.isFinite(n) ? String(n) : "";
  }

  function paintPnlExitChrome(s) {
    const pe = (s && s.pnl_exit) || {};
    const safeOn = !!pe.safe_on;
    const tpOn = !!pe.tp_on;
    const safeIn = $("safeExitOn");
    const tpIn = $("tpExitOn");
    const safeLvl = $("safeExitLevel");
    const tpLvl = $("tpExitLevel");
    const _mobExit = isMobileUi();
    paintToggle(
      safeIn,
      $("safeExitLbl"),
      safeOn,
      _mobExit ? "ON" : "STOP LOSS ON",
      _mobExit ? "OFF" : "STOP LOSS OFF"
    );
    paintToggle(
      tpIn,
      $("tpExitLbl"),
      tpOn,
      _mobExit ? "ON" : "TARGET ON",
      _mobExit ? "OFF" : "TARGET OFF"
    );
    const slName = document.querySelector(".top-exit-box.exit-sl .tog-name");
    const tpName = document.querySelector(".top-exit-box.exit-tp .tog-name");
    if (slName) slName.textContent = _mobExit ? "SL" : "STOP LOSS";
    if (tpName) tpName.textContent = _mobExit ? "TGT" : "TARGET";
    if (safeLvl && document.activeElement !== safeLvl) {
      safeLvl.value = fmtExitLevel(pe.safe_level_rs);
    }
    if (tpLvl && document.activeElement !== tpLvl) {
      tpLvl.value = fmtExitLevel(pe.tp_level_rs);
    }
  }

  let _lastPnlFireAt = null;
  let _pnlFireSeen = false;
  let _pnlFiringToast = false;

  function maybeToastPnlFire(s) {
    const pe = (s && s.pnl_exit) || {};
    const at = pe.last_at ? String(pe.last_at) : "";
    if (pe.firing) {
      _pnlFiringToast = true;
      return;
    }
    _pnlFiringToast = false;
    if (!_pnlFireSeen) {
      _pnlFireSeen = true;
      _lastPnlFireAt = at;
      return;
    }
    _lastPnlFireAt = at;
  }

  async function postPnlExit(path, on, levelEl) {
    const raw = levelEl ? levelEl.value : "";
    const body = { on: !!on, level_rs: raw === "" ? null : Number(raw) };
    try {
      setBusy(true);
      const r = await api(path, { method: "POST", body: JSON.stringify(body) });
      toastResult(r, !!r.ok);
      if (!r.ok) throw new Error(r.error || "failed");
      if (r.pnl_exit) live.pnl_exit = r.pnl_exit;
      applyChrome(live);
      await render();
    } catch (e) {
      toast(String(e.message || e), false);
      applyChrome(live);
    } finally {
      setBusy(false);
    }
  }

  function bindPnlExitControls() {
    const safeIn = $("safeExitOn");
    const tpIn = $("tpExitOn");
    const safeLvl = $("safeExitLevel");
    const tpLvl = $("tpExitLevel");
    if (safeIn && !safeIn.dataset.bound) {
      safeIn.dataset.bound = "1";
      safeIn.addEventListener("change", () => postPnlExit("/api/safe-exit", !!safeIn.checked, safeLvl));
    }
    if (tpIn && !tpIn.dataset.bound) {
      tpIn.dataset.bound = "1";
      tpIn.addEventListener("change", () => postPnlExit("/api/take-profit", !!tpIn.checked, tpLvl));
    }
    const armSave = (el, path, tog) => {
      if (!el || el.dataset.bound) return;
      el.dataset.bound = "1";
      el.addEventListener("keydown", (e) => {
        if (e.key === "Enter") {
          e.preventDefault();
          postPnlExit(path, !!(tog && tog.checked), el);
        }
      });
      el.addEventListener("change", () => {
        if (tog && tog.checked) postPnlExit(path, true, el);
      });
    };
    armSave(safeLvl, "/api/safe-exit", safeIn);
    armSave(tpLvl, "/api/take-profit", tpIn);
  }


  function applyChrome(s) {
    live = s || live;
    const paused = !!live.paused;
    const resumed = !paused;
    const hedgeOn = !!live.dyn_hedge;
    const nifty = $("niftyTop");
    if (nifty) {
      const ar = live.ato_readiness || {};
      const feed = ar.feed || {};
      const px = (feed.ltp != null && feed.ltp !== "")
        ? Number(feed.ltp).toLocaleString("en-IN", { maximumFractionDigits: 0 })
        : (live.nifty_ltp != null && live.nifty_ltp !== ""
          ? Number(live.nifty_ltp).toLocaleString("en-IN", { maximumFractionDigits: 0 })
          : (String(live.nifty || "").trim() || "—"));
      const age = feed.age_s != null ? Math.round(Number(feed.age_s)) : null;
      const ageTxt = age == null ? "?" : String(age) + "s";
      const src = String(feed.source || "—").toUpperCase();
      const col = String(feed.collector || "feeder");
      nifty.textContent = "NIFTY " + px + " · " + ageTxt + " · " + src;
      nifty.className = "";
      const stack = $("spotStack");
      if (stack) stack.className = "chip chip-spot chip-spot-stack " + feedAgeClass(age);
    }
    paintAtoBanner(live);
    onAtoDeskAudioEdges(live);
    drainDeskAlerts(live);
    const clock = $("clock");
    if (clock) clock.className = "";
    const pnlEl = $("statPnl");
    if (pnlEl) {
      const v = live.deployment ? live.day_pnl : 0;
      pnlEl.textContent = fmtPnl(v);
      const base = pnlEl.classList.contains("home-pnl-strip-val")
        ? "home-pnl-strip-val"
        : (pnlEl.classList.contains("home-pnl-big") ? "home-pnl-big" : "");
      const tone = (v == null || v === "") ? "" : clsPnl(v);
      pnlEl.className = [base, tone].filter(Boolean).join(" ");
    }
    const batEl = $("statBatmanPnl");
    if (batEl) {
      const v = live.deployment
        ? (live.batman_pnl != null ? live.batman_pnl : live.day_pnl)
        : 0;
      batEl.textContent = fmtPnl(v);
      const tone = (v == null || v === "") ? "" : clsPnl(v);
      batEl.className = ["home-pnl-strip-val", tone].filter(Boolean).join(" ");
    }
    paintToggle(
      $("runToggle"),
      $("runLbl"),
      resumed,
      isMobileUi() ? "KAVACH ON" : "KAVACH RESUMED",
      isMobileUi() ? "KAVACH OFF" : "KAVACH PAUSED"
    );
    paintToggle($("hedgeToggle"), $("hedgeLbl"), hedgeOn, "HEDGE ON", "HEDGE OFF");
    paintPnlExitChrome(live);
    maybeToastPnlFire(live);
    paintPositions(live.positions);
  }

  function pre(text) {
    return `<div class="card"><pre>${esc(text || "")}</pre></div>`;
  }

  function cap(s) {
    const t = String(s || "");
    if (!t) return "";
    return t.charAt(0).toUpperCase() + t.slice(1);
  }
  function fmtDays(n) {
    const v = Number(n);
    if (!Number.isFinite(v)) return "—";
    return v.toFixed(1) + " Days";
  }


  function kiteValidToday(saved) {
    const s = String(saved || "");
    if (s.length < 10) return false;
    const day = s.slice(0, 10);
    try {
      const todayIst = new Date().toLocaleDateString("en-CA", { timeZone: "Asia/Kolkata" });
      const todayUtc = new Date().toISOString().slice(0, 10);
      return day === todayIst || day === todayUtc;
    } catch (e) {
      return false;
    }
  }

  function paintTokenPage(view, t) {
    const d = t.dhan || {};
    const totp = t.totp || {};
    const z = t.zerodha || {};
    const n = t.nifty || {};
    const health = d.health_class || (d.present ? "healthy" : "missing");
    const healthLabel = d.present ? cap(d.status || health) : "Missing";
    view.innerHTML = `
      <header class="page-head"><h3>AUTHORISATION</h3></header>
      <div class="row2 tok-grid">
        <div class="card tok-card tok-card-green">
          <h3 class="tok-title"><img class="tok-logo" src="/static/dhan.png" alt="" />DHAN TOKEN</h3>
          <div class="tok-meta">
            <div class="kv"><span>Status</span><b class="${d.present ? "buy" : "sell"}">${esc(healthLabel)}</b></div>
            <div class="kv"><span>Last4</span><b>${d.last4 ? "····" + esc(d.last4) : "—"}</b></div>
            <div class="kv"><span>Saved</span><b>${esc(d.saved_at || "—")}</b></div>
            <div class="kv"><span>Expires</span><b>${esc(d.jwt_exp || d.expires_at || "—")}</b></div>
            <div class="kv"><span>Age / Left</span><b>${d.age_hours == null || !d.present ? "—" : d.age_hours + "h / " + (d.expires_in_hours == null ? "—" : d.expires_in_hours + "h")}</b></div>
            <div class="kv"><span>TOTP Auto-Renew</span><b>${totp.configured ? (totp.auto_renew ? "ON" : "OFF") : "Not configured"}</b></div>
            <div class="kv"><span>TOTP Secret Due</span><b>${totp.days_left == null ? "—" : fmtDays(totp.days_left)}</b></div>
            <div class="kv"><span>Last TOTP Refresh</span><b>${esc(totp.last_refresh || "never")}</b></div>
          </div>
          ${totp.last_error ? `<p class="sub tok-err">${esc(totp.last_error)}</p>` : ""}
          <label class="muted" for="jwtBox">Paste Dhan Token</label>
          <textarea id="jwtBox" class="tokbox" rows="3" autocomplete="off" spellcheck="false" placeholder="Paste DHAN Token Here"></textarea>
          <div class="row2">
            <button type="button" class="btn btn-green" id="tokRef">REFRESH JWT</button>
            <button type="button" class="btn btn-green-outline" id="tokPaste">SAVE DHAN TOKEN</button>
          </div>
          <div class="row2 tok-actions">
            <button type="button" class="btn btn-green-outline" id="tokStat">TOKEN STATUS</button>
            <button type="button" class="btn btn-red" id="tokOff">DEACTIVATE TOKEN</button>
          </div>
        </div>
        <div class="card tok-card tok-card-red">
          <h3 class="tok-title"><img class="tok-logo" src="/static/kite.svg" alt="" />KITE TOKEN</h3>
          <div class="tok-meta">
            <div class="kv"><span>Set</span><b class="${z.present ? "buy" : "sell"}">${z.present ? "Yes" : "No"}</b></div>
            <div class="kv"><span>Valid today</span><b class="${kiteValidToday(z.saved_at) ? "buy" : "sell"}">${z.present ? (kiteValidToday(z.saved_at) ? "Yes" : "No — paste a fresh token") : "—"}</b></div>
            <div class="kv"><span>Last4</span><b>${z.last4 ? "····" + esc(z.last4) : "—"}</b></div>
            <div class="kv"><span>Saved</span><b>${esc(z.saved_at || "—")}</b></div>
            <div class="kv"><span>Nifty feed</span><b>${n.ltp ? (esc(n.source || "?") + "  " + n.ltp) : "—"}</b></div>
          </div>
          <label class="muted" for="zBox">Paste Zerodha Token</label>
          <textarea id="zBox" class="tokbox" rows="3" autocomplete="off" spellcheck="false" placeholder="Paste ZERODHA Token Here"></textarea>
          <div class="row2">
            <button type="button" class="btn btn-red" id="tokZ">SAVE ZERODHA TOKEN</button>
            <button type="button" class="btn btn-red" id="tokZOff">DEACTIVATE TOKEN</button>
          </div>
        </div>
      </div>
      <p class="sub" id="tokMsg"></p>`;
    wrapPageFrame(view);
  }

  async function renderTokenPage(view, msgText) {
    const t = await api("/api/token/status");
    paintTokenPage(view, t);
    if (msgText && $("tokMsg")) $("tokMsg").textContent = msgText;
    wireTokenHandlers(view);
  }

  
  function drawPayoffChart(svg, points, spot, opts) {
    if (!svg) return;
    const pts = Array.isArray(points) ? points : [];
    const o = opts || {};
    const step = Number(o.step) || 50;
    const W = 1000, H = 420;
    const pad = { l: 64, r: 24, t: 28, b: 52 };
    const innerW = W - pad.l - pad.r;
    const innerH = H - pad.t - pad.b;
    if (!pts.length) {
      svg.innerHTML = `<text x="500" y="210" text-anchor="middle" fill="#7A7494" font-size="18">No payoff points</text>`;
      return;
    }
    const xs = pts.map((p) => Number(p.x));
    const ys = pts.map((p) => Number(p.y));
    let xmin = Math.min(...xs), xmax = Math.max(...xs);
    let ymin = Math.min(...ys, 0), ymax = Math.max(...ys, 0);
    if (xmin === xmax) { xmin -= step; xmax += step; }
    if (ymin === ymax) { ymin -= 100; ymax += 100; }
    // Keep spot visually centered: domain already ATM±10; if spot exists, shift domain symmetrically around spot.
    if (spot != null && Number(spot) > 0) {
      const half = (xmax - xmin) / 2;
      const s = Number(spot);
      xmin = s - half;
      xmax = s + half;
    }
    const xScale = (x) => pad.l + ((x - xmin) / (xmax - xmin)) * innerW;
    const yScale = (y) => pad.t + ((ymax - y) / (ymax - ymin)) * innerH;
    const zeroY = yScale(0);

    // Split payoff into profit (green) / loss (red); interpolate at zero crossings.
    const greenSegs = [];
    const redSegs = [];
    let seg = [];
    let segSign = 0;
    const flushSeg = () => {
      if (seg.length >= 2) {
        const d = seg.map((c, i) => `${i ? "L" : "M"}${c[0].toFixed(1)},${c[1].toFixed(1)}`).join(" ");
        if (segSign >= 0) greenSegs.push(d);
        else redSegs.push(d);
      }
      seg = [];
    };
    for (let i = 0; i < pts.length; i++) {
      const x = Number(pts[i].x);
      const y = Number(pts[i].y);
      const px = xScale(x);
      const py = yScale(y);
      const sign = y > 0 ? 1 : y < 0 ? -1 : 0;
      if (i === 0) {
        seg = [[px, py]];
        segSign = sign || 1;
        continue;
      }
      const y0 = Number(pts[i - 1].y);
      const px0 = xScale(Number(pts[i - 1].x));
      if ((y0 > 0 && y < 0) || (y0 < 0 && y > 0)) {
        const t = Math.abs(y0) / (Math.abs(y0) + Math.abs(y));
        const zx = px0 + t * (px - px0);
        const zy = zeroY;
        seg.push([zx, zy]);
        flushSeg();
        seg = [[zx, zy], [px, py]];
        segSign = sign;
      } else {
        if (sign && segSign && sign !== segSign) {
          flushSeg();
          seg = [[px0, yScale(y0)], [px, py]];
          segSign = sign;
        } else {
          if (sign) segSign = sign;
          seg.push([px, py]);
        }
      }
    }
    flushSeg();

    const pathAll = pts.map((p, i) => `${i ? "L" : "M"}${xScale(p.x).toFixed(1)},${yScale(p.y).toFixed(1)}`).join(" ");
    const area = `${pathAll} L${xScale(pts[pts.length - 1].x).toFixed(1)},${zeroY.toFixed(1)} L${xScale(pts[0].x).toFixed(1)},${zeroY.toFixed(1)} Z`;
    const greenPaths = greenSegs.map((d) => `<path d="${d}" fill="none" stroke="#1ED760" stroke-width="3" stroke-linejoin="round" stroke-linecap="round" />`).join("");
    const redPaths = redSegs.map((d) => `<path d="${d}" fill="none" stroke="#FF3B5C" stroke-width="3" stroke-linejoin="round" stroke-linecap="round" />`).join("");

    let grid = "";
    const atm = o.atm != null ? Number(o.atm) : null;
    const strikeStart = Math.ceil(xmin / step) * step;
    const strikes = [];
    for (let x = strikeStart; x <= xmax + 0.01; x += step) strikes.push(Math.round(x));
    strikes.forEach((x, idx) => {
      const px = xScale(x);
      const isAtm = atm != null && Math.abs(x - atm) < 0.1;
      const showLabel = isAtm || idx === 0 || idx === strikes.length - 1 || idx % 2 === 0;
      grid += `<line x1="${px}" y1="${pad.t}" x2="${px}" y2="${H - pad.b}" stroke="${isAtm ? "rgba(43,179,192,0.35)" : "rgba(124,106,232,0.10)"}" />`;
      if (showLabel) {
        grid += `<text x="${px}" y="${H - 16}" text-anchor="middle" fill="${isAtm ? "#2BB3C0" : "#7A7494"}" font-size="${isAtm ? 13 : 11}" font-weight="${isAtm ? 700 : 500}">${x}</text>`;
      }
    });
    for (let i = 0; i <= 4; i++) {
      const y = ymin + ((ymax - ymin) * i) / 4;
      const py = yScale(y);
      grid += `<line x1="${pad.l}" y1="${py}" x2="${W - pad.r}" y2="${py}" stroke="rgba(124,106,232,0.10)" />`;
      grid += `<text x="${pad.l - 10}" y="${py + 4}" text-anchor="end" fill="#7A7494" font-size="13">${Math.round(y)}</text>`;
    }

    let peakLbl = "";
    const iMax = ys.indexOf(Math.max(...ys));
    const iMin = ys.indexOf(Math.min(...ys));
    if (iMax >= 0 && ys[iMax] > 0) {
      const mx = xScale(xs[iMax]), my = yScale(ys[iMax]);
      peakLbl += `<text x="${mx}" y="${Math.max(pad.t + 14, my - 10)}" text-anchor="middle" fill="#1ED760" font-size="12" font-weight="800">MAX +${Math.round(ys[iMax])}</text>`;
    }
    if (iMin >= 0 && ys[iMin] < 0) {
      const mx = xScale(xs[iMin]), my = yScale(ys[iMin]);
      peakLbl += `<text x="${mx}" y="${Math.min(H - pad.b - 6, my + 18)}" text-anchor="middle" fill="#FF3B5C" font-size="12" font-weight="800">MAX −${Math.round(Math.abs(ys[iMin]))}</text>`;
    }

    let spotLine = "";
    if (spot != null && Number(spot) > 0) {
      const s = Number(spot);
      const sx = xScale(s);
      let spotY = null;
      for (let i = 1; i < pts.length; i++) {
        const x0 = Number(pts[i - 1].x), x1 = Number(pts[i].x);
        if ((s >= x0 && s <= x1) || (s >= x1 && s <= x0)) {
          const t = x1 === x0 ? 0 : (s - x0) / (x1 - x0);
          spotY = Number(pts[i - 1].y) + t * (Number(pts[i].y) - Number(pts[i - 1].y));
          break;
        }
      }
      if (spotY == null) spotY = 0;
      const sy = yScale(spotY);
      const pnlCol = spotY >= 0 ? "#1ED760" : "#FF3B5C";
      const pnlTxt = (spotY >= 0 ? "+" : "") + Math.round(spotY);
      spotLine = `<line x1="${sx}" y1="${pad.t}" x2="${sx}" y2="${H - pad.b}" stroke="#7C6AE8" stroke-width="2.5" />
        <circle cx="${sx}" cy="${sy}" r="6" fill="#7C6AE8" stroke="#fff" stroke-width="1.5" />
        <text x="${sx}" y="${pad.t + 18}" text-anchor="middle" fill="#7C6AE8" font-size="14" font-weight="800">SPOT ${s.toFixed(0)}</text>
        <text x="${sx + 10}" y="${sy - 10}" text-anchor="start" fill="${pnlCol}" font-size="13" font-weight="800">PnL ${pnlTxt}</text>`;
    }

    const uid = "pf" + Math.floor(Math.random() * 1e9);
    svg.innerHTML = `
      <defs>
        <clipPath id="${uid}up"><rect x="${pad.l}" y="${pad.t}" width="${innerW}" height="${Math.max(0, zeroY - pad.t)}" /></clipPath>
        <clipPath id="${uid}dn"><rect x="${pad.l}" y="${zeroY}" width="${innerW}" height="${Math.max(0, H - pad.b - zeroY)}" /></clipPath>
      </defs>
      <rect x="0" y="0" width="${W}" height="${H}" fill="transparent" />
      ${grid}
      <line x1="${pad.l}" y1="${zeroY}" x2="${W - pad.r}" y2="${zeroY}" stroke="#2A2450" stroke-width="1.5" opacity="0.45" />
      <path d="${area}" fill="rgba(30,215,96,0.14)" clip-path="url(#${uid}up)" />
      <path d="${area}" fill="rgba(255,59,92,0.12)" clip-path="url(#${uid}dn)" />
      ${greenPaths}
      ${redPaths}
      ${peakLbl}
      ${spotLine}
    `;
  }



  function go(p) {
    page = p;
    closeMenu();
    document.querySelectorAll(".nav").forEach((b) => b.classList.toggle("on", b.dataset.go === p));
    const tabPages = { home: 1, status: 1, ato: 1, register: 1 };
    document.querySelectorAll(".tabbar span").forEach((b) => {
      if (b.hasAttribute("data-menu")) {
        b.classList.toggle("on", !tabPages[p]);
      } else {
        b.classList.toggle("on", b.dataset.go === p);
      }
    });
    render(true);
  }

  function autoProtect(side, sellStrike, step) {
    const n = Number(sellStrike);
    if (!n) return "";
    return side === "PE" ? String(n - step) : String(n + step);
  }

  function strikeOf(list, symbol) {
    const row = (list || []).find((p) => p.symbol === symbol);
    return row ? row.strike : "";
  }

  function optionHtml(rows, selected, noneLabel) {
    const opts = [`<option value="">${esc(noneLabel)}</option>`];
    for (const p of rows || []) {
      const sel = p.symbol === selected ? " selected" : "";
      opts.push(`<option value="${esc(p.symbol)}"${sel}>${esc(p.label)}</option>`);
    }
    return opts.join("");
  }

  function qBlock(n, label, inner) {
    return `<div class="reg-q"><div class="q-lab"><span class="q-label">${esc(label)}</span></div><div class="field">${inner}</div></div>`;
  }


  function numLevel(el) {
    if (!el) return null;
    const raw = String(el.value || "").trim().replace(/,/g, "");
    if (!raw) return null;
    const n = Number(raw);
    return Number.isFinite(n) ? n : null;
  }

  function bufferPairIssues() {
    const issues = [];
    const ceEntry = numLevel($("ce_entry"));
    const ceExit = numLevel($("ce_retrace"));
    const peEntry = numLevel($("pe_entry"));
    const peExit = numLevel($("pe_retrace"));
    if (ceEntry != null && ceExit != null && !(ceExit < ceEntry)) {
      issues.push("CE exit must be below CE entry");
    }
    if (peEntry != null && peExit != null && !(peExit > peEntry)) {
      issues.push("PE exit must be above PE entry");
    }
    return issues;
  }

  function syncBufSaveEnabled() {
    const btn = $("bufSave");
    const msg = $("bufMsg");
    if (!btn) return;
    const issues = bufferPairIssues();
    const ok = issues.length === 0;
    btn.disabled = !ok;
    btn.setAttribute("aria-disabled", ok ? "false" : "true");
    if (msg) {
      if (!ok) {
        msg.textContent = issues.join(" · ");
        msg.classList.add("buf-hint-bad");
      } else if (msg.classList.contains("buf-hint-bad") || /must be (above|below)/i.test(msg.textContent || "")) {
        msg.textContent = "";
        msg.classList.remove("buf-hint-bad");
      }
    }
  }

  function wireAtoMgrHandlers() {
    ["ce_entry", "ce_retrace", "pe_entry", "pe_retrace"].forEach((id) => {
      const el = $(id);
      if (!el || el.dataset.bufGateWired === "1") return;
      el.dataset.bufGateWired = "1";
      el.addEventListener("input", syncBufSaveEnabled);
      el.addEventListener("change", syncBufSaveEnabled);
    });
    syncBufSaveEnabled();
    if ($("bufSave")) {
      $("bufSave").onclick = async () => {
        syncBufSaveEnabled();
        if ($("bufSave").disabled) return;
        const body = {
          ce_entry: $("ce_entry").value,
          pe_entry: $("pe_entry").value,
          ce_retrace: $("ce_retrace").value,
          pe_retrace: $("pe_retrace").value,
        };
        const r = await api("/api/buffer", { method: "POST", body: JSON.stringify(body) });
        $("bufMsg").textContent = r.ok ? "Saved" : r.error || "failed";
        if ($("bufMsg")) $("bufMsg").classList.toggle("buf-hint-bad", !r.ok);
        toastResult(r, !!r.ok);
        if (r.ok) invalidatePageCache(["home", "ato"]);
      };
    }
    if ($("pollSave")) {
      $("pollSave").onclick = async () => {
        try {
          const r = await api("/api/poll", { method: "POST", body: JSON.stringify({ poll_interval: $("pollSel").value }) });
          $("pollMsg").textContent = r.ok ? (r.text || "Saved") : (r.error || "failed");
          toastResult(r, !!r.ok);
        } catch (err) {
          $("pollMsg").textContent = err.message;
          toast(err.message, false);
        }
      };
    }
  }


  function fmtPreviewLtp(v) {
    if (v == null || v === "") return "—";
    const n = Number(v);
    return Number.isFinite(n) ? n.toFixed(2) : String(v);
  }

  function previewTableHtml(rows) {
    const body = (rows || []).length
      ? rows.map((r) => {
          const rowCls = String(r.side || '').toUpperCase() === 'BUY' ? 'dep-buy-row' : 'dep-sell-row';
          return `<tr class="${rowCls}">
          <td>${esc(r.sn)}</td>
          <td>${esc(r.type)}</td>
          <td>${esc(r.side)}</td>
          <td>${esc(r.opt)}</td>
          <td>${esc(r.strike)}</td>
          <td>${esc(r.lots)}</td>
          <td>${esc(r.qty)}</td>
          <td>${esc(fmtPreviewLtp(r.ltp))}</td>
        </tr>`;
        }).join("")
      : `<tr><td colspan="8">None</td></tr>`;
    return `<div class="card hist-wrap dep-preview-wrap"><table class="hist-table dep-preview-table"><thead><tr>
      <th>#</th><th>Type</th><th>BUY/SELL</th><th>CE/PE</th><th>Strike</th><th>Lots</th><th>Qty</th><th>LTP</th>
    </tr></thead><tbody>${body}</tbody></table></div>`;
  }

  function renderDeployPreview(el, r) {
    if (!el) return;
    if (r && r.ok && Array.isArray(r.place_rows)) {
      const nPlace = r.place_rows.length;
      const nSkip = (r.skipped_rows || []).length;
      const nPlan = nPlace + nSkip;
      let html = `<div class="dep-preview">
        <div class="dep-preview-title">Batman 2.0 Preview — Center ${esc(r.level)}</div>
        <div class="dep-preview-sub">Expiry: ${esc(r.expiry_label || r.expiry || "")} | Lots: ${esc(r.lots)} | ${nPlace} Legs to place (of ${nPlan} in plan)</div>
        ${previewTableHtml(r.place_rows)}`;
      if (nSkip) {
        html += `<div class="dep-preview-skip">Skipped (35% dyn hedge &lt; 1 lot at this size):</div>
          ${previewTableHtml(r.skipped_rows)}`;
      }
      html += `<p class="dep-preview-foot">Confirm to place all legs above (entry only).<br>Then Register Batman to arm Phase 1 / ATO.</p></div>`;
      el.innerHTML = html;
      return;
    }
    el.textContent = (r && (r.text || r.error)) || "";
  }

  function wireDeployHandlers() {
    if ($("depPrev")) {
      $("depPrev").onclick = async () => {
        try {
          const r = await api("/api/deploy", { method: "POST", body: JSON.stringify({ preview: true, level: $("depLevel").value, lots: $("depLots").value, expiry: $("depExpiry") ? $("depExpiry").value : "" }) });
          renderDeployPreview($("depOut"), r);
          $("depMsg").textContent = r.ok ? "Preview ready. Confirm only if the legs look right." : (r.error || "");
          savePageCache("deploy", $("view").innerHTML, pageCacheMeta.deploy);
        } catch (err) {
          $("depOut").textContent = err.message;
        }
      };
    }
    if ($("depGo")) {
      $("depGo").onclick = async () => {
        if (!window.confirm("Place Batman 2.0 legs now?")) return;
        try {
          const r = await api("/api/deploy", { method: "POST", body: JSON.stringify({ confirm: true, level: $("depLevel").value, lots: $("depLots").value, expiry: $("depExpiry") ? $("depExpiry").value : "" }) });
          $("depOut").textContent = r.text || r.error || "";
          const filled = Number((r.result && r.result.legs || []).filter(function (x) { return x && x.status === "filled"; }).length);
          const success = !!r.ok && filled > 0;
          $("depMsg").textContent = success
            ? ("Deploy sent " + filled + " leg(s) to Kite.")
            : (r.error || r.text || "No legs filled — check Kite. No orders punched.");
          toastResult(r, success);
          if (success) invalidatePageCache();
        } catch (err) {
          $("depOut").textContent = err.message;
          toast(err.message, false);
        }
      };
    }
    if ($("depGoReg")) {
      $("depGoReg").onclick = async () => {
        if (!window.confirm("Place Batman 2.0 legs now, then auto-Register if all placeable legs fill?")) return;
        try {
          const r = await api("/api/deploy-register", { method: "POST", body: JSON.stringify({ level: $("depLevel").value, lots: $("depLots").value, expiry: $("depExpiry") ? $("depExpiry").value : "" }) });
          $("depOut").textContent = r.detail_text || r.text || r.error || "";
          $("depMsg").textContent = r.ok
            ? "Deploy sent and Register armed successfully."
            : (r.error || r.text || "Deploy completed, but Register was not started.");
          toastResult(r, !!r.ok);
          if (r.ok) invalidatePageCache();
        } catch (err) {
          $("depOut").textContent = err.message;
          $("depMsg").textContent = err.message;
          toast(err.message, false);
        }
      };
    }
    if ($("exitAllBtn")) {
      $("exitAllBtn").onclick = async () => {
        if (!window.confirm("Exit all positions now?")) return;
        try {
          setBusy(true);
          const dres = await api("/api/flatten", {
            method: "POST",
            body: JSON.stringify({ confirm: true }),
          });
          $("exitMsg").textContent = dres.text || dres.error || "";
          toastResult(dres, !!dres.ok);
          if (dres.pnl_exit) live.pnl_exit = dres.pnl_exit;
          if (dres.ok) live.paused = true;
          applyChrome(live);
        } catch (err) {
          $("exitMsg").textContent = err.message;
          toast(err.message, false);
        } finally {
          setBusy(false);
        }
      };
    }
    if ($("doneYes")) {
      $("doneYes").onclick = async () => {
        if (!window.confirm("Complete Batman now? ATO will stop and deployment will be archived.")) return;
        try {
          const dres = await api("/api/complete", {
            method: "POST",
            body: JSON.stringify({ confirm: true }),
          });
          $("doneMsg").textContent = dres.text || dres.error || "";
          toastResult(dres, !!dres.ok);
          if (dres.ok) {
            playAtoClip("complete");
            invalidatePageCache();
            const pnlEl = $("statPnl");
            if (pnlEl) {
              pnlEl.textContent = fmtPnl(0);
              const base = pnlEl.classList.contains("home-pnl-strip-val")
                ? "home-pnl-strip-val"
                : (pnlEl.classList.contains("home-pnl-big") ? "home-pnl-big" : "");
              pnlEl.className = base;
            }
            const batEl = $("statBatmanPnl");
            if (batEl) {
              batEl.textContent = fmtPnl(0);
              batEl.className = "home-pnl-strip-val";
            }
          }
        } catch (err) {
          $("doneMsg").textContent = err.message;
          toast(err.message, false);
        }
      };
    }
  }

  function wirePayoffChart(meta) {
    drawPayoffChart($("payoffSvg"), meta.points || [], meta.spot, {
      atm: meta.atm,
      step: meta.step || 50,
    });
  }

  function wireTokenHandlers(view) {
    if (!view) return;
    async function tokenCall(fn) {
      const msg = $("tokMsg");
      try {
        setBusy(true);
        const r = await fn();
        const text = r.text || r.error || (r.ok ? "Done" : "failed");
        toastResult(r, !!r.ok);
        if (r.ok) {
          invalidatePageCache("token");
          await renderTokenPage(view, text);
          return;
        }
        if (msg) msg.textContent = text;
      } catch (err) {
        const text = err.message || "failed";
        if (msg) msg.textContent = text;
        toast(text, false);
      } finally {
        setBusy(false);
      }
    }
    if ($("tokRef")) $("tokRef").onclick = () => tokenCall(() => api("/api/token/refresh", { method: "POST", body: "{}" }));
    if ($("tokOff")) $("tokOff").onclick = () => tokenCall(() => api("/api/token/deactivate", { method: "POST", body: "{}" }));
    if ($("tokStat")) $("tokStat").onclick = () => renderTokenPage(view, "Token status refreshed.");
    if ($("tokPaste")) {
      $("tokPaste").onclick = () => tokenCall(() => api("/api/token/dhan-jwt", {
        method: "POST",
        body: JSON.stringify({ token: $("jwtBox").value }),
      }));
    }
    if ($("tokZ")) {
      $("tokZ").onclick = () => tokenCall(() => api("/api/token/zerodha", {
        method: "POST",
        body: JSON.stringify({ token: $("zBox").value }),
      }));
    }
    if ($("tokZOff")) $("tokZOff").onclick = () => tokenCall(() => api("/api/token/zerodha/deactivate", { method: "POST", body: "{}" }));
  }

  function wireRegisterHandlers(d) {
    const step = Number(d.ato_step || 50);

    function refillLong(sel, rows, keep, used, noneLabel) {
      const filtered = (rows || []).filter((p) => p.symbol === keep || !used.has(p.symbol));
      sel.innerHTML = optionHtml(filtered, keep, noneLabel);
    }

    function sync() {
      const scope = $("regScope").value;
      const peOn = scope !== "ce";
      const ceOn = scope !== "pe";
      $("regPeBlock").classList.toggle("q-off", !peOn);
      $("regCeBlock").classList.toggle("q-off", !ceOn);
      $("regPeBlock").querySelectorAll("input,select").forEach((el) => { el.disabled = !peOn; });
      $("regCeBlock").querySelectorAll("input,select").forEach((el) => { el.disabled = !ceOn; });

      const peUsed = new Set();
      if ($("regPeBuy").value) peUsed.add($("regPeBuy").value);
      refillLong($("regPeHedge"), d.pe_long, $("regPeHedge").value, peUsed, "None — not required");
      if ($("regPeHedge").value) peUsed.add($("regPeHedge").value);
      refillLong($("regPeDyn"), d.pe_long, $("regPeDyn").value, peUsed, "None — not required");
      const peHedgeLeft = (d.pe_long || []).filter((p) => p.symbol !== $("regPeBuy").value);
      const peDynLeft = peHedgeLeft.filter((p) => p.symbol !== $("regPeHedge").value);
      $("regPeHedge").closest(".reg-q").classList.toggle("q-off", !peOn || peHedgeLeft.length === 0);
      $("regPeDyn").closest(".reg-q").classList.toggle("q-off", !peOn || peDynLeft.length === 0);
      if (peOn) {
        $("regPeHedge").disabled = peHedgeLeft.length === 0;
        $("regPeDyn").disabled = peDynLeft.length === 0;
      }

      const ceUsed = new Set();
      if ($("regCeBuy").value) ceUsed.add($("regCeBuy").value);
      refillLong($("regCeHedge"), d.ce_long, $("regCeHedge").value, ceUsed, "None — not required");
      if ($("regCeHedge").value) ceUsed.add($("regCeHedge").value);
      refillLong($("regCeDyn"), d.ce_long, $("regCeDyn").value, ceUsed, "None — not required");
      const ceHedgeLeft = (d.ce_long || []).filter((p) => p.symbol !== $("regCeBuy").value);
      const ceDynLeft = ceHedgeLeft.filter((p) => p.symbol !== $("regCeHedge").value);
      $("regCeHedge").closest(".reg-q").classList.toggle("q-off", !ceOn || ceHedgeLeft.length === 0);
      $("regCeDyn").closest(".reg-q").classList.toggle("q-off", !ceOn || ceDynLeft.length === 0);
      if (ceOn) {
        $("regCeHedge").disabled = ceHedgeLeft.length === 0;
        $("regCeDyn").disabled = ceDynLeft.length === 0;
      }

      const peSell = strikeOf(d.pe_short, $("regPeSell").value);
      const ceSell = strikeOf(d.ce_short, $("regCeSell").value);
      const peAuto = autoProtect("PE", peSell, step);
      const ceAuto = autoProtect("CE", ceSell, step);
      const peCustom = $("regPeAtoMode").value === "custom";
      const ceCustom = $("regCeAtoMode").value === "custom";
      if (peOn) {
        $("regPeAto").disabled = !peCustom;
        $("regPeAto").closest(".reg-q").querySelector("input").classList.toggle("is-grey", !peCustom);
        if (!peCustom) $("regPeAto").value = "";
        $("regPeAto").placeholder = peAuto ? "Auto " + peAuto : "Custom NIFTY strike";
      }
      if (ceOn) {
        $("regCeAto").disabled = !ceCustom;
        if (!ceCustom) $("regCeAto").value = "";
        $("regCeAto").placeholder = ceAuto ? "Auto " + ceAuto : "Custom NIFTY strike";
      }

      const atoMonQ = $("regAtoMon").closest(".reg-q");
      if (peOn && ceOn) {
        $("regAtoMon").disabled = false;
        atoMonQ.classList.remove("q-off");
      } else {
        $("regAtoMon").value = peOn ? "pe" : "ce";
        $("regAtoMon").disabled = true;
        atoMonQ.classList.add("q-off");
      }
    }

    ["regScope","regPeBuy","regPeHedge","regPeDyn","regPeSell","regPeAtoMode","regCeBuy","regCeHedge","regCeDyn","regCeSell","regCeAtoMode"].forEach((id) => {
      const el = $(id);
      if (el) el.onchange = sync;
    });
    if ($("regExpiry")) {
      $("regExpiry").onchange = async () => {
        const iso = $("regExpiry").value;
        const view = $("view");
        try {
          setBusy(true);
          const nd = await api("/api/register?expiry=" + encodeURIComponent(iso));
          renderRegister(view, nd);
        } catch (err) {
          toast(err.message || "Could not reload expiry", false);
        } finally {
          setBusy(false);
        }
      };
    }
    sync();

    if ($("regGo")) {
      $("regGo").onclick = async () => {
        const body = {
          confirm: true,
          order_mode: $("regMode").value,
          expiry: $("regExpiry") ? $("regExpiry").value : "",
          reg_scope: $("regScope").value,
          pe_buy: $("regPeBuy").value,
          pe_margin_hedge: $("regPeHedge").value,
          pe_dyn_hedge: $("regPeDyn").value,
          pe_sell: $("regPeSell").value,
          pe_ato_mode: $("regPeAtoMode").value,
          pe_ato_strike: $("regPeAto").value,
          pe_entry: $("regPeEntry").value,
          pe_exit: $("regPeExit").value,
          ce_buy: $("regCeBuy").value,
          ce_margin_hedge: $("regCeHedge").value,
          ce_dyn_hedge: $("regCeDyn").value,
          ce_sell: $("regCeSell").value,
          ce_ato_mode: $("regCeAtoMode").value,
          ce_ato_strike: $("regCeAto").value,
          ce_entry: $("regCeEntry").value,
          ce_exit: $("regCeExit").value,
          ato_mon: $("regAtoMon").value,
        };
        if (!window.confirm("Arm Kavach with these Register answers?")) return;
        try {
          const r = await api("/api/register", { method: "POST", body: JSON.stringify(body) });
          $("regMsg").textContent = r.text || r.error || "done";
          toastResult(r, !!r.ok);
          if (r.ok) {
            playAtoClip("register");
            invalidatePageCache();
          }
        } catch (err) {
          $("regMsg").textContent = err.message;
          toast(err.message, false);
        }
      };
    }
  }

  function renderRegister(view, d) {
    window.__regQCount = Number(d.question_count || 18);
    const step = Number(d.ato_step || 50);
    const peHint = d.auto_protect_hint && d.auto_protect_hint.pe ? d.auto_protect_hint.pe : "";
    const ceHint = d.auto_protect_hint && d.auto_protect_hint.ce ? d.auto_protect_hint.ce : "";
    const note = d.book_note
      ? `<p class="reg-note">${esc(d.book_note)}</p>`
      : "";
    const armed = d.deployed
      ? `<p class="reg-note">Batman is already armed (${esc(d.file)}). Confirm will archive it and register again.</p>`
      : "";
    view.innerHTML = `
      <header class="page-head"><h3>REGISTER BATMAN</h3></header>
      ${note}${armed}
      <div class="card add-form reg-form">
        <section class="reg-setup reg-side dep-card-blue">
          <h4 class="sec-title">SETUP</h4>
          <div class="reg-top-grid reg-top-row">
          ${qBlock(1, "Select Mode", `
            <select id="regMode">
              <option value="paper" ${d.order_mode !== "live" ? "selected" : ""}>Paper</option>
              <option value="live" ${d.order_mode === "live" ? "selected" : ""}>Live</option>
            </select>`)}
          ${qBlock(2, "Expiry week", `
            <select id="regExpiry">
              ${(d.expiry_options || []).map((o) => `<option value="${esc(o.iso)}" ${d.expiry === o.iso ? "selected" : ""}>${esc(o.label)}</option>`).join("")}
            </select>`)}
          ${qBlock(3, "Register CE/PE", `
            <select id="regScope">
              <option value="both" ${d.reg_scope === "both" ? "selected" : ""}>Register both CE and PE</option>
              <option value="ce" ${d.reg_scope === "ce" ? "selected" : ""}>Register CE only</option>
              <option value="pe" ${d.reg_scope === "pe" ? "selected" : ""}>Register PE only</option>
            </select>`)}
          </div>
        </section>
        <div class="reg-grid">
          <section class="reg-side reg-side-ce dep-card-green" id="regCeBlock">
            <h4 class="sec-title">CE SIDE</h4>
            ${qBlock(10, "Core BUY leg", `<select id="regCeBuy">${optionHtml(d.ce_long, "", "Core BUY")}</select>`)}
            ${qBlock(11, "Margin Hedge", `<select id="regCeHedge">${optionHtml(d.ce_long, "", "None — not required")}</select>`)}
            ${qBlock(12, "35% Dynamic Hedge", `<select id="regCeDyn">${optionHtml(d.ce_long, "", "None — not required")}</select>`)}
            ${qBlock(13, "SELL leg", `<select id="regCeSell">${optionHtml(d.ce_short, "", "SELL")}</select>`)}
            ${qBlock(14, "ATO strike", `
              <div class="ato-row">
                <select id="regCeAtoMode">
                  <option value="auto" selected>Auto</option>
                  <option value="custom">Custom strike</option>
                </select>
                <input id="regCeAto" type="number" placeholder="Auto ${esc(ceHint)}" />
              </div>`)}
            ${qBlock(15, "ATO Entry Level", `<input id="regCeEntry" type="number" placeholder="${esc(d.entry_placeholder || "NIFTY level")}" />`)}
            ${qBlock(16, "ATO Exit Level (Retrace)", `<input id="regCeExit" type="number" placeholder="${esc(d.exit_placeholder || "NIFTY level")}" />`)}
          </section>
          <section class="reg-side reg-side-pe dep-card-red" id="regPeBlock">
            <h4 class="sec-title">PE SIDE</h4>
            ${qBlock(3, "Core BUY leg", `<select id="regPeBuy">${optionHtml(d.pe_long, "", "Core BUY")}</select>`)}
            ${qBlock(4, "Margin Hedge", `<select id="regPeHedge">${optionHtml(d.pe_long, "", "None — not required")}</select>`)}
            ${qBlock(5, "35% Dynamic Hedge", `<select id="regPeDyn">${optionHtml(d.pe_long, "", "None — not required")}</select>`)}
            ${qBlock(6, "SELL leg", `<select id="regPeSell">${optionHtml(d.pe_short, "", "SELL")}</select>`)}
            ${qBlock(7, "ATO strike", `
              <div class="ato-row">
                <select id="regPeAtoMode">
                  <option value="auto" selected>Auto</option>
                  <option value="custom">Custom strike</option>
                </select>
                <input id="regPeAto" type="number" placeholder="Auto ${esc(peHint)}" />
              </div>`)}
            ${qBlock(8, "ATO Entry Level", `<input id="regPeEntry" type="number" placeholder="${esc(d.entry_placeholder || "NIFTY level")}" />`)}
            ${qBlock(9, "ATO Exit Level (Retrace)", `<input id="regPeExit" type="number" placeholder="${esc(d.exit_placeholder || "NIFTY level")}" />`)}
          </section>
        </div>
        <div class="reg-top-grid">
          ${qBlock(17, "ATO manage CE/PE", `
            <select id="regAtoMon">
              <option value="both" ${d.ato_mon === "both" ? "selected" : ""}>Manage both CE and PE</option>
              <option value="ce" ${d.ato_mon === "ce" ? "selected" : ""}>Manage CE only</option>
              <option value="pe" ${d.ato_mon === "pe" ? "selected" : ""}>Manage PE only</option>
            </select>`)}
          ${qBlock(18, "Confirm Deployment", `<button type="button" class="btn gold" id="regGo">REGISTER — ARM KAVACH</button>`)}
        </div>
        <p class="sub" id="regMsg"></p>
      </div>`;
    wrapPageFrame(view);
    wireRegisterHandlers(d);
  }

  function demoOvernight() {
    try {
      return new URLSearchParams(location.search).get("demo") === "hedge";
    } catch (e) {
      return false;
    }
  }
  function overnightDemoData() {
    return {
      pending: true,
      denied: false,
      active: false,
      buy_time_ist: "15:20",
      ce_symbol: "NIFTY25SEP24950CE",
      ce_qty: 650,
      pe_symbol: "NIFTY25SEP23950PE",
      pe_qty: 650,
      sides: [
        { side: "CE", zone: "White", symbol: "NIFTY25SEP24950CE", strike: 24950, qty: 650, action: "standard_break_even" },
        { side: "PE", zone: "White", symbol: "NIFTY25SEP23950PE", strike: 23950, qty: 650, action: "standard_break_even" },
      ],
      summary: { status: "pending", denied: false },
      cycles: [
        { side: "CE", symbol: "NIFTY25SEP24950CE", qty: 650, entry_time: "15:20:11", entry_premium: 42.5, exit_time: "", exit_premium: null, impact: null, status: "open" },
        { side: "PE", symbol: "NIFTY25SEP23950PE", qty: 650, entry_time: "15:20:14", entry_premium: 38.0, exit_time: "", exit_premium: null, impact: null, status: "open" },
      ],
    };
  }

  async function render() {

    const view = $("view");
    if (!view) return;
    try {
      if (restorePageFromCache(view)) return;
      const navT0 = performance.now();
      let pageMeta = null;
      setBusy(true);
      if (page === "home") {
        const [s, a, b, sum, tok] = await Promise.all([
          api("/api/state"),
          api("/api/ato-status"),
          api("/api/buffer"),
          api("/api/trade-summary"),
          api("/api/token/status"),
        ]);
        if (demoOvernight()) s.overnight = overnightDemoData();
        applyChrome(s);
        const homePnl = s.deployment ? s.day_pnl : 0;
        const batmanPnl = s.deployment ? (s.batman_pnl != null ? s.batman_pnl : homePnl) : 0;
        const pnlCls = homePnl == null || homePnl === "" ? "" : clsPnl(homePnl);
        const batmanCls = batmanPnl == null || batmanPnl === "" ? "" : clsPnl(batmanPnl);
        const mode = String(s.order_mode || "paper").toUpperCase();
        const armed = !!s.deployment;
        const dhan = (tok && tok.dhan) || {};
        const kite = (tok && tok.zerodha) || {};
        const dhanLbl = dhan.present ? cap(dhan.status || dhan.health_class || "OK") : "Missing";
        const kiteLbl = kite.present ? "Set" : "Missing";
        const open = (sum && sum.open) || [];
        const openHtml = open.length
          ? open.map((leg) => `
              <div class="kv"><span>${esc(leg.side)} ATO</span><b>${esc(leg.symbol || "—")}</b></div>
              <div class="kv"><span>Strike</span><b>${esc(leg.protect_strike || "—")}</b></div>
              <div class="kv"><span>Status</span><b class="buy">OPEN</b></div>`).join("")
          : `<p class="sub home-empty">No open ATO protect leg.</p>`;
        const lvl = (v) => (v == null || v === "" ? "—" : esc(v));
        view.innerHTML = `
          <header class="page-head"><h3>HOME</h3></header>
          <div class="home-dash">
            <div class="home-strip">
              <div class="home-pnl-pair">
                <div class="home-pnl-strip" title="Day PnL">
                  <span class="home-pnl-strip-lab">DAY PNL</span>
                  <span id="statPnl" class="home-pnl-strip-val ${pnlCls}">${esc(fmtPnl(homePnl))}</span>
                </div>
                <div class="home-pnl-strip home-pnl-strip-batman" title="${esc((s.batman_pnl_detail && (s.batman_pnl_detail.asof_label + ' | day ' + s.batman_pnl_detail.day_pnl + ' + ATO ' + s.batman_pnl_detail.ato_prev_day_rupees + ' + OH ' + s.batman_pnl_detail.overnight_prev_day_rupees)) || 'Day PnL + prior-day ATO + prior-day overnight')}">
                  <span class="home-pnl-strip-lab">BATMAN PNL</span>
                  <span id="statBatmanPnl" class="home-pnl-strip-val ${batmanCls}">${esc(fmtPnl(batmanPnl))}</span>
                </div>
              </div>
              <div class="home-strip-group home-strip-ops">
                <span class="home-chip ${s.paused ? "bad" : "ok"}">${s.paused ? "KAVACH PAUSED" : "KAVACH RESUMED"}</span>
                <span class="home-chip ${s.dyn_hedge ? "ok" : "bad"}">${s.dyn_hedge ? "HEDGE ON" : "HEDGE OFF"}</span>
                <span class="home-chip ${(s.overnight && s.overnight.active) ? "ok" : ((s.overnight && s.overnight.pending) ? "bad" : "")}">${(function(){ const o=s.overnight||{}; if(o.active) return "OVERNIGHT HEDGE ON"; if(o.pending) return "HEDGE BOX PENDING"; return "OVERNIGHT OFF"; })()}</span>
                <span class="home-chip ${s.broker ? "ok" : "bad"}">${s.broker ? "BROKER OK" : "BROKER OFF"}</span>
                <span class="home-chip ${armed ? "ok" : "bad"}">${armed ? "ARMED" : "NOT ARMED"}</span>
                <span class="home-chip ${(function(){ const ar=s.ato_readiness||{}; const att=(ar.attention_reasons||[]); const halt=att.some(r=>r==="pe_side_halted"||r==="ce_side_halted"||r==="all_sides_halted"); if(ar.armed && halt) return "bad"; return ar.armed?"ok":"bad"; })()}">${(function(){ const ar=s.ato_readiness||{}; const att=(ar.attention_reasons||[]); const halt=att.some(r=>r==="pe_side_halted"||r==="ce_side_halted"||r==="all_sides_halted"); if(ar.armed && halt) return "ATO PARTIAL"; return ar.armed?"ATO ARMED":"ATO BLOCKED"; })()}</span>
              </div>
              <div class="home-strip-group home-strip-ato">
                <span class="home-chip ${s.ce_ato ? "ok" : ""}">CE ATO ${s.ce_ato ? "ACTIVE" : "IDLE"}</span>
                <span class="home-chip ${s.pe_ato ? "ok" : ""}">PE ATO ${s.pe_ato ? "ACTIVE" : "IDLE"}</span>
              </div>
              <div class="home-strip-group home-strip-tok">
                <span class="home-chip ${dhan.present ? "ok" : "bad"}">DHAN · ${esc(dhanLbl)}</span>
                <span class="home-chip ${kite.present ? "ok" : "bad"}">KITE · ${esc(kiteLbl)}</span>
              </div>
            </div>

            <div class="home-body-grid">
              <div class="home-left-stack">
                <div class="card home-card dep-card-blue home-open-card">
                  <h4 class="sec-title">OPEN ATO</h4>
                  <div class="home-kv-wrap">${openHtml}</div>
                  <div class="kv"><span>Manage</span><b>${esc(a.manage || "—")}</b></div>
                  <div class="kv"><span>CE protect</span><b>${esc(a.ce_protect || s.ce_symbol || "N/A")}</b></div>
                  <div class="kv"><span>PE protect</span><b>${esc(a.pe_protect || s.pe_symbol || "N/A")}</b></div>
                </div>
                <div class="card home-card dep-card-green">
                  <h4 class="sec-title">ATO LEVELS</h4>
                  <div class="kv"><span>CE Entry</span><b>${lvl(b.ce_entry)}</b></div>
                  <div class="kv"><span>CE Exit</span><b>${lvl(b.ce_retrace)}</b></div>
                  <div class="kv"><span>PE Entry</span><b>${lvl(b.pe_entry)}</b></div>
                  <div class="kv"><span>PE Exit</span><b>${lvl(b.pe_retrace)}</b></div>
                  <div class="kv"><span>NIFTY</span><b>${lvl(b.nifty_ltp != null ? Number(b.nifty_ltp).toFixed(2) : s.nifty)}</b></div>
                </div>
                <div class="card home-card" id="hedgeBoxCard">
                  <h4 class="sec-title">HEDGE BOX / OVERNIGHT</h4>
                  ${(function(){
                    const o = s.overnight || {};
                    const sides = o.sides || [];
                    const sideHtml = sides.length
                      ? sides.map((x) => `<div class="kv"><span>${esc(x.side)} ${esc(x.zone || "")}</span><b>${esc(x.symbol || x.strike || "—")} x${esc(x.qty || 0)}</b></div>`).join("")
                      : (o.active
                          ? `<div class="kv"><span>CE overnight</span><b>${esc(o.ce_symbol || "—")} x${esc(o.ce_qty || 0)}</b></div>
                             <div class="kv"><span>PE overnight</span><b>${esc(o.pe_symbol || "—")} x${esc(o.pe_qty || 0)}</b></div>`
                          : `<p class="sub home-empty">No Hedge Box plan. Auto-buy 15:20 unless Deny.</p>`);
                    const denyBtn = o.pending
                      ? `<button type="button" class="btn danger oh-deny" id="hedgeBoxDeny">DENY EVENING BUY</button>`
                      : "";
                    const status = o.denied ? "DENIED" : (o.active ? "ON — ATO OFF UNTIL 09:20" : (o.pending ? ("AUTO-BUY " + (o.buy_time_ist || "15:20")) : "IDLE"));
                    return `<div class="kv"><span>Status</span><b>${esc(status)}</b></div>${sideHtml}${denyBtn}`;
                  })()}
                </div>
                <div class="card home-card ato-ready-card">
                  <h4 class="sec-title">ATO READINESS</h4>
                  <div class="kv"><span>Status</span><b class="${(function(){ const ar=s.ato_readiness||{}; const att=ar.attention_reasons||[]; const halt=att.some(r=>r==="pe_side_halted"||r==="ce_side_halted"||r==="all_sides_halted"); if(ar.armed && !halt) return "ok"; return "bad"; })()}">${esc((s.ato_readiness && s.ato_readiness.summary_line) || "—")}</b></div>
                  <div class="kv"><span>PE side</span><b class="${(s.ato_readiness && s.ato_readiness.sides && s.ato_readiness.sides.pe && s.ato_readiness.sides.pe.halted) ? "bad" : "ok"}">${esc((s.ato_readiness && s.ato_readiness.sides && s.ato_readiness.sides.pe && s.ato_readiness.sides.pe.label) || "—")}</b></div>
                  <div class="kv"><span>CE side</span><b class="${(s.ato_readiness && s.ato_readiness.sides && s.ato_readiness.sides.ce && s.ato_readiness.sides.ce.halted) ? "bad" : "ok"}">${esc((s.ato_readiness && s.ato_readiness.sides && s.ato_readiness.sides.ce && s.ato_readiness.sides.ce.label) || "—")}</b></div>
                  <div class="kv"><span>Feed age</span><b>${esc((s.ato_readiness && s.ato_readiness.feed && s.ato_readiness.feed.age_s != null) ? (Math.round(s.ato_readiness.feed.age_s) + "s") : "—")}</b></div>
                  <div class="kv"><span>Checked</span><b>${esc((s.ato_readiness && s.ato_readiness.checked_at) || "—")}</b></div>
                </div>
              </div>

              <div class="card hist-wrap pos-card home-pos-card">
                <div class="home-pos-inner">
                  <div class="home-pos-side" aria-label="Positions">POSITIONS</div>
                  <div class="home-pos-table-wrap">
                    <table class="hist-table pos-table"><thead><tr>
                      <th>Symbol</th><th>Type</th><th>Qty</th><th>Avg</th><th>LTP</th><th>PnL</th>
                    </tr></thead><tbody id="posBody">${posRowsHtml(s.positions)}</tbody><tfoot id="posFoot">${posFootHtml(s.positions)}</tfoot></table>
                  </div>
                </div>
              </div>
            </div>
          </div>`;
        finishPageRender("home", view, null, navT0);
        const denyBtn = $("hedgeBoxDeny");
        if (denyBtn) denyBtn.onclick = async () => {
          const r = await api("/api/hedge-box", { method: "POST", body: JSON.stringify({ action: "deny" }) });
          toast((r && r.text) || (r && r.error) || "Deny sent", r && r.ok);
          render();
        };
        return;
      }

      if (page === "positions") {
        const s = await api("/api/state");
        applyChrome(s);
        view.innerHTML = `
          <header class="page-head"><h3>POSITIONS</h3></header>
          ${positionsCardHtml(s.positions)}`;
        finishPageRender("positions", view, null, navT0);
        return;
      }
      if (page === "status") {
        const stTxt = (await api("/api/status")).text;
        let ready = {};
        try { ready = await api("/api/ato-readiness"); } catch (_) { ready = {}; }
        const hard = (ready.hard_blocked_reasons || []).map((r) => (ready.reason_labels && ready.reason_labels[r]) || r);
        const svc = ready.services || {};
        const feed = ready.feed || {};
        view.innerHTML = `<header class="page-head"><h3>KAVACH STATUS</h3></header>
          <div class="card ato-ready-card">
            <h4 class="sec-title">ATO READINESS</h4>
            <div class="kv"><span>Summary</span><b class="${(function(){ const att=ready.attention_reasons||[]; const halt=att.some(r=>r==="pe_side_halted"||r==="ce_side_halted"||r==="all_sides_halted"); if(ready.armed && !halt) return "ok"; return "bad"; })()}">${esc(ready.summary_line || "—")}</b></div>
            <div class="kv"><span>PE side</span><b class="${(ready.sides && ready.sides.pe && ready.sides.pe.halted) ? "bad" : "ok"}">${esc((ready.sides && ready.sides.pe && ready.sides.pe.label) || "—")}</b></div>
            <div class="kv"><span>CE side</span><b class="${(ready.sides && ready.sides.ce && ready.sides.ce.halted) ? "bad" : "ok"}">${esc((ready.sides && ready.sides.ce && ready.sides.ce.label) || "—")}</b></div>
            <div class="kv"><span>Checked</span><b>${esc(ready.checked_at || "—")}</b></div>
            <div class="kv"><span>Feed</span><b>${esc((feed.ltp != null ? feed.ltp : "—") + " · age " + (feed.age_s != null ? Math.round(feed.age_s) + "s" : "?") + " · " + (feed.source || "") + " · " + (feed.collector || ""))}</b></div>
            <div class="kv"><span>Datafeedbot</span><b class="${svc.datafeedbot_active ? "ok" : "bad"}">${svc.datafeedbot_active ? "active" : "down"}</b></div>
            <div class="kv"><span>Kavach2</span><b class="${svc.kavach2_active ? "ok" : "bad"}">${svc.kavach2_active ? "active" : "down"}</b></div>
            <div class="kv"><span>Block reasons</span><b>${esc(hard.length ? hard.join("; ") : "none")}</b></div>
          </div>` + pre(stTxt);

      } else if (page === "overnight") {
        const o = demoOvernight() ? overnightDemoData() : ((await api("/api/hedge-box")) || {});
        const sum = o.summary || {};
        const sides = o.sides && o.sides.length ? o.sides : (sum.sides || []);
        const sideRows = sides.length
          ? sides.map((x, i) => `<tr>
              <td>${i + 1}</td>
              <td>${esc(x.side)}</td>
              <td>${esc(x.zone || "—")}</td>
              <td>${esc(x.symbol || x.strike || "—")}</td>
              <td>${esc(x.qty || 0)}</td>
              <td>${esc(x.action || "—")}</td>
            </tr>`).join("")
          : `<tr><td colspan="6">No evening plan yet. Kavach posts CE + PE here at 15:15.</td></tr>`;
        const status = o.denied || sum.denied ? "DENIED" : (o.active ? "HOLDING — ATO OFF UNTIL 09:20" : (o.pending ? ("PENDING — AUTO-BUY " + (o.buy_time_ist || "15:20")) : (sum.status || "IDLE")));
        const morning = sum.morning_kind
          ? (sum.morning_kind === "inside"
              ? "Open inside box — hedges exited — ATO on"
              : sum.morning_kind === "ce_out"
                ? "Open outside CE — CE ATO first — hedges exited"
                : sum.morning_kind === "pe_out"
                  ? "Open outside PE — PE ATO first — hedges exited"
                  : "Open outside both — ATO both sides — hedges exited")
          : "Waiting for 09:20";
        const denyBtn = o.pending
          ? `<button type="button" class="btn danger oh-deny" id="hedgeBoxDeny">DENY EVENING BUY</button>`
          : "";
        const cycles = o.cycles || [];
        let cycTotal = 0;
        let cycRs = 0;
        let cycN = 0;
        const sess = o.session_totals || {};
        const cycRows = cycles.map((b, i) => {
          const impact = b.impact == null || b.impact === "" ? null : Number(b.impact);
          if (impact != null && Number.isFinite(impact)) {
            cycTotal += impact;
            cycRs += Number(b.impact_rupees || 0);
            cycN += 1;
          }
          const num = b.session_cycle != null ? b.session_cycle : (i + 1);
          const when = b.entry_time || "—";
          return `<tr class="hist-buy">
            <td>${num}</td>
            <td>${esc(b.side)}</td>
            <td>${esc(b.symbol)}</td>
            <td>${esc(when)}</td>
            <td>${b.entry_premium != null && b.entry_premium !== "" ? fmt(b.entry_premium) : "—"}</td>
            <td>${esc(b.exit_time || "—")}</td>
            <td>${b.exit_premium != null && b.exit_premium !== "" ? fmt(b.exit_premium) : "—"}</td>
            <td class="${impact == null ? "" : clsPnl(impact)}">${impact == null ? (b.converted_to_ato ? "→ ATO" : "—") : ((impact >= 0 ? "+" : "") + fmt(impact))}</td>
          </tr>`;
        }).join("");
        const footImpact = sess.total_impact != null ? Number(sess.total_impact) : cycTotal;
        const footRs = sess.total_rupees != null ? Number(sess.total_rupees) : cycRs;
        const footN = sess.closed_count != null ? Number(sess.closed_count) : cycN;
        const cycFoot = (cycles.length || footN)
          ? `<tfoot><tr class="hist-total">
              <td colspan="7"><b>Session total since Register — ${footN} closed hedge cycle${footN === 1 ? "" : "s"} · ₹ ${fmt(footRs)}</b></td>
              <td class="${clsPnl(footImpact)}"><b>${(footImpact >= 0 ? "+" : "") + fmt(footImpact)}</b></td>
            </tr></tfoot>`
          : "";
        view.innerHTML = `
          <header class="page-head"><h3>OVERNIGHT HEDGE</h3><p class="sub">Right card keeps every buy/sell from Register until Batman Complete.</p></header>
          <div class="oh-page-grid">
            <div class="oh-left-stack">
              <div class="card home-card dep-card-blue">
                <h4 class="sec-title">TODAY</h4>
                <div class="kv"><span>Status</span><b>${esc(status)}</b></div>
                <div class="kv"><span>CE fill</span><b>${esc(o.ce_symbol || sum.ce_symbol || "—")} x${esc(o.ce_qty || sum.ce_qty || 0)}</b></div>
                <div class="kv"><span>PE fill</span><b>${esc(o.pe_symbol || sum.pe_symbol || "—")} x${esc(o.pe_qty || sum.pe_qty || 0)}</b></div>
                <div class="kv"><span>Morning</span><b>${esc(morning)}</b></div>
                <p class="sub">Kavach buys at 15:20 unless you Deny. Morning SELL is the evening fill only — extra lots and 35% dyn hedge stay.</p>
                ${denyBtn}
              </div>
              <div class="card hist-wrap">
                <table class="hist-table"><thead><tr>
                  <th>#</th><th>Side</th><th>Zone</th><th>Hedge</th><th>Qty</th><th>Action</th>
                </tr></thead><tbody>${sideRows}</tbody></table>
              </div>
            </div>
            <div class="card hist-wrap oh-summary-card">
              <table class="hist-table"><thead><tr>
                <th>#</th><th>Side</th><th>Hedge</th><th>Entry Time</th><th>Entry Px</th>
                <th>Exit Time</th><th>Exit Px</th><th>Impact</th>
              </tr></thead><tbody>${cycRows || '<tr><td colspan="8">No overnight hedge cycles since Register.</td></tr>'}</tbody>${cycFoot}</table>
            </div>
          </div>`;
        const denyBtnEl = $("hedgeBoxDeny");
        if (denyBtnEl) denyBtnEl.onclick = async () => {
          const r = await api("/api/hedge-box", { method: "POST", body: JSON.stringify({ action: "deny" }) });
          toast((r && r.text) || (r && r.error) || "Deny sent", r && r.ok);
          render();
        };

      } else if (page === "summary") {
        const d = await api("/api/trade-summary");
        const closed = d.closed || [];
        let total = 0;
        let totalRs = 0;
        const rows = closed
          .map((b, i) => {
            const impact = Number(b.impact || 0);
            total += impact;
            totalRs += Number(b.impact_rupees || 0);
            const num = b.session_cycle != null ? b.session_cycle : (i + 1);
            return `<tr class="hist-buy">
            <td>${num}</td>
            <td>${esc(b.side)}</td>
            <td>${esc(b.symbol)}</td>
            <td>${esc(b.entry_time)}</td>
            <td>${fmt(b.entry_premium)}</td>
            <td>${esc(b.exit_time)}</td>
            <td>${fmt(b.exit_premium)}</td>
            <td class="${clsPnl(impact)}">${(impact >= 0 ? "+" : "") + fmt(impact)}</td>
          </tr>`;
          })
          .join("");
        const n = closed.length;
        const foot = n
          ? `<tfoot><tr class="hist-total">
              <td colspan="7"><b>Session total since Register — ${n} ATO cycle${n === 1 ? "" : "s"} · ₹ ${fmt(d.total_rupees != null ? d.total_rupees : totalRs)}</b></td>
              <td class="${clsPnl(d.total_impact != null ? d.total_impact : total)}"><b>${((d.total_impact != null ? d.total_impact : total) >= 0 ? "+" : "") + fmt(d.total_impact != null ? d.total_impact : total)}</b></td>
            </tr></tfoot>`
          : "";
        view.innerHTML = `
          <header class="page-head"><h3>ATO SUMMARY</h3>
            <p class="sub">Cycles keep numbering from Register until Batman Complete (not reset each day).</p>
          </header>
          <div class="card hist-wrap">
            <table class="hist-table"><thead><tr>
              <th>#</th><th>Side</th><th>Protect</th><th>Entry Time</th><th>Entry Px</th>
              <th>Exit Time</th><th>Exit Px</th><th>Impact</th>
            </tr></thead><tbody>${rows || '<tr><td colspan="8">No completed ATO cycles since Register.</td></tr>'}</tbody>${foot}</table>
          </div>`;


      } else if (page === "ato" || page === "buffer") {
        const [a, b, sum, p] = await Promise.all([
          api("/api/ato-status"),
          api("/api/buffer"),
          api("/api/trade-summary"),
          api("/api/poll"),
        ]);
        const open = sum.open || [];
        const openHtml = open.length
          ? open
              .map(
                (leg) => `<div class="ato-open-block">
              <div class="kv"><span>Side</span><b>${esc(leg.side)} ATO</b></div>
              <div class="kv"><span>Protect</span><b>${esc(leg.symbol)}</b></div>
              <div class="kv"><span>Strike</span><b>${esc(leg.protect_strike)}</b></div>
              <div class="kv"><span>Order</span><b>${esc(leg.order_id || "—")}</b></div>
              <div class="kv"><span>Status</span><b class="buy">OPEN</b></div>
            </div>`
              )
              .join("")
          : `<p class="sub ato-open-empty">No open ATO protect leg.</p>`;
        const pollOpts = (p.poll_options || [0, 1, 2, 3, 4, 5, 10, 15])
          .map((v) => `<option value="${v}" ${Number(p.poll_interval) === Number(v) ? "selected" : ""}>${v}s</option>`)
          .join("");
        const statusHtml = a.deployed === false
          ? `<p class="sub ato-open-empty">${esc(a.text || "No active deployment.")}</p>`
          : `<div class="ato-open-block ato-status-block">
              <div class="kv"><span>CE protect</span><b>${esc(a.ce_protect || "N/A")}</b></div>
              <div class="kv"><span>PE protect</span><b>${esc(a.pe_protect || "N/A")}</b></div>
              <div class="kv"><span>Manage</span><b>${esc(a.manage || "—")}</b></div>
            </div>`;
        view.innerHTML = `
          <header class="page-head"><h3>ATO MANAGER</h3></header>
          <div class="ato-mgr">
            <div class="card add-form ato-mgr-buf dep-card-green">
              <h4 class="sec-title">BUFFER MANAGER</h4>
              <div class="ato-buf-fields">
                <div class="field"><label class="ato-lab" for="ce_entry">CE ENTRY</label><input id="ce_entry" type="number" inputmode="decimal" autocomplete="off" name="ato-ce-entry" placeholder="${esc(b.ce_entry_placeholder || "Nifty Level")}" value="${esc(b.ce_entry)}" /></div>
                <div class="field"><label class="ato-lab" for="ce_retrace">CE EXIT</label><input id="ce_retrace" type="number" inputmode="decimal" autocomplete="off" name="ato-ce-exit" placeholder="${esc(b.ce_retrace_placeholder || "Nifty Level")}" value="${esc(b.ce_retrace)}" /></div>
                <div class="field"><label class="ato-lab" for="pe_entry">PE ENTRY</label><input id="pe_entry" type="number" inputmode="decimal" autocomplete="off" name="ato-pe-entry" placeholder="${esc(b.pe_entry_placeholder || "Nifty Level")}" value="${esc(b.pe_entry)}" /></div>
                <div class="field"><label class="ato-lab" for="pe_retrace">PE EXIT</label><input id="pe_retrace" type="number" inputmode="decimal" autocomplete="off" name="ato-pe-exit" placeholder="${esc(b.pe_retrace_placeholder || "Nifty Level")}" value="${esc(b.pe_retrace)}" /></div>
              </div>
              <button type="button" class="btn btn-green" id="bufSave">SAVE</button>
              <p class="sub" id="bufMsg"></p>
            </div>
            <div class="card ato-mgr-status dep-card-blue">
              <h4 class="sec-title">ATO STATUS</h4>
              <div class="ato-status-wrap">${statusHtml}</div>
              <h4 class="sec-title ato-open-title">OPEN ATO</h4>
              <div class="ato-open-wrap">${openHtml}</div>
            </div>
            <div class="card add-form ato-mgr-poll dep-card-red">
              <h4 class="sec-title">POLL INTERVAL</h4>
              <div class="field"><select id="pollSel">${pollOpts}</select></div>
              <button type="button" class="btn btn-red" id="pollSave">SAVE</button>
              <p class="sub" id="pollMsg"></p>
            </div>
          </div>`;
        wireAtoMgrHandlers();
      } else if (page === "legs") {
        page = "home";
        document.querySelectorAll("[data-go]").forEach((el) => {
          el.classList.toggle("on", el.getAttribute("data-go") === "home");
        });
        return render();
      } else if (page === "poll") {
        page = "ato";
        document.querySelectorAll("[data-go]").forEach((el) => {
          el.classList.toggle("on", el.getAttribute("data-go") === "ato");
        });
        return render();

      } else if (page === "register") {
        const d = await api("/api/register");
        renderRegister(view, d);
        finishPageRender("register", view, { register: d }, navT0);
        return;
      } else if (page === "deploy" || page === "complete") {
        if (page === "complete") {
          page = "deploy";
          document.querySelectorAll("[data-go]").forEach((el) => {
            el.classList.toggle("on", el.getAttribute("data-go") === "deploy");
          });
        }
        const [d, c] = await Promise.all([
          api("/api/deploy"),
          api("/api/complete", { method: "POST", body: "{}" }),
        ]);
        view.innerHTML = `
          <header class="page-head"><h3>DEPLOY / COMPLETE</h3></header>
          <div class="dep-complete">
            <div class="card add-form dep-card-green">
              <h4 class="sec-title">DEPLOY BATMAN 2.0</h4>
              <p class="sub dep-card-sub">Preview the legs below, then confirm to place them.</p>
              <div class="dep-top-row">
                <div class="field dep-top-field"><label class="ato-lab">EXPIRY WEEK</label>
                  <select id="depExpiry">
                    ${(d.expiry_options || []).map((o) => `<option value="${esc(o.iso)}" ${d.expiry === o.iso ? "selected" : ""}>${esc(o.label)}</option>`).join("")}
                  </select>
                </div>
                <div class="field dep-top-field"><label class="ato-lab">NIFTY CENTER</label><input id="depLevel" type="number" placeholder="${esc(d.placeholder_level || "NIFTY level")}" value="${esc(d.level || "")}" /></div>
                <div class="field dep-top-field"><label class="ato-lab">LOTS</label><input id="depLots" type="number" placeholder="Lots" value="${esc(d.lots || 1)}" /></div>
                <div class="dep-top-action">
                  <label class="ato-lab dep-top-action-label">&nbsp;</label>
                  <button type="button" class="btn btn-green-outline" id="depPrev">PREVIEW LEGS</button>
                </div>
              </div>
                          <div class="dep-out" id="depOut"></div>
              <div class="row2 dep-confirm-row">
                <button type="button" class="btn btn-green" id="depGo">CONFIRM DEPLOY ONLY</button>
                <button type="button" class="btn btn-green" id="depGoReg">CONFIRM DEPLOY AND REGISTER</button>
              </div>
              <p class="sub" id="depMsg"></p>
            </div>
            <div class="card add-form dep-card-red dep-exit-card">
              <h4 class="sec-title">EXIT ALL POSITIONS</h4>
              <div class="complete-pre" id="exitMsg">Exits every open position immediately after you confirm.</div>
              <button type="button" class="btn btn-red" id="exitAllBtn">CONFIRM EXIT</button>
            </div>
            <div class="card add-form dep-card-red dep-done-card">
              <h4 class="sec-title">COMPLETE BATMAN</h4>
              <p class="sub dep-card-sub">End this deployment safely</p>
              <div class="complete-pre" id="doneMsg">${esc(c.text || c.error || "")}</div>
              <button type="button" class="btn btn-red" id="doneYes">CONFIRM COMPLETE</button>
            </div>
          </div>`;
        wireDeployHandlers();
      } else if (page === "payoff") {
        const d = await api("/api/payoff");
        const legs = d.legs || [];
        const pts = d.points || [];
        const spot = d.spot;
        const be = (d.breakevens || []).map((x) => Number(x).toFixed(0)).join(" · ") || "—";
        const maxP = d.max_profit == null ? "—" : fmtPnl(d.max_profit);
        const maxL = d.max_loss == null ? "—" : fmtPnl(d.max_loss);
        const atm = d.atm;
        view.innerHTML = `
          <header class="page-head payoff-head"><h3>PAYOFF</h3></header>
          <div class="payoff-page">
            <div class="payoff-stats">
              <div class="card home-chip-card"><kbd>SPOT</kbd><b>${spot == null ? "—" : Number(spot).toFixed(2)}</b></div>
              <div class="card home-chip-card"><kbd>ATM</kbd><b>${atm == null ? "—" : Number(atm).toFixed(0)}</b></div>
              <div class="card home-chip-card"><kbd>MAX PROFIT*</kbd><b class="buy">${esc(maxP)}</b></div>
              <div class="card home-chip-card"><kbd>MAX LOSS*</kbd><b class="sell">${esc(maxL)}</b></div>
              <div class="card home-chip-card payoff-be"><kbd>BREAKEVENS*</kbd><b>${esc(be)}</b></div>
            </div>
            <div class="card payoff-chart-card">
              <div class="payoff-chart-top">
                <h4 class="sec-title">EXPIRY PAYOFF</h4>
                <span class="sub payoff-sub">ATM ± 10 strikes · spot at center</span>
              </div>
              <div class="payoff-chart-wrap">
                <svg id="payoffSvg" class="payoff-svg" viewBox="0 0 1000 420" preserveAspectRatio="none" role="img" aria-label="Payoff chart"></svg>
              </div>
            </div>
          </div>`;
        pageMeta = { points: pts, spot: spot, atm: atm, step: d.step || 50 };
        wirePayoffChart(pageMeta);

      } else if (page === "alerts") {
        const d = await api("/api/alerts?limit=200");
        const rows = (d.alerts || []).slice().reverse();
        const body = rows.length
          ? rows.map((a) => {
              const sev = String(a.severity || "orange");
              return `<tr>
                <td>${esc(a.ts || "")}</td>
                <td class="sev-${esc(sev)}">${esc(a.category || "")}</td>
                <td>${esc(a.alert || "")}</td>
                <td class="alert-log">${esc(a.log || "")}</td>
              </tr>`;
            }).join("")
          : `<tr><td colspan="4">No alerts yet today.</td></tr>`;
        view.innerHTML = `
          <header class="page-head"><h3>ALERT LOGS</h3></header>
          <div class="card hist-wrap">
            <table class="hist-table"><thead><tr>
              <th>Time</th><th>Category</th><th>Alert</th><th>Full log</th>
            </tr></thead><tbody>${body}</tbody></table>
          </div>`;
      } else if (page === "token") {
        await renderTokenPage(view);
      }
      if (page === "ato" || page === "buffer") page = "ato";
      if (page === "status" || page === "summary" || page === "overnight" || page === "ato" || page === "deploy" || page === "payoff" || page === "token" || page === "alerts" || page === "positions") {
        finishPageRender(page, view, pageMeta, navT0);
      } else {
        playViewIn(view);
      }
    } catch (err) {
      view.innerHTML = `<p class="sub" style="color:var(--sell)">${esc(err.message)}</p>`;
    } finally {
      setBusy(false);
    }
  }

  function closeMenu() {
    const side = $("sideNav") || document.querySelector(".side");
    const scrim = $("navScrim");
    const btn = $("menuBtn");
    if (side) side.classList.remove("open");
    if (scrim) scrim.classList.remove("on");
    document.body.classList.remove("nav-open");
    if (btn) btn.setAttribute("aria-expanded", "false");
  }

  function openMenu() {
    const side = $("sideNav") || document.querySelector(".side");
    const scrim = $("navScrim");
    const btn = $("menuBtn");
    if (side) side.classList.add("open");
    if (scrim) scrim.classList.add("on");
    document.body.classList.add("nav-open");
    if (btn) btn.setAttribute("aria-expanded", "true");
  }

  function toggleMenu() {
    const side = $("sideNav") || document.querySelector(".side");
    if (side && side.classList.contains("open")) closeMenu();
    else openMenu();
  }

  function bindGo(root) {
    root.querySelectorAll("[data-go]").forEach((el) => {
      el.addEventListener("click", () => go(el.dataset.go));
    });
  }

  let brokerAcctPainted = false;

  function paintBrokerAcct(me) {
    const z = (me && me.zerodha) || {};
    const d = (me && me.dhan) || {};
    const kiteId = String(z.user_id || "").trim();
    const kiteName = String(z.name || "").trim();
    const kiteOn = !!(z.present || kiteId || kiteName);
    const dhanId = String(d.client_id || d.client_code || "").trim();
    const dhanOn = !!d.present;
    const useKite = kiteOn || !dhanOn;
    const broker = useKite ? "Kite" : "Dhan";
    const name = useKite ? kiteName : String(d.name || "").trim();
    const uid = useKite ? (kiteId || "STE992") : dhanId;
    const active = useKite ? kiteOn : dhanOn;
    const wrap = $("brokerAcct");
    const nameEl = $("brokerAcctName");
    const brokerEl = $("brokerAcctBroker");
    const idEl = $("brokerAcctId");
    const sep1 = $("brokerAcctSep1");
    const sep2 = $("brokerAcctSep2");
    const statusEl = $("brokerAcctStatus");
    if (!wrap || !nameEl || !idEl) return;
    nameEl.textContent = name;
    nameEl.style.display = name ? "" : "none";
    if (brokerEl) {
      brokerEl.textContent = broker;
      brokerEl.style.display = "";
    }
    idEl.textContent = uid || "—";
    idEl.style.display = uid ? "" : "none";
    if (sep1) sep1.style.display = name && broker ? "" : "none";
    if (sep2) sep2.style.display = broker && uid ? "" : "none";
    if (statusEl) {
      statusEl.style.display = "";
      statusEl.classList.toggle("is-active", active);
      statusEl.classList.toggle("is-inactive", !active);
      statusEl.title = active ? (broker + " connected") : (broker + " off");
      statusEl.setAttribute("aria-label", active ? "Connected" : "Disconnected");
    }
    wrap.hidden = false;
    brokerAcctPainted = true;
  }

  async function loadBrokerAcct() {
    if (brokerAcctPainted) return;
    try {
      const me = await api("/api/me");
      paintBrokerAcct(me);
    } catch (_) {}
  }

  function showDesk() {
    $("login").classList.add("hidden");
    $("desk").classList.remove("hidden");
    $("desk").classList.remove("desk-in");
    void $("desk").offsetWidth;
    $("desk").classList.add("desk-in");
    $("view").innerHTML = skeleton();
    loadBrokerAcct();
    go("home");
    startWs();
    if (!clockTimer) {
      tickClock();
      clockTimer = setInterval(tickClock, 1000);
    }
  }


  function applyTheme(mode) {
    const t = mode === "dark" ? "dark" : "light";
    document.documentElement.setAttribute("data-theme", t);
    try { localStorage.setItem("kavach-theme", t); } catch (_) {}
    const meta = document.querySelector('meta[name="theme-color"]');
    if (meta) meta.setAttribute("content", t === "dark" ? "#0F172A" : "#7C6AE8");
    document.querySelectorAll(".theme-switch input").forEach((inp) => {
      inp.checked = t === "dark";
      const lab = inp.closest(".theme-switch");
      if (!lab) return;
      lab.setAttribute("aria-checked", t === "dark" ? "true" : "false");
      lab.setAttribute("aria-label", t === "dark" ? "Switch to light theme" : "Switch to dark theme");
      lab.title = t === "dark" ? "Dark theme" : "Light theme";
    });
  }
  function bindThemeToggles() {
    document.querySelectorAll(".theme-switch input").forEach((inp) => {
      if (inp.dataset.bound) return;
      inp.dataset.bound = "1";
      inp.addEventListener("change", () => {
        applyTheme(inp.checked ? "dark" : "light");
      });
    });
    let start = document.documentElement.getAttribute("data-theme") || "light";
    try {
      const saved = localStorage.getItem("kavach-theme");
      if (saved === "dark" || saved === "light") start = saved;
    } catch (_) {}
    applyTheme(start);
  }
  bindThemeToggles();

  function playLockThenLogin() {
    $("desk").classList.add("hidden");
    const scene = $("lockScene");
    const logo = document.querySelector(".logo-hero");
    if (logo) logo.classList.remove("drop-in");
    scene.classList.remove("is-on");
    void scene.offsetWidth;
    scene.classList.add("is-on");
    scene.setAttribute("aria-hidden", "false");
    const wait = reduceMotion() ? 700 : 3400;
    setTimeout(() => {
      scene.classList.remove("is-on");
      scene.setAttribute("aria-hidden", "true");
      if (logo) {
        void logo.offsetWidth;
        logo.classList.add("drop-in");
      }
      $("login").classList.remove("hidden");
      $("pw").value = "";
      $("loginErr").textContent = "";
    }, wait);
  }

  function startWs() {
    const proto = location.protocol === "https:" ? "wss" : "ws";
    let ws;
    const connect = () => {
      try { ws = new WebSocket(proto + "://" + location.host + "/ws/state"); }
      catch (_) { setTimeout(connect, 2000); return; }
      ws.onmessage = (ev) => {
        try { applyChrome(JSON.parse(ev.data)); } catch (_) {}
      };
      ws.onclose = () => setTimeout(connect, 2000);
      ws.onerror = () => { try { ws.close(); } catch (_) {} };
    };
    connect();
  }

  document.querySelectorAll(".nav, .tabbar span").forEach((el) => {
    if (el.id === "logoutBtn") return;
    if (el.hasAttribute("data-menu")) {
      el.addEventListener("click", () => toggleMenu());
      return;
    }
    el.addEventListener("click", () => go(el.dataset.go));
  });
  const menuBtn = $("menuBtn");
  if (menuBtn) menuBtn.addEventListener("click", () => toggleMenu());
  const navScrim = $("navScrim");
  if (navScrim) navScrim.addEventListener("click", () => closeMenu());
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") closeMenu();
  });


  async function flipRun(wantResume) {
    toggling = true;
    try {
      setBusy(true);
      const r = await api(wantResume ? "/api/resume" : "/api/pause", { method: "POST", body: "{}" });
      if (!r.ok) throw new Error(r.error || "failed");
      live.paused = !wantResume;
      applyChrome(live);
      if (wantResume) setGoNotice("WEAPONS HOT", "ok");
      else setGoNotice("WEAPONS COLD", "paused");
    } catch (err) {
      const run = $("runToggle");
      if (run) run.checked = !wantResume;
      applyChrome(live);
      toast(err.message, false);
    } finally {
      toggling = false;
      setBusy(false);
    }
  }

  async function flipHedge(on) {
    toggling = true;
    try {
      setBusy(true);
      const r = await api("/api/dyn-hedge", { method: "POST", body: JSON.stringify({ enabled: on }) });
      if (r.ok === false) throw new Error(r.error || "failed");
      live.dyn_hedge = on;
      applyChrome(live);
      toastResult(r, true);
    } catch (err) {
      const h = $("hedgeToggle");
      if (h) h.checked = !on;
      applyChrome(live);
      toast(err.message, false);
    } finally {
      toggling = false;
      setBusy(false);
    }
  }

  $("runToggle").addEventListener("change", (e) => {
    flipRun(!!e.target.checked);
  });
  $("hedgeToggle").addEventListener("change", (e) => {
    flipHedge(!!e.target.checked);
  });
  bindPnlExitControls();

  $("logoutBtn").addEventListener("click", async () => {
    closeMenu();
    invalidatePageCache();
    try {
      await api("/api/logout", { method: "POST", body: "{}" });
    } catch (_) {}
    playLockThenLogin();
  });

  $("loginBtn").addEventListener("click", async () => {
    toast("");
    $("loginErr").textContent = "";
    try {
      setBusy(true);
      await api("/api/login", {
        method: "POST",
        body: JSON.stringify({ password: $("pw").value }),
      });
      unlockAudio();
      if (!_welcomePlayed) { _welcomePlayed = true; playAtoClip("welcome"); }
      showDesk();
    } catch (e) {
      $("loginErr").textContent = e.message;
    } finally {
      setBusy(false);
    }
  });
  $("pw").addEventListener("keydown", (e) => {
    if (e.key === "Enter") $("loginBtn").click();
  });

  const viewEl = $("view");
  if (viewEl) {
    viewEl.addEventListener(
      "scroll",
      () => {
        const main = document.querySelector(".main");
        if (!main || reduceMotion()) return;
        main.style.setProperty("--paray", viewEl.scrollTop * 0.18 + "px");
      },
      { passive: true }
    );
  }

  function isStandalone() {
    return window.matchMedia("(display-mode: standalone)").matches
      || window.navigator.standalone === true;
  }

  function isIos() {
    const ua = navigator.userAgent || "";
    return /iPhone|iPad|iPod/i.test(ua)
      || (navigator.platform === "MacIntel" && navigator.maxTouchPoints > 1);
  }

  function setInstallHint(text) {
    const el = $("installHint");
    if (el) el.textContent = text || "";
  }

  if (isStandalone()) {
    document.body.classList.add("standalone");
    const hint = $("installHint");
    const btn = $("installBtn");
    if (hint) hint.textContent = "Running as app";
    if (btn) btn.classList.add("hidden");
  } else if (isIos()) {
    setInstallHint("iPhone / iPad: tap Share, then Add to Home Screen. Open that icon to hide the address bar.");
  } else if (location.protocol !== "https:") {
    setInstallHint("Open the HTTPS link once, then tap Install as app. That opens Kavach with no address bar.");
  } else {
    setInstallHint("Install as app to hide the address bar. Chrome menu → Install Kavach, or tap the button below.");
    const btn = $("installBtn");
    if (btn) btn.classList.remove("hidden");
  }

  if (location.protocol === "https:" && "serviceWorker" in navigator) {
    navigator.serviceWorker.register("/sw.js", { scope: "/" }).catch(() => {});
  }

  let deferredPrompt = null;
  window.addEventListener("beforeinstallprompt", (e) => {
    e.preventDefault();
    deferredPrompt = e;
    const btn = $("installBtn");
    if (btn && !isStandalone()) btn.classList.remove("hidden");
    setInstallHint("Tap Install as app. Kavach will open in its own window with no address bar.");
  });

  const installBtn = $("installBtn");
  if (installBtn) {
    installBtn.addEventListener("click", async () => {
      if (deferredPrompt) {
        deferredPrompt.prompt();
        try { await deferredPrompt.userChoice; } catch (e) {}
        deferredPrompt = null;
        installBtn.classList.add("hidden");
        return;
      }
      if (isIos()) {
        setInstallHint("Safari only: tap the Share button, then Add to Home Screen.");
        return;
      }
      setInstallHint("Use the Chrome menu (three dots) → Install Kavach / Add to Home Screen.");
    });
  }

  window.addEventListener("appinstalled", () => {
    const btn = $("installBtn");
    if (btn) btn.classList.add("hidden");
    setInstallHint("Installed. Open Kavach from the app icon — no address bar.");
  });

  api("/api/me")
    .then((me) => {
      paintBrokerAcct(me);
      showDesk();
    })
    .catch(() => {});
})();
