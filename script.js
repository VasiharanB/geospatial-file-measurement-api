/**
 * Geospatial File Measurement API — Professional 3D Command Center
 * Authoritative Client Controller with Realistic Procedural 3D Earth,
 * Dual Light/Dark Theme System, 2D Vector Geometry Viewport,
 * Interactive Feature Explorer, and Safe textContent DOM Rendering.
 */

import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';

// Authoritative API Target Endpoints
const PROD_API_URL = "https://geospatial-measurement-api-9tqz.onrender.com";
const LOCAL_API_URL = "http://127.0.0.1:8000";

/**
 * Resolve the authoritative API Base URL securely:
 * 1. An untrusted external ?api_url= or window.ENV_API_BASE_URL value must never receive uploaded files.
 * 2. On the deployed GitHub Pages frontend (or any non-local hostname), localhost API overrides
 *    must NOT be accepted (mixed content and loopback exploitation protection).
 * 3. Localhost overrides are permitted ONLY when the application is running in its intended local-development context.
 * 4. window.ENV_API_BASE_URL is validated using the exact same origin trust policy.
 * 5. Rejected overrides fall back safely to the authoritative backend default with a clear console security alert.
 */
function getAuthoritativeApiBaseUrl() {
  if (typeof window === "undefined") {
    return LOCAL_API_URL;
  }

  const isLocalDev = window.location.hostname === "localhost" || window.location.hostname === "127.0.0.1";
  const defaultUrl = isLocalDev ? LOCAL_API_URL : PROD_API_URL;
  const prodOrigin = new URL(PROD_API_URL).origin;

  // Origin Trust Policy:
  // - In local development: localhost and production backend are acceptable targets.
  // - In production/deployed environment: ONLY the authoritative production backend is trusted; localhost is strictly forbidden.
  const trustedOrigins = isLocalDev
    ? new Set([prodOrigin, "http://127.0.0.1:8000", "http://localhost:8000"])
    : new Set([prodOrigin]);

  function validateCandidateUrl(candidate, sourceName) {
    if (!candidate || typeof candidate !== "string") {
      return null;
    }
    try {
      const parsed = new URL(candidate, window.location.href);
      if (trustedOrigins.has(parsed.origin)) {
        return parsed.origin;
      }
      if (!isLocalDev && (parsed.hostname === "localhost" || parsed.hostname === "127.0.0.1" || parsed.hostname === "[::1]")) {
        console.warn(`[Security] Localhost API override from ${sourceName} rejected in production deployment. Falling back to authoritative backend.`);
      } else {
        console.warn(`[Security] Untrusted ${sourceName} origin rejected: ${parsed.origin}. Falling back to authoritative backend.`);
      }
      return null;
    } catch (e) {
      console.warn(`[Security] Malformed ${sourceName} URL ignored: ${candidate}`);
      return null;
    }
  }

  // 1. Inspect window.ENV_API_BASE_URL using strict origin trust policy
  const envValid = validateCandidateUrl(window.ENV_API_BASE_URL, "window.ENV_API_BASE_URL");
  if (envValid) {
    return envValid;
  }

  // 2. Inspect query parameter override (?api_url=) using strict origin trust policy
  const urlParam = new URLSearchParams(window.location.search).get("api_url");
  const paramValid = validateCandidateUrl(urlParam, "?api_url=");
  if (paramValid) {
    return paramValid;
  }

  return defaultUrl;
}

const API_BASE_URL = getAuthoritativeApiBaseUrl();

// Synchronize navigation links to authoritative backend
try {
  const docLink = document.querySelector('.doc-link');
  if (docLink) {
    docLink.href = `${API_BASE_URL}/docs`;
  }
  const portalLink = document.getElementById('nav-portal-link');
  if (portalLink) {
    portalLink.href = `${API_BASE_URL}/portal`;
  }
} catch (e) {
  // Graceful fallback
}

// Allowed extensions and bounded stream limit (25 MB)
const ALLOWED_EXTENSIONS = [".kml", ".zip"];
const MAX_UPLOAD_SIZE_BYTES = 25 * 1024 * 1024;

// DOM Element References
const healthBadge = document.getElementById("health-badge");
const themeToggleBtn = document.getElementById("theme-toggle-btn");
const themeIcon = document.getElementById("theme-icon");
const themeLabel = document.getElementById("theme-label");

const uploadForm = document.getElementById("upload-form");
const fileInput = document.getElementById("file-input");
const dropzone = document.getElementById("dropzone");
const selectedFileBar = document.getElementById("selected-file-bar");
const selectedFileName = document.getElementById("selected-file-name");
const selectedFileSize = document.getElementById("selected-file-size");
const removeFileBtn = document.getElementById("remove-file-btn");
const uploadBtn = document.getElementById("upload-btn");

const errorSection = document.getElementById("error-section");
const errorTitle = document.getElementById("error-title");
const errorMessage = document.getElementById("error-message");
const errorDismissBtn = document.getElementById("error-dismiss-btn");

const processingSection = document.getElementById("processing-section");
const resultsContainer = document.getElementById("results-container");

// Summary Card DOM Elements
const summaryFilename = document.getElementById("summary-filename");
const summaryFileType = document.getElementById("summary-filetype");
const summaryFileId = document.getElementById("summary-fileid");
const summaryCount = document.getElementById("summary-count");
const summaryCrs = document.getElementById("summary-crs");
const summaryStatus = document.getElementById("summary-status");

// Preserved Relational Tables (Part 9A assertion compatibility)
const measurementsTable = document.getElementById("measurements-table");
const measurementsTbody = document.getElementById("measurements-tbody");
const featuresTable = document.getElementById("features-table");
const featuresTbody = document.getElementById("features-tbody");

// Metric Hero Displays
const metricTotalArea = document.getElementById("metric-total-area");
const metricAreaHa = document.getElementById("metric-area-ha");
const metricAreaKm2 = document.getElementById("metric-area-km2");
const metricTotalLength = document.getElementById("metric-total-length");
const metricLengthKm = document.getElementById("metric-length-km");
const metricTotalFeatures = document.getElementById("metric-total-features");
const metricPolyCount = document.getElementById("metric-poly-count");
const metricLineCount = document.getElementById("metric-line-count");
const metricPointCount = document.getElementById("metric-point-count");

// CRS Pipeline Diagram Elements
const crsInputCode = document.getElementById("crs-input-code");
const crsInputDesc = document.getElementById("crs-input-desc");
const crsMethodLabel = document.getElementById("crs-method-label");
const crsProjectedCode = document.getElementById("crs-projected-code");
const crsProjectedDesc = document.getElementById("crs-projected-desc");
const crsPipelineStatus = document.getElementById("crs-pipeline-status");
const crsWarningNotice = document.getElementById("crs-warning-notice");

// Feature Explorer & Geometry Canvas
const bannerActiveFile = document.getElementById("banner-active-file");
const featureCardsList = document.getElementById("feature-cards-list");
const featureSearchInput = document.getElementById("feature-search");
const geomCountBadge = document.getElementById("geom-count-badge");
const geometryCanvas = document.getElementById("geometry-canvas");
const zoomInBtn = document.getElementById("zoom-in-btn");
const zoomOutBtn = document.getElementById("zoom-out-btn");
const zoomFitBtn = document.getElementById("zoom-fit-btn");
const clearViewBtn = document.getElementById("clear-view-btn");
const leafletMapEl = document.getElementById("leaflet-map");
const mapHudCoords = document.getElementById("map-hud-coords");
const mapHudZoom = document.getElementById("map-hud-zoom");
const mapEmptyOverlay = document.getElementById("map-empty-overlay");
const basemapPillsContainer = document.getElementById("basemap-pills");

// 3D Globe HUD & Canvas
const heroCanvas = document.getElementById("hero-canvas");
const globeStatusText = document.getElementById("globe-status-text");
const globeStatusDot = document.getElementById("globe-status-dot");
const resetCamBtn = document.getElementById("reset-cam-btn");
const hudCrsVal = document.getElementById("hud-crs-val");
const telemetryLat = document.getElementById("telemetry-lat");
const telemetryLon = document.getElementById("telemetry-lon");

// Application State
let currentTheme = 'dark'; // 'dark' | 'light'
let currentFile = null;
let currentFeatures = [];
let currentMeasurements = [];
let globeState = {
  rotationSpeed: 0.001,
  idleSpeed: 0.001,
  pulseActive: false,
};

// Spatial Geometry Canvas State
let spatialViewer = null;

// ==============================================================================
// 1. INITIALIZATION & LIFECYCLE
// ==============================================================================

document.addEventListener("DOMContentLoaded", () => {
  initThemeSystem();
  initThreeJsEarth();
  initSpatialGeometryCanvas();
  checkHealth();
  setupEventListeners();
});

/**
 * Initialize Light/Dark theme system with localStorage persistence (Section 3).
 */
function initThemeSystem() {
  const savedTheme = localStorage.getItem("geo_theme");
  if (savedTheme === "light" || savedTheme === "dark") {
    currentTheme = savedTheme;
  } else if (window.matchMedia && window.matchMedia("(prefers-color-scheme: light)").matches) {
    currentTheme = "light";
  } else {
    currentTheme = "dark";
  }

  applyTheme(currentTheme, false);

  if (themeToggleBtn) {
    themeToggleBtn.addEventListener("click", () => {
      const nextTheme = currentTheme === "dark" ? "light" : "dark";
      applyTheme(nextTheme, true);
    });
  }
}

/**
 * Apply theme to document and update Three.js environment dynamically.
 */
function applyTheme(theme, persist = true) {
  currentTheme = theme;
  document.documentElement.setAttribute("data-theme", theme);

  if (persist) {
    localStorage.setItem("geo_theme", theme);
  }

  // Update theme toggle button text & icon
  if (themeIcon && themeLabel) {
    if (theme === "dark") {
      themeIcon.textContent = "☀";
      themeLabel.textContent = "Light";
      themeToggleBtn.setAttribute("title", "Switch to Light Mode");
    } else {
      themeIcon.textContent = "🌙";
      themeLabel.textContent = "Dark";
      themeToggleBtn.setAttribute("title", "Switch to Dark Mode");
    }
  }

  // Update Three.js lighting and background
  updateThreeJsTheme(theme);

  // Redraw geometry viewport or update map basemap with theme-aware styling
  if (spatialViewer) {
    if (typeof spatialViewer.updateTheme === "function") {
      spatialViewer.updateTheme(theme);
    } else if (typeof spatialViewer.render === "function") {
      spatialViewer.render();
    }
  }
}

