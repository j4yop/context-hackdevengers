"use client";

import React, { useEffect, useRef } from "react";
import { cn } from "@/lib/utils";

// Constants for wave animation behavior
const WAVE_THRESH = 3;
const CHAR_MULT = 3;
const ANIM_STEP = 40;
const WAVE_BUF = 5;

export interface AsciiGlitchRippleProps extends React.AnchorHTMLAttributes<HTMLAnchorElement> {
  /**
   * The text to display and animate.
   */
  children: string;
  /**
   * The HTML element or component to render as.
   * @default "a"
   */
  as?: any;
  /**
   * Additional CSS classes.
   */
  className?: string;
  /**
   * Duration of each ripple wave in milliseconds.
   * @default 1000
   */
  dur?: number;
  /**
   * Character set to scramble through during the ripple wave.
   * @default '.,·-─~+:;=*π""┐┌┘┴┬╗╔╝╚╬╠╣╩╦║░▒▓█▄▀▌▐■!?&#$@0123456789*'
   */
  chars?: string;
  /**
   * Whether to preserve space characters or scramble them too.
   * @default true
   */
  preserveSpaces?: boolean;
  /**
   * The spread of the ripple wave. Larger numbers mean wider waves.
   * @default 1.0
   */
  spread?: number;
  [key: string]: any;
}

