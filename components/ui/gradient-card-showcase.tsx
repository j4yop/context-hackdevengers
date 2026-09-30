import React from 'react';

interface CardItem {
  title: string;
  desc: string;
  gradientFrom: string;
  gradientTo: string;
  linkText?: string;
  linkHref?: string;
  tag?: string;
}

const defaultCards: CardItem[] = [
  {
    title: 'Deterministic State DAG',
    desc: 'Mathematical tracking of entity lifecycles. When a key is re-asserted, the prior turn is retired; when a key is voided, it is cleanly struck from active state.',
    gradientFrom: '#00f2fe',
    gradientTo: '#4facfe',
    tag: 'DAG Engine',
  },
  {
    title: 'Safety-First Compactor',
    desc: 'Compresses multi-row tool payloads by up to 80% while guaranteeing that any row carrying allergen, PII, security, or expiry signals is strictly preserved.',
    gradientFrom: '#ff9a9e',
    gradientTo: '#fecfef',
    tag: 'Safety Gate',
  },
  {
    title: 'KV-Cache Prefix Preserver',
    desc: 'In cache_friendly mode, unchanged prefix messages are emitted byte-identical, retaining provider KV cache hits across model generations.',
    gradientFrom: '#a18cd1',
    gradientTo: '#fbc2eb',
    tag: 'Cache Hit Align',
  },
  {
    title: 'Dual Read & Write Path',
    desc: 'Extracts implicit facts using measured regex schemas on the read path, or receives direct declarations from the agent via <contextgc-state> blocks.',
    gradientFrom: '#03a9f4',
    gradientTo: '#ff0058',
    tag: 'Dual Path I/O',
  },
  {
    title: 'Lexical Evidence Gate',
    desc: 'A turn is never retired if it remains the sole supporting evidence for an active fact. Orphaned assertions are mathematically prevented.',
    gradientFrom: '#4dff03',
    gradientTo: '#00d0ff',
    tag: 'Evidence Anchor',
  },
  {
    title: 'Zero-Dependency Core',
    desc: 'Written in 100% pure standard-library Python (3.9–3.13). Installs instantly, needs no PyTorch or heavy NLP dependencies, and compiles in <3ms.',
    gradientFrom: '#ffbc00',
    gradientTo: '#ff0058',
    tag: 'Pure Python',
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
        {cards.map(({ title, desc, gradientFrom, gradientTo, linkText = 'Read More', linkHref = '#', tag }, idx) => (
          <div
            key={idx}
            className="group relative w-[320px] h-[400px] m-[40px_30px] transition-all duration-500"
          >
            {/* Skewed gradient panels */}
            <span
              className="absolute top-0 left-[50px] w-1/2 h-full rounded-lg transform skew-x-[15deg] transition-all duration-500 group-hover:skew-x-0 group-hover:left-[20px] group-hover:w-[calc(100%-90px)]"
              style={{
                background: `linear-gradient(315deg, ${gradientFrom}, ${gradientTo})`,
              }}
            />
            <span
              className="absolute top-0 left-[50px] w-1/2 h-full rounded-lg transform skew-x-[15deg] blur-[30px] transition-all duration-500 group-hover:skew-x-0 group-hover:left-[20px] group-hover:w-[calc(100%-90px)]"
              style={{
                background: `linear-gradient(315deg, ${gradientFrom}, ${gradientTo})`,
              }}
            />

            {/* Animated blurs */}
            <span className="pointer-events-none absolute inset-0 z-10">
              <span className="absolute top-0 left-0 w-0 h-0 rounded-lg opacity-0 bg-[rgba(255,255,255,0.1)] backdrop-blur-[10px] shadow-[0_5px_15px_rgba(0,0,0,0.08)] transition-all duration-100 animate-blob group-hover:top-[-50px] group-hover:left-[50px] group-hover:w-[100px] group-hover:h-[100px] group-hover:opacity-100" />
              <span className="absolute bottom-0 right-0 w-0 h-0 rounded-lg opacity-0 bg-[rgba(255,255,255,0.1)] backdrop-blur-[10px] shadow-[0_5px_15px_rgba(0,0,0,0.08)] transition-all duration-500 animate-blob animation-delay-1000 group-hover:bottom-[-50px] group-hover:right-[50px] group-hover:w-[100px] group-hover:h-[100px] group-hover:opacity-100" />
            </span>

            {/* Content */}
            <div className="relative z-20 left-0 p-[20px_40px] bg-[rgba(255,255,255,0.05)] backdrop-blur-[10px] shadow-lg rounded-lg text-white transition-all duration-500 group-hover:left-[-25px] group-hover:p-[60px_40px]">
              {tag && (
                <span className="inline-block text-xs uppercase tracking-wider font-mono opacity-80 mb-2">
                  {tag}
                </span>
              )}
              <h2 className="text-2xl mb-2">{title}</h2>
              <p className="text-lg leading-relaxed mb-2">{desc}</p>
              <a
                href={linkHref}
                className="inline-block text-lg font-bold text-black bg-white px-3 py-2 rounded hover:bg-[#ffcf4d] hover:border hover:border-[rgba(255,0,88,0.4)] hover:shadow-md"
              >
                {linkText}
              </a>
            </div>
          </div>
        ))}
      </div>

      {/* Tailwind custom utilities for animation and shadows */}
      <style>{`
        @keyframes blob {
          0%, 100% { transform: translateY(10px); }
          50% { transform: translate(-10px); }
        }
        .animate-blob { animation: blob 2s ease-in-out infinite; }
        .animation-delay-1000 { animation-delay: -1s; }
        .shadow-\[0_5px_15px_rgba\(0,0,0,0.08\) { box-shadow: 0 5px 15px rgba(0,0,0,0.08); }
      `}</style>
    </>
  );
}
