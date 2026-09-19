#!/usr/bin/env python3
"""
ContextGC - Editable PowerPoint Generator
Generates a 100% native, fully editable PPTX presentation for Canva and PowerPoint.
Every shape, card, text box, table, and metric is an editable PowerPoint element.
"""

from pptx import Presentation
from pptx.util import Inches, Pt
from pptx.enum.text import PP_ALIGN, MSO_ANCHOR
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE

# Design Tokens (Dark Tech Aesthetic)
COLOR_BG = RGBColor(11, 15, 25)           # #0B0F19 Deep Space Slate
COLOR_CARD = RGBColor(19, 27, 46)         # #131B2E Card Slate
COLOR_CARD_INNER = RGBColor(15, 23, 42)   # #0F172A Code/Inner Card
COLOR_BORDER = RGBColor(30, 41, 59)       # #1E293B Subtle Border

COLOR_BLUE = RGBColor(56, 189, 248)       # #38BDF8 Cyan/Sky Blue
COLOR_BLUE_LINE = RGBColor(59, 130, 246)  # #3B82F6 Blue Line
COLOR_INDIGO = RGBColor(99, 102, 241)     # #6366F1 Indigo
COLOR_EMERALD = RGBColor(52, 211, 153)    # #34D399 Emerald Green
COLOR_ROSE = RGBColor(244, 63, 94)        # #F43F5E Rose Red
COLOR_AMBER = RGBColor(251, 191, 36)      # #FBBF24 Amber Yellow
COLOR_PURPLE = RGBColor(167, 139, 250)    # #A78BFA Purple

COLOR_TEXT_WHITE = RGBColor(255, 255, 255)
COLOR_TEXT_LIGHT = RGBColor(241, 245, 249)
COLOR_TEXT_SLATE = RGBColor(148, 163, 184)
COLOR_TEXT_MUTED = RGBColor(100, 116, 139)

FONT_HEADING = "Arial"
FONT_BODY = "Arial"
FONT_MONO = "Consolas"

