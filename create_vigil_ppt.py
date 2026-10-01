from pathlib import Path
from pptx import Presentation
from pptx.util import Inches, Pt
from pptx.dml.color import RGBColor
from pptx.enum.text import PP_ALIGN, MSO_ANCHOR
from pptx.enum.shapes import MSO_SHAPE, MSO_CONNECTOR
from pptx.enum.dml import MSO_THEME_COLOR
from pptx.enum.text import MSO_AUTO_SIZE

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "VIGIL_Project_Overview_10_Slides.pptx"
SCREEN = ROOT / "ppt_assets" / "login.png"

prs = Presentation()
prs.slide_width = Inches(13.333)
prs.slide_height = Inches(7.5)

BG = RGBColor(8, 13, 24)
PANEL = RGBColor(18, 27, 43)
PANEL2 = RGBColor(25, 37, 57)
WHITE = RGBColor(241, 245, 249)
MUTED = RGBColor(157, 172, 193)
CYAN = RGBColor(44, 213, 196)
BLUE = RGBColor(67, 139, 246)
AMBER = RGBColor(251, 184, 60)
RED = RGBColor(244, 84, 103)
GREEN = RGBColor(74, 222, 128)

def rect(slide, x, y, w, h, fill=PANEL, radius=True, line=None):
    s = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE if radius else MSO_SHAPE.RECTANGLE,
                               Inches(x), Inches(y), Inches(w), Inches(h))
    s.fill.solid(); s.fill.fore_color.rgb = fill
    s.line.color.rgb = line or fill
    return s

def textbox(slide, x, y, w, h, text, size=18, color=WHITE, bold=False,
            font="Aptos", align=PP_ALIGN.LEFT, valign=MSO_ANCHOR.TOP, margin=0.05):
    box = slide.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
    tf = box.text_frame; tf.clear(); tf.margin_left = tf.margin_right = Inches(margin)
    tf.margin_top = tf.margin_bottom = Inches(margin); tf.vertical_anchor = valign
    p = tf.paragraphs[0]; p.text = text; p.alignment = align
    p.font.name = font; p.font.size = Pt(size); p.font.bold = bold; p.font.color.rgb = color
    return box

def rich_text(slide, x, y, w, h, lines, size=15, color=MUTED, gap=5):
    box = slide.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
    tf = box.text_frame; tf.clear(); tf.word_wrap = True
    tf.margin_left = tf.margin_right = Inches(.08); tf.margin_top = Inches(.05)
    for i, item in enumerate(lines):
        if isinstance(item, tuple):
            head, body = item
        else: head, body = "", item
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        p.space_after = Pt(gap); p.font.name = "Aptos"; p.font.size = Pt(size); p.font.color.rgb = color
        if head:
            r = p.add_run(); r.text = head; r.font.bold = True; r.font.color.rgb = WHITE
            r = p.add_run(); r.text = body; r.font.color.rgb = color
        else: p.text = body
    return box

def title(slide, n, heading, sub=None):
    textbox(slide, .55, .28, .55, .38, f"{n:02}", 14, CYAN, True, align=PP_ALIGN.CENTER, valign=MSO_ANCHOR.MIDDLE)
    textbox(slide, 1.12, .22, 11.5, .55, heading, 28, WHITE, True)
    if sub: textbox(slide, 1.13, .75, 11.3, .33, sub, 11, MUTED)
    line = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(.55), Inches(1.13), Inches(12.22), Inches(.025))
    line.fill.solid(); line.fill.fore_color.rgb = PANEL2; line.line.fill.background()

def new_slide(n, heading, sub=None):
    s = prs.slides.add_slide(prs.slide_layouts[6]); s.background.fill.solid(); s.background.fill.fore_color.rgb = BG
    title(s, n, heading, sub); return s

def label(slide, x, y, w, text, color=CYAN):
    s=rect(slide,x,y,w,.34,fill=PANEL2)
    textbox(slide,x,y+.01,w,.28,text.upper(),10,color,True,align=PP_ALIGN.CENTER,valign=MSO_ANCHOR.MIDDLE)
    return s

