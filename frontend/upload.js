const PROD_API_BASE = "https://resume-chatbot-904427517105.us-central1.run.app";
const DEV_API_BASE = "http://localhost:8000";
const API_BASE = (window.location.hostname === 'localhost' || window.location.hostname === '127.0.0.1') 
    ? DEV_API_BASE 
    : PROD_API_BASE;

// Elements
const dropZone    = document.getElementById("drop-zone");
const fileInput   = document.getElementById("file-input");
const browseLink  = document.getElementById("browse-link");
const filePreview = document.getElementById("file-preview");
const fileName    = document.getElementById("file-name");
const fileSize    = document.getElementById("file-size");
const removeFile  = document.getElementById("remove-file");
const uploadBtn   = document.getElementById("upload-btn");
const progressWrap = document.getElementById("progress-wrap");
const progressFill = document.getElementById("progress-fill");
const progressLabel = document.getElementById("progress-label");
const resultCard  = document.getElementById("result-card");
const resultStatusIcon = document.getElementById("result-status-icon");
const resultBody  = document.getElementById("result-body");
const replaceToggle = document.getElementById("replace-toggle");
const uploadAnotherBtn = document.getElementById("upload-another-btn");
const uploadCard  = document.querySelector(".upload-card");

let selectedFile = null;

// ── File Selection Helpers ──────────────────────────────────────

function formatBytes(bytes) {
    if (bytes < 1024) return bytes + " B";
    if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + " KB";
    return (bytes / (1024 * 1024)).toFixed(2) + " MB";
}

function showFilePreview(file) {
    selectedFile = file;
    fileName.textContent = file.name;
    fileSize.textContent = formatBytes(file.size);
    filePreview.hidden = false;
    dropZone.hidden = true;
    uploadBtn.disabled = false;
}

function clearFile() {
    selectedFile = null;
    fileInput.value = "";
    filePreview.hidden = true;
    dropZone.hidden = false;
    uploadBtn.disabled = true;
}

// ── Event Listeners ────────────────────────────────────────────

dropZone.addEventListener("click", () => fileInput.click());
browseLink.addEventListener("click", (e) => { e.stopPropagation(); fileInput.click(); });

fileInput.addEventListener("change", () => {
    const file = fileInput.files[0];
    if (file) showFilePreview(file);
});

removeFile.addEventListener("click", clearFile);

// Drag & Drop
dropZone.addEventListener("dragover", (e) => {
    e.preventDefault();
    dropZone.classList.add("dragover");
});
["dragleave", "dragend"].forEach(ev =>
    dropZone.addEventListener(ev, () => dropZone.classList.remove("dragover"))
);
dropZone.addEventListener("drop", (e) => {
    e.preventDefault();
    dropZone.classList.remove("dragover");
    const file = e.dataTransfer.files[0];
    if (file) {
        if (!file.name.endsWith(".pdf")) {
            showError("Only PDF files are supported.", "Invalid File Type");
            return;
        }
        showFilePreview(file);
    }
});

// Upload Another button
uploadAnotherBtn.addEventListener("click", () => {
    resultCard.hidden = true;
    uploadCard.style.display = "flex";
    clearFile();
    progressWrap.hidden = true;
    progressFill.style.width = "0%";
    uploadBtn.disabled = true;
});

// ── Upload Logic ────────────────────────────────────────────────

uploadBtn.addEventListener("click", async () => {
    if (!selectedFile) return;

    if (selectedFile.size > 5 * 1024 * 1024) {
        showError("File size exceeds the 5MB limit.", "File Too Large");
        return;
    }

    // Animate button → progress
    uploadBtn.disabled = true;
    uploadBtn.innerHTML = `
        <svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="animation:spin 1s linear infinite"><path d="M21 12a9 9 0 1 1-6.219-8.56"/></svg>
        Processing...
    `;
    progressWrap.hidden = false;

    // Fake progressive bar during upload
    let fakeProgress = 0;
    const fakeInterval = setInterval(() => {
        fakeProgress = Math.min(fakeProgress + Math.random() * 12, 80);
        progressFill.style.width = fakeProgress + "%";
        if (fakeProgress < 30) progressLabel.textContent = "Uploading PDF...";
        else if (fakeProgress < 60) progressLabel.textContent = "Extracting text...";
        else progressLabel.textContent = "Running AI metadata extraction...";
    }, 400);

    try {
        const formData = new FormData();
        formData.append("file", selectedFile);
        formData.append("replace_existing", replaceToggle.checked ? "true" : "false");

        const response = await fetch(`${API_BASE}/api/upload-resume`, {
            method: "POST",
            body: formData,
        });

        clearInterval(fakeInterval);
        progressFill.style.width = "100%";
        progressLabel.textContent = "Done!";

        const data = await response.json();

        if (!response.ok) {
            throw new Error(data.detail || "Upload failed.");
        }

        await new Promise(r => setTimeout(r, 400));
        showSuccess(data);

    } catch (err) {
        clearInterval(fakeInterval);
        showError(err.message, "Upload Failed");
    }
});

