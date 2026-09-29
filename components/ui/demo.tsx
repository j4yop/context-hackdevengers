"use client";

import { Terminal } from "@/components/ui/terminal";

export default function TerminalDemo() {
  return (
    <div className="flex w-full min-h-[400px] items-center justify-center bg-background p-10">
      <Terminal
        className="w-full max-w-md"
        lines={[
          { type: "system", text: "SYSTEM BOOT SEQUENCE INITIATED" },
          { type: "input", text: "connect --grid=encom" },
          { type: "output", text: "Connection established. Welcome, User." },
          { type: "error", text: "Access to Sector 7 denied." },
        ]}
      />
    </div>
  );
}