def card(slide, x, y, w, h, heading, body, accent=CYAN):
    rect(slide,x,y,w,h)
    rect(slide,x,y,.055,h,accent,radius=False)
    textbox(slide,x+.22,y+.18,w-.38,.35,heading,17,WHITE,True)
    textbox(slide,x+.22,y+.65,w-.42,h-.8,body,12.5,MUTED)

def footer(slide, text="VIGIL · Agentic Video Analytics · Port 8090"):
    textbox(slide,.58,7.16,12.1,.18,text,8.5,RGBColor(90,107,130),align=PP_ALIGN.RIGHT)

# 1 — cover
s = prs.slides.add_slide(prs.slide_layouts[6]); s.background.fill.solid(); s.background.fill.fore_color.rgb = BG
rect(s,0,0,5.35,7.5,fill=RGBColor(10,18,31),radius=False)
label(s,.62,.63,2.1,"PROJECT OVERVIEW",CYAN)
textbox(s,.62,1.25,4.2,.7,"VIGIL",38,WHITE,True)
textbox(s,.62,1.96,4.2,.8,"Agentic Video\nAnalytics",29,CYAN,True)
textbox(s,.62,3.05,4.05,.9,"Real-time perception, persistent identity, explainable threat detection, and AI-assisted investigation.",16,MUTED)
for i,(k,v,c) in enumerate([("SERVICE","vigil.main",CYAN),("CONSOLE","HTTPS :8090",BLUE),("STATUS","LIVE",GREEN)]):
    x=.62+i*1.42; rect(s,x,4.42,1.25,.78,fill=PANEL2); textbox(s,x+.1,4.56,1.05,.18,k,8,MUTED,True); textbox(s,x+.1,4.84,1.05,.2,v,10,c,True)
textbox(s,.62,6.55,4.1,.35,"Technical overview · 10 slides",11,MUTED)
if SCREEN.exists():
    s.shapes.add_picture(str(SCREEN), Inches(5.35), Inches(0), width=Inches(7.98), height=Inches(5.0))
rect(s,5.35,5.0,7.98,2.5,fill=RGBColor(12,20,34),radius=False)
textbox(s,5.82,5.45,6.9,.38,"A private, on-premises command center",22,WHITE,True)
textbox(s,5.82,6.03,6.75,.62,"React console + FastAPI backend + GPU perception + local LLM/VLM. Data and inference remain on the host.",15,MUTED)

# 2
s=new_slide(2,"What VIGIL delivers","From camera pixels to reviewable, evidence-backed incidents")
cards=[("SEE","CCTV, RTSP, FRS relay, files, and browser webcam sources",BLUE),
       ("UNDERSTAND","People, pose, objects, faces, motion, zones, paths and behavior",CYAN),
       ("VERIFY","Multi-stage violence/threat checks with evidence frames and a vision model",AMBER),
       ("ACT","Correlated incidents, investigations, reports, notes and notifications",RED)]
for i,(h,b,c) in enumerate(cards): card(s,.65+i*3.1,1.48,2.75,2.05,h,b,c)
rect(s,.65,3.9,12.05,2.65,fill=PANEL)
textbox(s,.95,4.18,3.3,.38,"Operational outcomes",19,WHITE,True)
rich_text(s,.95,4.72,5.25,1.45,[
    ("Persistent IDs — ","recognize returning people across cameras and restarts."),
    ("Explainable alerts — ","retain measurements, thresholds and reasoning for audit."),
    ("Fast response — ","live WebSockets and evidence clips shorten review time.")],13.5)
rich_text(s,6.55,4.72,5.35,1.45,[
    ("Human control — ","watchlist matches remain candidates, not confirmed identities."),
    ("Local intelligence — ","Qwen text/vision models run through local Ollama."),
    ("Safe demos — ","synthetic data is labelled, isolated, and removable.")],13.5)
