import { app } from "../../scripts/app.js";

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
}

app.registerExtension({
  name: "ArtMirror.Tab",
  async setup() {
    if (app.extensionManager?.registerSidebarTab) {
      app.extensionManager.registerSidebarTab({
        id: "artmirror-gallery",
        title: "图库",
        type: "custom",
        render: mountArtMirror,
      });
    } else if (app.extensionManager?.registerBottomPanelTab) {
      app.extensionManager.registerBottomPanelTab({
        id: "artmirror-gallery",
        title: "图库",
        type: "custom",
        render: mountArtMirror,
      });
    }
  },
});
