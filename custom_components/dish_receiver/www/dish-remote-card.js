/**
 * dish-remote-card — a photo-realistic remote for a DISH receiver.
 *
 * Renders the physical DISH 54.0 remote's image with invisible clickable
 * regions positioned over each real button. Clicking a region calls
 * `remote.send_command` on the configured entity with the matching key from
 * this integration's RemoteKey vocabulary (custom_components/dish_receiver/keys.py)
 * — the same names `remote.send_command` / `dish_receiver.send_key` already
 * accept.
 *
 * Usage (Lovelace YAML):
 *   type: custom:dish-remote-card
 *   entity: remote.living_room_dish_remote
 *
 * Optional:
 *   image: /dish_receiver_static/dish-remote.png   # override the bundled photo
 *   calibrate: true                                 # start in calibration mode
 *   buttons: [...]                                   # full override of the hit-map
 *
 * Calibration: click the ⚙ in the card's corner (or set `calibrate: true`) to
 * see every hit-box outlined and labeled. Drag a box to reposition it; click
 * "Copy map" to copy the updated coordinates as JSON — paste that into
 * `buttons:` in the card config, or back into DEFAULT_BUTTONS below.
 *
 * Coordinates are percentages of the image's rendered width/height, so the
 * map holds at any card width. DEFAULT_BUTTONS was measured against the
 * bundled photo with a labeled pixel grid overlaid on the source, then
 * checked by rendering the resulting boxes back onto the photo and visually
 * confirming every one lands on its real button — not guessed. The
 * calibration tool remains for anyone who wants to fine-tune further.
 */

// key: a RemoteKey value from custom_components/dish_receiver/keys.py, or
//   null for a button that exists on the physical remote but has no working
//   IP command (Power, volume, channel step — all confirmed unavailable over
//   the network on a Wally; see tools/protocol-findings/WALLY_KEYS.md).
// x/y: center of the hit-box, percent of image width/height.
// w/h: hit-box size, percent of image width/height.
const DEFAULT_BUTTONS = [
  { key: null, label: "Power", x: 50, y: 7.4, w: 18, h: 10.3, note: "Not available over IP (IR-only)." },
  { key: null, label: "Mode", x: 65.8, y: 3.6, w: 13.5, h: 5.4, note: "Device-target switch (SAT/TV/AUX); not sent to the receiver." },
  { key: null, label: "?", x: 81.2, y: 6.3, w: 12.5, h: 5.7, note: "Function unclear from the photo." },

  { key: "dvr", label: "DVR", x: 28, y: 16.1, w: 34, h: 9.4 },
  { key: "home", label: "Home", x: 51, y: 16.1, w: 20, h: 11.1 },
  { key: "guide", label: "Guide", x: 80, y: 16.1, w: 36, h: 9.4 },

  { key: "options", label: "Options", x: 22.5, y: 20, w: 35, h: 8.6 },
  { key: "microphone", label: "Mic", x: 80, y: 20, w: 30, h: 8.6 },
  { key: "up", label: "Up", x: 50, y: 19.3, w: 15, h: 4.3 },

  { key: "left", label: "Left", x: 23.2, y: 27.1, w: 13.5, h: 6.3 },
  { key: "select", label: "Select", x: 55.5, y: 26.6, w: 23, h: 8.6 },
  { key: "right", label: "Right", x: 76.8, y: 27.1, w: 13.5, h: 6.3 },
  { key: "down", label: "Down", x: 50, y: 34.9, w: 11, h: 4.6 },

  { key: "back", label: "Back", x: 30, y: 37.1, w: 30, h: 4 },
  { key: "info", label: "Info", x: 84, y: 37.1, w: 28, h: 4 },
  { key: "live_tv", label: "Live TV", x: 30, y: 41.1, w: 30, h: 4 },
  { key: "help", label: "Help", x: 84, y: 41.1, w: 28, h: 4 },

  { key: "rewind", label: "Rewind", x: 24, y: 44.6, w: 30, h: 5.1 },
  { key: "play", label: "Play/Pause", x: 50, y: 44.6, w: 28, h: 5.1 },
  { key: "jump", label: "Jump", x: 77.5, y: 44.6, w: 30, h: 5.1 },

  { key: null, label: "Vol +", x: 29.8, y: 50.9, w: 22.5, h: 4.6, note: "Volume is TV-side; route it through your TV/AVR entity." },
  { key: null, label: "Vol −", x: 29.8, y: 58, w: 22.5, h: 4.6, note: "Volume is TV-side; route it through your TV/AVR entity." },
  { key: "recall", label: "Recall", x: 50, y: 50.9, w: 24, h: 4.6 },
  { key: null, label: "Ch +", x: 64, y: 50, w: 20, h: 4.6, note: "Not available over IP on a Wally — use tune-by-number instead." },
  { key: null, label: "Ch −", x: 64, y: 57.1, w: 20, h: 4.6, note: "Not available over IP on a Wally — use tune-by-number instead." },
  { key: "mute", label: "Mute", x: 50, y: 57.1, w: 24, h: 5.7 },

  { key: "1", label: "1", x: 30.2, y: 63.7, w: 22.5, h: 5.7 },
  { key: "2", label: "2", x: 50.2, y: 63.7, w: 22.5, h: 5.7 },
  { key: "3", label: "3", x: 70.2, y: 63.7, w: 22.5, h: 5.7 },
  { key: "4", label: "4", x: 30.2, y: 70.3, w: 22.5, h: 5.7 },
  { key: "5", label: "5", x: 50.2, y: 70.3, w: 22.5, h: 5.7 },
  { key: "6", label: "6", x: 70.2, y: 70.3, w: 22.5, h: 5.7 },
  { key: "7", label: "7", x: 30.2, y: 76.6, w: 22.5, h: 5.7 },
  { key: "8", label: "8", x: 50.2, y: 76.6, w: 22.5, h: 5.7 },
  { key: "9", label: "9", x: 70.2, y: 76.6, w: 22.5, h: 5.7 },

  { key: null, label: "◆", x: 30.2, y: 82.6, w: 22.5, h: 5.1, note: "Function/DASH not confirmed working over IP on the Wally." },
  { key: "0", label: "0", x: 50.2, y: 82.6, w: 22.5, h: 5.1 },
  { key: null, label: "◆◆", x: 70.2, y: 82.6, w: 22.5, h: 5.1, note: "Function unclear from the photo." },
];