/**
 * Check backend service health on load.
 */
async function checkHealth() {
  if (!healthBadge) return;
  healthBadge.textContent = "Checking API...";
  healthBadge.className = "badge badge-checking";

  try {
    const response = await fetch(`${API_BASE_URL}/api/health/`);
    if (response.ok) {
      const data = await response.json();
      if (data.status === "ok") {
        healthBadge.textContent = "API Online";
        healthBadge.className = "badge badge-online";
        return;
      }
    }
    throw new Error("Unhealthy status");
  } catch (err) {
    healthBadge.textContent = "API Offline";
    healthBadge.className = "badge badge-offline";
  }
}

// ==============================================================================
// 2. PROCEDURAL 3D EARTH GENERATOR & THREE.JS SCENE (Section 1 & 2)
// ==============================================================================

let globeScene, globeCamera, globeRenderer, globeControls;
let earthMesh, cloudsMesh, atmosphereMesh, starfieldMesh, orbitGroup;
let ambientLight, sunLight, fillLight;

/**
 * Procedural Earth Texture Generator.
 * Produces high-resolution equirectangular textures:
 * 1. Diffuse map: realistic blue oceans, green/brown continents, polar ice, subtle grid.
 * 2. Roughness map: oceans smooth (glossy specular reflection), land matte.
 * 3. Clouds map: semi-transparent procedural cloud wisps.
 */
function createProceduralEarthTextures() {
  const width = 2048;
  const height = 1024;

  // 1. Diffuse Earth Texture Canvas
  const diffuseCanvas = document.createElement("canvas");
  diffuseCanvas.width = width;
  diffuseCanvas.height = height;
  const ctx = diffuseCanvas.getContext("2d");

  // Deep ocean gradient bathymetry
  const oceanGrad = ctx.createLinearGradient(0, 0, 0, height);
  oceanGrad.addColorStop(0, "#0e294b");    // Arctic deep blue
  oceanGrad.addColorStop(0.3, "#0d2b56");  // North temperate blue
  oceanGrad.addColorStop(0.5, "#10396e");  // Equatorial rich ocean blue
  oceanGrad.addColorStop(0.7, "#0d2b56");  // South temperate blue
  oceanGrad.addColorStop(1, "#0a213e");    // Antarctic polar blue
  ctx.fillStyle = oceanGrad;
  ctx.fillRect(0, 0, width, height);

  // Helper to project [lon, lat] in degrees to canvas [x, y]
  function toCanvas(lon, lat) {
    const x = ((lon + 180) / 360) * width;
    const y = ((90 - lat) / 180) * height;
    return [x, y];
  }

  // Major Continents & Landmasses Polygons (Equirectangular Degrees)
  const CONTINENTS = [
    // Eurasia (Europe, Russia, Asia, India, Indochina, Arabia)
    [
      [-9, 36], [-9, 43], [-1, 44], [0, 49], [5, 53], [8, 57], [12, 55], [20, 55], [24, 60],
      [18, 65], [28, 71], [45, 68], [60, 71], [80, 74], [105, 78], [130, 73], [160, 71],
      [175, 66], [170, 60], [140, 50], [132, 43], [123, 40], [120, 32], [118, 25], [108, 20],
      [105, 10], [100, 4], [98, 15], [90, 22], [80, 15], [77, 8], [72, 20], [68, 25],
      [58, 25], [54, 26], [50, 15], [44, 12], [42, 16], [35, 28], [32, 31], [26, 36],
      [20, 40], [15, 38], [12, 44], [4, 43], [3, 40], [-2, 37], [-9, 36]
    ],
    // Scandinavia
    [ [5, 58], [10, 59], [12, 64], [16, 69], [25, 71], [31, 70], [28, 65], [22, 61], [18, 59], [10, 54], [5, 58] ],
    // Africa
    [
      [-6, 36], [10, 37], [25, 32], [32, 31], [35, 28], [43, 12], [51, 11], [42, -2],
      [40, -10], [35, -20], [32, -28], [28, -32], [20, -34], [18, -34], [15, -23], [12, -12],
      [9, 4], [3, 6], [-8, 4], [-17, 15], [-17, 21], [-13, 28], [-6, 36]
    ],
    // North America (Canada, Alaska, USA, Mexico, Central America)
    [
      [-168, 65], [-160, 71], [-140, 70], [-130, 69], [-120, 68], [-95, 70], [-80, 63],
      [-65, 60], [-55, 52], [-65, 44], [-70, 42], [-75, 38], [-80, 25], [-82, 25], [-81, 29],
      [-88, 30], [-97, 26], [-97, 21], [-88, 16], [-83, 9], [-77, 8], [-83, 10], [-93, 16],
      [-105, 20], [-110, 24], [-115, 32], [-124, 40], [-125, 48], [-132, 54], [-140, 60],
      [-152, 58], [-165, 60], [-168, 65]
    ],
    // South America
    [
      [-77, 8], [-72, 12], [-60, 10], [-50, 0], [-35, -5], [-35, -8], [-40, -22], [-48, -28],
      [-55, -34], [-65, -42], [-67, -54], [-75, -50], [-72, -40], [-71, -30], [-76, -15],
      [-80, -5], [-77, 8]
    ],
    // Australia
    [
      [114, -22], [115, -34], [120, -35], [135, -34], [140, -38], [148, -38], [153, -28],
      [148, -20], [142, -11], [136, -12], [130, -14], [124, -16], [114, -22]
    ],
    // Antarctica (Ice Shelf across South Pole)
    [
      [-180, -68], [-180, -90], [180, -90], [180, -68], [160, -70], [140, -66], [120, -65],
      [90, -65], [60, -67], [30, -69], [0, -69], [-30, -71], [-60, -64], [-70, -71],
      [-100, -72], [-130, -73], [-160, -74], [-180, -68]
    ],
    // Greenland
    [ [-50, 60], [-40, 65], [-20, 70], [-20, 82], [-35, 83], [-55, 82], [-60, 75], [-50, 60] ],
    // United Kingdom & Ireland
    [ [-5, 50], [-4, 53], [-3, 58], [-5, 58], [-2, 56], [1, 52], [-3, 50], [-5, 50] ],
    [ [-10, 52], [-8, 54], [-6, 55], [-6, 52], [-10, 52] ],
    // Japan
    [ [130, 31], [132, 34], [138, 36], [141, 41], [144, 44], [140, 43], [136, 36], [131, 33], [130, 31] ],
    // Madagascar
    [ [44, -12], [50, -15], [48, -25], [44, -25], [43, -16], [44, -12] ],
    // Indonesia & New Guinea
    [ [95, 5], [105, -5], [100, -2], [95, 5] ],
    [ [109, 2], [118, 5], [119, -4], [110, -3], [109, 2] ],
    [ [131, -1], [141, -3], [150, -9], [141, -8], [131, -1] ],
    // New Zealand
    [ [173, -35], [178, -38], [175, -41], [174, -39], [173, -35] ],
    [ [167, -45], [174, -41], [173, -44], [168, -46], [167, -45] ]
  ];

  // Pass A: Coastal Shelf Glow (Continental margins in cyan/turquoise)
  ctx.strokeStyle = "rgba(30, 110, 165, 0.65)";
  ctx.lineWidth = 14;
  ctx.lineJoin = "round";
  ctx.lineCap = "round";
  CONTINENTS.forEach(poly => {
    ctx.beginPath();
    poly.forEach((pt, idx) => {
      const [x, y] = toCanvas(pt[0], pt[1]);
      if (idx === 0) ctx.moveTo(x, y);
      else ctx.lineTo(x, y);
    });
    ctx.closePath();
    ctx.stroke();
  });

  // Pass B: Base Landmass Fill (Rich Vegetation Green)
  ctx.fillStyle = "#2c5f31";
  CONTINENTS.forEach(poly => {
    ctx.beginPath();
    poly.forEach((pt, idx) => {
      const [x, y] = toCanvas(pt[0], pt[1]);
      if (idx === 0) ctx.moveTo(x, y);
      else ctx.lineTo(x, y);
    });
    ctx.closePath();
    ctx.fill();
  });

  // Pass C: Biome Overlay (Deserts / Arid Terraces in Warm Gold/Brown)
  const DESERTS = [
    // Sahara Desert (North Africa)
    { cx: 15, cy: 23, rx: 25, ry: 8 },
    // Arabian Peninsula
    { cx: 45, cy: 22, rx: 12, ry: 7 },
    // Gobi Desert (Central/East Asia)
    { cx: 98, cy: 42, rx: 18, ry: 6 },
    // Australian Outback
    { cx: 133, cy: -25, rx: 14, ry: 7 },
    // Kalahari / Southwest Africa
    { cx: 20, cy: -23, rx: 8, ry: 6 },
    // American Southwest / Mojave
    { cx: -110, cy: 32, rx: 10, ry: 5 }
  ];

  DESERTS.forEach(d => {
    const [cx, cy] = toCanvas(d.cx, d.cy);
    const rx = (d.rx / 360) * width;
    const ry = (d.ry / 180) * height;

    const radGrad = ctx.createRadialGradient(cx, cy, 0, cx, cy, rx);
    radGrad.addColorStop(0, "rgba(182, 150, 92, 0.85)");
    radGrad.addColorStop(0.6, "rgba(154, 126, 75, 0.65)");
    radGrad.addColorStop(1, "rgba(44, 95, 49, 0)");

    ctx.save();
    ctx.fillStyle = radGrad;
    ctx.beginPath();
    ctx.ellipse(cx, cy, rx, ry, 0, 0, 2 * Math.PI);
    ctx.fill();
    ctx.restore();
  });

  // Pass D: Rainforest Biomes (Deep Lush Emerald)
  const FORESTS = [
    // Amazon Basin
    { cx: -60, cy: -4, rx: 14, ry: 8 },
    // Congo Basin
    { cx: 22, cy: 0, rx: 10, ry: 7 },
    // Southeast Asia
    { cx: 105, cy: 8, rx: 12, ry: 8 }
  ];

  FORESTS.forEach(f => {
    const [cx, cy] = toCanvas(f.cx, f.cy);
    const rx = (f.rx / 360) * width;
    const ry = (f.ry / 180) * height;

    const radGrad = ctx.createRadialGradient(cx, cy, 0, cx, cy, rx);
    radGrad.addColorStop(0, "rgba(22, 74, 30, 0.85)");
    radGrad.addColorStop(0.7, "rgba(35, 88, 40, 0.45)");
    radGrad.addColorStop(1, "rgba(44, 95, 49, 0)");

    ctx.save();
    ctx.fillStyle = radGrad;
    ctx.beginPath();
    ctx.ellipse(cx, cy, rx, ry, 0, 0, 2 * Math.PI);
    ctx.fill();
    ctx.restore();
  });

  // Pass E: Mountain Ranges (Andes, Rockies, Himalayas Relief)
  const MOUNTAINS = [
    // Andes
    [ [-74, 10], [-73, 0], [-76, -14], [-71, -30], [-72, -45], [-68, -54] ],
    // Rockies
    [ [-145, 60], [-130, 54], [-120, 48], [-114, 40], [-106, 32] ],
    // Himalayas
    [ [72, 34], [78, 32], [85, 29], [92, 28], [98, 28] ],
    // Alps
    [ [5, 45], [8, 46], [12, 47], [15, 46] ]
  ];

  ctx.strokeStyle = "rgba(90, 80, 68, 0.75)";
  ctx.lineWidth = 4;
  ctx.lineCap = "round";
  MOUNTAINS.forEach(mtn => {
    ctx.beginPath();
    mtn.forEach((pt, idx) => {
      const [x, y] = toCanvas(pt[0], pt[1]);
      if (idx === 0) ctx.moveTo(x, y);
      else ctx.lineTo(x, y);
    });
    ctx.stroke();
  });

  // Pass F: Polar Glaciers & Ice Caps (Crisp Ice White & Cyan)
  const ICE_ZONES = [
    // Greenland
    [ [-50, 62], [-40, 66], [-22, 71], [-22, 81], [-36, 82], [-54, 81], [-58, 75], [-50, 62] ],
    // Antarctica (South Polar Cap)
    [
      [-180, -68], [-180, -90], [180, -90], [180, -68], [160, -70], [120, -66],
      [60, -67], [0, -69], [-60, -65], [-120, -73], [-180, -68]
    ]
  ];

  ctx.fillStyle = "#edf4fa";
  ICE_ZONES.forEach(ice => {
    ctx.beginPath();
    ice.forEach((pt, idx) => {
      const [x, y] = toCanvas(pt[0], pt[1]);
      if (idx === 0) ctx.moveTo(x, y);
      else ctx.lineTo(x, y);
    });
    ctx.closePath();
    ctx.fill();
  });

  // Pass G: Subtle Geographic Grid Lines
  ctx.lineWidth = 1;

  // Equator (lat 0, y = 512)
  ctx.strokeStyle = "rgba(56, 189, 248, 0.4)";
  ctx.beginPath();
  ctx.moveTo(0, height / 2);
  ctx.lineTo(width, height / 2);
  ctx.stroke();

  // Tropics of Cancer & Capricorn (lat ±23.44°)
  ctx.strokeStyle = "rgba(56, 189, 248, 0.2)";
  ctx.setLineDash([6, 6]);
  const [, yCancer] = toCanvas(0, 23.44);
  const [, yCapri] = toCanvas(0, -23.44);
  ctx.beginPath();
  ctx.moveTo(0, yCancer); ctx.lineTo(width, yCancer);
  ctx.moveTo(0, yCapri); ctx.lineTo(width, yCapri);
  ctx.stroke();

  // Meridians every 30°
  ctx.strokeStyle = "rgba(255, 255, 255, 0.08)";
  ctx.setLineDash([4, 8]);
  for (let lon = -180; lon < 180; lon += 30) {
    const [x] = toCanvas(lon, 0);
    ctx.beginPath();
    ctx.moveTo(x, 0);
    ctx.lineTo(x, height);
    ctx.stroke();
  }
  ctx.setLineDash([]); // Reset line dash

  // 2. Specular Roughness Texture Canvas (Ocean smooth = glossy, Land rough = matte)
  const roughnessCanvas = document.createElement("canvas");
  roughnessCanvas.width = width;
  roughnessCanvas.height = height;
  const rCtx = roughnessCanvas.getContext("2d");

  // Ocean: very dark (smooth specular ocean reflection)
  rCtx.fillStyle = "#161616";
  rCtx.fillRect(0, 0, width, height);

  // Land: light gray (diffuse matte land surfaces)
  rCtx.fillStyle = "#d0d0d0";
  CONTINENTS.forEach(poly => {
    rCtx.beginPath();
    poly.forEach((pt, idx) => {
      const [x, y] = toCanvas(pt[0], pt[1]);
      if (idx === 0) rCtx.moveTo(x, y);
      else rCtx.lineTo(x, y);
    });
    rCtx.closePath();
    rCtx.fill();
  });

  // 3. Clouds Texture Canvas (Semi-transparent wisps & equatorial cloud bands)
  const cloudsCanvas = document.createElement("canvas");
  cloudsCanvas.width = 1024;
  cloudsCanvas.height = 512;
  const cCtx = cloudsCanvas.getContext("2d");
  cCtx.clearRect(0, 0, 1024, 512);

  // Procedural cloud swirls & bands
  for (let i = 0; i < 400; i++) {
    const cx = Math.random() * 1024;
    // Bias clouds towards equator (ITCZ) and mid-latitude jet streams
    let lat = (Math.random() - 0.5) * 160;
    if (Math.random() < 0.4) lat = (Math.random() - 0.5) * 30; // Equatorial band
    const cy = ((90 - lat) / 180) * 512;

    const rx = 20 + Math.random() * 70;
    const ry = 8 + Math.random() * 25;
    const opacity = 0.15 + Math.random() * 0.45;

    const cGrad = cCtx.createRadialGradient(cx, cy, 0, cx, cy, rx);
    cGrad.addColorStop(0, `rgba(255, 255, 255, ${opacity})`);
    cGrad.addColorStop(0.6, `rgba(240, 248, 255, ${opacity * 0.5})`);
    cGrad.addColorStop(1, "rgba(255, 255, 255, 0)");

    cCtx.fillStyle = cGrad;
    cCtx.beginPath();
    cCtx.ellipse(cx, cy, rx, ry, (Math.random() - 0.5) * 0.4, 0, 2 * Math.PI);
    cCtx.fill();
  }

  // Convert canvases to Three.js textures
  const earthTexture = new THREE.CanvasTexture(diffuseCanvas);
  const roughnessTexture = new THREE.CanvasTexture(roughnessCanvas);
  const cloudsTexture = new THREE.CanvasTexture(cloudsCanvas);

  return { earthTexture, roughnessTexture, cloudsTexture };
}

