"use strict";

const $ = (id) => document.getElementById(id);
const token = document.querySelector('meta[name="local-token"]').content;
const rates = [64, 96, 128, 160, 192, 256, 320];
const qualities = [
  ["Для речи", "Компактный файл для голосовых записей, лекций и подкастов."],
  ["Экономное", "Небольшой файл для подкастов и повседневных записей."],
  ["Стандартное", "Хороший баланс размера и качества для большинства записей."],
  ["Хорошее", "Чистый звук для музыки с умеренным размером файла."],
  ["Оптимальное", "Сбалансированное качество для музыки и повседневного прослушивания."],
  ["Высокое", "Больше деталей в музыке, больше размер готового файла."],
  ["Максимальное", "Самый высокий битрейт. Качество зависит также от оригинала."],
];
const rows = new Map();
let uploading = false;
let polling = false;
let disconnected = false;
let stopped = false;
const activeStates = new Set(["queued", "converting", "uploading"]);

function icon(name) {
  return `<svg class="icon" aria-hidden="true"><use href="#i-${name}"/></svg>`;
}

function bytes(size) {
  if (size < 1000) return `${size} Б`;
  const unit = size >= 1e9 ? "ГБ" : size >= 1e6 ? "МБ" : "КБ";
  const divisor = size >= 1e9 ? 1e9 : size >= 1e6 ? 1e6 : 1000;
  return `${(size / divisor).toLocaleString("ru-RU", { maximumFractionDigits: 2 })} ${unit}`;
}

function notice(message = "") {
  $("notice").textContent = message;
  $("notice").hidden = !message;
}

async function api(path, options = {}) {
  const response = await fetch(path, {
    ...options,
    headers: { "X-Local-Token": token, ...options.headers },
  });
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || "Не удалось выполнить действие.");
  return data;
}

function downloadUrl(path) {
  const url = new URL(path, location.origin);
  url.searchParams.set("token", token);
  return url.href;
}

function qualityChanged() {
  const index = Number($("quality").value);
  $("bitrate").textContent = rates[index];
  $("quality-label").textContent = qualities[index][0];
  $("quality-description").textContent = qualities[index][1];
  $("estimate").textContent = `${(rates[index] * 60 / 8000).toLocaleString("ru-RU", { maximumFractionDigits: 2 })} МБ`;
  $("quality").style.setProperty("--fill", `${index / 6 * 100}%`);
  $("quality").setAttribute("aria-valuetext", `${rates[index]} кбит/с, ${qualities[index][0]}`);
}

function makeRow(row) {
  const element = document.createElement("div");
  element.className = "file-row";
  element.setAttribute("role", "listitem");
  // All filenames and messages below are assigned through textContent.
  element.innerHTML = `<div class="file-mark">${icon("file")}</div>
    <div class="file-detail"><p class="file-name"></p><div class="file-meta"><span class="file-size"></span><span>·</span><span class="file-state"></span></div>
    <div class="file-progress" role="progressbar" aria-label="Прогресс конвертации" aria-valuemin="0" aria-valuemax="100" hidden><span></span></div><p class="error-message" hidden></p></div>
    <div class="file-actions"><button class="icon-button retry" hidden>${icon("arrow")}</button><a class="icon-button download" hidden>${icon("download")}</a><button class="icon-button remove">${icon("close")}</button></div>`;
  row.element = element;
  element.querySelector(".remove").addEventListener("click", () => removeRow(row));
  element.querySelector(".retry").addEventListener("click", () => {
    row.id = null;
    row.status = "pending";
    row.error = "";
    row.progress = 0;
    render();
  });
  $("file-list").append(element);
}

