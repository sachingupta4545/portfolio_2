const PROD_API_BASE = "https://resume-chatbot-904427517105.us-central1.run.app";
const DEV_API_BASE  = "http://localhost:8000";
const API_BASE = (window.location.hostname === 'localhost' || window.location.hostname === '127.0.0.1')
    ? DEV_API_BASE
    : PROD_API_BASE;

// ── Spinner CSS (injected once) ──────────────────────────────────
const styleEl = document.createElement("style");
styleEl.textContent = `@keyframes spin { to { transform: rotate(360deg); } }`;
document.head.appendChild(styleEl);

// ── Tab Switching ────────────────────────────────────────────────
const tabResume  = document.getElementById("tab-resume");
const tabProject = document.getElementById("tab-project");
const panelResume  = document.getElementById("panel-resume");
const panelProject = document.getElementById("panel-project");
const resultCard   = document.getElementById("result-card");

function switchTab(tab) {
    if (tab === "resume") {
        tabResume.classList.add("active");
        tabProject.classList.remove("active");
        tabResume.setAttribute("aria-selected", "true");
        tabProject.setAttribute("aria-selected", "false");
        panelResume.hidden  = false;
        panelProject.hidden = true;
    } else {
        tabProject.classList.add("active");
        tabResume.classList.remove("active");
        tabProject.setAttribute("aria-selected", "true");
        tabResume.setAttribute("aria-selected", "false");
        panelResume.hidden  = true;
        panelProject.hidden = false;
    }
    resultCard.hidden = true;
}

tabResume.addEventListener("click",  () => switchTab("resume"));
tabProject.addEventListener("click", () => switchTab("project"));

// ── Schema Hint Toggle (Project Panel) ──────────────────────────
const schemaToggle = document.getElementById("schema-toggle-btn");
const schemaBody   = document.getElementById("schema-body");

schemaToggle.addEventListener("click", () => {
    const open = schemaBody.hidden;
    schemaBody.hidden = !open;
    schemaToggle.setAttribute("aria-expanded", String(open));
});
schemaToggle.addEventListener("keydown", (e) => {
    if (e.key === "Enter" || e.key === " ") { e.preventDefault(); schemaToggle.click(); }
});

// ── Shared Utilities ─────────────────────────────────────────────
function formatBytes(bytes) {
    if (bytes < 1024) return bytes + " B";
    if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + " KB";
    return (bytes / (1024 * 1024)).toFixed(2) + " MB";
}

function spinnerSvg() {
    return `<svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24"
      fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"
      style="animation:spin 1s linear infinite"><path d="M21 12a9 9 0 1 1-6.219-8.56"/></svg>`;
}

// ─────────────────────────────────────────────────────────────────
// RESUME PANEL
// ─────────────────────────────────────────────────────────────────
const resumeDropZone   = document.getElementById("resume-drop-zone");
const resumeFileInput  = document.getElementById("resume-file-input");
const resumeBrowse     = document.getElementById("resume-browse");
const resumeFilePreview = document.getElementById("resume-file-preview");
const resumeFileName   = document.getElementById("resume-file-name");
const resumeFileSize   = document.getElementById("resume-file-size");
const resumeRemove     = document.getElementById("resume-remove");
const resumeUploadBtn  = document.getElementById("resume-upload-btn");
const resumeProgress   = document.getElementById("resume-progress");
const resumeProgressFill  = document.getElementById("resume-progress-fill");
const resumeProgressLabel = document.getElementById("resume-progress-label");
const replaceToggle    = document.getElementById("replace-toggle");

let resumeFile = null;

function showResumeFile(file) {
    resumeFile = file;
    resumeFileName.textContent = file.name;
    resumeFileSize.textContent = formatBytes(file.size);
    resumeFilePreview.hidden = false;
    resumeDropZone.hidden = true;
    resumeUploadBtn.disabled = false;
}
function clearResumeFile() {
    resumeFile = null;
    resumeFileInput.value = "";
    resumeFilePreview.hidden = true;
    resumeDropZone.hidden = false;
    resumeUploadBtn.disabled = true;
}

resumeDropZone.addEventListener("click", () => resumeFileInput.click());
resumeBrowse.addEventListener("click", (e) => { e.stopPropagation(); resumeFileInput.click(); });
resumeFileInput.addEventListener("change", () => { if (resumeFileInput.files[0]) showResumeFile(resumeFileInput.files[0]); });
resumeRemove.addEventListener("click", clearResumeFile);

