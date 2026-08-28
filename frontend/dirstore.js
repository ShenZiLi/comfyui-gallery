/* ArtMirror 画镜 — 导入保存目录句柄存取（IndexedDB 持久化，跨设置/图库页共享）
 *
 * 用 File System Access API（showDirectoryPicker）选择本地目录并拿到
 * FileSystemDirectoryHandle；该句柄保存在 IndexedDB，供图库页拖拽导入时
 * 由浏览器直写所选本地目录（弹出授权），从而绕开服务端写权限限制。
 */
(function () {
  var DB = "artmirror-dirs", STORE = "dirs", KEY = "import";

  function openDB() {
    return new Promise(function (resolve, reject) {
      var req = indexedDB.open(DB, 1);
      req.onupgradeneeded = function () {
        if (!req.result.objectStoreNames.contains(STORE)) {
          req.result.createObjectStore(STORE);
        }
      };
      req.onsuccess = function () { resolve(req.result); };
      req.onerror = function () { reject(req.error); };
    });
  }

  var DirStore = {
    // 是否支持文件系统访问（仅部分 Chromium 支持）
    supported: function () { return typeof window.showDirectoryPicker === "function"; },

    saveHandle: function (handle) {
      return openDB().then(function (db) {
        return new Promise(function (resolve, reject) {
          var tx = db.transaction(STORE, "readwrite");
          tx.objectStore(STORE).put(handle, KEY);
          tx.oncomplete = function () { resolve(); };
          tx.onerror = function () { reject(tx.error); };
        });
      });
    },

    getHandle: function () {
      return openDB().then(function (db) {
        return new Promise(function (resolve, reject) {
          var tx = db.transaction(STORE, "readonly");
          var req = tx.objectStore(STORE).get(KEY);
          req.onsuccess = function () { resolve(req.result || null); };
          req.onerror = function () { reject(req.error); };
        });
      });
    },

    clear: function () {
      return openDB().then(function (db) {
        return new Promise(function (resolve, reject) {
          var tx = db.transaction(STORE, "readwrite");
          tx.objectStore(STORE).delete(KEY);
          tx.oncomplete = function () { resolve(); };
          tx.onerror = function () { reject(tx.error); };
        });
      });
    },
  };

  window.DirStore = DirStore;
})();