/**
 * 2D Brain Hemodynamic Heatmap for Openwater Open-Motion Headset
 *
 * Visualizes 16 optical camera channels (8 Left module, 8 Right module)
 * measuring cortical blood flow index (BFI) and blood volume index (BVI)
 * across the prefrontal cortex with continuous 2D spatial interpolation.
 *
 * Supports:
 * - Dual projections: Top-down Axial (10-20 system) & Coronal Frontal PFC
 * - Real-time continuous Gaussian/IDW interpolation on HTML5 Canvas
 * - Multiple metrics: BFI, BVI, Hemispheric Asymmetry [(R - L)/(R + L)]
 * - Scientific colormaps: Turbo, Viridis, Coolwarm
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

  // Hardware sensor specs from Openwater Open-Motion
  // 8 cameras per module. Analog gain: [16, 4, 2, 1, 1, 2, 4, 16]
  const CAMERA_GAINS = [16, 4, 2, 1, 1, 2, 4, 16];
  const CAMERA_ROLES = [
    "Outer Superior", "Inner Superior-mid", "Inner Inferior-mid", "Inner Inferior",
    "Inner Inferior", "Inner Inferior-mid", "Inner Superior-mid", "Outer Superior"
  ];

  // Normalized 2D coordinates for the two projection styles:
  // View 1: Axial (Top-down 10-20 head model, nose at top, front of head y: 0.15 .. 0.35)
  // View 2: Frontal (Coronal view of prefrontal cortex lobes, y: 0.22 .. 0.78)
  const SENSOR_GEOMETRY = {
    axial: {
      left: [
        { id: "L1", cam: 1, x: 0.33, y: 0.30, gain: 16, col: "outer", row: 0 },
        { id: "L2", cam: 2, x: 0.32, y: 0.26, gain: 4,  col: "outer", row: 1 },
        { id: "L3", cam: 3, x: 0.31, y: 0.22, gain: 2,  col: "outer", row: 2 },
        { id: "L4", cam: 4, x: 0.30, y: 0.18, gain: 1,  col: "outer", row: 3 },
        { id: "L5", cam: 5, x: 0.43, y: 0.18, gain: 1,  col: "inner", row: 3 },
        { id: "L6", cam: 6, x: 0.42, y: 0.22, gain: 2,  col: "inner", row: 2 },
        { id: "L7", cam: 7, x: 0.42, y: 0.26, gain: 4,  col: "inner", row: 1 },
        { id: "L8", cam: 8, x: 0.42, y: 0.30, gain: 16, col: "inner", row: 0 }
      ],
      right: [
        { id: "R1", cam: 1, x: 0.67, y: 0.30, gain: 16, col: "outer", row: 0 },
        { id: "R2", cam: 2, x: 0.68, y: 0.26, gain: 4,  col: "outer", row: 1 },
        { id: "R3", cam: 3, x: 0.69, y: 0.22, gain: 2,  col: "outer", row: 2 },
        { id: "R4", cam: 4, x: 0.70, y: 0.18, gain: 1,  col: "outer", row: 3 },
        { id: "R5", cam: 5, x: 0.57, y: 0.18, gain: 1,  col: "inner", row: 3 },
        { id: "R6", cam: 6, x: 0.58, y: 0.22, gain: 2,  col: "inner", row: 2 },
        { id: "R7", cam: 7, x: 0.58, y: 0.26, gain: 4,  col: "inner", row: 1 },
        { id: "R8", cam: 8, x: 0.58, y: 0.30, gain: 16, col: "inner", row: 0 }
      ],
      landmarks: [
        { label: "Nz", x: 0.50, y: 0.11 },
        { label: "Fpz", x: 0.50, y: 0.18 },
        { label: "Fp1", x: 0.37, y: 0.17 },
        { label: "Fp2", x: 0.63, y: 0.17 },
        { label: "Fz", x: 0.50, y: 0.35 },
        { label: "F3", x: 0.34, y: 0.35 },
        { label: "F4", x: 0.66, y: 0.35 },
        { label: "F7", x: 0.20, y: 0.33 },
        { label: "F8", x: 0.80, y: 0.33 },
        { label: "Cz", x: 0.50, y: 0.54 },
        { label: "Pz", x: 0.50, y: 0.74 },
        { label: "Oz", x: 0.50, y: 0.91 }
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
        { label: "Superior DLPFC", x: 0.24, y: 0.22 },
        { label: "Medial Frontopolar", x: 0.40, y: 0.80 },
        { label: "Medial Frontopolar", x: 0.60, y: 0.80 },
        { label: "Superior DLPFC", x: 0.76, y: 0.22 }
      ]
    }
  };

  class BrainHeatmap {
    constructor(canvas, options = {}) {
      this.canvas = canvas;
      this.ctx = canvas.getContext("2d");
      this.container = options.container || canvas.parentElement;
      this.tooltipEl = options.tooltipEl || null;

      // Settings
      this.projection = options.projection || "axial"; // 'axial' | 'frontal'
      this.metric = options.metric || "bfi";           // 'bfi' | 'bvi' | 'asym'
      this.colormap = options.colormap || "turbo";     // 'turbo' | 'viridis' | 'coolwarm'
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
        cq: { left: 1.0, right: 1.0 }
      };

      // Offscreen low-resolution interpolation grid
      this.gridWidth = 120;
      this.gridHeight = 90;
      this.offscreenCanvas = document.createElement("canvas");
      this.offscreenCanvas.width = this.gridWidth;
      this.offscreenCanvas.height = this.gridHeight;
      this.offscreenCtx = this.offscreenCanvas.getContext("2d");
      this.gridImageData = this.offscreenCtx.createImageData(this.gridWidth, this.gridHeight);

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
      const rect = this.container.getBoundingClientRect();
      const dpr = window.devicePixelRatio || 1;
      const width = Math.max(320, Math.floor(rect.width));
      const height = Math.max(260, Math.floor(rect.height || (width * 0.70)));

      if (this.canvas.width !== width * dpr || this.canvas.height !== height * dpr) {
        this.canvas.width = width * dpr;
        this.canvas.height = height * dpr;
        this.canvas.style.width = `${width}px`;
        this.canvas.style.height = `${height}px`;
        this.ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
        this.render();
      }
    }

    setProjection(projection) {
      if (this.projection !== projection && SENSOR_GEOMETRY[projection]) {
        this.projection = projection;
        this.render();
      }
    }

    setMetric(metric) {
      if (this.metric !== metric) {
        this.metric = metric;
        // If asymmetry is chosen, default colormap to coolwarm for intuitive R/L balance
        if (metric === "asym" && this.colormap !== "coolwarm") {
          this.setColormap("coolwarm");
        } else if (metric !== "asym" && this.colormap === "coolwarm") {
          this.setColormap("turbo");
        }
        this.render();
      }
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
        this.render();
      } else if (frame.type === "cq") {
        if (frame.left !== undefined) this.latestData.cq.left = frame.left;
        if (frame.right !== undefined) this.latestData.cq.right = frame.right;
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

    // High performance continuous 2D spatial interpolation
    computeHeatmapGrid(sensors, width, height) {
      const validSensors = sensors.filter((s) => s.value !== null && !isNaN(s.value));
      if (!validSensors.length) return false;

      const { min: rangeMin, max: rangeMax } = this.getScaleRange();
      const lut = COLORMAPS[this.colormap] || COLORMAPS.turbo;
      const gw = this.gridWidth;
      const gh = this.gridHeight;
      const data = this.gridImageData.data;

      // Mean value for background falloff
      const meanVal = validSensors.reduce((acc, s) => acc + s.value, 0) / validSensors.length;

      // Precalculate sensor grid positions
      const sensorPts = validSensors.map((s) => ({
        gx: s.x * gw,
        gy: s.y * gh,
        val: s.value
      }));

      // Interpolation tuning parameters
      const sigma = this.projection === "axial" ? 18.0 : 22.0;
      const twoSigmaSq = 2 * sigma * sigma;
      const epsilon = 1.8;
      const p = 1.35;

      let idx = 0;
      for (let gy = 0; gy < gh; gy++) {
        const ny = gy / gh;
        for (let gx = 0; gx < gw; gx++) {
          const nx = gx / gw;

          // Check if point is inside anatomical mask
          const inside = this.isInsideAnatomicalMask(nx, ny);

          if (!inside) {
            data[idx] = 0;
            data[idx + 1] = 0;
            data[idx + 2] = 0;
            data[idx + 3] = 0;
          } else {
            let sumWeight = 0;
            let sumVal = 0;

            for (let i = 0; i < sensorPts.length; i++) {
              const sp = sensorPts[i];
              const dx = gx - sp.gx;
              const dy = gy - sp.gy;
              const distSq = dx * dx + dy * dy;
              const dist = Math.sqrt(distSq);

              // Gaussian + Inverse Distance Weighting
              const w = Math.exp(-distSq / twoSigmaSq) / Math.pow(dist + epsilon, p);
              sumWeight += w;
              sumVal += w * sp.val;
            }

            let finalVal = meanVal;
            let alpha = 245;

            if (sumWeight > 0.0001) {
              const interpolated = sumVal / sumWeight;
              // Smooth relaxation to mean for points far from forehead optodes
              const distWeightNorm = Math.min(1.0, sumWeight * 12.0);
              finalVal = interpolated * distWeightNorm + meanVal * (1.0 - distWeightNorm);

              // In axial top-down view, gently attenuate alpha towards occipital/back of head
              if (this.projection === "axial") {
                const occipitalAtten = Math.max(0.2, 1.0 - (ny - 0.35) * 1.1);
                alpha = Math.round(250 * Math.min(1.0, distWeightNorm * 1.5) * occipitalAtten);
              } else {
                alpha = Math.round(245 * Math.min(1.0, distWeightNorm * 1.3));
              }
            } else {
              alpha = 30;
            }

            // Normalize through colormap
            const norm = Math.max(0, Math.min(1, (finalVal - rangeMin) / (rangeMax - rangeMin || 1)));
            const colorIdx = Math.floor(norm * 255);
            const lutOffset = colorIdx * 3;

            data[idx] = lut[lutOffset];
            data[idx + 1] = lut[lutOffset + 1];
            data[idx + 2] = lut[lutOffset + 2];
            data[idx + 3] = alpha;
          }

          idx += 4;
        }
      }

      this.offscreenCtx.putImageData(this.gridImageData, 0, 0);
      return true;
    }

    isInsideAnatomicalMask(nx, ny) {
      if (this.projection === "axial") {
        // Head oval centered at (0.5, 0.54)
        const dx = (nx - 0.5) / 0.38;
        const dy = (ny - 0.53) / 0.40;
        return (dx * dx + dy * dy) <= 1.0;
      } else {
        // Frontal view: prefrontal forehead region
        const dx = (nx - 0.5) / 0.42;
        const dy = (ny - 0.50) / 0.38;
        return (dx * dx + dy * dy) <= 1.0 && ny >= 0.16 && ny <= 0.86;
      }
    }

    render() {
      const w = this.canvas.width / (window.devicePixelRatio || 1);
      const h = this.canvas.height / (window.devicePixelRatio || 1);
      const ctx = this.ctx;

      ctx.clearRect(0, 0, w, h);

      const sensors = this.getSensorValues();
      const hasData = this.computeHeatmapGrid(sensors, w, h);

      // Render interpolated color field
      if (hasData) {
        ctx.save();
        this.clipAnatomicalPath(ctx, w, h);
        ctx.imageSmoothingEnabled = true;
        ctx.imageSmoothingQuality = "high";
        ctx.drawImage(this.offscreenCanvas, 0, 0, w, h);
        ctx.restore();
      }

      // Render anatomical contours
      this.drawAnatomicalOverlays(ctx, w, h);

      // Render optodes & sensor overlays
      if (this.showOptodes) {
        this.drawOptodes(ctx, sensors, w, h);
      }

      // Render hover highlight
      if (this.hoveredOptode) {
        this.drawHoverHighlight(ctx, this.hoveredOptode, w, h);
      }
    }

    clipAnatomicalPath(ctx, w, h) {
      ctx.beginPath();
      if (this.projection === "axial") {
        const cx = w * 0.5;
        const cy = h * 0.53;
        const rx = w * 0.38;
        const ry = h * 0.40;
        ctx.ellipse(cx, cy, rx, ry, 0, 0, Math.PI * 2);
      } else {
        const cx = w * 0.5;
        const cy = h * 0.50;
        const rx = w * 0.40;
        const ry = h * 0.35;
        ctx.ellipse(cx, cy, rx, ry, 0, 0, Math.PI * 2);
      }
      ctx.clip();
    }

    drawAnatomicalOverlays(ctx, w, h) {
      ctx.save();
      const isDark = document.documentElement.dataset.theme === "dark" ||
        (!document.documentElement.dataset.theme && window.matchMedia("(prefers-color-scheme: dark)").matches);

      const strokePrimary = isDark ? "rgba(255, 255, 255, 0.45)" : "rgba(20, 20, 19, 0.55)";
      const strokeMuted = isDark ? "rgba(255, 255, 255, 0.18)" : "rgba(20, 20, 19, 0.18)";
      const textFill = isDark ? "rgba(255, 255, 255, 0.60)" : "rgba(20, 20, 19, 0.60)";

      if (this.projection === "axial") {
        const cx = w * 0.5;
        const cy = h * 0.53;
        const rx = w * 0.38;
        const ry = h * 0.40;

        // 1. Skull outline
        ctx.strokeStyle = strokePrimary;
        ctx.lineWidth = 2.0;
        ctx.beginPath();
        ctx.ellipse(cx, cy, rx, ry, 0, 0, Math.PI * 2);
        ctx.stroke();

        // 2. Nose (triangle at top pointing up)
        const noseY = cy - ry;
        ctx.beginPath();
        ctx.moveTo(cx - 15, noseY + 2);
        ctx.lineTo(cx, noseY - 18);
        ctx.lineTo(cx + 15, noseY + 2);
        ctx.stroke();

        // 3. Left & Right ears
        ctx.beginPath();
        // Left ear
        ctx.arc(cx - rx - 2, cy, 14, Math.PI * 0.55, Math.PI * 1.45, false);
        // Right ear
        ctx.arc(cx + rx + 2, cy, 14, Math.PI * 1.55, Math.PI * 0.45, false);
        ctx.stroke();

        // 4. Longitudinal fissure & coronal reference line
        ctx.strokeStyle = strokeMuted;
        ctx.lineWidth = 1.0;
        ctx.setLineDash([4, 4]);

        // Midline (anterior-posterior)
        ctx.beginPath();
        ctx.moveTo(cx, cy - ry + 4);
        ctx.lineTo(cx, cy + ry - 4);
        ctx.stroke();

        // Coronal line (C3 - Cz - C4)
        ctx.beginPath();
        ctx.moveTo(cx - rx + 4, cy);
        ctx.lineTo(cx + rx - 4, cy);
        ctx.stroke();
        ctx.setLineDash([]);

        // 5. Prefrontal Region Boundary Highlight
        ctx.strokeStyle = isDark ? "rgba(42, 120, 214, 0.40)" : "rgba(42, 120, 214, 0.30)";
        ctx.lineWidth = 1.5;
        ctx.beginPath();
        ctx.ellipse(cx, cy - ry * 0.45, rx * 0.85, ry * 0.45, 0, 0, Math.PI * 2);
        ctx.stroke();

        // 6. 10-20 Landmark labels
        ctx.fillStyle = textFill;
        ctx.font = "10px Geist, system-ui, sans-serif";
        ctx.textAlign = "center";
        ctx.textBaseline = "middle";

        const landmarks = SENSOR_GEOMETRY.axial.landmarks;
        landmarks.forEach((lm) => {
          ctx.fillText(lm.label, lm.x * w, lm.y * h);
        });

      } else {
        // Frontal Prefrontal Coronal View
        const cx = w * 0.5;
        const cy = h * 0.50;
        const rx = w * 0.40;
        const ry = h * 0.35;

        // 1. Forehead arch boundary
        ctx.strokeStyle = strokePrimary;
        ctx.lineWidth = 2.0;
        ctx.beginPath();
        ctx.ellipse(cx, cy, rx, ry, 0, 0, Math.PI * 2);
        ctx.stroke();

        // 2. Eyebrow / supraorbital line at bottom
        ctx.strokeStyle = strokeMuted;
        ctx.lineWidth = 1.5;
        ctx.beginPath();
        ctx.moveTo(cx - rx * 0.85, cy + ry * 0.65);
        ctx.quadraticCurveTo(cx - rx * 0.45, cy + ry * 0.55, cx, cy + ry * 0.65);
        ctx.quadraticCurveTo(cx + rx * 0.45, cy + ry * 0.55, cx + rx * 0.85, cy + ry * 0.65);
        ctx.stroke();

        // 3. Longitudinal interhemispheric fissure (vertical midline)
        ctx.setLineDash([4, 4]);
        ctx.beginPath();
        ctx.moveTo(cx, cy - ry + 4);
        ctx.lineTo(cx, cy + ry - 4);
        ctx.stroke();
        ctx.setLineDash([]);

        // 4. Lobe Headers
        ctx.fillStyle = isDark ? "#82b4f5" : "#2a78d6";
        ctx.font = "600 12px Geist, system-ui, sans-serif";
        ctx.textAlign = "center";
        ctx.fillText("LEFT PFC (Fp1 / F3)", cx - rx * 0.52, cy - ry - 14);

        ctx.fillStyle = isDark ? "#f28b61" : "#eb6834";
        ctx.fillText("RIGHT PFC (Fp2 / F4)", cx + rx * 0.52, cy - ry - 14);

        // Anatomical labels
        ctx.fillStyle = textFill;
        ctx.font = "10px Geist, system-ui, sans-serif";
        ctx.fillText("Superior DLPFC", cx - rx * 0.55, cy - ry * 0.68);
        ctx.fillText("Superior DLPFC", cx + rx * 0.55, cy - ry * 0.68);
        ctx.fillText("Ventral / Frontopolar", cx - rx * 0.55, cy + ry * 0.84);
        ctx.fillText("Ventral / Frontopolar", cx + rx * 0.55, cy + ry * 0.84);
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

        // Optode Channel Label (e.g. L1, R8)
        ctx.fillStyle = isDark ? "#f0f0ee" : "#141413";
        ctx.font = "bold 9px Geist Mono, monospace";
        ctx.textAlign = "center";
        ctx.textBaseline = "middle";

        const labelY = py + (s.row === 3 ? 15 : -14);
        ctx.fillText(s.id, px, labelY);

        // In Frontal view, also show value under sensor
        if (this.projection === "frontal" && hasVal) {
          ctx.font = "8px Geist Mono, monospace";
          ctx.fillStyle = isDark ? "rgba(255, 255, 255, 0.70)" : "rgba(20, 20, 19, 0.70)";
          const valY = py + (s.row === 3 ? 24 : 14);
          ctx.fillText(s.value.toFixed(1), px, valY);
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

      const sideName = sensor.side === "left" ? "Left Prefrontal" : "Right Prefrontal";
      const valStr = sensor.value !== null && !isNaN(sensor.value)
        ? (this.metric === "asym" ? `${sensor.value > 0 ? "+" : ""}${sensor.value.toFixed(1)}%` : sensor.value.toFixed(2))
        : "No signal";
      const unitStr = this.metric === "asym" ? "Asymmetry" : (this.metric === "bfi" ? "BFI" : "BVI");
      const cqStr = (sensor.cq * 100).toFixed(0);

      el.innerHTML = `
        <div class="tip-head">
          <strong>${sensor.id}</strong> (${sideName})
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
          <span>Role:</span>
          <span>${CAMERA_ROLES[sensor.cam - 1]}</span>
        </div>
        <div class="tip-row">
          <span>Contact Quality:</span>
          <span style="color: ${sensor.cq >= 0.7 ? '#0ca30c' : '#fab219'}">${cqStr}%</span>
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
