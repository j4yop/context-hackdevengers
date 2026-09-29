"use client";

import React from "react";
import DisplayCards from "@/components/ui/display-cards";
import { Sparkles, AlertTriangle, Database, Clock } from "lucide-react";

export const failureModeCards = [
  {
    icon: <AlertTriangle className="size-4 text-amber-400" />,
    title: "1. Contradiction & Ghost State",
    description: "A user changes delivery address or flight date 15 turns in. The model sees conflicting values and hallucinates a blend.",
    date: "High Severity",
    iconClassName: "bg-amber-950 text-amber-400",
    titleClassName: "text-amber-400 font-bold",
    className:
      "[grid-area:stack] hover:-translate-y-10 before:absolute before:w-[100%] before:outline-1 before:rounded-xl before:outline-border before:h-[100%] before:content-[''] before:bg-blend-overlay before:bg-background/50 grayscale-[100%] hover:before:opacity-0 before:transition-opacity before:duration-700 hover:grayscale-0 before:left-0 before:top-0",
  },
  {
    icon: <Database className="size-4 text-blue-400" />,
    title: "2. Irrelevance & Token Bleed",
    description: "Bash tool runs and SQL lookups dump hundreds of lines of raw tabular data that no turn will ever read again.",
    date: "Token Inflation",
    iconClassName: "bg-blue-950 text-blue-400",
    titleClassName: "text-blue-400 font-bold",
    className:
      "[grid-area:stack] translate-x-12 translate-y-10 hover:-translate-y-1 before:absolute before:w-[100%] before:outline-1 before:rounded-xl before:outline-border before:h-[100%] before:content-[''] before:bg-blend-overlay before:bg-background/50 grayscale-[100%] hover:before:opacity-0 before:transition-opacity before:duration-700 hover:grayscale-0 before:left-0 before:top-0",
  },
  {
    icon: <Clock className="size-4 text-rose-400" />,
    title: "3. Attention Position Decay",
    description: "Important constraints placed in the middle of a 50-turn dialogue suffer from lost-in-the-middle decay.",
    date: "Attention Loss",
    iconClassName: "bg-rose-950 text-rose-400",
    titleClassName: "text-rose-400 font-bold",
    className:
      "[grid-area:stack] translate-x-24 translate-y-20 hover:translate-y-10",
  },
];

export default function DisplayCardsDemo() {
  return (
    <div className="flex min-h-[400px] w-full items-center justify-center py-16">
      <div className="w-full max-w-2xl">
        <DisplayCards cards={failureModeCards} />
      </div>
    </div>
  );
}