export function AsciiGlitchRipple({
  children,
  as = "a",
  className,
  dur = 1000,
  chars = '.,·-─~+:;=*π""┐┌┘┴┬╗╔╝╚╬╠╣╩╦║░▒▓█▄▀▌▐■!?&#$@0123456789*',
  preserveSpaces = true,
  spread = 1.0,
  ...props
}: AsciiGlitchRippleProps) {
  const Component = as;
  const elRef = useRef<any>(null);

  // Use a mutable ref to store animation state, preventing unnecessary React renders
  const stateRef = useRef({
    origTxt: children,
    origChars: children.split(""),
    isAnim: false,
    cursorPos: 0,
    waves: [] as Array<{ startPos: number; startTime: number; id: number }>,
    animId: null as number | null,
    isHover: false,
    origW: null as number | null,
    dur,
    chars,
    preserveSpaces,
    spread,
  });

  // Keep internal mutable state updated when props change
  useEffect(() => {
    stateRef.current.origTxt = children;
    stateRef.current.origChars = children.split("");
    stateRef.current.dur = dur;
    stateRef.current.chars = chars;
    stateRef.current.preserveSpaces = preserveSpaces;
    stateRef.current.spread = spread;
  }, [children, dur, chars, preserveSpaces, spread]);

  useEffect(() => {
    const el = elRef.current;
    if (!el) return;

    // Build word and character spans to prevent any layout vibration
    const origTxt = stateRef.current.origTxt;
    const words = origTxt.split(" ");
    el.innerHTML = "";
    const charSpans: HTMLSpanElement[] = [];

    words.forEach((word, wIdx) => {
      const wSpan = document.createElement("span");
      wSpan.className = "agr-word";
      wSpan.style.display = "inline-block";
      wSpan.style.whiteSpace = "nowrap";

      for (let i = 0; i < word.length; i++) {
        const cSpan = document.createElement("span");
        cSpan.className = "agr-char";
        cSpan.setAttribute("data-orig", word[i]);
        cSpan.textContent = word[i];
        cSpan.style.display = "inline-block";
        cSpan.style.textAlign = "center";
        cSpan.style.overflow = "visible";
        wSpan.appendChild(cSpan);
        charSpans.push(cSpan);
      }
      el.appendChild(wSpan);
      if (wIdx < words.length - 1) {
        const spaceNode = document.createTextNode(" ");
        el.appendChild(spaceNode);
      }
    });

    const totalChars = charSpans.length;

    // Lock character widths and element min-height
    const lockMetrics = () => {
      charSpans.forEach((s) => {
        s.style.width = "";
      });
      el.style.minHeight = "";
      requestAnimationFrame(() => {
        charSpans.forEach((s) => {
          const r = s.getBoundingClientRect();
          s.style.width = `${Math.round(r.width * 100) / 100}px`;
        });
        const elRect = el.getBoundingClientRect();
        el.style.minHeight = `${Math.round(elRect.height)}px`;
      });
    };

    if (document.fonts && document.fonts.ready) {
      document.fonts.ready.then(lockMetrics);
    } else {
      lockMetrics();
    }

    let resizeTimer: any = null;
    const onResize = () => {
      clearTimeout(resizeTimer);
      resizeTimer = setTimeout(lockMetrics, 80);
    };
    window.addEventListener("resize", onResize);

    const updateCursorPos = (e: MouseEvent | Touch) => {
      const target = (e as any).target;
      const targetChar = target && target.closest ? target.closest(".agr-char") : null;
      if (targetChar) {
        const idx = charSpans.indexOf(targetChar);
        if (idx >= 0) {
          stateRef.current.cursorPos = idx;
          return;
        }
      }

      const clientX = (e as MouseEvent).clientX;
      const clientY = (e as MouseEvent).clientY;
      if (clientX === undefined || clientY === undefined) return;

      let nearestIdx = 0;
      let nearestDist = Infinity;
      for (let i = 0; i < charSpans.length; i++) {
        const r = charSpans[i].getBoundingClientRect();
        const cx = r.left + r.width / 2;
        const cy = r.top + r.height / 2;
        const d = (clientX - cx) ** 2 + (clientY - cy) ** 2;
        if (d < nearestDist) {
          nearestDist = d;
          nearestIdx = i;
        }
      }
      stateRef.current.cursorPos = nearestIdx;
    };

    const stop = () => {
      charSpans.forEach((s) => {
        s.textContent = s.getAttribute("data-orig") || "";
      });
      el.classList.remove("as");
      stateRef.current.isAnim = false;
      if (stateRef.current.animId) {
        cancelAnimationFrame(stateRef.current.animId);
        stateRef.current.animId = null;
      }
    };

    const calcWaveEffect = (charIdx: number, t: number) => {
      let shouldAnim = false;
      let resultChar = charSpans[charIdx].getAttribute("data-orig") || "";

      for (const w of stateRef.current.waves) {
        const age = t - w.startTime;
        const prog = Math.min(age / stateRef.current.dur, 1);
        const dist = Math.abs(charIdx - w.startPos);
        const maxDist = Math.max(w.startPos, totalChars - w.startPos - 1);
        const rad = (prog * (maxDist + WAVE_BUF)) / stateRef.current.spread;

        if (dist <= rad) {
          shouldAnim = true;
          const intens = Math.max(0, rad - dist);

          if (intens <= WAVE_THRESH && intens > 0) {
            const index =
              (dist * CHAR_MULT + Math.floor(age / ANIM_STEP)) % stateRef.current.chars.length;
            resultChar = stateRef.current.chars[index];
          }
        }
      }

      return { shouldAnim, char: resultChar };
    };

    const renderFrame = (t: number) => {
      for (let i = 0; i < totalChars; i++) {
        const span = charSpans[i];
        const orig = span.getAttribute("data-orig") || "";
        const res = calcWaveEffect(i, t);
        const nextChar = res.shouldAnim ? res.char : orig;
        if (span.textContent !== nextChar) {
          span.textContent = nextChar;
        }
      }
    };

    const start = () => {
      if (stateRef.current.isAnim) return;
      stateRef.current.isAnim = true;
      el.classList.add("as");

      const animate = () => {
        const t = performance.now();
        stateRef.current.waves = stateRef.current.waves.filter(
          (w) => t - w.startTime < stateRef.current.dur
        );

        if (stateRef.current.waves.length === 0) {
          stop();
          return;
        }

        renderFrame(t);
        stateRef.current.animId = requestAnimationFrame(animate);
      };

      stateRef.current.animId = requestAnimationFrame(animate);
    };

    let lastWaveTime = 0;
    const startWave = (customPos?: number) => {
      const now = performance.now();
      if (typeof customPos !== "number" && now - lastWaveTime < 75) {
        return;
      }
      lastWaveTime = now;

      if (stateRef.current.waves.length >= 3) {
        stateRef.current.waves.shift();
      }

      const pos = typeof customPos === "number" ? customPos : stateRef.current.cursorPos;
      stateRef.current.waves.push({
        startPos: Math.max(0, Math.min(pos, totalChars - 1)),
        startTime: now,
        id: Math.random(),
      });

      if (!stateRef.current.isAnim) start();
    };

    const handleEnter = (e: MouseEvent) => {
      stateRef.current.isHover = true;
      updateCursorPos(e);
      startWave();
    };

    const handleMove = (e: MouseEvent) => {
      if (!stateRef.current.isHover) return;
      const old = stateRef.current.cursorPos;
      updateCursorPos(e);
      if (stateRef.current.cursorPos !== old) startWave();
    };

    const handleLeave = () => {
      stateRef.current.isHover = false;
    };

    el.addEventListener("mouseenter", handleEnter);
    el.addEventListener("mousemove", handleMove);
    el.addEventListener("mouseleave", handleLeave);

    return () => {
      window.removeEventListener("resize", onResize);
      el.removeEventListener("mouseenter", handleEnter);
      el.removeEventListener("mousemove", handleMove);
      el.removeEventListener("mouseleave", handleLeave);
      if (stateRef.current.animId) {
        cancelAnimationFrame(stateRef.current.animId);
      }
    };
  }, [children]);

  return (
    <Component
      ref={elRef}
      className={cn(
        "cursor-pointer relative inline-block transition-colors duration-200",
        className
      )}
      {...props}
    />
  );
}

export default AsciiGlitchRipple;
