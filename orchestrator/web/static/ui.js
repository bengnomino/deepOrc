(() => {
  async function copyText(text) {
    if (navigator.clipboard && window.isSecureContext) {
      await navigator.clipboard.writeText(text);
      return;
    }
    const area = document.createElement("textarea");
    area.value = text;
    document.body.appendChild(area);
    area.select();
    document.execCommand("copy");
    area.remove();
  }

  function wireDialogClose(modal, closeBtn) {
    closeBtn?.addEventListener("click", () => modal.close());
    modal.addEventListener("click", (event) => {
      const rect = modal.getBoundingClientRect();
      const inDialog =
        event.clientX >= rect.left &&
        event.clientX <= rect.right &&
        event.clientY >= rect.top &&
        event.clientY <= rect.bottom;
      if (!inDialog) modal.close();
    });
  }

  function parseWorkerChoices() {
    const node = document.getElementById("worker-choices-data");
    if (!node) return [];
    try {
      return JSON.parse(node.textContent || "[]");
    } catch {
      return [];
    }
  }

  const workerChoices = parseWorkerChoices();

  function renderWorkerPickerRow(row) {
    const status = row.online ? "online" : "offline";
    const disabled = row.online ? "" : "disabled";
    return `
      <label class="worker-picker-option ${row.online ? "" : "is-disabled"}">
        <input type="radio" name="gateway_worker_pick" value="${row.id}" ${disabled}>
        <span class="worker-picker-row">
          <span class="worker-picker-name">${row.display_name}</span>
          <span class="status-pill ${status}">${status}</span>
        </span>
      </label>`;
  }

  const gatewayModal = document.getElementById("gateway-modal");
  const gatewayBtn = document.getElementById("btn-new-gateway");
  if (gatewayModal && gatewayBtn) {
    const gatewayError = document.getElementById("gateway-modal-error");
    const gatewayPicker = document.getElementById("gateway-worker-picker");
    const gatewayWorkerId = document.getElementById("gateway-worker-id");
    const gatewaySubmit = document.getElementById("gateway-create-submit");
    const gatewayClose = document.getElementById("gateway-modal-close");

    function resetGatewayModal() {
      gatewayError.hidden = true;
      gatewayError.textContent = "";
      gatewayPicker.innerHTML = "";
      gatewayWorkerId.value = "";
      gatewaySubmit.disabled = false;
    }

    function openGatewayModal() {
      resetGatewayModal();
      const online = workerChoices.filter((row) => row.online);

      if (!workerChoices.length) {
        gatewayError.textContent = "No workers registered.";
        gatewayError.hidden = false;
        gatewaySubmit.disabled = true;
        gatewayModal.showModal();
        return;
      }

      if (!online.length) {
        gatewayError.textContent = "All workers are offline.";
        gatewayError.hidden = false;
        gatewaySubmit.disabled = true;
        gatewayModal.showModal();
        return;
      }

      const firstOnline = online[0];
      gatewayWorkerId.value = String(firstOnline.id);
      gatewayPicker.innerHTML = workerChoices.map(renderWorkerPickerRow).join("");

      gatewayPicker.querySelectorAll('input[type="radio"]').forEach((input) => {
        if (input.value === gatewayWorkerId.value && !input.disabled) {
          input.checked = true;
        }
        input.addEventListener("change", () => {
          if (input.checked && !input.disabled) {
            gatewayWorkerId.value = input.value;
          }
        });
      });

      gatewayModal.showModal();
    }

    gatewayBtn.addEventListener("click", () => openGatewayModal());
    wireDialogClose(gatewayModal, gatewayClose);

    document.getElementById("gateway-create-form")?.addEventListener("submit", (event) => {
      if (!gatewayWorkerId.value) {
        event.preventDefault();
        gatewayError.hidden = false;
        gatewayError.textContent = "Select an online worker.";
      }
    });
  }

  function wireOptionPicker(root) {
    if (!root) return;
    const trigger = root.querySelector(".picker-trigger");
    const menu = root.querySelector(".picker-menu");
    const hidden = root.querySelector('input[type="hidden"]');
    if (!trigger || !menu || !hidden) return;

    function dotClass(kind) {
      if (kind === "online") return "status-dot online";
      if (kind === "offline") return "status-dot offline";
      if (kind === "warn") return "status-dot warn";
      return "status-dot none";
    }

    function renderTrigger(option) {
      const main = trigger.querySelector(".picker-trigger-main");
      if (!main) return;
      const label = option.dataset.label || "Unassigned";
      const meta = option.dataset.meta || "";
      const dot = option.dataset.dot || "none";
      const isPending = option.dataset.value === "pending";
      main.innerHTML = `
        <span class="${dotClass(dot)}" aria-hidden="true"></span>
        <span class="picker-trigger-label${isPending ? " muted" : ""}">${label}</span>
        ${meta ? `<code class="picker-trigger-meta">${meta}</code>` : ""}`;
    }

    function closeMenu() {
      menu.hidden = true;
      trigger.setAttribute("aria-expanded", "false");
    }

    function selectOption(option) {
      if (option.disabled) return;
      hidden.value = option.dataset.value;
      root.querySelectorAll(".picker-option").forEach((row) => {
        row.classList.toggle("is-selected", row === option);
      });
      renderTrigger(option);
      closeMenu();
    }

    trigger.addEventListener("click", () => {
      const willOpen = menu.hidden;
      menu.hidden = !willOpen;
      trigger.setAttribute("aria-expanded", String(willOpen));
    });

    root.querySelectorAll(".picker-option").forEach((option) => {
      option.addEventListener("click", () => selectOption(option));
    });

    document.addEventListener("click", (event) => {
      if (!root.contains(event.target)) closeMenu();
    });

    document.addEventListener("keydown", (event) => {
      if (event.key === "Escape") closeMenu();
    });
  }

  wireOptionPicker(document.getElementById("exit-node-picker"));

  const gatewayDeleteModal = document.getElementById("gateway-delete-modal");
  const gatewayDeleteBtn = document.getElementById("btn-delete-gateway");
  if (gatewayDeleteModal && gatewayDeleteBtn) {
    const gatewayDeleteClose = document.getElementById("gateway-delete-modal-close");
    const gatewayDeleteCancel = document.getElementById("gateway-delete-cancel");
    const gatewayDeleteSubmit = gatewayDeleteModal.querySelector('button[type="submit"]');

    gatewayDeleteBtn.addEventListener("click", () => gatewayDeleteModal.showModal());
    wireDialogClose(gatewayDeleteModal, gatewayDeleteClose);
    gatewayDeleteCancel?.addEventListener("click", () => gatewayDeleteModal.close());

    gatewayDeleteModal.querySelector("#gateway-delete-form")?.addEventListener("submit", () => {
      if (gatewayDeleteSubmit) {
        gatewayDeleteSubmit.disabled = true;
        gatewayDeleteSubmit.textContent = "Deleting…";
      }
    });
  }

  const workerModal = document.getElementById("worker-modal");
  const workerBtn = document.getElementById("btn-add-worker");
  if (workerModal && workerBtn) {
    const workerLoading = document.getElementById("worker-modal-loading");
    const workerError = document.getElementById("worker-modal-error");
    const workerBody = document.getElementById("worker-modal-body");
    const workerClose = document.getElementById("worker-modal-close");
    const workerKey = document.getElementById("worker-enroll-key");
    const workerCmd = document.getElementById("worker-enroll-command");
    const workerLabel = document.getElementById("worker-enroll-label");

    function resetWorkerModal() {
      workerLoading.hidden = false;
      workerBody.hidden = true;
      workerError.hidden = true;
      workerError.textContent = "";
    }

    async function openWorkerModal() {
      resetWorkerModal();
      workerModal.showModal();
      try {
        const response = await fetch("/orchestrator/ui/workers/enroll", {
          method: "POST",
          headers: { Accept: "application/json" },
        });
        const data = await response.json();
        if (!response.ok) {
          throw new Error(data.detail || "Enrollment failed");
        }
        workerLabel.textContent = `${data.display_name} (${data.name})`;
        workerKey.value = data.tailscale_auth_key;
        workerCmd.value = data.command;
        workerLoading.hidden = true;
        workerBody.hidden = false;
      } catch (err) {
        workerLoading.hidden = true;
        workerError.hidden = false;
        workerError.textContent = err.message || String(err);
      }
    }

    workerBtn.addEventListener("click", openWorkerModal);
    wireDialogClose(workerModal, workerClose);
    document.getElementById("worker-enroll-copy-key")?.addEventListener("click", () => {
      copyText(workerKey.value);
    });
    document.getElementById("worker-enroll-copy-cmd")?.addEventListener("click", () => {
      copyText(workerCmd.value);
    });
  }

  const authModal = document.getElementById("exit-node-modal");
  const openAuthBtn = document.getElementById("btn-add-exit-node");
  if (authModal && openAuthBtn) {
    const loading = document.getElementById("exit-node-modal-loading");
    const errorBox = document.getElementById("exit-node-modal-error");
    const body = document.getElementById("exit-node-modal-body");
    const keyInput = document.getElementById("exit-node-key");
    const cmdInput = document.getElementById("exit-node-command");
    const tagEl = document.getElementById("exit-node-tag");
    const closeAuthBtn = document.getElementById("exit-node-modal-close");

    function resetAuthModal() {
      loading.hidden = false;
      body.hidden = true;
      errorBox.hidden = true;
      errorBox.textContent = "";
    }

    async function openAuthModal() {
      resetAuthModal();
      authModal.showModal();
      try {
        const response = await fetch("/orchestrator/ui/exit-nodes/authkey", {
          method: "POST",
          headers: { Accept: "application/json" },
        });
        const data = await response.json();
        if (!response.ok) {
          throw new Error(data.detail || "Auth key generation failed");
        }
        keyInput.value = data.key;
        cmdInput.value = data.command;
        tagEl.textContent = data.tag;
        loading.hidden = true;
        body.hidden = false;
      } catch (err) {
        loading.hidden = true;
        errorBox.hidden = false;
        errorBox.textContent = err.message || String(err);
      }
    }

    openAuthBtn.addEventListener("click", openAuthModal);
    wireDialogClose(authModal, closeAuthBtn);

    document.getElementById("exit-node-copy-key")?.addEventListener("click", () => {
      copyText(keyInput.value);
    });
    document.getElementById("exit-node-copy-cmd")?.addEventListener("click", () => {
      copyText(cmdInput.value);
    });
  }

  const pendingSection = document.getElementById("pending-registrations-section");
  const pendingList = document.getElementById("pending-registrations-list");
  if (pendingList) {
    function renderPending(items) {
      if (pendingSection) {
        pendingSection.hidden = items.length === 0;
      }
      if (!items.length) {
        pendingList.innerHTML = "";
        return;
      }
      pendingList.innerHTML = items
        .map(
          (item) => `
        <div class="chip-card pending-chip" data-registration-key="${item.registration_key}">
          <span class="admin-code">${item.display_code}</span>
          <span class="muted chip-meta">${item.created_at}</span>
          <div class="chip-actions">
            <form method="post" action="/orchestrator/ui/registrations/${item.registration_key}/approve">
              <button type="submit" class="btn btn-sm btn-glow">Approve</button>
            </form>
            <form method="post" action="/orchestrator/ui/registrations/${item.registration_key}/reject">
              <button type="submit" class="btn btn-sm btn-ghost">Reject</button>
            </form>
          </div>
        </div>`
        )
        .join("");
    }

    async function pollPending() {
      try {
        const response = await fetch("/orchestrator/ui/registrations/pending");
        if (response.ok) {
          renderPending(await response.json());
        }
      } catch {
        /* ignore */
      }
      setTimeout(pollPending, 3000);
    }
    pollPending();
  }

  const workerSections = document.querySelectorAll(".worker-section");
  if (workerSections.length) {
    function setMeter(bar, percent) {
      if (!bar) return;
      const value = Math.max(0, Math.min(100, percent || 0));
      bar.style.width = `${value}%`;
    }

    function formatBytesPerSec(value) {
      if (value == null || Number.isNaN(value)) return "—";
      if (value >= 1024 * 1024 * 1024) return `${(value / (1024 * 1024 * 1024)).toFixed(2)} GB/s`;
      if (value >= 1024 * 1024) return `${(value / (1024 * 1024)).toFixed(2)} MB/s`;
      if (value >= 1024) return `${(value / (1024 * 1024)).toFixed(2)} KB/s`;
      return `${Math.round(value)} B/s`;
    }

    function renderWorkerStats(workers) {
      const byId = new Map(workers.map((row) => [String(row.id), row]));
      workerSections.forEach((section) => {
        const data = byId.get(section.dataset.workerId);
        if (!data) return;
        const cpuEl = section.querySelector(".worker-cpu");
        const ramEl = section.querySelector(".worker-ram");
        const rxEl = section.querySelector(".worker-rx");
        const txEl = section.querySelector(".worker-tx");
        const cpuBar = section.querySelector(".worker-cpu-bar");
        const ramBar = section.querySelector(".worker-ram-bar");
        if (data.cpu_percent != null && cpuEl) {
          cpuEl.textContent = `${data.cpu_percent.toFixed(1)}%`;
          setMeter(cpuBar, data.cpu_percent);
        }
        if (data.memory_total_mb != null && ramEl) {
          ramEl.textContent = `${data.memory_used_mb ?? "—"} / ${data.memory_total_mb} MiB`;
          setMeter(ramBar, data.memory_percent);
        }
        if (rxEl) rxEl.textContent = formatBytesPerSec(data.network_rx_bytes_per_sec);
        if (txEl) txEl.textContent = formatBytesPerSec(data.network_tx_bytes_per_sec);
        const dot = section.querySelector(".worker-status-dot");
        if (dot) {
          const online = data.status === "online";
          dot.className = online
            ? "listen-dot worker-status-dot"
            : "worker-dot-offline worker-status-dot";
          dot.title = online ? "Online" : "Offline";
        }
      });
    }

    async function pollWorkerStats() {
      try {
        const response = await fetch("/orchestrator/ui/workers/stats");
        if (response.ok) {
          renderWorkerStats(await response.json());
        }
      } catch {
        /* ignore */
      }
      setTimeout(pollWorkerStats, 3000);
    }
    pollWorkerStats();
  }

  if (document.querySelector(".gateway-tile-deleting")) {
    setTimeout(() => window.location.reload(), 3000);
  }

  const peerGroupModal = document.getElementById("peer-group-modal");
  const peerGroupWorkerSelect = peerGroupModal?.querySelector('select[name="worker_id"]');
  const openPeerGroup = (workerId) => {
    if (peerGroupWorkerSelect && workerId) {
      peerGroupWorkerSelect.value = String(workerId);
    }
    peerGroupModal?.showModal();
  };
  document.getElementById("btn-new-peer-group")?.addEventListener("click", () => openPeerGroup());
  document.querySelectorAll(".btn-new-peer-group-worker").forEach((btn) => {
    btn.addEventListener("click", () => openPeerGroup(btn.dataset.workerId));
  });
  wireDialogClose(peerGroupModal, document.getElementById("peer-group-modal-close"));

  const renamePeerGroupModal = document.getElementById("rename-peer-group-modal");
  const renamePeerGroupForm = document.getElementById("rename-peer-group-form");
  const renamePeerGroupInput = document.getElementById("rename-peer-group-input");
  document.querySelectorAll(".btn-rename-peer-group").forEach((btn) => {
    btn.addEventListener("click", () => {
      const groupId = btn.dataset.groupId;
      if (!renamePeerGroupForm || !renamePeerGroupInput || !groupId) return;
      renamePeerGroupForm.action = `/orchestrator/ui/peer-groups/${groupId}/rename`;
      renamePeerGroupInput.value = btn.dataset.groupName || "";
      renamePeerGroupModal?.showModal();
      renamePeerGroupInput.focus();
      renamePeerGroupInput.select();
    });
  });
  wireDialogClose(renamePeerGroupModal, document.getElementById("rename-peer-group-close"));

  const renameGatewayModal = document.getElementById("rename-gateway-modal");
  const renameGatewayForm = document.getElementById("rename-gateway-form");
  const renameGatewayInput = document.getElementById("rename-gateway-input");
  document.querySelectorAll(".btn-rename-gateway").forEach((btn) => {
    btn.addEventListener("click", (event) => {
      event.preventDefault();
      event.stopPropagation();
      const gatewayId = btn.dataset.gatewayId;
      if (!renameGatewayForm || !renameGatewayInput || !gatewayId) return;
      renameGatewayForm.action = `/orchestrator/ui/gateways/${gatewayId}/tailscale-name`;
      renameGatewayInput.value = btn.dataset.gatewayName || "";
      renameGatewayModal?.showModal();
      renameGatewayInput.focus();
      renameGatewayInput.select();
    });
  });
  wireDialogClose(renameGatewayModal, document.getElementById("rename-gateway-close"));

  document.querySelectorAll(".btn-restart-gateway").forEach((btn) => {
    btn.addEventListener("click", (event) => {
      event.preventDefault();
      event.stopPropagation();
      const tile = btn.closest(".gateway-tile");
      const overlay = tile?.querySelector(".gateway-restart-overlay");
      if (!overlay) return;
      overlay.hidden = false;
    });
  });
  document.querySelectorAll(".gateway-restart-cancel").forEach((btn) => {
    btn.addEventListener("click", () => {
      const overlay = btn.closest(".gateway-restart-overlay");
      if (overlay) overlay.hidden = true;
    });
  });

  async function pollGatewayBootStatus(gatewayId, timeoutMs = 180000) {
    const deadline = Date.now() + timeoutMs;
    while (Date.now() < deadline) {
      const response = await fetch(`/orchestrator/ui/gateways/${gatewayId}/boot-status`, {
        headers: { Accept: "application/json" },
      });
      if (!response.ok) {
        throw new Error("Could not read gateway status");
      }
      const data = await response.json();
      if (data.ready) return data;
      await new Promise((resolve) => setTimeout(resolve, 2000));
    }
    throw new Error("Gateway restart timed out");
  }

  document.querySelectorAll(".gateway-restart-form").forEach((form) => {
    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      const tile = form.closest(".gateway-tile");
      const confirmOverlay = tile?.querySelector(".gateway-restart-overlay");
      const progressOverlay = tile?.querySelector(".gateway-tile-restart-progress");
      const match = form.action.match(/\/gateways\/(\d+)\/restart$/);
      const gatewayId = match?.[1];
      if (!tile || !progressOverlay || !gatewayId) return;

      confirmOverlay.hidden = true;
      tile.classList.add("gateway-tile-restarting");
      progressOverlay.hidden = false;

      try {
        const response = await fetch(form.action, {
          method: "POST",
          body: new FormData(form),
          headers: { Accept: "application/json" },
        });
        const payload = await response.json().catch(() => ({}));
        if (!response.ok || !payload.ok) {
          throw new Error(payload.error || "Gateway restart failed");
        }
        await pollGatewayBootStatus(gatewayId);
        window.location.reload();
      } catch (error) {
        tile.classList.remove("gateway-tile-restarting");
        progressOverlay.hidden = true;
        const message = error instanceof Error ? error.message : "Gateway restart failed";
        window.alert(message);
      }
    });
  });
})();