const DEFAULT_IMAGE = "/dish_receiver_static/dish-remote.png";

class DishRemoteCard extends HTMLElement {
  setConfig(config) {
    if (!config.entity) {
      throw new Error("dish-remote-card: `entity` is required (a remote.* entity)");
    }
    this._config = config;
    this._buttons = config.buttons || DEFAULT_BUTTONS;
    this._calibrate = Boolean(config.calibrate);
    this._render();
  }

  set hass(hass) {
    this._hass = hass;
  }

  getCardSize() {
    return 8;
  }

  _render() {
    const root = this.attachShadow ? this.shadowRoot || this.attachShadow({ mode: "open" }) : this;
    root.innerHTML = `
      <style>${this._css()}</style>
      <ha-card>
        <div class="wrap">
          <img class="remote" src="${this._config.image || DEFAULT_IMAGE}" alt="DISH remote" draggable="false">
          <div class="hits"></div>
          <button class="gear" title="Calibrate button positions">⚙</button>
          <div class="toast" hidden></div>
          <div class="calpanel" hidden>
            <button class="copy">Copy map</button>
            <span class="hint">Drag a box to reposition it.</span>
          </div>
        </div>
      </ha-card>
    `;
    this._root = root;
    this._hitsEl = root.querySelector(".hits");
    this._toastEl = root.querySelector(".toast");
    this._calpanelEl = root.querySelector(".calpanel");
    root.querySelector(".gear").addEventListener("click", () => this._toggleCalibrate());
    root.querySelector(".copy").addEventListener("click", () => this._copyMap());
    this._renderButtons();
  }

  _renderButtons() {
    this._hitsEl.innerHTML = "";
    this._hitsEl.classList.toggle("calibrate", this._calibrate);
    this._calpanelEl.hidden = !this._calibrate;

    this._buttons.forEach((btn, index) => {
      const el = document.createElement("div");
      el.className = "hit" + (btn.key ? "" : " unsupported");
      el.style.left = btn.x - btn.w / 2 + "%";
      el.style.top = btn.y - btn.h / 2 + "%";
      el.style.width = btn.w + "%";
      el.style.height = btn.h + "%";
      if (this._calibrate) {
        el.textContent = btn.label;
        this._makeDraggable(el, btn);
      } else {
        el.addEventListener("click", () => this._press(btn));
      }
      this._hitsEl.appendChild(el);
    });
  }

  async _press(btn) {
    if (!btn.key) {
      this._flashToast(btn.note || `${btn.label} isn't available over IP.`, true);
      return;
    }
    try {
      await this._hass.callService("remote", "send_command", {
        entity_id: this._config.entity,
        command: [btn.key],
      });
      this._flashToast(`${btn.label} ✓`, false);
    } catch (err) {
      this._flashToast(`${btn.label}: ${(err && err.message) || "failed"}`, true);
    }
  }