footer(s)

# 3 architecture
s=new_slide(3,"System architecture","One uvicorn process; camera and GPU work in owned threads; async I/O and persistence")
nodes=[(.55,1.65,2.0,1.05,"VIDEO SOURCES","FRS relay · RTSP\nfiles · webcam",BLUE),
       (3.0,1.65,2.25,1.05,"CAMERA WORKERS","motion gate · tracking\nidentity · rules",CYAN),
       (5.75,1.65,2.25,1.05,"GPU WORKERS","YOLO · SCRFD · AdaFace\nVideoMAE · CLIP",AMBER),
       (8.5,1.65,2.1,1.05,"ORCHESTRATOR","dedupe · verify\ncorrelate · escalate",RED),
       (11.0,1.65,1.75,1.05,"CONSOLE","REST · WSS\nReact UI",GREEN)]
for x,y,w,h,a,b,c in nodes:
    rect(s,x,y,w,h,fill=PANEL2,line=c); textbox(s,x+.12,y+.15,w-.24,.25,a,11,c,True,align=PP_ALIGN.CENTER); textbox(s,x+.12,y+.49,w-.24,.42,b,10.5,MUTED,align=PP_ALIGN.CENTER)
for i in range(len(nodes)-1):
    x1=nodes[i][0]+nodes[i][2]; x2=nodes[i+1][0]
    ln=s.shapes.add_connector(MSO_CONNECTOR.STRAIGHT, Inches(x1+.05), Inches(2.18), Inches(x2-.05), Inches(2.18)); ln.line.color.rgb=RGBColor(80,105,135); ln.line.width=Pt(2); ln.line.end_arrowhead=True
card(s,.75,3.42,3.65,2.52,"FRS backend · :8000","Read-only integration: camera MJPEG relay, watchlist search, records, detections and health. Camera credentials are redacted.",BLUE)
card(s,4.82,3.42,3.65,2.52,"VIGIL data layer","SQLite in WAL mode by default; PostgreSQL optional. Stores cameras, identities, tracks, events, incidents, audit and agent traces.",CYAN)
card(s,8.89,3.42,3.65,2.52,"Local AI · :11434","Ollama serves qwen3.8 for reasoning and qwen3-vl:8b for visual evidence verification. Nothing needs to leave the machine.",AMBER)
textbox(s,.77,6.32,11.8,.3,"Concurrency design: model groups own their CUDA/ONNX contexts; camera calls return Futures; bounded queues prevent slow clients from blocking perception.",11,MUTED,align=PP_ALIGN.CENTER)
footer(s)

# 4 pipeline
s=new_slide(4,"Real-time perception pipeline","Optimized for continuous multi-camera operation and explainable decisions")
steps=[("01","FRAME","Latest frame slot\n+ evidence ring"),("02","GATE","Motion-aware\n~1 fps when idle"),("03","DETECT","YOLO11 pose\n+ objects"),("04","TRACK","ByteTrack paths\nspeed + posture"),("05","IDENTIFY","SCRFD + AdaFace\npooled embeddings"),("06","REASON","Rules + VideoMAE\n+ agent verification")]
for i,(n,h,b) in enumerate(steps):
    x=.45+i*2.12; c=[BLUE,CYAN,CYAN,AMBER,AMBER,RED][i]
    rect(s,x,1.58,1.75,1.75,fill=PANEL2,line=c); textbox(s,x+.12,1.74,.42,.25,n,11,c,True); textbox(s,x+.12,2.12,1.5,.28,h,15,WHITE,True); textbox(s,x+.12,2.58,1.48,.52,b,10.5,MUTED)
    if i<5:
        ln=s.shapes.add_connector(MSO_CONNECTOR.STRAIGHT, Inches(x+1.76), Inches(2.45), Inches(x+2.05), Inches(2.45)); ln.line.color.rgb=RGBColor(89,109,137); ln.line.end_arrowhead=True
