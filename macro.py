# -*- coding: utf-8 -*-
"""
Robot Hotkey Macro (ฉบับปรับปรุง)
=================================
กดคีย์ลัด -> พิมพ์โค้ดหุ่นยนต์ลง IDE (Arduino IDE / VS Code) ที่บรรทัดปัจจุบัน แล้วขึ้นบรรทัดใหม่ให้อัตโนมัติ
ค่า speed / cm / ms / dir / angle / action char ดึงจากหน้าต่างโพย (Always-on-Top) แบบสด ๆ

ปิดโปรแกรม: Ctrl+Shift+Q  (หรือปิดหน้าต่าง)

โหมดพิเศษ (ไม่กดคีย์ใส่ IDE):
    python macro.py --selftest      ตรวจว่าทุกคำสั่งในชุด API render ได้ + คีย์ลัดไม่ซ้ำ
    python macro.py --table         พิมพ์ตารางคีย์ลัดเป็น Markdown (ใช้ทำ README)
    python macro.py --gui-test      สร้างหน้าต่าง GUI แล้วปิดทันที (เช็กว่า Tk ใช้ได้)

หมายเหตุทางเทคนิค
- คีย์ลัดใช้ Win32 RegisterHotKey (ไม่ใช้ hook ของไลบรารี keyboard) จึงไม่ทำให้ปุ่มค้าง,
  กินคีย์ลัดไม่ให้หลุดไปถึง IDE และทำงานได้แม้คีย์บอร์ดเป็นภาษาไทย (อ้างอิง virtual-key ไม่ใช่ตัวอักษร)
- การพิมพ์ใช้ Clipboard + Ctrl+V (ไม่เพี้ยนเป็นภาษาไทย และไม่โดน IDE เติมวงเล็บ/ฟันหนูซ้ำ)
  แล้วคืนค่า Clipboard เดิมให้
"""

import ctypes
import os
import queue
import sys
import threading
import time
from ctypes import wintypes

# ============================================================================
# 1) ค่าตั้งต้น (แก้ตรงนี้ได้เลย)
# ============================================================================
DEFAULT_SPEED = 70        # ความเร็วปกติ           (Ctrl+Alt+9)
FAST_SPEED = 90           # ความเร็วสูง            (Ctrl+Alt+0)
SLOW_SPEED = 40           # ความเร็วต่ำ/งานละเอียด (Ctrl+Alt+8)
DEFAULT_CM = 20           # ระยะทาง (cm)
DEFAULT_MS = 500          # เวลา (ms)
DEFAULT_DIR = 0           # ทิศสัมบูรณ์ 0 / 90 / 180 / 270
DEFAULT_ANGLE = 90        # มุมหมุน/เลี้ยวสัมพัทธ์ (slg/srg/tlg/...)
DEFAULT_ACTION = 'p'      # ตัวอักษรโหมดหยุด/เลี้ยวแยก
DEFAULT_TOL = None        # tol (tolerance) ของ *dircl/*dircr: None = ไม่ใส่
TOL_PRESETS = (None, 1, 2, 3, 5)
FORCED_ACTION = 'p'       # คำสั่งที่บังคับ action (ชุด *dirclg) แต่ผู้ใช้เลือก None -> ใช้ตัวนี้แทน

SPEED_STEP = 5            # Ctrl+Alt+= / Ctrl+Alt+-
CM_STEP = 5               # Ctrl+Alt+] / Ctrl+Alt+[
MS_STEP = 100             # Ctrl+Alt+Shift+] / Ctrl+Alt+Shift+[
ANGLE_STEP = 5            # ปุ่มบนจอ
SPEED_MIN, SPEED_MAX = 0, 100
DIR_CHOICES = (0, 90, 180, 270)

# ---- พฤติกรรมการพิมพ์ ----
PRESS_END_BEFORE = True   # กด End ก่อนพิมพ์ (ต่อท้ายบรรทัด)
PRESS_ENTER_AFTER = True  # กด Enter หลังพิมพ์ (ขึ้นบรรทัดใหม่ + IDE จัดย่อหน้าให้)
USE_SHORT_ALIAS = False   # True = ใช้ชื่อย่อ เช่น sdg / tlg แทน spindir / turnlg
GYRO_INCLUDE_ACT = True   # ffcmg/bbcmg/ffcmgs/bbcmgs: ใส่ 'p' (optional) ไหม
GYRO_INCLUDE_DIR = False  # ffcmg/bbcmg/ffcmgs/bbcmgs: ใส่ dir (optional) ไหม
OPT_SPEED_INCLUDE = True  # spinl/spinr/spinl2/spinr2 + spindir/spinlg/spinrg: ใส่ speed (optional) ไหม
TYPE_METHOD = 'clipboard' # 'clipboard' (แนะนำ) หรือ 'unicode' (ใช้ keyboard.write)
RESTORE_CLIPBOARD = True  # คืนค่า Clipboard เดิมหลังวาง

# ---- จังหวะเวลา (วินาที) ปรับเพิ่มถ้าเครื่องช้าแล้วพิมพ์ไม่ครบ ----
MODIFIER_RELEASE_TIMEOUT = 10.0 # รอให้ปล่อย Ctrl/Alt/Shift ก่อนพิมพ์ (กดค้างแล้วรัวหลายคำสั่งได้)
FOCUS_DELAY = 0.12              # รอหลังสลับกลับไปหน้าต่าง IDE (กรณีกดปุ่มบนจอ)
KEY_GAP = 0.02                  # เว้นระหว่างปุ่ม
PASTE_SETTLE = 0.06             # รอหลัง Ctrl+V ก่อนกด Enter
CLIPBOARD_RESTORE_DELAY = 0.30  # รอก่อนคืนค่า Clipboard

# ---- หน้าต่าง ----
WINDOW_ALPHA = 1.0        # 0.85 - 1.0 (โปร่งใส)
ALWAYS_ON_TOP = True
CODE_FONT = ('Consolas', 10)
UI_FONT = ('Segoe UI', 9)
STATUS_FONT = ('Segoe UI', 10)
HOVER_DEBOUNCE_MS = 30    # หน่วงพรีวิวตอนชี้ปุ่ม กัน UI รีเฟรชรัวเวลาลากเมาส์ผ่านหลายปุ่ม
STATUS_LINES = 2          # ความสูงคงที่ของบรรทัดสถานะ (บรรทัด) — ข้อความยาวกว่านี้จะถูกตัด ไม่ดันแท็บลง
TARGET_LABEL_CHARS = 32   # ความกว้างคงที่ของป้าย "เป้าหมาย: ..." (ตัวอักษร) กันหน้าต่างยืด/หดตามชื่อหน้าต่าง IDE

EXIT_HOTKEY = 'ctrl+shift+q'

# ============================================================================
# 2) ตัวอักษรโหมดหยุด/เลี้ยวแยก (Action Characters)
#    (ตัวอักษร, ความหมายในโหมด ff/bb, ความหมายในโหมด Gyro)
# ============================================================================
ACTION_CHARS = [
    ('s', 'หยุด', 'หยุด'),
    ('S', 'วิ่งถึงขอบเส้นแล้วหยุด', 'หยุด'),
    ('p', 'วิ่งผ่านแยก', 'วิ่งผ่านแยก'),
    ('P', 'วิ่งผ่านแยก', 'วิ่งผ่านแยก'),
    ('c', 'เข้ากลางแยกแล้วหยุด', 'เข้ากลางแยกแล้วหยุด'),
    ('C', 'เข้ากลางแยกแล้วหยุด', 'เข้ากลางแยกแล้วหยุด'),
    ('l', 'เข้ากลาง + หมุนซ้าย', 'เข้ากลาง + หมุนซ้าย'),
    ('L', 'เข้ากลาง + หมุนซ้าย', 'หมุนซ้ายทันที'),
    ('r', 'เข้ากลาง + หมุนขวา', 'เข้ากลาง + หมุนขวา'),
    ('R', 'เข้ากลาง + หมุนขวา', 'หมุนขวาทันที'),
    ('q', 'เลี้ยวโค้งซ้าย (bb = ขวา)', 'เลี้ยวโค้งซ้าย (gb = ขวา)'),
    ('Q', 'เลี้ยวโค้งซ้าย (bb = ขวา)', 'เลี้ยวโค้งซ้าย (gb = ขวา)'),
    ('e', 'เลี้ยวโค้งขวา (bb = ซ้าย)', 'เลี้ยวโค้งขวา (gb = ซ้าย)'),
    ('E', 'เลี้ยวโค้งขวา (bb = ซ้าย)', 'เลี้ยวโค้งขวา (gb = ซ้าย)'),
    ('a', 'หมุนซ้ายด้วยเซนเซอร์หลัง', '-'),
    ('A', 'หมุนซ้ายด้วยเซนเซอร์หลัง', '-'),
    ('d', 'หมุนขวาด้วยเซนเซอร์หลัง', '-'),
    ('D', 'หมุนขวาด้วยเซนเซอร์หลัง', '-'),
    ('b', 'เข้ากลางแล้ววิ่งต่อถึงเส้นอีกฝั่ง', 'เข้ากลางแล้ววิ่งต่อถึงเส้นอีกฝั่ง'),
    ('B', 'เข้ากลางแล้ววิ่งต่อถึงเส้นอีกฝั่ง', 'เข้ากลางแล้ววิ่งต่อถึงเส้นอีกฝั่ง'),
    ('g', 'ปรับตรงด้วย Gyro', 'ตัวอื่น ๆ = SetG(100)'),
    ('G', 'ปรับตรงด้วย Gyro', 'ตัวอื่น ๆ = SetG(100)'),
]
ACTION_LIST = [c for c, _, _ in ACTION_CHARS]
ACTION_INFO = {c: (line, gyro) for c, line, gyro in ACTION_CHARS}
ACT_NONE = ''   # ปุ่ม None = ไม่ใส่ตัวอักษร (ใช้กับคำสั่งที่ action เป็น optional)

# คำย่อบรรทัดล่างบนปุ่ม Action Pad
ACTION_SHORT = {
    's': 'หยุด', 'S': 'ขอบเส้นหยุด', 'c': 'กลางหยุด', 'C': 'กลางหยุด',
    'p': 'ผ่านแยก', 'P': 'ผ่านแยก', 'b': 'ทะลุอีกฝั่ง', 'B': 'ทะลุอีกฝั่ง',
    'l': 'กลาง+ซ้าย', 'L': 'ซ้ายทันที', 'r': 'กลาง+ขวา', 'R': 'ขวาทันที',
    'q': 'โค้งซ้าย', 'Q': 'โค้งซ้าย', 'e': 'โค้งขวา', 'E': 'โค้งขวา',
    'a': 'หลังซ้าย', 'A': 'หลังซ้าย', 'd': 'หลังขวา', 'D': 'หลังขวา',
    'g': 'ปรับตรง', 'G': 'ปรับตรง', ACT_NONE: 'ไม่ใส่ตัวอักษร',
}

# หมวดสีของ Action Pad: (ชื่อหมวด, สีพื้นอ่อน, สีเข้ม, ตัวอักษร)
ACTION_GROUPS = [
    ('หยุด', '#fde2e2', '#c53030', ['s', 'S', 'c', 'C']),
    ('ผ่าน/ทะลุ', '#dcfce7', '#2f855a', ['p', 'P', 'b', 'B']),
    ('หมุนแยก', '#dbeafe', '#1d4ed8', ['l', 'L', 'r', 'R']),
    ('เลี้ยวโค้ง', '#ffedd5', '#c05621', ['q', 'Q', 'e', 'E']),
    ('หลัง/Gyro', '#ede9fe', '#6b21a8', ['a', 'A', 'd', 'D', 'g', 'G']),
]
ACTION_NONE_COLORS = ('#eeeeee', '#4a5568')
ACTION_COLOR = {ch: (light, strong) for _, light, strong, chars in ACTION_GROUPS for ch in chars}
ACTION_COLOR[ACT_NONE] = ACTION_NONE_COLORS
ACTION_FONT = ('Consolas', 16, 'bold')     # ตัวอักษรบนปุ่ม (ใหญ่ แยกเล็ก/ใหญ่ชัด)
ACTION_SUB_FONT = ('Segoe UI', 8)          # คำย่อบรรทัดล่าง
ACTION_CYCLE = ['p', 'c', 'l', 'r', 's', 'b', 'q', 'e', 'a', 'd', 'g']  # Ctrl+Alt+/ วนตัวถัดไป

