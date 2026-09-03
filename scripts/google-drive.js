(() => {
  const FOLDER_ID = "1XjxskHzqZeVhhCx4HTe00mWWRuH2Sdnc";
  const FOLDER_VIEW = "grid";
  const frame = document.getElementById("gd-frame");
  const placeholder = document.getElementById("gd-placeholder");
  const openButton = document.getElementById("gd-open-btn");
  const fallbackUrl = "https://drive.google.com/drive/my-drive";
  const isConfigured = FOLDER_ID && FOLDER_ID !== "FOLDER_ID_HERE";

  if (!frame || !placeholder || !openButton) return;

  if (!isConfigured) {
    frame.hidden = true;
    placeholder.hidden = false;
    openButton.href = fallbackUrl;
    return;
  }

  const embeddedUrl =
    "https://drive.google.com/embeddedfolderview?id=" +
    encodeURIComponent(FOLDER_ID) +
    "&hl=ru#" +
    encodeURIComponent(FOLDER_VIEW);
  const folderUrl =
    "https://drive.google.com/drive/folders/" +
    encodeURIComponent(FOLDER_ID);
  const chooserUrl =
    "https://accounts.google.com/AccountChooser?continue=" +
    encodeURIComponent(folderUrl) +
    "&service=writely";

  frame.src = embeddedUrl;
  openButton.href = chooserUrl;
})();