rect(s,.62,3.83,12.0,2.38,fill=PANEL)
textbox(s,.9,4.08,3.2,.3,"Identity confidence logic",17,WHITE,True)
rich_text(s,.9,4.53,5.45,1.35,[
    ("Observe — ","quality ≥ 0.35 and face ≥ 40 px; keep the best track views."),
    ("Match — ","pooled AdaFace similarity ≥ 0.40 with ≥ 0.06 runner-up margin."),
    ("Lock — ","two votes establish the identity; contradictory views can unlock it.")],12.5)
textbox(s,6.75,4.08,3.2,.3,"Evidence lifecycle",17,WHITE,True)
rich_text(s,6.75,4.53,5.2,1.35,[
    ("Capture — ","annotated keyframe immediately; 6 s pre-roll + 4 s post-roll."),
    ("Package — ","H.264 clip plus six frames for visual verification."),
    ("Preserve — ","rejected alerts are downgraded, not deleted, for auditability.")],12.5)
footer(s)

# 5 features
s=new_slide(5,"Analytics and detection capabilities","Deterministic perception first; AI reasoning only where it adds value")
features=[("IDENTITY","Persistent person IDs\nEnrollment without losing history\nFRS watchlist candidates",CYAN),
          ("BEHAVIOR","Loitering · running · falls\nrestricted zones · crowding\npacing · repeat visits",BLUE),
          ("VIOLENCE","Pose interaction → VideoMAE\nfusion → VLM verification\ncritical escalation",RED),
          ("SEARCH","Identity timelines\nco-occurrence and camera paths\nCLIP appearance search",AMBER),
          ("LIVE","Boxes · labels · trails\nskeletons · zones · objects\nbackpressured WebSockets",GREEN),
          ("EVIDENCE","Keyframes and clips\nverification frames\nincident-ready audit trail",RGBColor(180,120,255))]
for i,(h,b,c) in enumerate(features):
    row=i//3; col=i%3; card(s,.65+col*4.08,1.45+row*2.55,3.67,2.18,h,b,c)
textbox(s,.75,6.72,11.8,.24,"Deliberate safeguards: clothing never assigns identity · VideoMAE never alerts alone · watchlist hits require human verification.",11,MUTED,align=PP_ALIGN.CENTER)
footer(s)

# 6 agents
s=new_slide(6,"Agentic investigation layer","Agents enrich, verify and investigate signals while preserving every step")
agents=[("Threat Agent","Checks evidence frames; confirms, rejects or holds for review.",RED),
        ("Identity Agent","Adds FRS candidate context and live identity evidence.",CYAN),
        ("Behavior Agent","Finds repeat visits and correlated suspicious patterns.",BLUE),
        ("Investigation Agent","Runs a ReAct loop over ~20 read/action tools.",AMBER),
        ("Reporting Agent","Produces structured findings and incident reports.",GREEN),
        ("Analyst Agent","Read-only chat for people, cameras, events and incidents.",RGBColor(180,120,255))]
for i,(h,b,c) in enumerate(agents):
    y=1.42+i*.82; rect(s,.65,y,4.25,.65,fill=PANEL2,line=c); textbox(s,.85,y+.12,1.62,.25,h,12.5,c,True); textbox(s,2.5,y+.11,2.2,.38,b,10.2,MUTED)
rect(s,5.35,1.42,7.35,4.75,fill=PANEL)
textbox(s,5.7,1.75,6.65,.35,"Event → verified incident",18,WHITE,True)
flow=[("SIGNAL","rule/model output",BLUE),("EVIDENCE","clip + frames",CYAN),("VERIFY","Threat Agent + VLM",AMBER),("CORRELATE","person · camera · type",RED),("INVESTIGATE","LLM + tools",RGBColor(180,120,255)),("REPORT","assessment + actions",GREEN)]
for i,(h,b,c) in enumerate(flow):
    row=i//3; col=i%3; x=5.7+col*2.18; y=2.42+row*1.55
    rect(s,x,y,1.83,1.02,fill=PANEL2,line=c); textbox(s,x+.1,y+.16,1.63,.22,h,11,c,True,align=PP_ALIGN.CENTER); textbox(s,x+.1,y+.54,1.63,.25,b,9.5,MUTED,align=PP_ALIGN.CENTER)