/**
 * Initialize 3D Earth in Three.js with realistic materials,
 * day/night directional lighting, clouds, and orbit controls.
 */
function initThreeJsEarth() {
  if (!heroCanvas) return;

  try {
    // 1. Scene & Camera
    globeScene = new THREE.Scene();
    const width = heroCanvas.clientWidth || 540;
    const height = heroCanvas.clientHeight || 480;

    globeCamera = new THREE.PerspectiveCamera(45, width / height, 0.1, 1000);
    globeCamera.position.set(0, 0.8, 3.8);

    // 2. WebGL Renderer
    globeRenderer = new THREE.WebGLRenderer({
      canvas: heroCanvas,
      antialias: true,
      alpha: true,
      powerPreference: "high-performance",
    });
    globeRenderer.setSize(width, height);
    globeRenderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));

    // 3. OrbitControls
    globeControls = new OrbitControls(globeCamera, heroCanvas);
    globeControls.enableDamping = true;
    globeControls.dampingFactor = 0.05;
    globeControls.enablePan = false;
    globeControls.minDistance = 2.0;
    globeControls.maxDistance = 6.0;
    globeControls.autoRotate = false;

    // 4. Lighting Rig
    ambientLight = new THREE.AmbientLight(0xffffff, 0.45);
    globeScene.add(ambientLight);

    // Primary Sun Light (Day / Night Terminator from high-angle)
    sunLight = new THREE.DirectionalLight(0xfffaed, 2.2);
    sunLight.position.set(5, 3, 5);
    globeScene.add(sunLight);

    // Soft Fill Light (Night hemisphere visibility)
    fillLight = new THREE.DirectionalLight(0x38bdf8, 0.35);
    fillLight.position.set(-5, -2, -5);
    globeScene.add(fillLight);

    // 5. Build Procedural Earth Textures
    const { earthTexture, roughnessTexture, cloudsTexture } = createProceduralEarthTextures();

    // 6. Earth Mesh (Radius 1.6)
    const earthGeo = new THREE.SphereGeometry(1.6, 64, 64);
    const earthMat = new THREE.MeshStandardMaterial({
      map: earthTexture,
      roughnessMap: roughnessTexture,
      roughness: 0.8,
      metalness: 0.1,
    });
    earthMesh = new THREE.Mesh(earthGeo, earthMat);
    globeScene.add(earthMesh);

    // 7. Rotating Cloud Sphere (Radius 1.615)
    const cloudsGeo = new THREE.SphereGeometry(1.615, 48, 48);
    const cloudsMat = new THREE.MeshStandardMaterial({
      map: cloudsTexture,
      transparent: true,
      opacity: 0.6,
      blending: THREE.NormalBlending,
      depthWrite: false,
    });
    cloudsMesh = new THREE.Mesh(cloudsGeo, cloudsMat);
    globeScene.add(cloudsMesh);

    // 8. Atmospheric Rim Glow Mesh (Radius 1.66)
    const atmosGeo = new THREE.SphereGeometry(1.66, 48, 48);
    const atmosMat = new THREE.MeshBasicMaterial({
      color: 0x38bdf8,
      side: THREE.BackSide,
      transparent: true,
      opacity: 0.28,
    });
    atmosphereMesh = new THREE.Mesh(atmosGeo, atmosMat);
    globeScene.add(atmosphereMesh);

    // 9. Equatorial & Tropic Grid Overlays
    const equatorGeo = new THREE.RingGeometry(1.605, 1.618, 64);
    const equatorMat = new THREE.MeshBasicMaterial({
      color: 0x38bdf8,
      side: THREE.DoubleSide,
      transparent: true,
      opacity: 0.5,
    });
    const equatorMesh = new THREE.Mesh(equatorGeo, equatorMat);
    equatorMesh.rotation.x = Math.PI / 2;
    earthMesh.add(equatorMesh);

    // 10. Geodetic Reference Station Markers (Pulsing Beacons)
    const stations = [
      { lat: 48.8566, lon: 2.3522, label: "Paris" },
      { lat: 40.7128, lon: -74.006, label: "New York" },
      { lat: 12.9716, lon: 77.5946, label: "Bangalore" },
      { lat: 35.6762, lon: 139.6503, label: "Tokyo" },
      { lat: -33.8688, lon: 151.2093, label: "Sydney" },
      { lat: 0.0, lon: 0.0, label: "Null Island" },
    ];

    stations.forEach(st => {
      const phi = (90 - st.lat) * (Math.PI / 180);
      const theta = (st.lon + 180) * (Math.PI / 180);
      const x = -(1.6 * Math.sin(phi) * Math.cos(theta));
      const z = 1.6 * Math.sin(phi) * Math.sin(theta);
      const y = 1.6 * Math.cos(phi);

      const beacon = new THREE.Mesh(
        new THREE.SphereGeometry(0.025, 12, 12),
        new THREE.MeshBasicMaterial({ color: 0x10b981 })
      );
      beacon.position.set(x, y, z);
      earthMesh.add(beacon);
    });

    // 11. Subtle Starfield Particles for Dark Mode
    const starCount = 500;
    const starGeo = new THREE.BufferGeometry();
    const starPos = new Float32Array(starCount * 3);
    for (let i = 0; i < starCount * 3; i += 3) {
      starPos[i] = (Math.random() - 0.5) * 20;
      starPos[i + 1] = (Math.random() - 0.5) * 20;
      starPos[i + 2] = (Math.random() - 0.5) * 20;
    }
    starGeo.setAttribute('position', new THREE.BufferAttribute(starPos, 3));
    const starMat = new THREE.PointsMaterial({
      size: 0.025,
      color: 0x94a3b8,
      transparent: true,
      opacity: 0.5,
    });
    starfieldMesh = new THREE.Points(starGeo, starMat);
    globeScene.add(starfieldMesh);

    // Apply initial theme settings
    updateThreeJsTheme(currentTheme);

    // 12. Reset Camera Button Handler
    if (resetCamBtn) {
      resetCamBtn.addEventListener("click", () => {
        resetGlobeCamera();
      });
    }

    // 13. Animation Loop
    let lastTime = performance.now();
    function animate(now) {
      requestAnimationFrame(animate);
      const delta = (now - lastTime) / 1000;
      lastTime = now;

      // Autonomous gentle idle rotation
      if (earthMesh) {
        earthMesh.rotation.y += globeState.rotationSpeed;
      }

      // Clouds rotate slightly faster for natural atmospheric drift
      if (cloudsMesh) {
        cloudsMesh.rotation.y += globeState.rotationSpeed * 1.35;
      }

      // Smooth damping update
      if (globeControls) {
        globeControls.update();
      }

      // Update live camera telemetry readout
      updateCameraTelemetry();

      globeRenderer.render(globeScene, globeCamera);
    }
    requestAnimationFrame(animate);

    // 14. Responsive Resize Observer
    const resizeObserver = new ResizeObserver(() => {
      if (!heroCanvas || !globeRenderer || !globeCamera) return;
      const newWidth = heroCanvas.clientWidth;
      const newHeight = heroCanvas.clientHeight;
      if (newWidth === 0 || newHeight === 0) return;
      globeCamera.aspect = newWidth / newHeight;
      globeCamera.updateProjectionMatrix();
      globeRenderer.setSize(newWidth, newHeight);
    });
    resizeObserver.observe(heroCanvas);

  } catch (err) {
    console.error("Three.js initialization notice:", err);
    const fallback = document.getElementById("globe-fallback");
    if (fallback) fallback.style.display = "block";
  }
}

