/* ArtMirror 画镜 — 应用公共脚本：顶部导航注入与文本/评分工具 */
(function () {
  var ICON_SUN = '<svg viewBox="0 0 24 24" width="17" height="17" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/></svg>';
  var ICON_MOON = '<svg viewBox="0 0 24 24" width="17" height="17" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 12.8A9 9 0 1 1 11.2 3 7 7 0 0 0 21 12.8z"/></svg>';
  // 画镜品牌图标：抠图后的银色画框 + 玻璃 + 羽毛笔（多尺寸输出，详见 frontend/assets/icons/）
  var ICON_LOGO = '<img class="brand-icon" src="assets/icons/icon-32.png" width="22" height="22" alt="" aria-hidden="true" />';

  function navHTML(active) {
    var links = [
      { href: "gallery.html", key: "gallery", text: "图库" },
      { href: "settings.html", key: "settings", text: "设置" },
    ];
    var items = links.map(function (l) {
      return '<a class="nav-link' + (l.key === active ? " active" : "") + '" href="' + l.href + '">' + l.text + "</a>";
    }).join("");
    return '<nav><span class="brand">' + ICON_LOGO + '画镜 <span class="dot" style="font-size:12px;color:var(--text-3)">ArtMirror</span></span>' +
      items +
      '<span class="nav-spacer"></span>' +
      '<button id="theme-toggle" class="theme-toggle" data-tip="切换明暗模式" aria-label="切换明暗模式"></button></nav>';
  }

  function currentTheme() {
    return localStorage.getItem("am-theme") || "light";
  }

  function applyTheme(t) {
    document.documentElement.setAttribute("data-theme", t);
    localStorage.setItem("am-theme", t);
    var btn = document.getElementById("theme-toggle");
    if (btn) btn.innerHTML = t === "dark" ? ICON_SUN : ICON_MOON;
  }

  function toggleTheme() {
    var next = document.documentElement.getAttribute("data-theme") === "dark" ? "light" : "dark";
    // 亮/暗切换：优先用 View Transitions 从右上角按钮处圆形扩散至全屏
    if (document.startViewTransition) {
      try {
        document.startViewTransition(function () { applyTheme(next); });
        return;
      } catch (e) {}
    }
    applyTheme(next); // 不支持时降级为直接切换
  }

  function initNav(active) {
    var host = document.getElementById("topnav");
    if (host) host.innerHTML = navHTML(active);
    applyTheme(currentTheme());
    var t = document.getElementById("theme-toggle");
    if (t) t.addEventListener("click", toggleTheme);
    // 导航链接：非当前页点击走淡出跳转（页面间跳转淡入淡出）
    if (host) {
      var cur = location.pathname.split("/").pop() || "index.html";
      host.querySelectorAll("a.nav-link").forEach(function (a) {
        a.addEventListener("click", function (e) {
          var href = a.getAttribute("href");
          if (href === cur) { e.preventDefault(); return; }
          e.preventDefault();
          go(href);
        });
      });
    }
  }

  // 页面间跳转：先淡出当前页再跳转（目标页加载时自动淡入）
  function go(url) {
    var body = document.body;
    if (!body) { location.href = url; return; }
    body.classList.add("am-page-out");
    setTimeout(function () { location.href = url; }, 180);
  }

  // 星级（人工评分）
  function starHTML(rating, interactive, onClick) {
    var stars = "";
    for (var i = 1; i <= 5; i++) {
      var on = i <= Math.round(rating || 0);
      var cls = on ? "" : "off";
      if (interactive) {
        stars += '<span class="star' + (on ? "" : " on") + '" data-v="' + i + '" style="cursor:pointer">★</span>';
      } else {
        stars += '<span class="' + cls + '">★</span>';
      }
    }
    return '<span class="stars">' + stars + "</span>";
  }

  // 关键词高亮
  function highlight(text, terms) {
    if (!text) return "";
    if (!terms || !terms.length) return escapeHTML(text);
    var lower = text.toLowerCase();
    var found = terms.filter(function (t) { return t && lower.indexOf(t.toLowerCase()) >= 0; });
    if (!found.length) return escapeHTML(text);
    var esc = escapeHTML(text);
    found.forEach(function (t) {
      var re = new RegExp("(" + escapeReg(t) + ")", "ig");
      esc = esc.replace(re, "<mark>$1</mark>");
    });
    return esc;
  }

  function escapeHTML(s) {
    return String(s).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }
  function escapeReg(s) { return String(s).replace(/[.*+?^${}()|[\]\\]/g, "\\$&"); }

  function fmtSize(bytes) {
    if (!bytes) return "0 B";
    var u = ["B", "KB", "MB", "GB"], i = 0, v = bytes;
    while (v >= 1024 && i < u.length - 1) { v /= 1024; i++; }
    return v.toFixed(v >= 10 || i === 0 ? 0 : 1) + " " + u[i];
  }

  var _toastTimer = null;
  function toast(msg) {
    var el = document.getElementById("am-toast");
    if (!el) {
      el = document.createElement("div");
      el.id = "am-toast";
      el.className = "am-toast";
      document.body.appendChild(el);
    }
    el.textContent = msg;
    el.classList.add("show");
    clearTimeout(_toastTimer);
    _toastTimer = setTimeout(function () { el.classList.remove("show"); }, 1400);
  }

  // 可靠复制：优先异步剪贴板，非安全上下文/拒绝时回退 execCommand；执行后给反馈
  function copyText(text) {
    text = text == null ? "" : String(text);
    function legacy() {
      try {
        var ta = document.createElement("textarea");
        ta.value = text;
        ta.style.position = "fixed";
        ta.style.top = "-9999px";
        ta.style.left = "-9999px";
        document.body.appendChild(ta);
        ta.focus();
        ta.select();
        var ok = document.execCommand("copy");
        document.body.removeChild(ta);
        toast(ok ? "已复制" : "复制失败");
      } catch (e) { toast("复制失败"); }
    }
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(text).then(function () { toast("已复制"); }, legacy);
    } else {
      legacy();
    }
  }

  window.App = { initNav: initNav, starHTML: starHTML, highlight: highlight, fmtSize: fmtSize, copyText: copyText, toast: toast, go: go };
})();