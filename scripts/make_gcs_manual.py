#!/usr/bin/env python3
"""Generate the Daedalus Ground Station Operations Manual PDF, styled to match
the team's Mission Operation Manual (Arial, title page, TOC, Page X of Y footer)."""
from fpdf import FPDF
from fpdf.enums import XPos, YPos, MethodReturnValue
from datetime import date

F = "/System/Library/Fonts/Supplemental/"
NAVY = (31, 56, 100)
GREY = (90, 90, 90)
WARN_BG = (255, 244, 204)
WARN_BD = (191, 143, 0)
LINE = (210, 210, 210)

class Manual(FPDF):
    def __init__(self):
        super().__init__(format="A4")
        self.add_font("Arial", "", F + "Arial.ttf")
        self.add_font("Arial", "B", F + "Arial Bold.ttf")
        self.add_font("Arial", "I", F + "Arial Italic.ttf")
        self.set_auto_page_break(True, margin=20)
        self.set_margins(20, 20, 20)
        self.title_page = False

    def header(self):
        if self.title_page or self.page_no() == 1:
            return
        self.set_font("Arial", "", 8)
        self.set_text_color(*GREY)
        self.cell(0, 5, "DAEDALUS #1043  -  Ground Station Operations Manual",
                  new_x=XPos.LMARGIN, new_y=YPos.NEXT, align="R")
        self.set_draw_color(*LINE)
        self.line(20, 27, 190, 27)
        self.ln(6)

    def footer(self):
        if self.title_page or self.page_no() == 1:
            return
        self.set_y(-15)
        self.set_font("Arial", "", 8)
        self.set_text_color(*GREY)
        self.cell(0, 10, f"Page {self.page_no()} of {{nb}}", align="C")

    # ---- building blocks ----
    def h1(self, num, title):
        self.ln(2)
        self.set_font("Arial", "B", 14)
        self.set_text_color(*NAVY)
        self.cell(0, 8, f"{num}   {title}", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        self.set_draw_color(*NAVY)
        self.line(self.l_margin, self.get_y() + 0.5, 190, self.get_y() + 0.5)
        self.ln(3)
        self.set_text_color(0, 0, 0)

    def h2(self, num, title):
        self.ln(1)
        self.set_font("Arial", "B", 11.5)
        self.set_text_color(*NAVY)
        self.cell(0, 7, f"{num}   {title}", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        self.ln(1)
        self.set_text_color(0, 0, 0)

    def body(self, text):
        self.set_font("Arial", "", 10.5)
        self.set_text_color(0, 0, 0)
        self.multi_cell(0, 5.6, text, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        self.ln(1.5)

    def bullets(self, items, bullet="•"):
        self.set_font("Arial", "", 10.5)
        for it in items:
            x = self.get_x()
            self.set_font("Arial", "B", 10.5)
            self.cell(6, 5.6, bullet)
            self.set_font("Arial", "", 10.5)
            self.set_left_margin(self.l_margin + 6)
            self.multi_cell(0, 5.6, it, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
            self.set_left_margin(self.l_margin - 6)
            self.set_x(x)
        self.ln(1.5)

    def checklist(self, items):
        self.set_font("Arial", "", 10.5)
        for it in items:
            x, y = self.get_x(), self.get_y()
            self.set_draw_color(80, 80, 80)
            self.rect(x + 1, y + 1.3, 3.4, 3.4)
            self.set_left_margin(self.l_margin + 8)
            self.set_x(x + 8)
            self.multi_cell(0, 5.8, it, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
            self.set_left_margin(self.l_margin - 8)
            self.set_x(x)
        self.ln(1.5)

    def warning(self, title, text):
        self.ln(1)
        x, y = self.l_margin, self.get_y()
        w = 190 - self.l_margin
        inner = w - 10
        lh = 5.6
        # measure height with a dry run (no drawing)
        self.set_font("Arial", "B", 10.5)
        tlines = self.multi_cell(inner, lh, title, dry_run=True,
                                 output=MethodReturnValue.LINES)
        self.set_font("Arial", "", 10.5)
        blines = self.multi_cell(inner, lh, text, dry_run=True,
                                 output=MethodReturnValue.LINES)
        h = (len(tlines) + len(blines)) * lh + 6
        # box
        self.set_fill_color(*WARN_BG)
        self.set_draw_color(*WARN_BD)
        self.set_line_width(0.5)
        self.rect(x, y, w, h, style="DF")
        self.set_line_width(0.2)
        # text (rendered once, on top)
        self.set_xy(x + 5, y + 3)
        self.set_left_margin(x + 5)
        self.set_right_margin(self.r_margin + 5)
        self.set_font("Arial", "B", 10.5)
        self.set_text_color(120, 80, 0)
        self.multi_cell(0, lh, title, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        self.set_font("Arial", "", 10.5)
        self.set_text_color(60, 45, 0)
        self.multi_cell(0, lh, text, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        self.set_left_margin(self.l_margin - 5)
        self.set_right_margin(self.r_margin - 5)
        self.set_xy(x, y + h + 3)
        self.set_text_color(0, 0, 0)

    def toc_row(self, label, page, indent=0):
        self.set_font("Arial", "B" if indent == 0 else "", 10.5)
        self.set_text_color(0, 0, 0)
        self.cell(indent)
        self.cell(120 - indent, 7, label)
        self.cell(0, 7, str(page), new_x=XPos.LMARGIN, new_y=YPos.NEXT, align="R")


pdf = Manual()

# ---------------- TITLE PAGE ----------------
pdf.title_page = True
pdf.add_page()
pdf.set_font("Arial", "", 9)
pdf.set_text_color(*GREY)
pdf.cell(0, 5, f"Latest Version: {date.today().strftime('%d/%m/%Y')}",
         new_x=XPos.LMARGIN, new_y=YPos.NEXT)
pdf.ln(45)
pdf.set_text_color(*NAVY)
pdf.set_font("Arial", "B", 30)
pdf.cell(0, 14, "DAEDALUS #1043", new_x=XPos.LMARGIN, new_y=YPos.NEXT, align="C")
pdf.set_font("Arial", "", 13)
pdf.set_text_color(0, 0, 0)
pdf.cell(0, 8, "SPACE AC Institute of Technology", new_x=XPos.LMARGIN, new_y=YPos.NEXT, align="C")
pdf.cell(0, 8, "Assumption College, Thailand", new_x=XPos.LMARGIN, new_y=YPos.NEXT, align="C")
pdf.ln(20)
pdf.set_draw_color(*NAVY)
pdf.set_line_width(0.6)
pdf.line(55, pdf.get_y(), 155, pdf.get_y())
pdf.set_line_width(0.2)
pdf.ln(6)
pdf.set_font("Arial", "B", 20)
pdf.set_text_color(*NAVY)
pdf.cell(0, 12, "Ground Station Operations Manual", new_x=XPos.LMARGIN, new_y=YPos.NEXT, align="C")
pdf.set_font("Arial", "", 13)
pdf.set_text_color(0, 0, 0)
pdf.cell(0, 8, "Revision 1.0", new_x=XPos.LMARGIN, new_y=YPos.NEXT, align="C")
pdf.ln(35)
pdf.set_font("Arial", "B", 12)
pdf.cell(0, 7, "CANSAT Competition 2026", new_x=XPos.LMARGIN, new_y=YPos.NEXT, align="C")
pdf.set_font("Arial", "", 12)
pdf.cell(0, 7, "Monterey, VA, USA", new_x=XPos.LMARGIN, new_y=YPos.NEXT, align="C")
pdf.title_page = False

# ---------------- TABLE OF CONTENTS ----------------
pdf.add_page()
pdf.set_font("Arial", "B", 16)
pdf.set_text_color(*NAVY)
pdf.cell(0, 10, "Table of Contents", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
pdf.ln(4)
pdf.set_draw_color(*LINE)
pdf.line(20, pdf.get_y(), 190, pdf.get_y())
pdf.ln(4)
toc = [
    ("Table of Contents", 2, 0),
    ("1.0  Introduction", 3, 0),
    ("1.1  Ground Station Crew Responsibilities", 3, 6),
    ("2.0  System Overview", 4, 0),
    ("3.0  Ground Station Setup", 5, 0),
    ("3.1  MacBook Setup (Main Configuration)", 5, 6),
    ("3.2  Portable Cyberdesk Setup (Raspberry Pi)", 5, 6),
    ("4.0  Pre-Flight Ground Station Checklist", 7, 0),
    ("5.0  XBee Address Selection and Commanding", 8, 0),
    ("6.0  Telemetry, Logging, and Recovery Support", 9, 0),
    ("7.0  Troubleshooting Guide", 10, 0),
    ("8.0  Quick Reference", 12, 0),
]
for label, page, indent in toc:
    pdf.toc_row(label, page, indent)

# ---------------- 1.0 INTRODUCTION ----------------
pdf.add_page()
pdf.h1("1.0", "Introduction")
pdf.body(
    "This manual describes how to set up and operate the Daedalus ground station for the "
    "CANSAT mission. The ground station is the team's link to the CANSAT: it receives live "
    "telemetry over the XBee radio, displays the mission on a real-time dashboard, sends "
    "commands to the satellite, and records every packet for later review. Everything in this "
    "document is written so that any member of the Ground Station Crew can bring the station "
    "online, confirm it is healthy, and run it through a launch without guesswork."
)
pdf.body(
    "The team uses two interchangeable ground stations that run the same software. The MacBook "
    "is used for development, bench testing, and as a backup. The portable cyberdesk, built "
    "around a Raspberry Pi, is the flight-day station and is designed to start itself the moment "
    "it is powered. Both are covered here. Where a step applies to only one of them, it is "
    "clearly labelled."
)

pdf.h2("1.1", "Ground Station Crew Responsibilities")
pdf.body(
    "The Ground Station Crew is responsible for monitoring telemetry reception and issuing "
    "control commands to the CANSAT during mission operations. The crew works in close "
    "coordination with the Mission Control Officer and reports the station's readiness before "
    "every launch."
)
pdf.set_font("Arial", "B", 10.5)
pdf.set_fill_color(*NAVY)
pdf.set_text_color(255, 255, 255)
pdf.cell(55, 7, "  Role", border=1, fill=True)
pdf.cell(0, 7, "  Crew", border=1, fill=True, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
pdf.set_text_color(0, 0, 0)
pdf.set_font("Arial", "", 10.5)
rows = [("Ground Station Crew",
         "Techit Monsakul, Warithnun Kliesuwan, Nopparuch Ungpipatpong")]
for role, crew in rows:
    y = pdf.get_y()
    pdf.multi_cell(55, 6, "  " + role, border=1, new_x=XPos.RIGHT, new_y=YPos.TOP)
    pdf.multi_cell(0, 6, "  " + crew, border=1, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
pdf.ln(2)

# ---------------- 2.0 SYSTEM OVERVIEW ----------------
pdf.add_page()
pdf.h1("2.0", "System Overview")
pdf.body(
    "The ground station software (named Daedalus GCS) is a single program that owns the radio "
    "and serves a dashboard to any web browser on the same network. The radio link is an XBee "
    "PRO 900HP module running in API mode at 115200 baud. The CANSAT sends one telemetry packet "
    "per second; the ground station decodes it, updates the dashboard, and writes it to a CSV "
    "file. When the operator sends a command, the station wraps it in a radio frame addressed to "
    "the exact CANSAT selected on the configuration page and waits for the radio to confirm "
    "delivery."
)
pdf.body("In simple terms, the signal path is:")
pdf.bullets([
    "CANSAT  ->  radio (900 MHz)  ->  ground XBee  ->  USB  ->  Daedalus GCS  ->  dashboard.",
    "Operator command  ->  GCS  ->  ground XBee  ->  radio  ->  CANSAT.",
])
pdf.body(
    "The two stations differ only in hardware and start-up. The MacBook is connected by hand and "
    "the operator starts the software; the portable cyberdesk is powered as a unit and starts the "
    "software automatically. Both open the same dashboard at http://localhost:8080."
)

# ---------------- 3.0 SETUP ----------------
pdf.add_page()
pdf.h1("3.0", "Ground Station Setup")
pdf.body(
    "Set up whichever station you are using by following the matching procedure below. One rule "
    "applies to both, and to every radio you will ever handle: the antenna must be attached to "
    "the XBee before the radio receives power. A radio that transmits without an antenna can be "
    "permanently damaged."
)

pdf.h2("3.1", "MacBook Setup (Main Configuration)")
pdf.body(
    "The MacBook configuration is the primary bench and backup station. Build the radio link "
    "outward from the radio itself, in the order below, so the connection is complete before the "
    "MacBook ever sees the device."
)
pdf.checklist([
    "Attach the antenna to the XBee module first. Make sure it is finger-tight before doing "
    "anything else.",
    "Seat the XBee firmly onto its USB adapter board, checking that the pins are aligned and "
    "fully inserted.",
    "Connect the USB adapter to the USB extender cable.",
    "Connect the USB extender to the MacBook.",
    "Open Terminal, activate the environment, and start the software with: python main.py",
    "At the serial-port picker, choose the XBee's port (it looks like /dev/cu.usbserial-...).",
    "Open http://localhost:8080 and confirm the Connected indicator is green.",
])

pdf.h2("3.2", "Portable Cyberdesk Setup (Raspberry Pi Configuration)")
pdf.body(
    "The portable cyberdesk is the flight-day ground station. It is designed to be effortless on "
    "the field: when it receives power, the Raspberry Pi boots, the ground station software starts "
    "by itself, and the dashboard opens in full screen. Because it powers the radio automatically, "
    "there is one step you must perform every single time, before you press the power button."
)
pdf.warning(
    "IMPORTANT - Attach the antenna before powering the cyberdesk.",
    "The XBee radio powers up the instant the cyberdesk does. If the antenna is not connected at "
    "that moment, the radio can be damaged on boot. Always plug the antenna into the XBee first, "
    "every time, with no exceptions."
)
pdf.checklist([
    "Connect the antenna to the XBee module and confirm it is finger-tight. Do this first, "
    "before power.",
    "Power on the portable cyberdesk.",
    "Wait for the Raspberry Pi to boot. The ground station software starts automatically and the "
    "dashboard appears on the screen.",
    "Confirm the Connected indicator is green and that telemetry begins to arrive.",
    "If the dashboard does not appear or stays disconnected, see the Troubleshooting Guide in "
    "Section 7.",
])

# ---------------- 4.0 PRE-FLIGHT CHECKLIST ----------------
pdf.add_page()
pdf.h1("4.0", "Pre-Flight Ground Station Checklist")
pdf.body(
    "Complete this checklist at the ground station before every flight, after the station is set "
    "up and the CANSAT is powered. Each item should be confirmed out loud so the crew shares the "
    "same picture of readiness."
)
pdf.checklist([
    "Ground station software is running and the dashboard is open at http://localhost:8080.",
    "The Connected indicator is green.",
    "On the configuration page, the correct CANSAT unit is selected and the XBee indicator shows "
    "the right unit.",
    "Send CX,ON and confirm the dashboard reports the uplink was delivered to the CANSAT.",
    "Telemetry is arriving steadily at 1 Hz; the received-packet counter is climbing and losses "
    "are near zero.",
    "Live values look sensible: mission time, altitude, battery at or above 7.9 V, GPS satellites, "
    "and flight state.",
    "Signal strength (RSSI) is reasonable and not sitting at the noise floor.",
    "The map shows the CANSAT once it has a GPS fix; if operating offline, the launch area has "
    "been pre-loaded while online.",
    "The active log file is correct for this run.",
    "Calibration and arming commands have been sent per the integration checklist, and each one "
    "reported a successful delivery.",
])

# ---------------- 5.0 XBEE ADDRESS / COMMANDING ----------------
pdf.add_page()
pdf.h1("5.0", "XBee Address Selection and Commanding")
pdf.body(
    "Every command is addressed to one specific CANSAT. The address is chosen on the "
    "configuration page (open http://localhost:8080/config). The page offers three preset units "
    "as Quick Select buttons and a Custom option for any unit not in the presets."
)
pdf.bullets([
    "To target a known unit, press its Quick Select button (1, 2, or 3), then press Apply. The "
    "XBee indicator on the dashboard updates to show the active unit.",
    "To target a new unit, choose Custom and enter its address by hand.",
    "The selected address is saved automatically and restored after a restart, so the station "
    "never quietly reverts to the wrong unit after a reboot.",
    "The station will never broadcast. A command always goes to exactly one CANSAT.",
])
pdf.body(
    "If two CANSATs ever respond to a single command, the cause is two radios sharing the same "
    "address, not the ground station. Give each radio a unique address and the problem disappears."
)
pdf.body(
    "Commands are sent from the command page or the quick-command menu. The station automatically "
    "adds the team prefix, so you only type the command itself, for example CX,ON or CAL,NORTH. "
    "After each command, the dashboard shows whether the radio confirmed delivery to the CANSAT, "
    "so a sent command is never mistaken for a delivered one."
)

# ---------------- 6.0 TELEMETRY / LOGGING / RECOVERY ----------------
pdf.add_page()
pdf.h1("6.0", "Telemetry, Logging, and Recovery Support")
pdf.body(
    "Every packet the CANSAT sends is written to disk the moment it arrives, before any "
    "processing, so nothing is ever lost. Flight data is saved to a CSV file, and the flight path "
    "is continuously exported to a KML file that can be opened directly in Google Earth. A named "
    "log can be started for each run so test data and flight data stay separate."
)
pdf.body(
    "During descent and recovery, the dashboard supports the Recovery Crew by showing the "
    "CANSAT's live GPS position and its track on the map. The last known coordinates remain on "
    "screen after landing, and the portable cyberdesk also shows the operator's own position with "
    "the range and bearing to the CANSAT to guide the walk-in. These on-screen aids work alongside "
    "the CANSAT's own audio beacon and AirTag."
)

# ---------------- 7.0 TROUBLESHOOTING ----------------
pdf.add_page()
pdf.h1("7.0", "Troubleshooting Guide")
pdf.body(
    "Work through the symptom that matches what you see. Each entry lists the most likely cause "
    "and the fastest fix, in hardware and in software."
)

def issue(title, lines):
    pdf.set_font("Arial", "B", 10.5)
    pdf.set_text_color(*NAVY)
    pdf.multi_cell(0, 6, title, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.set_text_color(0, 0, 0)
    pdf.bullets(lines)

issue("The Connected indicator stays red (no radio).", [
    "Hardware: re-seat the XBee and its USB adapter, and try a different USB port or cable. Make "
    "sure the antenna is attached and the adapter's light is on.",
    "Software (MacBook): pick the correct serial port in the configuration panel and connect.",
    "Software (cyberdesk): the radio appears as /dev/xbee0. If it is missing, unplug and replug "
    "the radio, or restart the station; the radio must be the only program using that port.",
])
issue("Connected, but no telemetry is arriving.", [
    "Send CX,ON first - transmission may simply be off.",
    "Hardware: confirm the CANSAT is powered and its status light is blinking.",
    "Software: both radios must use the same settings (API mode, 115200 baud, and the same "
    "channel). A mismatch produces silence even with a perfect Connected indicator.",
])
issue("A command says it was sent but the CANSAT does not respond.", [
    "Read the delivery result. If it says NOT delivered, the frame reached the radio but got no "
    "acknowledgement: improve the link (antenna aim, line of sight, distance) and confirm the "
    "CANSAT radio is on.",
    "Confirm the configuration page is targeting the correct unit.",
    "If it says delivered but nothing happens, the CANSAT received it but did not act - check the "
    "command and its preconditions (for example, simulation must be enabled before it is "
    "activated).",
])
issue("The command buttons do nothing and there is no message.", [
    "Reload the dashboard with a hard refresh. On the cyberdesk, restart the station and reload.",
    "This is usually a display glitch during start-up; it does not affect the radio or the data "
    "already saved.",
])
issue("The map is blank.", [
    "Online: the map tiles are still loading - wait a moment, or switch between 3D and 2D with the "
    "map toggle.",
    "Offline: only areas you viewed while online are stored. Before losing internet, pan and zoom "
    "around the launch site so it is cached. On the cyberdesk the map falls back to 2D if 3D "
    "cannot start, and the rest of the dashboard keeps working.",
])
issue("After a restart, commands seem to go to the wrong unit.", [
    "The selected address is saved and restored automatically, so this should not happen. If it "
    "does, simply re-select the unit on the configuration page - it will save again.",
])

# ---------------- 8.0 QUICK REFERENCE ----------------
pdf.add_page()
pdf.h1("8.0", "Quick Reference")
pdf.set_font("Arial", "B", 10.5)
pdf.set_text_color(*NAVY)
pdf.multi_cell(0, 6, "Sixty-second triage", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
pdf.set_text_color(0, 0, 0)
pdf.bullets([
    "Indicator red? Fix the radio or the serial port.",
    "Connected but no data? Send CX,ON, then check that both radios use the same settings.",
    "Command not working? Read the delivery result and check the selected unit on the "
    "configuration page.",
    "Buttons dead? Hard-refresh the dashboard.",
    "Map blank? Toggle to 2D and pre-load the launch area while online.",
])
pdf.ln(2)
pdf.set_font("Arial", "B", 10.5)
pdf.set_text_color(*NAVY)
pdf.multi_cell(0, 6, "Key facts", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
pdf.set_text_color(0, 0, 0)
pdf.bullets([
    "Dashboard: http://localhost:8080   -   Configuration: /config   -   Commands: /cmd",
    "Radio: XBee PRO 900HP, API mode, 115200 baud, 1 Hz telemetry.",
    "Always connect the antenna before powering the radio.",
    "MacBook order: XBee onto adapter, adapter to USB extender, extender to MacBook.",
    "Cyberdesk: antenna on the XBee first, then power on - the station starts itself.",
])

out = "/Users/tae/Downloads/Daedalus_Ground_Station_Manual.pdf"
pdf.output(out)
print("WROTE", out, "pages:", pdf.page_no())