/**
 * Update Three.js scene according to Light or Dark theme.
 */
function updateThreeJsTheme(theme) {
  if (!globeScene) return;

  if (theme === "light") {
    // Light Mode: bright laboratory lighting, colorful Earth on light background
    globeScene.background = new THREE.Color(0xf1f5f9);
    if (ambientLight) ambientLight.intensity = 0.85;
    if (sunLight) sunLight.intensity = 1.9;
    if (fillLight) {
      fillLight.color.setHex(0x94a3b8);
      fillLight.intensity = 0.45;
    }
    if (atmosphereMesh) {
      atmosphereMesh.material.color.setHex(0x0284c7);
      atmosphereMesh.material.opacity = 0.16;
    }
    if (starfieldMesh) {
      starfieldMesh.visible = false;
    }
  } else {
    // Dark Mode: deep space background, directional sun, starry sky
    globeScene.background = new THREE.Color(0x070b14);
    if (ambientLight) ambientLight.intensity = 0.45;
    if (sunLight) sunLight.intensity = 2.2;
    if (fillLight) {
      fillLight.color.setHex(0x38bdf8);
      fillLight.intensity = 0.35;
    }
    if (atmosphereMesh) {
      atmosphereMesh.material.color.setHex(0x38bdf8);
      atmosphereMesh.material.opacity = 0.28;
    }
    if (starfieldMesh) {
      starfieldMesh.visible = true;
    }
  }
}

/**
 * Reset globe camera smoothly to default view.
 */
function resetGlobeCamera() {
  if (!globeCamera || !globeControls) return;

  const targetPos = new THREE.Vector3(0, 0.8, 3.8);
  const targetLook = new THREE.Vector3(0, 0, 0);

  const startPos = globeCamera.position.clone();
  const startTime = performance.now();
  const duration = 600;

  function step(now) {
    const elapsed = now - startTime;
    const progress = Math.min(1, elapsed / duration);
    // Ease-out cubic
    const ease = 1 - Math.pow(1 - progress, 3);

    globeCamera.position.lerpVectors(startPos, targetPos, ease);
    globeControls.target.lerp(targetLook, ease);

    if (progress < 1) {
      requestAnimationFrame(step);
    } else {
      globeCamera.position.copy(targetPos);
      globeControls.target.copy(targetLook);
    }
  }
  requestAnimationFrame(step);
}

/**
 * Update live lat/lon telemetry readout based on camera orientation.
 */
function updateCameraTelemetry() {
  if (!globeCamera || !telemetryLat || !telemetryLon) return;

  // Approximate viewing latitude and longitude
  const p = globeCamera.position;
  const radius = p.length();
  const lat = 90 - (Math.acos(p.y / radius) * 180 / Math.PI);
  const lon = (Math.atan2(p.x, p.z) * 180 / Math.PI) - ((earthMesh ? earthMesh.rotation.y : 0) * 180 / Math.PI);
  const normLon = ((lon % 360) + 540) % 360 - 180;

  telemetryLat.textContent = `${Math.abs(lat).toFixed(2)}°${lat >= 0 ? 'N' : 'S'}`;
  telemetryLon.textContent = `${Math.abs(normLon).toFixed(2)}°${normLon >= 0 ? 'E' : 'W'}`;
}

// ==============================================================================
// 3. EVENT LISTENERS & INGESTION PORTAL LOGIC (Section 7)
// ==============================================================================

function setupEventListeners() {
  // File input change
  if (fileInput) {
    fileInput.addEventListener("change", handleFileSelected);
  }

  // Upload Form submission
  if (uploadForm) {
    uploadForm.addEventListener("submit", handleUploadSubmit);
  }

  // Remove File Button
  if (removeFileBtn) {
    removeFileBtn.addEventListener("click", clearSelectedFile);
  }

  // Error Dismiss Button
  if (errorDismissBtn) {
    errorDismissBtn.addEventListener("click", hideError);
  }

  // Drag-and-drop dropzone interactions
  if (dropzone) {
    ["dragenter", "dragover"].forEach(eventName => {
      dropzone.addEventListener(eventName, (e) => {
        e.preventDefault();
        e.stopPropagation();
        dropzone.classList.add("drag-active");
        globeState.rotationSpeed = 0.003; // Globe reacts to drag hover
      });
    });

    ["dragleave", "drop"].forEach(eventName => {
      dropzone.addEventListener(eventName, (e) => {
        e.preventDefault();
        e.stopPropagation();
        dropzone.classList.remove("drag-active");
        globeState.rotationSpeed = globeState.idleSpeed;
      });
    });

    dropzone.addEventListener("drop", (e) => {
      const dt = e.dataTransfer;
      if (dt && dt.files && dt.files.length > 0) {
        if (fileInput) {
          fileInput.files = dt.files;
          handleFileSelected();
        }
      }
    });
  }

  // Feature Search Filter
  if (featureSearchInput) {
    featureSearchInput.addEventListener("input", (e) => {
      const query = (e.target.value || "").toLowerCase().trim();
      filterFeatureCards(query);
    });
  }
}

/**
 * Handle file selection from input or dropzone.
 */
function handleFileSelected() {
  hideError();

  if (!fileInput || !fileInput.files || fileInput.files.length === 0) {
    clearSelectedFile();
    return;
  }

  const file = fileInput.files[0];
  currentFile = file;

  // Validate extension client-side
  const ext = getFileExtension(file.name);
  if (!ALLOWED_EXTENSIONS.includes(ext.toLowerCase())) {
    showError(
      "Invalid File Type",
      `The file "${file.name}" has an unsupported extension (${ext}). Please provide a .kml vector file or a zipped Shapefile bundle (.zip).`
    );
    clearSelectedFile();
    return;
  }

  // Validate bounded stream size limit (25 MB)
  if (file.size > MAX_UPLOAD_SIZE_BYTES) {
    showError(
      "Payload Too Large",
      `The file "${file.name}" (${formatFileSize(file.size)}) exceeds the maximum allowed limit of 25 MB.`
    );
    clearSelectedFile();
    return;
  }

  // Display staged file packet
  if (selectedFileName) selectedFileName.textContent = file.name;
  if (selectedFileSize) selectedFileSize.textContent = formatFileSize(file.size);
  if (selectedFileBar) selectedFileBar.style.display = "flex";
  if (uploadBtn) uploadBtn.disabled = false;
}

/**
 * Clear selected file state.
 */