function render() {
  if (stopped) return;
  const all = [...rows.values()];
  const active = all.filter((row) => activeStates.has(row.status));
  const pending = all.filter((row) => row.status === "pending");
  const done = all.filter((row) => row.status === "done");
  for (const row of all) {
    if (!row.element) makeRow(row);
    const element = row.element;
    const name = row.status === "done" ? row.output_name : row.name;
    element.querySelector(".file-name").textContent = name;
    element.querySelector(".file-name").title = name;
    element.querySelector(".file-size").textContent = row.status === "done"
      ? `${bytes(row.source_size)} → ${bytes(row.output_size)} · ${row.bitrate} кбит/с`
      : bytes(row.source_size);
    const states = {
      pending: "Ожидает запуска", uploading: `Передача ${row.progress || 0}%`,
      queued: "В очереди", converting: `Конвертация ${row.progress || 0}%`,
      done: "Готово", error: "Ошибка", cancelled: "Отменено", expired: "Срок хранения истёк",
    };
    const state = element.querySelector(".file-state");
    state.textContent = states[row.status] || row.status;
    state.className = `file-state ${row.status}`;
    const progress = element.querySelector(".file-progress");
    progress.hidden = !activeStates.has(row.status);
    progress.setAttribute("aria-valuenow", row.progress || 0);
    progress.firstElementChild.style.width = `${row.progress || 0}%`;
    const error = element.querySelector(".error-message");
    error.textContent = row.error || "";
    error.hidden = !row.error;
    const link = element.querySelector(".download");
    link.hidden = row.status !== "done";
    if (row.status === "done") link.href = downloadUrl(`/api/jobs/${row.id}/download`);
    link.setAttribute("aria-label", `Скачать ${name}`);
    link.title = "Скачать .m4a";
    const remove = element.querySelector(".remove");
    remove.disabled = row.status === "uploading" || row.removing;
    remove.setAttribute("aria-label", `${activeStates.has(row.status) ? "Отменить" : "Убрать"} ${row.name}`);
    remove.title = activeStates.has(row.status) ? "Отменить и убрать" : "Убрать из списка";
    const retry = element.querySelector(".retry");
    retry.hidden = !row.file || !["error", "cancelled", "expired"].includes(row.status);
    retry.setAttribute("aria-label", `Попробовать снова: ${row.name}`);
    retry.title = "Подготовить к повторной конвертации";
  }
  $("file-count").textContent = all.length;
  $("empty-hint").hidden = all.length > 0;
  $("queue-footer").hidden = all.length === 0;
  $("queue-summary").textContent = `${done.length} из ${all.length} готово · ${bytes(all.reduce((sum, row) => sum + row.source_size, 0))}`;
  $("clear-files").disabled = uploading;
  $("quality").disabled = uploading || active.length > 0;
  $("convert").disabled = uploading || pending.length === 0;
  $("convert").innerHTML = uploading
    ? '<span>Добавляем файлы в очередь…</span><span class="spinner" aria-hidden="true"></span>'
    : `<span>${pending.length > 0 ? `Конвертировать · ${pending.length}` : active.length > 0 ? "Конвертация идёт…" : done.length > 0 ? "Конвертация завершена" : "Конвертировать в .m4a"}</span>${active.length > 0 && !pending.length ? '<span class="spinner" aria-hidden="true"></span>' : icon("arrow")}`;
  $("button-note").textContent = active.length > 0 ? "Обработка файлов по очереди" : pending.length > 0
    ? `AAC · ${rates[Number($("quality").value)]} кбит/с · отдельный .m4a для каждого файла`
    : done.length > 0 ? "Сохраните файлы кнопкой ↓ или одним ZIP" : "Добавьте файлы, чтобы начать";
  $("download-all").hidden = done.length < 2;
  $("download-all").innerHTML = `${icon("download")} Скачать ZIP · ${done.length}`;
}

function addFiles(files) {
  if (stopped) return;
  notice();
  const warnings = [];
  for (const file of files) {
    if (rows.size >= 100) { warnings.push("В списке может быть до 100 файлов."); break; }
    if (!file.size) { warnings.push(`«${file.name}» пустой.`); continue; }
    if (file.size > 2 * 1024 ** 3) { warnings.push(`«${file.name}» превышает 2 ГБ.`); continue; }
    const duplicate = [...rows.values()].some((row) => row.file && row.file.name === file.name
      && row.file.size === file.size && row.file.lastModified === file.lastModified);
    if (duplicate) continue;
    const key = crypto.randomUUID();
    rows.set(key, { key, file, name: file.name, source_size: file.size, status: "pending", progress: 0 });
  }
  if (warnings.length) notice(warnings.join(" "));
  $("file-input").value = "";
  render();
}

async function removeRow(row) {
  if (row.status === "uploading" || row.removing) return;
  row.removing = true;
  render();
  try {
    if (row.id && row.status !== "expired") await api(`/api/jobs/${row.id}`, { method: "DELETE" });
    rows.delete(row.key);
    row.element?.remove();
  } catch (error) {
    notice(`Не удалось отменить файл: ${error.message}`);
  } finally {
    row.removing = false;
    render();
  }
}

