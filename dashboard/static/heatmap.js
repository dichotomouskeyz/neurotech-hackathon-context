/**
 * 2D Brain Hemodynamic Heatmap for Openwater Open-Motion Headset
 *
 * Visualizes 16 optical camera channels (8 Left module, 8 Right module)
 * measuring cortical blood flow index (BFI) and blood volume index (BVI)
 * across the prefrontal cortex with continuous 2D spatial interpolation.
 *
 * Supports:
 * - Dual projections: forehead-focused axial 10-20 and coronal frontal PFC
 * - Real-time Gaussian interpolation on HTML5 Canvas
 * - A soft prefrontal field. Nothing is clipped to a circle or a head oval.
 * - Multiple metrics: BFI, BVI, Hemispheric Asymmetry [(R - L)/(R + L)]
 * - Scientific colormaps: Turbo, Viridis (default), Coolwarm
 * - Interactive optode inspection, gain mapping & contact quality gating
 */

"use strict";

(function (root, factory) {
  if (typeof define === "function" && define.amd) {
    define([], factory);
  } else if (typeof module === "object" && module.exports) {
    module.exports = factory();
  } else {
    root.BrainHeatmap = factory();
  }
})(typeof self !== "undefined" ? self : this, function () {

  // Colormap generator tables (256 RGB tuples)
  const COLORMAPS = {
    turbo: (function () {
      const lut = new Uint8Array(256 * 3);
      for (let i = 0; i < 256; i++) {
        const x = i / 255;
        // Polynomial approximation of Google Turbo colormap
        const r = Math.round(255 * Math.min(1, Math.max(0,
          0.1357 + x * (4.5974 - x * (42.3277 - x * (130.5887 - x * (150.5667 - x * 58.1375))))
        )));
        const g = Math.round(255 * Math.min(1, Math.max(0,
          0.0914 + x * (2.1856 + x * (4.8052 - x * (14.0195 - x * (4.2109 - x * 2.7747))))
        )));
        const b = Math.round(255 * Math.min(1, Math.max(0,
          0.1067 + x * (12.5833 - x * (78.0189 - x * (128.6662 - x * (83.6714 - x * 20.8365))))
        )));
        lut[i * 3] = r;
        lut[i * 3 + 1] = g;
        lut[i * 3 + 2] = b;
      }
      return lut;
    })(),

    viridis: (function () {
      const lut = new Uint8Array(256 * 3);
      // Key anchors for viridis
      const anchors = [
        [68, 1, 84],
        [72, 35, 116],
        [64, 67, 135],
        [52, 94, 141],
        [41, 120, 142],
        [32, 144, 140],
        [34, 167, 132],
        [68, 190, 112],
        [121, 209, 81],
        [189, 222, 38],
        [253, 231, 37]
      ];
      for (let i = 0; i < 256; i++) {
        const t = (i / 255) * (anchors.length - 1);
        const idx = Math.floor(t);
        const frac = t - idx;
        const c1 = anchors[idx];
        const c2 = anchors[Math.min(idx + 1, anchors.length - 1)];
        lut[i * 3] = Math.round(c1[0] + frac * (c2[0] - c1[0]));
        lut[i * 3 + 1] = Math.round(c1[1] + frac * (c2[1] - c1[1]));
        lut[i * 3 + 2] = Math.round(c1[2] + frac * (c2[2] - c1[2]));
      }
      return lut;
    })(),

    coolwarm: (function () {
      const lut = new Uint8Array(256 * 3);
      // Blue -> Light Gray/White -> Red
      for (let i = 0; i < 256; i++) {
        const t = i / 255;
        let r, g, b;
        if (t < 0.5) {
          const u = t * 2; // 0 to 1
          r = Math.round(59 + u * (220 - 59));
          g = Math.round(76 + u * (220 - 76));
          b = Math.round(192 + u * (220 - 192));
        } else {
          const u = (t - 0.5) * 2; // 0 to 1
          r = Math.round(220 + u * (180 - 220));
          g = Math.round(220 - u * (220 - 24));
          b = Math.round(220 - u * (220 - 43));
        }
        lut[i * 3] = r;
        lut[i * 3 + 1] = g;
        lut[i * 3 + 2] = b;
      }
      return lut;
    })()
  };

  // Second toolbar option. Turbo stays available; this is only the load default.
  const DEFAULT_COLORMAP = "viridis";

  // Hardware sensor specs from Openwater Open-Motion
  // 8 cameras per module. Analog gain: [16, 4, 2, 1, 1, 2, 4, 16]
  // Layout on each module (cam number):
  //   1 lateral-superior | 8 medial-superior
  //   2                  | 7
  //   3                  | 6
  //   4 lateral-inferior | 5 medial-inferior
  // Each camera gets its own placement. Sharing one region name across a
  // column made two different optodes read as the same site.
  const CAMERA_GAINS = [16, 4, 2, 1, 1, 2, 4, 16];
  const CAMERA_PLACEMENT = [
    "lateral superior",
    "lateral upper-mid",
    "lateral lower-mid",
    "lateral inferior",
    "medial inferior",
    "medial lower-mid",
    "medial upper-mid",
    "medial superior"
  ];

  // Normalized 2D coordinates. Both views are framed on the forehead, which
  // is the only scalp Open-Motion measures. Axial is a zoomed top-down 10-20
  // view with nasion toward the top. Medial cameras sit slightly anterior of
  // the lateral ones so the cloud follows the brow instead of a rectangle.
  // Posterior sites (Cz, Pz, Oz) are outside this frame.
  // Frontal is the same two modules face-on.
  const SENSOR_GEOMETRY = {
    axial: {
      left: [
        { id: "L1", cam: 1, x: 0.31, y: 0.70, gain: 16, col: "outer", row: 0 },
        { id: "L2", cam: 2, x: 0.27, y: 0.57, gain: 4,  col: "outer", row: 1 },
        { id: "L3", cam: 3, x: 0.26, y: 0.44, gain: 2,  col: "outer", row: 2 },
        { id: "L4", cam: 4, x: 0.30, y: 0.32, gain: 1,  col: "outer", row: 3 },
        { id: "L5", cam: 5, x: 0.43, y: 0.28, gain: 1,  col: "inner", row: 3 },
        { id: "L6", cam: 6, x: 0.44, y: 0.41, gain: 2,  col: "inner", row: 2 },
        { id: "L7", cam: 7, x: 0.45, y: 0.54, gain: 4,  col: "inner", row: 1 },
        { id: "L8", cam: 8, x: 0.45, y: 0.67, gain: 16, col: "inner", row: 0 }
      ],
      right: [
        { id: "R1", cam: 1, x: 0.69, y: 0.70, gain: 16, col: "outer", row: 0 },
        { id: "R2", cam: 2, x: 0.73, y: 0.57, gain: 4,  col: "outer", row: 1 },
        { id: "R3", cam: 3, x: 0.74, y: 0.44, gain: 2,  col: "outer", row: 2 },
        { id: "R4", cam: 4, x: 0.70, y: 0.32, gain: 1,  col: "outer", row: 3 },
        { id: "R5", cam: 5, x: 0.57, y: 0.28, gain: 1,  col: "inner", row: 3 },
        { id: "R6", cam: 6, x: 0.56, y: 0.41, gain: 2,  col: "inner", row: 2 },
        { id: "R7", cam: 7, x: 0.55, y: 0.54, gain: 4,  col: "inner", row: 1 },
        { id: "R8", cam: 8, x: 0.55, y: 0.67, gain: 16, col: "inner", row: 0 }
      ],
      landmarks: [
        { label: "Nz", x: 0.50, y: 0.075 },
        { label: "Fp1", x: 0.20, y: 0.24 },
        { label: "Fpz", x: 0.50, y: 0.16 },
        { label: "Fp2", x: 0.80, y: 0.24 },
        { label: "F7", x: 0.13, y: 0.50 },
        { label: "F8", x: 0.87, y: 0.50 },
        { label: "F3", x: 0.22, y: 0.82 },
        { label: "Fz", x: 0.50, y: 0.84 },
        { label: "F4", x: 0.78, y: 0.82 }
      ]
    },

    frontal: {
      left: [
        { id: "L1", cam: 1, x: 0.24, y: 0.30, gain: 16, col: "outer", row: 0 },
        { id: "L2", cam: 2, x: 0.24, y: 0.44, gain: 4,  col: "outer", row: 1 },
        { id: "L3", cam: 3, x: 0.24, y: 0.58, gain: 2,  col: "outer", row: 2 },
        { id: "L4", cam: 4, x: 0.24, y: 0.72, gain: 1,  col: "outer", row: 3 },
        { id: "L8", cam: 8, x: 0.40, y: 0.30, gain: 16, col: "inner", row: 0 },
        { id: "L7", cam: 7, x: 0.40, y: 0.44, gain: 4,  col: "inner", row: 1 },
        { id: "L6", cam: 6, x: 0.40, y: 0.58, gain: 2,  col: "inner", row: 2 },
        { id: "L5", cam: 5, x: 0.40, y: 0.72, gain: 1,  col: "inner", row: 3 }
      ],
      right: [
        { id: "R8", cam: 8, x: 0.60, y: 0.30, gain: 16, col: "inner", row: 0 },
        { id: "R7", cam: 7, x: 0.60, y: 0.44, gain: 4,  col: "inner", row: 1 },
        { id: "R6", cam: 6, x: 0.60, y: 0.58, gain: 2,  col: "inner", row: 2 },
        { id: "R5", cam: 5, x: 0.60, y: 0.72, gain: 1,  col: "inner", row: 3 },
        { id: "R1", cam: 1, x: 0.76, y: 0.30, gain: 16, col: "outer", row: 0 },
        { id: "R2", cam: 2, x: 0.76, y: 0.44, gain: 4,  col: "outer", row: 1 },
        { id: "R3", cam: 3, x: 0.76, y: 0.58, gain: 2,  col: "outer", row: 2 },
        { id: "R4", cam: 4, x: 0.76, y: 0.72, gain: 1,  col: "outer", row: 3 }
      ],
      landmarks: [
        { label: "L superior", x: 0.24, y: 0.22 },
        { label: "L frontopolar", x: 0.32, y: 0.80 },
        { label: "R frontopolar", x: 0.68, y: 0.80 },
        { label: "R superior", x: 0.76, y: 0.22 }
      ]
    }
  };

  // Gaussian extent in normalized canvas units. Wide enough that neighboring
  // cameras become one scalp field, narrow enough that the brow row stays
  // distinct from the hairline row. fissure is the longitudinal darkening,
  // in the same units, and it does not mask pixels out.
  const FIELD_KERNEL = {
    axial: { sigmaX: 0.09, sigmaY: 0.074, fissure: 0.024, fissureDepth: 0.2 },
    frontal: { sigmaX: 0.086, sigmaY: 0.078, fissure: 0.026, fissureDepth: 0.18 }
  };

  function finiteUnit(value) {
    if (typeof value !== "number" || !Number.isFinite(value) || value < 0 || value > 1) {
      return null;
    }
    return value;
  }

  class BrainHeatmap {
    constructor(canvas, options = {}) {
      this.canvas = canvas;
      this.ctx = canvas.getContext("2d");
      this.container = options.container || canvas.parentElement;
      this.tooltipEl = options.tooltipEl || null;

      // Settings
      this.projection = options.projection || "axial"; // 'axial' | 'frontal'
      this.metric = options.metric || "bfi";           // 'bfi' | 'bvi' | 'asym'
      this.colormap = options.colormap || DEFAULT_COLORMAP;
      // Map to restore when leaving laterality. Coolwarm stays the asymmetry map.
      this._colormapBeforeAsym = null;
      this.showOptodes = options.showOptodes !== undefined ? options.showOptodes : true;
      this.autoscale = options.autoscale !== undefined ? options.autoscale : true;

      // Dynamic scales (smooth damped min/max)
      this.scale = {
        bfi: { min: 0.2, max: 5.5, currentMin: 0.5, currentMax: 4.5 },
        bvi: { min: 4.0, max: 8.5, currentMin: 4.5, currentMax: 8.0 },
        asym: { min: -25.0, max: 25.0, currentMin: -20.0, currentMax: 20.0 }
      };

      // Sensor state
      this.latestData = {
        bfi: { left: Array(8).fill(null), right: Array(8).fill(null) },
        bvi: { left: Array(8).fill(null), right: Array(8).fill(null) },
        // null until a cq frame arrives. 1.0 here used to paint every optode
        // as 100% contact before any measurement.
        cq: { left: null, right: null }
      };

      // Offscreen interpolation grid. Sized to the view aspect in ensureGrid
      // so the upscale does not stretch blocks sideways.
      this.gridWidth = 0;
      this.gridHeight = 0;
      this.offscreenCanvas = document.createElement("canvas");
      this.offscreenCtx = this.offscreenCanvas.getContext("2d");
      this.gridImageData = null;

      // Mouse interaction
      this.hoveredOptode = null;
      this.mousePos = { x: -1, y: -1 };

      // Stats callbacks
      this.onStatsUpdate = options.onStatsUpdate || null;

      this.initEvents();
      this.resize();
      this.render();
    }

    initEvents() {
      // Resize observer
      if (window.ResizeObserver) {
        this.resizeObserver = new ResizeObserver(() => this.resize());
        this.resizeObserver.observe(this.container || this.canvas);
      } else {
        window.addEventListener("resize", () => this.resize());
      }

      // Mousemove for optode inspection & tooltip
      this.canvas.addEventListener("mousemove", (e) => this.handleMouseMove(e));
      this.canvas.addEventListener("mouseleave", () => this.handleMouseLeave());
    }

    resize() {
      // The canvas is taken out of flow (see styles.css). Size the bitmap
      // from the container's content box and do not write canvas style
      // width/height. getBoundingClientRect() includes the border, and
      // copying that onto an in-flow canvas grew the card by a few pixels
      // on every ResizeObserver callback.
      const el = this.container || this.canvas;
      const width = Math.floor(el.clientWidth);
      const height = Math.floor(el.clientHeight);
      if (width < 2 || height < 2) return;

      const dpr = window.devicePixelRatio || 1;
      const bw = Math.max(1, Math.floor(width * dpr));
      const bh = Math.max(1, Math.floor(height * dpr));
      if (this.canvas.width === bw && this.canvas.height === bh &&
          this.viewWidth === width && this.viewHeight === height) {
        return;
      }
      this.viewWidth = width;
      this.viewHeight = height;
      this.canvas.width = bw;
      this.canvas.height = bh;
      this.ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      this.ensureGrid();
      this.render();
    }

    ensureGrid() {
      const aspect = Math.max(0.5, (this.viewWidth || 640) / (this.viewHeight || 420));
      const budget = 22000;
      let gh = Math.round(Math.sqrt(budget / aspect));
      let gw = Math.round(gh * aspect);
      gh = Math.max(72, Math.min(150, gh));
      gw = Math.max(96, Math.min(340, gw));
      if (gw === this.gridWidth && gh === this.gridHeight && this.gridImageData) return;
      this.gridWidth = gw;
      this.gridHeight = gh;
      this.offscreenCanvas.width = gw;
      this.offscreenCanvas.height = gh;
      this.gridImageData = this.offscreenCtx.createImageData(gw, gh);
    }

    setProjection(projection) {
      if (this.projection !== projection && SENSOR_GEOMETRY[projection]) {
        this.projection = projection;
        this.render();
      }
    }

    setMetric(metric) {
      if (this.metric === metric) return;
      const previous = this.metric;
      this.metric = metric;
      // Laterality is a signed contrast, so it still switches to coolwarm.
      // Leaving it restores the map in use before that switch. On a fresh
      // load that map is viridis, not turbo.
      if (metric === "asym") {
        if (this.colormap !== "coolwarm") {
          this._colormapBeforeAsym = this.colormap;
          this.setColormap("coolwarm");
        }
      } else if (previous === "asym" && this.colormap === "coolwarm") {
        this.setColormap(this._colormapBeforeAsym || DEFAULT_COLORMAP);
      }
      this.render();
    }

    setColormap(colormap) {
      if (COLORMAPS[colormap]) {
        this.colormap = colormap;
        this.render();
      }
    }

    setShowOptodes(show) {
      this.showOptodes = !!show;
      this.render();
    }

    setAutoscale(autoscale) {
      this.autoscale = !!autoscale;
      this.render();
    }

    update(frame) {
      if (!frame || !frame.type) return;

      if (frame.type === "bfi" || frame.type === "bvi") {
        if (Array.isArray(frame.left)) {
          this.latestData[frame.type].left = frame.left.slice();
        }
        if (Array.isArray(frame.right)) {
          this.latestData[frame.type].right = frame.right.slice();
        }
        this.updateStats();
        // bfi and bvi both arrive at 40 Hz. Repaint only the metric on screen.
        const shown = this.metric === "asym" ? "bfi" : this.metric;
        if (frame.type === shown) this.render();
      } else if (frame.type === "cq") {
        // null is a real "no measurement" value. Only a finite 0..1 score
        // is contact. Anything else stays unknown rather than becoming 1.
        if ("left" in frame) this.latestData.cq.left = finiteUnit(frame.left);
        if ("right" in frame) this.latestData.cq.right = finiteUnit(frame.right);
        this.render();
      }
    }

    updateStats() {
      const bfiL = this.latestData.bfi.left.filter((x) => x !== null && !isNaN(x));
      const bfiR = this.latestData.bfi.right.filter((x) => x !== null && !isNaN(x));
      const bviL = this.latestData.bvi.left.filter((x) => x !== null && !isNaN(x));
      const bviR = this.latestData.bvi.right.filter((x) => x !== null && !isNaN(x));

      const meanBfiL = bfiL.length ? bfiL.reduce((a, b) => a + b, 0) / bfiL.length : null;
      const meanBfiR = bfiR.length ? bfiR.reduce((a, b) => a + b, 0) / bfiR.length : null;
      const meanBviL = bviL.length ? bviL.reduce((a, b) => a + b, 0) / bviL.length : null;
      const meanBviR = bviR.length ? bviR.reduce((a, b) => a + b, 0) / bviR.length : null;

      let asymIndex = null;
      if (meanBfiL !== null && meanBfiR !== null && meanBfiL + meanBfiR > 0) {
        // Laterality index: (R - L) / (R + L) * 100%
        asymIndex = ((meanBfiR - meanBfiL) / (meanBfiR + meanBfiL)) * 100;
      }

      // Smooth autoscale dampening
      if (this.autoscale) {
        const curMetric = this.metric === "asym" ? "bfi" : this.metric;
        const allVals = [
          ...this.latestData[curMetric].left,
          ...this.latestData[curMetric].right
        ].filter((x) => x !== null && !isNaN(x));

        if (allVals.length > 4) {
          allVals.sort((a, b) => a - b);
          const p10 = allVals[Math.floor(allVals.length * 0.05)];
          const p90 = allVals[Math.floor(allVals.length * 0.95)];
          const span = Math.max(0.5, p90 - p10);
          const targetMin = Math.max(0, p10 - span * 0.15);
          const targetMax = p90 + span * 0.15;

          const s = this.scale[curMetric];
          // Damped exponential moving average (alpha = 0.15)
          s.currentMin = s.currentMin * 0.85 + targetMin * 0.15;
          s.currentMax = s.currentMax * 0.85 + targetMax * 0.15;
        }
      }

      if (this.onStatsUpdate) {
        this.onStatsUpdate({
          metric: this.metric,
          meanL: this.metric === "bvi" ? meanBviL : meanBfiL,
          meanR: this.metric === "bvi" ? meanBviR : meanBfiR,
          asym: asymIndex,
          scaleMin: this.getScaleRange().min,
          scaleMax: this.getScaleRange().max
        });
      }
    }

    getScaleRange() {
      if (this.metric === "asym") {
        return { min: -25.0, max: 25.0 };
      }
      const s = this.scale[this.metric];
      return {
        min: this.autoscale ? s.currentMin : s.min,
        max: this.autoscale ? s.currentMax : s.max
      };
    }

    getSensorValues() {
      const curMetric = this.metric === "asym" ? "bfi" : this.metric;
      const leftRaw = this.latestData[curMetric].left;
      const rightRaw = this.latestData[curMetric].right;

      // Calculate baseline mean for asymmetry contrast if needed
      const bfiL = this.latestData.bfi.left.filter((v) => v !== null && !isNaN(v));
      const bfiR = this.latestData.bfi.right.filter((v) => v !== null && !isNaN(v));
      const meanL = bfiL.length ? bfiL.reduce((a, b) => a + b, 0) / bfiL.length : 2.5;
      const meanR = bfiR.length ? bfiR.reduce((a, b) => a + b, 0) / bfiR.length : 2.5;
      const globalMean = (meanL + meanR) / 2 || 2.5;

      const geom = SENSOR_GEOMETRY[this.projection];
      const sensors = [];

      // Map Left module cameras
      geom.left.forEach((s) => {
        const camIdx = s.cam - 1;
        const val = leftRaw[camIdx];
        let displayVal = val;
        if (this.metric === "asym") {
          displayVal = val !== null ? ((val - globalMean) / globalMean) * 100 : null;
        }
        sensors.push({
          ...s,
          side: "left",
          value: displayVal,
          rawVal: val,
          cq: this.latestData.cq.left
        });
      });

      // Map Right module cameras
      geom.right.forEach((s) => {
        const camIdx = s.cam - 1;
        const val = rightRaw[camIdx];
        let displayVal = val;
        if (this.metric === "asym") {
          displayVal = val !== null ? ((val - globalMean) / globalMean) * 100 : null;
        }
        sensors.push({
          ...s,
          side: "right",
          value: displayVal,
          rawVal: val,
          cq: this.latestData.cq.right
        });
      });

      return sensors;
    }

    // Continuous field. Alpha follows distance from the cameras, so the color
    // fades out past the forehead instead of being cut into a silhouette.
    computeHeatmapGrid(sensors) {
      const validSensors = sensors.filter((s) => s.value !== null && !isNaN(s.value));
      if (!validSensors.length) return false;
      this.ensureGrid();
      if (!this.gridImageData) return false;

      const { min: rangeMin, max: rangeMax } = this.getScaleRange();
      const lut = COLORMAPS[this.colormap] || COLORMAPS[DEFAULT_COLORMAP];
      const kernel = FIELD_KERNEL[this.projection] || FIELD_KERNEL.axial;
      const gw = this.gridWidth;
      const gh = this.gridHeight;
      const data = this.gridImageData.data;
      data.fill(0);

      const sensorPts = validSensors.map((s) => ({ nx: s.x, ny: s.y, val: s.value }));
      const invTwoSigmaX = 1 / (2 * kernel.sigmaX * kernel.sigmaX);
      const invTwoSigmaY = 1 / (2 * kernel.sigmaY * kernel.sigmaY);
      const range = (rangeMax - rangeMin) || 1;
      const fissureInv = kernel.fissure > 0 ? 1 / (2 * kernel.fissure * kernel.fissure) : 0;

      let idx = 0;
      for (let gy = 0; gy < gh; gy++) {
        const ny = (gy + 0.5) / gh;
        for (let gx = 0; gx < gw; gx++) {
          const nx = (gx + 0.5) / gw;
          let sumW = 0;
          let sumV = 0;
          let maxW = 0;

          for (let i = 0; i < sensorPts.length; i++) {
            const sp = sensorPts[i];
            const dx = nx - sp.nx;
            const dy = ny - sp.ny;
            const w = Math.exp(-dx * dx * invTwoSigmaX - dy * dy * invTwoSigmaY);
            if (w < 0.004) continue;
            sumW += w;
            sumV += w * sp.val;
            if (w > maxW) maxW = w;
          }

          // Interior of the camera cloud stays opaque. The edge feathers
          // where every camera's weight has fallen off.
          let cover = (maxW - 0.06) / 0.42;
          if (cover <= 0) {
            idx += 4;
            continue;
          }
          if (cover > 1) cover = 1;
          cover = cover * cover * (3 - 2 * cover);

          const finalVal = sumV / sumW;
          const norm = Math.max(0, Math.min(1, (finalVal - rangeMin) / range));
          const lutOffset = Math.floor(norm * 255) * 3;

          let shade = 1;
          if (fissureInv) {
            const fx = nx - 0.5;
            shade = 1 - kernel.fissureDepth * Math.exp(-fx * fx * fissureInv);
          }

          data[idx] = Math.round(lut[lutOffset] * shade);
          data[idx + 1] = Math.round(lut[lutOffset + 1] * shade);
          data[idx + 2] = Math.round(lut[lutOffset + 2] * shade);
          data[idx + 3] = Math.round(255 * cover * 0.94);
          idx += 4;
        }
      }

      this.offscreenCtx.putImageData(this.gridImageData, 0, 0);
      return true;
    }

    render() {
      const dpr = window.devicePixelRatio || 1;
      const w = this.viewWidth || (this.canvas.width / dpr);
      const h = this.viewHeight || (this.canvas.height / dpr);
      const ctx = this.ctx;

      ctx.clearRect(0, 0, w, h);

      const sensors = this.getSensorValues();
      const hasData = this.computeHeatmapGrid(sensors);

      if (hasData) {
        ctx.save();
        ctx.imageSmoothingEnabled = true;
        ctx.imageSmoothingQuality = "high";
        ctx.drawImage(this.offscreenCanvas, 0, 0, w, h);
        ctx.restore();
      }

      this.drawAnatomicalOverlays(ctx, w, h);

      if (this.showOptodes) {
        this.drawOptodes(ctx, sensors, w, h);
      }

      if (this.hoveredOptode) {
        this.drawHoverHighlight(ctx, this.hoveredOptode, w, h);
      }
    }

    drawAnatomicalOverlays(ctx, w, h) {
      ctx.save();
      const isDark = document.documentElement.dataset.theme === "dark" ||
        (!document.documentElement.dataset.theme && window.matchMedia("(prefers-color-scheme: dark)").matches);

      const stroke = isDark ? "rgba(255, 255, 255, 0.38)" : "rgba(20, 20, 19, 0.32)";
      const strokeMuted = isDark ? "rgba(255, 255, 255, 0.22)" : "rgba(20, 20, 19, 0.2)";
      const textFill = isDark ? "rgba(255, 255, 255, 0.72)" : "rgba(20, 20, 19, 0.72)";
      const halo = isDark ? "rgba(20, 20, 19, 0.8)" : "rgba(246, 245, 242, 0.92)";

      const paintLabel = (text, x, y) => {
        ctx.lineWidth = 3;
        ctx.strokeStyle = halo;
        ctx.strokeText(text, x, y);
        ctx.fillStyle = textFill;
        ctx.fillText(text, x, y);
      };

      ctx.lineJoin = "round";
      ctx.lineCap = "round";
      ctx.strokeStyle = stroke;
      ctx.lineWidth = 1.25;

      if (this.projection === "axial") {
        // No skull oval and no clip. A short nasion tick plus the 10-20
        // names orient the forehead; the color itself is the unclipped field.
        ctx.beginPath();
        ctx.moveTo(w * 0.50, h * 0.045);
        ctx.lineTo(w * 0.50, h * 0.095);
        ctx.stroke();

        ctx.strokeStyle = strokeMuted;
        ctx.lineWidth = 1;
        ctx.setLineDash([3, 5]);
        ctx.beginPath();
        ctx.moveTo(w * 0.50, h * 0.18);
        ctx.lineTo(w * 0.50, h * 0.78);
        ctx.stroke();
        ctx.setLineDash([]);

        ctx.font = "10px Geist, system-ui, sans-serif";
        ctx.textAlign = "center";
        ctx.textBaseline = "middle";
        SENSOR_GEOMETRY.axial.landmarks.forEach((lm) => {
          paintLabel(lm.label, lm.x * w, lm.y * h);
        });
      } else {
        // Shallow hairline and two brow arches. They do not meet, so the
        // guide cannot read as a head oval, and neither path clips the field.
        ctx.beginPath();
        ctx.moveTo(w * 0.24, h * 0.13);
        ctx.quadraticCurveTo(w * 0.50, h * 0.07, w * 0.76, h * 0.13);
        ctx.stroke();

        ctx.strokeStyle = strokeMuted;
        ctx.beginPath();
        ctx.moveTo(w * 0.20, h * 0.90);
        ctx.quadraticCurveTo(w * 0.33, h * 0.82, w * 0.46, h * 0.90);
        ctx.moveTo(w * 0.54, h * 0.90);
        ctx.quadraticCurveTo(w * 0.67, h * 0.82, w * 0.80, h * 0.90);
        ctx.stroke();

        ctx.lineWidth = 1;
        ctx.setLineDash([3, 5]);
        ctx.beginPath();
        ctx.moveTo(w * 0.50, h * 0.16);
        ctx.lineTo(w * 0.50, h * 0.84);
        ctx.stroke();
        ctx.setLineDash([]);

        // Headers sit in the margin above the hairline, clear of the optodes.
        ctx.font = "600 12px Geist, system-ui, sans-serif";
        ctx.textAlign = "center";
        ctx.textBaseline = "middle";
        ctx.fillStyle = isDark ? "#82b4f5" : "#2a78d6";
        ctx.fillText("LEFT PFC", w * 0.32, h * 0.045);
        ctx.fillStyle = isDark ? "#f28b61" : "#eb6834";
        ctx.fillText("RIGHT PFC", w * 0.68, h * 0.045);
      }

      ctx.restore();
    }

    drawOptodes(ctx, sensors, w, h) {
      ctx.save();
      const isDark = document.documentElement.dataset.theme === "dark" ||
        (!document.documentElement.dataset.theme && window.matchMedia("(prefers-color-scheme: dark)").matches);

      sensors.forEach((s) => {
        const px = s.x * w;
        const py = s.y * h;
        const hasVal = s.value !== null && !isNaN(s.value);

        // Optode outer halo
        ctx.beginPath();
        ctx.arc(px, py, 11, 0, Math.PI * 2);
        ctx.fillStyle = isDark ? "rgba(20, 20, 19, 0.75)" : "rgba(255, 255, 255, 0.85)";
        ctx.fill();
        ctx.strokeStyle = s.side === "left"
          ? (isDark ? "#82b4f5" : "#2a78d6")
          : (isDark ? "#f28b61" : "#eb6834");
        ctx.lineWidth = 1.5;
        ctx.stroke();

        // Optode center dot
        ctx.beginPath();
        ctx.arc(px, py, 4, 0, Math.PI * 2);
        ctx.fillStyle = hasVal ? (s.side === "left" ? "#2a78d6" : "#eb6834") : "#999999";
        ctx.fill();

        // Channel id sits off the dot, toward the outside of its column,
        // so a neighbor's id is not drawn on top of this optode. The halo
        // keeps the id readable on the dark end of viridis.
        ctx.font = "bold 9px Geist Mono, monospace";
        ctx.textBaseline = "middle";
        ctx.lineWidth = 3;
        ctx.strokeStyle = isDark ? "rgba(20, 20, 19, 0.85)" : "rgba(255, 255, 255, 0.9)";
        ctx.fillStyle = isDark ? "#f0f0ee" : "#141413";
        const outward = s.side === "left"
          ? (s.col === "outer" ? -1 : 1)
          : (s.col === "outer" ? 1 : -1);
        ctx.textAlign = outward < 0 ? "right" : "left";
        const labelX = px + outward * 14;
        ctx.strokeText(s.id, labelX, py);
        ctx.fillText(s.id, labelX, py);

        if (this.projection === "frontal" && hasVal) {
          ctx.font = "8px Geist Mono, monospace";
          ctx.textAlign = "center";
          ctx.strokeText(s.value.toFixed(1), px, py + 16);
          ctx.fillText(s.value.toFixed(1), px, py + 16);
        }
      });

      ctx.restore();
    }

    drawHoverHighlight(ctx, optode, w, h) {
      ctx.save();
      const px = optode.x * w;
      const py = optode.y * h;

      ctx.beginPath();
      ctx.arc(px, py, 18, 0, Math.PI * 2);
      ctx.fillStyle = "rgba(42, 120, 214, 0.25)";
      ctx.fill();
      ctx.strokeStyle = "#2a78d6";
      ctx.lineWidth = 2.0;
      ctx.stroke();

      ctx.restore();
    }

    handleMouseMove(e) {
      const rect = this.canvas.getBoundingClientRect();
      const mx = e.clientX - rect.left;
      const my = e.clientY - rect.top;
      this.mousePos = { x: mx, y: my };

      const w = rect.width;
      const h = rect.height;
      const sensors = this.getSensorValues();

      let closest = null;
      let minDist = 22; // Hit radius in CSS pixels

      sensors.forEach((s) => {
        const sx = s.x * w;
        const sy = s.y * h;
        const dist = Math.hypot(mx - sx, my - sy);
        if (dist < minDist) {
          minDist = dist;
          closest = s;
        }
      });

      if (this.hoveredOptode !== closest) {
        this.hoveredOptode = closest;
        this.render();
      }

      if (closest && this.tooltipEl) {
        this.showTooltip(closest, e.clientX, e.clientY);
      } else if (this.tooltipEl) {
        this.tooltipEl.style.display = "none";
      }
    }

    handleMouseLeave() {
      this.hoveredOptode = null;
      if (this.tooltipEl) this.tooltipEl.style.display = "none";
      this.render();
    }

    showTooltip(sensor, clientX, clientY) {
      const el = this.tooltipEl;
      if (!el) return;

      const sideName = sensor.side === "left" ? "Left" : "Right";
      const place = CAMERA_PLACEMENT[sensor.cam - 1] || `camera ${sensor.cam}`;
      const valStr = sensor.value !== null && !isNaN(sensor.value)
        ? (this.metric === "asym" ? `${sensor.value > 0 ? "+" : ""}${sensor.value.toFixed(1)}%` : sensor.value.toFixed(2))
        : "No signal";
      const unitStr = this.metric === "asym" ? "Asymmetry" : (this.metric === "bfi" ? "BFI" : "BVI");
      const cqKnown = typeof sensor.cq === "number" && Number.isFinite(sensor.cq);
      const cqHtml = cqKnown
        ? `<span style="color: ${sensor.cq >= 0.7 ? "#0ca30c" : "#fab219"}">${(sensor.cq * 100).toFixed(0)}%</span>`
        : `<span>unknown</span>`;

      el.innerHTML = `
        <div class="tip-head">
          <strong>${sensor.id}</strong> ${sideName} ${place}
        </div>
        <div class="tip-row">
          <span>${unitStr}:</span>
          <strong>${valStr}</strong>
        </div>
        <div class="tip-row">
          <span>Analog Gain:</span>
          <span>${sensor.gain}x</span>
        </div>
        <div class="tip-row">
          <span>Contact Quality:</span>
          ${cqHtml}
        </div>
      `;

      el.style.display = "block";
      const rect = this.container.getBoundingClientRect();
      let left = clientX - rect.left + 14;
      let top = clientY - rect.top + 14;

      if (left + 180 > rect.width) left -= 200;
      if (top + 120 > rect.height) top -= 130;

      el.style.left = `${Math.max(8, left)}px`;
      el.style.top = `${Math.max(8, top)}px`;
    }
  }

  return BrainHeatmap;
});
