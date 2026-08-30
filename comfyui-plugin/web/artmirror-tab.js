import { app } from "../../scripts/app.js";

function mountArtMirror(el) {
  const iframe = document.createElement("iframe");
  iframe.src = "/artmirror/gallery.html";
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