// ── Result renderers ────────────────────────────────────────────

function showSuccess(data) {
    uploadCard.style.display = "none";
    resultCard.hidden = false;

    const meta = data.extracted_metadata || {};

    resultStatusIcon.innerHTML = `
        <div class="result-icon success">
            <svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"/></svg>
        </div>
        <div>
            <p class="result-title">Resume Processed!</p>
            <p class="result-subtitle">${data.message || "Your resume has been stored successfully."}</p>
        </div>
    `;

    const skillsHtml = Array.isArray(meta.key_skills) && meta.key_skills.length
        ? `<div class="skills-list">${meta.key_skills.map(s => `<span class="skill-tag">${s}</span>`).join("")}</div>`
        : "<span style='color:var(--text-muted);font-size:0.82rem'>Not detected</span>";

    const projectsHtml = Array.isArray(meta.notable_projects) && meta.notable_projects.length
        ? meta.notable_projects.map(p => `<div style="margin-bottom:6px"><strong>${p.name}</strong><br><span style="font-size:0.8rem;color:var(--text-muted)">${p.description}</span></div>`).join("")
        : "<span style='color:var(--text-muted);font-size:0.82rem'>Not detected</span>";

    resultBody.innerHTML = `
        <div class="chunks-badge">
            <svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polyline points="20 6 9 17 4 12"/></svg>
            ${data.chunks_processed} chunks stored in Qdrant
        </div>

        <div class="meta-grid" style="margin-top:16px">
            ${meta.candidate_name ? `
            <div class="meta-item">
                <p class="meta-label">Candidate</p>
                <p class="meta-value">${meta.candidate_name}</p>
            </div>` : ""}

            ${meta.total_experience_years != null ? `
            <div class="meta-item">
                <p class="meta-label">Experience</p>
                <p class="meta-value">${meta.total_experience_years} years</p>
            </div>` : ""}

            ${meta.current_or_last_role ? `
            <div class="meta-item">
                <p class="meta-label">Latest Role</p>
                <p class="meta-value">${meta.current_or_last_role}</p>
            </div>` : ""}

            ${meta.education ? `
            <div class="meta-item">
                <p class="meta-label">Education</p>
                <p class="meta-value">${meta.education}</p>
            </div>` : ""}

            ${meta.summary ? `
            <div class="meta-item full-width">
                <p class="meta-label">AI Summary</p>
                <p class="meta-value" style="line-height:1.5">${meta.summary}</p>
            </div>` : ""}

            <div class="meta-item full-width">
                <p class="meta-label">Key Skills</p>
                ${skillsHtml}
            </div>

            <div class="meta-item full-width">
                <p class="meta-label">Notable Projects</p>
                ${projectsHtml}
            </div>
        </div>
    `;
}

function showError(message, title = "Error") {
    uploadCard.style.display = "none";
    resultCard.hidden = false;

    // Reset progress
    progressWrap.hidden = true;
    progressFill.style.width = "0%";

    resultStatusIcon.innerHTML = `
        <div class="result-icon error">
            <svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
        </div>
        <div>
            <p class="result-title">${title}</p>
            <p class="result-subtitle">${message}</p>
        </div>
    `;
    resultBody.innerHTML = "";
}

// CSS animation for the spinner
const style = document.createElement("style");
style.textContent = `@keyframes spin { to { transform: rotate(360deg); } }`;
document.head.appendChild(style);
