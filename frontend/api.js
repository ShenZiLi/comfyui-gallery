/* ArtMirror 画镜 — API 层（优先对接后端 REST；离线/双击打开时回退 mock） */
(function () {
  function clone(x) { return JSON.parse(JSON.stringify(x)); }
  function ok(data) { return Promise.resolve(clone(data)); }

  // 规范化提示词（分组键，与后端一致）
  function normalizePrompt(p) {
    return String(p || "").toLowerCase().replace(/\s+/g, " ").trim();
  }

  function req(path, opts) {
    opts = opts || {};
    var init = { method: opts.method || "GET", headers: { "Content-Type": "application/json" } };
    if (opts.body) init.body = JSON.stringify(opts.body);
    return fetch(path, init).then(function (r) {
      if (!r.ok) throw new Error("HTTP " + r.status);
      return r.json();
    });
  }

  var Api = {
    _fallback: false,

    listFolders: function () {
      return req("api/folders").catch(function () {
        Api._fallback = true;
        return ok(window.Mock.getFolders());
      });
    },

    listTags: function () {
      return req("api/tags").catch(function () {
        Api._fallback = true;
        var set = {};
        window.Mock.getImages().forEach(function (im) { (im.tags || []).forEach(function (t) { set[t.name] = t; }); });
        return ok(Object.values(set));
      });
    },

    listImages: function (opts) {
      opts = opts || {};
      var qs = [];
      if (opts.folderId) qs.push("folderId=" + opts.folderId);
      if (opts.tag) qs.push("tag=" + encodeURIComponent(opts.tag));
      if (opts.q) qs.push("q=" + encodeURIComponent(opts.q));
      qs.push("sort=" + (opts.sort || "ai"));
      return req("api/images?" + qs.join("&")).catch(function () {
        Api._fallback = true;
        return ok(window.Mock.getImages());
      });
    },

    getImage: function (id) {
      return req("api/images/" + id).catch(function () {
        Api._fallback = true;
        return ok(window.Mock.getImage(id) || {});
      });
    },

    aggregateByPrompt: function (opts) {
      opts = opts || {};
      return req("api/aggregate/by-prompt?kind=" + (opts.kind || "exact")).catch(function () {
        Api._fallback = true;
        return ok(buildMockGroups(opts.kind === "similar"));
      });
    },

    dimensionGroups: function () {
      return req("api/aggregate/dimensions").catch(function () {
        Api._fallback = true;
        return ok(buildMockDim());
      });
    },

    getSettings: function () {
      return req("api/settings").catch(function () {
        Api._fallback = true;
        return ok({ scanRoots: [], llm: { vendor: "deepseek", baseUrl: "", apiKey: "", visionModel: "", textModel: "", embedModel: "" } });
      });
    },

    updateSettings: function (body) {
      return req("api/settings", { method: "POST", body: body }).catch(function () {
        throw new Error("后端未连接");
      });
    },

    // ---- 图片目录管理与目录浏览器 ----
    listFsRoots: function () {
      return req("api/fs/roots").catch(function () {
        Api._fallback = true;
        return ok([{ name: "~", path: "/", isDir: true }]);
      });
    },
    listFsDir: function (path) {
      return req("api/fs/list?path=" + encodeURIComponent(path || "")).catch(function () {
        Api._fallback = true;
        return ok({ path: path || "/", parent: "", items: [] });
      });
    },
    addRoot: function (path) {
      return req("api/settings/roots", { method: "POST", body: { path: path } }).catch(function () {
        throw new Error("后端未连接");
      });
    },
    removeRoot: function (path) {
      return req("api/settings/roots", { method: "DELETE", body: { path: path } }).catch(function () {
        throw new Error("后端未连接");
      });
    },
    getSyncVersion: function () {
      return req("api/sync/version").then(function (d) { return d.version; }).catch(function () { return 0; });
    },
  };

  // ---- mock 分组回退 ----
  function buildMockGroups(similar) {
    var map = {};
    window.Mock.getImages().forEach(function (im) {
      var key = normalizePrompt(im.prompt);
      if (!key) return;
      (map[key] = map[key] || []).push(im);
    });
    return Object.keys(map).map(function (key) {
      var members = map[key].slice().sort(function (a, b) { return (b.aiRating || 0) - (a.aiRating || 0); });
      return {
        id: key, title: members[0].prompt, kind: similar ? "similar" : "exact", count: members.length,
        maxScore: members[0].aiRating || 0, cover: members[0],
        samples: similar ? [members[0].prompt] : [], members: members,
      };
    });
  }
  function buildMockDim() {
    var out = [];
    ["model", "lora", "vae", "style"].forEach(function (cat) {
      var items = {};
      window.Mock.getImages().forEach(function (im) {
        (im.tags || []).filter(function (t) { return t.category === cat; })
          .forEach(function (t) { (items[t.name] = items[t.name] || []).push(im); });
      });
      var arr = Object.keys(items).map(function (name) { return { name: name, category: cat, count: items[name].length, members: items[name] }; });
      if (arr.length) out.push({ category: cat, items: arr });
    });
    return out;
  }

  window.Api = Api;
})();