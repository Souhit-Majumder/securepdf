import React, { useEffect, useRef } from "react";

export interface GradientASCIIProps {
  /** Array of hex colors for the gradient (e.g. ['#0f172a', '#1e3a8a', '#0284c7', '#38bdf8', '#f8fafc']) */
  colors?: string[];
  /** Pattern shape: 'horizon' | 'radial' | 'wave' */
  shape?: "horizon" | "radial" | "wave";
  /** Character ramp ordered from low to high density/luminance */
  characters?: string;
  /** Size of each grid cell in pixels (default 18) */
  cellSize?: number;
  /** Density multiplier for character placement between 0 and 1 (default 0.8) */
  density?: number;
  /** Speed multiplier for animation (default 1.0) */
  speed?: number;
  /** Additional CSS class names */
  className?: string;
  /** Additional inline styles */
  style?: React.CSSProperties;
}

// Helper to convert hex color to RGB triplet
function hexToRgb(hex: string): [number, number, number] {
  const clean = hex.replace("#", "").trim();
  if (clean.length === 3) {
    const r = parseInt(clean[0] + clean[0], 16);
    const g = parseInt(clean[1] + clean[1], 16);
    const b = parseInt(clean[2] + clean[2], 16);
    return [r, g, b];
  }
  const r = parseInt(clean.substring(0, 2), 16) || 0;
  const g = parseInt(clean.substring(2, 4), 16) || 0;
  const b = parseInt(clean.substring(4, 6), 16) || 0;
  return [r, g, b];
}

// Linear interpolation between two RGB colors
function interpolateRgb(
  c1: [number, number, number],
  c2: [number, number, number],
  t: number
): [number, number, number] {
  return [
    Math.round(c1[0] + (c2[0] - c1[0]) * t),
    Math.round(c1[1] + (c2[1] - c1[1]) * t),
    Math.round(c1[2] + (c2[2] - c1[2]) * t),
  ];
}

// Multi-stop color map interpolation
function samplePalette(
  palette: [number, number, number][],
  t: number
): [number, number, number] {
  if (palette.length === 0) return [255, 255, 255];
  if (palette.length === 1) return palette[0];

  const clamped = Math.max(0, Math.min(1, t));
  const segmentCount = palette.length - 1;
  const pos = clamped * segmentCount;
  const index = Math.min(Math.floor(pos), segmentCount - 1);
  const fraction = pos - index;

  return interpolateRgb(palette[index], palette[index + 1], fraction);
}

/**
 * SecurePDF Gradient ASCII Background
 *
 * Implements the React Bits Gradient ASCII effect adapted to SecurePDF's
 * cyan, blue, white, and navy palette with non-blocking pointer events,
 * reduced-motion accessibility support, and optimal rendering performance.
 */