# ============================================================================
# 3) ตารางคำสั่ง (MACROS)
#    params: speed cm ms dir angle act tol  + เครื่องหมายท้ายชื่อ:
#       (ไม่มี)  บังคับใส่เสมอ
#       ?        optional ตามติ๊กในหน้าต่าง (act? / dir? = "Gyro ใส่ act/dir", speed? = "ใส่ speed (opt.)",
#                tol? = ช่อง tol ไม่ว่าง)  — ถ้า ? ตัวหลังถูกใส่ ตัว ? ก่อนหน้าต้องใส่ด้วย (เรียงตำแหน่ง)
#       ~        act~ = ใส่เมื่อเลือกตัวอักษร / ตัดทิ้งเมื่อเลือก None (ตัดกลางรายการได้ เช่น ffdircl)
#       !        act! = บังคับมี action ถ้าเลือก None จะใช้ FORCED_ACTION ('p') แทน
#    raw   : ข้อความแม่แบบ ใช้ {speed} {cm} {ms} {dir} {angle} {act} {tol} {fast} {slow} ได้
# ============================================================================


class Cmd:
    """คำสั่งที่พิมพ์โค้ดลง IDE"""

    def __init__(self, cat, hotkey, name, params='', alias=None, desc='', raw=None):
        self.cat = cat
        self.hotkey = hotkey
        self.name = name
        self.params = params.split()
        self.alias = alias
        self.desc = desc
        self.raw = raw

    @property
    def id(self):
        return 'cmd:' + self.hotkey   # คีย์ลัดไม่ซ้ำกัน (fft มี 2 แบบ จึงใช้ชื่อเป็น id ไม่ได้)

    def label(self, short=False):
        if self.raw:
            return self.name
        return self.alias if (short and self.alias) else self.name


CAT_LINE = 'เดินตามเส้น'
CAT_DIST = 'ระยะ/เวลา'
CAT_SPIN_LINE = 'หมุนหาเส้น (เซนเซอร์หน้า)'
CAT_CURVE_CM = 'โค้งตามระยะ (cm)'
CAT_DIR_LINE = 'โค้งจนถึงทิศ dir (จบโหมดเส้น)'
CAT_DIR_G = 'โค้งจนถึงทิศ dir (จบ *g)'
CAT_GYRO = 'Gyro วิ่ง'
CAT_TURN = 'Gyro หมุน/ทิศ'
CAT_ARM = 'แขนกล'
CAT_ARM2 = 'แขนกล (ท่าผสม)'
CAT_CUSTOM = 'กำหนดเอง'

MACROS = [
    # ---------- เดินตามเส้น: Ctrl+Alt+1..4 = ไปหน้า / +Shift = ถอยหลัง ----------
    Cmd(CAT_LINE, 'ctrl+alt+1', 'ff', 'speed act', desc='เดินหน้าตามเส้น'),
    Cmd(CAT_LINE, 'ctrl+alt+2', 'ffc', 'speed act', desc='เดินหน้าตามเส้น (กลาง)'),
    Cmd(CAT_LINE, 'ctrl+alt+3', 'ffl', 'speed act', desc='เดินหน้าตามเส้น (ซ้าย)'),
    Cmd(CAT_LINE, 'ctrl+alt+4', 'ffr', 'speed act', desc='เดินหน้าตามเส้น (ขวา)'),
    Cmd(CAT_LINE, 'ctrl+alt+shift+1', 'bb', 'speed act', desc='ถอยหลังตามเส้น'),
    Cmd(CAT_LINE, 'ctrl+alt+shift+2', 'bbc', 'speed act', desc='ถอยหลังตามเส้น (กลาง)'),
    Cmd(CAT_LINE, 'ctrl+alt+shift+3', 'bbl', 'speed act', desc='ถอยหลังตามเส้น (ซ้าย)'),
    Cmd(CAT_LINE, 'ctrl+alt+shift+4', 'bbr', 'speed act', desc='ถอยหลังตามเส้น (ขวา)'),

    # ---------- ระยะ / เวลา: Ctrl+Alt+5..7 / +Shift = ถอยหลัง ----------
    Cmd(CAT_DIST, 'ctrl+alt+5', 'ffcm', 'speed cm', desc='เดินหน้าตามระยะ (cm)'),
    Cmd(CAT_DIST, 'ctrl+alt+shift+5', 'bbcm', 'speed cm', desc='ถอยหลังตามระยะ (cm)'),
    Cmd(CAT_DIST, 'ctrl+alt+6', 'fft', 'speed ms', desc='เดินหน้าตามเวลา (ms)'),
    Cmd(CAT_DIST, 'ctrl+alt+shift+6', 'bbt', 'speed ms', desc='ถอยหลังตามเวลา (ms)'),
    Cmd(CAT_DIST, 'ctrl+alt+7', 'fft', 'speed ms act', desc='เดินหน้าตามเวลา + action'),
    Cmd(CAT_DIST, 'ctrl+alt+shift+7', 'bbt', 'speed ms act', desc='ถอยหลังตามเวลา + action'),

    # ---------- หมุนหาเส้นถัดไป (เซนเซอร์หน้า): Shift+A/D = 1 เส้น, Shift+J/L = เส้นที่ 2 ----------
    Cmd(CAT_SPIN_LINE, 'ctrl+alt+shift+a', 'spinl', 'speed?', desc='หมุนซ้ายหาเส้นถัดไป'),
    Cmd(CAT_SPIN_LINE, 'ctrl+alt+shift+d', 'spinr', 'speed?', desc='หมุนขวาหาเส้นถัดไป'),
    Cmd(CAT_SPIN_LINE, 'ctrl+alt+shift+j', 'spinl2', 'speed?', desc='หมุนซ้ายข้ามไปเส้นที่ 2'),
    Cmd(CAT_SPIN_LINE, 'ctrl+alt+shift+l', 'spinr2', 'speed?', desc='หมุนขวาข้ามไปเส้นที่ 2'),

    # ---------- โค้งตามระยะ: T / Y (+Shift = ถอยหลัง) ----------
    Cmd(CAT_CURVE_CM, 'ctrl+alt+t', 'ffcmcl', 'speed cm act~', desc='เดินหน้าโค้งซ้ายตามระยะ'),
    Cmd(CAT_CURVE_CM, 'ctrl+alt+y', 'ffcmcr', 'speed cm act~', desc='เดินหน้าโค้งขวาตามระยะ'),
    Cmd(CAT_CURVE_CM, 'ctrl+alt+shift+t', 'bbcmcl', 'speed cm act~', desc='ถอยหลังโค้งซ้ายตามระยะ'),
    Cmd(CAT_CURVE_CM, 'ctrl+alt+shift+y', 'bbcmcr', 'speed cm act~', desc='ถอยหลังโค้งขวาตามระยะ'),

    # ---------- โค้งจนถึงทิศ dir จบโหมดเส้น (MyRP): ; / ' (+Shift = ถอยหลัง)  ลำดับ: speed, [act,] dir [, tol] ----------
    Cmd(CAT_DIR_LINE, 'ctrl+alt+;', 'ffdircl', 'speed act~ dir tol?', desc='เดินหน้าโค้งซ้ายจนถึงทิศ dir'),
    Cmd(CAT_DIR_LINE, "ctrl+alt+'", 'ffdircr', 'speed act~ dir tol?', desc='เดินหน้าโค้งขวาจนถึงทิศ dir'),
    Cmd(CAT_DIR_LINE, 'ctrl+alt+shift+;', 'bbdircl', 'speed act~ dir tol?', desc='ถอยหลังโค้งซ้ายจนถึงทิศ dir'),
    Cmd(CAT_DIR_LINE, "ctrl+alt+shift+'", 'bbdircr', 'speed act~ dir tol?', desc='ถอยหลังโค้งขวาจนถึงทิศ dir'),

    # ---------- โค้งจนถึงทิศ dir จบ *g: Z / X (+Shift = ถอยหลัง)  action บังคับ (None -> 'p') ----------
    Cmd(CAT_DIR_G, 'ctrl+alt+z', 'ffdirclg', 'speed act! dir tol?', desc="เดินหน้าโค้งซ้ายถึง dir จบ *g (None→'p')"),
    Cmd(CAT_DIR_G, 'ctrl+alt+x', 'ffdircrg', 'speed act! dir tol?', desc="เดินหน้าโค้งขวาถึง dir จบ *g (None→'p')"),
    Cmd(CAT_DIR_G, 'ctrl+alt+shift+z', 'bbdirclg', 'speed act! dir tol?', desc="ถอยหลังโค้งซ้ายถึง dir จบ *g (None→'p')"),
    Cmd(CAT_DIR_G, 'ctrl+alt+shift+x', 'bbdircrg', 'speed act! dir tol?', desc="ถอยหลังโค้งขวาถึง dir จบ *g (None→'p')"),

    # ---------- Gyro วิ่ง: G / H / B  (+Shift = ถอยหลัง)  + รีเซ็ตมุม = Ctrl+Alt+O (O = 0°) ----------
    Cmd(CAT_GYRO, 'ctrl+alt+o', 'resetAngles', desc='รีเซ็ตมุมไจโร (ตั้งลำ/เช็กพอยต์)'),
    Cmd(CAT_GYRO, 'ctrl+alt+g', 'ffcmg', 'speed cm act? dir?', desc='Gyro ตามระยะ เร่ง/ผ่อน'),
    Cmd(CAT_GYRO, 'ctrl+alt+shift+g', 'bbcmg', 'speed cm act? dir?', desc='Gyro ถอยตามระยะ เร่ง/ผ่อน'),
    Cmd(CAT_GYRO, 'ctrl+alt+h', 'ffcmgs', 'speed cm act? dir?', desc='Gyro ตามระยะ ความเร็วคงที่'),
    Cmd(CAT_GYRO, 'ctrl+alt+shift+h', 'bbcmgs', 'speed cm act? dir?', desc='Gyro ถอยตามระยะ ความเร็วคงที่'),
    Cmd(CAT_GYRO, 'ctrl+alt+b', 'ffbg', 'speed act dir', desc='Gyro วิ่งจนเจอเส้น'),
    Cmd(CAT_GYRO, 'ctrl+alt+shift+b', 'bbbg', 'speed act dir', desc='Gyro ถอยจนเจอเส้น'),

    # ---------- หันทิศสัมบูรณ์: N / M (+Shift) ----------
    Cmd(CAT_TURN, 'ctrl+alt+n', 'spindir', 'speed? dir', alias='sdg', desc='หมุนอยู่กับที่ไปทิศ dir'),
    Cmd(CAT_TURN, 'ctrl+alt+m', 'turndir', 'speed dir', alias='tdg', desc='เลี้ยว(เดินหน้า)ไปทิศ dir'),
    Cmd(CAT_TURN, 'ctrl+alt+shift+m', 'turndirb', 'speed dir', alias='tdbg', desc='เลี้ยว(ถอยหลัง)ไปทิศ dir'),
    # ---------- หมุน/เลี้ยวสัมพัทธ์: A D = หมุน, Q E = เลี้ยวหน้า, Shift+Q E = เลี้ยวถอย ----------
    Cmd(CAT_TURN, 'ctrl+alt+a', 'spinlg', 'speed? angle', alias='slg', desc='หมุนซ้ายอยู่กับที่'),
    Cmd(CAT_TURN, 'ctrl+alt+d', 'spinrg', 'speed? angle', alias='srg', desc='หมุนขวาอยู่กับที่'),
    Cmd(CAT_TURN, 'ctrl+alt+q', 'turnlg', 'speed angle', alias='tlg', desc='เลี้ยวซ้าย (เดินหน้า)'),
    Cmd(CAT_TURN, 'ctrl+alt+e', 'turnrg', 'speed angle', alias='trg', desc='เลี้ยวขวา (เดินหน้า)'),
    Cmd(CAT_TURN, 'ctrl+alt+shift+q', 'turnlbg', 'speed angle', alias='tlbg', desc='เลี้ยวซ้าย (ถอยหลัง)'),
    Cmd(CAT_TURN, 'ctrl+alt+shift+e', 'turnrbg', 'speed angle', alias='trbg', desc='เลี้ยวขวา (ถอยหลัง)'),

    # ---------- แขนกล: Ctrl+Alt+F1..F12 ----------
    Cmd(CAT_ARM, 'ctrl+alt+f1', 'arm_ready', desc='ท่าเตรียม'),
    Cmd(CAT_ARM, 'ctrl+alt+f2', 'arm_up', desc='ยกขึ้น'),
    Cmd(CAT_ARM, 'ctrl+alt+f3', 'arm_up45', desc='ยก 45°'),
    Cmd(CAT_ARM, 'ctrl+alt+f4', 'arm_down', desc='ลง'),
    Cmd(CAT_ARM, 'ctrl+alt+f5', 'arm_open', desc='ปล่อย'),
    Cmd(CAT_ARM, 'ctrl+alt+f6', 'arm_close', desc='หนีบ'),
    Cmd(CAT_ARM, 'ctrl+alt+f7', 'arm_open_l', desc='เปิดซ้าย'),
    Cmd(CAT_ARM, 'ctrl+alt+f8', 'arm_open_r', desc='เปิดขวา'),
    Cmd(CAT_ARM, 'ctrl+alt+f9', 'arm_big', desc='ท่ากล่องใหญ่'),
    Cmd(CAT_ARM, 'ctrl+alt+f10', 'arm_big_box', desc='จับกล่องใหญ่'),
    Cmd(CAT_ARM, 'ctrl+alt+f11', 'arm_big_box_up', desc='ยกกล่องใหญ่'),
    Cmd(CAT_ARM, 'ctrl+alt+f12', 'arm_behihd', desc='ท่าด้านหลัง (สะกดตามไลบรารี)'),
    # ---------- แขนกลท่าผสม: Ctrl+Alt+Shift+F1..F8 ----------
    Cmd(CAT_ARM2, 'ctrl+alt+shift+f1', 'arm_open_down', desc='ปล่อย → ลง'),
    Cmd(CAT_ARM2, 'ctrl+alt+shift+f2', 'arm_down_open', desc='ลง → ปล่อย'),
    Cmd(CAT_ARM2, 'ctrl+alt+shift+f3', 'arm_open_up', desc='ปล่อย → ยก'),
    Cmd(CAT_ARM2, 'ctrl+alt+shift+f4', 'arm_up_open', desc='ยก → ปล่อย'),
    Cmd(CAT_ARM2, 'ctrl+alt+shift+f5', 'arm_down_close', desc='ลง → หนีบ'),
    Cmd(CAT_ARM2, 'ctrl+alt+shift+f6', 'arm_close_down', desc='หนีบ → ลง'),
    Cmd(CAT_ARM2, 'ctrl+alt+shift+f7', 'arm_up_close', desc='ยก → หนีบ'),
    Cmd(CAT_ARM2, 'ctrl+alt+shift+f8', 'arm_close_up', desc='หนีบ → ยก'),

    # ---------- กำหนดเอง (แก้/เพิ่มได้ตามใจ) ----------
    Cmd(CAT_CUSTOM, 'ctrl+alt+shift+0', 'ff เร็ว ผ่านแยก', raw="ff({fast}, 'p');", desc='ff ความเร็ว FAST_SPEED'),
    Cmd(CAT_CUSTOM, 'ctrl+alt+shift+9', 'ff ช้า เข้ากลาง', raw="ff({slow}, 'c');", desc='ff ความเร็ว SLOW_SPEED'),
    Cmd(CAT_CUSTOM, 'ctrl+alt+shift+8', 'delay(ms)', raw='delay({ms});', desc='หน่วงเวลา (Arduino)'),
]

