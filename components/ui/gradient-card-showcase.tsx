import React from 'react';

interface CardItem {
  title: string;
  desc: string;
  gradientFrom: string;
  gradientTo: string;
  tag?: string;
  num?: string;
}

const defaultCards: CardItem[] = [
  {
    title: 'Deterministic State DAG',
    desc: 'Mathematical tracking of entity lifecycles. When a key is re-asserted, the prior turn is retired; when a key is voided, it is cleanly struck from active state.',
    gradientFrom: '#ffbc00',
    gradientTo: '#ff0058',
    tag: 'DAG Engine',
    num: '01',
  },
  {
    title: 'Safety-First Compactor',
    desc: 'Compresses multi-row tool payloads by up to 80% while guaranteeing that any row carrying allergen, PII, security, or expiry signals is strictly preserved.',
    gradientFrom: '#03a9f4',
    gradientTo: '#ff0058',
    tag: 'Safety Gate',
    num: '02',
  },
  {
    title: 'KV-Cache Prefix Preserver',
    desc: 'In cache_friendly mode, unchanged prefix messages are emitted byte-identical, retaining provider KV cache hits across model generations.',
    gradientFrom: '#4dff03',
    gradientTo: '#00d0ff',
    tag: 'Cache Align',
    num: '03',
  },
  {
    title: 'Dual Read & Write Path',
    desc: 'Extracts implicit facts using measured regex schemas on the read path, or receives direct declarations from the agent via <contextgc-state> blocks.',
    gradientFrom: '#7928ca',
    gradientTo: '#ff0080',
    tag: 'Dual Path I/O',
    num: '04',
  },
  {
    title: 'Lexical Evidence Gate',
    desc: 'A turn is never retired if it remains the sole supporting evidence for an active fact. Orphaned assertions are mathematically prevented.',
    gradientFrom: '#0070f3',
    gradientTo: '#00dfd8',
    tag: 'Evidence Gate',
    num: '05',
  },
  {
    title: 'Zero-Dependency Core',
    desc: 'Written in 100% pure standard-library Python (3.9–3.13). Installs instantly, needs no PyTorch or heavy NLP dependencies, and compiles in <3ms.',
    gradientFrom: '#ff4b1f',
    gradientTo: '#ff9068',
    tag: 'Pure Python',
    num: '06',
  },
];

interface SkewCardsProps {
  cards?: CardItem[];
  className?: string;
}

export default function SkewCards({ cards = defaultCards, className = '' }: SkewCardsProps) {
  return (
    <>
      <div className={`flex justify-center items-center flex-wrap py-10 min-h-screen ${className}`}>
        {cards.map(({ title, desc, gradientFrom, gradientTo, tag, num }, idx) => (
          <div
            key={idx}
            className="group relative w-[320px] min-h-[300px] m-[30px_20px] transition-all duration-500"
          >
            {/* Skewed gradient panels */}
            <span
              className="absolute top-0 left-[40px] w-1/2 h-full rounded-2xl transform skew-x-[12deg] transition-all duration-500 group-hover:skew-x-0 group-hover:left-[16px] group-hover:w-[calc(100%-32px)]"
              style={{
                background: `linear-gradient(315deg, ${gradientFrom}, ${gradientTo})`,
              }}
            />
            <span
              className="absolute top-0 left-[40px] w-1/2 h-full rounded-2xl transform skew-x-[12deg] blur-[28px] opacity-60 transition-all duration-500 group-hover:skew-x-0 group-hover:left-[16px] group-hover:w-[calc(100%-32px)] group-hover:opacity-90"
              style={{
                background: `linear-gradient(315deg, ${gradientFrom}, ${gradientTo})`,
              }}
            />

            {/* Animated blurs */}
            <span className="pointer-events-none absolute inset-0 z-10">
              <span className="absolute top-0 left-0 w-0 h-0 rounded-xl opacity-0 bg-[rgba(255,255,255,0.12)] backdrop-blur-[10px] shadow-[0_5px_15px_rgba(0,0,0,0.08)] transition-all duration-100 animate-blob group-hover:top-[-30px] group-hover:left-[30px] group-hover:w-[80px] group-hover:h-[80px] group-hover:opacity-100" />
              <span className="absolute bottom-0 right-0 w-0 h-0 rounded-xl opacity-0 bg-[rgba(255,255,255,0.12)] backdrop-blur-[10px] shadow-[0_5px_15px_rgba(0,0,0,0.08)] transition-all duration-500 animate-blob animation-delay-1000 group-hover:bottom-[-30px] group-hover:right-[30px] group-hover:w-[80px] group-hover:h-[80px] group-hover:opacity-100" />
            </span>

            {/* Content */}
            <div className="relative z-20 left-0 p-[28px_24px] bg-[rgba(255,255,255,0.05)] backdrop-blur-[14px] shadow-lg rounded-2xl text-white transition-all duration-500 group-hover:translate-x-[-8px] group-hover:translate-y-[-4px]">
              <div className="flex items-center justify-between mb-4">
                {tag && (
                  <span className="inline-block text-[10px] uppercase tracking-widest font-mono px-2.5 py-1 rounded-md bg-white/10 border border-white/15 text-white/80">
                    {tag}
                  </span>
                )}
                {num && (
                  <span className="font-mono text-xs font-bold text-white/40 tracking-wider">
                    {num}
                  </span>
                )}
              </div>
              <h2 className="text-xl font-bold mb-3 tracking-tight">{title}</h2>
              <p className="text-sm leading-relaxed text-white/80">{desc}</p>
            </div>
          </div>
        ))}
      </div>

      {/* Tailwind custom utilities for animation and shadows */}
      <style>{`
        @keyframes blob {
          0%, 100% { transform: translateY(8px); }
          50% { transform: translateY(-8px); }
        }
        .animate-blob { animation: blob 2s ease-in-out infinite; }
        .animation-delay-1000 { animation-delay: -1s; }
        .shadow-\[0_5px_15px_rgba\(0,0,0,0.08\) { box-shadow: 0 5px 15px rgba(0,0,0,0.08); }
      `}</style>
    </>
  );
}