function uploadFile(row, bitrate) {
  return new Promise((resolve, reject) => {
    const data = new FormData();
    data.append("file", row.file);
    data.append("bitrate", bitrate);
    const xhr = new XMLHttpRequest();
    xhr.open("POST", "/api/jobs");
    xhr.setRequestHeader("X-Local-Token", token);
    xhr.upload.onprogress = (event) => {
      if (event.lengthComputable) {
        row.progress = Math.round(event.loaded / event.total * 100);
        render();
      }
    };
    xhr.onload = () => {
      try {
        const result = JSON.parse(xhr.responseText);
        if (xhr.status >= 400) reject(new Error(result.error || "Ошибка передачи файла."));
        else resolve(result);
      } catch {
        reject(new Error("Не удалось передать файл. Проверьте, работает ли локальный сервер."));
      }
    };
    xhr.onerror = () => reject(new Error("Нет связи с локальным сервером. Проверьте окно запуска."));
    xhr.send(data);
  });
}

async function convert() {
  if (uploading || stopped) return;
  uploading = true;
  notice();
  const bitrate = rates[Number($("quality").value)];
  const batch = [...rows.values()].filter((row) => row.status === "pending");
  render();
  try {
    for (const row of batch) {
      if (stopped) break;
      if (!rows.has(row.key)) continue;
      row.status = "uploading";
      row.progress = 0;
      render();
      try {
        Object.assign(row, await uploadFile(row, bitrate));
      } catch (error) {
        row.status = "error";
        row.error = error.message;
      }
      render();
    }
  } finally {
    uploading = false;
    render();
    poll();
  }
}

async function poll(restore = false) {
  if (polling || stopped) return;
  polling = true;
  try {
    const data = await api("/api/jobs");
    const jobs = new Map(data.jobs.map((job) => [job.id, job]));
    if (restore) for (const job of data.jobs) {
      const key = crypto.randomUUID();
      rows.set(key, { ...job, key });
    }
    for (const row of rows.values()) {
      if (!row.id) continue;
      if (jobs.has(row.id)) Object.assign(row, jobs.get(row.id));
      else {
        row.status = "expired";
        row.error = "Результат больше недоступен. Добавьте оригинал или попробуйте снова.";
      }
    }
    if (stopped) return;
    if (disconnected) { disconnected = false; notice(); }
    render();
  } catch (error) {
    if (stopped) return;
    disconnected = true;
    notice(`Нет связи с конвертером. ${error.message} Если сервер перезапущен, обновите страницу.`);
  } finally {
    polling = false;
  }
}

$("quality").addEventListener("input", () => { qualityChanged(); render(); });
$("add-files").addEventListener("click", () => $("file-input").click());
$("dropzone").addEventListener("click", () => $("file-input").click());
$("file-input").addEventListener("change", (event) => addFiles(event.target.files));
$("convert").addEventListener("click", convert);
$("clear-files").addEventListener("click", async () => {
  if (uploading) return;
  for (const row of [...rows.values()]) await removeRow(row);
});
$("download-all").addEventListener("click", () => {
  const ids = [...rows.values()].filter((row) => row.status === "done").map((row) => row.id);
  const link = document.createElement("a");
  link.href = downloadUrl(`/api/archive?ids=${ids.join(",")}`);
  link.click();
});

$("stop-converter")?.addEventListener("click", async () => {
  const button = $("stop-converter");
  button.disabled = true;
  try {
    await api("/api/shutdown", { method: "POST" });
    stopped = true;
    notice("Конвертер закрыт. Для запуска снова откройте приложение двойным щелчком.");
    document.querySelectorAll("button, input").forEach((control) => { control.disabled = true; });
    document.querySelectorAll(".download").forEach((link) => { link.removeAttribute("href"); });
  } catch (error) {
    button.disabled = false;
    notice(error.message);
  }
});

let dragDepth = 0;
document.addEventListener("dragover", (event) => event.preventDefault());
document.addEventListener("drop", (event) => {
  event.preventDefault();
  dragDepth = 0;
  $("dropzone").classList.remove("dragover");
  if (event.dataTransfer.files.length) addFiles(event.dataTransfer.files);
});
$("dropzone").addEventListener("dragenter", (event) => {
  event.preventDefault();
  dragDepth++;
  $("dropzone").classList.add("dragover");
});
$("dropzone").addEventListener("dragleave", () => {
  if (--dragDepth <= 0) { dragDepth = 0; $("dropzone").classList.remove("dragover"); }
});

qualityChanged();
render();
poll(true);
setInterval(() => {
  if (rows.size || disconnected) poll();
}, 1000);
