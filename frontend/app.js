/* ArtMirror 画镜 — 应用公共脚本：顶部导航注入与文本/评分工具 */
(function () {
  var ICON_SUN = '<svg viewBox="0 0 24 24" width="17" height="17" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/></svg>';
  var ICON_MOON = '<svg viewBox="0 0 24 24" width="17" height="17" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 12.8A9 9 0 1 1 11.2 3 7 7 0 0 0 21 12.8z"/></svg>';

  function navHTML(active) {
    var links = [
      { href: "gallery.html", key: "gallery", text: "图库" },
      { href: "settings.html", key: "settings", text: "设置" },
    ];
    var items = links.map(function (l) {
      return '<a class="nav-link' + (l.key === active ? " active" : "") + '" href="' + l.href + '">' + l.text + "</a>";
    }).join("");
    return '<nav><span class="brand"><span class="dot">🖼</span>画镜 <span class="dot" style="font-size:12px;color:var(--text-3)">ArtMirror</span></span>' +
      items +
      '<span class="nav-spacer"></span>' +
      '<button id="theme-toggle" class="theme-toggle" title="切换明暗模式" aria-label="切换明暗模式"></button></nav>';
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
    applyTheme(document.documentElement.getAttribute("data-theme") === "dark" ? "light" : "dark");
  }

  function initNav(active) {
    var host = document.getElementById("topnav");
    if (host) host.innerHTML = navHTML(active);
    applyTheme(currentTheme());
    var t = document.getElementById("theme-toggle");
    if (t) t.addEventListener("click", toggleTheme);
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

  window.App = { initNav: initNav, starHTML: starHTML, highlight: highlight, fmtSize: fmtSize };
})();