function clearSelectedFile() {
  currentFile = null;
  if (fileInput) fileInput.value = "";
  if (selectedFileBar) selectedFileBar.style.display = "none";
  if (uploadBtn) uploadBtn.disabled = true;
}

/**
 * Handle form submit and initiate upload.
 */
async function handleUploadSubmit(e) {
  if (e) e.preventDefault();
  if (!currentFile) return;
  await processUpload(currentFile);
}

// ==============================================================================
// 4. API INGESTION & PIPELINE EXECUTION (Section 8)
// ==============================================================================

/**
 * Process upload through backend FastAPI service.
 */
async function processUpload(file) {
  // Clean prior state and tables before processing new uploads
  clearRenderedTables();
  hideError();
  resultsContainer.style.display = "none";

  // Display processing pipeline
  if (processingSection) processingSection.style.display = "block";
  if (uploadBtn) uploadBtn.disabled = true;
  globeState.rotationSpeed = 0.005; // Globe accelerates during processing

  // Advance pipeline steps
  advancePipelineStep("step-upload");

  try {
    const formData = new FormData();
    formData.append("file", file);

    advancePipelineStep("step-validate");

    const response = await fetch(`${API_BASE_URL}/api/files/`, {
      method: "POST",
      body: formData,
    });

    if (!response.ok) {
      let errPayload;
      try {
        errPayload = await response.json();
      } catch (parseErr) {
        errPayload = { detail: `Server responded with status code ${response.status}` };
      }

      const errTitleText = errPayload.error || (response.status === 413 ? "Payload Too Large" : "Upload Failed");
      const errDetailText = errPayload.detail || "An unexpected error occurred during file ingestion.";
      throw new BackendError(errTitleText, errDetailText);
    }

    advancePipelineStep("step-parse");
    const uploadResult = await response.json();
    const fileId = uploadResult.id;

    advancePipelineStep("step-crs");
    advancePipelineStep("step-project");

    // Fetch complete file details (summary & features)
    const detailResponse = await fetch(`${API_BASE_URL}/api/files/${fileId}/`);
    if (!detailResponse.ok) {
      throw new BackendError("Detail Retrieval Failed", "Failed to fetch file summary records from backend.");
    }
    const fileDetail = await detailResponse.json();

    advancePipelineStep("step-measure");

    // Fetch authoritative measurements
    const measResponse = await fetch(`${API_BASE_URL}/api/files/${fileId}/measurements/`);
    if (!measResponse.ok) {
      throw new BackendError("Measurement Retrieval Failed", "Failed to fetch measurement records from backend.");
    }
    const measResult = await measResponse.json();

    advancePipelineStep("step-store");
    advancePipelineStep("step-complete");

    // Complete processing & transition to Spatial Analysis report
    if (processingSection) processingSection.style.display = "none";
    resultsContainer.style.display = "block";
    globeState.rotationSpeed = globeState.idleSpeed;

    // Render results
    renderAnalysisResults(fileDetail, measResult.measurements);

    // Invalidate map size so Leaflet recalculates viewport bounds immediately
    if (spatialViewer && spatialViewer.map) {
      setTimeout(() => {
        spatialViewer.map.invalidateSize();
        spatialViewer.fit();
      }, 150);
    }

    // Smooth scroll to results
    resultsContainer.scrollIntoView({ behavior: "smooth" });

  } catch (err) {
    if (processingSection) processingSection.style.display = "none";
    if (uploadBtn) uploadBtn.disabled = false;
    globeState.rotationSpeed = globeState.idleSpeed;

    if (err instanceof BackendError) {
      showError(err.title, err.message);
    } else if (err instanceof TypeError && err.message.includes("fetch")) {
      showError(
        "Network Error",
        "Unable to connect to the API. Check that FastAPI is running on port 8000 and CORS is enabled."
      );
    } else {
      showError("Processing Error", err.message || "An unexpected error occurred.");
    }
  }
}

/**
 * Custom error class for controlled backend exceptions.
 */
class BackendError extends Error {
  constructor(title, message) {
    super(message);
    this.title = title;
  }
}

/**
 * Advance active node in processing pipeline stepper.
 */
function advancePipelineStep(stepId) {
  const steps = ["step-upload", "step-validate", "step-parse", "step-crs", "step-project", "step-measure", "step-store", "step-complete"];
  const targetIdx = steps.indexOf(stepId);
  if (targetIdx === -1) return;

  steps.forEach((s, idx) => {
    const el = document.getElementById(s);
    if (!el) return;
    if (idx <= targetIdx) {
      el.classList.add("active");
    } else {
      el.classList.remove("active");
    }
  });
}

// ==============================================================================
// 5. ANALYSIS & RESULTS RENDERING (Section 9 & 10)
// ==============================================================================

/**
 * Render complete Spatial Analysis Report with animated metric counters.
 */
function renderAnalysisResults(fileDetail, measurements) {
  currentFeatures = fileDetail.features || [];
  currentMeasurements = measurements || [];

  // 1. Active File Banner
  if (bannerActiveFile) {
    bannerActiveFile.textContent = `${fileDetail.filename} (${fileDetail.file_type.toUpperCase()})`;
  }

  // 2. Summary Specification Grid
  if (summaryFilename) summaryFilename.textContent = fileDetail.filename;
  if (summaryFileType) summaryFileType.textContent = fileDetail.file_type.toUpperCase();
  if (summaryFileId) summaryFileId.textContent = fileDetail.id;
  if (summaryCount) summaryCount.textContent = `${fileDetail.feature_count}`;
  if (summaryCrs) summaryCrs.textContent = fileDetail.crs || "None (Unspecified)";

  if (summaryStatus) {
    summaryStatus.replaceChildren();
    const statusBadge = document.createElement("span");
    statusBadge.textContent = fileDetail.status;
    statusBadge.className = fileDetail.status === "COMPLETED" ? "badge badge-online" : "badge badge-offline";
    summaryStatus.appendChild(statusBadge);
  }

  // 3. Aggregate Authoritative Metrics
  let totalAreaSqMeters = 0;
  let totalLengthMeters = 0;
  let polyCount = 0;
  let lineCount = 0;
  let pointCount = 0;
  let inputCrs = fileDetail.crs || "None";
  let projectedCrs = "None";
  let hasMissingCrs = false;

  measurements.forEach(m => {
    if (m.geometry_type === "Polygon") {
      polyCount++;
      if (m.status === "COMPLETED" && m.measurement) {
        totalAreaSqMeters += m.measurement.value;
        if (m.measurement.input_crs) inputCrs = m.measurement.input_crs;
        if (m.measurement.projected_crs) projectedCrs = m.measurement.projected_crs;
      }
    } else if (m.geometry_type === "LineString") {
      lineCount++;
      if (m.status === "COMPLETED" && m.measurement) {
        totalLengthMeters += m.measurement.value;
        if (m.measurement.input_crs) inputCrs = m.measurement.input_crs;
        if (m.measurement.projected_crs) projectedCrs = m.measurement.projected_crs;
      }
    } else if (m.geometry_type === "Point") {
      pointCount++;
    }

    if (m.status === "ERROR" && m.note && m.note.toLowerCase().includes("missing coordinate reference system")) {
      hasMissingCrs = true;
    }
  });

  // Animated Counter: Area
  animateCounter(metricTotalArea, totalAreaSqMeters, 2, " m²");
  if (metricAreaHa) metricAreaHa.textContent = `${formatNumber(totalAreaSqMeters / 10000, 2)} ha`;
  if (metricAreaKm2) metricAreaKm2.textContent = `${formatNumber(totalAreaSqMeters / 1000000, 4)} km²`;

  // Animated Counter: Length
  animateCounter(metricTotalLength, totalLengthMeters, 2, " m");
  if (metricLengthKm) metricLengthKm.textContent = `${formatNumber(totalLengthMeters / 1000, 3)} km`;

  // Feature Entities Breakdown
  if (metricTotalFeatures) metricTotalFeatures.textContent = `${fileDetail.feature_count}`;
  if (metricPolyCount) metricPolyCount.textContent = `${polyCount} Polygon${polyCount === 1 ? '' : 's'}`;
  if (metricLineCount) metricLineCount.textContent = `${lineCount} Line${lineCount === 1 ? '' : 's'}`;
  if (metricPointCount) metricPointCount.textContent = `${pointCount} Point${pointCount === 1 ? '' : 's'}`;

  // 4. CRS Transformation Visualizer
  renderCrsVisualizer(inputCrs, projectedCrs, hasMissingCrs);

  // 5. Interactive Feature Cards Explorer
  renderFeatureCards(currentFeatures, currentMeasurements);

  // 6. 2D/3D Vector Geometry Canvas
  if (spatialViewer) {
    spatialViewer.loadGeometries(currentFeatures);
  }

  // 7. Relational Data Tables (Strict Part 9A test compatibility)
  renderRelationalTables(measurements, currentFeatures);
}

/**
 * Animate numeric counter value smoothly.
 */
function animateCounter(element, targetValue, decimals = 2, suffix = "") {
  if (!element) return;
  if (targetValue === 0) {
    element.textContent = `0.00${suffix}`;
    return;
  }

  const duration = 800;
  const start = performance.now();
  const startValue = 0;

  function tick(now) {
    const elapsed = now - start;
    const progress = Math.min(1, elapsed / duration);
    // Ease-out cubic
    const ease = 1 - Math.pow(1 - progress, 3);
    const current = startValue + (targetValue - startValue) * ease;
    element.textContent = `${formatNumber(current, decimals)}${suffix}`;

    if (progress < 1) {
      requestAnimationFrame(tick);
    } else {
      element.textContent = `${formatNumber(targetValue, decimals)}${suffix}`;
    }
  }
  requestAnimationFrame(tick);
}

/**
 * Render CRS Transformation Instrument diagram (Section 13).
 */