resumeDropZone.addEventListener("dragover", (e) => { e.preventDefault(); resumeDropZone.classList.add("dragover"); });
["dragleave","dragend"].forEach(ev => resumeDropZone.addEventListener(ev, () => resumeDropZone.classList.remove("dragover")));
resumeDropZone.addEventListener("drop", (e) => {
    e.preventDefault();
    resumeDropZone.classList.remove("dragover");
    const file = e.dataTransfer.files[0];
    if (!file) return;
    if (!/\.(pdf|md|txt)$/i.test(file.name)) { showResultError("Only PDF, MD, or TXT files are supported.", "Invalid File"); return; }
    showResumeFile(file);
});

resumeUploadBtn.addEventListener("click", async () => {
    if (!resumeFile) return;
    if (resumeFile.size > 5 * 1024 * 1024) { showResultError("File exceeds the 5 MB limit.", "File Too Large"); return; }

    resumeUploadBtn.disabled = true;
    resumeUploadBtn.innerHTML = `${spinnerSvg()} Processing...`;
    resumeProgress.hidden = false;

    let prog = 0;
    const iv = setInterval(() => {
        prog = Math.min(prog + Math.random() * 10, 82);
        resumeProgressFill.style.width = prog + "%";
        resumeProgressLabel.textContent =
            prog < 30 ? "Uploading file..." :
            prog < 55 ? "Extracting text & metadata..." :
            "Running AI extraction (may take ~15s)...";
    }, 450);

    try {
        const fd = new FormData();
        fd.append("file", resumeFile);
        fd.append("replace_existing", replaceToggle.checked ? "true" : "false");

        const res  = await fetch(`${API_BASE}/api/upload-resume`, { method: "POST", body: fd });
        clearInterval(iv);
        resumeProgressFill.style.width = "100%";
        resumeProgressLabel.textContent = "Done!";
        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || "Upload failed.");
        await delay(350);
        showResumeSuccess(data);
    } catch (err) {
        clearInterval(iv);
        showResultError(err.message, "Resume Upload Failed");
    } finally {
        resumeUploadBtn.innerHTML = `<svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="16 16 12 12 8 16"/><line x1="12" y1="12" x2="12" y2="21"/><path d="M20.39 18.39A5 5 0 0 0 18 9h-1.26A8 8 0 1 0 3 16.3"/></svg> Upload & Process Resume`;
    }
});

// ─────────────────────────────────────────────────────────────────
// PROJECT PANEL
// ─────────────────────────────────────────────────────────────────
const projectDropZone    = document.getElementById("project-drop-zone");
const projectFileInput   = document.getElementById("project-file-input");
const projectBrowse      = document.getElementById("project-browse");
const projectFilePreview = document.getElementById("project-file-preview");
const projectFileName    = document.getElementById("project-file-name");
const projectFileSize    = document.getElementById("project-file-size");
const projectRemove      = document.getElementById("project-remove");
const projectUploadBtn   = document.getElementById("project-upload-btn");
const projectProgress    = document.getElementById("project-progress");
const projectProgressFill  = document.getElementById("project-progress-fill");
const projectProgressLabel = document.getElementById("project-progress-label");

let projectFile = null;

function showProjectFile(file) {
    projectFile = file;
    projectFileName.textContent = file.name;
    projectFileSize.textContent = formatBytes(file.size);
    projectFilePreview.hidden = false;
    projectDropZone.hidden = true;
    projectUploadBtn.disabled = false;
}
function clearProjectFile() {
    projectFile = null;
    projectFileInput.value = "";
    projectFilePreview.hidden = true;
    projectDropZone.hidden = false;
    projectUploadBtn.disabled = true;
}

projectDropZone.addEventListener("click", () => projectFileInput.click());
projectBrowse.addEventListener("click", (e) => { e.stopPropagation(); projectFileInput.click(); });
projectFileInput.addEventListener("change", () => { if (projectFileInput.files[0]) showProjectFile(projectFileInput.files[0]); });
projectRemove.addEventListener("click", clearProjectFile);

projectDropZone.addEventListener("dragover", (e) => { e.preventDefault(); projectDropZone.classList.add("dragover"); });
["dragleave","dragend"].forEach(ev => projectDropZone.addEventListener(ev, () => projectDropZone.classList.remove("dragover")));
projectDropZone.addEventListener("drop", (e) => {
    e.preventDefault();
    projectDropZone.classList.remove("dragover");
    const file = e.dataTransfer.files[0];
    if (!file) return;
    if (!/\.(pdf|md|txt)$/i.test(file.name)) { showResultError("Only PDF, MD, or TXT files are supported.", "Invalid File"); return; }
    showProjectFile(file);
});

