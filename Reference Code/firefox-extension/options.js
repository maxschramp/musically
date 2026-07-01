const $ = (id) => document.getElementById(id);

async function load() {
  const { email, password, defaultQuality, targetSubfolder } = await browser.storage.local.get([
    "email",
    "password",
    "defaultQuality",
    "targetSubfolder",
  ]);
  if (email) $("email").value = email;
  if (password) $("password").value = password;
  if (defaultQuality === "mp3" || defaultQuality === "flac") {
    $("defaultQuality").value = defaultQuality;
  }
  if (targetSubfolder) $("targetSubfolder").value = targetSubfolder;
}

$("save").addEventListener("click", async () => {
  await browser.storage.local.set({
    email: $("email").value.trim(),
    password: $("password").value,
    defaultQuality: $("defaultQuality").value,
    targetSubfolder: $("targetSubfolder").value.trim(),
  });
  const s = $("status");
  s.textContent = "Saved.";
  setTimeout(() => { s.textContent = ""; }, 1500);
});

load();