def create_presentation():
    prs = Presentation()
    prs.slide_width = Inches(13.333)
    prs.slide_height = Inches(7.5)
    blank_layout = prs.slide_layouts[6]

    def set_slide_bg(slide):
        bg = slide.background
        fill = bg.fill
        fill.solid()
        fill.fore_color.rgb = COLOR_BG

    def add_header(slide, title_text, subtitle_text):
        header_box = slide.shapes.add_textbox(Inches(0.8), Inches(0.4), Inches(11.733), Inches(0.9))
        tf = header_box.text_frame
        tf.word_wrap = True
        tf.margin_left = tf.margin_top = tf.margin_right = tf.margin_bottom = 0

        p1 = tf.paragraphs[0]
        p1.text = title_text
        p1.font.name = FONT_HEADING
        p1.font.size = Pt(22)
        p1.font.bold = True
        p1.font.color.rgb = COLOR_TEXT_WHITE

        p2 = tf.add_paragraph()
        p2.text = subtitle_text
        p2.font.name = FONT_BODY
        p2.font.size = Pt(11.5)
        p2.font.color.rgb = COLOR_TEXT_SLATE
        p2.space_before = Pt(4)

    # =========================================================================
    # SLIDE 1: Title Slide (Hero)
    # =========================================================================
    slide1 = prs.slides.add_slide(blank_layout)
    set_slide_bg(slide1)

    # Hackathon badge
    badge = slide1.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, Inches(0.8), Inches(0.8), Inches(5.0), Inches(0.4))
    badge.fill.solid()
    badge.fill.fore_color.rgb = RGBColor(30, 41, 59)
    badge.line.color.rgb = COLOR_BLUE_LINE
    badge.line.width = Pt(1)
    tf_b = badge.text_frame
    tf_b.margin_left = tf_b.margin_right = tf_b.margin_top = tf_b.margin_bottom = 0
    p_b = tf_b.paragraphs[0]
    p_b.text = "🏆 HACK DEVENGERS 2.0 · OPEN INNOVATION TRACK"
    p_b.font.name = FONT_MONO
    p_b.font.size = Pt(10)
    p_b.font.bold = True
    p_b.font.color.rgb = COLOR_BLUE
    p_b.alignment = PP_ALIGN.CENTER

    # Main Title
    tbox = slide1.shapes.add_textbox(Inches(0.8), Inches(1.35), Inches(11.733), Inches(1.8))
    tf1 = tbox.text_frame
    tf1.word_wrap = True
    tf1.margin_left = tf1.margin_right = tf1.margin_top = tf1.margin_bottom = 0

    p_title = tf1.paragraphs[0]
    p_title.text = "⚡ ContextGC"
    p_title.font.name = FONT_HEADING
    p_title.font.size = Pt(44)
    p_title.font.bold = True
    p_title.font.color.rgb = COLOR_TEXT_WHITE

    p_sub = tf1.add_paragraph()
    p_sub.text = "Autonomous Semantic Context Defragmenter for AI Agents"
    p_sub.font.name = FONT_HEADING
    p_sub.font.size = Pt(20)
    p_sub.font.bold = True
    p_sub.font.color.rgb = COLOR_BLUE
    p_sub.space_before = Pt(6)

    p_desc = tf1.add_paragraph()
    p_desc.text = "Eliminating Context Rot, Policy Drift, and 70% of Redundant Tokens with Deterministic Causal Garbage Collection"
    p_desc.font.name = FONT_BODY
    p_desc.font.size = Pt(13)
    p_desc.font.color.rgb = COLOR_TEXT_SLATE
    p_desc.space_before = Pt(8)

    # 4 Metric Highlight Cards (Horizontal Row)
    metrics_data = [
        ("70.1%", "Token Reduction", "Prunes superseded branches & dead context", COLOR_EMERALD),
        ("0%", "Policy Drift", "Pins hard security & financial invariants", COLOR_EMERALD),
        ("< 15ms", "In-Memory Overhead", "Pure Python, zero network roundtrip GC", COLOR_BLUE),
        ("100%", "KV-Cache Friendly", "Preserves exact prefix for Radix tree hits", COLOR_AMBER),
    ]

    card_w = Inches(2.72)
    card_h = Inches(1.6)
    card_gap = Inches(0.28)
    start_x = Inches(0.8)
    card_y = Inches(3.6)

    for i, (m_val, m_title, m_desc, m_color) in enumerate(metrics_data):
        cx = start_x + i * (card_w + card_gap)
        c_shape = slide1.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, cx, card_y, card_w, card_h)
        c_shape.fill.solid()
        c_shape.fill.fore_color.rgb = COLOR_CARD
        c_shape.line.color.rgb = m_color
        c_shape.line.width = Pt(1.5)

        ctf = c_shape.text_frame
        ctf.word_wrap = True
        ctf.margin_left = ctf.margin_right = Inches(0.18)
        ctf.margin_top = Inches(0.16)

        cp1 = ctf.paragraphs[0]
        cp1.text = m_val
        cp1.font.name = FONT_MONO
        cp1.font.size = Pt(26)
        cp1.font.bold = True
        cp1.font.color.rgb = m_color

        cp2 = ctf.add_paragraph()
        cp2.text = m_title
        cp2.font.name = FONT_HEADING
        cp2.font.size = Pt(12)
        cp2.font.bold = True
        cp2.font.color.rgb = COLOR_TEXT_WHITE
        cp2.space_before = Pt(3)

        cp3 = ctf.add_paragraph()
        cp3.text = m_desc
        cp3.font.name = FONT_BODY
        cp3.font.size = Pt(9.5)
        cp3.font.color.rgb = COLOR_TEXT_SLATE
        cp3.space_before = Pt(4)

    # Footer
    fbox = slide1.shapes.add_textbox(Inches(0.8), Inches(6.0), Inches(11.733), Inches(0.8))
    ftf = fbox.text_frame
    ftf.word_wrap = True
    ftf.margin_left = ftf.margin_right = ftf.margin_top = ftf.margin_bottom = 0
    fp1 = ftf.paragraphs[0]
    fp1.text = "Architect: Jay Gopal Tripathy (@j4yop)   ·   GitHub: github.com/j4yop/context-hackdevengers   ·   Live on Vercel Edge"
    fp1.font.name = FONT_MONO
    fp1.font.size = Pt(11)
    fp1.font.color.rgb = COLOR_TEXT_MUTED

    # =========================================================================
    # SLIDE 2: The Problem: Context Rot in AI Agents
    # =========================================================================
    slide2 = prs.slides.add_slide(blank_layout)
    set_slide_bg(slide2)
    add_header(slide2, "🛑 The Problem: \"Context Rot\" in AI Agents",
               "1M+ token windows solve raw capacity, NOT attention quality. Multi-turn operational sludge quietly degrades agent intelligence.")

    p_cards = [
        ("💸 1. Economic & Latency Tax", "74%", "DEAD TOKENS", COLOR_ROSE, [
            "Over 70% of prompt tokens in long sessions are dead weight: superseded instructions, 500-line JSON dumps, and resolved stack traces.",
            "Paid for repeatedly on every single turn, creating a linear cost explosion as agent conversations progress.",
            "Balloons Time-To-First-Token (TTFT) by hundreds of milliseconds, degrading interactive responsiveness."
        ]),
        ("🌪️ 2. \"Lost in the Middle\" Drift", "> 80%", "ATTENTION DEGRADE", COLOR_AMBER, [
            "Transformer attention mechanisms collapse over noisy middle turns (Lost-in-the-Middle phenomenon).",
            "When users update goals mid-session (e.g. changing delivery address 3 times), agents suffer recency collisions.",
            "Agents hallucinate and act on obsolete variables: delivering to old gates or calling deprecated database ports."
        ]),
        ("🚨 3. Policy Invariant Erosion", "0% Safe", "COMPLIANCE BREAK", COLOR_PURPLE, [
            "Critical system rules (financial caps, privacy boundaries, safety guardrails) fade under massive token context.",
            "Agents quietly violate hard constraints: issuing unauthorized ₹800 refunds or dumping raw API keys to debug.",
            "Multi-turn conversational sludge completely erodes developer-defined safety guarantees."
        ])
    ]

    col_w = Inches(3.72)
    col_gap = Inches(0.28)
    for i, (p_title, p_stat, p_stat_label, p_color, p_bullets) in enumerate(p_cards):
        cx = Inches(0.8) + i * (col_w + col_gap)
        c_shape = slide2.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, cx, Inches(1.5), col_w, Inches(4.35))
        c_shape.fill.solid()
        c_shape.fill.fore_color.rgb = COLOR_CARD
        c_shape.line.color.rgb = p_color
        c_shape.line.width = Pt(1.5)

        ctf = c_shape.text_frame
        ctf.word_wrap = True
        ctf.margin_left = ctf.margin_right = Inches(0.22)
        ctf.margin_top = Inches(0.22)

        p1 = ctf.paragraphs[0]
        p1.text = p_title
        p1.font.name = FONT_HEADING
        p1.font.size = Pt(13)
        p1.font.bold = True
        p1.font.color.rgb = p_color

        p2 = ctf.add_paragraph()
        p2.text = p_stat
        p2.font.name = FONT_MONO
        p2.font.size = Pt(32)
        p2.font.bold = True
        p2.font.color.rgb = COLOR_TEXT_WHITE
        p2.space_before = Pt(6)

        p2_lbl = ctf.add_paragraph()
        p2_lbl.text = p_stat_label
        p2_lbl.font.name = FONT_MONO
        p2_lbl.font.size = Pt(9.5)
        p2_lbl.font.bold = True
        p2_lbl.font.color.rgb = p_color
        p2_lbl.space_before = Pt(1)

        for bullet in p_bullets:
            pb = ctf.add_paragraph()
            pb.text = "• " + bullet
            pb.font.name = FONT_BODY
            pb.font.size = Pt(10)
            pb.font.color.rgb = COLOR_TEXT_LIGHT
            pb.space_before = Pt(8)

    # Bottom Callout Box
    insight_box = slide2.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, Inches(0.8), Inches(6.05), Inches(11.733), Inches(0.75))
    insight_box.fill.solid()
    insight_box.fill.fore_color.rgb = RGBColor(15, 23, 42)
    insight_box.line.color.rgb = COLOR_BLUE_LINE
    insight_box.line.width = Pt(1)
    itf = insight_box.text_frame
    itf.word_wrap = True
    itf.margin_left = itf.margin_right = Inches(0.2)
    itf.margin_top = Inches(0.12)
    ip = itf.paragraphs[0]
    ip.text = "💡 Key Architectural Takeaway: 1M token windows solve capacity, NOT attention quality. AI agents don't need infinite memory; they need systems-level context garbage collection."
    ip.font.name = FONT_BODY
    ip.font.size = Pt(11)
    ip.font.bold = True
    ip.font.color.rgb = COLOR_BLUE
    ip.alignment = PP_ALIGN.CENTER

    # =========================================================================
    # SLIDE 3: Visual Structure & System Architecture (THE FIXED SLIDE!)
    # =========================================================================
    slide3 = prs.slides.add_slide(blank_layout)
    set_slide_bg(slide3)
    add_header(slide3, "🏗️ Visual Structure & System Architecture",
               "ContextGC operates as an inline, deterministic semantic garbage collector between agent frameworks and LLM runtimes.")

    # 3 Pipeline Pillars
    # Pillar 1: Ingestion Tier
    p1_shape = slide3.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, Inches(0.8), Inches(1.5), Inches(3.3), Inches(3.2))
    p1_shape.fill.solid()
    p1_shape.fill.fore_color.rgb = COLOR_CARD
    p1_shape.line.color.rgb = COLOR_BLUE_LINE
    p1_shape.line.width = Pt(1.5)
    p1_tf = p1_shape.text_frame
    p1_tf.word_wrap = True
    p1_tf.margin_left = p1_tf.margin_right = Inches(0.18)
    p1_tf.margin_top = Inches(0.16)

    p1_head = p1_tf.paragraphs[0]
    p1_head.text = "📥 1. INGESTION TIER"
    p1_head.font.name = FONT_HEADING
    p1_head.font.size = Pt(12)
    p1_head.font.bold = True
    p1_head.font.color.rgb = COLOR_BLUE

    items_p1 = [
        ("User Prompts", "Multi-turn goals, constraints & updates"),
        ("Tool Logs & Dumps", "JSON payloads, API responses & stack traces"),
        ("System Invariants", "Hard financial, security & policy rules")
    ]
    for title, desc in items_p1:
        pt = p1_tf.add_paragraph()
        pt.text = "▸ " + title
        pt.font.name = FONT_HEADING
        pt.font.size = Pt(11)
        pt.font.bold = True
        pt.font.color.rgb = COLOR_TEXT_WHITE
        pt.space_before = Pt(8)

        pd = p1_tf.add_paragraph()
        pd.text = desc
        pd.font.name = FONT_BODY
        pd.font.size = Pt(9.5)
        pd.font.color.rgb = COLOR_TEXT_SLATE
        pd.space_before = Pt(1)

    # Arrow 1
    arrow1 = slide3.shapes.add_textbox(Inches(4.15), Inches(2.7), Inches(0.5), Inches(0.6))
    atf1 = arrow1.text_frame
    ap1 = atf1.paragraphs[0]
    ap1.text = "➔"
    ap1.font.name = FONT_HEADING
    ap1.font.size = Pt(24)
    ap1.font.bold = True
    ap1.font.color.rgb = COLOR_BLUE
    ap1.alignment = PP_ALIGN.CENTER

    # Pillar 2: Core Engine
    p2_shape = slide3.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, Inches(4.7), Inches(1.5), Inches(4.0), Inches(3.2))
    p2_shape.fill.solid()
    p2_shape.fill.fore_color.rgb = COLOR_CARD
    p2_shape.line.color.rgb = COLOR_INDIGO
    p2_shape.line.width = Pt(2)
    p2_tf = p2_shape.text_frame
    p2_tf.word_wrap = True
    p2_tf.margin_left = p2_tf.margin_right = Inches(0.18)
    p2_tf.margin_top = Inches(0.16)

    p2_head = p2_tf.paragraphs[0]
    p2_head.text = "⚡ 2. CONTEXTGC ENGINE  (< 15ms)"
    p2_head.font.name = FONT_HEADING
    p2_head.font.size = Pt(12)
    p2_head.font.bold = True
    p2_head.font.color.rgb = COLOR_INDIGO

    engine_items = [
        ("1. State DAG:", "Causal fact invalidation & branch pruning"),
        ("2. Tool Sanitizer:", "Protocol-safe schema tombstones (-95%)"),
        ("3. Policy Anchors:", "Recency attention boundary re-injection"),
        ("4. Episodic Vector:", "Cold turn storage & BM25/Cosine recall"),
        ("5. Dual Compactor:", "Token minimization vs KV-cache hits")
    ]
    for title, desc in engine_items:
        pt = p2_tf.add_paragraph()
        pt.text = title + " " + desc
        pt.font.name = FONT_BODY
        pt.font.size = Pt(9.5)
        pt.font.color.rgb = COLOR_TEXT_LIGHT
        pt.space_before = Pt(5)

    # Arrow 2
    arrow2 = slide3.shapes.add_textbox(Inches(8.75), Inches(2.7), Inches(0.5), Inches(0.6))
    atf2 = arrow2.text_frame
    ap2 = atf2.paragraphs[0]
    ap2.text = "➔"
    ap2.font.name = FONT_HEADING
    ap2.font.size = Pt(24)
    ap2.font.bold = True
    ap2.font.color.rgb = COLOR_EMERALD
    ap2.alignment = PP_ALIGN.CENTER

    # Pillar 3: Delivery & Runtime
    p3_shape = slide3.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, Inches(9.3), Inches(1.5), Inches(3.233), Inches(3.2))
    p3_shape.fill.solid()
    p3_shape.fill.fore_color.rgb = COLOR_CARD
    p3_shape.line.color.rgb = COLOR_EMERALD
    p3_shape.line.width = Pt(1.5)
    p3_tf = p3_shape.text_frame
    p3_tf.word_wrap = True
    p3_tf.margin_left = p3_tf.margin_right = Inches(0.18)
    p3_tf.margin_top = Inches(0.16)

    p3_head = p3_tf.paragraphs[0]
    p3_head.text = "🚀 3. DELIVERY & LLM"
    p3_head.font.name = FONT_HEADING
    p3_head.font.size = Pt(12)
    p3_head.font.bold = True
    p3_head.font.color.rgb = COLOR_EMERALD

    items_p3 = [
        ("SSE Streaming Proxy", "/v1/chat/completions drop-in endpoint"),
        ("1-Line Python SDK", "patch_openai(mode='compact')"),
        ("Downstream LLMs", "GPT-4o, Claude 3.7, DeepSeek V3, vLLM")
    ]
    for title, desc in items_p3:
        pt = p3_tf.add_paragraph()
        pt.text = "▸ " + title
        pt.font.name = FONT_HEADING
        pt.font.size = Pt(11)
        pt.font.bold = True
        pt.font.color.rgb = COLOR_TEXT_WHITE
        pt.space_before = Pt(8)

        pd = p3_tf.add_paragraph()
        pd.text = desc
        pd.font.name = FONT_BODY
        pd.font.size = Pt(9.5)
        pd.font.color.rgb = COLOR_TEXT_SLATE
        pd.space_before = Pt(1)

    # Bottom 4 Feature Cards (Clean, unclipped, aesthetic)
    sub_cards = [
        ("State DAG", "Prunes superseded branches in causal order (Tower B → Clubhouse → Gate 2).", COLOR_BLUE),
        ("Tool Sanitizer", "Replaces resolved errors with tombstones while preserving tool_call_id.", COLOR_EMERALD),
        ("Policy Anchors", "Pins non-negotiable financial & security rules at recency attention boundary.", COLOR_AMBER),
        ("Episodic Vector", "Archives cold history into 768-dim table for sub-ms JIT semantic recall.", COLOR_PURPLE),
    ]

    sc_w = Inches(2.72)
    sc_h = Inches(1.75)
    sc_gap = Inches(0.28)
    sc_y = Inches(4.9)

    for i, (s_title, s_desc, s_color) in enumerate(sub_cards):
        sx = Inches(0.8) + i * (sc_w + sc_gap)
        s_shape = slide3.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, sx, sc_y, sc_w, sc_h)
        s_shape.fill.solid()
        s_shape.fill.fore_color.rgb = COLOR_CARD_INNER
        s_shape.line.color.rgb = s_color
        s_shape.line.width = Pt(1)

        stf = s_shape.text_frame
        stf.word_wrap = True
        stf.margin_left = stf.margin_right = Inches(0.16)
        stf.margin_top = Inches(0.14)

        sp1 = stf.paragraphs[0]
        sp1.text = f"{i+1}. {s_title}"
        sp1.font.name = FONT_HEADING
        sp1.font.size = Pt(11.5)
        sp1.font.bold = True
        sp1.font.color.rgb = s_color

        sp2 = stf.add_paragraph()
        sp2.text = s_desc
        sp2.font.name = FONT_BODY
        sp2.font.size = Pt(9.5)
        sp2.font.color.rgb = COLOR_TEXT_LIGHT
        sp2.space_before = Pt(4)

    # =========================================================================
    # SLIDE 4: Engine 1: Neuro-Symbolic State DAG
    # =========================================================================
    slide4 = prs.slides.add_slide(blank_layout)
    set_slide_bg(slide4)
    add_header(slide4, "🧠 Engine 1: Neuro-Symbolic State DAG",
               "Why naive RAG and summarizers fail: They understand similarity, not causality.")

    # Left Column: Mechanics
    s4_left = slide4.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, Inches(0.8), Inches(1.5), Inches(5.6), Inches(5.3))
    s4_left.fill.solid()
    s4_left.fill.fore_color.rgb = COLOR_CARD
    s4_left.line.color.rgb = COLOR_BLUE_LINE
    s4_left.line.width = Pt(1.5)
    s4l_tf = s4_left.text_frame
    s4l_tf.word_wrap = True
    s4l_tf.margin_left = s4l_tf.margin_right = Inches(0.24)
    s4l_tf.margin_top = Inches(0.2)

    p = s4l_tf.paragraphs[0]
    p.text = "Causal Branch Resolution Mechanics"
    p.font.name = FONT_HEADING
    p.font.size = Pt(14)
    p.font.bold = True
    p.font.color.rgb = COLOR_BLUE

    bullets_s4 = [
        ("Entity Mutation Graph", "Scans user and agent turns for slot updates (addresses, ports, keys) with preceding 50-character negation windows."),
        ("Immutable Guardrails", "Critical user constraints (e.g. 'NO PEANUTS', spending caps) are permanently anchored against overrides."),
        ("Dead-Branch Eviction", "Once Turn 9 confirms Gate 2, Turn 1 (Tower B) and Turn 5 (Clubhouse) are recognized as dead branches and pruned from active tokens."),
        ("Transactional Rollback", "Supports dag.rollback_to(turn_id) to instantly restore prior states on tool failure without confusing the model."),
        ("Zero DAG Pollution", "Heuristic filtering prevents transient tool inventory dumps from polluting the state graph.")
    ]
    for b_title, b_text in bullets_s4:
        p_t = s4l_tf.add_paragraph()
        p_t.text = "• " + b_title + ":"
        p_t.font.name = FONT_HEADING
        p_t.font.size = Pt(11)
        p_t.font.bold = True
        p_t.font.color.rgb = COLOR_TEXT_WHITE
        p_t.space_before = Pt(8)

        p_d = s4l_tf.add_paragraph()
        p_d.text = b_text
        p_d.font.name = FONT_BODY
        p_d.font.size = Pt(10)
        p_d.font.color.rgb = COLOR_TEXT_LIGHT
        p_d.space_before = Pt(1)

    # Right Column: Live State Snapshot
    s4_right = slide4.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, Inches(6.7), Inches(1.5), Inches(5.833), Inches(5.3))
    s4_right.fill.solid()
    s4_right.fill.fore_color.rgb = COLOR_CARD_INNER
    s4_right.line.color.rgb = COLOR_BORDER
    s4_right.line.width = Pt(1)
    s4r_tf = s4_right.text_frame
    s4r_tf.word_wrap = True
    s4r_tf.margin_left = s4r_tf.margin_right = Inches(0.24)
    s4r_tf.margin_top = Inches(0.2)

    p = s4r_tf.paragraphs[0]
    p.text = "// Active DAG State Snapshot (Live In-Memory State)"
    p.font.name = FONT_MONO
    p.font.size = Pt(11)
    p.font.bold = True
    p.font.color.rgb = COLOR_TEXT_MUTED

    dag_lines = [
        ("✓ destination_address: \"Gate 2 Security Entrance\"", "[Settled Turn 9]", COLOR_EMERALD),
        ("✓ gate_code: \"4921\"", "[Settled Turn 9]", COLOR_EMERALD),
        ("✓ dietary_allergy: \"NO PEANUTS\"", "[IMMUTABLE GUARD]", COLOR_BLUE),
        ("✓ substitute_choice: \"Organic A2 Milk\"", "[Settled Turn 3]", COLOR_EMERALD),
        ("✓ refund_cap_enforced: \"₹1,500 Max\"", "[Policy Invariant]", COLOR_AMBER),
        ("----------------------------------------------------------------", "", COLOR_BORDER),
        ("✗ Pruned: Tower B Flat 402", "[Superseded at Turn 5]", COLOR_ROSE),
        ("✗ Pruned: Clubhouse Reception Gate", "[Superseded at Turn 9]", COLOR_ROSE),
        ("✗ Pruned: Regular Cow Milk (A1)", "[Superseded at Turn 3]", COLOR_ROSE),
    ]

    for item, tag, color in dag_lines:
        p = s4r_tf.add_paragraph()
        p.text = f"{item}  {tag}"
        p.font.name = FONT_MONO
        p.font.size = Pt(10.5)
        p.font.color.rgb = color
        p.space_before = Pt(8)

    p_bot = s4r_tf.add_paragraph()
    p_bot.text = "Result: Downstream LLM receives ONLY active ground truth. Zero hallucination of superseded instructions."
    p_bot.font.name = FONT_BODY
    p_bot.font.size = Pt(10)
    p_bot.font.bold = True
    p_bot.font.color.rgb = COLOR_BLUE
    p_bot.space_before = Pt(18)

    # =========================================================================
    # SLIDE 5: Engine 2: Tool Sanitizer & Protocol Safety
    # =========================================================================
    slide5 = prs.slides.add_slide(blank_layout)
    set_slide_bg(slide5)
    add_header(slide5, "🛡️ Engine 2: Tool Sanitizer & Protocol Safety",
               "Blind context truncation breaks autonomous agents. ContextGC guarantees 100% protocol compliance.")

    # Left Container Card
    s5_left_card = slide5.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, Inches(0.8), Inches(1.5), Inches(5.6), Inches(5.3))
    s5_left_card.fill.solid()
    s5_left_card.fill.fore_color.rgb = COLOR_CARD
    s5_left_card.line.color.rgb = COLOR_ROSE
    s5_left_card.line.width = Pt(1.5)

    # Left Text Box (Header & Intro)
    s5_l_box1 = slide5.shapes.add_textbox(Inches(1.05), Inches(1.7), Inches(5.1), Inches(1.1))
    s5_l_tf1 = s5_l_box1.text_frame
    s5_l_tf1.word_wrap = True
    s5_l_tf1.margin_left = s5_l_tf1.margin_right = s5_l_tf1.margin_top = s5_l_tf1.margin_bottom = 0
    p = s5_l_tf1.paragraphs[0]
    p.text = "The OpenAI Protocol Trap"
    p.font.name = FONT_HEADING
    p.font.size = Pt(14)
    p.font.bold = True
    p.font.color.rgb = COLOR_ROSE

    p_trap = s5_l_tf1.add_paragraph()
    p_trap.text = "In modern agent loops, the assistant invokes tools via structured schemas. If an agent defragmenter blindly drops an intermediate tool message, the OpenAI/Anthropic API throws an immediate fatal error:"
    p_trap.font.name = FONT_BODY
    p_trap.font.size = Pt(10)
    p_trap.font.color.rgb = COLOR_TEXT_LIGHT
    p_trap.space_before = Pt(4)

    # Left Error Box
    err_box = slide5.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, Inches(1.05), Inches(2.95), Inches(5.1), Inches(1.4))
    err_box.fill.solid()
    err_box.fill.fore_color.rgb = RGBColor(35, 10, 15)
    err_box.line.color.rgb = COLOR_ROSE
    err_box.line.width = Pt(1)
    etf = err_box.text_frame
    etf.word_wrap = True
    etf.margin_left = etf.margin_right = Inches(0.16)
    etf.margin_top = Inches(0.12)
    ep = etf.paragraphs[0]
    ep.text = "HTTP 400 Bad Request:\nInvalid parameter: 'messages'. An assistant message with 'tool_calls' must be followed by tool messages responding to each tool_call_id."
    ep.font.name = FONT_MONO
    ep.font.size = Pt(9.5)
    ep.font.color.rgb = COLOR_ROSE

    # Left Bottom Text Box
    s5_l_box2 = slide5.shapes.add_textbox(Inches(1.05), Inches(4.55), Inches(5.1), Inches(2.0))
    s5_l_tf2 = s5_l_box2.text_frame
    s5_l_tf2.word_wrap = True
    s5_l_tf2.margin_left = s5_l_tf2.margin_right = s5_l_tf2.margin_top = s5_l_tf2.margin_bottom = 0
    p_fail1 = s5_l_tf2.paragraphs[0]
    p_fail1.text = "• Why Summarizers Fail:"
    p_fail1.font.name = FONT_HEADING
    p_fail1.font.size = Pt(11)
    p_fail1.font.bold = True
    p_fail1.font.color.rgb = COLOR_TEXT_WHITE

    p_fail2 = s5_l_tf2.add_paragraph()
    p_fail2.text = "Generic LLM summarizers compress messages into flat prose, stripping out tool_call_id linkage and immediately breaking agent tool-call execution loops."
    p_fail2.font.name = FONT_BODY
    p_fail2.font.size = Pt(9.5)
    p_fail2.font.color.rgb = COLOR_TEXT_LIGHT
    p_fail2.space_before = Pt(2)

    p_fail3 = s5_l_tf2.add_paragraph()
    p_fail3.text = "• Positional Degradation:"
    p_fail3.font.name = FONT_HEADING
    p_fail3.font.size = Pt(11)
    p_fail3.font.bold = True
    p_fail3.font.color.rgb = COLOR_TEXT_WHITE
    p_fail3.space_before = Pt(8)

    p_fail4 = s5_l_tf2.add_paragraph()
    p_fail4.text = "500-line tool outputs push earlier instructions out of transformer attention span, triggering catastrophic policy amnesia."
    p_fail4.font.name = FONT_BODY
    p_fail4.font.size = Pt(9.5)
    p_fail4.font.color.rgb = COLOR_TEXT_LIGHT
    p_fail4.space_before = Pt(2)

    # Right Container Card
    s5_right_card = slide5.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, Inches(6.7), Inches(1.5), Inches(5.833), Inches(5.3))
    s5_right_card.fill.solid()
    s5_right_card.fill.fore_color.rgb = COLOR_CARD
    s5_right_card.line.color.rgb = COLOR_EMERALD
    s5_right_card.line.width = Pt(1.5)

    # Right Text Box (Header & Intro)
    s5_r_box1 = slide5.shapes.add_textbox(Inches(6.95), Inches(1.7), Inches(5.333), Inches(1.1))
    s5_r_tf1 = s5_r_box1.text_frame
    s5_r_tf1.word_wrap = True
    s5_r_tf1.margin_left = s5_r_tf1.margin_right = s5_r_tf1.margin_top = s5_r_tf1.margin_bottom = 0
    p = s5_r_tf1.paragraphs[0]
    p.text = "ContextGC Semantic Tombstoning"
    p.font.name = FONT_HEADING
    p.font.size = Pt(14)
    p.font.bold = True
    p.font.color.rgb = COLOR_EMERALD

    p_sol = s5_r_tf1.add_paragraph()
    p_sol.text = "ContextGC replaces superseded tool dumps with minimal 1-line tombstones while strictly preserving tool_call_id and tool name parameters:"
    p_sol.font.name = FONT_BODY
    p_sol.font.size = Pt(10)
    p_sol.font.color.rgb = COLOR_TEXT_LIGHT
    p_sol.space_before = Pt(4)

    # Right Tombstone Box
    tomb_box = slide5.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, Inches(6.95), Inches(2.95), Inches(5.333), Inches(1.4))
    tomb_box.fill.solid()
    tomb_box.fill.fore_color.rgb = RGBColor(10, 30, 20)
    tomb_box.line.color.rgb = COLOR_EMERALD
    tomb_box.line.width = Pt(1)
    ttf = tomb_box.text_frame
    ttf.word_wrap = True
    ttf.margin_left = ttf.margin_right = Inches(0.16)
    ttf.margin_top = Inches(0.12)
    tp = ttf.paragraphs[0]
    tp.text = "{\n  \"role\": \"tool\",\n  \"tool_call_id\": \"call_9f2a\",\n  \"content\": \"[TOMBSTONE: Superseded catalog output. Resolved at Turn 7.]\"\n}"
    tp.font.name = FONT_MONO
    tp.font.size = Pt(9.5)
    tp.font.color.rgb = COLOR_EMERALD

    # Right Bottom Text Box
    s5_r_box2 = slide5.shapes.add_textbox(Inches(6.95), Inches(4.55), Inches(5.333), Inches(2.0))
    s5_r_tf2 = s5_r_box2.text_frame
    s5_r_tf2.word_wrap = True
    s5_r_tf2.margin_left = s5_r_tf2.margin_right = s5_r_tf2.margin_top = s5_r_tf2.margin_bottom = 0

    sol_bullets = [
        ("95.1% Compression", "25-item supermarket catalog dump distilled from 450 tokens → 22 tokens with zero schema violations."),
        ("Resolved Error Pruning", "Detects when a 504 gateway timeout in turn N is resolved by retry in turn N+1, collapsing the error trace safely."),
        ("100% Framework Compatible", "Fully compliant with OpenAI, Anthropic, LangChain, AutoGen, and CrewAI schema requirements.")
    ]
    for b_title, b_desc in sol_bullets:
        pt = s5_r_tf2.add_paragraph() if s5_r_tf2.paragraphs[0].text else s5_r_tf2.paragraphs[0]
        pt.text = "• " + b_title + ":"
        pt.font.name = FONT_HEADING
        pt.font.size = Pt(11)
        pt.font.bold = True
        pt.font.color.rgb = COLOR_TEXT_WHITE
        pt.space_before = Pt(6) if pt != s5_r_tf2.paragraphs[0] else 0

        pd = s5_r_tf2.add_paragraph()
        pd.text = b_desc
        pd.font.name = FONT_BODY
        pd.font.size = Pt(9.5)
        pd.font.color.rgb = COLOR_TEXT_LIGHT
        pd.space_before = Pt(1)

    # =========================================================================
    # SLIDE 6: Engine 3: Radix KV-Cache Friendly Compaction
    # =========================================================================
    slide6 = prs.slides.add_slide(blank_layout)
    set_slide_bg(slide6)
    add_header(slide6, "⚡ Engine 3: Radix KV-Cache Friendly Compaction",
               "The Prompt Caching Paradox: Why cutting tokens can sometimes cost you money.")

    # Left: The Paradox
    s6_left = slide6.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, Inches(0.8), Inches(1.5), Inches(5.6), Inches(5.3))
    s6_left.fill.solid()
    s6_left.fill.fore_color.rgb = COLOR_CARD
    s6_left.line.color.rgb = COLOR_AMBER
    s6_left.line.width = Pt(1.5)
    s6l_tf = s6_left.text_frame
    s6l_tf.word_wrap = True
    s6l_tf.margin_left = s6l_tf.margin_right = Inches(0.24)
    s6l_tf.margin_top = Inches(0.2)

    p = s6l_tf.paragraphs[0]
    p.text = "The Prompt Caching Dilemma"
    p.font.name = FONT_HEADING
    p.font.size = Pt(14)
    p.font.bold = True
    p.font.color.rgb = COLOR_AMBER

    p_dilemma = [
        ("Radix Tree Prefix Reuse", "Modern inference engines (vLLM, DeepSeek, Anthropic, OpenAI) offer 50% to 90% cost discounts for identical prompt prefixes via Radix tree KV-cache reuse."),
        ("The Invalidation Trap", "If a context defragmenter mutates early or middle turns, it invalidates the byte-exact prefix—destroying the cache hit rate and increasing inference latency!"),
        ("The Cost Surprise", "You save 40% on tokens, but pay 5x more because you lost the 90% cache discount!")
    ]
    for b_title, b_desc in p_dilemma:
        p_t = s6l_tf.add_paragraph()
        p_t.text = "• " + b_title + ":"
        p_t.font.name = FONT_HEADING
        p_t.font.size = Pt(11)
        p_t.font.bold = True
        p_t.font.color.rgb = COLOR_TEXT_WHITE
        p_t.space_before = Pt(10)

        p_d = s6l_tf.add_paragraph()
        p_d.text = b_desc
        p_d.font.name = FONT_BODY
        p_d.font.size = Pt(10)
        p_d.font.color.rgb = COLOR_TEXT_LIGHT
        p_d.space_before = Pt(2)

    # Right: The Dual Mode Solution
    s6_right = slide6.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, Inches(6.7), Inches(1.5), Inches(5.833), Inches(5.3))
    s6_right.fill.solid()
    s6_right.fill.fore_color.rgb = COLOR_CARD
    s6_right.line.color.rgb = COLOR_BLUE_LINE
    s6_right.line.width = Pt(1.5)
    s6r_tf = s6_right.text_frame
    s6r_tf.word_wrap = True
    s6r_tf.margin_left = s6r_tf.margin_right = Inches(0.24)
    s6r_tf.margin_top = Inches(0.2)

    p = s6r_tf.paragraphs[0]
    p.text = "ContextGC Dual-Mode Solution"
    p.font.name = FONT_HEADING
    p.font.size = Pt(14)
    p.font.bold = True
    p.font.color.rgb = COLOR_BLUE

    modes = [
        ("mode=\"compact\" (Maximum Token Savings)", COLOR_EMERALD, [
            "Aggressively prunes all historical dead weight.",
            "Reclaims up to 70.1% of active prompt tokens.",
            "Ideal for models without prefix caching or when sessions approach hard context limits."
        ]),
        ("mode=\"cache_friendly\" (Maximum Cache Hits)", COLOR_BLUE, [
            "Leaves earlier prompt bytes 100% untouched to preserve Radix tree prefix caches.",
            "Maintains 100% KV-cache hit rates on DeepSeek, vLLM, and Anthropic.",
            "Injects active settled DAG state at the conversation tail."
        ])
    ]

    for m_title, m_color, m_bullets in modes:
        p_m = s6r_tf.add_paragraph()
        p_m.text = m_title
        p_m.font.name = FONT_MONO
        p_m.font.size = Pt(11)
        p_m.font.bold = True
        p_m.font.color.rgb = m_color
        p_m.space_before = Pt(12)

        for b in m_bullets:
            pb = s6r_tf.add_paragraph()
            pb.text = "▸ " + b
            pb.font.name = FONT_BODY
            pb.font.size = Pt(9.5)
            pb.font.color.rgb = COLOR_TEXT_LIGHT
            pb.space_before = Pt(3)

    p_note = s6r_tf.add_paragraph()
    p_note.text = "Developers switch optimization targets with a single configuration flag: patch_openai(mode='cache_friendly')"
    p_note.font.name = FONT_MONO
    p_note.font.size = Pt(9.5)
    p_note.font.bold = True
    p_note.font.color.rgb = COLOR_AMBER
    p_note.space_before = Pt(14)

    # =========================================================================
    # SLIDE 7: Empirical Benchmarks: Side-by-Side Showdown
    # =========================================================================
    slide7 = prs.slides.add_slide(blank_layout)
    set_slide_bg(slide7)
    add_header(slide7, "📊 Empirical Benchmarks: Side-by-Side Showdown",
               "Deterministic evaluation verified across industrial multi-turn agent execution runs.")

    # Native PPTX Table
    table_shape = slide7.shapes.add_table(8, 4, Inches(0.8), Inches(1.5), Inches(11.733), Inches(3.6))
    table = table_shape.table

    table.columns[0].width = Inches(3.4)
    table.columns[1].width = Inches(2.7)
    table.columns[2].width = Inches(2.7)
    table.columns[3].width = Inches(2.933)

    table_data = [
        ("Benchmark Metric", "Vanilla Agent (Rotted Context)", "ContextGC Agent (Defragmented)", "Measured Advantage"),
        ("Scenario 1: Operations Crisis", "1,592 tokens", "476 tokens", "-70.1% Tokens Saved"),
        ("Scenario 2: Coding Refactor", "1,000 tokens", "311 tokens", "-68.9% Tokens Saved"),
        ("Turn Inference Latency (TTFT)", "750 – 898 ms", "454 – 487 ms", "+39.8% to +46.8% Faster"),
        ("GC Interception Latency", "0 ms", "8.2 – 16.1 ms", "Deterministic In-Memory"),
        ("Policy Invariant Violations", "100% Failure Rate", "0% Violations", "100% Bounded Compliance"),
        ("State Resolution Accuracy", "0% (Obsolete Hallucinations)", "100% (Settled DAG State)", "Zero Hallucination"),
        ("KV-Cache Hit Compatibility", "Broken on mutation", "100% Supported", "Dual-Mode Compactor"),
    ]

    for row_idx, row in enumerate(table_data):
        for col_idx, text in enumerate(row):
            cell = table.cell(row_idx, col_idx)
            cell.text = text
            cell.fill.solid()
            if row_idx == 0:
                cell.fill.fore_color.rgb = RGBColor(30, 41, 59)
            elif row_idx % 2 == 1:
                cell.fill.fore_color.rgb = RGBColor(19, 27, 46)
            else:
                cell.fill.fore_color.rgb = RGBColor(15, 23, 42)

            for p in cell.text_frame.paragraphs:
                p.font.name = FONT_BODY
                p.font.size = Pt(9.5)
                if row_idx == 0:
                    p.font.bold = True
                    p.font.color.rgb = COLOR_BLUE
                elif col_idx == 3:
                    p.font.bold = True
                    p.font.color.rgb = COLOR_EMERALD
                elif col_idx == 2:
                    p.font.bold = True
                    p.font.color.rgb = COLOR_TEXT_WHITE
                else:
                    p.font.color.rgb = COLOR_TEXT_LIGHT

    # 4 Bottom Metric Badges
    bottom_badges = [
        ("70.1%", "Token Reduction", COLOR_EMERALD),
        ("< 15ms", "In-Memory GC Latency", COLOR_INDIGO),
        ("0%", "Policy Drift Rate", COLOR_BLUE),
        ("27 / 27", "Passing Pytests", COLOR_PURPLE),
    ]

    b_w = Inches(2.72)
    b_h = Inches(1.3)
    b_gap = Inches(0.28)
    b_y = Inches(5.45)

    for i, (b_val, b_lbl, b_col) in enumerate(bottom_badges):
        bx = Inches(0.8) + i * (b_w + b_gap)
        b_shape = slide7.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, bx, b_y, b_w, b_h)
        b_shape.fill.solid()
        b_shape.fill.fore_color.rgb = COLOR_CARD
        b_shape.line.color.rgb = b_col
        b_shape.line.width = Pt(1.5)

        btf = b_shape.text_frame
        btf.word_wrap = True
        btf.margin_top = Inches(0.16)
        bp1 = btf.paragraphs[0]
        bp1.text = b_val
        bp1.font.name = FONT_MONO
        bp1.font.size = Pt(22)
        bp1.font.bold = True
        bp1.font.color.rgb = b_col
        bp1.alignment = PP_ALIGN.CENTER

        bp2 = btf.add_paragraph()
        bp2.text = b_lbl
        bp2.font.name = FONT_HEADING
        bp2.font.size = Pt(11)
        bp2.font.bold = True
        bp2.font.color.rgb = COLOR_TEXT_WHITE
        bp2.space_before = Pt(3)
        bp2.alignment = PP_ALIGN.CENTER

    # =========================================================================
    # SLIDE 8: Developer Ergonomics: Integration in 60 Seconds
    # =========================================================================
    slide8 = prs.slides.add_slide(blank_layout)
    set_slide_bg(slide8)
    add_header(slide8, "🔌 Developer Ergonomics: Integration in 60 Seconds",
               "Deploy ContextGC with zero friction via two turnkey integration patterns.")

    # Left Container Card
    s8_left_card = slide8.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, Inches(0.8), Inches(1.5), Inches(5.6), Inches(5.3))
    s8_left_card.fill.solid()
    s8_left_card.fill.fore_color.rgb = COLOR_CARD
    s8_left_card.line.color.rgb = COLOR_BLUE_LINE
    s8_left_card.line.width = Pt(1.5)

    # Left Header Box
    s8_l_head = slide8.shapes.add_textbox(Inches(1.05), Inches(1.7), Inches(5.1), Inches(0.8))
    s8_l_htf = s8_l_head.text_frame
    s8_l_htf.word_wrap = True
    s8_l_htf.margin_left = s8_l_htf.margin_right = s8_l_htf.margin_top = s8_l_htf.margin_bottom = 0
    p = s8_l_htf.paragraphs[0]
    p.text = "Option A: 1-Line Python Client SDK"
    p.font.name = FONT_HEADING
    p.font.size = Pt(14)
    p.font.bold = True
    p.font.color.rgb = COLOR_BLUE

    p_a_desc = s8_l_htf.add_paragraph()
    p_a_desc.text = "Monkey-patch the official OpenAI client for zero-proxy, zero-network overhead:"
    p_a_desc.font.name = FONT_BODY
    p_a_desc.font.size = Pt(10)
    p_a_desc.font.color.rgb = COLOR_TEXT_SLATE
    p_a_desc.space_before = Pt(3)

    # Left Code Box
    cbox_l = slide8.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, Inches(1.05), Inches(2.6), Inches(5.1), Inches(2.3))
    cbox_l.fill.solid()
    cbox_l.fill.fore_color.rgb = COLOR_CARD_INNER
    cbox_l.line.color.rgb = COLOR_BORDER
    cbox_l.line.width = Pt(1)
    cl_tf = cbox_l.text_frame
    cl_tf.word_wrap = True
    cl_tf.margin_left = cl_tf.margin_right = Inches(0.15)
    cl_tf.margin_top = Inches(0.12)
    cl_p = cl_tf.paragraphs[0]
    cl_p.text = "from core.client import patch_openai\nfrom openai import OpenAI\n\n# Intercepts all chat.completions calls\npatch_openai(mode=\"compact\")\n\nclient = OpenAI()\nresponse = client.chat.completions.create(\n    model=\"gpt-4o\",\n    messages=session_history\n)"
    cl_p.font.name = FONT_MONO
    cl_p.font.size = Pt(9.5)
    cl_p.font.color.rgb = COLOR_BLUE

    # Left Checklist Box
    s8_l_feats = slide8.shapes.add_textbox(Inches(1.05), Inches(5.1), Inches(5.1), Inches(1.5))
    s8_l_ftf = s8_l_feats.text_frame
    s8_l_ftf.word_wrap = True
    s8_l_ftf.margin_left = s8_l_ftf.margin_right = s8_l_ftf.margin_top = s8_l_ftf.margin_bottom = 0

    feats_a = [
        "Zero extra infrastructure or proxy server required",
        "Transparently preserves return types and streaming",
        "Deterministic sub-15ms local GC execution"
    ]
    for i, feat in enumerate(feats_a):
        pf = s8_l_ftf.add_paragraph() if i > 0 else s8_l_ftf.paragraphs[0]
        pf.text = "✓ " + feat
        pf.font.name = FONT_BODY
        pf.font.size = Pt(10)
        pf.font.color.rgb = COLOR_TEXT_LIGHT
        pf.space_before = Pt(6) if i > 0 else 0

    # Right Container Card
    s8_right_card = slide8.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, Inches(6.7), Inches(1.5), Inches(5.833), Inches(5.3))
    s8_right_card.fill.solid()
    s8_right_card.fill.fore_color.rgb = COLOR_CARD
    s8_right_card.line.color.rgb = COLOR_EMERALD
    s8_right_card.line.width = Pt(1.5)

    # Right Header Box
    s8_r_head = slide8.shapes.add_textbox(Inches(6.95), Inches(1.7), Inches(5.333), Inches(0.8))
    s8_r_htf = s8_r_head.text_frame
    s8_r_htf.word_wrap = True
    s8_r_htf.margin_left = s8_r_htf.margin_right = s8_r_htf.margin_top = s8_r_htf.margin_bottom = 0
    p = s8_r_htf.paragraphs[0]
    p.text = "Option B: Drop-in SSE Reverse Proxy"
    p.font.name = FONT_HEADING
    p.font.size = Pt(14)
    p.font.bold = True
    p.font.color.rgb = COLOR_EMERALD

    p_b_desc = s8_r_htf.add_paragraph()
    p_b_desc.text = "Point Cursor, LangChain, CrewAI, AutoGen, or Claude Code directly to ContextGC:"
    p_b_desc.font.name = FONT_BODY
    p_b_desc.font.size = Pt(10)
    p_b_desc.font.color.rgb = COLOR_TEXT_SLATE
    p_b_desc.space_before = Pt(3)

    # Right Code Box
    cbox_r = slide8.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, Inches(6.95), Inches(2.6), Inches(5.333), Inches(2.3))
    cbox_r.fill.solid()
    cbox_r.fill.fore_color.rgb = COLOR_CARD_INNER
    cbox_r.line.color.rgb = COLOR_BORDER
    cbox_r.line.width = Pt(1)
    cr_tf = cbox_r.text_frame
    cr_tf.word_wrap = True
    cr_tf.margin_left = cr_tf.margin_right = Inches(0.15)
    cr_tf.margin_top = Inches(0.12)
    cr_p = cr_tf.paragraphs[0]
    cr_p.text = "# Point any agent framework to the ContextGC proxy:\nexport OPENAI_BASE_URL=\"https://context-hackdevengers.vercel.app/v1\"\nexport OPENAI_API_KEY=\"sk-your-openai-key\"\n\n# Standard OpenAI SDK or curl works out-of-the-box\ncurl -X POST $OPENAI_BASE_URL/chat/completions \\\n  -H \"Authorization: Bearer $OPENAI_API_KEY\" \\\n  -d '{\"model\": \"gpt-4o\", \"messages\": [...]}'"
    cr_p.font.name = FONT_MONO
    cr_p.font.size = Pt(9)
    cr_p.font.color.rgb = COLOR_EMERALD

    # Right Checklist Box
    s8_r_feats = slide8.shapes.add_textbox(Inches(6.95), Inches(5.1), Inches(5.333), Inches(1.5))
    s8_r_ftf = s8_r_feats.text_frame
    s8_r_ftf.word_wrap = True
    s8_r_ftf.margin_left = s8_r_ftf.margin_right = s8_r_ftf.margin_top = s8_r_ftf.margin_bottom = 0

    feats_b = [
        "Real-time SSE streaming (stream: true) with chat.completion.chunk",
        "Trailing defrag telemetry headers: x-contextgc-saved-tokens",
        "Deployed serverless on Vercel Edge with zero cold start penalty"
    ]
    for i, feat in enumerate(feats_b):
        pf = s8_r_ftf.add_paragraph() if i > 0 else s8_r_ftf.paragraphs[0]
        pf.text = "✓ " + feat
        pf.font.name = FONT_BODY
        pf.font.size = Pt(10)
        pf.font.color.rgb = COLOR_TEXT_LIGHT
        pf.space_before = Pt(6) if i > 0 else 0

    # =========================================================================
    # SLIDE 9: Production Readiness & Hackathon Wrap-up
    # =========================================================================
    slide9 = prs.slides.add_slide(blank_layout)
    set_slide_bg(slide9)
    add_header(slide9, "🚀 Built for Production · Ready for Hack Devengers 2.0",
               "ContextGC transforms long-horizon AI agents from brittle prototypes into reliable, cost-efficient enterprise infrastructure.")

    action_cards = [
        ("🌐 Live Web Dashboard", "https://context-hackdevengers.vercel.app", COLOR_BLUE, [
            "Interactive split-screen showdown.",
            "Visual token flamegraph & savings metrics.",
            "Real-time State DAG inspector & rollbacks.",
            "1-click live execution against GPT-4o."
        ]),
        ("📊 Pitch Deck & Benchmarks", "https://context-hackdevengers.vercel.app/presentation", COLOR_INDIGO, [
            "Comprehensive architectural slide deck.",
            "Full empirical benchmark comparison sheets.",
            "Detailed failure mode analysis & solutions.",
            "100% editable PPTX & Canva presentations."
        ]),
        ("🐙 Open-Source Repository", "https://github.com/j4yop/context-hackdevengers", COLOR_EMERALD, [
            "27 automated pytests passing.",
            "Drop-in FastAPI proxy & Python SDK.",
            "Clean architecture, fully typed & documented.",
            "Ready for immediate production deployment."
        ])
    ]

    for i, (ac_title, ac_url, ac_col, ac_bullets) in enumerate(action_cards):
        cx = Inches(0.8) + i * (col_w + col_gap)
        c_shape = slide9.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, cx, Inches(1.5), col_w, Inches(4.35))
        c_shape.fill.solid()
        c_shape.fill.fore_color.rgb = COLOR_CARD
        c_shape.line.color.rgb = ac_col
        c_shape.line.width = Pt(1.5)

        ctf = c_shape.text_frame
        ctf.word_wrap = True
        ctf.margin_left = ctf.margin_right = Inches(0.22)
        ctf.margin_top = Inches(0.22)

        p1 = ctf.paragraphs[0]
        p1.text = ac_title
        p1.font.name = FONT_HEADING
        p1.font.size = Pt(14)
        p1.font.bold = True
        p1.font.color.rgb = ac_col

        p_url = ctf.add_paragraph()
        p_url.text = ac_url
        p_url.font.name = FONT_MONO
        p_url.font.size = Pt(9.5)
        p_url.font.bold = True
        p_url.font.color.rgb = COLOR_TEXT_WHITE
        p_url.space_before = Pt(4)

        for bullet in ac_bullets:
            pb = ctf.add_paragraph()
            pb.text = "• " + bullet
            pb.font.name = FONT_BODY
            pb.font.size = Pt(10)
            pb.font.color.rgb = COLOR_TEXT_LIGHT
            pb.space_before = Pt(8)

    # Bottom Terminal Runner Box
    runner_box = slide9.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, Inches(0.8), Inches(6.05), Inches(11.733), Inches(0.75))
    runner_box.fill.solid()
    runner_box.fill.fore_color.rgb = COLOR_CARD_INNER
    runner_box.line.color.rgb = COLOR_BLUE_LINE
    runner_box.line.width = Pt(1)
    rtf = runner_box.text_frame
    rtf.word_wrap = True
    rtf.margin_left = rtf.margin_right = Inches(0.2)
    rtf.margin_top = Inches(0.12)
    rp = rtf.paragraphs[0]
    rp.text = "⚡ Run Local Showdown in 5 Seconds: python3 demo/interactive_demo.py  (Deterministic sub-15ms terminal showdown)"
    rp.font.name = FONT_MONO
    rp.font.size = Pt(11)
    rp.font.bold = True
    rp.font.color.rgb = COLOR_EMERALD
    rp.alignment = PP_ALIGN.CENTER

    return prs

if __name__ == "__main__":
    prs = create_presentation()
    out_path = "/Users/jaygopal/Desktop/contextGCC.pptx"
    prs.save(out_path)
    # Also save backup with ContextGC_Presentation.pptx
    prs.save("/Users/jaygopal/Desktop/ContextGC_Presentation.pptx")
    print(f"Successfully generated native editable presentation at: {out_path}")
