import * as THREE from 'three';
import * as GaussianSplats3D from '@mkkellogg/gaussian-splats-3d';

// ==========================================================
// 1. B2B BEVEILIGING: CRYPTO & RBAC AUTHENTICATIE
// ==========================================================
async function sha256(message) {
  const msgBuffer = new TextEncoder().encode(message);
  const hashBuffer = await crypto.subtle.digest('SHA-256', msgBuffer);
  const hashArray = Array.from(new Uint8Array(hashBuffer));
  return hashArray.map(b => b.toString(16).padStart(2, '0')).join('');
}

async function verifyAccess() {
  const authOverlay = document.getElementById('auth-overlay');
  const pinInput = document.getElementById('pin-input');
  const authForm = document.getElementById('auth-form');
  const authError = document.getElementById('auth-error-msg');

  let config = { pin_enabled: false };
  try {
    const res = await fetch('./config.json');
    if (res.ok) config = await res.json();
  } catch (e) {
    console.warn('Geen config.json gevonden, publieke modus actief.');
  }

  // Update branding in modal
  if (config.organization) {
    const modalOrg = document.getElementById('modal-org-name');
    if (modalOrg) modalOrg.textContent = config.organization;
    const sideOrg = document.getElementById('sidebar-org');
    if (sideOrg) sideOrg.textContent = config.organization;
  }
  if (config.confidentiality) {
    const modalConf = document.getElementById('modal-confidentiality-badge');
    if (modalConf) modalConf.textContent = config.confidentiality;
    const sideBadge = document.getElementById('sidebar-badge');
    if (sideBadge) sideBadge.textContent = config.confidentiality;
  }

  if (!config.pin_enabled || (!config.pin_hash && !config.admin_hash)) {
    if (authOverlay) authOverlay.style.display = 'none';
    const defaultRole = config.default_role || (config.is_demo ? 'operator' : 'admin');
    return { role: defaultRole, config };
  }

  // Zorg dat het invoerveld leeg is en focus krijgt
  if (pinInput) {
    pinInput.value = '';
    setTimeout(() => pinInput.focus(), 150);
  }

  // Wacht altijd op pincode-invoer van de gebruiker (1234 voor Operator, 9999 voor Admin/Supervisor)
  return new Promise((resolve) => {
    authForm.addEventListener('submit', async (e) => {
      e.preventDefault();
      const enteredPin = pinInput.value.trim();
      const hashed = await sha256(enteredPin);

      const isAdmin = (config.admin_hash && hashed.toLowerCase() === config.admin_hash.toLowerCase()) || enteredPin === '9999';
      const isOperator = (config.pin_hash && hashed.toLowerCase() === config.pin_hash.toLowerCase()) || enteredPin === '1234';

      if (isAdmin) {
        authError.style.color = '#34d399';
        authError.textContent = '👑 Supervisor / Admin toegang verleend! 3D-model wordt geladen...';
        setTimeout(() => {
          authOverlay.style.opacity = '0';
          setTimeout(() => {
            authOverlay.style.display = 'none';
            resolve({ role: 'admin', config });
          }, 300);
        }, 400);
      } else if (isOperator) {
        authError.style.color = '#34d399';
        authError.textContent = '👤 Operator toegang verleend! 3D-model wordt geladen...';
        setTimeout(() => {
          authOverlay.style.opacity = '0';
          setTimeout(() => {
            authOverlay.style.display = 'none';
            resolve({ role: 'operator', config });
          }, 300);
        }, 400);
      } else {
        authError.style.color = '#f87171';
        authError.textContent = '❌ Onjuiste toegangscode (Operator: 1234 / Admin: 9999).';
        pinInput.value = '';
        pinInput.focus();
      }
    });
  });
}

// Toast notificatie functie
function showToast(msg) {
  const toast = document.getElementById('toast');
  if (!toast) return;
  toast.textContent = msg;
  toast.classList.add('show');
  setTimeout(() => toast.classList.remove('show'), 2800);
}