textbox(s,5.73,5.55,6.55,.33,"Stored trace: thoughts · tool calls · results · decisions",12,CYAN,True,align=PP_ALIGN.CENTER)
footer(s)

# 7 platform
s=new_slide(7,"Application, APIs and data","A single deployable service with an integrated browser console")
card(s,.65,1.42,3.75,2.05,"React + TypeScript console","Command center, live wall, events, incidents, identities, analytics, cameras, agents, system status and FRS workspace.",BLUE)
card(s,4.78,1.42,3.75,2.05,"FastAPI service","REST routers, authenticated media, per-camera live streams, browser webcam ingest and shared realtime event stream.",CYAN)
card(s,8.91,1.42,3.75,2.05,"Persistence","SQLAlchemy async with SQLite WAL; optional PostgreSQL. Additive migrations run at startup.",AMBER)
rect(s,.65,3.88,12.01,2.45,fill=PANEL)
textbox(s,.95,4.17,2.4,.3,"Core records",18,WHITE,True)
records=[("users + audit","roles and mutations"),("cameras + zones","sources and rules"),("identities + vectors","persistent people"),("tracks","paths and crops"),("events + incidents","evidence and correlation"),("agent_runs","full reasoning traces")]
for i,(a,b) in enumerate(records):
    x=.95+(i%3)*3.92; y=4.72+(i//3)*.72
    textbox(s,x,y,1.5,.22,a,11.5,CYAN,True); textbox(s,x+1.55,y,2.05,.22,b,10.5,MUTED)
textbox(s,.95,6.02,10.9,.2,"Media: data/media/evidence · faces · persons · uploads     |     Occupancy: data/heat/<camera>.npy",10.5,MUTED)
footer(s)

# 8 security
s=new_slide(8,"Security and integration boundaries","Designed for on-premises use with explicit trust and audit controls")
left=[("Session security","JWT in HttpOnly, Secure, SameSite=Strict cookies; bearer tokens supported."),
      ("Access control","Server-side viewer < analyst < admin roles; disabled users lock immediately."),
      ("Auditability","Every mutation and every agent action is written to the audit log."),
      ("Media safety","Uploads are not served directly; paths are confined to the media root.")]
for i,(h,b) in enumerate(left): card(s,.65,1.4+i*1.28,5.55,1.02,h,b,[CYAN,BLUE,AMBER,GREEN][i])
rect(s,6.6,1.4,6.05,5.12,fill=PANEL)
textbox(s,6.95,1.78,5.3,.34,"FRS integration contract",19,WHITE,True)
label(s,6.95,2.3,1.65,"READ ONLY",GREEN)
rich_text(s,6.95,2.85,5.2,2.85,[
    ("Allowed — ","camera relay, watchlist search, records, detections, alerts and health."),
    ("Blocked by design — ","FRS enrollment, deletion, settings, re-index and alert acknowledgement."),
    ("Credential hygiene — ","RTSP credentials are redacted before reaching VIGIL APIs, DB or logs."),
    ("Privacy — ","text and vision reasoning use local Ollama; no cloud dependency is required.")],13)
footer(s)

# 9 hardware
s=new_slide(9,"Hardware profile and sizing","Current host verified locally; sizing tiers are practical deployment guidance")
rect(s,.65,1.4,4.0,5.35,fill=PANEL,line=CYAN)
label(s,.95,1.72,2.12,"CURRENT HOST",CYAN)
textbox(s,.95,2.27,3.25,.52,"NVIDIA GB10",25,WHITE,True)
rich_text(s,.95,2.98,3.05,2.85,[
    ("CPU — ","ARM64, 20 cores (Cortex-X925/A725)"),
    ("Memory — ","121 GiB system/unified memory"),
    ("Storage — ","3.7 TB NVMe; 2.1 TB free at capture"),
    ("GPU driver — ","NVIDIA 580.173.02"),
    ("Software — ","CUDA 13 stack; PyTorch + ONNX Runtime GPU")],13)
textbox(s,.95,6.08,3.05,.35,"Well suited to multi-model, on-prem inference",10.5,GREEN,True)
tiers=[("MINIMUM / DEMO","1–2 streams","8 CPU cores · 32 GB RAM\nNVIDIA GPU with 12+ GB VRAM\n500 GB NVMe",BLUE),
       ("RECOMMENDED","4–8 streams","16+ CPU cores · 64–128 GB RAM\n24–48 GB VRAM / unified memory\n1–2 TB NVMe",CYAN),
       ("SCALE-OUT","8+ streams","Separate ingest/inference nodes\nPostgreSQL + shared object storage\nGPU capacity sized by measured FPS",AMBER)]
for i,(h,k,b,c) in enumerate(tiers):
    y=1.4+i*1.78; rect(s,5.02,y,7.63,1.47,fill=PANEL2,line=c); textbox(s,5.3,y+.18,2.08,.23,h,11,c,True); textbox(s,5.3,y+.57,2.08,.25,k,12.5,WHITE,True); textbox(s,7.6,y+.24,4.65,.86,b,12,MUTED)
textbox(s,5.05,6.76,7.55,.18,"Final capacity depends on resolution, analysis FPS, active motion, camera count, and concurrent LLM/VLM work.",9.2,MUTED,align=PP_ALIGN.CENTER)
footer(s)

# 10 operations
s=new_slide(10,"Deployment and operational readiness","A compact, service-managed deployment with observable health and safe recovery")
ops=[("BUILD","Python venv + CUDA packages\nFetch YOLO / VideoMAE / CLIP\nBuild React frontend",BLUE),
     ("CONFIGURE",".env with VIGIL_* settings\nTLS certificate and keys\nFRS + Ollama endpoints",CYAN),
     ("RUN","systemd user service\nOne uvicorn worker only\nHTTPS console on :8090",GREEN),
     ("OBSERVE","/api/health + /api/ready\n/system/status + /metrics\nrotating structured logs",AMBER)]
for i,(h,b,c) in enumerate(ops): card(s,.65+i*3.03,1.42,2.68,2.05,h,b,c)
rect(s,.65,3.85,12.0,2.45,fill=PANEL)
textbox(s,.95,4.16,3.0,.34,"Recommended next steps",18,WHITE,True)
nexts=[("01","Validate camera-by-camera FPS and latency under real motion."),
       ("02","Tune thresholds and zone rules using local evaluation clips."),
       ("03","Set retention, backup and incident-response policies."),
       ("04","Load-test concurrent streams plus an active investigation."),
       ("05","Move to PostgreSQL/object storage when scaling beyond one node.")]
for i,(n,b) in enumerate(nexts):
    col=i%3; row=i//3; x=.95+col*3.82; y=4.76+row*.68
    textbox(s,x,y,.37,.22,n,11,CYAN,True); textbox(s,x+.43,y,3.15,.42,b,10.5,MUTED)
textbox(s,.72,6.62,11.8,.34,"VIGIL turns continuous video into explainable, reviewable intelligence—while keeping identities, evidence and AI inference under local control.",13,WHITE,True,align=PP_ALIGN.CENTER)
footer(s,"VIGIL · Project overview complete · Source: repository documentation and live host inspection")

prs.core_properties.title = "VIGIL — Agentic Video Analytics"
prs.core_properties.subject = "10-slide technical project overview"
prs.core_properties.author = "OpenAI Codex"
prs.core_properties.keywords = "VIGIL, video analytics, AI, FastAPI, computer vision, port 8090"
prs.save(OUT)
print(OUT)
