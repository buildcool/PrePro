// The logo of each AI service you can connect, so you can tell them apart at a glance (see assets/brands/NOTICE.md:
// LobeHub lobe-icons, MIT; the marks are their owners' trademarks, shown only to identify the service). The SVGs are
// static files checked into the repo — plain paths and gradients, no scripts — so they're inlined: one-colour marks
// then follow the theme (black in light, white in dark) while Claude and Gemini keep their own colours.
import { useId } from "react";
import anthropic from "../assets/brands/anthropic.svg?raw";
import claude from "../assets/brands/claude-color.svg?raw";
import gemini from "../assets/brands/gemini-color.svg?raw";
import ollama from "../assets/brands/ollama.svg?raw";
import openai from "../assets/brands/openai.svg?raw";
import openrouter from "../assets/brands/openrouter.svg?raw";
import xai from "../assets/brands/xai.svg?raw";
import Icon from "./Icon";

const LOGOS: Record<string, string> = {
  "claude-plan": claude,
  "chatgpt-plan": openai,
  "gemini-plan": gemini,
  "claude-api": anthropic,
  "openai-api": openai,
  gemini: gemini,
  "xai-api": xai,
  openrouter: openrouter,
  ollama: ollama,
};

export const hasLogo = (id: string) => id in LOGOS;

/** Just the mark. It fills its box: give it a size, or let the tile around it size it. */
export default function BrandLogo({ id, size }: { id: string; size?: number }) {
  // Gemini's gradients are found by id, and the same logo can be on screen several times (card, picker, sidebar):
  // give every copy its own ids so one hidden copy can never take the colours of the others with it.
  const uid = useId().replace(/[^\w-]/g, "");
  const svg = LOGOS[id];
  if (!svg) return null;
  const html = svg.replace(/_R_0_/g, `_${uid}_`).replace(/<title>[^<]*<\/title>/, ""); // the card already names it
  return <span className="brand-logo" style={size ? { width: size, height: size } : undefined} aria-hidden="true" dangerouslySetInnerHTML={{ __html: html }} />;
}

/** The logo on a neutral tile, sized by CSS (.amark); the rules engine gets the wand. */
export function LogoTile({ id }: { id: string }) {
  return (
    <span className="amark" aria-hidden="true">
      {hasLogo(id) ? <BrandLogo id={id} /> : <Icon name={id === "basic" ? "wand" : "sparkles"} />}
    </span>
  );
}