# คำสั่งปรับค่า (ไม่พิมพ์ลง IDE)  id -> (hotkey, ป้าย)
PARAM_ACTIONS = [
    ('speed+', 'ctrl+alt+=', f'speed +{SPEED_STEP}'),
    ('speed-', 'ctrl+alt+-', f'speed -{SPEED_STEP}'),
    ('speed_slow', 'ctrl+alt+8', f'speed = SLOW ({SLOW_SPEED})'),
    ('speed_def', 'ctrl+alt+9', f'speed = DEFAULT ({DEFAULT_SPEED})'),
    ('speed_fast', 'ctrl+alt+0', f'speed = FAST ({FAST_SPEED})'),
    ('cm+', 'ctrl+alt+]', f'cm +{CM_STEP}'),
    ('cm-', 'ctrl+alt+[', f'cm -{CM_STEP}'),
    ('ms+', 'ctrl+alt+shift+]', f'ms +{MS_STEP}'),
    ('ms-', 'ctrl+alt+shift+[', f'ms -{MS_STEP}'),
    ('dir0', 'ctrl+alt+i', 'dir = 0   (I = บน)'),
    ('dir90', 'ctrl+alt+l', 'dir = 90  (L = ขวา)'),
    ('dir180', 'ctrl+alt+k', 'dir = 180 (K = ล่าง)'),
    ('dir270', 'ctrl+alt+j', 'dir = 270 (J = ซ้าย)'),
    ('act_p', 'ctrl+alt+p', "act = 'p' ผ่านแยก"),
    ('act_c', 'ctrl+alt+c', "act = 'c' เข้ากลาง"),
    ('act_s', 'ctrl+alt+s', "act = 's' หยุด"),
    ('act_l', 'ctrl+alt+,', "act = 'l' (, = <)"),
    ('act_r', 'ctrl+alt+.', "act = 'r' (. = >)"),
    ('act_next', 'ctrl+alt+/', 'act ตัวถัดไป'),
    ('act_prev', 'ctrl+alt+shift+/', 'act ตัวก่อนหน้า'),
    ('act_case', 'ctrl+alt+u', 'act สลับเล็ก/ใหญ่ (p↔P)'),
    ('repeat', 'ctrl+alt+r', 'พิมพ์คำสั่งล่าสุดซ้ำ (ค่าปัจจุบัน)'),
    ('pause', 'ctrl+alt+shift+p', 'หยุด/เปิด มาโครชั่วคราว'),
    ('window', 'ctrl+alt+shift+w', 'ซ่อน/แสดงหน้าต่าง'),
    ('exit', EXIT_HOTKEY, 'ปิดโปรแกรม'),
]

# ป้ายสั้นบนปุ่มแท็บ "ค่า/ระบบ" (ตารางใน README ใช้ป้ายเต็มด้านบน)
PARAM_SHORT = {
    'speed+': f'speed +{SPEED_STEP}', 'speed-': f'speed -{SPEED_STEP}',
    'speed_slow': f'SLOW {SLOW_SPEED}', 'speed_def': f'DEF {DEFAULT_SPEED}', 'speed_fast': f'FAST {FAST_SPEED}',
    'cm+': f'cm +{CM_STEP}', 'cm-': f'cm -{CM_STEP}', 'ms+': f'ms +{MS_STEP}', 'ms-': f'ms -{MS_STEP}',
    'dir0': 'dir 0', 'dir90': 'dir 90', 'dir180': 'dir 180', 'dir270': 'dir 270',
    'act_p': "'p'", 'act_c': "'c'", 'act_s': "'s'", 'act_l': "'l'", 'act_r': "'r'",
    'act_next': 'act ถัดไป', 'act_prev': 'act ก่อน', 'act_case': 'เล็ก↔ใหญ่',
    'repeat': 'พิมพ์ซ้ำ', 'pause': 'หยุดชั่วคราว', 'window': 'ซ่อนจอ', 'exit': 'ปิดโปรแกรม',
}

# รายชื่อฟังก์ชันจากชุด API ที่ต้องรองรับครบ (ใช้ใน --selftest)
REQUIRED_NAMES = [
    'ff', 'ffc', 'ffl', 'ffr', 'bb', 'bbc', 'bbl', 'bbr', 'ffcm', 'bbcm', 'fft', 'bbt',
    'spindir', 'sdg', 'turndir', 'tdg', 'turndirb', 'tdbg',
    'ffcmg', 'bbcmg', 'ffcmgs', 'bbcmgs', 'ffbg', 'bbbg',
    'spinlg', 'slg', 'spinrg', 'srg', 'turnlg', 'tlg', 'turnrg', 'trg',
    'turnlbg', 'tlbg', 'turnrbg', 'trbg',
    'arm_ready', 'arm_up', 'arm_up45', 'arm_down', 'arm_open', 'arm_close',
    'arm_open_l', 'arm_open_r', 'arm_open_down', 'arm_down_open', 'arm_open_up',
    'arm_up_open', 'arm_down_close', 'arm_close_down', 'arm_up_close', 'arm_close_up',
    'arm_big', 'arm_big_box', 'arm_big_box_up', 'arm_behihd',
    'resetAngles', 'spinl', 'spinr', 'spinl2', 'spinr2',
    'ffcmcl', 'ffcmcr', 'bbcmcl', 'bbcmcr',
    'ffdircl', 'ffdircr', 'bbdircl', 'bbdircr',
    'ffdirclg', 'ffdircrg', 'bbdirclg', 'bbdircrg',
]

# ============================================================================
# 4) แปลงข้อความคีย์ลัด -> (modifiers, virtual-key)  [อิงตำแหน่งปุ่ม ใช้ได้ทั้งแป้นไทย/อังกฤษ]
# ============================================================================
MOD_ALT, MOD_CONTROL, MOD_SHIFT, MOD_WIN, MOD_NOREPEAT = 0x1, 0x2, 0x4, 0x8, 0x4000
MOD_NAMES = {'alt': MOD_ALT, 'ctrl': MOD_CONTROL, 'control': MOD_CONTROL, 'shift': MOD_SHIFT, 'win': MOD_WIN}

VK_NAMES = {str(d): 0x30 + d for d in range(10)}
VK_NAMES.update({chr(c): c for c in range(ord('A'), ord('Z') + 1)})
VK_NAMES.update({chr(c).lower(): c for c in range(ord('A'), ord('Z') + 1)})
VK_NAMES.update({f'f{n}': 0x6F + n for n in range(1, 13)})
VK_NAMES.update({
    '-': 0xBD, '=': 0xBB, '[': 0xDB, ']': 0xDD, ';': 0xBA, "'": 0xDE,
    ',': 0xBC, '.': 0xBE, '/': 0xBF, '`': 0xC0, '\\': 0xDC,
    'space': 0x20, 'insert': 0x2D, 'home': 0x24, 'pageup': 0x21, 'pagedown': 0x22,
})


def parse_hotkey(text):
    """'ctrl+alt+shift+1' -> (mods, vk)  ('+' ตัวสุดท้ายถือเป็นปุ่ม '=' ไม่ได้ ใช้ชื่อปุ่มตรง ๆ)"""
    parts = [p.strip().lower() for p in text.split('+')]
    mods = 0
    for p in parts[:-1]:
        if p not in MOD_NAMES:
            raise ValueError(f'ไม่รู้จัก modifier "{p}" ใน "{text}"')
        mods |= MOD_NAMES[p]
    key = parts[-1]
    if key not in VK_NAMES:
        raise ValueError(f'ไม่รู้จักปุ่ม "{key}" ใน "{text}"')
    return mods, VK_NAMES[key]


def pretty_hotkey(text, short=False):
    parts = text.split('+')
    if short:
        m = ''.join({'ctrl': 'C', 'alt': 'A', 'shift': 'S', 'win': 'W'}[p] for p in parts[:-1])
        key = {'space': 'SPC'}.get(parts[-1], parts[-1].upper())
        return f'{m}+{key}'
    return '+'.join(p.capitalize() if len(p) > 1 else p.upper() for p in parts)


# ============================================================================
# 5) การ render โค้ด
# ============================================================================
def fmt_number(v):
    f = float(v)
    return str(int(f)) if f.is_integer() else ('%g' % f)


