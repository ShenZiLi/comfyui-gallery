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
      if (!r.ok) {
        return r.json().catch(function () { return {}; }).then(function (body) {
          var msg = (body && body.detail) || ("HTTP " + r.status);
          throw new Error(msg);
        });
      }
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

    toggleHiddenFolder: function (id) {
      return req("api/folders/" + id + "/toggle-hidden", { method: "POST" }).catch(function (e) {
        throw (e && e.message) ? e : new Error("操作失败");
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
      qs.push("limit=" + (opts.limit || 60));
      qs.push("offset=" + (opts.offset || 0));
      return req("api/images?" + qs.join("&")).catch(function () {
        Api._fallback = true;
        var all = window.Mock.getImages();
        var off = opts.offset || 0, lim = opts.limit || 60;
        return ok({
          items: all.slice(off, off + lim),
          total: all.length,
          limit: lim,
          offset: off,
          hasMore: off + lim < all.length
        });
      });
    },

    getImage: function (id) {
      return req("api/images/" + id).catch(function () {
        Api._fallback = true;
        return ok(window.Mock.getImage(id) || {});
      });
    },

    reparseModels: function (id) {
      return req("api/images/" + id + "/reparse-models", { method: "POST" }).catch(function (e) {
        throw e;
      });
    },

    reversePrompt: function (id) {
      return req("api/images/" + id + "/reverse", { method: "POST" }).catch(function (e) {
        throw e;
      });
    },

    translatePrompt: function (id, kind) {
      return req("api/images/" + id + "/translate", { method: "POST", body: { kind: kind } }).catch(function (e) {
        throw e;
      });
    },

    deleteImage: function (id) {
      return req("api/images/" + id, { method: "DELETE" }).catch(function (e) {
        throw e;
      });
    },

    scoreImage: function (id) {
      return req("api/images/" + id + "/score", { method: "POST" }).catch(function (e) {
        throw e;
      });
    },

    setRating: function (id, score) {
      return req("api/images/" + id + "/rating", { method: "POST", body: { score: score } }).catch(function (e) {
        throw e;
      });
    },

    aggregateByPrompt: function (opts) {
      opts = opts || {};
      var qs = [
        "kind=" + (opts.kind || "exact"),
        "limit=" + (opts.limit || 20),
        "offset=" + (opts.offset || 0)
      ];
      if (opts.folderId) qs.push("folder_id=" + encodeURIComponent(opts.folderId));
      return req("api/aggregate/by-prompt?" + qs.join("&")).catch(function () {
        Api._fallback = true;
        var g = buildMockGroups(opts.kind === "similar");
        var off = opts.offset || 0, lim = opts.limit || 20;
        return ok({
          items: g.slice(off, off + lim),
          total: g.length,
          limit: lim,
          offset: off,
          hasMore: off + lim < g.length
        });
      });
    },

    aggregateMembers: function (group, opts) {
      opts = opts || {};
      var qs = [
        "group=" + encodeURIComponent(group),
        "limit=" + (opts.limit || 24),
        "offset=" + (opts.offset || 0)
      ];
      if (opts.folderId) qs.push("folder_id=" + encodeURIComponent(opts.folderId));
      return req("api/aggregate/by-prompt/members?" + qs.join("&")).catch(function () {
        Api._fallback = true;
        var g = buildMockGroups(false).filter(function (x) { return x.id === group; })[0] || { members: [] };
        var off = opts.offset || 0, lim = opts.limit || 24;
        return ok({
          items: g.members.slice(off, off + lim),
          total: g.members.length,
          limit: lim,
          offset: off,
          hasMore: off + lim < g.members.length
        });
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
      return req("api/settings", { method: "POST", body: body }).catch(function (e) {
        throw (e && e.message) ? e : new Error("后端未连接");
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
    getHealth: function () {
      return req("api/health").catch(function () {
        Api._fallback = true;
        return ok({ status: "ok", app: "artmirror", version: "0.1.0" });
      });
    },
    uploadImages: function (files) {
      // 逐文件表单上传所有图片到导入保存目录；分批并发（每批 8），避免目录导入大量文件打满连接
      var list = Array.prototype.slice.call(files || []);
      var results = [];
      var up = function (f) {
        var fd = new FormData();
        fd.append("file", f);
        // 目录导入（webkitdirectory）：携带相对路径，后端保留目录结构落盘
        if (f.webkitRelativePath) fd.append("path", f.webkitRelativePath);
        return fetch("api/settings/upload", { method: "POST", body: fd }).then(function (r) {
          if (!r.ok) {
            return r.json().catch(function () { return {}; }).then(function (body) {
              var err = new Error((body && body.detail) || ("HTTP " + r.status));
              err.status = r.status;
              throw err;
            });
          }
          return r.json();
        });
      };
      var CHUNK = 8;
      function run(from) {
        if (from >= list.length) return Promise.resolve();
        var batch = list.slice(from, from + CHUNK);
        return Promise.all(batch.map(up)).then(function (rs) {
          results = results.concat(rs);
          return run(from + CHUNK);
        });
      }
      return run(0).then(function () {
        return { uploaded: results.length, paths: results.map(function (r) { return r.path; }) };
      }).catch(function (e) {
        if (!(e && e.status)) e.status = 0;
        throw (e && e.message) ? e : new Error("导入失败：后端未连接");
      });
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
        coverThumbs: members.slice(0, 6).map(function (m) { return { id: m.id, name: m.name, thumb: m.thumb }; }),
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