function renderCrsVisualizer(sourceCrs, targetCrs, hasMissingCrs) {
  if (crsInputCode) crsInputCode.textContent = sourceCrs;
  if (crsInputDesc) {
    crsInputDesc.textContent = sourceCrs.includes("4326") ? "WGS 84 Geographic 2D (Degrees)" : "Ingested Source Coordinate Reference";
  }

  if (crsProjectedCode) crsProjectedCode.textContent = targetCrs;
  if (crsProjectedDesc) {
    crsProjectedDesc.textContent = targetCrs !== "None" ? "Conformal Planar Metric Projection" : "Projection Blocked (Missing Reference)";
  }

  if (crsPipelineStatus) {
    crsPipelineStatus.replaceChildren();
    const statusChip = document.createElement("span");
    if (hasMissingCrs) {
      statusChip.textContent = "CRS MISSING &bull; ZERO GUESSING";
      statusChip.className = "badge badge-offline";
    } else {
      statusChip.textContent = "AUTOMATED CONFORMAL REPROJECTION";
      statusChip.className = "badge badge-online";
    }
    crsPipelineStatus.appendChild(statusChip);
  }

  if (crsWarningNotice) {
    crsWarningNotice.style.display = hasMissingCrs ? "flex" : "none";
  }
}

// ==============================================================================
// 6. INTERACTIVE FEATURE EXPLORER (Section 12)
// ==============================================================================

/**
 * Render interactive feature cards with safe textContent rendering.
 */
function renderFeatureCards(features, measurements) {
  if (!featureCardsList) return;
  featureCardsList.replaceChildren();

  if (!features || features.length === 0) {
    const emptyNotice = document.createElement("div");
    emptyNotice.textContent = "No entities present in ingested dataset.";
    emptyNotice.className = "empty-notice";
    featureCardsList.appendChild(emptyNotice);
    return;
  }

  features.forEach((feat, idx) => {
    // Find matching measurement
    const meas = measurements.find(m => String(m.feature_id) === String(feat.id));

    const card = document.createElement("div");
    card.className = "feature-item-card";
    card.setAttribute("role", "listitem");
    card.setAttribute("data-feature-idx", `${idx}`);

    // Card Header
    const cardHeader = document.createElement("div");
    cardHeader.className = "feature-card-header";

    const titleRow = document.createElement("div");
    titleRow.className = "feature-title-row";

    const indexBadge = document.createElement("span");
    indexBadge.className = "feature-index";
    indexBadge.textContent = `FEATURE ${(idx + 1).toString().padStart(2, '0')}`;

    const geomType = document.createElement("span");
    geomType.className = "feature-geom-type";
    geomType.textContent = feat.geometry_type.toUpperCase();

    titleRow.appendChild(indexBadge);
    titleRow.appendChild(geomType);

    const statusBadge = document.createElement("span");
    const statusText = meas ? meas.status : feat.status;
    statusBadge.textContent = statusText;
    statusBadge.className = `feature-card-status status-${statusText.toLowerCase()}`;

    cardHeader.appendChild(titleRow);
    cardHeader.appendChild(statusBadge);
    card.appendChild(cardHeader);

    // Card Details Body
    const cardBody = document.createElement("div");
    cardBody.className = "feature-card-body";

    // Measurement Row
    const measRow = document.createElement("div");
    measRow.className = "feature-detail-row";
    const measLabel = document.createElement("span");
    measLabel.className = "feature-detail-label";
    measLabel.textContent = "Metric Calculation:";
    const measVal = document.createElement("span");
    measVal.className = "feature-detail-val";

    if (meas && meas.measurement) {
      const unit = meas.measurement.unit === "square_meters" ? "m²" : "m";
      measVal.textContent = `${formatNumber(meas.measurement.value, 2)} ${unit}`;
    } else if (meas && meas.note) {
      measVal.textContent = meas.note;
    } else {
      measVal.textContent = "None";
    }
    measRow.appendChild(measLabel);
    measRow.appendChild(measVal);
    cardBody.appendChild(measRow);

    // Properties Rows
    if (feat.properties && typeof feat.properties === "object") {
      Object.entries(feat.properties).forEach(([k, v]) => {
        const propRow = document.createElement("div");
        propRow.className = "feature-detail-row";
        const propLabel = document.createElement("span");
        propLabel.className = "feature-detail-label";
        propLabel.textContent = `${k}:`;
        const propVal = document.createElement("span");
        propVal.className = "feature-detail-val";
        propVal.textContent = String(v);
        propRow.appendChild(propLabel);
        propRow.appendChild(propVal);
        cardBody.appendChild(propRow);
      });
    }

    card.appendChild(cardBody);

    // Click handler to expand/collapse card
    card.addEventListener("click", () => {
      card.classList.toggle("expanded");
      if (spatialViewer) {
        spatialViewer.highlightFeature(idx);
      }
    });

    featureCardsList.appendChild(card);
  });
}

/**
 * Filter feature cards by text query.
 */
function filterFeatureCards(query) {
  if (!featureCardsList) return;
  const cards = featureCardsList.querySelectorAll(".feature-item-card");
  cards.forEach(card => {
    const text = card.textContent.toLowerCase();
    card.style.display = text.includes(query) ? "block" : "none";
  });
}

// ==============================================================================
// 7. INTERACTIVE GEOSPATIAL MAP VIEWPORT (Section 11)
// ==============================================================================

/**
 * Initialize Interactive Geospatial Map Viewport (Leaflet with 2D Canvas Fallback).
 */
