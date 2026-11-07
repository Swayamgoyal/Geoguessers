// Input: wheel (zoom about the cursor; trackpad pinch arrives as ctrl+wheel), pointer drag (pan), two-pointer pinch
// (zoom about the midpoint, commits at once on release), Shift + drag (box zoom), double click (zoom in ×2), keyboard
// (+ / − zoom about the centre, arrows pan a quarter view, Backspace = back). The debounce lives in Viewer.

export function attachGestures(canvas, v, policy) {
  const pos = (e) => {
    const r = canvas.getBoundingClientRect();
    return [e.clientX - r.left, e.clientY - r.top];
  };

  canvas.addEventListener("wheel", (e) => {
    e.preventDefault();
    const scale = e.deltaMode === 1 ? 16 : e.deltaMode === 2 ? 800 : 1;   // lines / pages -> pixels
    const dy = e.deltaY * scale;
    const [x, y] = pos(e);
    v.zoomAt(Math.exp(dy * policy.wheelZoomRate), x, y);
  }, { passive: false });

  const pointers = new Map();
  let mode = null;            // "pan" | "pinch" | "box"
  let last = null, pinch0 = null;

  canvas.addEventListener("pointerdown", (e) => {
    canvas.setPointerCapture(e.pointerId);
    pointers.set(e.pointerId, pos(e));
    if (pointers.size === 1) {
      if (e.shiftKey) {
        mode = "box";
        const [x, y] = pos(e);
        v.box = { x0: x, y0: y, x1: x, y1: y };
      } else {
        mode = "pan";
        last = pos(e);
        canvas.classList.add("dragging");
      }
    } else if (pointers.size === 2) {
      mode = "pinch";
      const [a, b] = [...pointers.values()];
      pinch0 = { d: Math.hypot(a[0] - b[0], a[1] - b[1]), m: [(a[0] + b[0]) / 2, (a[1] + b[1]) / 2] };
    }
  });

  canvas.addEventListener("pointermove", (e) => {
    if (!pointers.has(e.pointerId)) {
      v.cursor = pos(e);
      v.emitCursor && v.emitCursor();
      return;
    }
    pointers.set(e.pointerId, pos(e));
    v.cursor = pos(e);
    if (mode === "pan") {
      const p = pos(e);
      v.panBy(p[0] - last[0], p[1] - last[1]);
      last = p;
    } else if (mode === "box") {
      const [x, y] = pos(e);
      v.box.x1 = x;
      v.box.y1 = y;
      v.dirty = true;
    } else if (mode === "pinch" && pointers.size === 2) {
      const [a, b] = [...pointers.values()];
      const d = Math.hypot(a[0] - b[0], a[1] - b[1]), m = [(a[0] + b[0]) / 2, (a[1] + b[1]) / 2];
      v.panBy(m[0] - pinch0.m[0], m[1] - pinch0.m[1]);
      v.zoomAt(pinch0.d / Math.max(d, 1), m[0], m[1]);
      pinch0 = { d, m };
    }
  });

  const end = (e) => {
    if (!pointers.has(e.pointerId)) return;
    pointers.delete(e.pointerId);
    if (mode === "box" && v.box) {
      const b = v.box;
      v.box = null;
      v.dirty = true;
      v.boxZoom(b);
    } else if (mode === "pinch" && pointers.size < 2) {
      v.commitNow();                                   // pinch end commits at once
    }
    if (pointers.size === 0) {
      mode = null;
      canvas.classList.remove("dragging");
    } else if (pointers.size === 1) {
      mode = "pan";
      last = [...pointers.values()][0];
    }
  };
  canvas.addEventListener("pointerup", end);
  canvas.addEventListener("pointercancel", end);

  canvas.addEventListener("dblclick", (e) => {
    const [x, y] = pos(e);
    v.zoomAt(0.5, x, y);
  });

  window.addEventListener("keydown", (e) => {
    if (e.target && ["INPUT", "SELECT", "TEXTAREA"].includes(e.target.tagName)) return;
    const c = v.camera;
    if (e.key === "+" || e.key === "=") v.zoomAt(0.7, c.width / 2, c.height / 2);
    else if (e.key === "-" || e.key === "_") v.zoomAt(1 / 0.7, c.width / 2, c.height / 2);
    else if (e.key === "ArrowLeft") v.panBy(c.width / 4, 0);
    else if (e.key === "ArrowRight") v.panBy(-c.width / 4, 0);
    else if (e.key === "ArrowUp") v.panBy(0, c.height / 4);
    else if (e.key === "ArrowDown") v.panBy(0, -c.height / 4);
    else if (e.key === "Backspace") v.back();
    else return;
    e.preventDefault();
  });
}
