/* ArtMirror 画镜 — 应用公共脚本：顶部导航注入与文本/评分工具 */
(function () {
  function navHTML(active) {
    var links = [
      { href: "gallery.html", key: "gallery", text: "图库" },
      { href: "aggregate.html", key: "aggregate", text: "提示词聚合" },
      { href: "settings.html", key: "settings", text: "设置" },
    ];
    var items = links.map(function (l) {
      return '<a class="nav-link' + (l.key === active ? " active" : "") + '" href="' + l.href + '">' + l.text + "</a>";
    }).join("");
    return '<nav><span class="brand"><span class="dot">🖼</span>画镜 <span class="dot" style="font-size:12px;color:var(--text-3)">ArtMirror</span></span>' +
      items +
      '<span class="nav-spacer"></span>' +
      '<span class="muted" id="nav-status" style="color:var(--text-3);font-size:12px"></span></nav>';
  }

  function initNav(active) {
    var host = document.getElementById("topnav");
    if (host) host.innerHTML = navHTML(active);
    var s = document.getElementById("nav-status");
    if (s) {
      // 尝试探测后端是否已就绪
      fetch("api/health").then(function (r) { return r.json(); }).then(function (d) {
        s.textContent = d.status === "ok" ? "后端已连接 · 真实数据" : "原型 · mock 数据";
      }).catch(function () {
        s.textContent = "原型 · mock 数据";
      });
    }
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