function initSpatialGeometryCanvas() {
  const hasLeaflet = (typeof window.L !== "undefined" && leafletMapEl);

  if (hasLeaflet) {
    // 1. Initialize Leaflet Map
    const map = L.map(leafletMapEl, {
      zoomControl: false,
      attributionControl: true,
      fadeAnimation: true,
      zoomAnimation: true,
      minZoom: 1,
      maxZoom: 19
    }).setView([20, 0], 2);

    // 2. High-Resolution Basemap Tile Providers (100% Free & Watermark-Free)
    const tileLayers = {
      streets: L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
        attribution: '&copy; <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener">OpenStreetMap</a> contributors',
        maxZoom: 19
      }),
      satellite: L.tileLayer("https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}", {
        attribution: 'Tiles &copy; Esri &mdash; Earthstar Geographics, CNES/Airbus DS, USGS, AeroGRID, IGN',
        maxZoom: 19
      }),
      topo: L.tileLayer("https://server.arcgisonline.com/ArcGIS/rest/services/World_Topo_Map/MapServer/tile/{z}/{y}/{x}", {
        attribution: 'Tiles &copy; Esri &mdash; USGS, FAO, NPS, NRCAN, GeoBase, Ordnance Survey',
        maxZoom: 19
      })
    };

    let activeBasemapKey = "auto";
    let currentTileLayer = tileLayers.streets;
    currentTileLayer.addTo(map);

    function applyTileDarkMode(enable) {
      if (!leafletMapEl) return;
      if (enable) {
        leafletMapEl.classList.add("leaflet-map-dark");
      } else {
        leafletMapEl.classList.remove("leaflet-map-dark");
      }
    }

    function switchBasemap(key) {
      activeBasemapKey = key;
      if (currentTileLayer) {
        map.removeLayer(currentTileLayer);
      }

      if (key === "auto") {
        currentTileLayer = tileLayers.streets;
        applyTileDarkMode(currentTheme === "dark");
      } else if (key === "streets") {
        currentTileLayer = tileLayers.streets;
        applyTileDarkMode(false);
      } else if (key === "satellite") {
        currentTileLayer = tileLayers.satellite;
        applyTileDarkMode(false);
      } else if (key === "topo") {
        currentTileLayer = tileLayers.topo;
        applyTileDarkMode(false);
      }

      currentTileLayer.addTo(map);

      // Synchronize basemap pill buttons
      const pills = document.querySelectorAll(".basemap-pill");
      pills.forEach(p => {
        if (p.getAttribute("data-map") === key) {
          p.classList.add("active");
        } else {
          p.classList.remove("active");
        }
      });
    }

    // Initial theme tile mode
    applyTileDarkMode(currentTheme === "dark");

    // Basemap pill click handlers
    const pills = document.querySelectorAll(".basemap-pill");
    pills.forEach(p => {
      p.addEventListener("click", () => {
        const targetMap = p.getAttribute("data-map");
        switchBasemap(targetMap);
      });
    });

    // Vector feature layer group
    const featureGroup = L.featureGroup().addTo(map);
    const layerByIndex = new Map();

    // Map Telemetry HUD Coordinates Tracker
    function updateMapHud() {
      if (!mapHudCoords || !mapHudZoom) return;
      const center = map.getCenter();
      const zoom = map.getZoom();
      const latStr = `${Math.abs(center.lat).toFixed(4)}° ${center.lat >= 0 ? "N" : "S"}`;
      const lonStr = `${Math.abs(center.lng).toFixed(4)}° ${center.lng >= 0 ? "E" : "W"}`;
      mapHudCoords.textContent = `Center: ${latStr}, ${lonStr}`;
      mapHudZoom.textContent = `Zoom ${zoom}`;
    }

    map.on("move", updateMapHud);
    map.on("zoomend", updateMapHud);
    updateMapHud();

    // Authoritative Spatial Viewer Object
    spatialViewer = {
      map: map,
      featureGroup: featureGroup,
      layerByIndex: layerByIndex,
      features: [],
      highlightIdx: -1,
      isCleared: false,

      loadGeometries(features) {
        this.features = features || [];
        this.isCleared = false;
        this.layerByIndex.clear();
        this.featureGroup.clearLayers();

        if (geomCountBadge) {
          geomCountBadge.textContent = `${this.features.length} Geometrie${this.features.length === 1 ? '' : 's'}`;
        }

        if (mapEmptyOverlay) {
          mapEmptyOverlay.style.display = this.features.length ? "none" : "flex";
          if (!this.features.length) {
            mapEmptyOverlay.textContent = "Ingest a dataset to render vector geometry on the map.";
          }
        }

        if (!this.features.length) {
          this.map.setView([20, 0], 2);
          return;
        }

        // Render each feature geometry into Leaflet
        this.features.forEach((feat, idx) => {
          const geom = feat.geometry;
          if (!geom || !geom.coordinates) return;

          // Find associated measurement if available
          const meas = (currentMeasurements && currentMeasurements[idx]) ? currentMeasurements[idx] : null;

          // Helper to normalize/reproject coordinates safely
          const normCoord = (pt) => {
            if (!Array.isArray(pt) || pt.length < 2) return [0, 0];
            let x = pt[0];
            let y = pt[1];
            // Reproject if outside valid WGS84 range and proj4 is available
            if ((Math.abs(x) > 180 || Math.abs(y) > 90) && typeof window.proj4 !== "undefined") {
              const srcCrs = (meas && meas.input_crs) || (summaryCrs ? summaryCrs.textContent : null);
              if (srcCrs && srcCrs !== "None") {
                try {
                  const projPt = window.proj4(srcCrs, "EPSG:4326", [x, y]);
                  return [projPt[1], projPt[0]]; // Leaflet expects [lat, lon]
                } catch (e) {
                  // Fallback to original
                }
              }
            }
            // GeoJSON coordinates are [lon, lat], Leaflet uses [lat, lon]
            return [y, x];
          };

          let layer = null;

          if (feat.geometry_type === "Polygon") {
            const rawCoords = geom.coordinates;
            const rings = Array.isArray(rawCoords[0][0]) ? rawCoords : [rawCoords];
            const latLngRings = rings.map(ring => ring.map(normCoord));

            layer = L.polygon(latLngRings, {
              color: "#10b981",
              weight: 2.5,
              opacity: 0.95,
              fillColor: "#10b981",
              fillOpacity: 0.22,
              lineCap: "round",
              lineJoin: "round"
            });

          } else if (feat.geometry_type === "LineString") {
            const latLngs = geom.coordinates.map(normCoord);
            layer = L.polyline(latLngs, {
              color: "#f59e0b",
              weight: 3.5,
              opacity: 0.95,
              lineCap: "round",
              lineJoin: "round"
            });

          } else if (feat.geometry_type === "Point") {
            const latLng = normCoord(geom.coordinates);
            layer = L.circleMarker(latLng, {
              radius: 7,
              color: "#ffffff",
              weight: 2,
              fillColor: "#6366f1",
              fillOpacity: 0.95
            });
          }

          if (layer) {
            // Build safe DOM popup content using standard DOM nodes
            const popupNode = document.createElement("div");
            popupNode.className = "map-popup-card";

            const headerNode = document.createElement("div");
            headerNode.className = "map-popup-header";

            const badgeNode = document.createElement("span");
            badgeNode.className = `map-popup-type-badge type-${feat.geometry_type.toLowerCase()}`;
            badgeNode.textContent = feat.geometry_type.toUpperCase();

            const idxNode = document.createElement("span");
            idxNode.className = "map-popup-idx";
            idxNode.textContent = `Feature #${idx + 1}`;

            headerNode.appendChild(badgeNode);
            headerNode.appendChild(idxNode);
            popupNode.appendChild(headerNode);

            if (meas && meas.measurement) {
              const measRow = document.createElement("div");
              measRow.className = "map-popup-metric-row";
              const mLabel = document.createElement("span");
              mLabel.className = "map-popup-metric-label";
              mLabel.textContent = meas.measurement.type === "area" ? "Area:" : "Length:";
              const mVal = document.createElement("span");
              mVal.className = "map-popup-metric-val";
              const unitStr = meas.measurement.unit === "square_meters" ? "m²" : "m";
              mVal.textContent = `${formatNumber(meas.measurement.value, 2)} ${unitStr}`;
              measRow.appendChild(mLabel);
              measRow.appendChild(mVal);
              popupNode.appendChild(measRow);
            }

            if (feat.properties && typeof feat.properties === "object") {
              const propsNode = document.createElement("div");
              propsNode.className = "map-popup-props";
              Object.entries(feat.properties).slice(0, 5).forEach(([k, v]) => {
                const pRow = document.createElement("div");
                pRow.className = "map-popup-prop-row";
                const pKey = document.createElement("span");
                pKey.className = "map-popup-prop-key";
                pKey.textContent = `${k}:`;
                const pVal = document.createElement("span");
                pVal.className = "map-popup-prop-val";
                pVal.textContent = String(v);
                pRow.appendChild(pKey);
                pRow.appendChild(pVal);
                propsNode.appendChild(pRow);
              });
              popupNode.appendChild(propsNode);
            }

            layer.bindPopup(popupNode, {
              className: "custom-leaflet-popup",
              closeButton: false,
              offset: [0, -6]
            });

            // Interactive hover & selection synchronization
            layer.on("mouseover", () => {
              if (this.highlightIdx !== idx) {
                if (feat.geometry_type === "Polygon") {
                  layer.setStyle({ weight: 3.5, fillOpacity: 0.38 });
                } else if (feat.geometry_type === "LineString") {
                  layer.setStyle({ weight: 5 });
                } else if (feat.geometry_type === "Point") {
                  layer.setRadius(9);
                }
              }
            });

            layer.on("mouseout", () => {
              if (this.highlightIdx !== idx) {
                if (feat.geometry_type === "Polygon") {
                  layer.setStyle({ weight: 2.5, fillOpacity: 0.22 });
                } else if (feat.geometry_type === "LineString") {
                  layer.setStyle({ weight: 3.5 });
                } else if (feat.geometry_type === "Point") {
                  layer.setRadius(7);
                }
              }
            });

            layer.on("click", () => {
              this.highlightFeature(idx);
              // Scroll and expand corresponding card in Section 05
              const cards = featureCardsList ? featureCardsList.querySelectorAll(".feature-item-card") : [];
              if (cards[idx]) {
                cards[idx].scrollIntoView({ behavior: "smooth", block: "nearest" });
                cards[idx].classList.add("expanded");
              }
            });

            this.featureGroup.addLayer(layer);
            this.layerByIndex.set(idx, { layer, feat, type: feat.geometry_type });
          }
        });

        this.fit();
        setTimeout(() => {
          if (this.map) {
            this.map.invalidateSize();
            if (this.featureGroup && this.featureGroup.getLayers().length > 0) {
              const bounds = this.featureGroup.getBounds();
              if (bounds.isValid()) {
                this.map.fitBounds(bounds, { padding: [40, 40], maxZoom: 16 });
              }
            }
          }
        }, 120);
      },

      fit() {
        if (this.map) {
          this.map.invalidateSize();
        }
        if (this.isCleared && currentFeatures && currentFeatures.length) {
          // Restore if currently cleared
          this.loadGeometries(currentFeatures);
          return;
        }

        if (this.featureGroup && this.featureGroup.getLayers().length > 0) {
          const bounds = this.featureGroup.getBounds();
          if (bounds.isValid()) {
            this.map.fitBounds(bounds, { padding: [40, 40], maxZoom: 16 });
          }
        } else {
          this.map.setView([20, 0], 2);
        }
      },

      clear() {
        if (this.featureGroup) {
          this.featureGroup.clearLayers();
        }
        this.layerByIndex.clear();
        this.features = [];
        this.highlightIdx = -1;
        this.isCleared = true;

        if (geomCountBadge) {
          geomCountBadge.textContent = "0 Geometries";
        }

        this.map.closePopup();
        this.map.setView([20, 0], 2);

        if (mapEmptyOverlay) {
          mapEmptyOverlay.textContent = "Viewport cleared. Ingest a dataset or click FIT to reload.";
          mapEmptyOverlay.style.display = "flex";
        }
      },

      highlightFeature(idx) {
        // Reset previously highlighted layer
        if (this.highlightIdx >= 0 && this.layerByIndex.has(this.highlightIdx)) {
          const prev = this.layerByIndex.get(this.highlightIdx);
          if (prev.type === "Polygon") {
            prev.layer.setStyle({ color: "#10b981", weight: 2.5, fillOpacity: 0.22 });
          } else if (prev.type === "LineString") {
            prev.layer.setStyle({ color: "#f59e0b", weight: 3.5 });
          } else if (prev.type === "Point") {
            prev.layer.setRadius(7);
            prev.layer.setStyle({ fillColor: "#6366f1" });
          }
        }

        this.highlightIdx = idx;

        if (this.layerByIndex.has(idx)) {
          const target = this.layerByIndex.get(idx);
          if (target.type === "Polygon") {
            target.layer.setStyle({ color: "#34d399", weight: 4, fillOpacity: 0.45 });
          } else if (target.type === "LineString") {
            target.layer.setStyle({ color: "#fbbf24", weight: 5 });
          } else if (target.type === "Point") {
            target.layer.setRadius(10);
            target.layer.setStyle({ fillColor: "#818cf8" });
          }

          if (target.layer.getBounds) {
            this.map.flyToBounds(target.layer.getBounds(), { padding: [50, 50], maxZoom: 16 });
          } else if (target.layer.getLatLng) {
            this.map.flyTo(target.layer.getLatLng(), 15);
          }

          target.layer.openPopup();
        }
      },

      updateTheme(theme) {
        if (activeBasemapKey === "auto") {
          switchBasemap("auto");
        }
      },

      render() {
        this.fit();
      }
    };

    // Controls wiring
    if (zoomInBtn) {
      zoomInBtn.addEventListener("click", () => map.zoomIn());
    }
    if (zoomOutBtn) {
      zoomOutBtn.addEventListener("click", () => map.zoomOut());
    }
    if (zoomFitBtn) {
      zoomFitBtn.addEventListener("click", () => spatialViewer.fit());
    }
    if (clearViewBtn) {
      clearViewBtn.addEventListener("click", () => spatialViewer.clear());
    }

    // Invalidate map size to ensure tiles render immediately
    setTimeout(() => {
      map.invalidateSize();
    }, 200);

    return;
  }

  // Fallback to 2D Canvas if Leaflet is not loaded
  if (!geometryCanvas) return;

  spatialViewer = {
    canvas: geometryCanvas,
    ctx: geometryCanvas.getContext("2d"),
    features: [],
    zoom: 1,
    offsetX: 0,
    offsetY: 0,
    highlightIdx: -1,

    loadGeometries(features) {
      this.features = features || [];
      if (geomCountBadge) {
        geomCountBadge.textContent = `${this.features.length} Geometrie${this.features.length === 1 ? '' : 's'}`;
      }
      this.fit();
    },

    clear() {
      this.features = [];
      this.highlightIdx = -1;
      if (geomCountBadge) {
        geomCountBadge.textContent = "0 Geometries";
      }
      this.render();
    },

    fit() {
      if (!this.features.length) {
        this.render();
        return;
      }

      // Compute bounding box
      let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
      this.features.forEach(f => {
        this.extractCoordinates(f.geometry).forEach(([x, y]) => {
          if (x < minX) minX = x;
          if (y < minY) minY = y;
          if (x > maxX) maxX = x;
          if (y > maxY) maxY = y;
        });
      });

      if (minX === Infinity) {
        minX = -180; maxX = 180; minY = -90; maxY = 90;
      }

      const padding = 40;
      const w = this.canvas.width;
      const h = this.canvas.height;
      const dx = maxX - minX || 0.001;
      const dy = maxY - minY || 0.001;

      const scaleX = (w - padding * 2) / dx;
      const scaleY = (h - padding * 2) / dy;
      this.zoom = Math.min(scaleX, scaleY);

      this.offsetX = w / 2 - ((minX + maxX) / 2) * this.zoom;
      this.offsetY = h / 2 + ((minY + maxY) / 2) * this.zoom;

      this.render();
    },

    highlightFeature(idx) {
      this.highlightIdx = idx;
      this.render();
    },

    extractCoordinates(geom) {
      const coords = [];
      if (!geom || !geom.coordinates) return coords;

      function recurse(arr) {
        if (Array.isArray(arr) && arr.length >= 2 && typeof arr[0] === "number") {
          coords.push([arr[0], arr[1]]);
        } else if (Array.isArray(arr)) {
          arr.forEach(recurse);
        }
      }
      recurse(geom.coordinates);
      return coords;
    },

    render() {
      const ctx = this.ctx;
      const w = this.canvas.width;
      const h = this.canvas.height;

      ctx.fillStyle = currentTheme === "dark" ? "#070b14" : "#f8fafc";
      ctx.fillRect(0, 0, w, h);

      ctx.strokeStyle = currentTheme === "dark" ? "rgba(255, 255, 255, 0.04)" : "rgba(15, 23, 42, 0.04)";
      ctx.lineWidth = 1;
      for (let x = 0; x < w; x += 40) {
        ctx.beginPath(); ctx.moveTo(x, 0); ctx.lineTo(x, h); ctx.stroke();
      }
      for (let y = 0; y < h; y += 40) {
        ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(w, y); ctx.stroke();
      }

      if (!this.features.length) {
        ctx.fillStyle = currentTheme === "dark" ? "#64748b" : "#94a3b8";
        ctx.font = "12px JetBrains Mono";
        ctx.textAlign = "center";
        ctx.fillText("Ingest a dataset to render vector geometry.", w / 2, h / 2);
        return;
      }

      this.features.forEach((feat, idx) => {
        const isHighlighted = (idx === this.highlightIdx);
        const geom = feat.geometry;
        if (!geom) return;

        ctx.save();

        if (feat.geometry_type === "Polygon") {
          ctx.fillStyle = isHighlighted ? "rgba(16, 185, 129, 0.35)" : "rgba(16, 185, 129, 0.18)";
          ctx.strokeStyle = isHighlighted ? "#34d399" : "#10b981";
          ctx.lineWidth = isHighlighted ? 3 : 2;

          this.drawPolygon(geom.coordinates);
          ctx.fill();
          ctx.stroke();

        } else if (feat.geometry_type === "LineString") {
          ctx.strokeStyle = isHighlighted ? "#fbbf24" : "#f59e0b";
          ctx.lineWidth = isHighlighted ? 4 : 2.5;

          this.drawLineString(geom.coordinates);
          ctx.stroke();

        } else if (feat.geometry_type === "Point") {
          const pt = geom.coordinates;
          if (Array.isArray(pt) && pt.length >= 2) {
            const cx = pt[0] * this.zoom + this.offsetX;
            const cy = -pt[1] * this.zoom + this.offsetY;

            ctx.fillStyle = isHighlighted ? "#818cf8" : "#6366f1";
            ctx.beginPath();
            ctx.arc(cx, cy, isHighlighted ? 7 : 5, 0, 2 * Math.PI);
            ctx.fill();

            ctx.strokeStyle = "#ffffff";
            ctx.lineWidth = 1.5;
            ctx.stroke();
          }
        }

        ctx.restore();
      });
    },

    drawPolygon(coords) {
      const ctx = this.ctx;
      if (!Array.isArray(coords) || !coords.length) return;

      const ring = Array.isArray(coords[0][0]) ? coords[0] : coords;
      ctx.beginPath();
      ring.forEach((pt, i) => {
        const x = pt[0] * this.zoom + this.offsetX;
        const y = -pt[1] * this.zoom + this.offsetY;
        if (i === 0) ctx.moveTo(x, y);
        else ctx.lineTo(x, y);
      });
      ctx.closePath();
    },

    drawLineString(coords) {
      const ctx = this.ctx;
      if (!Array.isArray(coords) || !coords.length) return;

      ctx.beginPath();
      coords.forEach((pt, i) => {
        const x = pt[0] * this.zoom + this.offsetX;
        const y = -pt[1] * this.zoom + this.offsetY;
        if (i === 0) ctx.moveTo(x, y);
        else ctx.lineTo(x, y);
      });
    }
  };

  // Wire viewport controls for canvas fallback
  if (zoomInBtn) {
    zoomInBtn.addEventListener("click", () => {
      spatialViewer.zoom *= 1.25;
      spatialViewer.render();
    });
  }
  if (zoomOutBtn) {
    zoomOutBtn.addEventListener("click", () => {
      spatialViewer.zoom *= 0.8;
      spatialViewer.render();
    });
  }
  if (zoomFitBtn) {
    zoomFitBtn.addEventListener("click", () => {
      spatialViewer.fit();
    });
  }
  if (clearViewBtn) {
    clearViewBtn.addEventListener("click", () => {
      spatialViewer.clear();
    });
  }
}

