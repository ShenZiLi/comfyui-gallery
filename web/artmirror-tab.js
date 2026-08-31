import { app } from "../../scripts/app.js";

// 记录所有 ArtMirror iframe，供拖拽期间的穿透处理使用
const artmirrorFrames = [];

function mountArtMirror(el) {
  // ComfyUI 0.33+ sidebar tab 内容区为 flex 子项，未必会传 height: 100% 给孙子。
  // 强制让父容器占满可填空间，iframe 自身用 absolute 撑满父容器，避免被外层尺寸压缩成一小条。
  el.style.position = "relative";
  el.style.width = "100%";
  el.style.height = "100%";
  el.style.minHeight = "0";
  el.style.flex = "1 1 auto";
  el.style.overflow = "hidden";

  const iframe = document.createElement("iframe");
  iframe.src = "/artmirror/gallery.html";
  iframe.style.position = "absolute";
  iframe.style.inset = "0";
  iframe.style.width = "100%";
  iframe.style.height = "100%";
  iframe.style.border = "0";
  iframe.setAttribute("allow", "clipboard-read; clipboard-write");
  el.appendChild(iframe);
  artmirrorFrames.push(iframe);
}

function patchDragThroughIframe() {
  // 面板整块被 iframe 填充时，向左缩小面板会让鼠标移进 iframe 区域，
  // 快速拖动时 mousemove 被 iframe 吞掉、ComfyUI 分隔条收不到 → 拖动脱手。
  // 方案：抓取分隔条（col-resize 的 gutter）按下时，临时把 iframe 设为
  // pointer-events:none 让事件穿透回父页面，松手后恢复。
  let dragging = false;
  const restore = () => {
    dragging = false;
    for (const f of artmirrorFrames) f.style.pointerEvents = "";
  };
  const isSplitter = (t) => {
    const el = t instanceof Element ? t : null;
    if (!el) return false;
    if (el.closest(".p-splitter-gutter, .p-splitter-gutter-handle")) return true;
    const cls = (el.className && el.className.baseVal !== undefined ? el.className.baseVal : el.className) || "";
    return /gutter|col-resize|splitter/i.test(String(cls)) || getComputedStyle(el).cursor === "col-resize";
  };
  window.addEventListener("mousedown", (e) => {
    if (isSplitter(e.target)) {
      dragging = true;
      for (const f of artmirrorFrames) f.style.pointerEvents = "none";
    }
  });
  window.addEventListener("mouseup", () => {
    if (dragging) restore();
  });
  const drop = () => {
    if (dragging) restore();
  };
  window.addEventListener("blur", drop);
  window.addEventListener("mouseleave", drop);
}

function unlockSidebarMinWidth() {
  // ComfyUI 核心给共享侧边栏面板加了 min-width:312px（类 min-w-78），
  // 导致图库等 tab 只能向右放大、向左拖到 312px 后无法继续缩小。
  // 这里覆写共享面板的 min-width，让侧边栏能自由左右缩放（仅插件侧改动）。
  const style = document.createElement("style");
  style.textContent = ".side-bar-panel { min-width: 0 !important; }";
  document.head.appendChild(style);
}

app.registerExtension({
  name: "ArtMirror.Tab",
  async setup() {
    unlockSidebarMinWidth();
    patchDragThroughIframe();

    if (app.extensionManager?.registerSidebarTab) {
      app.extensionManager.registerSidebarTab({
        id: "artmirror-gallery",
        title: "图库",
        icon: "pi pi-image",
        tooltip: "ArtMirror 图库",
        type: "custom",
        render: mountArtMirror,
      });
    } else if (app.extensionManager?.registerBottomPanelTab) {
      app.extensionManager.registerBottomPanelTab({
        id: "artmirror-gallery",
        title: "图库",
        icon: "pi pi-image",
        tooltip: "ArtMirror 图库",
        type: "custom",
        render: mountArtMirror,
      });
    }
  },
});