// ==========================================================
// 2. HOOFDVIEWER & HUMAN-IN-THE-LOOP 3D EDITOR
// ==========================================================
async function initViewer() {
  const authResult = await verifyAccess();
  let userRole = authResult.role || 'operator';
  const config = authResult.config || {};

  // Update Role Badge in Sidebar
  const roleBadge = document.getElementById('role-badge');
  function updateRoleBadge() {
    if (!roleBadge) return;
    if (config.is_demo) {
      roleBadge.textContent = '✨ 3D Demo Preview';
      roleBadge.style.background = 'rgba(59, 130, 246, 0.2)';
      roleBadge.style.borderColor = '#3b82f6';
      roleBadge.style.color = '#93c5fd';
    } else if (userRole === 'admin') {
      roleBadge.textContent = '👑 Supervisor / Admin';
      roleBadge.style.background = 'rgba(59, 130, 246, 0.2)';
      roleBadge.style.borderColor = '#3b82f6';
      roleBadge.style.color = '#93c5fd';
    } else {
      roleBadge.textContent = '👤 Operator';
      roleBadge.style.background = 'rgba(16, 185, 129, 0.2)';
      roleBadge.style.borderColor = '#10b981';
      roleBadge.style.color = '#6ee7b7';
    }
  }
  updateRoleBadge();

  // Laad annotaties en metadata
  let annotations = [];
  let metadata = {};

  try {
    const res = await fetch('./annotations.json');
    if (res.ok) {
      const data = await res.json();
      if (Array.isArray(data)) {
        annotations = data;
      } else if (data.annotations) {
        annotations = data.annotations;
        metadata = data.metadata || {};
      }
    }
  } catch (e) {
    console.error('Fout bij laden van annotations.json:', e);
  }

  if (metadata.organization) {
    const sideOrg = document.getElementById('sidebar-org');
    if (sideOrg) sideOrg.textContent = metadata.organization;
  }
  if (metadata.confidentiality) {
    const sideBadge = document.getElementById('sidebar-badge');
    if (sideBadge) sideBadge.textContent = metadata.confidentiality;
  }

  // Bepaal startpositie van de camera
  const firstCam = annotations.length > 0 ? annotations[0].camera_position_3d : [0, 0, -2];
  const firstTarget = annotations.length > 0 ? annotations[0].position_3d : [0, 0, 0];

  const container = document.getElementById('canvas-container');

  // Audio setup
  const sopAudio = new Audio('./audio.mp3');
  let audioStopTimer = null;
  let isAudioMuted = false;

  function playStepAudio(timestamp) {
    if (isAudioMuted || !timestamp) return;
    if (audioStopTimer) clearTimeout(audioStopTimer);
    sopAudio.currentTime = Math.max(0, timestamp - 1.0);
    sopAudio.play().catch(() => {});
    audioStopTimer = setTimeout(() => sopAudio.pause(), 8000);
  }

  // Initialiseer Gaussian Splatting Viewer in COLMAP-coördinaten
  const viewer = new GaussianSplats3D.Viewer({
    rootElement: container,
    cameraUp: [0, -1, 0], // COLMAP OPENCV gebruikt -Y als 'boven'
    initialCameraPosition: firstCam,
    initialCameraLookAt: firstTarget,
    sharedMemoryForWorkers: false,
    selfDrivenMode: true
  });

  await viewer.addSplatScene('./point_cloud.splat', {
    splatAlphaRemovalThreshold: 5,
    showLoadingUI: true
  });

  viewer.start();

  // State variabelen
  let currentLang = 'nl';
  let isEditMode = false;
  let activeStepIndex = -1;
  let animState = null;
  let pinElements = [];
  let repositioningStepIdx = null;

  const stepsListEl = document.getElementById('steps-list');
  const hotspotsLayerEl = document.getElementById('hotspots-layer');
  const modeToggleBtn = document.getElementById('mode-toggle-btn');
  const modeBtnText = document.getElementById('mode-btn-text');
  const saveServerBtn = document.getElementById('save-server-btn');
  const saveExportBtn = document.getElementById('save-export-btn');
  const addStepBtn = document.getElementById('add-step-btn');
  const audioToggleBtn = document.getElementById('audio-toggle-btn');
  const audioBtnIcon = document.getElementById('audio-btn-icon');
  const editCrosshair = document.getElementById('edit-crosshair');
  const exportPdfBtn = document.getElementById('export-pdf-btn');
  const sopReportModal = document.getElementById('sop-report-modal');
  const printableSopDoc = document.getElementById('printable-sop-document');
  const printSopBtn = document.getElementById('print-sop-btn');
  const closeSopBtn = document.getElementById('close-sop-btn');
  const repositionBanner = document.getElementById('reposition-banner');
  const cancelRepositionBtn = document.getElementById('cancel-reposition-btn');
  const commitCenterBtn = document.getElementById('commit-center-btn');
  const repositionBannerTitle = document.getElementById('reposition-banner-title');
  const axesLegend = document.getElementById('axes-legend');

  // 3D Assenstelsel Gizmo (AxesHelper: X=Rood, Y=Groen, Z=Blauw)
  const axesGizmo = new THREE.AxesHelper(0.35);
  axesGizmo.renderOrder = 999;
  axesGizmo.material.depthTest = false;
  axesGizmo.visible = false;
  if (viewer.threeScene) {
    viewer.threeScene.add(axesGizmo);
  }

  // Meertalige hulptaalfuncties
  function getStepTitle(step, lang) {
    if (lang && lang !== 'nl' && step.translations && step.translations[lang] && step.translations[lang].part_name) {
      return step.translations[lang].part_name;
    }
    return step.title || '';
  }

  function getStepDesc(step, lang) {
    if (lang && lang !== 'nl' && step.translations && step.translations[lang] && step.translations[lang].instruction) {
      return step.translations[lang].instruction;
    }
    return step.description || '';
  }

  // Luister naar taalkeuzeknoppen
  document.querySelectorAll('.btn-lang').forEach((btn) => {
    btn.addEventListener('click', () => {
      document.querySelectorAll('.btn-lang').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      currentLang = btn.getAttribute('data-lang');
      renderUI();
      showToast(`🌐 Taal gewijzigd: ${currentLang.toUpperCase()}`);
    });
  });

  // Vlieg soepel naar een stap
  function flyToStep(index) {
    if (index < 0 || index >= annotations.length) return;
    activeStepIndex = index;
    const step = annotations[index];

    playStepAudio(step.timestamp);

    document.querySelectorAll('.step-card').forEach((el, i) => {
      el.classList.toggle('active', i === index);
      const indicator = el.querySelector('.audio-indicator');
      if (indicator) indicator.style.display = (i === index && !isAudioMuted) ? 'inline' : 'none';
    });

    pinElements.forEach((item, i) => {
      item.el.classList.toggle('active', i === index);
    });

    animState = {
      startTime: performance.now(),
      duration: 900,
      startCam: viewer.camera.position.clone(),
      endCam: new THREE.Vector3(...step.camera_position_3d),
      startTarget: viewer.controls.target.clone(),
      endTarget: new THREE.Vector3(...step.position_3d)
    };
  }

  // Bouw UI stappenlijst opnieuw op
  function renderUI() {
    stepsListEl.innerHTML = '';
    hotspotsLayerEl.innerHTML = '';
    pinElements = [];

    if (annotations.length === 0) {
      stepsListEl.innerHTML = '<div style="color: #94a3b8; font-size: 13px; text-align: center; padding: 20px;">Geen stappen gedetecteerd. Klik op "+ Nieuwe stap toevoegen" om te beginnen.</div>';
      return;
    }

    annotations.forEach((step, idx) => {
      step.step = idx + 1; // Nummering consistent houden

      // Maak zijbalk-kaartje
      const card = document.createElement('div');
      card.className = `step-card ${idx === activeStepIndex ? 'active' : ''}`;

      const currentTitle = getStepTitle(step, currentLang);
      const currentDesc = getStepDesc(step, currentLang);

      if (!isEditMode) {
        // --- WEERGAVEMODUS (Overzichtelijk voor operators / kleine bedrijven) ---
        card.innerHTML = `
          <div class="step-header-row">
            <span class="step-badge">Stap ${step.step} • ${step.timestamp || 0}s</span>
            <span class="audio-indicator">🔊 Speelt</span>
          </div>
          <div class="step-title">${currentTitle}</div>
          <div class="step-desc">${currentDesc}</div>
        `;
        card.addEventListener('click', () => flyToStep(idx));
      } else {
        // --- BEWERKMODUS (Human-in-the-Loop met 3D Nudge) ---
        const isRepositioning = repositioningStepIdx === idx;
        const coords = step.position_3d || [0, 0, 0];
        const displayCoords = coords.map(c => Math.round(c * 100) / 100).join(', ');

        card.innerHTML = `
          <div class="step-header-row">
            <span class="step-badge">Stap ${step.step} (${currentLang.toUpperCase()})</span>
            <div style="display: flex; gap: 4px;">
              ${idx > 0 ? `<button class="btn-reorder btn-move-up" data-idx="${idx}" title="Stap naar boven verplaatsen">⬆️</button>` : ''}
              ${idx < annotations.length - 1 ? `<button class="btn-reorder btn-move-down" data-idx="${idx}" title="Stap naar beneden verplaatsen">⬇️</button>` : ''}
            </div>
          </div>

          ${(step.debug_snapshot || step.matched_frame) ? `
          <div style="display: flex; align-items: center; gap: 8px; margin-bottom: 6px; background: rgba(15, 23, 42, 0.5); padding: 4px 6px; border-radius: 4px;">
            <img src="./${step.debug_snapshot || step.matched_frame}" style="width: 44px; height: 30px; object-fit: cover; border-radius: 3px; border: 1px solid rgba(255,255,255,0.15);" onerror="this.style.display='none'" />
            <span style="font-size: 11px; color: #94a3b8;">Gekoppeld frame</span>
          </div>
          ` : ''}

          <input type="text" class="edit-field step-title-input" value="${currentTitle}" placeholder="Naam onderdeel (${currentLang.toUpperCase()})" />
          <textarea class="edit-field step-desc-input" placeholder="Onderhoudsinstructie (${currentLang.toUpperCase()})">${currentDesc}</textarea>

          <!-- Audio timing finetuning -->
          <div class="audio-timing-box">
            <span>⏱️ Audio timing:</span>
            <input type="number" step="0.5" min="0" class="audio-ts-input" value="${step.timestamp || 0}" />
            <span>sec</span>
            <button class="btn-audio-test" title="Beluister audio vanaf deze seconde">▶ Test</button>
          </div>

          <div class="card-actions">
            <button class="btn btn-sm btn-reposition" data-idx="${idx}">
              ${isRepositioning ? '📌 Sla middenpositie op' : '🎯 3D-Positie verplaatsen'}
            </button>
            <button class="btn btn-sm btn-delete" data-idx="${idx}">🗑️ Verwijderen</button>
          </div>

          <!-- 3D Finetuning Nudge Knoppen (±2cm) met X, Y, Z Assen -->
          <div class="nudge-panel">
            <div class="nudge-title">
              <span>🎯 Assen Finetunen (±2cm):</span>
              <span style="font-size: 10px; color: #94a3b8; font-family: monospace;">[${displayCoords}]</span>
            </div>
            <div class="nudge-grid">
              <div class="nudge-group" style="border-left: 3px solid #ef4444;">
                <span style="color: #f87171; font-weight: 700;">🔴 X:</span>
                <button class="nudge-btn" data-axis="0" data-val="-0.02" title="-2cm X">-2</button>
                <button class="nudge-btn" data-axis="0" data-val="0.02" title="+2cm X">+2</button>
              </div>
              <div class="nudge-group" style="border-left: 3px solid #22c55e;">
                <span style="color: #4ade80; font-weight: 700;">🟢 Y:</span>
                <button class="nudge-btn" data-axis="1" data-val="-0.02" title="-2cm Y">-2</button>
                <button class="nudge-btn" data-axis="1" data-val="0.02" title="+2cm Y">+2</button>
              </div>
              <div class="nudge-group" style="border-left: 3px solid #3b82f6;">
                <span style="color: #60a5fa; font-weight: 700;">🔵 Z:</span>
                <button class="nudge-btn" data-axis="2" data-val="-0.02" title="-2cm Z">-2</button>
                <button class="nudge-btn" data-axis="2" data-val="0.02" title="+2cm Z">+2</button>
              </div>
            </div>
          </div>
        `;

        // Event listeners voor bewerken
        const titleInput = card.querySelector('.step-title-input');
        const descInput = card.querySelector('.step-desc-input');
        const repoBtn = card.querySelector('.btn-reposition');
        const delBtn = card.querySelector('.btn-delete');
        const audioTsInput = card.querySelector('.audio-ts-input');
        const audioTestBtn = card.querySelector('.btn-audio-test');
        const moveUpBtn = card.querySelector('.btn-move-up');
        const moveDownBtn = card.querySelector('.btn-move-down');

        titleInput.addEventListener('input', (e) => {
          const val = e.target.value;
          if (currentLang === 'nl') {
            step.title = val;
          } else {
            step.translations = step.translations || {};
            step.translations[currentLang] = step.translations[currentLang] || {};
            step.translations[currentLang].part_name = val;
          }
          pin.title = val;
        });

        descInput.addEventListener('input', (e) => {
          const val = e.target.value;
          if (currentLang === 'nl') {
            step.description = val;
          } else {
            step.translations = step.translations || {};
            step.translations[currentLang] = step.translations[currentLang] || {};
            step.translations[currentLang].instruction = val;
          }
        });

        if (audioTsInput) {
          audioTsInput.addEventListener('change', (e) => {
            step.timestamp = parseFloat(e.target.value) || 0.0;
          });
        }

        if (audioTestBtn) {
          audioTestBtn.addEventListener('click', (e) => {
            e.stopPropagation();
            playStepAudio(step.timestamp);
          });
        }

        if (moveUpBtn) {
          moveUpBtn.addEventListener('click', (e) => {
            e.stopPropagation();
            if (idx > 0) {
              const temp = annotations[idx];
              annotations[idx] = annotations[idx - 1];
              annotations[idx - 1] = temp;
              activeStepIndex = idx - 1;
              renderUI();
              showToast(`Stap ${idx + 1} verplaatst naar positie ${idx}`);
            }
          });
        }

        if (moveDownBtn) {
          moveDownBtn.addEventListener('click', (e) => {
            e.stopPropagation();
            if (idx < annotations.length - 1) {
              const temp = annotations[idx];
              annotations[idx] = annotations[idx + 1];
              annotations[idx + 1] = temp;
              activeStepIndex = idx + 1;
              renderUI();
              showToast(`Stap ${idx + 1} verplaatst naar positie ${idx + 2}`);
            }
          });
        }

        // Finetuning Nudge buttons (X, Y, Z Assen)
        card.querySelectorAll('.nudge-btn').forEach(btn => {
          btn.addEventListener('click', (e) => {
            e.stopPropagation();
            const axis = parseInt(btn.getAttribute('data-axis'));
            const delta = parseFloat(btn.getAttribute('data-val'));
            step.position_3d = step.position_3d || [0, 0, 0];
            step.position_3d[axis] = round4(step.position_3d[axis] + delta);
            activeStepIndex = idx;
            if (axesGizmo) {
              axesGizmo.position.set(...step.position_3d);
              axesGizmo.visible = true;
            }
            if (pinElements[idx]) {
              pinElements[idx].worldPos.set(...step.position_3d);
            }
            renderUI();
          });
        });

        repoBtn.addEventListener('click', (e) => {
          e.stopPropagation();
          if (repositioningStepIdx === idx) {
            const targetPos = viewer.controls.target;
            const camPos = viewer.camera.position;
            step.position_3d = [round4(targetPos.x), round4(targetPos.y), round4(targetPos.z)];
            step.camera_position_3d = [round4(camPos.x), round4(camPos.y), round4(camPos.z)];
            repositioningStepIdx = null;
            if (repositionBanner) repositionBanner.style.display = 'none';
            if (axesGizmo) axesGizmo.position.set(...step.position_3d);
            showToast(`✅ Positie voor Stap ${step.step} bijgewerkt!`);
            renderUI();
          } else {
            repositioningStepIdx = idx;
            activeStepIndex = idx;
            if (repositionBanner) {
              repositionBanner.style.display = 'flex';
              if (repositionBannerTitle) {
                repositionBannerTitle.textContent = `🎯 3D-Positie aanpassen voor Stap ${step.step} (${step.title || ''})`;
              }
            }
            if (axesGizmo) {
              axesGizmo.position.set(...(step.position_3d || [0, 0, 0]));
              axesGizmo.visible = true;
            }
            showToast(`🎯 Draai vrij rond het toestel. Klik op een punt of neem het midden over.`);
            renderUI();
          }
        });

        delBtn.addEventListener('click', (e) => {
          e.stopPropagation();
          if (confirm(`Weet je zeker dat je Stap ${step.step} ("${step.title}") wilt verwijderen?`)) {
            annotations.splice(idx, 1);
            showToast(`🗑️ Stap ${idx + 1} verwijderd.`);
            renderUI();
          }
        });
      }

      stepsListEl.appendChild(card);

      // Maak 3D pin op scherm
      const pin = document.createElement('div');
      pin.className = `hotspot-pin ${idx === activeStepIndex ? 'active' : ''}`;
      pin.textContent = step.step;
      pin.title = currentTitle;
      pin.addEventListener('click', () => flyToStep(idx));
      hotspotsLayerEl.appendChild(pin);

      pinElements.push({
        el: pin,
        worldPos: new THREE.Vector3(...step.position_3d)
      });
    });

    // Update 3D Assenstelsel Gizmo op het actieve inspectiepunt
    if (isEditMode && activeStepIndex >= 0 && activeStepIndex < annotations.length) {
      const activeStep = annotations[activeStepIndex];
      if (activeStep && activeStep.position_3d && axesGizmo) {
        axesGizmo.position.set(...activeStep.position_3d);
        axesGizmo.visible = true;
      }
    } else if (axesGizmo) {
      axesGizmo.visible = false;
    }
  }

  function round4(num) {
    return Math.round(num * 10000) / 10000;
  }

  // ==========================================================
  // HUMAN-IN-THE-LOOP WEB EDITOR: BEWERKMODUS & PERSISTENTIE
  // ==========================================================
  function setEditMode(enabled) {
    isEditMode = enabled;
    repositioningStepIdx = null;
    if (repositionBanner) repositionBanner.style.display = 'none';

    if (isEditMode) {
      modeBtnText.textContent = 'Weergave';
      modeToggleBtn.className = 'btn btn-edit-active';
      if (saveServerBtn) saveServerBtn.style.display = 'flex';
      saveExportBtn.style.display = 'flex';
      addStepBtn.style.display = 'flex';
      editCrosshair.style.display = 'block';
      if (axesLegend) axesLegend.style.display = 'flex';
      showToast('✏️ Human-in-the-Loop Web Editor actief!');
    } else {
      modeBtnText.textContent = 'Bewerken';
      modeToggleBtn.className = 'btn btn-secondary';
      if (saveServerBtn) saveServerBtn.style.display = 'none';
      saveExportBtn.style.display = 'none';
      addStepBtn.style.display = 'none';
      editCrosshair.style.display = 'none';
      if (axesLegend) axesLegend.style.display = 'none';
      if (axesGizmo) axesGizmo.visible = false;
      showToast('👁️ Weergavemodus actief.');
    }
    renderUI();
  }

  // RBAC bescherming: Alleen supervisor met Admin PIN mag de 3D-instructies bewerken
  modeToggleBtn.addEventListener('click', async () => {
    if (!isEditMode && userRole !== 'admin') {
      const entered = window.prompt('🔒 Supervisor / Beheerderscode vereist:\nVoer de beheerders PIN in (standaard: 9999) om 3D-annotaties en instructies aan te passen:');
      if (!entered) return;
      const hashed = await sha256(entered.trim());
      const isSuper = (config.admin_hash && hashed.toLowerCase() === config.admin_hash.toLowerCase()) || entered.trim() === '9999';
      if (isSuper) {
        userRole = 'admin';
        updateRoleBadge();
        showToast('👑 Beheerdersrechten toegekend! Bewerkmodus ontgrendeld.');
        setEditMode(true);
      } else {
        alert('❌ Onjuiste beheerderscode. Alleen supervisors (PIN 9999) hebben bewerkrechten.');
      }
      return;
    }
    setEditMode(!isEditMode);
  });

  function getObjectNameFromUrl() {
    const parts = window.location.pathname.split('/');
    const vIdx = parts.indexOf('viewer');
    if (vIdx !== -1 && parts.length > vIdx + 1) {
      return parts[vIdx + 1];
    }
    return '';
  }

  async function saveAnnotationsToServer() {
    const objectName = getObjectNameFromUrl();
    if (!objectName) {
      showToast('⚠️ Objectnaam niet gevonden in URL; download als JSON bestand.');
      return;
    }

    metadata.updated_at = new Date().toISOString();
    metadata.version = (parseFloat(metadata.version || '1.0') + 0.1).toFixed(1);

    const exportData = {
      metadata: metadata,
      annotations: annotations
    };

    if (saveServerBtn) {
      saveServerBtn.disabled = true;
      saveServerBtn.innerHTML = '<span>⏳</span> <span>Opslaan...</span>';
    }

    try {
      const res = await fetch('/api/save-annotations', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          object_name: objectName,
          data: exportData
        })
      });

      const resData = await res.json();
      if (res.ok && resData.success) {
        showToast(`💾 Server-sync geslaagd! Revisie ${metadata.version} permanent opgeslagen.`);
      } else {
        throw new Error(resData.error || 'Serverfout bij opslaan');
      }
    } catch (err) {
      console.error('Opslaan naar server mislukt:', err);
      showToast(`❌ Fout bij opslaan naar server: ${err.message}`);
    } finally {
      if (saveServerBtn) {
        saveServerBtn.disabled = false;
        saveServerBtn.innerHTML = '<span>💾</span> <span>Opslaan</span>';
      }
    }
  }

  if (saveServerBtn) {
    saveServerBtn.addEventListener('click', saveAnnotationsToServer);
  }

  // Interactief klikken op het 3D-model met onderscheid tussen camera-draaien (drag) en gerichte klik
  let pointerDownPos = null;

  container.addEventListener('pointerdown', (e) => {
    if (repositioningStepIdx === null) return;
    if (e.target.closest('#sidebar') || e.target.closest('#reposition-banner') || e.target.closest('#sop-report-modal') || e.target.closest('#axes-legend')) {
      return;
    }
    pointerDownPos = { x: e.clientX, y: e.clientY, time: performance.now() };
  });

  container.addEventListener('pointerup', (e) => {
    if (repositioningStepIdx === null || !pointerDownPos) return;
    if (e.target.closest('#sidebar') || e.target.closest('#reposition-banner') || e.target.closest('#sop-report-modal') || e.target.closest('#axes-legend')) {
      pointerDownPos = null;
      return;
    }

    const dx = e.clientX - pointerDownPos.x;
    const dy = e.clientY - pointerDownPos.y;
    const dt = performance.now() - pointerDownPos.time;
    pointerDownPos = null;

    // Als de cursor meer dan 6px bewoog of langdurig werd ingedrukt, was het een camerabeweging/orbit!
    if (Math.hypot(dx, dy) > 6 || dt > 600) {
      return;
    }

    const step = annotations[repositioningStepIdx];
    const camPos = viewer.camera.position;
    const oldTarget = new THREE.Vector3(...(step.position_3d || [0, 0, 0]));
    const dist = Math.max(0.2, camPos.distanceTo(oldTarget));

    const rect = container.getBoundingClientRect();
    const mouseX = ((e.clientX - rect.left) / rect.width) * 2 - 1;
    const mouseY = -((e.clientY - rect.top) / rect.height) * 2 + 1;

    const raycaster = new THREE.Raycaster();
    raycaster.setFromCamera({ x: mouseX, y: mouseY }, viewer.camera);

    const hitPoint = new THREE.Vector3();
    raycaster.ray.at(dist, hitPoint);

    step.position_3d = [round4(hitPoint.x), round4(hitPoint.y), round4(hitPoint.z)];
    step.camera_position_3d = [round4(camPos.x), round4(camPos.y), round4(camPos.z)];

    if (axesGizmo) {
      axesGizmo.position.set(...step.position_3d);
      axesGizmo.visible = true;
    }

    repositioningStepIdx = null;
    if (repositionBanner) repositionBanner.style.display = 'none';
    showToast(`🎯 Stap ${step.step} via 3D-klik gepositioneerd!`);
    renderUI();
  });

  // Vastleggen op schermmidden (crosshair positie)
  if (commitCenterBtn) {
    commitCenterBtn.addEventListener('click', () => {
      if (repositioningStepIdx === null) return;
      const step = annotations[repositioningStepIdx];
      const targetPos = viewer.controls.target;
      const camPos = viewer.camera.position;

      step.position_3d = [round4(targetPos.x), round4(targetPos.y), round4(targetPos.z)];
      step.camera_position_3d = [round4(camPos.x), round4(camPos.y), round4(camPos.z)];

      if (axesGizmo) {
        axesGizmo.position.set(...step.position_3d);
        axesGizmo.visible = true;
      }

      repositioningStepIdx = null;
      if (repositionBanner) repositionBanner.style.display = 'none';
      showToast(`📌 Stap ${step.step} vastgelegd op het schermmidden!`);
      renderUI();
    });
  }

  if (cancelRepositionBtn) {
    cancelRepositionBtn.addEventListener('click', () => {
      repositioningStepIdx = null;
      if (repositionBanner) repositionBanner.style.display = 'none';
      renderUI();
    });
  }

  // Automatisch openen in bewerkmodus indien ?mode=edit in URL staat (mits admin rechten)
  const urlParams = new URLSearchParams(window.location.search);
  if (urlParams.get('mode') === 'edit' && userRole === 'admin') {
    setEditMode(true);
  }

  // Nieuwe stap toevoegen op basis van de huidige camera-kijkhoek
  addStepBtn.addEventListener('click', () => {
    const targetPos = viewer.controls.target;
    const camPos = viewer.camera.position;

    const newStep = {
      step: annotations.length + 1,
      title: `Onderdeel ${annotations.length + 1}`,
      description: 'Voeg hier een concrete onderhouds- of controle-instructie toe.',
      timestamp: sopAudio && !isNaN(sopAudio.currentTime) && sopAudio.currentTime > 0
        ? round4(sopAudio.currentTime)
        : 0.0,
      position_3d: [round4(targetPos.x), round4(targetPos.y), round4(targetPos.z)],
      camera_position_3d: [round4(camPos.x), round4(camPos.y), round4(camPos.z)]
    };

    annotations.push(newStep);
    activeStepIndex = annotations.length - 1;
    repositioningStepIdx = annotations.length - 1;

    if (repositionBanner) {
      repositionBanner.style.display = 'flex';
      if (repositionBannerTitle) {
        repositionBannerTitle.textContent = `🎯 Nieuwe Stap ${newStep.step} plaatsen`;
      }
    }
    if (axesGizmo) {
      axesGizmo.position.set(...newStep.position_3d);
      axesGizmo.visible = true;
    }

    showToast(`➕ Stap ${newStep.step} toegevoegd! Klik op het gewenste punt of neem het midden over.`);
    renderUI();

    setTimeout(() => {
      stepsListEl.scrollTop = stepsListEl.scrollHeight;
    }, 100);
  });

  // Exporteren / Lokale JSON download backup
  saveExportBtn.addEventListener('click', () => {
    metadata.updated_at = new Date().toISOString();
    metadata.version = (parseFloat(metadata.version || '1.0') + 0.1).toFixed(1);

    const exportData = {
      metadata: metadata,
      annotations: annotations
    };

    const jsonStr = JSON.stringify(exportData, null, 2);
    const blob = new Blob([jsonStr], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `annotations_${getObjectNameFromUrl() || 'export'}.json`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);

    showToast('📥 Lokale backup van annotations.json gedownload!');
  });

  // ==========================================================
  // ISO 9001 SOP RAPPORT GENERATOR (PRINT / PDF MET LOGO)
  // ==========================================================
  function openSopReport() {
    const org = metadata.organization || config.organization || 'Industriële Installatie';
    const conf = metadata.confidentiality || config.confidentiality || 'Vertrouwelijk - Alleen Geautoriseerd Personeel';
    const docDate = new Date().toLocaleDateString('nl-BE', { year: 'numeric', month: 'long', day: 'numeric' });
    const docTime = new Date().toLocaleTimeString('nl-BE', { hour: '2-digit', minute: '2-digit' });
    const cleanUrl = window.location.origin + window.location.pathname;
    const qrUrl = `https://api.qrserver.com/v1/create-qr-code/?size=160x160&data=${encodeURIComponent(cleanUrl)}`;

    let stepsHtml = '';
    annotations.forEach((st) => {
      const title = getStepTitle(st, currentLang);
      const desc = getStepDesc(st, currentLang);
      const snapshotSrc = st.debug_snapshot || st.matched_frame || '';
      const imgHtml = snapshotSrc
        ? `<img src="./${snapshotSrc}" class="sop-snapshot-img" alt="Inspectiepunt ${st.step}" onerror="this.parentElement.innerHTML='<span style=\\'color:#94a3b8;font-size:11px;\\'>Geen foto</span>'"/>`
        : `<span style="color: #94a3b8; font-size: 11px;">Geen snapshot</span>`;

      stepsHtml += `
        <tr>
          <td style="text-align: center; font-weight: 700; width: 45px;">
            <span class="sop-step-badge">${st.step}</span>
          </td>
          <td style="width: 130px; text-align: center;">
            ${imgHtml}
          </td>
          <td style="font-weight: 700; color: #0f172a; width: 180px;">
            ${title}
            <div style="font-size: 10px; color: #64748b; margin-top: 4px; font-weight: 500;">
              3D Coördinaten:<br/>[${st.position_3d ? st.position_3d.join(', ') : 'N.v.t.'}]
            </div>
          </td>
          <td style="color: #334155; line-height: 1.5;">
            ${desc}
          </td>
          <td style="width: 140px; font-size: 11px;">
            <label style="display: flex; align-items: center; gap: 4px; margin-bottom: 3px; cursor: pointer;">
              <input type="checkbox" style="cursor: pointer;" /> <span>Conform</span>
            </label>
            <label style="display: flex; align-items: center; gap: 4px; margin-bottom: 3px; cursor: pointer;">
              <input type="checkbox" style="cursor: pointer;" /> <span>Afwijking</span>
            </label>
            <label style="display: flex; align-items: center; gap: 4px; margin-bottom: 6px; cursor: pointer;">
              <input type="checkbox" style="cursor: pointer;" /> <span>N.v.t.</span>
            </label>
            <div style="border-top: 1px dotted #cbd5e1; padding-top: 4px; color: #64748b; font-size: 10px;">
              Paraaf: _________
            </div>
          </td>
        </tr>
      `;
    });

    printableSopDoc.innerHTML = `
      <div class="sop-doc-header">
        <div style="display: flex; align-items: center; gap: 16px;">
          <img src="./logo.svg" alt="Company Logo" style="max-height: 48px; max-width: 160px; object-fit: contain;" onerror="this.style.display='none'" />
          <div class="sop-doc-title-box">
            <div style="font-size: 11px; font-weight: 700; color: #2563eb; letter-spacing: 0.5px; margin-bottom: 2px;">
              ${org.toUpperCase()} • KWALITEIT & VEILIGHEID
            </div>
            <h1>STANDAARD OPERATIONELE PROCEDURE (SOP)</h1>
            <h2>Werkvoorschrift & Visuele Handleiding conform ISO 9001</h2>
          </div>
        </div>
        <div style="text-align: right;">
          <span class="sop-step-badge" style="background: #1e293b; font-size: 10px; padding: 4px 10px;">
            ${conf}
          </span>
          <div style="font-size: 10px; color: #64748b; margin-top: 6px;">
            Taalversie: <strong>${currentLang.toUpperCase()}</strong>
          </div>
        </div>
      </div>

      <!-- Metadata Tabel -->
      <table class="sop-meta-table">
        <tr>
          <th>Document Code:</th>
          <td>SOP-DOC-${Date.now().toString().slice(-6)}</td>
          <th>Status:</th>
          <td><strong style="color: #059669;">● VRIJGEGEVEN VOOR PRODUCTIE</strong></td>
        </tr>
        <tr>
          <th>Revisienummer:</th>
          <td>REV 1.0</td>
          <th>Uitgiftedatum & Tijd:</th>
          <td>${docDate} om ${docTime}</td>
        </tr>
        <tr>
          <th>Systeem / Object:</th>
          <td>${document.title || '3D Digital Twin SOP'}</td>
          <th>Beveiligingsniveau:</th>
          <td>PIN Beveiligd (RBAC SHA-256)</td>
        </tr>
      </table>

      <!-- 3D Digital Twin QR Badge -->
      <div class="sop-qr-box">
        <img src="${qrUrl}" alt="3D SOP QR Code" class="sop-qr-img" />
        <div class="sop-qr-text">
          <strong>📱 Interactieve 3D Gaussian Splatting Digital Twin:</strong><br/>
          Scan deze QR-code met een smartphone of tablet om de realtime 3D-weergave met ruimtelijk geluid en stappennavigatie direct op de werkplek te laden.<br/>
          <span style="font-size: 11px; color: #64748b; word-break: break-all;">Link: ${cleanUrl}</span>
        </div>
      </div>

      <!-- Werkstappen Tabel -->
      <table class="sop-steps-table">
        <thead>
          <tr>
            <th>#</th>
            <th>Visuele Referentie</th>
            <th>Component / Actiepunt</th>
            <th>Werkinstructie (${currentLang.toUpperCase()})</th>
            <th>Kwaliteitscontrole</th>
          </tr>
        </thead>
        <tbody>
          ${stepsHtml}
        </tbody>
      </table>

      <!-- Validatie & Sign-off Sectie -->
      <div class="sop-signoff-grid">
        <div class="sop-signoff-box">
          <div class="sop-signoff-title">1. Uitvoerend Technicus / Monteur</div>
          <div class="sop-signoff-line">Naam & Functie: _____________________________________</div>
          <div class="sop-signoff-line">Datum & Tijdstip: _____ - _____ - 2026 om _____:_____</div>
          <div class="sop-signoff-line" style="margin-top: 18px;">Handtekening: _______________________________________</div>
        </div>
        <div class="sop-signoff-box">
          <div class="sop-signoff-title">2. Verantwoordelijke / Supervisor</div>
          <div class="sop-signoff-line">Naam Verantwoordelijke: _____________________________</div>
          <div class="sop-signoff-line">Vrijgave: [ ] Akkoord  [ ] Afgekeurd</div>
          <div class="sop-signoff-line" style="margin-top: 18px;">Handtekening: _______________________________________</div>
        </div>
      </div>
    `;

    sopReportModal.style.display = 'flex';
  }

  if (exportPdfBtn) {
    exportPdfBtn.addEventListener('click', openSopReport);
  }
  if (closeSopBtn) {
    closeSopBtn.addEventListener('click', () => {
      sopReportModal.style.display = 'none';
    });
  }
  if (printSopBtn) {
    printSopBtn.addEventListener('click', () => {
      window.print();
    });
  }
  if (sopReportModal) {
    sopReportModal.addEventListener('click', (e) => {
      if (e.target === sopReportModal) {
        sopReportModal.style.display = 'none';
      }
    });
  }

  // Audio Toggle
  audioToggleBtn.addEventListener('click', () => {
    isAudioMuted = !isAudioMuted;
    if (isAudioMuted) {
      sopAudio.pause();
      audioBtnIcon.textContent = '🔇';
      showToast('Stembegeleiding gedempt');
    } else {
      audioBtnIcon.textContent = '🔊';
      showToast('Stembegeleiding ingeschakeld');
    }
  });

  // Orbit-Lock Constraint
  const orbitToggle = document.getElementById('orbit-lock-toggle');
  function applyOrbitConstraints(enabled) {
    if (!viewer.controls) return;
    if (enabled) {
      viewer.controls.minDistance = 0.25;
      viewer.controls.maxDistance = 3.5;
      viewer.controls.maxPolarAngle = Math.PI * 0.85;
    } else {
      viewer.controls.minDistance = 0.05;
      viewer.controls.maxDistance = Infinity;
      viewer.controls.maxPolarAngle = Math.PI;
    }
  }
  if (orbitToggle) {
    orbitToggle.addEventListener('change', (e) => applyOrbitConstraints(e.target.checked));
    applyOrbitConstraints(true);
  }

  // Initial render
  renderUI();
  if (annotations.length > 0) {
    flyToStep(0);
  }

  // 3. Render-loop: 3D naar 2D Schermprojectie
  const tempVec = new THREE.Vector3();

  function updateLoop(now) {
    requestAnimationFrame(updateLoop);

    if (animState && viewer.controls) {
      const progress = Math.min((now - animState.startTime) / animState.duration, 1.0);
      const ease = progress < 0.5
        ? 2 * progress * progress
        : 1 - Math.pow(-2 * progress + 2, 2) / 2;

      viewer.camera.position.lerpVectors(animState.startCam, animState.endCam, ease);
      viewer.controls.target.lerpVectors(animState.startTarget, animState.endTarget, ease);
      viewer.controls.update();

      if (progress >= 1.0) {
        animState = null;
      }
    }

    const width = window.innerWidth;
    const height = window.innerHeight;

    pinElements.forEach((item) => {
      tempVec.copy(item.worldPos);
      tempVec.project(viewer.camera);

      if (tempVec.z > 1.0) {
        item.el.style.display = 'none';
        return;
      }

      const x = (tempVec.x * 0.5 + 0.5) * width;
      const y = (-tempVec.y * 0.5 + 0.5) * height;

      item.el.style.display = 'flex';
      item.el.style.transform = `translate3d(${x}px, ${y}px, 0)`;
    });
  }

  requestAnimationFrame(updateLoop);
}

initViewer();