// ==============================================================================
// 8. RELATIONAL DATA TABLES (Strict Part 9A Test Suite Compatibility)
// ==============================================================================

/**
 * Clear existing table rows before loading new dataset.
 */
function clearRenderedTables() {
  if (measurementsTbody) measurementsTbody.replaceChildren();
  if (featuresTbody) featuresTbody.replaceChildren();
  if (featureCardsList) featureCardsList.replaceChildren();
}

/**
 * Render authoritative database tables safely using textContent.
 */
function renderRelationalTables(measurements, features) {
  clearRenderedTables();

  // Render Measurements Table
  if (measurementsTbody && Array.isArray(measurements)) {
    measurements.forEach(m => {
      const tr = document.createElement("tr");

      // 1. Feature ID
      const tdId = document.createElement("td");
      const idStr = String(m.feature_id ?? '');
      tdId.textContent = idStr.length > 8 ? idStr.substring(0, 8) + '...' : (idStr || '-');
      tr.appendChild(tdId);

      // 2. Geometry Type
      const tdGeom = document.createElement("td");
      tdGeom.textContent = m.geometry_type;
      tr.appendChild(tdGeom);

      // 3. Metric Type
      const tdType = document.createElement("td");
      tdType.textContent = m.measurement ? m.measurement.type : '-';
      tr.appendChild(tdType);

      // 4. Calculated Value
      const tdVal = document.createElement("td");
      if (m.measurement) {
        const unit = m.measurement.unit === "square_meters" ? "m²" : "m";
        tdVal.textContent = `${formatNumber(m.measurement.value, 4)} ${unit}`;
      } else {
        tdVal.textContent = '-';
      }
      tr.appendChild(tdVal);

      // 5. Input CRS
      const tdInCrs = document.createElement("td");
      tdInCrs.textContent = m.measurement ? m.measurement.input_crs : '-';
      tr.appendChild(tdInCrs);

      // 6. Projected CRS
      const tdProjCrs = document.createElement("td");
      tdProjCrs.textContent = m.measurement ? m.measurement.projected_crs : '-';
      tr.appendChild(tdProjCrs);

      // 7. Status
      const tdStatus = document.createElement("td");
      const badge = document.createElement("span");
      badge.textContent = m.status;
      badge.className = `badge badge-${m.status.toLowerCase()}`;
      tdStatus.appendChild(badge);
      tr.appendChild(tdStatus);

      // 8. Notes
      const tdNotes = document.createElement("td");
      tdNotes.textContent = m.note || '-';
      tr.appendChild(tdNotes);

      measurementsTbody.appendChild(tr);
    });
  }

  // Render Features Table
  if (featuresTbody && Array.isArray(features)) {
    features.forEach(f => {
      const tr = document.createElement("tr");

      // 1. Feature ID
      const tdId = document.createElement("td");
      const fIdStr = String(f.id ?? '');
      tdId.textContent = fIdStr.length > 8 ? fIdStr.substring(0, 8) + '...' : (fIdStr || '-');
      tr.appendChild(tdId);

      // 2. Geometry Type
      const tdGeom = document.createElement("td");
      tdGeom.textContent = f.geometry_type;
      tr.appendChild(tdGeom);

      // 3. Status
      const tdStatus = document.createElement("td");
      const badge = document.createElement("span");
      badge.textContent = f.status;
      badge.className = `badge badge-${f.status.toLowerCase()}`;
      tdStatus.appendChild(badge);
      tr.appendChild(tdStatus);

      // 4. Properties (Safe JSON stringification with textContent)
      const tdProps = document.createElement("td");
      tdProps.textContent = f.properties ? JSON.stringify(f.properties) : '{}';
      tr.appendChild(tdProps);

      featuresTbody.appendChild(tr);
    });
  }
}

// ==============================================================================
// 9. ERROR HANDLING & DISPLAY UTILITIES (Section 14)
// ==============================================================================

/**
 * Display restrained, formatted error alert card.
 */
function showError(title, message) {
  if (errorTitle) errorTitle.textContent = title;
  if (errorMessage) errorMessage.textContent = message;
  if (errorSection) {
    errorSection.style.display = "block";
    errorSection.scrollIntoView({ behavior: "smooth", block: "center" });
  }
}

/**
 * Hide error section.
 */
function hideError() {
  if (errorSection) errorSection.style.display = "none";
}

// ==============================================================================
// 10. FORMATTING UTILITIES
// ==============================================================================

function getFileExtension(filename) {
  const idx = filename.lastIndexOf(".");
  return idx !== -1 ? filename.substring(idx) : "";
}

function formatFileSize(bytes) {
  if (bytes === 0) return "0 Bytes";
  const k = 1024;
  const sizes = ["Bytes", "KB", "MB", "GB"];
  const i = Math.floor(Math.log(bytes) / Math.log(k));
  return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + " " + sizes[i];
}

function formatNumber(num, decimals = 2) {
  if (num === null || num === undefined || isNaN(num)) return "-";
  return Number(num).toLocaleString('en-US', {
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  });
}