def render(cmd, p, opts):
    """p = dict(speed, cm, ms, dir, angle, act, tol) ที่ตรวจแล้ว
    opts = dict(alias, opt_act, opt_dir, opt_speed)
    act = None/'' หมายถึงปุ่ม None (ไม่ใส่ตัวอักษร), tol = None หมายถึงไม่ใส่ tol
    ถ้าคำสั่งบังคับต้องมี action แต่เลือก None จะ raise ValueError (ยกเว้น act! ที่ใช้ FORCED_ACTION)"""
    act = p.get('act') or None
    tol = p.get('tol')
    if cmd.raw:
        if '{act}' in cmd.raw and not act:
            raise ValueError(f'"{cmd.name}" ต้องมี action (เลือกปุ่มตัวอักษรแทน None)')
        if '{tol}' in cmd.raw and tol is None:
            raise ValueError(f'"{cmd.name}" ต้องมีค่า tol')
        return cmd.raw.format(
            speed=fmt_number(p['speed']), cm=fmt_number(p['cm']), ms=fmt_number(p['ms']),
            dir=fmt_number(p['dir']), angle=fmt_number(p['angle']), act=f"'{act}'" if act else '',
            tol=fmt_number(tol) if tol is not None else '',
            fast=FAST_SPEED, slow=SLOW_SPEED, default=DEFAULT_SPEED)

    name = cmd.alias if (opts.get('alias') and cmd.alias) else cmd.name
    flags = {
        'act': opts.get('opt_act', True) and bool(act),
        'dir': opts.get('opt_dir', False),
        'speed': opts.get('opt_speed', True),
        'tol': tol is not None,
    }
    toks = [(t[:-1], t[-1]) if t[-1] in '?~!' else (t, '') for t in cmd.params]
    include = []
    for base, mod in toks:
        if mod in ('', '!'):
            include.append(True)
        elif mod == '~':
            include.append(bool(act))
        else:
            include.append(flags.get(base, False))
    # positional: ถ้า optional (?) ตัวหลังถูกใส่ ตัว ? ก่อนหน้าต้องถูกใส่ด้วย
    later = False
    for i in range(len(toks) - 1, -1, -1):
        if toks[i][1] == '?':
            if later:
                include[i] = True
            if include[i]:
                later = True

    args = []
    for (base, mod), on in zip(toks, include):
        if not on:
            continue
        if base == 'act':
            a = act or (FORCED_ACTION if mod == '!' else None)
            if not a:
                if mod == '?':
                    raise ValueError(f'{name}: ติ๊ก "Gyro ใส่ dir" อยู่ จึงต้องมี action (เลือกตัวอักษรแทน None)')
                raise ValueError(f'{name} ต้องมี action (เลือกปุ่มตัวอักษรแทน None)')
            args.append(f"'{a}'")
        elif base == 'tol':
            args.append(fmt_number(tol))
        else:
            args.append(fmt_number(p[base]))
    return f"{name}({', '.join(args)});"