projectUploadBtn.addEventListener("click", async () => {
    if (!projectFile) return;
    if (projectFile.size > 10 * 1024 * 1024) { showResultError("File exceeds the 10 MB limit.", "File Too Large"); return; }

    projectUploadBtn.disabled = true;
    projectUploadBtn.innerHTML = `${spinnerSvg()} Ingesting project...`;
    projectProgress.hidden = false;

    let prog = 0;
    const iv = setInterval(() => {
        prog = Math.min(prog + Math.random() * 8, 78);
        projectProgressFill.style.width = prog + "%";
        projectProgressLabel.textContent =
            prog < 25 ? "Uploading file..." :
            prog < 50 ? "Extracting project details..." :
            "Building architecture & logic chunks (may take ~20s)...";
    }, 450);

    try {
        const fd = new FormData();
        fd.append("file", projectFile);

        const res  = await fetch(`${API_BASE}/api/upload-project`, { method: "POST", body: fd });
        clearInterval(iv);
        projectProgressFill.style.width = "100%";
        projectProgressLabel.textContent = "Done!";
        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || "Upload failed.");
        await delay(350);
        showProjectSuccess(data);
    } catch (err) {
        clearInterval(iv);
        showResultError(err.message, "Project Upload Failed");
    } finally {
        projectUploadBtn.innerHTML = `<svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="16 16 12 12 8 16"/><line x1="12" y1="12" x2="12" y2="21"/><path d="M20.39 18.39A5 5 0 0 0 18 9h-1.26A8 8 0 1 0 3 16.3"/></svg> Ingest Project into AI`;
    }
});

// ─────────────────────────────────────────────────────────────────
// RESULT RENDERERS
// ─────────────────────────────────────────────────────────────────
const resultStatusIcon = document.getElementById("result-status-icon");
const resultBody       = document.getElementById("result-body");
const uploadAnotherBtn = document.getElementById("upload-another-btn");

function hideAllPanels() {
    panelResume.hidden  = true;
    panelProject.hidden = true;
    resultCard.hidden   = false;
}

function showResumeSuccess(data) {
    hideAllPanels();
    const meta = data.extracted_metadata || {};
    const skillsHtml = buildTagCloud(meta.key_skills, "skill-tag");
    const techHtml   = buildTechToolsTable(meta.tools_and_technologies);
    const projectsHtml = buildProjectsList(meta.notable_projects);

    resultStatusIcon.innerHTML = successHeader("Resume Processed! 🎉", data.message || "Your resume is now stored.");
    resultBody.innerHTML = `
        <div class="chunks-badge">
            <svg xmlns="http://www.w3.org/2000/svg" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"/></svg>
            ${data.chunks_processed} chunks stored in Qdrant
        </div>
        <div class="meta-grid" style="margin-top:14px">
            ${metaItem("Candidate", meta.candidate_name)}
            ${metaItem("Experience", meta.total_experience_years != null ? meta.total_experience_years + " years" : null)}
            ${metaItem("Latest Role", meta.current_or_last_role)}
            ${metaItem("Education", meta.education)}
            ${meta.summary ? `<div class="meta-item full-width"><p class="meta-label">AI Summary</p><p class="meta-value" style="line-height:1.55">${meta.summary}</p></div>` : ""}
            ${key_skills_present(meta.key_skills, skillsHtml)}
            ${techHtml ? `<div class="meta-item full-width"><p class="meta-label">Tech Breakdown</p>${techHtml}</div>` : ""}
            ${projectsHtml ? `<div class="meta-item full-width"><p class="meta-label">Notable Projects</p>${projectsHtml}</div>` : ""}
        </div>`;
}

function showProjectSuccess(data) {
    hideAllPanels();
    resultStatusIcon.innerHTML = successHeader("Project Ingested! 🚀", `"${data.project_name}" is now in your AI's knowledge base.`);
    resultBody.innerHTML = `
        <div class="chunks-badge">
            <svg xmlns="http://www.w3.org/2000/svg" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"/></svg>
            ${data.chunks_processed} sub-chunks stored in Qdrant
        </div>
        <div class="sub-chunks-list" style="margin-top:12px">
            ${subChunkItem("Overview, Features & Tech Stack")}
            ${subChunkItem("Architecture, DB Design & API Design")}
            ${subChunkItem("Core Logic, Challenges & Operations")}
        </div>
        <div class="meta-grid" style="margin-top:14px">
            <div class="meta-item full-width">
                <p class="meta-label">Project Name</p>
                <p class="meta-value">${data.project_name}</p>
            </div>
            <div class="meta-item full-width">
                <p class="meta-label">What's next?</p>
                <p class="meta-value" style="color:var(--text-muted);font-size:0.82rem;line-height:1.5">
                    You can upload more projects — each one is appended separately. Then ask the chatbot
                    technical questions like "What was the architecture flow for ${data.project_name}?"
                </p>
            </div>
        </div>`;
}