  _flashToast(text, isError) {
    const t = this._toastEl;
    t.textContent = text;
    t.hidden = false;
    t.classList.toggle("err", Boolean(isError));
    clearTimeout(this._toastTimer);
    this._toastTimer = setTimeout(() => { t.hidden = true; }, 1400);
  }

  _toggleCalibrate() {
    this._calibrate = !this._calibrate;
    this._renderButtons();
  }

  _makeDraggable(el, btn) {
    el.addEventListener("pointerdown", (downEvent) => {
      downEvent.preventDefault();
      const wrap = this._root.querySelector(".wrap");
      const rect = wrap.getBoundingClientRect();
      const onMove = (moveEvent) => {
        const xPct = ((moveEvent.clientX - rect.left) / rect.width) * 100;
        const yPct = ((moveEvent.clientY - rect.top) / rect.height) * 100;
        btn.x = Math.round(Math.max(0, Math.min(100, xPct)) * 10) / 10;
        btn.y = Math.round(Math.max(0, Math.min(100, yPct)) * 10) / 10;
        el.style.left = btn.x - btn.w / 2 + "%";
        el.style.top = btn.y - btn.h / 2 + "%";
      };
      const onUp = () => {
        window.removeEventListener("pointermove", onMove);
        window.removeEventListener("pointerup", onUp);
      };
      window.addEventListener("pointermove", onMove);
      window.addEventListener("pointerup", onUp);
    });
  }

  _copyMap() {
    const json = JSON.stringify(
      this._buttons.map((b) => ({ key: b.key, label: b.label, x: b.x, y: b.y, w: b.w, h: b.h, ...(b.note ? { note: b.note } : {}) })),
      null,
      2
    );
    if (navigator.clipboard) {
      navigator.clipboard.writeText(json).then(
        () => this._flashToast("Map copied to clipboard", false),
        () => console.log("dish-remote-card button map:\n" + json)
      );
    } else {
      console.log("dish-remote-card button map:\n" + json);
      this._flashToast("Map logged to console", false);
    }
  }

  _css() {
    return `
      ha-card { overflow: hidden; }
      .wrap { position: relative; width: 100%; user-select: none; -webkit-user-select: none; }
      .remote { display: block; width: 100%; height: auto; -webkit-touch-callout: none; }
      .hits { position: absolute; inset: 0; }
      .hit {
        position: absolute; cursor: pointer; background: transparent;
        border: none; border-radius: 6px;
      }
      .hit:active { background: rgba(255,255,255,0.25); }
      .hits.calibrate .hit {
        border: 1px dashed rgba(255, 60, 60, 0.85);
        background: rgba(255, 60, 60, 0.12);
        color: #ff3c3c; font: 10px/1.2 sans-serif; text-align: center;
        display: flex; align-items: center; justify-content: center;
        cursor: grab; overflow: hidden; padding: 2px; box-sizing: border-box;
      }
      .hits.calibrate .hit.unsupported { border-color: rgba(150,150,150,0.85); color: #999; background: rgba(150,150,150,0.12); }
      .gear {
        position: absolute; top: 6px; right: 6px; z-index: 2;
        width: 28px; height: 28px; border-radius: 50%; border: none;
        background: rgba(0,0,0,0.45); color: #fff; font-size: 14px; cursor: pointer;
      }
      .toast {
        position: absolute; left: 50%; bottom: 10px; transform: translateX(-50%);
        background: rgba(0,0,0,0.8); color: #fff; padding: 6px 12px; border-radius: 8px;
        font: 12px/1.3 sans-serif; z-index: 3; pointer-events: none;
      }
      .toast.err { background: rgba(180,20,20,0.9); }
      .calpanel {
        position: absolute; top: 6px; left: 6px; z-index: 2; display: flex;
        align-items: center; gap: 8px; background: rgba(0,0,0,0.55);
        padding: 4px 8px; border-radius: 8px;
      }
      .calpanel .copy {
        border: none; border-radius: 6px; padding: 4px 8px; cursor: pointer;
        background: #fff; font: 12px/1.2 sans-serif;
      }
      .calpanel .hint { color: #fff; font: 11px/1.2 sans-serif; }
    `;
  }
}

customElements.define("dish-remote-card", DishRemoteCard);
window.customCards = window.customCards || [];
window.customCards.push({
  type: "dish-remote-card",
  name: "DISH Remote",
  description: "A photo-realistic remote mapped to your DISH receiver.",
});
