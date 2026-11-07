// Camera: the transient view state (centre in UTM metres, metres per CSS pixel), changed on every gesture event and
// redrawn every animation frame; and screen <-> world transforms. No network here.

export class Camera {
  constructor(cx = 0, cy = 0, mpp = 1) {
    this.cx = cx;
    this.cy = cy;
    this.mpp = mpp;       // metres per CSS pixel
    this.width = 1;       // view size in CSS pixels
    this.height = 1;
    this.minMpp = 0;
    this.maxMpp = Infinity;
  }

  setSize(w, h) {
    this.width = Math.max(1, w);
    this.height = Math.max(1, h);
  }

  // ground size of one device pixel used for level choice (DPR capped by the policy)
  pixelSize(dpr = 1, dprCap = 1) {
    return this.mpp / Math.min(dpr, dprCap);
  }

  bbox() {
    const hw = (this.width / 2) * this.mpp, hh = (this.height / 2) * this.mpp;
    return { x0: this.cx - hw, x1: this.cx + hw, y0: this.cy - hh, y1: this.cy + hh };
  }

  toWorld(sx, sy) {
    return [this.cx + (sx - this.width / 2) * this.mpp, this.cy - (sy - this.height / 2) * this.mpp];
  }

  toScreen(x, y) {
    return [(x - this.cx) / this.mpp + this.width / 2, (this.cy - y) / this.mpp + this.height / 2];
  }

  clampMpp(m) {
    return Math.min(this.maxMpp, Math.max(this.minMpp, m));
  }

  // zoom by `factor` (> 1 = zoom out) keeping the world point under screen point (sx, sy) fixed
  zoomAt(factor, sx, sy) {
    const [wx, wy] = this.toWorld(sx, sy);
    this.mpp = this.clampMpp(this.mpp * factor);
    this.cx = wx - (sx - this.width / 2) * this.mpp;
    this.cy = wy + (sy - this.height / 2) * this.mpp;
  }

  panBy(dsx, dsy) {
    this.cx -= dsx * this.mpp;
    this.cy += dsy * this.mpp;
  }

  // fit a world bbox into the view (with a small margin)
  fit(b, margin = 1.0) {
    this.cx = (b.x0 + b.x1) / 2;
    this.cy = (b.y0 + b.y1) / 2;
    this.mpp = this.clampMpp(margin * Math.max((b.x1 - b.x0) / this.width, (b.y1 - b.y0) / this.height));
  }

  state() {
    return { cx: this.cx, cy: this.cy, mpp: this.mpp };
  }

  set(s) {
    this.cx = s.cx;
    this.cy = s.cy;
    this.mpp = this.clampMpp(s.mpp);
  }
}