# ============================================================================
# 6) Win32: ส่งปุ่ม / Clipboard / หน้าต่าง
# ============================================================================
IS_WINDOWS = sys.platform == 'win32'
if IS_WINDOWS:
    user32 = ctypes.WinDLL('user32', use_last_error=True)
    kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)

    user32.RegisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int, wintypes.UINT, wintypes.UINT]
    user32.RegisterHotKey.restype = wintypes.BOOL
    user32.UnregisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int]
    user32.GetMessageW.argtypes = [ctypes.POINTER(wintypes.MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT]
    user32.GetMessageW.restype = ctypes.c_int
    user32.PostThreadMessageW.argtypes = [wintypes.DWORD, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
    user32.keybd_event.argtypes = [wintypes.BYTE, wintypes.BYTE, wintypes.DWORD, ctypes.c_size_t]
    user32.keybd_event.restype = None
    user32.MapVirtualKeyW.argtypes = [wintypes.UINT, wintypes.UINT]
    user32.MapVirtualKeyW.restype = wintypes.UINT
    user32.GetAsyncKeyState.argtypes = [ctypes.c_int]
    user32.GetAsyncKeyState.restype = ctypes.c_short
    user32.GetForegroundWindow.restype = wintypes.HWND
    user32.SetForegroundWindow.argtypes = [wintypes.HWND]
    user32.BringWindowToTop.argtypes = [wintypes.HWND]
    user32.IsWindow.argtypes = [wintypes.HWND]
    user32.IsIconic.argtypes = [wintypes.HWND]
    user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
    user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    user32.GetWindowThreadProcessId.restype = wintypes.DWORD
    user32.AttachThreadInput.argtypes = [wintypes.DWORD, wintypes.DWORD, wintypes.BOOL]
    user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    user32.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    user32.OpenClipboard.argtypes = [wintypes.HWND]
    user32.OpenClipboard.restype = wintypes.BOOL
    user32.GetClipboardData.argtypes = [wintypes.UINT]
    user32.GetClipboardData.restype = ctypes.c_void_p
    user32.SetClipboardData.argtypes = [wintypes.UINT, ctypes.c_void_p]
    user32.SetClipboardData.restype = ctypes.c_void_p
    kernel32.GlobalAlloc.argtypes = [wintypes.UINT, ctypes.c_size_t]
    kernel32.GlobalAlloc.restype = ctypes.c_void_p
    kernel32.GlobalLock.argtypes = [ctypes.c_void_p]
    kernel32.GlobalLock.restype = ctypes.c_void_p
    kernel32.GlobalUnlock.argtypes = [ctypes.c_void_p]
    kernel32.GlobalFree.argtypes = [ctypes.c_void_p]
    kernel32.GetCurrentThreadId.restype = wintypes.DWORD
    kernel32.GetConsoleWindow.restype = wintypes.HWND

WM_HOTKEY, WM_QUIT = 0x0312, 0x0012
KEYEVENTF_EXTENDEDKEY, KEYEVENTF_KEYUP = 0x1, 0x2
VK_SHIFT, VK_CONTROL, VK_MENU, VK_LWIN, VK_RWIN = 0x10, 0x11, 0x12, 0x5B, 0x5C
VK_END, VK_RETURN, VK_V, VK_MASK = 0x23, 0x0D, 0x56, 0xE8  # 0xE8 = ปุ่มว่าง ใช้กันเมนู Alt/สลับภาษา
EXTENDED_VKS = {VK_END, 0x24, 0x21, 0x22, 0x25, 0x26, 0x27, 0x28, 0x2D, 0x2E}
IGNORED_TARGET_CLASSES = {'Shell_TrayWnd', 'Shell_SecondaryTrayWnd', 'Progman', 'WorkerW',
                          'ConsoleWindowClass', 'CASCADIA_HOSTING_WINDOW_CLASS',
                          # หน้าต่างของ Windows เอง (thumbnail ทาสก์บาร์, Start, Alt+Tab, ถาด icon)
                          'XamlExplorerHostIslandWindow', 'Windows.UI.Core.CoreWindow', 'TaskListThumbnailWnd',
                          'MultitaskingViewFrame', 'ForegroundStaging', 'NotifyIconOverflowWindow',
                          'TopLevelWindowForOverflowXamlIsland', 'Shell_InputSwitchTopLevelWindow'}


def key_down(vk):
    flags = KEYEVENTF_EXTENDEDKEY if vk in EXTENDED_VKS else 0
    user32.keybd_event(vk, user32.MapVirtualKeyW(vk, 0) & 0xFF, flags, 0)


def key_up(vk):
    flags = (KEYEVENTF_EXTENDEDKEY if vk in EXTENDED_VKS else 0) | KEYEVENTF_KEYUP
    user32.keybd_event(vk, user32.MapVirtualKeyW(vk, 0) & 0xFF, flags, 0)


def tap(vk, *mods):
    pressed = []
    try:
        for m in mods:
            key_down(m)
            pressed.append(m)
            time.sleep(KEY_GAP / 2)
        key_down(vk)
        key_up(vk)
    finally:   # ปล่อย modifier เสมอ แม้เกิด exception กลางทาง (กัน Ctrl ค้าง)
        for m in reversed(pressed):
            time.sleep(KEY_GAP / 2)
            key_up(m)
    time.sleep(KEY_GAP)


def modifiers_down():
    return any(user32.GetAsyncKeyState(vk) & 0x8000 for vk in (VK_SHIFT, VK_CONTROL, VK_MENU, VK_LWIN, VK_RWIN))


def wait_modifiers_released(timeout):
    end = time.time() + timeout
    while modifiers_down():
        if time.time() > end:
            return False
        time.sleep(0.01)
    time.sleep(0.03)
    return True


def window_title(hwnd):
    buf = ctypes.create_unicode_buffer(256)
    user32.GetWindowTextW(hwnd, buf, 256)
    return buf.value


def window_class(hwnd):
    buf = ctypes.create_unicode_buffer(256)
    user32.GetClassNameW(hwnd, buf, 256)
    return buf.value


def window_pid(hwnd):
    pid = wintypes.DWORD(0)
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return pid.value


def is_own_window(hwnd):
    return bool(hwnd) and window_pid(hwnd) == os.getpid()


def is_valid_target(hwnd):
    if not hwnd or not user32.IsWindow(hwnd) or is_own_window(hwnd):
        return False
    if hwnd == kernel32.GetConsoleWindow():
        return False
    return window_class(hwnd) not in IGNORED_TARGET_CLASSES


def focus_window(hwnd):
    if user32.IsIconic(hwnd):
        user32.ShowWindow(hwnd, 9)  # SW_RESTORE
    user32.SetForegroundWindow(hwnd)
    for _ in range(25):
        if user32.GetForegroundWindow() == hwnd:
            return True
        time.sleep(0.01)
    # วิธีสำรอง: ผูก input thread ชั่วคราวแล้วสั่งอีกครั้ง
    fg = user32.GetForegroundWindow()
    cur = kernel32.GetCurrentThreadId()
    fg_thread = user32.GetWindowThreadProcessId(fg, None) if fg else 0
    attached = bool(fg_thread and fg_thread != cur and user32.AttachThreadInput(cur, fg_thread, True))
    try:
        user32.BringWindowToTop(hwnd)
        user32.SetForegroundWindow(hwnd)
    finally:   # ถอด input thread เสมอ ไม่งั้นคีย์บอร์ด/เมาส์ของ 2 thread จะผูกกันค้าง
        if attached:
            user32.AttachThreadInput(cur, fg_thread, False)
    for _ in range(25):
        if user32.GetForegroundWindow() == hwnd:
            return True
        time.sleep(0.01)
    return False


# ---- Clipboard: ใช้ pyperclip ถ้ามี ไม่มีก็ใช้ Win32 API ตรง ----
CF_UNICODETEXT, GMEM_MOVEABLE = 13, 0x0002
try:
    import pyperclip  # noqa: E402
except Exception:  # pragma: no cover
    pyperclip = None


def _open_clipboard():
    for _ in range(50):
        if user32.OpenClipboard(None):
            return True
        time.sleep(0.01)
    return False


def _win_clip_get():
    if not _open_clipboard():
        raise RuntimeError('เปิด Clipboard ไม่ได้ (โปรแกรมอื่นใช้อยู่)')
    try:
        h = user32.GetClipboardData(CF_UNICODETEXT)
        if not h:
            return ''
        ptr = kernel32.GlobalLock(h)
        if not ptr:
            return ''
        try:
            return ctypes.wstring_at(ptr)
        finally:
            kernel32.GlobalUnlock(h)
    finally:
        user32.CloseClipboard()


def _win_clip_set(text):
    data = text.encode('utf-16-le') + b'\x00\x00'
    h = kernel32.GlobalAlloc(GMEM_MOVEABLE, len(data))
    if not h:
        raise RuntimeError('GlobalAlloc ล้มเหลว')
    ptr = kernel32.GlobalLock(h)
    ctypes.memmove(ptr, data, len(data))
    kernel32.GlobalUnlock(h)
    if not _open_clipboard():
        kernel32.GlobalFree(h)
        raise RuntimeError('เปิด Clipboard ไม่ได้ (โปรแกรมอื่นใช้อยู่)')
    try:
        user32.EmptyClipboard()
        if not user32.SetClipboardData(CF_UNICODETEXT, h):
            kernel32.GlobalFree(h)
            raise RuntimeError('SetClipboardData ล้มเหลว')
    finally:
        user32.CloseClipboard()


def clip_get():
    try:
        return pyperclip.paste() if pyperclip else _win_clip_get()
    except Exception:
        return None


def clip_set(text):
    if pyperclip:
        pyperclip.copy(text)
    else:
        _win_clip_set(text)


# ============================================================================
# 7) ตัวพิมพ์ (worker thread) — ทำงานทีละงานตามคิว
# ============================================================================
class Typer(threading.Thread):
    def __init__(self, ui_queue):
        super().__init__(daemon=True)
        self.jobs = queue.Queue()
        self.ui_queue = ui_queue
        self.last_target = None   # hwnd หน้าต่าง IDE ล่าสุด (main thread อัปเดต)
        self._clip_lock = threading.Lock()
        self._clip_gen = 0        # เพิ่มทุกครั้งที่เราตั้ง Clipboard
        self._clip_saved = None   # Clipboard เดิมของผู้ใช้ที่รอคืน (None = ไม่มีงานค้าง)

    def submit(self, text, opts):
        self.jobs.put((text, opts))

    def stop(self):
        self.jobs.put(None)

    def status(self, msg, ok=True):
        self.ui_queue.put(('status', msg, ok))

    def run(self):
        while True:
            job = self.jobs.get()
            if job is None:
                return
            text, opts = job
            try:
                self.type_text(text, opts)
            except Exception as exc:  # ไม่ให้ thread ตาย
                self.status(f'พิมพ์ไม่สำเร็จ: {exc}', ok=False)

    def type_text(self, text, opts):
        if not wait_modifiers_released(MODIFIER_RELEASE_TIMEOUT):
            self.status('ยกเลิก: ยังกด Ctrl/Alt/Shift ค้างอยู่ — ปล่อยปุ่มแล้วกดใหม่', ok=False)
            return
        fg = user32.GetForegroundWindow()
        if not is_valid_target(fg):
            target = self.last_target
            if not target or not user32.IsWindow(target):
                self.status('ยังไม่รู้ว่าจะพิมพ์ลงหน้าต่างไหน — คลิกที่ IDE ก่อน 1 ครั้ง', ok=False)
                return
            if not focus_window(target):
                self.status('สลับไปหน้าต่าง IDE ไม่ได้ — คลิกที่ IDE แล้วใช้คีย์ลัดแทน', ok=False)
                return
            time.sleep(FOCUS_DELAY)
            # ยืนยันอีกครั้งก่อนกดคีย์: ถ้า Focus เด้งกลับมาหน้าต่างโพย (เช่น Windows บล็อก/คลิกค้าง)
            # ลองสลับอีกรอบ — ถ้ายังไม่ได้ ห้ามกด Ctrl+V/Enter เด็ดขาด (ไม่งั้นจะไปลงช่อง speed/cm ของเราเอง)
            if user32.GetForegroundWindow() != target:
                if not focus_window(target):
                    self.status('สลับไปหน้าต่าง IDE ไม่ทัน — กดปุ่มอีกครั้ง', ok=False)
                    return
                time.sleep(FOCUS_DELAY)

        if opts['end']:
            tap(VK_END)

        if opts['method'] == 'unicode':
            import keyboard  # ใช้เฉพาะโหมด unicode
            keyboard.write(text, delay=0.003, exact=True)
            time.sleep(PASTE_SETTLE)
        else:
            with self._clip_lock:
                # เก็บ Clipboard เดิมเฉพาะตอนที่ไม่มีงานคืนค่าค้างอยู่ (กดรัวหลายคำสั่ง -> ของเดิมจริงไม่หาย)
                if RESTORE_CLIPBOARD and self._clip_saved is None:
                    self._clip_saved = clip_get() or ''
                clip_set(text)
                self._clip_gen += 1
                gen = self._clip_gen
            time.sleep(0.03)
            tap(VK_V, VK_CONTROL)
            time.sleep(PASTE_SETTLE)
            if RESTORE_CLIPBOARD:
                threading.Timer(CLIPBOARD_RESTORE_DELAY, self._restore_clip, args=(gen, text)).start()

        if opts['enter']:
            tap(VK_RETURN)
        self.status(f'✓ {text}')

    def _restore_clip(self, gen, ours):
        with self._clip_lock:
            if gen != self._clip_gen:   # มีงานใหม่ตั้ง Clipboard ต่อแล้ว -> ให้งานล่าสุดเป็นคนคืน
                return
            old, self._clip_saved = self._clip_saved, None
            try:
                if old and clip_get() == ours:   # ถ้าผู้ใช้ copy อย่างอื่นไปแล้วจะไม่ทับ
                    clip_set(old)
            except Exception:
                pass


# ============================================================================
# 8) Hotkey thread (Win32 RegisterHotKey + message loop)
# ============================================================================
class HotkeyThread(threading.Thread):
    def __init__(self, bindings, ui_queue):
        """bindings: list ของ (hotkey_text, action_id)"""
        super().__init__(daemon=True)
        self.bindings = bindings
        self.ui_queue = ui_queue
        self.thread_id = None
        self.ready = threading.Event()
        self.failed = []

    def run(self):
        self.thread_id = kernel32.GetCurrentThreadId()
        id_map = {}
        for i, (hk, action) in enumerate(self.bindings, start=1):
            mods, vk = parse_hotkey(hk)
            if user32.RegisterHotKey(None, i, mods | MOD_NOREPEAT, vk):
                id_map[i] = (action, mods)
            else:
                self.failed.append(hk)
        self.ready.set()
        msg = wintypes.MSG()
        try:
            while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
                if msg.message == WM_HOTKEY and msg.wParam in id_map:
                    action, mods = id_map[msg.wParam]
                    # กด "ปุ่มว่าง" คั่น ขณะที่ผู้ใช้ยังกด modifier อยู่
                    # -> กัน Alt เปิดเมนูของ IDE และกัน Alt+Shift / Ctrl+Shift สลับภาษา
                    user32.keybd_event(VK_MASK, 0, 0, 0)
                    user32.keybd_event(VK_MASK, 0, KEYEVENTF_KEYUP, 0)
                    self.ui_queue.put(('hotkey', action))
        finally:
            for i in id_map:
                user32.UnregisterHotKey(None, i)

    def stop(self):
        if self.thread_id:
            user32.PostThreadMessageW(self.thread_id, WM_QUIT, 0, 0)


# ============================================================================
# 9) หน้าต่าง GUI (Always-on-Top)
# ============================================================================
def build_app(start_hotkeys=True):
    import tkinter as tk
    import tkinter.font as tkfont
    from tkinter import ttk

    class App:
        def __init__(self):
            self.ui_queue = queue.Queue()
            self.root = tk.Tk()
            self.root.title('Robot Macro')
            self.root.attributes('-topmost', ALWAYS_ON_TOP)
            try:
                self.root.attributes('-alpha', WINDOW_ALPHA)
            except tk.TclError:
                pass
            self.root.protocol('WM_DELETE_WINDOW', self.quit)
            self.cmds = {c.id: c for c in MACROS}
            self.last_cmd_id = None
            self.paused = tk.BooleanVar(value=False)
            self.typer = Typer(self.ui_queue)
            self.hotkeys = None

            # --- ตัวแปรค่าพารามิเตอร์ (StringVar เพื่อให้พิมพ์แก้ได้อิสระ) ---
            self.v_speed = tk.StringVar(value=str(DEFAULT_SPEED))
            self.v_cm = tk.StringVar(value=str(DEFAULT_CM))
            self.v_ms = tk.StringVar(value=str(DEFAULT_MS))
            self.v_dir = tk.StringVar(value=str(DEFAULT_DIR))
            self.v_angle = tk.StringVar(value=str(DEFAULT_ANGLE))
            self.v_act = tk.StringVar(value=DEFAULT_ACTION)
            self.v_tol = tk.StringVar(value='' if DEFAULT_TOL is None else str(DEFAULT_TOL))   # '' = ไม่ใส่
            self.v_tolinfo = tk.StringVar(value='')
            self.v_opt_speed = tk.BooleanVar(value=OPT_SPEED_INCLUDE)
            self.v_end = tk.BooleanVar(value=PRESS_END_BEFORE)
            self.v_enter = tk.BooleanVar(value=PRESS_ENTER_AFTER)
            self.v_alias = tk.BooleanVar(value=USE_SHORT_ALIAS)
            self.v_opt_act = tk.BooleanVar(value=GYRO_INCLUDE_ACT)
            self.v_opt_dir = tk.BooleanVar(value=GYRO_INCLUDE_DIR)
            self.v_top = tk.BooleanVar(value=ALWAYS_ON_TOP)
            self.v_compact = tk.BooleanVar(value=False)
            self.v_status = tk.StringVar(value='พร้อม — คลิกที่ IDE แล้วกดคีย์ลัดได้เลย')
            self.v_preview = tk.StringVar(value='')
            self.v_target = tk.StringVar(value='เป้าหมาย: -')
            self.v_actinfo = tk.StringVar(value='')
            self._hover_job = None      # after() id ของพรีวิวตอนชี้ปุ่ม (debounce)

            self._build_ui()
            self.v_act.trace_add('write', lambda *a: self._on_act_change())
            self.v_alias.trace_add('write', lambda *a: self._refresh_button_labels())
            # Live Preview อัปเดตทันทีเมื่อเปลี่ยนค่าใดก็ได้
            for var in (self.v_speed, self.v_cm, self.v_ms, self.v_dir, self.v_angle, self.v_tol,
                        self.v_alias, self.v_opt_act, self.v_opt_dir, self.v_opt_speed):
                var.trace_add('write', lambda *a: self._live_preview())
            self.v_tol.trace_add('write', lambda *a: self._update_tolinfo())
            self._update_tolinfo()
            self._on_act_change()

            self.typer.start()
            if start_hotkeys:
                self._start_hotkeys()
            self.root.after(30, self._poll_queue)
            self.root.after(200, self._poll_foreground)

        # ------------------------------------------------------------ UI
        def _build_ui(self):
            root = self.root
            style = ttk.Style(root)
            style.configure('TButton', font=UI_FONT, padding=(2, 1))
            style.configure('Code.TButton', font=('Consolas', 9), padding=(2, 1))
            style.configure('Small.TButton', font=UI_FONT, padding=(0, 0), width=5)
            style.configure('Left.TButton', font=UI_FONT, padding=(4, 0), anchor='w')
            style.configure('TLabel', font=UI_FONT)
            style.configure('TCheckbutton', font=UI_FONT)
            style.configure('Status.TLabel', font=('Segoe UI', 10))
            style.configure('Preview.TLabel', font=CODE_FONT)

            outer = ttk.Frame(root, padding=6)
            outer.pack(fill='both', expand=True)

            # ---- แถวบน: สถานะ ----
            top = ttk.Frame(outer)
            top.pack(fill='x')
            self.lbl_mode = tk.Label(top, text=' ON ', bg='#1f9d55', fg='white', font=('Segoe UI', 9, 'bold'))
            self.lbl_mode.pack(side='left')
            # ปุ่มเด่น resetAngles (ใช้บ่อยตอนตั้งลำ/เช็กพอยต์)
            tk.Button(top, text='⟲ resetAngles()   C+A+O', bg='#0f766e', fg='white',
                      activebackground='#115e59', activeforeground='white', relief='flat', bd=0,
                      font=('Segoe UI', 9, 'bold'), padx=8, cursor='hand2', takefocus=0,
                      command=lambda: self.run_cmd('cmd:ctrl+alt+o', from_button=True)).pack(side='left', padx=(6, 0))
            # width คงที่: ชื่อหน้าต่าง IDE ยาว/สั้นไม่ทำให้หน้าต่างโพยยืด-หด (ซึ่งทำให้แท็บจัดวางใหม่)
            ttk.Label(top, textvariable=self.v_target, foreground='#555',
                      width=TARGET_LABEL_CHARS).pack(side='left', padx=6)
            ttk.Checkbutton(top, text='ย่อ', variable=self.v_compact, command=self._toggle_compact,
                            takefocus=0).pack(side='right')
            ttk.Checkbutton(top, text='บนสุด', variable=self.v_top, takefocus=0,
                            command=lambda: self.root.attributes('-topmost', self.v_top.get())).pack(side='right')

            # ---- ค่าพารามิเตอร์ ----
            pf = ttk.LabelFrame(outer, text=' ค่าที่ใช้พิมพ์ (แก้สด ๆ ได้) ', padding=4)
            pf.pack(fill='x', pady=(4, 2))

            def spin_row(row, label, var, lo, hi, step, presets=()):
                ttk.Label(pf, text=label, width=7).grid(row=row, column=0, sticky='w')
                sb = ttk.Spinbox(pf, textvariable=var, from_=lo, to=hi, increment=step, width=7, font=CODE_FONT)
                sb.grid(row=row, column=1, sticky='w', padx=2)
                col = 2
                for text, value in presets:
                    ttk.Button(pf, text=text, style='Small.TButton', takefocus=0,
                               command=lambda v=value: var.set(str(v))).grid(row=row, column=col, padx=1)
                    col += 1

            spin_row(0, 'speed', self.v_speed, SPEED_MIN, SPEED_MAX, SPEED_STEP,
                     [(str(SLOW_SPEED), SLOW_SPEED), (str(DEFAULT_SPEED), DEFAULT_SPEED), (str(FAST_SPEED), FAST_SPEED), ('100', 100)])
            spin_row(1, 'cm', self.v_cm, 0, 500, CM_STEP, [('5', 5), ('10', 10), ('20', 20), ('30', 30)])
            spin_row(2, 'ms', self.v_ms, 0, 10000, MS_STEP, [('100', 100), ('300', 300), ('500', 500), ('1000', 1000)])
            spin_row(3, 'angle', self.v_angle, -360, 360, ANGLE_STEP, [('45', 45), ('90', 90), ('135', 135), ('180', 180)])

            ttk.Label(pf, text='dir', width=7).grid(row=4, column=0, sticky='w')
            ttk.Combobox(pf, textvariable=self.v_dir, values=[str(d) for d in DIR_CHOICES], width=6,
                         font=CODE_FONT).grid(row=4, column=1, sticky='w', padx=2)
            for col, (txt, d) in enumerate([('↑0', 0), ('→90', 90), ('↓180', 180), ('←270', 270)], start=2):
                ttk.Button(pf, text=txt, style='Small.TButton', takefocus=0,
                           command=lambda v=d: self.v_dir.set(str(v))).grid(row=4, column=col, padx=1)

            # ---- tol (tolerance) อยู่คอลัมน์ขวา ไม่เพิ่มความสูงหน้าต่าง ----
            ttk.Separator(pf, orient='vertical').grid(row=0, column=6, rowspan=5, sticky='ns', padx=8)
            ttk.Label(pf, text='tol').grid(row=0, column=7, sticky='w')
            ttk.Spinbox(pf, textvariable=self.v_tol, from_=0, to=45, increment=1, width=4,
                        font=CODE_FONT).grid(row=0, column=8, sticky='w', padx=2)
            for i, v in enumerate(TOL_PRESETS):
                r, c = 1 + i // 2, 7 + i % 2
                ttk.Button(pf, text='ไม่ใส่' if v is None else str(v), style='Small.TButton', takefocus=0,
                           command=lambda val=v: self.v_tol.set('' if val is None else str(val))).grid(
                    row=r, column=c, padx=1, pady=0, sticky='ew')
            self.lbl_tolinfo = ttk.Label(pf, textvariable=self.v_tolinfo, font=('Consolas', 9))
            self.lbl_tolinfo.grid(row=4, column=7, columnspan=2, sticky='w')

            # ---- ตัวเลือก ----
            of = ttk.Frame(outer)
            of.pack(fill='x', pady=(2, 2))
            for text, var in [('End ก่อน', self.v_end), ('Enter หลัง', self.v_enter), ('ชื่อย่อ', self.v_alias),
                              ('ใส่ speed (opt.)', self.v_opt_speed),
                              ('Gyro ใส่ act', self.v_opt_act), ('Gyro ใส่ dir', self.v_opt_dir)]:
                ttk.Checkbutton(of, text=text, variable=var, takefocus=0).pack(side='left', padx=(0, 3))

            # ---- Action Pad (ปุ่มใหญ่ครบ 22 ตัว + None) ----
            self._build_action_pad(outer)

            # ---- พรีวิว + สถานะ: กรอบความสูงคงที่ (Zero Layout Shift) ----
            # เดิม label ตัดบรรทัดด้วย wraplength -> ข้อความตอนชี้ปุ่ม (1 บรรทัด) กับตอนออก (2 บรรทัด)
            # สูงไม่เท่ากัน แท็บด้านล่างจึงเด้งขึ้น-ลงหนีเมาส์ เกิด <Leave>/<Enter> วนไม่จบ และคลิกหลุด
            # ตอนนี้: กรอบ pack_propagate(False) สูงตายตัว + พรีวิวบรรทัดเดียว (ไม่ wrap)
            code_line = tkfont.Font(root, font=CODE_FONT).metrics('linespace')
            status_line = tkfont.Font(root, font=STATUS_FONT).metrics('linespace')
            self.info_box = ttk.Frame(outer, height=code_line + 2 + status_line * STATUS_LINES + 6)
            self.info_box.pack(fill='x', pady=(0, 4))
            self.info_box.pack_propagate(False)
            self.lbl_preview = ttk.Label(self.info_box, textvariable=self.v_preview, style='Preview.TLabel',
                                         foreground='#6b46c1', anchor='w')
            self.lbl_preview.pack(side='top', fill='x')
            self.lbl_status = ttk.Label(self.info_box, textvariable=self.v_status, style='Status.TLabel',
                                        foreground='#1f7a3a', justify='left', anchor='nw')
            self.lbl_status.pack(side='top', fill='both', expand=True)
            # wraplength ตามความกว้างจริงของกรอบ (ไม่กระทบความสูง เพราะกรอบล็อกไว้แล้ว)
            self.info_box.bind('<Configure>', self._fit_status_wrap)

            # ---- แท็บปุ่มคำสั่ง (เป็นโพยคีย์ลัดไปในตัว) ----
            self.nb = ttk.Notebook(outer)
            self.nb.pack(fill='both', expand=True)
            self.cmd_buttons = []
            tabs = [
                ('เส้น/ระยะ', [CAT_LINE, CAT_DIST, CAT_SPIN_LINE]),
                ('โค้ง/Dir', [CAT_CURVE_CM, CAT_DIR_LINE, CAT_DIR_G]),
                ('Gyro', [CAT_GYRO, CAT_TURN]),
                ('แขนกล', [CAT_ARM, CAT_ARM2]),
                ('ค่า/ระบบ', None),
                ('กำหนดเอง', [CAT_CUSTOM]),
            ]
            for tab_name, cats in tabs:
                frame = ttk.Frame(self.nb, padding=4)
                self.nb.add(frame, text=tab_name)
                if cats is None:
                    self._build_param_tab(frame)
                else:
                    self._build_cmd_tab(frame, cats)

            ttk.Label(outer, text=f'{pretty_hotkey(EXIT_HOTKEY)} = ปิดโปรแกรม   •   '
                                  'กดปุ่มบนจอ = พิมพ์ลง IDE ล่าสุด', foreground='#777').pack(fill='x', pady=(4, 0))
            self.compact_parts = [self.nb]

            sw, sh = root.winfo_screenwidth(), root.winfo_screenheight()
            root.update_idletasks()
            if root.winfo_reqheight() > sh - 80:     # จอเตี้ย (1366x768 / สเกล 150%) -> เริ่มแบบย่อ
                self.v_compact.set(True)
                self._toggle_compact()
                root.update_idletasks()
            w = max(root.winfo_reqwidth(), 400)
            root.geometry(f'+{max(sw - w - 20, 0)}+10')

        def _build_cmd_tab(self, frame, cats):
            row = 0
            for n, cat in enumerate(cats):
                if n:   # เส้นคั่นหมวด (ชื่อแท็บบอกหมวดอยู่แล้ว ประหยัดความสูงจอ)
                    ttk.Separator(frame).grid(row=row, column=0, columnspan=4, sticky='ew', pady=3)
                    row += 1
                if CAT_DIR_G in cats:   # แท็บโค้ง/Dir: ใส่ชื่อหมวดตัวเล็ก แยก "จบโหมดเส้น" กับ "จบ *g" ให้ชัด
                    ttk.Label(frame, text=cat, foreground='#666', font=('Segoe UI', 8)).grid(
                        row=row, column=0, columnspan=4, sticky='w')
                    row += 1
                col = 0
                for c in [m for m in MACROS if m.cat == cat]:
                    b = ttk.Button(frame, style='Code.TButton', takefocus=0, width=-16,
                                   command=lambda cid=c.id: self.run_cmd(cid, from_button=True))
                    b.grid(row=row, column=col, padx=1, pady=1, sticky='ew')
                    # add='+' และไม่คืน 'break' -> ไม่แตะ class binding ของปุ่ม (คลิกทำงานปกติ)
                    b.bind('<Enter>', lambda e, cid=c.id: self._schedule_hover(cid), add='+')
                    b.bind('<Leave>', lambda e: self._schedule_hover(None), add='+')
                    self.cmd_buttons.append((b, c))
                    col += 1
                    if col == 4:
                        col, row = 0, row + 1
                if col:
                    row += 1
            for i in range(4):
                frame.columnconfigure(i, weight=1)
            self._refresh_button_labels()

        def _build_param_tab(self, frame):
            cols = 5
            ttk.Label(frame, text='คีย์ด้านล่างกดพร้อม Ctrl+Alt (S+ = เติม Shift)', foreground='#777').grid(
                row=0, column=0, columnspan=cols, sticky='w')
            for i, (aid, hk, label) in enumerate(PARAM_ACTIONS):
                r, c = divmod(i, cols)
                if hk.startswith('ctrl+alt+'):
                    key = pretty_hotkey(hk[len('ctrl+alt+'):], short=True).lstrip('+')
                else:
                    key = pretty_hotkey(hk, short=True)   # เช่น CS+Q = Ctrl+Shift+Q (ไม่ใช่ชุด Ctrl+Alt)
                ttk.Button(frame, text=f'{key}  {PARAM_SHORT.get(aid, label)}',
                           takefocus=0, style='Left.TButton',
                           command=lambda a=aid: self.run_param(a)).grid(row=r + 1, column=c, padx=1, pady=0, sticky='ew')
            for c in range(cols):
                frame.columnconfigure(c, weight=1)

        # ------------------------------------------------------ Action Pad
        def _build_action_pad(self, parent):
            box = ttk.LabelFrame(parent, text=' Action Character — คลิกเลือก (ตัวเล็ก/ใหญ่ คนละปุ่ม) ', padding=4)
            box.pack(fill='x', pady=(2, 2))
            grid = tk.Frame(box)
            grid.pack(fill='x')
            self.act_tiles = {}
            for r, (gname, light, strong, chars) in enumerate(ACTION_GROUPS):
                tk.Label(grid, text=gname, fg=strong, font=('Segoe UI', 8, 'bold'), anchor='w',
                         width=8).grid(row=r, column=0, sticky='w')
                for c, ch in enumerate(chars):
                    self._make_tile(grid, ch).grid(row=r, column=c + 1, padx=2, pady=1, sticky='nsew')
            # None อยู่แถวแรก (กลุ่มหยุด มี 4 ปุ่ม จึงเหลือที่ 2 ช่องขวา)
            self._make_tile(grid, ACT_NONE).grid(row=0, column=5, columnspan=2, padx=2, pady=1, sticky='nsew')
            for c in range(1, 7):
                grid.columnconfigure(c, weight=1, uniform='tile')

            # คำอธิบายเต็มของตัวที่เลือก (ff/bb เทียบ Gyro)
            # height=2 (บรรทัด) คงที่: เปลี่ยนตัวอักษร/None แล้วกล่องไม่สูง-เตี้ยลง
            self.lbl_actdesc = tk.Label(box, textvariable=self.v_actinfo, font=('Segoe UI', 9), anchor='w',
                                        justify='left', wraplength=self._px(460), padx=6, pady=3, height=2)
            self.lbl_actdesc.pack(fill='x', pady=(4, 0))

        def _make_tile(self, parent, ch):
            light, strong = ACTION_COLOR[ch]
            tile = tk.Frame(parent, bg=light, highlightthickness=2, highlightbackground=strong,
                            highlightcolor=strong, cursor='hand2')
            big = tk.Label(tile, text=ch if ch else 'None', font=ACTION_FONT if ch else ('Segoe UI', 13, 'bold'),
                           bg=light, fg=strong)
            small = tk.Label(tile, text=ACTION_SHORT[ch], font=ACTION_SUB_FONT, bg=light, fg='#333333')
            big.pack(pady=0)
            small.pack(pady=(0, 1))
            for w in (tile, big, small):
                w.bind('<Button-1>', lambda e, v=ch: self.v_act.set(v))
            self.act_tiles[ch] = (tile, big, small, light, strong)
            return tile

        def _refresh_action_pad(self):
            cur = self.v_act.get()
            for ch, (tile, big, small, light, strong) in self.act_tiles.items():
                if ch == cur:   # ตัวที่เลือก: พื้นสีเข้ม ตัวหนังสือขาว ขอบดำ
                    tile.configure(bg=strong, highlightbackground='#111111', highlightcolor='#111111')
                    big.configure(bg=strong, fg='white')
                    small.configure(bg=strong, fg='white')
                else:
                    tile.configure(bg=light, highlightbackground=strong, highlightcolor=strong)
                    big.configure(bg=light, fg=strong)
                    small.configure(bg=light, fg='#333333')

        def _refresh_button_labels(self):
            short = self.v_alias.get()
            for b, c in self.cmd_buttons:
                label = c.label(short)
                if c.cat in (CAT_ARM, CAT_ARM2):      # แท็บแขนกล: ตัด arm_ ให้ปุ่มไม่ล้นจอ (พิมพ์จริงยังเป็นชื่อเต็ม)
                    label = label[len('arm_'):] if label.startswith('arm_') else label
                b.configure(text=f'{label}  {pretty_hotkey(c.hotkey, short=True)}')

        def _toggle_compact(self):
            for w in self.compact_parts:
                if self.v_compact.get():
                    w.pack_forget()
                else:
                    w.pack(fill='both', expand=True, after=self.info_box)

        def _update_actinfo(self):
            ch = self.v_act.get()
            light, strong = ACTION_COLOR.get(ch, ACTION_NONE_COLORS)
            if ch == ACT_NONE:
                text = ('None — ไม่ใส่ตัวอักษร: ใช้กับ ffcmg / bbcmg / ffcmgs / bbcmgs\n'
                        'คำสั่งที่บังคับมี action (ff, bb, ffbg ...) จะไม่พิมพ์ และขึ้นเตือน')
            else:
                line, gyro = ACTION_INFO[ch]
                text = (f"'{ch}'  เดินตามเส้น (ff / bb):  {line}\n"
                        f"'{ch}'  Gyro (*g / *gb):  {gyro}")
            self.v_actinfo.set(text)
            self.lbl_actdesc.configure(bg=light, fg=strong)

        def _update_tolinfo(self):
            t = self.v_tol.get().strip()
            self.v_tolinfo.set('= None' if t in ('', 'None', 'none') else f'= {t}')

        def _on_act_change(self):
            self._refresh_action_pad()
            self._update_actinfo()
            self._live_preview()

        def _live_preview(self):
            """บรรทัดตัวอย่างสด: ff + ffcmg (เทียบโหมดเส้น/Gyro) + คำสั่งล่าสุด"""
            p, errors = self.read_params()
            if errors:
                self._set_preview('⚠ ' + ', '.join(errors))
                return
            ids =['cmd:ctrl+alt+1', 'cmd:ctrl+alt+;']    # ff (เส้น) + ffdircl (ลำดับ act/dir/tol)
            if self.last_cmd_id and self.last_cmd_id not in ids:
                ids.append(self.last_cmd_id)
            parts = []
            for cid in ids:
                try:
                    parts.append(render(self.cmds[cid], p, self.opts()))
                except ValueError:
                    parts.append(f'{self.cmds[cid].label(self.v_alias.get())}(✗ ต้องมี action)')
            self._set_preview('ตัวอย่าง →  ' + '   '.join(parts))

        # ------------------------------------------------------ พรีวิวตอนชี้ปุ่ม (debounce + ไม่ set ซ้ำ)
        def _px(self, px96):
            """แปลงพิกเซลที่ออกแบบไว้ที่ 96 DPI -> พิกเซลจริงตามสเกลจอ (125% / 150%)"""
            try:
                return int(px96 * self.root.winfo_fpixels('1i') / 96.0)
            except tk.TclError:
                return px96

        def _set_preview(self, text):
            if self.v_preview.get() != text:     # ข้อความเหมือนเดิมเป๊ะ -> ไม่สั่งวาดซ้ำ
                self.v_preview.set(text)

        def _schedule_hover(self, cid):
            """<Enter> (cid) / <Leave> (None): รวบเหตุการณ์ที่เกิดติดกันภายใน HOVER_DEBOUNCE_MS ให้เหลือครั้งเดียว
            เช่นเลื่อนจากปุ่ม A ไป B: Leave(A) + Enter(B) -> แสดงพรีวิว B ทีเดียว ไม่กระพริบกลับไปตัวอย่างรวม"""
            if self._hover_job is not None:
                try:
                    self.root.after_cancel(self._hover_job)
                except tk.TclError:
                    pass
            self._hover_job = self.root.after(HOVER_DEBOUNCE_MS, self._apply_hover, cid)

        def _apply_hover(self, cid):
            self._hover_job = None
            if cid is None:
                self._live_preview()
            else:
                self._show_preview(cid)

        def _fit_status_wrap(self, event):
            wrap = max(event.width - 8, 100)
            if int(str(self.lbl_status.cget('wraplength') or 0)) != wrap:
                self.lbl_status.configure(wraplength=wrap)

        # ------------------------------------------------------ ค่า/ตรวจสอบ
        def read_params(self):
            errors = []

            def num(var, name, cast=float, lo=None, hi=None):
                try:
                    v = cast(float(var.get().strip()))
                except ValueError:
                    errors.append(f'{name} ไม่ใช่ตัวเลข')
                    return 0
                if (lo is not None and v < lo) or (hi is not None and v > hi):
                    errors.append(f'{name} ต้องอยู่ช่วง {lo}..{hi}')
                return v

            p = {
                'speed': num(self.v_speed, 'speed', int, SPEED_MIN, SPEED_MAX),
                'cm': num(self.v_cm, 'cm', float, 0),
                'ms': num(self.v_ms, 'ms', int, 0),
                'dir': num(self.v_dir, 'dir', int, -360, 360),
                'angle': num(self.v_angle, 'angle', int, -360, 360),
            }
            act = self.v_act.get()
            if act != ACT_NONE and act not in ACTION_INFO:
                errors.append(f'action "{act}" ไม่อยู่ในตาราง')
            p['act'] = act or None          # None = ปุ่ม None (ไม่ใส่ตัวอักษร)
            tol = self.v_tol.get().strip()
            if tol in ('', 'None', 'none'):
                p['tol'] = None              # ไม่ใส่ tol
            else:
                try:
                    p['tol'] = float(tol)
                    if p['tol'] < 0:
                        errors.append('tol ต้องไม่ติดลบ')
                except ValueError:
                    errors.append('tol ไม่ใช่ตัวเลข')
                    p['tol'] = None
            return p, errors

        def opts(self):
            return {'alias': self.v_alias.get(), 'opt_act': self.v_opt_act.get(), 'opt_dir': self.v_opt_dir.get(),
                    'opt_speed': self.v_opt_speed.get()}

        def _show_preview(self, cid):
            p, errors = self.read_params()
            if errors:
                self._set_preview('⚠ ' + ', '.join(errors))
                return
            try:
                self._set_preview('→ ' + render(self.cmds[cid], p, self.opts()))
            except ValueError as exc:
                self._set_preview('⚠ ' + str(exc))

        def set_status(self, msg, ok=True):
            self.v_status.set(msg)
            self.lbl_status.configure(foreground='#1f7a3a' if ok else '#c53030')
            if not ok:
                self.root.bell()

        # ------------------------------------------------------ คำสั่ง
        def run_cmd(self, cid, from_button=False):
            if self.paused.get() and not from_button:
                return
            p, errors = self.read_params()
            if errors:
                self.set_status('ไม่พิมพ์: ' + ', '.join(errors), ok=False)
                return
            try:
                text = render(self.cmds[cid], p, self.opts())
            except ValueError as exc:
                self.set_status('ไม่พิมพ์: ' + str(exc), ok=False)
                return
            self.last_cmd_id = cid
            self._live_preview()
            self.set_status(f'กำลังพิมพ์: {text}')
            self.typer.submit(text, {'end': self.v_end.get(), 'enter': self.v_enter.get(), 'method': TYPE_METHOD})

        def _adjust(self, var, delta, lo=None, hi=None):
            try:
                v = float(var.get())
            except ValueError:
                v = 0
            v += delta
            if lo is not None:
                v = max(lo, v)
            if hi is not None:
                v = min(hi, v)
            var.set(fmt_number(v))

        def run_param(self, aid):
            if aid == 'exit':
                self.quit()
                return
            if aid == 'pause':
                self.paused.set(not self.paused.get())
                on = not self.paused.get()
                self.lbl_mode.configure(text=' ON ' if on else ' PAUSE ', bg='#1f9d55' if on else '#c05621')
                self.set_status('มาโครทำงาน' if on else 'หยุดชั่วคราว (กด Ctrl+Alt+Shift+P เพื่อเปิด)', ok=on)
                return
            if aid == 'window':
                if self.root.state() == 'withdrawn':
                    self.root.deiconify()
                    self.root.attributes('-topmost', self.v_top.get())
                else:
                    self.root.withdraw()
                return
            if self.paused.get():
                return
            if aid == 'repeat':
                if self.last_cmd_id:
                    self.run_cmd(self.last_cmd_id)
                else:
                    self.set_status('ยังไม่มีคำสั่งล่าสุด', ok=False)
                return
            acts = {
                'speed+': lambda: self._adjust(self.v_speed, SPEED_STEP, SPEED_MIN, SPEED_MAX),
                'speed-': lambda: self._adjust(self.v_speed, -SPEED_STEP, SPEED_MIN, SPEED_MAX),
                'speed_slow': lambda: self.v_speed.set(str(SLOW_SPEED)),
                'speed_def': lambda: self.v_speed.set(str(DEFAULT_SPEED)),
                'speed_fast': lambda: self.v_speed.set(str(FAST_SPEED)),
                'cm+': lambda: self._adjust(self.v_cm, CM_STEP, 0),
                'cm-': lambda: self._adjust(self.v_cm, -CM_STEP, 0),
                'ms+': lambda: self._adjust(self.v_ms, MS_STEP, 0),
                'ms-': lambda: self._adjust(self.v_ms, -MS_STEP, 0),
                'dir0': lambda: self.v_dir.set('0'),
                'dir90': lambda: self.v_dir.set('90'),
                'dir180': lambda: self.v_dir.set('180'),
                'dir270': lambda: self.v_dir.set('270'),
                'act_p': lambda: self.v_act.set('p'),
                'act_c': lambda: self.v_act.set('c'),
                'act_s': lambda: self.v_act.set('s'),
                'act_l': lambda: self.v_act.set('l'),
                'act_r': lambda: self.v_act.set('r'),
                'act_next': lambda: self._cycle_act(1),
                'act_prev': lambda: self._cycle_act(-1),
                'act_case': lambda: self.v_act.set(self.v_act.get().swapcase()),
            }
            acts[aid]()
            self.set_status(f'speed={self.v_speed.get()}  cm={self.v_cm.get()}  ms={self.v_ms.get()}  '
                            f"dir={self.v_dir.get()}  angle={self.v_angle.get()}  "
                            f"act={repr(self.v_act.get()) if self.v_act.get() else 'None'}  "
                            f"tol={self.v_tol.get() or 'None'}")

        def _cycle_act(self, step):
            cur = self.v_act.get()
            upper = cur.isupper()
            low = cur.lower()
            i = ACTION_CYCLE.index(low) if low in ACTION_CYCLE else -1
            nxt = ACTION_CYCLE[(i + step) % len(ACTION_CYCLE)]
            self.v_act.set(nxt.upper() if upper else nxt)

        # ------------------------------------------------------ วนลูป
        def _poll_queue(self):
            try:
                while True:
                    item = self.ui_queue.get_nowait()
                    if item[0] == 'hotkey':
                        action = item[1]
                        if action.startswith('cmd:'):
                            self.run_cmd(action)
                        else:
                            self.run_param(action)
                    elif item[0] == 'status':
                        self.set_status(item[1], item[2])
            except queue.Empty:
                pass
            if self.root.winfo_exists():
                self.root.after(30, self._poll_queue)

        def _poll_foreground(self):
            try:
                hwnd = user32.GetForegroundWindow()
                if is_valid_target(hwnd) and hwnd != self.typer.last_target:
                    self.typer.last_target = hwnd
                    title = window_title(hwnd) or window_class(hwnd)
                    self.v_target.set('เป้าหมาย: ' + (title[:38] + '…' if len(title) > 38 else title))
            except Exception:
                pass
            self.root.after(200, self._poll_foreground)

        def _start_hotkeys(self):
            bindings = [(c.hotkey, c.id) for c in MACROS] + [(hk, aid) for aid, hk, _ in PARAM_ACTIONS]
            self.hotkeys = HotkeyThread(bindings, self.ui_queue)
            self.hotkeys.start()
            self.hotkeys.ready.wait(3)
            if self.hotkeys.failed:
                msg = 'คีย์ลัดที่ใช้ไม่ได้ (โปรแกรมอื่นจองไว้): ' + ', '.join(pretty_hotkey(h) for h in self.hotkeys.failed)
                print('[!] ' + msg)
                self.set_status(msg, ok=False)
            print(f'--- เริ่มทำงาน: คีย์ลัด {len(bindings) - len(self.hotkeys.failed)}/{len(bindings)} ใช้งานได้ ---')
            print(f'    {pretty_hotkey(EXIT_HOTKEY)} = ปิดโปรแกรม')

        def quit(self):
            if self.hotkeys:
                self.hotkeys.stop()
            self.typer.stop()
            try:
                self.root.destroy()
            except Exception:
                pass
            print('--- ปิดโปรแกรมแล้ว ---')

        def mainloop(self):
            self.root.mainloop()

    return App()


# ============================================================================
# 10) โหมดตรวจสอบ / ตาราง
# ============================================================================
SAMPLE_PARAMS = {'speed': DEFAULT_SPEED, 'cm': DEFAULT_CM, 'ms': DEFAULT_MS,
                 'dir': 90, 'angle': DEFAULT_ANGLE, 'act': DEFAULT_ACTION, 'tol': None}


def markdown_table():
    lines = []
    cats = []
    for c in MACROS:
        if c.cat not in cats:
            cats.append(c.cat)
    for cat in cats:
        lines += [f'#### {cat}', '', '| คีย์ลัด | ผลลัพธ์ (ค่าตัวอย่าง) | ความหมาย |', '|---|---|---|']
        for c in [m for m in MACROS if m.cat == cat]:
            code = f"`{render(c, SAMPLE_PARAMS, {'alias': False, 'opt_act': True, 'opt_dir': False, 'opt_speed': True})}`"
            if c.alias:
                code += f" / `{render(c, SAMPLE_PARAMS, {'alias': True})}`"
            lines.append(f'| `{pretty_hotkey(c.hotkey)}` | {code} | {c.desc} |')
        lines.append('')
    lines += ['#### ปรับค่า / ระบบ (ไม่พิมพ์ลง IDE)', '', '| คีย์ลัด | หน้าที่ |', '|---|---|']
    for _, hk, label in PARAM_ACTIONS:
        lines.append(f'| `{pretty_hotkey(hk)}` | {label} |')
    return '\n'.join(lines)


def selftest():
    ok = True
    seen = {}
    all_hotkeys = [(c.hotkey, c.id) for c in MACROS] + [(hk, aid) for aid, hk, _ in PARAM_ACTIONS]
    for hk, ident in all_hotkeys:
        key = parse_hotkey(hk)
        if key in seen:
            print(f'[FAIL] คีย์ลัดซ้ำ {hk}: {seen[key]} กับ {ident}')
            ok = False
        seen[key] = ident

    rendered = []
    for alias in (False, True):
        for opt_act in (False, True):
            for opt_dir in (False, True):
                o = {'alias': alias, 'opt_act': opt_act, 'opt_dir': opt_dir}
                rendered += [render(c, SAMPLE_PARAMS, o) for c in MACROS]
    names = {r.split('(')[0] for r in rendered}
    missing = [n for n in REQUIRED_NAMES if n not in names]
    if missing:
        print('[FAIL] ไม่มีคำสั่ง:', ', '.join(missing))
        ok = False

    checks = {
        ('ff', False, True, False): "ff(70, 'p');",
        ('ffcmg', False, False, False): 'ffcmg(70, 20);',
        ('ffcmg', False, True, False): "ffcmg(70, 20, 'p');",
        ('ffcmg', False, False, True): "ffcmg(70, 20, 'p', 90);",   # dir บังคับให้ใส่ act ด้วย
        ('ffbg', False, False, False): "ffbg(70, 'p', 90);",
        ('spindir', True, True, False): 'sdg(70, 90);',
        ('turnrbg', True, True, False): 'trbg(70, 90);',
        ('arm_behihd', False, True, False): 'arm_behihd();',
    }
    by_name = {}
    for c in MACROS:
        by_name.setdefault(c.name, c)
    for (name, alias, oa, od), expect in checks.items():
        got = render(by_name[name], SAMPLE_PARAMS, {'alias': alias, 'opt_act': oa, 'opt_dir': od})
        if got != expect:
            print(f'[FAIL] {name}: ได้ {got!r} ควรเป็น {expect!r}')
            ok = False
    # ---- คำสั่งชุดใหม่: ตรวจตามตัวอย่างในสเปกทุกกรณี ----
    def r(name, alias=False, **kw):
        o = {'alias': alias, 'opt_act': kw.pop('opt_act', True), 'opt_dir': kw.pop('opt_dir', False),
             'opt_speed': kw.pop('opt_speed', True)}
        return render(by_name[name], dict(SAMPLE_PARAMS, **kw), o)
    new_checks = [
        (r('resetAngles'), 'resetAngles();'),
        (r('spinl', opt_speed=False), 'spinl();'),
        (r('spinr', opt_speed=True), 'spinr(70);'),
        (r('spinl2', opt_speed=False), 'spinl2();'),
        (r('spinr2', opt_speed=True), 'spinr2(70);'),
        (r('spindir', opt_speed=False), 'spindir(90);'),
        (r('spinlg', alias=True, opt_speed=False), 'slg(90);'),
        (r('turnlg', opt_speed=False), 'turnlg(70, 90);'),          # turn* ไม่ได้เป็น optional
        (r('ffcmcl', cm=25, act=None), 'ffcmcl(70, 25);'),
        (r('ffcmcl', cm=25, act='p'), "ffcmcl(70, 25, 'p');"),
        (r('bbcmcr', cm=25, act='S'), "bbcmcr(70, 25, 'S');"),
        (r('ffdircl', act=None, tol=None), 'ffdircl(70, 90);'),
        (r('ffdircl', act='p', tol=None), "ffdircl(70, 'p', 90);"),
        (r('ffdircl', act=None, tol=2), 'ffdircl(70, 90, 2);'),
        (r('ffdircl', act='p', tol=2), "ffdircl(70, 'p', 90, 2);"),
        (r('bbdircr', act='c', tol=1.5), "bbdircr(70, 'c', 90, 1.5);"),
        (r('ffdirclg', act=None, tol=None), "ffdirclg(70, 'p', 90);"),
        (r('ffdirclg', act=None, tol=2), "ffdirclg(70, 'p', 90, 2);"),
        (r('bbdircrg', act='L', tol=None), "bbdircrg(70, 'L', 90);"),
        (r('ffcmg', act='p', opt_dir=True, tol=3), "ffcmg(70, 20, 'p', 90);"),  # tol ไม่กระทบคำสั่งอื่น
    ]
    for got, expect in new_checks:
        if got != expect:
            print(f'[FAIL] ได้ {got!r} ควรเป็น {expect!r}'); ok = False

    # ปุ่ม None (ไม่ใส่ action)
    none_p = dict(SAMPLE_PARAMS, act=None)
    if render(by_name['ffcmg'], none_p, {'opt_act': True, 'opt_dir': False}) != 'ffcmg(70, 20);':
        print('[FAIL] ffcmg + None'); ok = False
    for name, o in [('ff', {}), ('ffbg', {}), ('ffcmg', {'opt_act': True, 'opt_dir': True})]:
        try:
            render(by_name[name], none_p, o)
            print(f'[FAIL] {name} + None ควร raise ValueError'); ok = False
        except ValueError:
            pass
    if sorted(c for _, _, _, chars in ACTION_GROUPS for c in chars) != sorted(ACTION_LIST) or len(ACTION_LIST) != 22:
        print('[FAIL] Action Pad ไม่ครบ 22 ตัว'); ok = False
    if set(ACTION_SHORT) != set(ACTION_LIST) | {ACT_NONE}:
        print('[FAIL] ACTION_SHORT ไม่ครบ'); ok = False

    if len({c.id for c in MACROS}) != len(MACROS):
        print('[FAIL] Cmd.id ซ้ำ'); ok = False
    lookup = {c.id: c for c in MACROS}          # เส้นทางเดียวกับที่แอปใช้จริง
    for hk, expect in [('ctrl+alt+6', 'fft(70, 500);'), ('ctrl+alt+7', "fft(70, 500, 'p');"),
                       ('ctrl+alt+shift+6', 'bbt(70, 500);'), ('ctrl+alt+shift+7', "bbt(70, 500, 'p');")]:
        got = render(lookup['cmd:' + hk], SAMPLE_PARAMS, {})
        if got != expect:
            print(f'[FAIL] {hk}: ได้ {got!r} ควรเป็น {expect!r}'); ok = False
    fft_act = [c for c in MACROS if c.name == 'fft' and 'act' in c.params][0]
    if render(fft_act, SAMPLE_PARAMS, {}) != "fft(70, 500, 'p');":
        print('[FAIL] fft + act'); ok = False
    if render(MACROS[-1], dict(SAMPLE_PARAMS, ms=250), {}) != 'delay(250);':
        print('[FAIL] raw template'); ok = False
    if fmt_number(12.5) != '12.5' or fmt_number(20.0) != '20':
        print('[FAIL] fmt_number'); ok = False

    print(f'คำสั่ง {len(MACROS)} รายการ, คีย์ลัดทั้งหมด {len(all_hotkeys)} ชุด, ชื่อ API ครบ {len(REQUIRED_NAMES) - len(missing)}/{len(REQUIRED_NAMES)}')
    print('SELFTEST', 'PASS' if ok else 'FAIL')
    return ok


# ============================================================================
# main
# ============================================================================
def main():
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass

    if '--selftest' in sys.argv:
        sys.exit(0 if selftest() else 1)
    if '--table' in sys.argv:
        print(markdown_table())
        return
    if not IS_WINDOWS:
        print('โปรแกรมนี้รองรับเฉพาะ Windows')
        sys.exit(1)
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)   # ตัวหนังสือคมบนจอ 125-150% (ต้องเรียกก่อนสร้าง Tk)
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()     # Windows 7/8 ที่ไม่มี shcore
        except Exception:
            pass

    if '--gui-test' in sys.argv:
        app = build_app(start_hotkeys=False)
        app.root.update()
        print('GUI OK:', app.root.winfo_width(), 'x', app.root.winfo_height())
        app.quit()
        return

    if pyperclip is None:
        print('[i] ไม่พบ pyperclip — ใช้ Clipboard ของ Windows โดยตรงแทน (ทำงานได้เหมือนกัน)')
    app = build_app()
    try:
        app.mainloop()
    except KeyboardInterrupt:
        app.quit()


if __name__ == '__main__':
    main()