function showResultError(message, title = "Error") {
    hideAllPanels();
    resumeProgress.hidden  = true;
    projectProgress.hidden = true;
    resumeProgressFill.style.width  = "0%";
    projectProgressFill.style.width = "0%";
    resultStatusIcon.innerHTML = `
        <div class="result-icon error">
            <svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
        </div>
        <div><p class="result-title">${title}</p><p class="result-subtitle">${message}</p></div>`;
    resultBody.innerHTML = "";
}

// "Upload Another" restores the active tab's panel
uploadAnotherBtn.addEventListener("click", () => {
    resultCard.hidden = true;
    const activeTab = tabResume.classList.contains("active") ? "resume" : "project";
    if (activeTab === "resume") {
        panelResume.hidden = false;
        clearResumeFile();
        resumeProgress.hidden = true;
        resumeProgressFill.style.width = "0%";
    } else {
        panelProject.hidden = false;
        clearProjectFile();
        projectProgress.hidden = true;
        projectProgressFill.style.width = "0%";
    }
});

// ─────────────────────────────────────────────────────────────────
// TEMPLATE HELPERS
// ─────────────────────────────────────────────────────────────────
function delay(ms) { return new Promise(r => setTimeout(r, ms)); }

function successHeader(title, subtitle) {
    return `
        <div class="result-icon success">
            <svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"/></svg>
        </div>
        <div><p class="result-title">${title}</p><p class="result-subtitle">${subtitle}</p></div>`;
}

function metaItem(label, value) {
    if (!value) return "";
    return `<div class="meta-item"><p class="meta-label">${label}</p><p class="meta-value">${value}</p></div>`;
}

function key_skills_present(skills, skillsHtml) {
    if (!Array.isArray(skills) || !skills.length) return "";
    return `<div class="meta-item full-width"><p class="meta-label">Key Skills</p>${skillsHtml}</div>`;
}

function buildTagCloud(arr, className = "skill-tag") {
    if (!Array.isArray(arr) || !arr.length) return `<span style="color:var(--text-muted);font-size:0.8rem">Not detected</span>`;
    return `<div class="skills-list">${arr.map(s => `<span class="${className}">${s}</span>`).join("")}</div>`;
}

function buildTechToolsTable(tools) {
    if (!tools || typeof tools !== "object") return "";
    const labels = { languages:"Languages", frameworks:"Frameworks", libraries:"Libraries",
                     databases:"Databases", devops:"DevOps", cloud:"Cloud",
                     testing:"Testing", design:"Design", other:"Other" };
    const rows = Object.entries(labels)
        .filter(([k]) => Array.isArray(tools[k]) && tools[k].length)
        .map(([k, label]) => `
            <div style="margin-bottom:6px">
                <span style="font-size:0.7rem;font-weight:700;text-transform:uppercase;letter-spacing:0.06em;color:var(--text-muted)">${label}: </span>
                <span style="font-size:0.8rem;color:var(--text-main)">${tools[k].join(", ")}</span>
            </div>`).join("");
    return rows ? `<div style="margin-top:6px">${rows}</div>` : "";
}

function buildProjectsList(projects) {
    if (!Array.isArray(projects) || !projects.length) return "";
    return projects.map(p => `
        <div style="margin-bottom:8px;padding-bottom:8px;border-bottom:1px solid var(--glass-border)">
            <strong style="font-size:0.87rem">${p.name || "Unnamed"}</strong><br>
            <span style="font-size:0.78rem;color:var(--text-muted)">${p.description || ""}</span>
            ${p.tech_stack?.length ? `<div style="margin-top:4px">${p.tech_stack.slice(0,6).map(t=>`<span class="skill-tag" style="font-size:0.68rem">${t}</span>`).join(" ")}</div>` : ""}
        </div>`).join("");
}

function subChunkItem(label) {
    return `<div class="sub-chunk-item">
        <svg xmlns="http://www.w3.org/2000/svg" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"/></svg>
        <span>${label}</span>
    </div>`;
}