export const GradientASCII: React.FC<GradientASCIIProps> = ({
  colors = ["#090d16", "#1e3a8a", "#0284c7", "#38bdf8", "#f8fafc"],
  shape = "horizon",
  characters = " =+xX0S8#@",
  cellSize = 18,
  density = 0.8,
  speed = 1.0,
  className = "",
  style = {},
}) => {
  const containerRef = useRef<HTMLDivElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    const container = containerRef.current;
    if (!canvas || !container) return;

    const ctx = canvas.getContext("2d", { alpha: true });
    if (!ctx) return;

    // Convert input hex colors to RGB triplets once
    const rgbColors = colors.map(hexToRgb);

    let animationFrameId: number;
    let width = 0;
    let height = 0;
    let cols = 0;
    let rows = 0;
    let time = 0;

    // Check prefers-reduced-motion
    const mediaQuery = window.matchMedia("(prefers-reduced-motion: reduce)");
    let prefersReducedMotion = mediaQuery.matches;

    const handleMotionChange = (e: MediaQueryListEvent) => {
      prefersReducedMotion = e.matches;
      if (prefersReducedMotion) {
        renderFrame(0);
      }
    };
    mediaQuery.addEventListener("change", handleMotionChange);

    const updateSize = () => {
      if (!container || !canvas) return;
      const rect = container.getBoundingClientRect();
      const dpr = Math.min(window.devicePixelRatio || 1, 1.5); // Cap DPR to 1.5 for performance

      width = Math.max(rect.width, 100);
      height = Math.max(rect.height, 100);

      canvas.width = Math.floor(width * dpr);
      canvas.height = Math.floor(height * dpr);
      canvas.style.width = `${width}px`;
      canvas.style.height = `${height}px`;

      ctx.scale(dpr, dpr);

      cols = Math.ceil(width / cellSize);
      rows = Math.ceil(height / cellSize);
    };

    updateSize();

    const resizeObserver = new ResizeObserver(() => {
      updateSize();
      if (prefersReducedMotion) {
        renderFrame(0);
      }
    });
    resizeObserver.observe(container);

    // Compute field intensity based on coordinates, shape, and time
    const computeField = (
      xNorm: number,
      yNorm: number,
      t: number
    ): number => {
      if (shape === "radial") {
        const dx = (xNorm - 0.5) * 2;
        const dy = (yNorm - 0.5) * 2;
        const dist = Math.sqrt(dx * dx + dy * dy);
        return (Math.sin(dist * 3.5 - t * 0.8) + 1) * 0.5;
      }

      if (shape === "wave") {
        const v1 = Math.sin(xNorm * 4 + t * 0.7);
        const v2 = Math.cos(yNorm * 3 - t * 0.5);
        const v3 = Math.sin((xNorm + yNorm) * 2.5 + t * 0.3);
        return (v1 + v2 + v3 + 3) / 6;
      }

      // Default: "horizon"
      // Creates a fluid undulating horizon line reminiscent of digital security waves
      const wave1 = Math.sin(xNorm * 3.2 + t * 0.6) * 0.22;
      const wave2 = Math.cos(xNorm * 1.8 - t * 0.4) * 0.12;
      const horizonLine = 0.52 + wave1 + wave2;
      const distFromHorizon = yNorm - horizonLine;

      // Soft sigmoid falloff from horizon
      const falloff = 1 / (1 + Math.exp(-distFromHorizon * 7));
      const pulse = Math.sin(yNorm * 4 + t * 0.4) * 0.08;

      return Math.max(0, Math.min(1, falloff + pulse));
    };

    // Render a single frame of ASCII characters
    const renderFrame = (currentTime: number) => {
      ctx.clearRect(0, 0, width, height);

      const fontSize = Math.floor(cellSize * 0.85);
      ctx.font = `600 ${fontSize}px "JetBrains Mono", "SF Mono", "Fira Code", "Courier New", monospace`;
      ctx.textAlign = "center";
      ctx.textBaseline = "middle";

      const charCount = characters.length;
      if (charCount === 0) return;

      for (let r = 0; r < rows; r++) {
        const yCenter = r * cellSize + cellSize / 2;
        const yNorm = r / Math.max(rows - 1, 1);

        for (let c = 0; c < cols; c++) {
          const xCenter = c * cellSize + cellSize / 2;
          const xNorm = c / Math.max(cols - 1, 1);

          // Deterministic pseudorandom hash for density filtering
          const cellHash = Math.abs(
            Math.sin(c * 12.9898 + r * 78.233) * 43758.5453
          ) % 1;
          if (cellHash > density) continue;

          // Compute intensity field
          const intensity = computeField(xNorm, yNorm, currentTime);

          // Select ASCII character based on field intensity
          const charIndex = Math.min(
            Math.floor(intensity * charCount),
            charCount - 1
          );
          const char = characters[charIndex];

          // Skip space characters early
          if (!char || char === " ") continue;

          // Sample color from palette
          const [red, green, blue] = samplePalette(rgbColors, intensity);

          // Alpha modulation: dim quieter glyphs slightly for visual depth
          const alpha = 0.35 + intensity * 0.65;
          ctx.fillStyle = `rgba(${red}, ${green}, ${blue}, ${alpha})`;

          ctx.fillText(char, xCenter, yCenter);
        }
      }
    };

    // Animation loop
    const animate = () => {
      if (document.hidden) {
        // Pause rendering when tab is not visible to save CPU/battery
        animationFrameId = requestAnimationFrame(animate);
        return;
      }

      time += 0.02 * speed;
      renderFrame(time);
      animationFrameId = requestAnimationFrame(animate);
    };

    if (prefersReducedMotion) {
      renderFrame(0);
    } else {
      animate();
    }

    return () => {
      cancelAnimationFrame(animationFrameId);
      resizeObserver.disconnect();
      mediaQuery.removeEventListener("change", handleMotionChange);
    };
  }, [colors, shape, characters, cellSize, density, speed]);

  return (
    <div
      ref={containerRef}
      className={`pointer-events-none select-none overflow-hidden ${className}`}
      style={{
        position: "absolute",
        inset: 0,
        zIndex: 0,
        ...style,
      }}
      aria-hidden="true"
    >
      <canvas ref={canvasRef} className="block w-full h-full" />
    </div>
  );
};

export default GradientASCII;
