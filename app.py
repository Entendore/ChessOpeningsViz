#!/usr/bin/env python3
"""
Chess Openings Explorer — Optimized Single-file PySide6 application.
Key improvements:
  - SQLite-backed DataProvider for fast 3500+ opening loads
  - Paginated openings list (virtual scrolling)
  - Batch rendering with checkbox selection + range select
  - Title card & end screen preview widgets
  - Tabbed settings dialog
"""

import sys, os, re, ast, base64, json, csv, math, time, wave, logging, zlib
import shutil, subprocess, tempfile, threading, sqlite3
from pathlib import Path
from datetime import datetime
from contextlib import contextmanager
import numpy as np
import chess, chess.pgn

from PySide6.QtMultimedia import QSoundEffect

from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QTextEdit, QListWidget, QListWidgetItem,
    QSlider, QComboBox, QCheckBox, QGroupBox, QSplitter,
    QStatusBar, QLineEdit, QProgressBar, QSpinBox, QFileDialog,
    QTabWidget, QScrollArea, QTableWidget, QTableWidgetItem,
    QHeaderView, QAbstractItemView, QDialog, QDialogButtonBox,
    QToolTip, QFrame, QGridLayout, QSizePolicy, QToolButton, QDoubleSpinBox
)
from PySide6.QtCore import (
    Qt, QTimer, Signal, QThread, QUrl, QRect, QRectF, QPointF,
    QSortFilterProxyModel, QAbstractTableModel, QModelIndex,
)
from PySide6.QtGui import (
    QPainter, QPixmap, QPalette, QColor, QFont, QPen, QBrush,
    QRadialGradient, QLinearGradient, QImage, QPolygonF, QPainterPath,
    QTransform, QAction, QIcon, QFontMetrics,
)

# ═══════════════════════════════════════════════════════════════════════════════
#  OPTIONAL DEPENDENCIES
# ═══════════════════════════════════════════════════════════════════════════════

HAS_NUMPY = True
HAS_IMAGEIO = False
try:
    import imageio.v3 as iio; HAS_IMAGEIO = True
except Exception: pass
HAS_PANDAS = False; HAS_PYARROW = False; HAS_DUCKDB = False
try:
    import pandas as pd; HAS_PANDAS = True
except ImportError: pass
if not HAS_PANDAS:
    try:
        import pyarrow.parquet as pq; HAS_PYARROW = True
    except ImportError: pass
try:
    import duckdb; HAS_DUCKDB = True
except ImportError: pass
HAS_NUMBA = False
try:
    import numba; HAS_NUMBA = True
except ImportError: pass
HAS_CUPY = False
try:
    import cupy as cp; HAS_CUPY = True
except Exception: pass
HAS_FFMPEG = shutil.which('ffmpeg') is not None
HAS_MOVIEPY = False
try:
    import moviepy; HAS_MOVIEPY = True
except ImportError: pass

# ═══════════════════════════════════════════════════════════════════════════════
#  LOGGING
# ═══════════════════════════════════════════════════════════════════════════════

logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s.%(msecs)03d] [%(levelname)s] %(message)s',
    datefmt='%H:%M:%S'
)
logger = logging.getLogger(__name__)

def log(msg, level="INFO"):
    level_map = {
        "INFO": logging.INFO,
        "WARN": logging.WARNING,
        "WARNING": logging.WARNING,
        "ERROR": logging.ERROR,
        "DATA": logging.INFO,  # Map custom "DATA" level to INFO
        "DEBUG": logging.DEBUG
    }
    logger.log(level_map.get(level.upper(), logging.INFO), msg)

# ═══════════════════════════════════════════════════════════════════════════════
#  FILE PATHS
# ═══════════════════════════════════════════════════════════════════════════════

APP_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(APP_DIR, "data")
EXPORT_DIR = os.path.join(APP_DIR, "exports")
DB_OPENINGS_PATH = os.path.join(DATA_DIR, "cache_openings.parquet")
LICHESS_DB_PATH = os.path.join(DATA_DIR, "lichess_db_openings.parquet")
EXPORT_MANIFEST_PATH = os.path.join(APP_DIR, "export_manifest.json")
SQLITE_DB_PATH = os.path.join(DATA_DIR, "openings.db")

# ═══════════════════════════════════════════════════════════════════════════════
#  BOARD / RENDERING CONSTANTS
# ═══════════════════════════════════════════════════════════════════════════════

SQ_SIZE   = 68
BOARD_PX  = SQ_SIZE * 8

PIECE_SYM = {
    (chess.PAWN, chess.WHITE): "♟", (chess.PAWN, chess.BLACK): "♟",
    (chess.KNIGHT, chess.WHITE): "♞", (chess.KNIGHT, chess.BLACK): "♞",
    (chess.BISHOP, chess.WHITE): "♝", (chess.BISHOP, chess.BLACK): "♝",
    (chess.ROOK, chess.WHITE): "♜", (chess.ROOK, chess.BLACK): "♜",
    (chess.QUEEN, chess.WHITE): "♛", (chess.QUEEN, chess.BLACK): "♛",
    (chess.KING, chess.WHITE): "♚", (chess.KING, chess.BLACK): "♚",
}

FILES_STR = 'abcdefgh'
RANKS_STR = '87654321'

ANIM_SPEED_SLOW    = 500
ANIM_SPEED_DEFAULT = 250
ANIM_SPEED_FAST    = 100
ANIM_FPS           = 60


# ═══════════════════════════════════════════════════════════════════════════════
#  ARROW STYLES
# ═══════════════════════════════════════════════════════════════════════════════

ARROW_STYLE_SIMPLE  = "simple"
ARROW_STYLE_THICK   = "thick"     # Lichess-style
ARROW_STYLE_FANCY   = "fancy"     # Gradient + glow
ARROW_STYLE_MINIMAL = "minimal"   # Thin, subtle
ARROW_STYLE_NONE    = "none"

ARROW_STYLES = {
    "Thick (Lichess)":  ARROW_STYLE_THICK,
    "Fancy (Gradient)": ARROW_STYLE_FANCY,
    "Simple":           ARROW_STYLE_SIMPLE,
    "Minimal":          ARROW_STYLE_MINIMAL,
    "None":             ARROW_STYLE_NONE,
}

ARROW_STYLES_LIST = list(ARROW_STYLES.keys()) 

# ═══════════════════════════════════════════════════════════════════════════════
#  BOARD THEMES
# ═══════════════════════════════════════════════════════════════════════════════

class BoardTheme:
    def __init__(self, name="Classic",
                 light=(240, 217, 181), dark=(181, 136, 99),
                 border=(48, 26, 7), highlight=(255, 255, 0, 100),
                 last_move=(155, 199, 0, 100), arrow=(220, 50, 47, 200), arrow_style=ARROW_STYLE_THICK):
        self.name = name; self.light_sq = QColor(*light)
        self.dark_sq = QColor(*dark); self.border = QColor(*border)
        self.highlight = QColor(*highlight); self.last_move = QColor(*last_move)
        self.arrow_clr = QColor(*arrow)
        self.arrow_style = arrow_style
        self.bg = QColor(32, 32, 36); self.coord = QColor(180, 160, 130)

THEMES = {
    "Classic": BoardTheme(),
    "Blue":    BoardTheme("Blue", (208, 224, 243), (116, 150, 194), (40, 50, 70)),
    "Green":   BoardTheme("Green", (238, 238, 210), (118, 150, 86), (50, 60, 40)),
    "Brown":   BoardTheme("Brown", (222, 197, 165), (170, 120, 70), (60, 35, 15)),
    "Purple":  BoardTheme("Purple", (220, 210, 230), (150, 130, 170), (50, 40, 60)),
    "Ice":     BoardTheme("Ice", (230, 240, 250), (160, 190, 220), (50, 60, 80)),
}

# ═══════════════════════════════════════════════════════════════════════════════
#  EXPORT PRESETS
# ═══════════════════════════════════════════════════════════════════════════════

class ExportPreset:
    def __init__(self, name, width, height, fps=30, board_frac=0.82,
                 bg=(26, 26, 46), description=""):
        self.name = name; self.width = width; self.height = height
        self.fps = fps; self.board_frac = board_frac
        self.bg = bg; self.description = description

    @property
    def is_vertical(self): return self.height > self.width
    @property
    def is_square(self): return self.width == self.height
    @property
    def is_board_only(self): return self.board_frac >= 1.0

    def calc_sq_size(self):
        if self.is_vertical:
            board_px = int(self.width * self.board_frac)
        else:
            board_px = int(self.height * 0.78 * self.board_frac / 0.82)
        board_px = (board_px // 8) * 8
        return max(8, board_px // 8)

EXPORT_PRESETS = {
    "YouTube 1080p":    ExportPreset("YouTube 1080p",    1920, 1080, 30, 0.60, (26, 26, 46), "16:9 Full HD"),
    "YouTube 720p":     ExportPreset("YouTube 720p",     1280,  720, 30, 0.60, (26, 26, 46), "16:9 HD"),
    "YouTube 4K":       ExportPreset("YouTube 4K",       3840, 2160, 30, 0.60, (26, 26, 46), "16:9 4K"),
    "YouTube Shorts":   ExportPreset("YouTube Shorts",   1080, 1920, 30, 0.70, (26, 26, 46), "9:16 vertical"),
    "TikTok":           ExportPreset("TikTok",           1080, 1920, 30, 0.70, (26, 26, 46), "9:16 vertical"),
    "Instagram Reels":  ExportPreset("Instagram Reels",  1080, 1920, 30, 0.70, (26, 26, 46), "9:16 vertical"),
    "Instagram Square": ExportPreset("Instagram Square", 1080, 1080, 30, 0.65, (26, 26, 46), "1:1 square"),
    "Board Only":       ExportPreset("Board Only",        544,  544, 30, 1.00, (26, 26, 46), "Square board-only"),
}


# ═══════════════════════════════════════════════════════════════════════════════
#  EXPORT CONFIG
# ═══════════════════════════════════════════════════════════════════════════════
SETTINGS_JSON_PATH = os.path.join(APP_DIR, "settings.json")
class ExportConfig:
    def __init__(self):
        self.fps = 30
        self.title_enabled = True; self.title_duration = 3.0
        self.end_title_enabled = True; self.end_title_duration = 3.0
        self.move_anim_duration = 0.5; self.pause_after_move = 0.8
        self.preset_name = "YouTube 1080p"
        self.theme_name = "Classic"
        self.arrow_style = ARROW_STYLE_THICK
        self.ffmpeg_crf = 20; self.ffmpeg_preset = "medium"
        self.title_text_override = ""
        self.end_screen_text = ""
        self.flip_board = False
        self._bg_color = None
        self.output_dir = EXPORT_DIR
        self.load()

    def apply_preset(self, name):
        if name in EXPORT_PRESETS:
            p = EXPORT_PRESETS[name]; self.preset_name = name
            self.fps = p.fps

    @property
    def preset(self):
        return EXPORT_PRESETS.get(self.preset_name, EXPORT_PRESETS["YouTube 1080p"])

    @property
    def target_width(self): return self.preset.width

    @property
    def target_height(self): return self.preset.height

    @property
    def bg_color(self):
        return self._bg_color if self._bg_color is not None else self.preset.bg

    @bg_color.setter
    def bg_color(self, value):
        self._bg_color = value

    @property
    def is_vertical(self): return self.preset.is_vertical
    @property
    def sq_size(self): return self.preset.calc_sq_size()

    def save(self):
        try:
            os.makedirs(os.path.dirname(SETTINGS_JSON_PATH), exist_ok=True)
            data = {}
            for k, v in self.__dict__.items():
                if k == '_bg_color':
                    data['bg_color_override'] = list(v) if v is not None else None
                elif not k.startswith('_'):
                    if isinstance(v, Path): v = str(v)
                    data[k] = v
            with open(SETTINGS_JSON_PATH, 'w') as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            log(f"Failed to save settings: {e}", "ERROR")

    def load(self):
        if not os.path.exists(SETTINGS_JSON_PATH): return
        try:
            with open(SETTINGS_JSON_PATH, 'r') as f:
                data = json.load(f)
            for k, v in data.items():
                if k == 'bg_color_override':
                    self._bg_color = tuple(v) if v is not None else None
                elif hasattr(self, k):
                    setattr(self, k, v)
        except Exception as e:
            log(f"Failed to load settings: {e}", "WARN")

# ═══════════════════════════════════════════════════════════════════════════════
#  HELPERS
# ═══════════════════════════════════════════════════════════════════════════════
_SAFE_FS = re.compile(r'[\\/*?:"<>|]')

def _qimage_to_bgr_bytes(img):
    # Ensure the image is in a predictable format
    if img.format() != QImage.Format_RGB888:
        img = img.convertToFormat(QImage.Format_RGB888)
    
    w = img.width()
    h = img.height()
    bpl = img.bytesPerLine()
    
    # PySide6 constBits() returns a memoryview object
    ptr = img.constBits()
    
    # Read buffer and reshape to (h, bpl) to safely handle any row padding (stride)
    # Using count=img.sizeInBytes() ensures we never read past the allocated buffer
    raw = np.frombuffer(ptr, dtype=np.uint8, count=img.sizeInBytes()).reshape((h, bpl)).copy()
    
    # Drop any row padding if bytesPerLine is greater than width * 3
    if bpl > w * 3:
        raw = raw[:, :w * 3]
    
    # Reshape to the final (height, width, 3) format
    arr = raw.reshape((h, w, 3))
    
    # Swap R and B channels for FFmpeg (BGR) and return bytes
    return arr[:, :, ::-1].tobytes()

def sanitize_filename(name, max_len=120):
    s = _SAFE_FS.sub('_', name).strip('. ')
    return s[:max_len] if s else "untitled"

def _ease_out_cubic(t):
    return 1.0 - (1.0 - t) ** 3

def _to_i16(samples):
    """Converts float64 audio samples to 16-bit integers for WAV export."""
    return np.clip(samples * 32767.0, -32768, 32767).astype(np.int16)

@contextmanager
def paint_context(image):
    """Context manager to ensure QPainter is properly ended, preventing QPaintDevice destruction errors."""
    p = QPainter(image)
    try:
        yield p
    finally:
        if p.isActive():
            p.end()


def _font_family_sans():
    return "Segoe UI, sans-serif"

def _font_family_mono():
    return "Consolas, Courier New, monospace"

def _make_font(family, size_px, bold=False):
    font = QFont(family, -1, QFont.Bold if bold else QFont.Normal)
    font.setPixelSize(int(size_px))
    return font

# ═══════════════════════════════════════════════════════════════════════════════
#  ENGINE
# ═══════════════════════════════════════════════════════════════════════════════

class ChessEngine:
    def __init__(self):
        self.board = chess.Board()
        self.game_over = False; self.result = ""; self.last_move = None

    def reset(self):
        self.board.reset(); self.game_over = False
        self.result = ""; self.last_move = None

    @staticmethod
    def sq_to_rc(sq): return 7 - chess.square_rank(sq), chess.square_file(sq)
    @staticmethod
    def rc_to_sq(r, c): return chess.square(c, 7 - r)

    @property
    def turn(self): return 'w' if self.board.turn == chess.WHITE else 'b'

    def check_squares(self):
        if self.board.is_check():
            return [self.sq_to_rc(self.board.king(self.board.turn))]
        return []

    def legal_moves(self, r, c):
        sq = self.rc_to_sq(r, c)
        return [self.sq_to_rc(m.to_square) for m in self.board.legal_moves if m.from_square == sq]

    def make_move(self, fr, fc, tr, tc, promo=None):
        from_sq = self.rc_to_sq(fr, fc); to_sq = self.rc_to_sq(tr, tc)
        piece = self.board.piece_at(from_sq)
        if not piece: return None
        
        promotion = None
        if piece.piece_type == chess.PAWN:
            if (piece.color == chess.WHITE and tr == 0) or (piece.color == chess.BLACK and tr == 7):
                # Fix 10: Safe promotion handling with fallback to Queen
                try:
                    promo_str = str(promo).strip().lower() if promo else ""
                    if promo_str and promo_str[0] in 'qrbn':
                        promotion = chess.PIECE_SYMBOLS.index(promo_str[0])
                    else:
                        promotion = chess.QUEEN
                except (ValueError, AttributeError, IndexError):
                    promotion = chess.QUEEN

        move = chess.Move(from_sq, to_sq, promotion=promotion)
        if move not in self.board.legal_moves: return None
        
        is_castle = self.board.is_castling(move)
        is_ep = self.board.is_en_passant(move)
        if is_ep:
            ep_cap_sq = chess.square(chess.square_file(to_sq), chess.square_rank(from_sq))
            cap = self.board.piece_at(ep_cap_sq)
        else:
            cap = self.board.piece_at(to_sq)
        captured = cap.symbol() if cap else '.'
        notation = self.board.san(move)
        piece_obj = chess.Piece(piece.piece_type, piece.color)
        
        self.board.push(move); self.last_move = ((fr, fc), (tr, tc))
        self.game_over = self.board.is_game_over()
        self.result = self.board.result() if self.game_over else ""
        
        return {'from': (fr, fc), 'to': (tr, tc), 'piece': piece.symbol(),
                'piece_obj': piece_obj, 'captured': captured,
                'castle': is_castle, 'ep': is_ep, 'promo': promo,
                'check': self.board.is_check(), 'mate': self.board.is_checkmate(),
                'notation': notation}

    def make_move_uci(self, uci_str):
        move = chess.Move.from_uci(uci_str)
        if move in self.board.legal_moves:
            fr, fc = self.sq_to_rc(move.from_square)
            tr, tc = self.sq_to_rc(move.to_square)
            promo = chess.piece_symbol(move.promotion) if move.promotion else None
            return self.make_move(fr, fc, tr, tc, promo)
        return None

    def undo(self):
        if len(self.board.move_stack) > 0:
            self.board.pop()
            self.game_over = self.board.is_game_over()
            self.result = self.board.result() if self.game_over else ""
            if self.board.move_stack:
                last = self.board.peek()
                self.last_move = (self.sq_to_rc(last.from_square), self.sq_to_rc(last.to_square))
            else:
                self.last_move = None
            return True
        return False


# ═══════════════════════════════════════════════════════════════════════════════
#  RENDERING
# ═══════════════════════════════════════════════════════════════════════════════

_tl = threading.local()
def get_render_assets(sz):
    isz = int(sz * 100)
    if getattr(_tl, 'cache_sz', -1) == isz: return _tl.assets
    fp = QFont("Segoe UI Emoji", sz * 0.9); fp.setStyleStrategy(QFont.PreferAntialias)
    fc = QFont("Sans", max(7, int(sz * 0.13)), QFont.Bold)
    fb1 = QFont("Sans", max(6, int(sz * 0.19 * 0.95)), QFont.Bold)
    fb2 = QFont("Segoe UI Emoji", max(7, int(sz * 0.19 * 1.15)), QFont.Bold)
    pb = QPen(QColor(255, 255, 255, 120), max(0.8, sz * 0.008))
    _tl.assets = (fp, fc, fb1, fb2, pb); _tl.cache_sz = isz
    return _tl.assets
_piece_cache = {}

def get_cached_piece(piece_obj, sz, font):
    """Retrieves or generates a cached QPixmap for a chess piece to avoid redundant vector math."""
    # Key includes 'sz' so different board sizes (e.g., UI vs. 4K export) cache correctly
    key = (piece_obj.piece_type, piece_obj.color, sz)
    if key not in _piece_cache:
        pixmap = QPixmap(sz, sz)
        pixmap.fill(Qt.transparent)
        
        with paint_context(pixmap) as p:
            p.setRenderHint(QPainter.Antialiasing)
            p.setRenderHint(QPainter.TextAntialiasing)
            _draw_piece_at_core(p, piece_obj, 0.0, 0.0, sz, sz, sz, font)
            
        _piece_cache[key] = pixmap
    return _piece_cache[key]

def _draw_piece_at_core(p, piece_obj, row_f, col_f, sz, w, h, font):
    """Core drawing logic extracted for caching."""
    FIT_FRAC = 0.85
    is_w = piece_obj.color == chess.WHITE
    glyph = PIECE_SYM[(piece_obj.piece_type, piece_obj.color)]
    
    px = col_f * sz
    py = row_f * sz
    rect = QRectF(px + (sz - w) / 2, py + (sz - h) / 2, w, h)
    center = rect.center()
    
    p.setFont(font)
    path = QPainterPath()
    path.addText(QPointF(0, 0), font, glyph)
    br = path.boundingRect()
    path.translate(-br.center().x(), -br.center().y())
    
    if br.width() > 0 and br.height() > 0:
        s = min((w * FIT_FRAC) / br.width(), (h * FIT_FRAC) / br.height())
        path = QTransform.fromScale(s, s).map(path)
        path.translate(center.x(), center.y())
        
        shadow = QPainterPath(path)
        shadow.translate(1.5, 2.0)
        
        p.setPen(Qt.NoPen)
        if is_w:
            p.setBrush(QColor(0, 0, 0, 50))
            p.drawPath(shadow)
            olw = max(1.2, sz * 0.028)
            p.setPen(QPen(QColor(30, 30, 30), olw, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
            p.setBrush(QColor(255, 255, 255))
            p.drawPath(path)
        else:
            p.setBrush(QColor(0, 0, 0, 60))
            p.drawPath(shadow)
            olw = max(0.8, sz * 0.018)
            p.setPen(QPen(QColor(10, 10, 10), olw, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
            p.setBrush(QColor(40, 40, 40))
            p.drawPath(path)

def _draw_piece(p, piece_obj, row, col, sz, font):
    """Optimized wrapper that blits the cached pixmap instead of recalculating paths."""
    pixmap = get_cached_piece(piece_obj, sz, font)
    p.drawPixmap(int(col * sz), int(row * sz), pixmap)

# Keep the original signature for animated pieces that require dynamic scaling/lifting
def _draw_piece_at(p, piece_obj, row_f, col_f, sz, w, h, font):
    _draw_piece_at_core(p, piece_obj, row_f, col_f, sz, w, h, font)

def _draw_arrow(painter, fx, fy, tx, ty, color, sz, style=ARROW_STYLE_THICK):
    """Dispatch to the appropriate arrow style renderer."""
    if style == ARROW_STYLE_NONE:
        return
    elif style == ARROW_STYLE_SIMPLE:
        _draw_arrow_simple(painter, fx, fy, tx, ty, color, sz)
    elif style == ARROW_STYLE_THICK:
        _draw_arrow_thick(painter, fx, fy, tx, ty, color, sz)
    elif style == ARROW_STYLE_FANCY:
        _draw_arrow_fancy(painter, fx, fy, tx, ty, color, sz)
    elif style == ARROW_STYLE_MINIMAL:
        _draw_arrow_minimal(painter, fx, fy, tx, ty, color, sz)
    else:
        _draw_arrow_thick(painter, fx, fy, tx, ty, color, sz)


def _draw_arrow_simple(painter, fx, fy, tx, ty, color, sz):
    """Original simple arrow: thin line + triangular head."""
    dx = tx - fx; dy = ty - fy; dist = max(1, math.hypot(dx, dy))
    margin = sz * 0.22
    fx2 = fx + dx * margin / dist; fy2 = fy + dy * margin / dist
    tx2 = tx - dx * margin / dist; ty2 = ty - dy * margin / dist
    painter.setPen(QPen(color, max(2, sz // 20), Qt.SolidLine, Qt.RoundCap))
    painter.drawLine(int(fx2), int(fy2), int(tx2), int(ty2))
    angle = math.atan2(dy, dx); a_sz = sz * 0.22
    p1x = tx2 - a_sz * math.cos(angle - 0.45)
    p1y = ty2 - a_sz * math.sin(angle - 0.45)
    p2x = tx2 - a_sz * math.cos(angle + 0.45)
    p2y = ty2 - a_sz * math.sin(angle + 0.45)
    tri = QPolygonF([QPointF(tx2, ty2), QPointF(p1x, p1y), QPointF(p2x, p2y)])
    painter.setBrush(color); painter.setPen(Qt.NoPen); painter.drawPolygon(tri)



def _draw_arrow_thick(painter, fx, fy, tx, ty, color, sz):
    """Lichess-style thick arrow with proper head, shadow, and highlight."""
    dx = tx - fx; dy = ty - fy
    dist = max(1, math.hypot(dx, dy))
    if dist < 1:
        return

    # Unit vectors along and perpendicular to the arrow
    ux, uy = dx / dist, dy / dist
    nx, ny = -uy, ux

    # Proportional dimensions
    shaft_half = sz * 0.09        # half-width of shaft
    head_half  = sz * 0.22        # half-width of arrowhead
    head_len   = sz * 0.28        # arrowhead length (neck → tip)
    tail_r     = sz * 0.06        # rounded tail cap radius
    margin_s   = sz * 0.15        # offset from source square center
    margin_e   = sz * 0.06        # offset from target square center

    # Key points along the arrow axis
    sx = fx + ux * margin_s;  sy = fy + uy * margin_s
    ex = tx - ux * margin_e;  ey = ty - uy * margin_e
    neck_x = ex - ux * head_len; neck_y = ey - uy * head_len

    # ── Build the arrow polygon path ──
    path = QPainterPath()

    # Rounded tail (semicircle)
    tail_center_x = sx; tail_center_y = sy
    tail_angle_start = math.atan2(ny, nx)  # angle of normal vector
    # Draw semicircle at tail from right side to left side
    arc_rect = QRectF(tail_center_x - tail_r, tail_center_y - tail_r,
                      tail_r * 2, tail_r * 2)
    start_angle_deg = -math.degrees(math.atan2(-ny, -nx))
    path.arcMoveTo(arc_rect, start_angle_deg)
    path.arcTo(arc_rect, start_angle_deg, 180)

    # Shaft left edge to neck
    path.lineTo(neck_x + nx * shaft_half, neck_y + ny * shaft_half)

    # Arrowhead left wing
    path.lineTo(neck_x + nx * head_half, neck_y + ny * head_half)

    # Arrowhead tip
    path.lineTo(ex, ey)

    # Arrowhead right wing
    path.lineTo(neck_x - nx * head_half, neck_y - ny * head_half)

    # Shaft right edge back to tail
    path.lineTo(neck_x - nx * shaft_half, neck_y - ny * shaft_half)

    # Close back to tail
    path.closeSubpath()

    painter.save()

    # Shadow (offset, darker)
    shadow_path = QPainterPath(path)
    shadow_path.translate(2.5, 3.0)
    painter.setPen(Qt.NoPen)
    painter.setBrush(QColor(0, 0, 0, 50))
    painter.drawPath(shadow_path)

    # Main arrow body — semi-transparent fill
    arrow_clr = QColor(color)
    arrow_clr.setAlpha(min(arrow_clr.alpha(), 210))
    painter.setPen(QPen(arrow_clr.darker(140), max(1, sz * 0.008),
                        Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
    painter.setBrush(arrow_clr)
    painter.drawPath(path)

    # Glossy highlight along the top edge of the shaft
    gloss = QPainterPath()
    gloss.moveTo(sx + nx * shaft_half * 0.35, sy + ny * shaft_half * 0.35)
    gloss.lineTo(neck_x + nx * shaft_half * 0.35, neck_y + ny * shaft_half * 0.35)
    painter.setPen(QPen(QColor(255, 255, 255, 50), max(1, sz * 0.028),
                        Qt.SolidLine, Qt.RoundCap))
    painter.setBrush(Qt.NoBrush)
    painter.drawPath(gloss)

    painter.restore()


def _draw_arrow_fancy(painter, fx, fy, tx, ty, color, sz):
    """Fancy arrow with gradient fill, outer glow, shadow, and highlight."""
    dx = tx - fx; dy = ty - fy
    dist = max(1, math.hypot(dx, dy))
    if dist < 1:
        return

    ux, uy = dx / dist, dy / dist
    nx, ny = -uy, ux

    shaft_half = sz * 0.10
    head_half  = sz * 0.25
    head_len   = sz * 0.30
    margin_s   = sz * 0.15
    margin_e   = sz * 0.06

    sx = fx + ux * margin_s;  sy = fy + uy * margin_s
    ex = tx - ux * margin_e;  ey = ty - uy * margin_e
    neck_x = ex - ux * head_len; neck_y = ey - uy * head_len

    # Arrow polygon
    path = QPainterPath()
    path.moveTo(sx + nx * shaft_half, sy + ny * shaft_half)
    path.lineTo(neck_x + nx * shaft_half, neck_y + ny * shaft_half)
    path.lineTo(neck_x + nx * head_half, neck_y + ny * head_half)
    path.lineTo(ex, ey)
    path.lineTo(neck_x - nx * head_half, neck_y - ny * head_half)
    path.lineTo(neck_x - nx * shaft_half, neck_y - ny * shaft_half)
    path.lineTo(sx - nx * shaft_half, sy - ny * shaft_half)
    path.closeSubpath()

    painter.save()

    # Outer glow (layered wider strokes)
    glow_clr = QColor(color)
    glow_clr.setAlpha(18)
    for i in range(4, 0, -1):
        painter.setPen(QPen(glow_clr, i * sz * 0.04,
                            Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        painter.setBrush(Qt.NoBrush)
        painter.drawPath(path)

    # Shadow
    shadow_path = QPainterPath(path)
    shadow_path.translate(2, 3)
    painter.setPen(Qt.NoPen)
    painter.setBrush(QColor(0, 0, 0, 60))
    painter.drawPath(shadow_path)

    # Gradient fill (source → destination)
    grad = QLinearGradient(fx, fy, tx, ty)
    lighter = QColor(color).lighter(150); lighter.setAlpha(210)
    darker  = QColor(color).darker(130);  darker.setAlpha(210)
    grad.setColorAt(0.0, lighter)
    grad.setColorAt(1.0, darker)
    painter.setPen(QPen(QColor(color).darker(160), max(1, sz * 0.008),
                        Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
    painter.setBrush(QBrush(grad))
    painter.drawPath(path)

    # Inner specular highlight
    highlight = QPainterPath()
    highlight.moveTo(sx + nx * shaft_half * 0.2, sy + ny * shaft_half * 0.2)
    highlight.lineTo(neck_x + nx * shaft_half * 0.2, neck_y + ny * shaft_half * 0.2)
    painter.setPen(QPen(QColor(255, 255, 255, 70), max(1, sz * 0.022),
                        Qt.SolidLine, Qt.RoundCap))
    painter.setBrush(Qt.NoBrush)
    painter.drawPath(highlight)

    # Small bright dot at the tip for extra pop
    painter.setPen(Qt.NoPen)
    painter.setBrush(QColor(255, 255, 255, 55))
    painter.drawEllipse(QPointF(ex, ey), sz * 0.03, sz * 0.03)

    painter.restore()


def _draw_arrow_minimal(painter, fx, fy, tx, ty, color, sz):
    """Thin, subtle arrow — low opacity, small head."""
    dx = tx - fx; dy = ty - fy
    dist = max(1, math.hypot(dx, dy))
    if dist < 1:
        return

    margin = sz * 0.22
    fx2 = fx + dx * margin / dist; fy2 = fy + dy * margin / dist
    tx2 = tx - dx * margin / dist; ty2 = ty - dy * margin / dist

    subtle = QColor(color); subtle.setAlpha(130)

    painter.setPen(QPen(subtle, max(1.5, sz * 0.022), Qt.SolidLine, Qt.RoundCap))
    painter.drawLine(QPointF(fx2, fy2), QPointF(tx2, ty2))

    angle = math.atan2(dy, dx); a_sz = sz * 0.14
    p1x = tx2 - a_sz * math.cos(angle - 0.4)
    p1y = ty2 - a_sz * math.sin(angle - 0.4)
    p2x = tx2 - a_sz * math.cos(angle + 0.4)
    p2y = ty2 - a_sz * math.sin(angle + 0.4)

    tri = QPolygonF([QPointF(tx2, ty2), QPointF(p1x, p1y), QPointF(p2x, p2y)])
    painter.setBrush(subtle); painter.setPen(Qt.NoPen)
    painter.drawPolygon(tri)

_PIECE_TYPE_MAP = {'K': chess.KING, 'Q': chess.QUEEN, 'R': chess.ROOK, 'B': chess.BISHOP, 'N': chess.KNIGHT, 'P': chess.PAWN,
                   'k': chess.KING, 'q': chess.QUEEN, 'r': chess.ROOK, 'b': chess.BISHOP, 'n': chess.KNIGHT, 'p': chess.PAWN}

def _reconstruct_piece(symbol):
    pt = _PIECE_TYPE_MAP.get(symbol)
    if pt is None: return None
    return chess.Piece(pt, chess.WHITE if symbol.isupper() else chess.BLACK)

def render_board_image(board, last_move=None, selected=None, legal_targets=None,
                       check_squares=None, anim_state=None, sq_size=SQ_SIZE,
                       show_arrow=True, theme=None, flipped=False, arrow_style=None,
                       static_only=False):
    if theme is None: theme = THEMES["Classic"]
    sz = sq_size
    img = QImage(sz * 8, sz * 8, QImage.Format_ARGB32_Premultiplied)
    img.fill(Qt.transparent)
    with paint_context(img) as p:
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.TextAntialiasing)
        (font_piece, font_coord, *_) = get_render_assets(sz)
        check_set = set(check_squares or []); skip_sq = set()
        if anim_state: skip_sq.add(anim_state['from']); skip_sq.add(anim_state['to'])
        b2s = (lambda br, bc: (7 - br, 7 - bc)) if flipped else (lambda br, bc: (br, bc))
        effective_move = None
        if anim_state: effective_move = (anim_state['from'], anim_state['to'])
        elif last_move: effective_move = last_move
        
        # 1. Draw board squares and highlights
        for sq in chess.SQUARES:
            br, bc = 7 - chess.square_rank(sq), chess.square_file(sq)
            sr, sc = b2s(br, bc); x, y = sc * sz, sr * sz
            is_light = (br + bc) % 2 == 0
            p.fillRect(x, y, sz, sz, theme.light_sq if is_light else theme.dark_sq)
            if effective_move and (br, bc) in effective_move: p.fillRect(x, y, sz, sz, theme.last_move)
            if selected and (br, bc) == selected: p.fillRect(x, y, sz, sz, theme.highlight)
            if (br, bc) in check_set:
                grad = QRadialGradient(x + sz / 2, y + sz / 2, sz * 0.7)
                grad.setColorAt(0, QColor(255, 30, 30, 180)); grad.setColorAt(1, QColor(255, 0, 0, 0))
                p.setBrush(QBrush(grad)); p.setPen(Qt.NoPen); p.drawRect(x, y, sz, sz)
            if legal_targets and (br, bc) in legal_targets:
                cx, cy = x + sz // 2, y + sz // 2
                if board.piece_at(sq) is not None:
                    p.setPen(QPen(QColor(0, 0, 0, 90), max(3, sz // 14))); p.setBrush(Qt.NoBrush)
                    p.drawEllipse(cx - sz * 5 // 12, cy - sz * 5 // 12, sz * 10 // 12, sz * 10 // 12)
                else:
                    p.setPen(Qt.NoPen); p.setBrush(QColor(0, 0, 0, 90))
                    p.drawEllipse(cx - sz // 6, cy - sz // 6, sz // 3, sz // 3)
                    
        # 2. Draw static pieces (skips 'from' and 'to' squares if animating)
        for sq in chess.SQUARES:
            br, bc = 7 - chess.square_rank(sq), chess.square_file(sq)
            if (br, bc) in skip_sq: continue
            piece = board.piece_at(sq)
            if piece: sr, sc = b2s(br, bc); _draw_piece(p, piece, sr, sc, sz, font_piece)
            
        if not static_only:
            # 3. Draw captured piece fade (if animating)
            if anim_state and anim_state.get('captured', '.') != '.':
                bfr, bfc_ = anim_state['from']; btr, btc_ = anim_state['to']
                cap_piece = _reconstruct_piece(anim_state['captured'])
                if cap_piece is not None:
                    fade = max(0, int(200 * (1.0 - anim_state['progress'])))
                    p.setOpacity(fade / 255.0)
                    sr, sc = b2s(btr, btc_); _draw_piece(p, cap_piece, sr, sc, sz, font_piece)
                    p.setOpacity(1.0)
                    
            # 4. Draw arrow
            if show_arrow and effective_move:
                (bfr, bfc), (btr, btc) = effective_move
                sfr, sfc = b2s(bfr, bfc); str_, stc = b2s(btr, btc)
                _draw_arrow(p, sfc * sz + sz // 2, sfr * sz + sz // 2,
                            stc * sz + sz // 2, str_ * sz + sz // 2, theme.arrow_clr, sz, arrow_style)
                            
            # ── 5. Draw animated piece ──
            if anim_state:
                bfr, bfc_ = anim_state['from']; btr, btc_ = anim_state['to']
                t = anim_state['progress']; anim_obj = anim_state.get('piece_obj')
                if anim_obj:
                    # Increased lift and scale for a more pronounced, non-shrinking pop effect
                    lift = 4.0 * t * (1.0 - t) * 0.20
                    scale = 1.0 + 4.0 * t * (1.0 - t) * 0.15  # Grows up to 15% larger
                    
                    ir = bfr + (btr - bfr) * t; ic = bfc_ + (btc_ - bfc_) * t
                    sir, sic = b2s(ir, ic)
                    
                    # Dynamic shadow that scales with the piece to prevent optical shrinking illusions
                    shadow_w = sz * 0.65 * scale
                    shadow_h = sz * 0.12 * scale
                    sa = 30 + int(70 * (lift / 0.20))
                    
                    p.setPen(Qt.NoPen)
                    p.setBrush(QColor(0, 0, 0, sa))
                    
                    # Center shadow under the piece, with a slight right/down offset
                    piece_center_x = sic * sz + sz / 2
                    shadow_x = piece_center_x - shadow_w / 2 + (sz * 0.05 * scale)
                    shadow_y = sir * sz + sz * 0.85
                    
                    p.drawEllipse(QRectF(shadow_x, shadow_y, shadow_w, shadow_h))
                    
                    _draw_piece_at(p, anim_obj, (sir * sz - sz * lift) / sz, sic,
                                sz, sz * scale, sz * scale, font_piece)
                                   
        # 6. Draw coordinates (always drawn, even for static_only)
        p.setFont(font_coord); cm = max(3, int(sz * 0.04)); cs = max(12, sz // 5)
        for c in range(8):
            is_light = (7 + c) % 2 == 0
            p.setPen(theme.dark_sq if is_light else theme.light_sq)
            p.drawText(QRect(c * sz + sz - cs - cm, 7 * sz + cm, cs, cs),
                       Qt.AlignCenter, FILES_STR[7 - c if flipped else c])
        for r in range(8):
            is_light = r % 2 == 0
            p.setPen(theme.dark_sq if is_light else theme.light_sq)
            p.drawText(QRect(cm, r * sz + cm, cs, cs),
                       Qt.AlignCenter, RANKS_STR[7 - r if flipped else r])
                       
    return img



class CompositeLayout:
    def __init__(self, width, height, sq_size=None, is_vertical=False, is_square=False, is_board_only=False, show_title=False):
        self.w = width
        self.h = height
        self.vert = is_vertical
        self.show_title = show_title
        self.is_board_only = is_board_only
        self.sf = min(width, height) / 1080.0

        if is_board_only:
            self._board_only_layout(sq_size)
        elif is_vertical:
            self._vert_layout(sq_size)
        else:
            self._horiz_layout(sq_size)

    def _make_sq(self, raw_pixels):
        """Round down to nearest multiple of 8, minimum 8."""
        return max(8, (int(raw_pixels) // 8) * 8)

    def _board_only_layout(self, sq_size):
        self.pad = max(4, int(min(self.w, self.h) * 0.01))
        self.title_h = 0

        if sq_size is None:
            board_px = min(self.w, self.h) - (self.pad * 2)
            self.sq_size = self._make_sq(board_px / 8)
        else:
            self.sq_size = sq_size

        self.bpx = self.sq_size * 8
        self.bx = (self.w - self.bpx) // 2
        self.by = (self.h - self.bpx) // 2
        self.mx = self.my = self.mw = self.mh = 0

    def _horiz_layout(self, sq_size):
        self.pad = max(8, int(12 * self.sf))
        self.title_h = max(44, int(80 * self.sf)) if self.show_title else 0
        gap = self.pad  # gap between board and move list

        # --- Move list width: reasonable range for readability ---
        min_mw = max(180, int(220 * self.sf))
        max_mw = max(280, int(self.w * 0.35))
        target_mw = min(max_mw, max(min_mw, int(280 * self.sf)))

        # --- Max board that fits alongside the target move list ---
        max_board_w = self.w - target_mw - gap - self.pad * 2
        max_board_h = self.h - self.title_h - self.pad * 3

        if sq_size is None:
            self.sq_size = self._make_sq(min(max_board_w, max_board_h) / 8)
        else:
            self.sq_size = max(8, sq_size)

        self.bpx = self.sq_size * 8

        # --- Move list fills remaining horizontal space, clamped ---
        remaining_w = self.w - self.bpx - gap - self.pad * 2
        if remaining_w < min_mw:
            actual_mw = max(80, remaining_w)
        else:
            actual_mw = max(min_mw, min(max_mw, remaining_w))

        # --- Center the board+movelist group horizontally ---
        total_content_w = self.bpx + gap + actual_mw
        group_x = (self.w - total_content_w) // 2

        # --- Center board vertically in the space below the title ---
        vert_space = self.h - self.title_h - self.pad * 2
        board_y = self.title_h + self.pad + max(0, (vert_space - self.bpx) // 2)

        self.bx = group_x
        self.by = board_y
        self.mx = group_x + self.bpx + gap
        self.my = board_y
        self.mw = actual_mw
        self.mh = self.bpx

    def _vert_layout(self, sq_size):
        self.pad = max(8, int(14 * self.sf))
        self.title_h = max(36, int(50 * self.sf)) if self.show_title else 0
        gap = self.pad  # gap between board and move list

        # --- Move list height: reasonable range for readability ---
        min_mh = max(120, int(150 * self.sf))
        max_mh = max(180, int(self.h * 0.35))
        target_mh = min(max_mh, max(min_mh, int(200 * self.sf)))

        # --- Max board that fits above the target move list ---
        max_board_w = self.w - self.pad * 2
        max_board_h = self.h - self.title_h - target_mh - gap - self.pad * 3

        if sq_size is None:
            self.sq_size = self._make_sq(min(max_board_w, max_board_h) / 8)
        else:
            self.sq_size = max(8, sq_size)

        self.bpx = self.sq_size * 8

        # --- Move list fills remaining vertical space, clamped ---
        remaining_h = self.h - self.title_h - self.bpx - gap - self.pad * 3
        if remaining_h < min_mh:
            actual_mh = max(60, remaining_h)
        else:
            actual_mh = max(min_mh, min(max_mh, remaining_h))

        # --- Center board horizontally ---
        board_x = (self.w - self.bpx) // 2

        # --- Center the board+movelist group vertically below title ---
        total_content_h = self.bpx + gap + actual_mh
        vert_space = self.h - self.title_h - self.pad * 2
        group_y = self.title_h + self.pad + max(0, (vert_space - total_content_h) // 2)

        self.bx = board_x
        self.by = group_y
        self.mx = board_x          # move list matches board width
        self.my = group_y + self.bpx + gap
        self.mw = self.bpx
        self.mh = actual_mh

def render_composite_frame(board, notations, current_move_idx, last_move=None, check_squares=None,
                           anim_state=None, anim_move_idx=-1,
                           width=1920, height=1080, sq_size=None, theme=None, flipped=False,
                           bg_color=(26, 26, 46), arrow_style=None, is_board_only=False,
                           static_board_img=None): 
    is_vert = height > width; is_sq = (width == height)
    layout = CompositeLayout(width, height, sq_size=sq_size, is_vertical=is_vert, is_square=is_sq, is_board_only=is_board_only, show_title=not is_board_only)
    sq = layout.sq_size; sf = layout.sf
    img = QImage(width, height, QImage.Format_ARGB32_Premultiplied)
    bg = QColor(*bg_color); img.fill(bg)
    
    with paint_context(img) as p:
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.TextAntialiasing)
            
        # FAST PATH: Use pre-rendered static board + overlay anim elements
        if static_board_img is not None and anim_state is not None:
            p.drawImage(layout.bx, layout.by, static_board_img)
            # Save painter state and translate origin to the top-left of the board
            p.save()
            p.translate(layout.bx, layout.by)
            
            bfr, bfc = anim_state['from']; btr, btc = anim_state['to']
            
            if arrow_style != ARROW_STYLE_NONE:
                b2s = (lambda br, bc: (7 - br, 7 - bc)) if flipped else (lambda br, bc: (br, bc))
                sfr, sfc = b2s(bfr, bfc); str_, stc = b2s(btr, btc)
                _draw_arrow(p, sfc * sq + sq // 2, sfr * sq + sq // 2,
                            stc * sq + sq // 2, str_ * sq + sq // 2, theme.arrow_clr, sq, arrow_style)
            t = anim_state['progress']; anim_obj = anim_state.get('piece_obj')
            if anim_obj:
                lift = 4.0 * t * (1.0 - t) * 0.15; scale = 1.0 + 4.0 * t * (1.0 - t) * 0.08
                ir = bfr + (btr - bfr) * t; ic = bfc + (btc - bfc) * t
                b2s = (lambda br, bc: (7 - br, 7 - bc)) if flipped else (lambda br, bc: (br, bc))
                sir, sic = b2s(ir, ic)
                sa = 30 + int(70 * (lift / 0.15))
                p.setPen(Qt.NoPen); p.setBrush(QColor(0, 0, 0, sa))
                p.drawEllipse(QRectF(sic * sq + (sq * scale - sq * 0.65) / 2,
                                     sir * sq + sq * 0.82, sq * 0.65, sq * 0.12))
                (font_piece, _, *_) = get_render_assets(sq)
                # Simplified (sir * sq - sq * lift) / sq to just (sir - lift)
                _draw_piece_at(p, anim_obj, sir - lift, sic, sq, sq * scale, sq * scale, font_piece)
            # Restore painter state so the rest of the composite frame (move list, etc.) draws normally
            p.restore()
        else:
            board_img = render_board_image(board, last_move=last_move, check_squares=check_squares,
                                           anim_state=anim_state, sq_size=sq, theme=theme, flipped=flipped, arrow_style=arrow_style)
            p.drawImage(layout.bx, layout.by, board_img)
        
        if layout.mw > 20 and layout.mh > 20:
            display_idx = anim_move_idx if anim_move_idx >= 0 else current_move_idx
            _draw_move_list(p, notations, display_idx, layout, bg_color, sf)
            
    return img

def _draw_move_list(p, notations, current_idx, layout, bg_color, sf):
    mx, my, mw, mh = layout.mx, layout.my, layout.mw, layout.mh
    
    # ── Background panel ──
    panel_bg = QColor(*bg_color).lighter(115)
    p.setPen(Qt.NoPen); p.setBrush(panel_bg)
    radius = max(6, int(10 * sf))
    p.drawRoundedRect(QRectF(mx, my, mw, mh), radius, radius)
    
    # ── Header (Larger and more prominent) ──
    hdr_h = max(32, int(48 * sf))
    hdr_fs = max(14, int(24 * sf))
    p.setFont(QFont("Sans", hdr_fs, QFont.Bold))
    p.setPen(QColor(140, 140, 160))
    p.drawText(QRectF(mx + int(16 * sf), my + int(6 * sf), mw - int(32 * sf), hdr_h),
               Qt.AlignVCenter | Qt.AlignLeft, "MOVES")
    
    # ── Separator ──
    sep_y = my + hdr_h + int(6 * sf)
    p.setPen(QPen(QColor(80, 80, 100), max(1.5, 1.5 * sf)))
    p.drawLine(int(mx + int(16 * sf)), int(sep_y), int(mx + mw - int(16 * sf)), int(sep_y))
    
    # ── Row & Font Setup (Significantly larger for better readability at any resolution) ──
    row_h = max(32, int(44 * sf))
    fs = max(16, int(22 * sf))
    move_font = QFont("Monospace", fs)
    move_font_active = QFont("Monospace", fs, QFont.Bold)
    num_font = QFont("Sans", max(14, int(fs * 0.85)))
    
    content_y = sep_y + int(8 * sf)
    available_h = my + mh - content_y - int(12 * sf)
    max_rows = max(1, available_h // row_h)
    
    # ── Parse Notation Pairs ──
    pairs = []
    for i in range(0, len(notations), 2):
        w_move = notations[i] if i < len(notations) else ""
        b_move = notations[i + 1] if i + 1 < len(notations) else ""
        pairs.append((i + 1, w_move, b_move, i, i + 1 if i + 1 < len(notations) else -1))
    
    # ── Auto-Scroll Logic ──
    scroll = 0
    if len(pairs) > max_rows:
        cur_pair = current_idx // 2 if current_idx >= 0 else 0
        scroll = max(0, min(cur_pair - max_rows // 2, len(pairs) - max_rows))
    
    col_num_w = max(32, int(mw * 0.15))
    col_w = (mw - col_num_w - int(24 * sf)) / 2.0
    
    highlight_clr = QColor(42, 130, 218, 70)
    active_text_clr = QColor(100, 200, 255)
    normal_w_clr = QColor(230, 230, 230)
    normal_b_clr = QColor(190, 190, 200)
    num_clr = QColor(120, 120, 140)
    
    # ── Draw Rows ──
    for row_i in range(max_rows):
        pi = scroll + row_i
        if pi >= len(pairs): break
        move_num, w_txt, b_txt, w_idx, b_idx = pairs[pi]
        ry = content_y + row_i * row_h
        
        w_active = (current_idx == w_idx and w_txt)
        b_active = (current_idx == b_idx and b_txt)
        
        # Highlight backgrounds
        if w_active:
            p.setPen(Qt.NoPen); p.setBrush(highlight_clr)
            p.drawRoundedRect(QRectF(mx + col_num_w + int(12 * sf), ry, col_w, row_h - 2),
                              max(3, int(4 * sf)), max(3, int(4 * sf)))
        if b_active:
            p.setPen(Qt.NoPen); p.setBrush(highlight_clr)
            p.drawRoundedRect(QRectF(mx + col_num_w + int(12 * sf) + col_w + int(4 * sf), ry, col_w, row_h - 2),
                              max(3, int(4 * sf)), max(3, int(4 * sf)))
        
        # Move number
        p.setFont(num_font); p.setPen(num_clr)
        p.drawText(QRectF(mx + int(12 * sf), ry, col_num_w, row_h - 2),
                   Qt.AlignVCenter | Qt.AlignRight, f"{move_num}.")
        
        # White move
        if w_active: p.setFont(move_font_active); p.setPen(active_text_clr)
        else: p.setFont(move_font); p.setPen(normal_w_clr)
        if w_txt:
            p.drawText(QRectF(mx + col_num_w + int(16 * sf), ry, col_w, row_h - 2),
                       Qt.AlignVCenter | Qt.AlignLeft, w_txt)
        
        # Black move
        if b_active: p.setFont(move_font_active); p.setPen(active_text_clr)
        else: p.setFont(move_font); p.setPen(normal_b_clr)
        if b_txt:
            p.drawText(QRectF(mx + col_num_w + int(16 * sf) + col_w + int(8 * sf), ry, col_w, row_h - 2),
                       Qt.AlignVCenter | Qt.AlignLeft, b_txt)
            
def _draw_fitted_text(painter, rect, text, base_font, max_size_px=None, min_size_px=10, flags=Qt.AlignCenter | Qt.TextWordWrap, color=None):
    """Dynamically scales font size to fit text within a rect without truncation (Highly Optimized O(1))."""
    original_pen = painter.pen()
    if color is not None:
        painter.setPen(QPen(color))
    
    family = base_font.family()
    bold = base_font.bold()
    min_size_px = int(min_size_px)
    max_size_px = int(max_size_px or base_font.pixelSize())
    
    q_rect = QRect(int(rect.x()), int(rect.y()), int(rect.width()), int(rect.height()))
    
    # 1. Fast path: Try max size first (covers 80% of cases instantly)
    trial_font = _make_font(family, max_size_px, bold)
    painter.setFont(trial_font)
    fm = painter.fontMetrics()
    br = fm.boundingRect(q_rect, int(flags), text)
    
    if br.width() <= rect.width() and br.height() <= rect.height():
        painter.drawText(rect, int(flags), text)
        painter.setPen(original_pen)
        return

    # 2. Calculate approximate scale factor to fit
    # We use a 0.92 safety margin to account for word-wrap rounding differences at smaller sizes
    scale_w = rect.width() / br.width() if br.width() > 0 else 1.0
    scale_h = rect.height() / br.height() if br.height() > 0 else 1.0
    scale = min(scale_w, scale_h) * 0.92
    
    estimated_size = int(max_size_px * scale)
    estimated_size = max(min_size_px, min(max_size_px, estimated_size))
    
    # 3. Verify and adjust downward if needed (usually takes only 1-2 iterations max)
    for size in range(estimated_size, min_size_px - 1, -1):
        trial_font = _make_font(family, size, bold)
        painter.setFont(trial_font)
        fm = painter.fontMetrics()
        br = fm.boundingRect(q_rect, int(flags), text)
        if br.width() <= rect.width() and br.height() <= rect.height():
            painter.drawText(rect, int(flags), text)
            painter.setPen(original_pen)
            return
            
    # 4. Fallback to absolute minimum size
    fallback_font = _make_font(family, min_size_px, bold)
    painter.setFont(fallback_font)
    painter.drawText(rect, int(flags), text)
    painter.setPen(original_pen)


def render_export_title_card(opening_name, eco, num_moves, width=1920, height=1080, bg_color=(26, 26, 46)):
    img = QImage(width, height, QImage.Format_ARGB32_Premultiplied)
    bg = QColor(*bg_color)
    img.fill(bg)
    with paint_context(img) as p:
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.TextAntialiasing)
        sf = min(width, height) / 1080.0
        margin = max(12, int(60 * sf))
        
        # Background gradient
        grad = QLinearGradient(0, 0, 0, height)
        grad.setColorAt(0, bg.lighter(130))
        grad.setColorAt(0.5, bg)
        grad.setColorAt(1, bg.lighter(110))
        p.fillRect(0, 0, width, height, grad)
        
        # Watermark
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(255, 255, 255, 12))
        wm_px = max(16, int(480 * sf))
        wm_font = QFont("Segoe UI Emoji")
        wm_font.setPixelSize(wm_px)
        p.setFont(wm_font)
        p.drawText(QRectF(0, 0, width, height), Qt.AlignCenter, "♚")
        
        # Separator Line (Defined BEFORE it is used below)
        lw = width * 0.4
        pen_w = max(1.0, 2.0 * sf)
        line_y = int(height * 0.45)
        p.setPen(QPen(QColor(100, 100, 140, 120), pen_w))
        p.drawLine(int((width - lw) / 2), line_y, int((width + lw) / 2), line_y)
        
        # Smart Title Fitting (Opening Name)
        title_rect = QRectF(margin, height * 0.15, width - 2 * margin, height * 0.25)
        base_title_font = _make_font(_font_family_sans(), 64 * sf, bold=True)
        _draw_fitted_text(p, title_rect, opening_name, base_title_font, max_size_px=64*sf, min_size_px=24*sf, flags=Qt.AlignCenter | Qt.TextWordWrap, color=QColor(240, 240, 245))
        
        # Smart Info Fitting (Themes & Moves)
        info = f"Themes: {eco}   ·   {num_moves} half-moves"
        info_rect = QRectF(margin, line_y + int(20 * sf), width - 2 * margin, height * 0.15)
        base_info_font = _make_font(_font_family_sans(), 28 * sf)
        _draw_fitted_text(p, info_rect, info, base_info_font, max_size_px=28*sf, min_size_px=16*sf, flags=Qt.AlignCenter | Qt.TextWordWrap, color=QColor(160, 160, 190))
        
    return img

def render_export_end_screen(opening_name, eco, num_moves, width=1920, height=1080, bg_color=(26, 26, 46)):
    img = QImage(width, height, QImage.Format_ARGB32_Premultiplied)
    bg = QColor(*bg_color)
    img.fill(bg)
    with paint_context(img) as p:
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.TextAntialiasing)
        sf = min(width, height) / 1080.0
        margin = max(12, int(60 * sf))
        
        # Background gradient
        grad = QLinearGradient(0, 0, 0, height)
        grad.setColorAt(0, bg)
        grad.setColorAt(0.5, bg.lighter(120))
        grad.setColorAt(1, bg)
        p.fillRect(0, 0, width, height, grad)
        
        # Watermark
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(255, 255, 255, 8))
        wm_px = max(16, int(380 * sf))
        wm_font = QFont("Segoe UI Emoji")
        wm_font.setPixelSize(wm_px)
        p.setFont(wm_font)
        p.drawText(QRectF(0, 0, width, height), Qt.AlignCenter, "♛")
        
        # Thanks header
        thanks_rect = QRectF(margin, height * 0.18, width - 2 * margin, height * 0.12)
        base_thanks_font = _make_font(_font_family_sans(), 64 * sf, bold=True)
        _draw_fitted_text(p, thanks_rect, "Thanks for Watching!", base_thanks_font, max_size_px=64*sf, min_size_px=32*sf, flags=Qt.AlignCenter | Qt.TextWordWrap, color=QColor(240, 240, 245))
        
        # Name & Themes
        name_text = f"{opening_name}  ·  Themes: {eco}"
        name_rect = QRectF(margin, height * 0.30, width - 2 * margin, height * 0.12)
        base_name_font = _make_font(_font_family_sans(), 36 * sf)
        _draw_fitted_text(p, name_rect, name_text, base_name_font, max_size_px=36*sf, min_size_px=20*sf, flags=Qt.AlignCenter | Qt.TextWordWrap, color=QColor(160, 160, 190))
        
        # Separator Line
        lw = width * 0.35
        pen_w = max(1.0, 2.0 * sf)
        line_y = int(height * 0.48)
        p.setPen(QPen(QColor(100, 100, 140, 100), pen_w))
        p.drawLine(int((width - lw) / 2), line_y, int((width + lw) / 2), line_y)
        
        # Prominent YouTube-branded red SUBSCRIBE button
        btn_w = max(240, int(360 * sf))
        btn_h = max(48, int(72 * sf))
        btn_x = int((width - btn_w) / 2)
        btn_y = int(height * 0.56)
        btn_rect = QRectF(btn_x, btn_y, btn_w, btn_h)
        
        # Button shadow
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(0, 0, 0, 60))
        p.drawRoundedRect(QRectF(btn_x + 2, btn_y + 3, btn_w, btn_h), btn_h / 2.0, btn_h / 2.0)
        
        # Button background (YouTube Red)
        p.setBrush(QColor(255, 0, 0))
        p.drawRoundedRect(btn_rect, btn_h / 2.0, btn_h / 2.0)
        
        # Button text
        p.setPen(QColor(255, 255, 255))
        btn_font = QFont("Sans", max(16, int(32 * sf)), QFont.Bold)
        p.setFont(btn_font)
        p.drawText(btn_rect, Qt.AlignCenter, "SUBSCRIBE")
        
        # Like text (Correctly placed AFTER btn_y is defined, and using base_like_font)
        like_rect = QRectF(margin, btn_y + btn_h + int(24 * sf), width - 2 * margin, height * 0.08)
        base_like_font = _make_font(_font_family_sans(), 26 * sf)
        _draw_fitted_text(p, like_rect, "Like if this opening helped you!", base_like_font, max_size_px=26*sf, min_size_px=16*sf, flags=Qt.AlignCenter | Qt.TextWordWrap, color=QColor(140, 160, 200))
        
    return img

# ═══════════════════════════════════════════════════════════════════════════════
#  SQLITE-BACKED DATA PROVIDER — FAST 3500+ LOADING WITH PAGINATION
# ═══════════════════════════════════════════════════════════════════════════════

class DataProvider:
    """SQLite-backed provider with indexed pagination for instant 3500+ loads."""
    SCHEMA = '''
    CREATE TABLE IF NOT EXISTS openings (
        id          INTEGER PRIMARY KEY,
        name        TEXT NOT NULL DEFAULT '',
        eco         TEXT NOT NULL DEFAULT '',
        pgn         TEXT NOT NULL DEFAULT '',
        uci_moves   TEXT NOT NULL DEFAULT '[]',
        epd         TEXT NOT NULL DEFAULT '',
        display_title TEXT NOT NULL DEFAULT '',
        img_raw     TEXT NOT NULL DEFAULT '',
        num_moves   INTEGER NOT NULL DEFAULT 0
    );
    CREATE INDEX IF NOT EXISTS idx_name ON openings(name);
    CREATE INDEX IF NOT EXISTS idx_eco  ON openings(eco);
    CREATE INDEX IF NOT EXISTS idx_display ON openings(display_title);
    '''

    def __init__(self):
        os.makedirs(DATA_DIR, exist_ok=True)
        self.use_duckdb = HAS_DUCKDB
        self.parquet_path = None
        
        # Locate the parquet file
        possible_names = ["lichess_db_openings.parquet", "lichess-openings.parquet", "openings.parquet", "cache_openings.parquet"]
        for name in possible_names:
            path = os.path.join(DATA_DIR, name)
            if os.path.exists(path):
                self.parquet_path = path
                break

        if self.use_duckdb and self.parquet_path:
            import duckdb
            self._conn = duckdb.connect(database=':memory:')
            # DuckDB queries Parquet directly: INSTANT, zero migration needed!
            self._total_count = self._conn.execute(
                f"SELECT COUNT(*) FROM read_parquet('{self.parquet_path}')"
            ).fetchone()[0]
            log(f"DataProvider ready (DuckDB): {self._total_count} openings", "DATA")
        else:
            # Fallback to SQLite
            self._conn = sqlite3.connect(SQLITE_DB_PATH, check_same_thread=False)
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA synchronous=NORMAL")
            self._conn.execute("PRAGMA cache_size=-64000")
            self._conn.execute("PRAGMA temp_store=MEMORY")
            self._conn.row_factory = sqlite3.Row
            self._ensure_schema()
            self._migrate_from_parquet()
            self._total_count = self._get_count()
            log(f"DataProvider ready (SQLite): {self._total_count} openings", "DATA")

    def _ensure_schema(self):
        self._conn.executescript(self.SCHEMA)
        self._conn.commit()

    def _migrate_from_parquet(self):
        """One-time migration from parquet if SQLite is empty."""
        if self._get_count() > 0:
            return
        if not self.parquet_path:
            log("Parquet file not found. Skipping migration.", "WARN")
            return
        log("Migrating openings from parquet to SQLite...", "DATA")
        try:
            import json
            import base64
            
            if HAS_PANDAS:
                import pandas as pd
                for chunk in pd.read_parquet(self.parquet_path, chunksize=50000):
                    self._import_opening_df(chunk)
            elif HAS_PYARROW:
                import pyarrow.parquet as pq
                pf = pq.ParquetFile(self.parquet_path)
                for batch in pf.iter_batches(batch_size=50000):
                    df = batch.to_pandas()
                    self._import_opening_df(df)
            else:
                log("Cannot migrate: requires pandas or pyarrow", "ERROR")
                return
            log(f"Migration complete: {self._get_count()} openings", "DATA")
        except Exception as e:
            log(f"Migration error: {e}", "ERROR")

    def _import_opening_df(self, df):
        """Transforms parquet columns to match SQLite schema and inserts."""
        import json
        import base64
        
        records = []
        for row in df.itertuples(index=False):
            name = str(getattr(row, 'name', '')) or ''
            eco = str(getattr(row, 'eco', '')) or ''
            pgn = str(getattr(row, 'pgn', '')) or ''
            uci_str = str(getattr(row, 'uci', '')) or ''
            epd = str(getattr(row, 'epd', '')) or ''
            
            # Handle nested 'img' dict (contains 'bytes')
            img_bytes = b''
            img_field = getattr(row, 'img', None)
            if isinstance(img_field, dict) and 'bytes' in img_field:
                img_bytes = img_field['bytes']
            elif hasattr(img_field, 'bytes'):
                img_bytes = img_field.bytes
                
            img_raw = base64.b64encode(img_bytes).decode('utf-8') if img_bytes else ''
            
            # Process UCI moves (split space-separated string into JSON list)
            uci_list = uci_str.split() if uci_str.strip() else []
            uci_moves_json = json.dumps(uci_list)
            num_moves = len(uci_list)
            
            # Generate ID using Python's built-in hash (no zlib)
            id_key = f"{eco}:{name}"
            oid = abs(hash(id_key)) % (2**31)
            
            records.append({
                'id': oid,
                'name': name,
                'eco': eco,
                'pgn': pgn,
                'uci_moves': uci_moves_json,
                'epd': epd,
                'display_title': name,
                'img_raw': img_raw,
                'num_moves': num_moves
            })
            
            if len(records) >= 10000:
                self._insert_openings_batch(records)
                records = []
                
        if records:
            self._insert_openings_batch(records)

    def _insert_openings_batch(self, records):
        """Inserts a batch of transformed records into SQLite."""
        self._conn.executemany(
            '''INSERT OR REPLACE INTO openings
            (id, name, eco, pgn, uci_moves, epd, display_title, img_raw, num_moves)
            VALUES (:id, :name, :eco, :pgn, :uci_moves, :epd, :display_title, :img_raw, :num_moves)''',
            records)
        self._conn.commit()

    def _get_count(self):
        row = self._conn.execute("SELECT COUNT(*) FROM openings").fetchone()
        return row[0]

    @property
    def total_openings(self):
        return self._total_count

    def get_page(self, page=0, per_page=100, sort_col="name", sort_asc=True, theme_filter=""):
        """Return a page of slim opening records for the list view."""
        offset = page * per_page
        direction = "ASC" if sort_asc else "DESC"
        safe_cols = {"name", "eco", "id", "num_moves", "display_title"}
        if sort_col not in safe_cols:
            sort_col = "name"
            
        if self.use_duckdb:
            # DuckDB uses native hash() function
            query = f"""
                SELECT 
                    (abs(hash(name || eco)) % 2147483648) as id,
                    name,
                    eco,
                    name as display_title,
                    CASE WHEN uci IS NULL OR uci = '' THEN 0 ELSE array_length(string_split(uci, ' ')) END as num_moves
                FROM read_parquet('{self.parquet_path}')
            """
            params = []
            if theme_filter:
                query += " WHERE LOWER(name) LIKE LOWER(?) OR LOWER(eco) LIKE LOWER(?)"
                params.extend([f"%{theme_filter}%", f"%{theme_filter}%"])
            
            query += f" ORDER BY {sort_col} {direction} LIMIT ? OFFSET ?"
            params.extend([per_page, offset])
            
            rows = self._conn.execute(query, params).fetchall()
            
            count_query = f"SELECT COUNT(*) FROM read_parquet('{self.parquet_path}')"
            count_params = []
            if theme_filter:
                count_query += " WHERE LOWER(name) LIKE LOWER(?) OR LOWER(eco) LIKE LOWER(?)"
                count_params.extend([f"%{theme_filter}%", f"%{theme_filter}%"])
                
            total = self._conn.execute(count_query, count_params).fetchone()[0]
            
            formatted_rows = [{'id': r[0], 'name': r[1], 'eco': r[2], 'display_title': r[3], 'num_moves': r[4]} for r in rows]
            return formatted_rows, total
            
        else:
            query = "SELECT id, name, eco, display_title, num_moves FROM openings WHERE 1=1"
            params = []
            if theme_filter:
                query += " AND (LOWER(name) LIKE ? OR LOWER(eco) LIKE ?)"
                params.extend([f"%{theme_filter}%", f"%{theme_filter}%"])
            
            query += f" ORDER BY {sort_col} {direction} LIMIT ? OFFSET ?"
            params.extend([per_page, offset])
            
            rows = self._conn.execute(query, params).fetchall()
            
            count_query = "SELECT COUNT(*) FROM openings WHERE 1=1"
            count_params = []
            if theme_filter:
                count_query += " AND (LOWER(name) LIKE ? OR LOWER(eco) LIKE ?)"
                count_params.extend([f"%{theme_filter}%", f"%{theme_filter}%"])
                
            total = self._conn.execute(count_query, count_params).fetchone()[0]
            return [dict(r) for r in rows], total

    def search(self, query, page=0, per_page=100):
        """Full-text search with pagination."""
        return self.get_page(page, per_page, theme_filter=query)

    def get_opening(self, opening_id):
        """Get full record for a single opening."""
        if self.use_duckdb:
            row = self._conn.execute(
                f"""
                SELECT 
                    (abs(hash(name || eco)) % 2147483648) as id,
                    name, eco, pgn, uci, epd, 
                    name as display_title,
                    CASE WHEN uci IS NULL OR uci = '' THEN 0 ELSE array_length(string_split(uci, ' ')) END as num_moves
                FROM read_parquet('{self.parquet_path}') 
                WHERE (abs(hash(name || eco)) % 2147483648) = ?
                """, (opening_id,)
            ).fetchone()
            if row:
                return {
                    'id': row[0], 'name': row[1], 'eco': row[2], 'pgn': row[3],
                    'uci_moves': row[4].split() if row[4] else [],
                    'epd': row[5], 'display_title': row[6], 'num_moves': row[7]
                }
            return None
        else:
            row = self._conn.execute("SELECT * FROM openings WHERE id = ?", (opening_id,)).fetchone()
            if row:
                d = dict(row)
                import json
                if isinstance(d.get('uci_moves'), str):
                    try: d['uci_moves'] = json.loads(d['uci_moves'])
                    except Exception: d['uci_moves'] = []
                return d
            return None

    def get_openings_by_ids(self, ids):
        """Batch fetch multiple openings by id list."""
        if not ids:
            return []
        placeholders = ",".join("?" * len(ids))
        if self.use_duckdb:
            rows = self._conn.execute(
                f"""
                SELECT 
                    (abs(hash(name || eco)) % 2147483648) as id,
                    name, eco, pgn, uci, epd, 
                    name as display_title,
                    CASE WHEN uci IS NULL OR uci = '' THEN 0 ELSE array_length(string_split(uci, ' ')) END as num_moves
                FROM read_parquet('{self.parquet_path}') 
                WHERE (abs(hash(name || eco)) % 2147483648) IN ({placeholders})
                """, ids
            ).fetchall()
            return [{
                'id': r[0], 'name': r[1], 'eco': r[2], 'pgn': r[3],
                'uci_moves': r[4].split() if r[4] else [],
                'epd': r[5], 'display_title': r[6], 'num_moves': r[7]
            } for r in rows]
        else:
            rows = self._conn.execute(f"SELECT * FROM openings WHERE id IN ({placeholders})", ids).fetchall()
            results = []
            import json
            for row in rows:
                d = dict(row)
                if isinstance(d.get('uci_moves'), str):
                    try: d['uci_moves'] = json.loads(d['uci_moves'])
                    except Exception: d['uci_moves'] = []
                results.append(d)
            return results
            
    def get_all_slim(self):
        """Get all slim records (id, name, eco) — for batch selection."""
        if self.use_duckdb:
            rows = self._conn.execute(
                f"""
                SELECT (abs(hash(name || eco)) % 2147483648) as id, name, eco, name as display_title, 
                       CASE WHEN uci IS NULL OR uci = '' THEN 0 ELSE array_length(string_split(uci, ' ')) END as num_moves
                FROM read_parquet('{self.parquet_path}')
                ORDER BY name ASC
                """
            ).fetchall()
            return [{'id': r[0], 'name': r[1], 'eco': r[2], 'display_title': r[3], 'num_moves': r[4]} for r in rows]
        else:
            rows = self._conn.execute(
                "SELECT id, name, eco, display_title, num_moves FROM openings ORDER BY name ASC"
            ).fetchall()
            return [dict(r) for r in rows]

    def clear_all(self):
        if not self.use_duckdb:
            self._conn.execute("DELETE FROM openings")
            self._conn.commit()
            self._total_count = 0

    def close(self):
        self._conn.close()

# ═══════════════════════════════════════════════════════════════════════════════
#  PAGINATED OPENINGS LIST WIDGET
# ═══════════════════════════════════════════════════════════════════════════════

class PaginatedOpeningsWidget(QWidget):
    """Fast paginated list with search, sorting, and selection for batch rendering."""

    opening_selected = Signal(int)   # opening id
    selection_changed = Signal(list) # list of selected ids

    PAGE_SIZE = 100

    def __init__(self, data_provider: DataProvider, parent=None):
        super().__init__(parent)
        self.dp = data_provider
        self._current_page = 0
        self._total_pages = 1
        self._search_query = ""
        self._search_total = 0
        self._is_searching = False
        self._selected_ids = set()
        self._sort_col = "name"
        self._sort_asc = True
        self._last_range_anchor = None  # for shift-click range select

        self._build_ui()
        self._refresh()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        # ── Search bar ──
        search_row = QHBoxLayout()
        search_row.setSpacing(4)
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Search openings by name or ECO...")
        self.search_input.setClearButtonEnabled(True)
        self.search_input.textChanged.connect(self._on_search_changed)
        search_row.addWidget(self.search_input)
        layout.addLayout(search_row)

        # ── Batch selection toolbar ──
        batch_row = QHBoxLayout()
        batch_row.setSpacing(4)
        self.btn_select_all = QPushButton("Select All")
        self.btn_select_all.setFixedHeight(26)
        self.btn_select_all.setStyleSheet(
            "QPushButton{background:#2a82da;color:#fff;border:none;border-radius:3px;padding:2px 8px;font-size:11px}"
            "QPushButton:hover{background:#3a92ea}")
        self.btn_select_all.clicked.connect(self._select_all)
        batch_row.addWidget(self.btn_select_all)

        self.btn_select_page = QPushButton("Select Page")
        self.btn_select_page.setFixedHeight(26)
        self.btn_select_page.setStyleSheet(
            "QPushButton{background:#3a3a4a;color:#ddd;border:none;border-radius:3px;padding:2px 8px;font-size:11px}"
            "QPushButton:hover{background:#4a4a5a}")
        self.btn_select_page.clicked.connect(self._select_page)
        batch_row.addWidget(self.btn_select_page)

        self.btn_select_none = QPushButton("Clear Sel.")
        self.btn_select_none.setFixedHeight(26)
        self.btn_select_none.setStyleSheet(
            "QPushButton{background:#3a3a4a;color:#ddd;border:none;border-radius:3px;padding:2px 8px;font-size:11px}"
            "QPushButton:hover{background:#4a4a5a}")
        self.btn_select_none.clicked.connect(self._select_none)
        batch_row.addWidget(self.btn_select_none)

        self.lbl_selected = QLabel("0 selected")
        self.lbl_selected.setStyleSheet("color:#8a8aaa;font-size:11px;")
        batch_row.addWidget(self.lbl_selected)
        batch_row.addStretch()
        layout.addLayout(batch_row)

        # ── Sort controls ──
        sort_row = QHBoxLayout()
        sort_row.setSpacing(4)
        sort_row.addWidget(QLabel("Sort:"))
        self.sort_combo = QComboBox()
        self.sort_combo.addItems(["Name", "ECO", "Moves", "ID"])
        self.sort_combo.setFixedWidth(80)
        self.sort_combo.currentIndexChanged.connect(self._on_sort_changed)
        sort_row.addWidget(self.sort_combo)
        self.btn_sort_dir = QPushButton("↑")
        self.btn_sort_dir.setFixedSize(26, 26)
        self.btn_sort_dir.clicked.connect(self._toggle_sort_dir)
        sort_row.addWidget(self.btn_sort_dir)
        sort_row.addStretch()
        layout.addLayout(sort_row)

        # ── Table ──
        self.table = QTableWidget()
        self.table.setColumnCount(4)
        self.table.setHorizontalHeaderLabels(["☑", "Name", "ECO", "Moves"])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Fixed)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Fixed)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.Fixed)
        self.table.setColumnWidth(0, 28)
        self.table.setColumnWidth(2, 55)
        self.table.setColumnWidth(3, 50)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.setShowGrid(False)
        self.table.setAlternatingRowColors(True)
        self.table.setStyleSheet("""
            QTableWidget {
                background-color: #1e1e2a;
                alternate-background-color: #22223a;
                color: #ddd;
                font-size: 12px;
                border: 1px solid #333;
                gridline-color: #2a2a3a;
            }
            QTableWidget::item { padding: 3px 4px; }
            QTableWidget::item:selected { background: #2a82da; }
            QHeaderView::section {
                background: #16162a;
                color: #9a9abc;
                font-weight: bold;
                font-size: 11px;
                padding: 4px;
                border: none;
                border-bottom: 1px solid #333;
            }
            QCheckBox { spacing: 0; }
        """)
        self.table.cellClicked.connect(self._on_cell_clicked)
        self.table.cellDoubleClicked.connect(self._on_cell_double_clicked)
        layout.addWidget(self.table, 1)

        # ── Pagination controls ──
        page_row = QHBoxLayout()
        page_row.setSpacing(4)

        self.btn_first = QPushButton("⏮")
        self.btn_prev = QPushButton("◀")
        self.lbl_page = QLabel("Page 1/1")
        self.btn_next = QPushButton("▶")
        self.btn_last = QPushButton("⏭")

        for btn in (self.btn_first, self.btn_prev, self.btn_next, self.btn_last):
            btn.setFixedSize(30, 26)
            btn.setStyleSheet(
                "QPushButton{background:#2a2a3a;color:#ccc;border:1px solid #444;border-radius:3px}"
                "QPushButton:hover{background:#3a3a5a}")
            page_row.addWidget(btn)

        self.lbl_page.setStyleSheet("color:#9a9abc;font-size:11px;padding:0 6px;")
        page_row.addWidget(self.lbl_page)
        page_row.addStretch()

        self.lbl_total = QLabel("0 openings")
        self.lbl_total.setStyleSheet("color:#6a6a8a;font-size:11px;")
        page_row.addWidget(self.lbl_total)

        layout.addLayout(page_row)

        self.btn_first.clicked.connect(lambda: self._goto_page(0))
        self.btn_prev.clicked.connect(lambda: self._goto_page(self._current_page - 1))
        self.btn_next.clicked.connect(lambda: self._goto_page(self._current_page + 1))
        self.btn_last.clicked.connect(lambda: self._goto_page(self._total_pages - 1))

    # ── Data loading ─────────────────────────────────────────────────────

    def _refresh(self):
        if self._is_searching:
            rows, total = self.dp.search(self._search_query, self._current_page, self.PAGE_SIZE)
            self._search_total = total
            count = total
        else:
            rows, total = self.dp.get_page(self._current_page, self.PAGE_SIZE,
                                           self._sort_col, self._sort_asc)
            count = total
            
        self._total_pages = max(1, (count + self.PAGE_SIZE - 1) // self.PAGE_SIZE)
        self._populate_table(rows)
        self._update_pagination(count)
        self._update_selection_label()

    def _populate_table(self, rows):
        self.table.setRowCount(len(rows))
        for i, rec in enumerate(rows):
            oid = rec['id']
            # Checkbox
            chk_item = QTableWidgetItem()
            chk_item.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled)
            chk_item.setCheckState(Qt.Checked if oid in self._selected_ids else Qt.Unchecked)
            chk_item.setData(Qt.UserRole, oid)
            self.table.setItem(i, 0, chk_item)

            # Name
            name_item = QTableWidgetItem(rec.get('display_title', rec.get('name', '')))
            name_item.setData(Qt.UserRole, oid)
            name_item.setToolTip(rec.get('name', ''))
            self.table.setItem(i, 1, name_item)

            # ECO
            eco_item = QTableWidgetItem(rec.get('eco', ''))
            eco_item.setData(Qt.UserRole, oid)
            self.table.setItem(i, 2, eco_item)

            # Moves
            moves_item = QTableWidgetItem(str(rec.get('num_moves', 0)))
            moves_item.setTextAlignment(Qt.AlignCenter)
            moves_item.setData(Qt.UserRole, oid)
            self.table.setItem(i, 3, moves_item)

        self.table.resizeRowsToContents()

    def _update_pagination(self, count):
        self.lbl_page.setText(f"Page {self._current_page + 1}/{self._total_pages}")
        self.lbl_total.setText(f"{count} openings")
        self.btn_first.setEnabled(self._current_page > 0)
        self.btn_prev.setEnabled(self._current_page > 0)
        self.btn_next.setEnabled(self._current_page < self._total_pages - 1)
        self.btn_last.setEnabled(self._current_page < self._total_pages - 1)

    # ── Interaction ──────────────────────────────────────────────────────

    def _on_cell_clicked(self, row, col):
        item = self.table.item(row, 0)
        if item is None:
            return
        oid = item.data(Qt.UserRole)
        if col == 0:
            # Toggle checkbox
            if oid in self._selected_ids:
                self._selected_ids.discard(oid)
                item.setCheckState(Qt.Unchecked)
            else:
                self._selected_ids.add(oid)
                item.setCheckState(Qt.Checked)
            self._update_selection_label()
            self.selection_changed.emit(list(self._selected_ids))
        else:
            # Single click selects the opening for preview
            self.opening_selected.emit(oid)

    def _on_cell_double_clicked(self, row, col):
        item = self.table.item(row, 0)
        if item:
            self.opening_selected.emit(item.data(Qt.UserRole))

    def _on_search_changed(self, text):
        self._search_query = text.strip()
        self._is_searching = len(self._search_query) > 0
        self._current_page = 0
        self._refresh()

    def _on_sort_changed(self, idx):
        col_map = {0: "name", 1: "eco", 2: "num_moves", 3: "id"}
        self._sort_col = col_map.get(idx, "name")
        self._current_page = 0
        self._refresh()

    def _toggle_sort_dir(self):
        self._sort_asc = not self._sort_asc
        self.btn_sort_dir.setText("↓" if not self._sort_asc else "↑")
        self._current_page = 0
        self._refresh()

    def _goto_page(self, page):
        page = max(0, min(page, self._total_pages - 1))
        if page != self._current_page:
            self._current_page = page
            self._refresh()

    # ── Batch selection ──────────────────────────────────────────────────

    def _select_all(self):
        """Select all openings in the entire database."""
        all_slim = self.dp.get_all_slim()
        self._selected_ids = {r['id'] for r in all_slim}
        self._sync_checkboxes()
        self._update_selection_label()
        self.selection_changed.emit(list(self._selected_ids))

    def _select_page(self):
        """Select only the openings on the current page."""
        for row in range(self.table.rowCount()):
            item = self.table.item(row, 0)
            if item:
                oid = item.data(Qt.UserRole)
                self._selected_ids.add(oid)
                item.setCheckState(Qt.Checked)
        self._update_selection_label()
        self.selection_changed.emit(list(self._selected_ids))

    def _select_none(self):
        self._selected_ids.clear()
        self._sync_checkboxes()
        self._update_selection_label()
        self.selection_changed.emit([])

    def _sync_checkboxes(self):
        for row in range(self.table.rowCount()):
            item = self.table.item(row, 0)
            if item:
                oid = item.data(Qt.UserRole)
                item.setCheckState(Qt.Checked if oid in self._selected_ids else Qt.Unchecked)

    def _update_selection_label(self):
        n = len(self._selected_ids)
        self.lbl_selected.setText(f"{n} selected")

    def get_selected_ids(self):
        return list(self._selected_ids)


# ═══════════════════════════════════════════════════════════════════════════════
#  PREVIEW WIDGET — TITLE CARD & END SCREEN
# ═══════════════════════════════════════════════════════════════════════════════

class PreviewWidget(QWidget):
    """Shows a scaled preview of the title card and end screen for the selected opening."""

    def __init__(self, export_config: ExportConfig, parent=None):
        super().__init__(parent)
        self.config = export_config
        self._opening_name = ""
        self._eco = ""
        self._num_moves = 0
        self._title_img = None
        self._end_img = None
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(4)

        # Title preview
        title_lbl = QLabel("TITLE CARD PREVIEW")
        title_lbl.setStyleSheet("color:#7a7a9a;font-size:10px;font-weight:bold;")
        layout.addWidget(title_lbl)

        self.title_canvas = QLabel()
        self.title_canvas.setFixedSize(240, 135)
        self.title_canvas.setAlignment(Qt.AlignCenter)
        self.title_canvas.setStyleSheet(
            "QLabel{background:#1a1a2e;border:1px solid #333;border-radius:4px;}")
        layout.addWidget(self.title_canvas, 0, Qt.AlignCenter)

        # End screen preview
        end_lbl = QLabel("END SCREEN PREVIEW")
        end_lbl.setStyleSheet("color:#7a7a9a;font-size:10px;font-weight:bold;")
        layout.addWidget(end_lbl)

        self.end_canvas = QLabel()
        self.end_canvas.setFixedSize(240, 135)
        self.end_canvas.setAlignment(Qt.AlignCenter)
        self.end_canvas.setStyleSheet(
            "QLabel{background:#1a1a2e;border:1px solid #333;border-radius:4px;}")
        layout.addWidget(self.end_canvas, 0, Qt.AlignCenter)

        layout.addStretch()

        # Regenerate button
        self.btn_regen = QPushButton("Refresh Preview")
        self.btn_regen.setStyleSheet(
            "QPushButton{background:#2a2a3a;color:#ccc;border:1px solid #444;border-radius:3px;padding:4px 8px}"
            "QPushButton:hover{background:#3a3a5a}")
        self.btn_regen.clicked.connect(self._regenerate)
        layout.addWidget(self.btn_regen)

    def set_opening(self, name, eco, num_moves):
        self._opening_name = name
        self._eco = eco
        self._num_moves = num_moves
        self._regenerate()

    def _regenerate(self):
        preset = self.config.preset
        # Generate small preview images
        pw, ph = 480, 270  # Preview resolution (half of canvas)
        self._title_img = render_export_title_card(
            self._opening_name, self._eco, self._num_moves,
            width=pw, height=ph, bg_color=self.config.bg_color)
        self._end_img = render_export_end_screen(
            self._opening_name, self._eco, self._num_moves,
            width=pw, height=ph, bg_color=self.config.bg_color)
        self._display_previews()

    def _display_previews(self):
        if self._title_img:
            pm = QPixmap.fromImage(self._title_img.scaled(
                self.title_canvas.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation))
            self.title_canvas.setPixmap(pm)
        if self._end_img:
            pm = QPixmap.fromImage(self._end_img.scaled(
                self.end_canvas.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation))
            self.end_canvas.setPixmap(pm)

    def update_config(self, config):
        self.config = config
        self._regenerate()


# ═══════════════════════════════════════════════════════════════════════════════
#  SETTINGS DIALOG — TABBED LAYOUT
# ═══════════════════════════════════════════════════════════════════════════════

class SettingsDialog(QDialog):
    """Clean tabbed settings dialog."""

    def __init__(self, export_config: ExportConfig, parent=None):
        super().__init__(parent)
        self.config = export_config
        self.setWindowTitle("Settings")
        self.setMinimumSize(520, 480)
        self.setStyleSheet("""
            QDialog { background: #1a1a2e; color: #ddd; }
            QTabWidget::pane { border: 1px solid #333; background: #1e1e2e; }
            QTabBar::tab {
                background: #16162a; color: #9a9abc; padding: 8px 16px;
                border: 1px solid #333; border-bottom: none;
                border-top-left-radius: 4px; border-top-right-radius: 4px;
                margin-right: 2px;
            }
            QTabBar::tab:selected { background: #1e1e2e; color: #fff; }
            QGroupBox {
                color: #aab; font-weight: bold; font-size: 12px;
                border: 1px solid #333; border-radius: 4px;
                margin-top: 10px; padding-top: 14px;
            }
            QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 4px; }
            QLabel { color: #ccc; font-size: 12px; }
            QSpinBox, QDoubleSpinBox, QComboBox, QLineEdit {
                background: #2a2a3a; color: #ddd; border: 1px solid #444;
                border-radius: 3px; padding: 3px 6px; font-size: 12px;
            }
            QCheckBox { color: #ccc; font-size: 12px; }
            QCheckBox::indicator { width: 16px; height: 16px; }
            QPushButton {
                background: #2a82da; color: #fff; border: none;
                border-radius: 4px; padding: 6px 16px; font-size: 12px;
            }
            QPushButton:hover { background: #3a92ea; }
            QPushButton#secondary {
                background: #3a3a4a; color: #ccc;
            }
            QPushButton#secondary:hover { background: #4a4a5a; }
            QSlider::groove:horizontal {
                height: 6px; background: #333; border-radius: 3px;
            }
            QSlider::handle:horizontal {
                width: 14px; height: 14px; background: #2a82da;
                border-radius: 7px; margin: -4px 0;
            }
        """)

        self._build_ui()

    def _build_ui(self):
        main_layout = QVBoxLayout(self)

        tabs = QTabWidget()
        tabs.addTab(self._build_video_tab(), "Video")
        tabs.addTab(self._build_title_tab(), "Title Card")
        tabs.addTab(self._build_end_tab(), "End Screen")
        tabs.addTab(self._build_appearance_tab(), "Appearance")
        tabs.addTab(self._build_advanced_tab(), "Advanced")
        main_layout.addWidget(tabs)

        # Dialog buttons
        btn_box = QHBoxLayout()
        btn_box.addStretch()
        apply_btn = QPushButton("Apply")
        apply_btn.clicked.connect(self.accept)
        cancel_btn = QPushButton("Cancel")
        cancel_btn.setObjectName("secondary")
        cancel_btn.clicked.connect(self.reject)
        btn_box.addWidget(cancel_btn)
        btn_box.addWidget(apply_btn)
        main_layout.addLayout(btn_box)

    # ── Video tab ────────────────────────────────────────────────────────

    def _build_video_tab(self):
        w = QWidget()
        lay = QVBoxLayout(w)

        # Preset group
        grp_preset = QGroupBox("Export Preset")
        gl = QVBoxLayout(grp_preset)
        self.combo_preset = QComboBox()
        self.combo_preset.addItems(EXPORT_PRESETS.keys())
        self.combo_preset.setCurrentText(self.config.preset_name)
        self.combo_preset.currentTextChanged.connect(self._on_preset_changed)
        gl.addWidget(QLabel("Format:"))
        gl.addWidget(self.combo_preset)
        self.lbl_preset_info = QLabel()
        self.lbl_preset_info.setStyleSheet("color:#8a8aaa;font-size:11px;")
        gl.addWidget(self.lbl_preset_info)
        self._update_preset_info()
        lay.addWidget(grp_preset)

        # Timing group
        grp_timing = QGroupBox("Animation Timing")
        tl = QGridLayout(grp_timing)
        tl.addWidget(QLabel("Move animation (s):"), 0, 0)
        self.spin_move_anim = QDoubleSpinBox()
        self.spin_move_anim.setRange(0.1, 5.0); self.spin_move_anim.setSingleStep(0.1)
        self.spin_move_anim.setValue(self.config.move_anim_duration)
        tl.addWidget(self.spin_move_anim, 0, 1)

        tl.addWidget(QLabel("Pause after move (s):"), 1, 0)
        self.spin_pause = QDoubleSpinBox()
        self.spin_pause.setRange(0.1, 5.0); self.spin_pause.setSingleStep(0.1)
        self.spin_pause.setValue(self.config.pause_after_move)
        tl.addWidget(self.spin_pause, 1, 1)

        tl.addWidget(QLabel("FPS:"), 2, 0)
        self.spin_fps = QSpinBox()
        self.spin_fps.setRange(10, 120); self.spin_fps.setValue(self.config.fps)
        tl.addWidget(self.spin_fps, 2, 1)
        lay.addWidget(grp_timing)

        lay.addStretch()
        return w

    # ── Title card tab ───────────────────────────────────────────────────

    def _build_title_tab(self):
        w = QWidget()
        lay = QVBoxLayout(w)

        grp = QGroupBox("Title Card")
        gl = QGridLayout(grp)

        self.chk_title_enabled = QCheckBox("Enable title card")
        self.chk_title_enabled.setChecked(self.config.title_enabled)
        gl.addWidget(self.chk_title_enabled, 0, 0, 1, 2)

        gl.addWidget(QLabel("Duration (s):"), 1, 0)
        self.spin_title_dur = QDoubleSpinBox()
        self.spin_title_dur.setRange(1.0, 15.0); self.spin_title_dur.setSingleStep(0.5)
        self.spin_title_dur.setValue(self.config.title_duration)
        gl.addWidget(self.spin_title_dur, 1, 1)

        gl.addWidget(QLabel("Title override:"), 2, 0)
        self.edit_title_text = QLineEdit()
        self.edit_title_text.setPlaceholderText("(use opening name if empty)")
        self.edit_title_text.setText(self.config.title_text_override)
        gl.addWidget(self.edit_title_text, 2, 1)

        lay.addWidget(grp)

        # Inline preview
        preview_lbl = QLabel("Preview:")
        preview_lbl.setStyleSheet("color:#7a7a9a;font-size:10px;font-weight:bold;")
        lay.addWidget(preview_lbl)
        self.title_preview = QLabel()
        self.title_preview.setFixedSize(320, 180)
        self.title_preview.setAlignment(Qt.AlignCenter)
        self.title_preview.setStyleSheet(
            "QLabel{background:#0e0e1e;border:1px solid #333;border-radius:4px;}")
        lay.addWidget(self.title_preview, 0, Qt.AlignCenter)

        self._render_title_preview()
        lay.addStretch()
        return w

    # ── End screen tab ───────────────────────────────────────────────────

    def _build_end_tab(self):
        w = QWidget()
        lay = QVBoxLayout(w)

        grp = QGroupBox("End Screen")
        gl = QGridLayout(grp)

        self.chk_end_enabled = QCheckBox("Enable end screen")
        self.chk_end_enabled.setChecked(self.config.end_title_enabled)
        gl.addWidget(self.chk_end_enabled, 0, 0, 1, 2)

        gl.addWidget(QLabel("Duration (s):"), 1, 0)
        self.spin_end_dur = QDoubleSpinBox()
        self.spin_end_dur.setRange(1.0, 15.0); self.spin_end_dur.setSingleStep(0.5)
        self.spin_end_dur.setValue(self.config.end_title_duration)
        gl.addWidget(self.spin_end_dur, 1, 1)

        gl.addWidget(QLabel("Custom text:"), 2, 0)
        self.edit_end_text = QLineEdit()
        self.edit_end_text.setPlaceholderText("(default: Thanks for watching!)")
        self.edit_end_text.setText(self.config.end_screen_text)
        gl.addWidget(self.edit_end_text, 2, 1)

        lay.addWidget(grp)

        preview_lbl = QLabel("Preview:")
        preview_lbl.setStyleSheet("color:#7a7a9a;font-size:10px;font-weight:bold;")
        lay.addWidget(preview_lbl)
        self.end_preview = QLabel()
        self.end_preview.setFixedSize(320, 180)
        self.end_preview.setAlignment(Qt.AlignCenter)
        self.end_preview.setStyleSheet(
            "QLabel{background:#0e0e1e;border:1px solid #333;border-radius:4px;}")
        lay.addWidget(self.end_preview, 0, Qt.AlignCenter)

        self._render_end_preview()
        lay.addStretch()
        return w

    # ── Appearance tab ───────────────────────────────────────────────────

    def _build_appearance_tab(self):
        w = QWidget()
        lay = QVBoxLayout(w)

        grp_board = QGroupBox("Board Theme")
        bl = QVBoxLayout(grp_board)
        self.combo_theme = QComboBox()
        self.combo_theme.addItems(THEMES.keys())
        self.combo_theme.setCurrentText(self.config.theme_name)
        bl.addWidget(QLabel("Theme:"))
        bl.addWidget(self.combo_theme)

        self.chk_flip = QCheckBox("Flip board (black at bottom)")
        self.chk_flip.setChecked(self.config.flip_board)
        bl.addWidget(self.chk_flip)
        lay.addWidget(grp_board)

        # Arrow style combo
        arrow_label = QLabel("Arrow Style:")
        self.arrow_style_combo = QComboBox()
        for name in ARROW_STYLES_LIST:
            self.arrow_style_combo.addItem(name)
        # Set current from config
        current_arrow_name = next(
            (k for k, v in ARROW_STYLES.items() if v == self.config.arrow_style),
            ARROW_STYLES_LIST[0])
        self.arrow_style_combo.setCurrentText(current_arrow_name)
        self.arrow_style_combo.currentTextChanged.connect(self._on_arrow_style_changed)

        arrow_row = QHBoxLayout()
        arrow_row.addWidget(arrow_label)
        arrow_row.addWidget(self.arrow_style_combo, 1)
        lay.addLayout(arrow_row)

        # Handler
        def _on_arrow_style_changed(self, text):
            style_key = ARROW_STYLES.get(text, ARROW_STYLE_THICK)
            self.config.arrow_style = style_key

        grp_bg = QGroupBox("Background Color")
        bgl = QHBoxLayout(grp_bg)
        self.slider_bg_r = QSlider(Qt.Horizontal); self.slider_bg_r.setRange(0, 255)
        self.slider_bg_g = QSlider(Qt.Horizontal); self.slider_bg_g.setRange(0, 255)
        self.slider_bg_b = QSlider(Qt.Horizontal); self.slider_bg_b.setRange(0, 255)
        r, g, b_ = self.config.bg_color
        self.slider_bg_r.setValue(r); self.slider_bg_g.setValue(g); self.slider_bg_b.setValue(b_)
        for s, lbl in [(self.slider_bg_r, "R"), (self.slider_bg_g, "G"), (self.slider_bg_b, "B")]:
            row = QHBoxLayout()
            row.addWidget(QLabel(lbl))
            row.addWidget(s)
            bgl.addLayout(row)
        self.bg_preview = QLabel()
        self.bg_preview.setFixedSize(40, 40)
        bgl.addWidget(self.bg_preview)
        self._update_bg_preview()
        for s in (self.slider_bg_r, self.slider_bg_g, self.slider_bg_b):
            s.valueChanged.connect(self._update_bg_preview)
        lay.addWidget(grp_bg)

        lay.addStretch()
        return w

    # ── Advanced tab ─────────────────────────────────────────────────────

    def _build_advanced_tab(self):
        w = QWidget()
        lay = QVBoxLayout(w)

        # --- Export Directory Row ---
        dir_label = QLabel("Export Directory:")
        self.output_dir_edit = QLineEdit(self.config.output_dir)
        self.output_dir_edit.setReadOnly(True)

        browse_btn = QPushButton("Browse...")
        browse_btn.clicked.connect(self._on_browse_output_dir)

        dir_layout = QHBoxLayout()
        dir_layout.addWidget(dir_label)
        dir_layout.addWidget(self.output_dir_edit, 1)
        dir_layout.addWidget(browse_btn)
        lay.addLayout(dir_layout)

        grp_ff = QGroupBox("FFmpeg Encoding")
        fl = QGridLayout(grp_ff)

        fl.addWidget(QLabel("CRF (quality):"), 0, 0)
        self.spin_crf = QSpinBox()
        self.spin_crf.setRange(0, 51); self.spin_crf.setValue(self.config.ffmpeg_crf)
        fl.addWidget(self.spin_crf, 0, 1)
        fl.addWidget(QLabel("(lower = better quality, larger file)"), 0, 2)

        fl.addWidget(QLabel("Preset:"), 1, 0)
        self.combo_ff_preset = QComboBox()
        self.combo_ff_preset.addItems([
            "ultrafast", "superfast", "veryfast", "faster", "fast",
            "medium", "slow", "slower", "veryslow"])
        self.combo_ff_preset.setCurrentText(self.config.ffmpeg_preset)
        fl.addWidget(self.combo_ff_preset, 1, 1)
        lay.addWidget(grp_ff)

        # Info
        info_grp = QGroupBox("System Info")
        il = QVBoxLayout(info_grp)
        feats = []
        if HAS_FFMPEG: feats.append("FFmpeg")
        if HAS_IMAGEIO: feats.append("imageio")
        if HAS_NUMBA: feats.append("Numba")
        if HAS_CUPY: feats.append("CuPy (GPU)")
        if HAS_PANDAS: feats.append("Pandas")
        il.addWidget(QLabel(f"Available: {', '.join(feats) if feats else 'None (basic mode)'}"))
        il.addWidget(QLabel(f"SQLite DB: {self.config.preset.width}x{self.config.preset.height}"))
        lay.addWidget(info_grp)

        lay.addStretch()
        return w

    # ── Helpers ──────────────────────────────────────────────────────────

    def _on_browse_output_dir(self):
        """Open folder picker for export directory."""
        current_dir = self.output_dir_edit.text() or EXPORT_DIR
        new_dir = QFileDialog.getExistingDirectory(
            self, "Select Export Directory", current_dir
        )
        if new_dir:
            self.output_dir_edit.setText(new_dir)
            self.config.output_dir = new_dir

    def accept(self):
        """Override accept to trigger auto-save when clicking OK/Apply."""
        self.config.output_dir = self.output_dir_edit.text()
        self.config.save()  # <-- Auto save on dialog close
        super().accept()

    def _on_arrow_style_changed(self, text):
        """Update config arrow style when the combo selection changes."""
        style = ARROW_STYLES.get(text, ARROW_STYLE_THICK)
        self.config.arrow_style = style

    def _on_preset_changed(self, name):
        self.config.apply_preset(name)
        self._update_preset_info()

    def _update_preset_info(self):
        p = self.config.preset
        self.lbl_preset_info.setText(
            f"{p.width}x{p.height}  ·  {p.description}  ·  {p.fps} FPS")

    def _update_bg_preview(self):
        r = self.slider_bg_r.value()
        g = self.slider_bg_g.value()
        b = self.slider_bg_b.value()
        self.bg_preview.setStyleSheet(
            f"QLabel{{background:rgb({r},{g},{b});border:1px solid #444;border-radius:4px;}}")

    def _render_title_preview(self):
        name = self.edit_title_text.text() or "Sample Opening"
        img = render_export_title_card(name, "B20", 12,
                                       width=640, height=360,
                                       bg_color=self.config.bg_color)
        pm = QPixmap.fromImage(img.scaled(
            self.title_preview.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation))
        self.title_preview.setPixmap(pm)

    def _render_end_preview(self):
        name = self.edit_end_text.text() or "Sample Opening"
        img = render_export_end_screen(name, "B20", 12,
                                       width=640, height=360,
                                       bg_color=self.config.bg_color)
        pm = QPixmap.fromImage(img.scaled(
            self.end_preview.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation))
        self.end_preview.setPixmap(pm)

    def get_config(self):
        """Return the updated ExportConfig."""
        self.config.apply_preset(self.combo_preset.currentText())
        self.config.title_enabled = self.chk_title_enabled.isChecked()
        self.config.title_duration = self.spin_title_dur.value()
        self.config.title_text_override = self.edit_title_text.text()
        self.config.end_screen_text = self.edit_end_text.text()
        self.config.move_anim_duration = self.spin_move_anim.value()
        self.config.pause_after_move = self.spin_pause.value()
        self.config.fps = self.spin_fps.value()
        self.config.theme_name = self.combo_theme.currentText()
        self.config.flip_board = self.chk_flip.isChecked()
        self.config.bg_color = (
            self.slider_bg_r.value(),
            self.slider_bg_g.value(),
            self.slider_bg_b.value())
        self.config.ffmpeg_crf = self.spin_crf.value()
        self.config.ffmpeg_preset = self.combo_ff_preset.currentText()
        return self.config


# ═══════════════════════════════════════════════════════════════════════════════
#  BOARD WIDGET
# ═══════════════════════════════════════════════════════════════════════════════
class BoardWidget(QWidget):
    move_made = Signal(dict)
    move_animated = Signal(dict)
    move_attempted = Signal(int, int, int, int, object)

    def __init__(self, engine: ChessEngine, theme_name="Classic", parent=None):
        super().__init__(parent)
        self.engine = engine
        self.theme_name = theme_name
        self.flipped = False
        self.selected = None; self.legal_targets = []
        self.anim_timer = None; self.anim_state = None
        self._arrow_style = ARROW_STYLE_THICK
        self.opening_mode = False
        self.setMinimumSize(BOARD_PX, BOARD_PX)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setMouseTracking(True)

    @property
    def theme(self): return THEMES.get(self.theme_name, THEMES["Classic"])
    def _sq_size(self): return min(self.width(), self.height()) // 8

    def _rc_from_pos(self, pos):
        sz = self._sq_size()
        col = pos.x() // sz; row = pos.y() // sz
        if self.flipped: 
            # Note: Both row and col must invert for a proper 180-degree board rotation.
            col = 7 - col
            row = 7 - row
        if 0 <= row < 8 and 0 <= col < 8: return row, col
        return None, None

    @property
    def arrow_style(self): return self._arrow_style
    @arrow_style.setter
    def arrow_style(self, value): self._arrow_style = value; self.update()

    def paintEvent(self, event):
        with paint_context(self) as p:
            sz = self._sq_size()
            check_sqs = self.engine.check_squares()
            anim = self.anim_state
            img = render_board_image(
                self.engine.board, last_move=self.engine.last_move,
                selected=self.selected, legal_targets=self.legal_targets,
                check_squares=check_sqs, anim_state=anim,
                sq_size=sz, theme=self.theme, flipped=self.flipped, arrow_style=self.arrow_style)
            p.drawImage(0, 0, img.scaled(self.width(), self.height(), Qt.KeepAspectRatio, Qt.SmoothTransformation))

    def mousePressEvent(self, event):
        if event.button() != Qt.LeftButton: return
        r, c = self._rc_from_pos(event.pos())
        if r is None: return
        if self.selected:
            sr, sc = self.selected
            if (r, c) in self.legal_targets:
                self._execute_move(sr, sc, r, c)
                return
        piece = self.engine.board.piece_at(ChessEngine.rc_to_sq(r, c))
        if piece:
            self.selected = (r, c)
            self.legal_targets = self.engine.legal_moves(r, c)
        else:
            self.selected = None; self.legal_targets = []
        self.update()

    def _execute_move(self, fr, fc, tr, tc, promo=None):
        if self.opening_mode:
            self.move_attempted.emit(fr, fc, tr, tc, promo)
            self.selected = None; self.legal_targets = []
            self.update()
            return
        result = self.engine.make_move(fr, fc, tr, tc, promo)
        if result:
            self.selected = None; self.legal_targets = []
            self._start_animation(result)
            self.move_made.emit(result)

    def play_external_move(self, uci_str):
        result = self.engine.make_move_uci(uci_str)
        if result:
            self._start_animation(result)
            self.move_made.emit(result)

    def _start_animation(self, result):
        if self.anim_timer: self.anim_timer.stop()
        self.anim_state = {
            'from': result['from'], 'to': result['to'],
            'piece_obj': result['piece_obj'], 'captured': result['captured'], 'progress': 0.0}
        duration = ANIM_SPEED_DEFAULT
        steps = max(1, int(duration / 1000 * ANIM_FPS))
        self._anim_step = 0; self._anim_total = steps
        self.anim_timer = QTimer(self)
        self.anim_timer.timeout.connect(self._tick_animation)
        # Fix 6: Guard against division-by-zero in animation timer interval
        interval = max(1, int(duration / steps))
        self.anim_timer.start(interval)

    def _tick_animation(self):
        if not self.anim_state: 
            self.anim_timer.stop(); return
        self._anim_step += 1
        t = min(1.0, self._anim_step / self._anim_total)
        self.anim_state['progress'] = _ease_out_cubic(t)
        self.update()
        if t >= 1.0:
            self.anim_timer.stop()
            result_copy = dict(self.anim_state)
            self.anim_state = None
            self.update()
            self.move_animated.emit(result_copy)

    def reset_view(self):
        self.selected = None; self.legal_targets = []
        self.update()



# ═══════════════════════════════════════════════════════════════════════════════
#  BATCH EXPORT DIALOG
# ═══════════════════════════════════════════════════════════════════════════════

class BatchExportDialog(QDialog):
    """Modal dialog that shows progress for a batch of video exports."""

    def __init__(self, openings_list, config, parent=None):
        """
        Parameters
        ----------
        openings_list : list[dict]
            Each dict: {"name", "eco", "moves", "notations", …}
        config : ExportConfig
        parent : QWidget
        """
        super().__init__(parent)
        self.setWindowTitle("Batch Export")
        self.setMinimumSize(520, 420)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowContextHelpButtonHint)
        self.setModal(True)

        self.openings_list = openings_list
        self.config = config
        self.worker = None
        self._completed = 0
        self._failed = 0
        self._results = []
        self._total = len(openings_list)

        self._build_ui()
        self._start_export()

    # ── UI Construction ──

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(10)

        self.lbl_overall = QLabel(f"Exporting {self._total} opening(s)…")
        layout.addWidget(self.lbl_overall)

        self.progress_overall = QProgressBar()
        self.progress_overall.setRange(0, self._total)
        self.progress_overall.setValue(0)
        self.progress_overall.setFormat("%v / %m videos")
        layout.addWidget(self.progress_overall)

        self.lbl_current = QLabel("Preparing…")
        layout.addWidget(self.lbl_current)

        self.progress_current = QProgressBar()
        self.progress_current.setRange(0, 100)
        self.progress_current.setValue(0)
        self.progress_current.setFormat("%p%")
        layout.addWidget(self.progress_current)

        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["Opening", "Status", "File"])
        self.table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(
            2, QHeaderView.Stretch)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        layout.addWidget(self.table)

        btn_layout = QHBoxLayout()
        self.btn_cancel = QPushButton("Cancel")
        self.btn_cancel.clicked.connect(self._on_cancel)
        self.btn_open_folder = QPushButton("Open Folder")
        self.btn_open_folder.clicked.connect(self._open_output_folder)
        self.btn_open_folder.setEnabled(False)
        self.btn_close = QPushButton("Close")
        self.btn_close.clicked.connect(self.accept)
        self.btn_close.setEnabled(False)
        btn_layout.addStretch()
        btn_layout.addWidget(self.btn_open_folder)
        btn_layout.addWidget(self.btn_cancel)
        btn_layout.addWidget(self.btn_close)
        layout.addLayout(btn_layout)

    # ── Start Export ──

    def _start_export(self):
        self.worker = VideoExportWorker(
            self.openings_list, self.config, parent=self)
        self.worker.video_done.connect(
            self._on_video_done, Qt.QueuedConnection)
        self.worker.progress.connect(
            self._on_frame_progress, Qt.QueuedConnection)
        self.worker.finished.connect(
            self._on_batch_finished, Qt.QueuedConnection)
        self.worker.error.connect(
            self._on_error, Qt.QueuedConnection)
        self.worker.start()

    # ── Slots ──

    def _on_frame_progress(self, current_frame, total_frames):
        if total_frames > 0:
            self.progress_current.setValue(
                min(100, int(100 * current_frame / total_frames)))

    def _on_video_done(self, video_index, output_path):
        self._completed += 1
        name = self.openings_list[video_index].get(
            "name", f"Video {video_index}")
        self._results.append((name, "✓ Done", output_path))
        self._add_table_row(name, "✓ Done", output_path)
        self.progress_overall.setValue(self._completed + self._failed)
        self.lbl_overall.setText(
            f"Exported {self._completed} of {self._total}"
            + (f"  ({self._failed} failed)" if self._failed else ""))
        self.lbl_current.setText(f"✓ {name}")
        self.progress_current.setValue(100)

    def _on_error(self, error_msg):
        self._failed += 1
        next_idx = self._completed + self._failed - 1
        name = (self.openings_list[next_idx].get("name", f"Video {next_idx}")
                if next_idx < len(self.openings_list) else "Unknown")
        self._results.append((name, "✗ Failed", error_msg))
        self._add_table_row(name, "✗ Failed", error_msg[:120])
        self.progress_overall.setValue(self._completed + self._failed)
        self.lbl_overall.setText(
            f"Exported {self._completed} of {self._total}  "
            f"({self._failed} failed)")
        self.lbl_current.setText(f"✗ Failed: {name}")
        log(f"[EXPORT ERROR] {name}: {error_msg}", "ERROR")
        if self._completed + self._failed >= self._total:
            self._on_batch_finished("batch_complete")

    def _on_batch_finished(self, result):
        self.lbl_overall.setText(
            f"Batch complete: {self._completed} succeeded, "
            f"{self._failed} failed")
        self.lbl_current.setText("All exports finished.")
        self.progress_current.setValue(100)
        self.progress_overall.setValue(self._total)
        self.btn_cancel.setEnabled(False)
        self.btn_close.setEnabled(True)
        self.btn_open_folder.setEnabled(True)
        if self._failed == 0:
            self.lbl_current.setStyleSheet(
                "color: #4CAF50; font-weight: bold;")
            self.lbl_current.setText(
                f"✓ All {self._completed} videos exported successfully!")
        else:
            self.lbl_current.setStyleSheet(
                "color: #FF9800; font-weight: bold;")
            self.lbl_current.setText(
                f"⚠ {self._completed} succeeded, {self._failed} failed. "
                "Check the table.")
        log(f"[EXPORT] Batch complete: {self._completed} ok, "
            f"{self._failed} failed", "EXPORT")

    def _on_cancel(self):
        if self.worker and self.worker.isRunning():
            self.btn_cancel.setEnabled(False)
            self.btn_cancel.setText("Cancelling…")
            self.lbl_current.setText("Cancelling…")
            self.worker.cancel()
            QTimer.singleShot(5000, self._force_cleanup)
        else:
            self.reject()

    def _force_cleanup(self):
        if self.worker and self.worker.isRunning():
            log("[EXPORT] Force-terminating worker", "WARN")
            self.worker.terminate()
            self.worker.wait(2000)
        self._on_batch_finished("cancelled")

    def _add_table_row(self, name, status, detail):
        row = self.table.rowCount()
        self.table.insertRow(row)
        self.table.setItem(row, 0, QTableWidgetItem(name))
        si = QTableWidgetItem(status)
        si.setForeground(
            QColor("#4CAF50") if "✓" in status else QColor("#F44336"))
        self.table.setItem(row, 1, si)
        di = QTableWidgetItem(detail)
        di.setToolTip(detail)
        self.table.setItem(row, 2, di)
        self.table.scrollToBottom()

    def _open_output_folder(self):
        path = self.config.output_dir
        if not os.path.isdir(path):
            os.makedirs(path, exist_ok=True)
        if sys.platform == "win32":
            os.startfile(path)
        elif sys.platform == "darwin":
            subprocess.Popen(["open", path])
        else:
            subprocess.Popen(["xdg-open", path])

    def closeEvent(self, event):
        if self.worker and self.worker.isRunning():
            self._on_cancel()
            event.ignore()
        else:
            event.accept()

    def cleanup(self):
        if self.worker:
            self.worker.cancel()
            self.worker.wait(3000)



# ═══════════════════════════════════════════════════════════════════════════════
#  OPENINGS LOADER (PGN import)
# ═══════════════════════════════════════════════════════════════════════════════

class OpeningsLoader:
    """Load openings from PGN files into the SQLite database."""

    @staticmethod
    def load_pgn(pgn_path, data_provider: DataProvider, progress_cb=None):
        """Parse a PGN file and import all games as openings."""
        items = []
        with open(pgn_path, 'r', encoding='utf-8', errors='replace') as f:
            game_count = 0
            while True:
                game = chess.pgn.read_game(f)
                if game is None:
                    break
                headers = game.headers
                uci_moves = []
                board = game.board()
                for move in game.mainline_moves():
                    uci_moves.append(move.uci())
                    board.push(move)

                name = headers.get('Opening', headers.get('White', 'Unknown'))
                eco = headers.get('ECO', '')
                pgn_str = str(game)

                items.append({
                    'name': name,
                    'eco': eco,
                    'pgn': pgn_str,
                    'uci_moves': uci_moves,
                    'epd': board.epd(),
                    'display_title': name,
                    'img_raw': '',
                })
                game_count += 1

                if len(items) >= 500:
                    data_provider.insert_batch(items)
                    if progress_cb:
                        progress_cb(game_count)
                    items = []

        if items:
            data_provider.insert_batch(items)
            if progress_cb:
                progress_cb(game_count)

        return game_count

    @staticmethod
    def load_lichess_db(tsv_path, data_provider: DataProvider, progress_cb=None):
        """Load from Lichess opening database TSV format."""
        items = []
        count = 0
        with open(tsv_path, 'r', encoding='utf-8', errors='replace') as f:
            reader = csv.DictReader(f, delimiter='\t')
            for row in reader:
                name = row.get('name', row.get('Opening', ''))
                eco = row.get('eco', row.get('ECO', ''))
                uci_str = row.get('uci', row.get('moves', ''))
                uci_moves = uci_str.split() if uci_str else []

                items.append({
                    'name': name,
                    'eco': eco,
                    'pgn': '',
                    'uci_moves': uci_moves,
                    'epd': '',
                    'display_title': name,
                    'img_raw': '',
                })
                count += 1

                if len(items) >= 500:
                    data_provider.insert_batch(items)
                    if progress_cb:
                        progress_cb(count)
                    items = []

        if items:
            data_provider.insert_batch(items)
            if progress_cb:
                progress_cb(count)
        return count


# ═══════════════════════════════════════════════════════════════════════════════
#  MAIN WINDOW
# ═══════════════════════════════════════════════════════════════════════════════

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Chess Openings Explorer")
        self.setMinimumSize(1280, 800)
        self.resize(1440, 900)

        self.engine = ChessEngine()
        self.config = ExportConfig()
        self.dp = DataProvider()
        self._current_opening = None
        self._notations = []
        self._move_idx = -1

        self._apply_global_style()
        self._build_ui()
        self._connect_signals()

    def _apply_global_style(self):
        self.setStyleSheet("""
            QMainWindow { background: #12121e; }
            QWidget { background: #12121e; color: #ddd; font-family: 'Segoe UI', sans-serif; }
            QSplitter::handle { background: #2a2a3a; width: 3px; }
            QSplitter::handle:hover { background: #2a82da; }
            QStatusBar { background: #0e0e1a; color: #6a6a8a; font-size: 11px; border-top: 1px solid #222; }
            QMenuBar { background: #16162a; color: #ccc; border-bottom: 1px solid #222; }
            QMenuBar::item:selected { background: #2a82da; }
            QMenu { background: #1e1e2e; color: #ddd; border: 1px solid #333; }
            QMenu::item:selected { background: #2a82da; }
            QToolBar { background: #16162a; border-bottom: 1px solid #222; spacing: 4px; padding: 2px; }
            QToolButton { background: transparent; color: #ccc; border: 1px solid transparent;
                          border-radius: 4px; padding: 4px 8px; font-size: 12px; }
            QToolButton:hover { background: #2a2a3a; border-color: #444; }
            QToolButton:pressed { background: #2a82da; }
        """)

    def _build_ui(self):
        # ── Menu ──
        menubar = self.menuBar()

        file_menu = menubar.addMenu("File")
        import_pgn_action = QAction("Import PGN...", self)
        import_pgn_action.triggered.connect(self._import_pgn)
        file_menu.addAction(import_pgn_action)

        import_tsv_action = QAction("Import Lichess TSV...", self)
        import_tsv_action.triggered.connect(self._import_tsv)
        file_menu.addAction(import_tsv_action)

        file_menu.addSeparator()
        clear_action = QAction("Clear Database", self)
        clear_action.triggered.connect(self._clear_db)
        file_menu.addAction(clear_action)

        file_menu.addSeparator()
        exit_action = QAction("Exit", self)
        exit_action.triggered.connect(self.close)
        file_menu.addAction(exit_action)

        # ── Toolbar ──
        toolbar = self.addToolBar("Main")
        toolbar.setMovable(False)

        self.btn_settings = QToolButton()
        self.btn_settings.setText("⚙ Settings")
        self.btn_settings.clicked.connect(self._show_settings)
        toolbar.addWidget(self.btn_settings)

        toolbar.addSeparator()

        self.btn_undo = QToolButton()
        self.btn_undo.setText("↩ Undo")
        self.btn_undo.clicked.connect(self._undo_move)
        toolbar.addWidget(self.btn_undo)

        self.btn_reset = QToolButton()
        self.btn_reset.setText("⟳ Reset")
        self.btn_reset.clicked.connect(self._reset_board)
        toolbar.addWidget(self.btn_reset)

        toolbar.addSeparator()

        self.btn_flip = QToolButton()
        self.btn_flip.setText("⇅ Flip")
        self.btn_flip.clicked.connect(self._flip_board)
        toolbar.addWidget(self.btn_flip)

        toolbar.addSeparator()

        self.btn_batch_export = QToolButton()
        self.btn_batch_export.setText("▶ Batch Export")
        self.btn_batch_export.setStyleSheet(
            "QToolButton{background:#2a82da;color:#fff;border-radius:4px;padding:4px 12px}"
            "QToolButton:hover{background:#3a92ea}")
        self.btn_batch_export.clicked.connect(self._batch_export)
        toolbar.addWidget(self.btn_batch_export)

        toolbar.addSeparator()

        # Navigation buttons for stepping through moves
        self.btn_step_back = QToolButton()
        self.btn_step_back.setText("◀")
        self.btn_step_back.clicked.connect(self._step_back)
        toolbar.addWidget(self.btn_step_back)

        self.btn_step_fwd = QToolButton()
        self.btn_step_fwd.setText("▶")
        self.btn_step_fwd.clicked.connect(self._step_forward)
        toolbar.addWidget(self.btn_step_fwd)

        # ── Central layout ──
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QHBoxLayout(central)
        main_layout.setContentsMargins(6, 6, 6, 6)

        splitter = QSplitter(Qt.Horizontal)

        # ── Left panel: openings list with pagination ──
        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(0, 0, 0, 0)
        self.openings_list = PaginatedOpeningsWidget(self.dp)
        left_layout.addWidget(self.openings_list)
        left_panel.setMinimumWidth(320)
        left_panel.setMaximumWidth(500)
        splitter.addWidget(left_panel)

        # ── Center panel: board ──
        center_panel = QWidget()
        center_layout = QVBoxLayout(center_panel)
        center_layout.setContentsMargins(0, 0, 0, 0)

        self.board_widget = BoardWidget(self.engine, self.config.theme_name)
        center_layout.addWidget(self.board_widget, 1)

        # Move notation display
        self.notation_display = QTextEdit()
        self.notation_display.setReadOnly(True)
        self.notation_display.setMaximumHeight(80)
        self.notation_display.setStyleSheet(
            "QTextEdit{background:#1e1e2a;color:#ccc;border:1px solid #333;"
            "border-radius:4px;font-family:monospace;font-size:12px;padding:4px;}")
        center_layout.addWidget(self.notation_display)
        splitter.addWidget(center_panel)

        # ── Right panel: preview + info ──
        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(4, 4, 4, 4)

        # Opening info
        info_grp = QGroupBox("Current Opening")
        info_grp.setStyleSheet(
            "QGroupBox{color:#aab;font-weight:bold;border:1px solid #333;"
            "border-radius:4px;margin-top:10px;padding-top:14px;}"
            "QGroupBox::title{subcontrol-origin:margin;left:10px;padding:0 4px;}")
        info_lay = QVBoxLayout(info_grp)
        self.lbl_opening_name = QLabel("No opening selected")
        self.lbl_opening_name.setWordWrap(True)
        self.lbl_opening_name.setStyleSheet("font-size:14px;font-weight:bold;color:#eee;")
        info_lay.addWidget(self.lbl_opening_name)
        self.lbl_eco = QLabel("ECO: —")
        self.lbl_eco.setStyleSheet("color:#8a8aaa;font-size:12px;")
        info_lay.addWidget(self.lbl_eco)
        self.lbl_moves_count = QLabel("Moves: 0")
        self.lbl_moves_count.setStyleSheet("color:#8a8aaa;font-size:12px;")
        info_lay.addWidget(self.lbl_moves_count)
        right_layout.addWidget(info_grp)

        # Preview widget
        self.preview_widget = PreviewWidget(self.config)
        right_layout.addWidget(self.preview_widget)

        right_layout.addStretch()
        right_panel.setMinimumWidth(260)
        right_panel.setMaximumWidth(320)
        splitter.addWidget(right_panel)

        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setStretchFactor(2, 0)
        main_layout.addWidget(splitter)

        # ── Status bar ──
        self.statusBar().showMessage(f"Ready — {self.dp.total_openings} openings loaded")

    def _connect_signals(self):
        self.openings_list.opening_selected.connect(self._on_opening_selected)
        self.board_widget.move_made.connect(self._on_move_made)
        self.board_widget.move_animated.connect(self._on_move_anim_done)

    # ── Opening selection ────────────────────────────────────────────────

    def _on_opening_selected(self, opening_id):
        rec = self.dp.get_opening(opening_id)
        if rec is None:
            return
        self._current_opening = rec
        name = rec.get('display_title', rec.get('name', ''))
        eco = rec.get('eco', '')
        uci_moves = rec.get('uci_moves', [])

        self.lbl_opening_name.setText(name)
        self.lbl_eco.setText(f"ECO: {eco}")
        self.lbl_moves_count.setText(f"Moves: {len(uci_moves)}")

        # Play through moves to get notations
        self.engine.reset()
        self._notations = []
        for uci in uci_moves:
            result = self.engine.make_move_uci(uci)
            if result:
                self._notations.append(result['notation'])
            else:
                log(f"Invalid UCI move: {uci}", "WARN")
                break

        self._move_idx = len(self._notations) - 1
        self._update_notation_display()
        self.board_widget.reset_view()
        self.board_widget.update()

        # Update preview
        self.preview_widget.set_opening(name, eco, len(uci_moves))

        self.statusBar().showMessage(f"{name} — ECO {eco} — {len(uci_moves)} half-moves")

    def _update_notation_display(self):
        if not self._notations:
            self.notation_display.setPlainText("")
            return
        parts = []
        for i, n in enumerate(self._notations):
            if i % 2 == 0:
                parts.append(f"{i // 2 + 1}. {n}")
            else:
                parts.append(n)
        text = " ".join(parts)
        # Highlight current move
        if 0 <= self._move_idx < len(self._notations):
            cur_notation = self._notations[self._move_idx]
            # Simple highlight via bold ( QTextEdit)
            cursor = self.notation_display.textCursor()
            self.notation_display.setPlainText(text)
        else:
            self.notation_display.setPlainText(text)

    # ── Move stepping ────────────────────────────────────────────────────

    def _step_forward(self):
        """Step forward through opening moves."""
        if not self._current_opening:
            return
        uci_moves = self._current_opening.get('uci_moves', [])
        if self._move_idx + 1 < len(uci_moves):
            self._move_idx += 1
            uci = uci_moves[self._move_idx]
            result = self.engine.make_move_uci(uci)
            if result:
                self.board_widget.update()
                self._update_notation_display()

    def _step_back(self):
        """Step back through opening moves."""
        if self._move_idx >= 0:
            self.engine.undo()
            self._move_idx -= 1
            self.board_widget.update()
            self._update_notation_display()

    # ── Board interaction ────────────────────────────────────────────────

    def _on_move_made(self, result):
        self._notations.append(result['notation'])
        self._move_idx = len(self._notations) - 1
        self._update_notation_display()

    def _on_move_anim_done(self, anim_result):
        pass

    def _undo_move(self):
        if self.engine.undo():
            if self._notations:
                self._notations.pop()
            self._move_idx = len(self._notations) - 1
            self._update_notation_display()
            self.board_widget.update()

    def _reset_board(self):
        self.engine.reset()
        self._notations = []
        self._move_idx = -1
        self._update_notation_display()
        self.board_widget.reset_view()

    def _flip_board(self):
        self.board_widget.flipped = not self.board_widget.flipped
        self.board_widget.update()

    # ── Settings ─────────────────────────────────────────────────────────

    def _show_settings(self):
        dlg = SettingsDialog(self.config, self)
        if dlg.exec() == QDialog.Accepted:
            self.config = dlg.get_config()
            self.board_widget.theme_name = self.config.theme_name
            self.board_widget.flipped = self.config.flip_board
            self.board_widget.update()
            self.preview_widget.update_config(self.config)
            self.statusBar().showMessage("Settings updated")

    # ── Batch export ─────────────────────────────────────────────────────

    def _batch_export(self):
        ids = self.openings_list.get_selected_ids()
        if not ids:
            self.statusBar().showMessage(
                "No openings selected for export — use checkboxes")
            return

        # Look up full opening data from SQLite
        raw_records = self.dp.get_openings_by_ids(ids)
        if not raw_records:
            self.statusBar().showMessage(
                "Could not load selected openings")
            return

        # Enrich each record with "moves" and "notations"
        openings_data = []
        for rec in raw_records:
            uci_moves = rec.get('uci_moves', [])
            if isinstance(uci_moves, str):
                try:
                    uci_moves = json.loads(uci_moves)
                except Exception:
                    uci_moves = []
            rec['moves'] = uci_moves
            # Generate SAN notations
            notations = []
            temp_board = chess.Board()
            for uci in uci_moves:
                try:
                    m = chess.Move.from_uci(uci)
                    notations.append(temp_board.san(m))
                    temp_board.push(m)
                except Exception:
                    break
            rec['notations'] = notations
            openings_data.append(rec)

        dlg = BatchExportDialog(openings_data, self.config, self)
        dlg.exec()

    # ── Import ───────────────────────────────────────────────────────────

    def _import_pgn(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Import PGN", DATA_DIR, "PGN Files (*.pgn);;All Files (*)")
        if not path:
            return
        self.statusBar().showMessage("Importing PGN...")
        QApplication.processEvents()

        def worker():
            count = OpeningsLoader.load_pgn(path, self.dp,
                lambda c: self.statusBar().showMessage(f"Imported {c} openings..."))
            # Back to main thread
            QTimer.singleShot(0, lambda: self._on_import_done(count))

        threading.Thread(target=worker, daemon=True).start()

    def _import_tsv(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Import Lichess TSV", DATA_DIR,
            "TSV Files (*.tsv);;CSV Files (*.csv);;All Files (*)")
        if not path:
            return
        self.statusBar().showMessage("Importing TSV...")
        QApplication.processEvents()

        def worker():
            count = OpeningsLoader.load_lichess_db(path, self.dp,
                lambda c: self.statusBar().showMessage(f"Imported {c} openings..."))
            QTimer.singleShot(0, lambda: self._on_import_done(count))

        threading.Thread(target=worker, daemon=True).start()

    def _on_import_done(self, count):
        self.openings_list._current_page = 0
        self.openings_list._refresh()
        self.statusBar().showMessage(f"Import complete — {count} openings added ({self.dp.total_openings} total)")

    def _clear_db(self):
        self.dp.clear_all()
        self.openings_list._current_page = 0
        self.openings_list._refresh()
        self.statusBar().showMessage("Database cleared")

    def closeEvent(self, event):
        self.dp.close()
        event.accept()

# ═══════════════════════════════════════════════════════════════════════════════
#  MP4 EXPORT — YouTube-compatible H.264 via ffmpeg
# ═══════════════════════════════════════════════════════════════════════════════
class VideoExportWorker(QThread):
    """
    Optimized video export worker.

    Performance improvements over the original:
      • Static frames (title, end, holds) are rendered ONCE and their
        BGR24 byte representation is reused for every repetition.
      • Compact frame plan uses (kind, count, data) tuples instead of
        one list entry per frame — dramatically less memory.
      • Pre-computed easing curve avoids per-frame pow() calls.
      • Pre-computed board states and move metadata — no redundant
        chess.Move.from_uci() or board.copy() inside the hot loop.
      • Batched pipe writes via a bytearray accumulator reduce the
        number of proc.stdin.write() syscalls.
      • Efficient _qimage_to_bgr_bytes conversion (single-copy, slice
        based channel reversal).
      • Progress signal throttled to ~2 % granularity to avoid flooding
        the GUI thread.
    """

    progress   = Signal(int, int)   # current_frame, total_frames
    finished   = Signal(str)        # "batch_complete"
    error      = Signal(str)
    video_done = Signal(int, str)   # video_index, output_path

    # Flush the pipe buffer when it exceeds this many bytes
    _FLUSH_THRESHOLD = 32 * 1024 * 1024  # 32 MB ≈ 5 frames @ 1080p

    def __init__(self, openings_list, config, parent=None):
        """
        Parameters
        ----------
        openings_list : list[dict]
            Each dict must contain at minimum:
              - "name"  : str
              - "eco"   : str (may be "")
              - "moves" : list[str]  (UCI strings like "e2e4")
            Optional:
              - "notations" : list[str] (SAN strings; generated if absent)
        config : ExportConfig
        """
        super().__init__(parent)
        self.openings_list = openings_list
        self.config = config
        self._cancel = False

        self.tmpdir = os.path.join(os.getcwd(), "chess_sfx_tmp")
        os.makedirs(self.tmpdir, exist_ok=True)

    def cancel(self):
        self._cancel = True

    # ──────────────────────────────────────────────────────────────────────
    #  Thread entry
    # ──────────────────────────────────────────────────────────────────────

    def run(self):
        total = len(self.openings_list)
        for vid_idx, opening_data in enumerate(self.openings_list):
            if self._cancel:
                self.error.emit("Export cancelled")
                return
            try:
                path = self._export_single(opening_data, vid_idx)
                if path:
                    self.video_done.emit(vid_idx, path)
                elif self._cancel:
                    return
                # path is None → error already emitted
            except Exception as exc:
                self.error.emit(
                    f"Error on '{opening_data.get('name', '?')}': {exc}")
        self.finished.emit("batch_complete")

    # ──────────────────────────────────────────────────────────────────────
    #  Single-video export  (the hot path)
    # ──────────────────────────────────────────────────────────────────────

    def _export_single(self, opening_data, vid_idx):
        """Export one opening to MP4. Returns output_path on success, None on error."""

        cfg       = self.config
        preset    = cfg.preset
        w, h      = preset.width, preset.height
        fps       = cfg.fps
        sq_size   = preset.calc_sq_size()
        theme     = THEMES.get(cfg.theme_name, THEMES["Classic"])
        bg_color  = cfg.bg_color
        arrow_sty = cfg.arrow_style
        flipped   = cfg.flip_board
        is_board_only = preset.is_board_only

        # ── Output path ──
        os.makedirs(cfg.output_dir, exist_ok=True)
        safe = sanitize_filename(opening_data["name"])
        ts   = datetime.now().strftime("%Y%m%d_%H%M%S")
        out  = os.path.join(cfg.output_dir, f"{safe}_{ts}.mp4")

        # ── Moves & notations ──
        uci_moves = opening_data.get("moves", [])
        notations = opening_data.get("notations", [])
        if not notations:
            notations = self._generate_notations(uci_moves)

        # ── Pre-compute board snapshots ──
        board_states = self._precompute_boards(uci_moves)

        # ── Pre-compute per-move metadata ──
        move_metas = self._precompute_move_meta(board_states, uci_moves)

        # ── Pre-compute easing curve ──
        n_anim   = max(1, int(cfg.move_anim_duration * fps))
        ease_vals = [_ease_out_cubic(i / max(1, n_anim - 1))
                     for i in range(n_anim)]

        # ── Build compact frame plan ──
        n_hold = max(1, int(cfg.pause_after_move * fps))
        plan   = self._build_frame_plan(cfg, fps, uci_moves, move_metas, n_anim, n_hold)

        total_frames = sum(p[1] for p in plan)
        if total_frames == 0:
            self.error.emit(f"No frames for '{opening_data['name']}'")
            return None
        
        # ── Build Synchronized Audio Timeline ──
        sr = 44100
        total_duration = total_frames / fps
        total_samples = int(total_duration * sr) + sr  # Add 1 sec padding for safety
        audio_buffer = np.zeros(total_samples, dtype=np.float64)

        t = 0.0
        if cfg.title_enabled:
            t += cfg.title_duration

        audio_events = [(t, 'start')]
        t += cfg.pause_after_move

        for mi in range(len(uci_moves)):
            meta = move_metas[mi]
            snd = 'move'
            if meta.get('checkmate'): snd = 'checkmate'
            elif meta.get('check'): snd = 'check'
            elif meta.get('castle'): snd = 'castle'
            elif meta.get('promo'): snd = 'promote'
            elif meta.get('captured') != '.': snd = 'capture'

            audio_events.append((t, snd))
            t += cfg.move_anim_duration
            t += cfg.pause_after_move

        if cfg.end_title_enabled:
            audio_events.append((t, 'end'))

        # Mix sounds into the buffer
        for t_sec, snd_name in audio_events:
            samples = self._get_sound_samples(snd_name, sr)
            start_idx = int(t_sec * sr)
            end_idx = start_idx + len(samples)
            if end_idx > len(audio_buffer):
                new_buf = np.zeros(end_idx + sr, dtype=np.float64)
                new_buf[:len(audio_buffer)] = audio_buffer
                audio_buffer = new_buf
            audio_buffer[start_idx:end_idx] += samples

        # Convert to 16-bit PCM and save to temp file
        audio_i16 = _to_i16(audio_buffer)
        temp_audio_path = os.path.join(self.tmpdir, f"chess_export_audio_{vid_idx}_{int(time.time())}.wav")
        with wave.open(temp_audio_path, 'w') as wave_file:
            wave_file.setnchannels(1)
            wave_file.setsampwidth(2)
            wave_file.setframerate(sr)
            wave_file.writeframes(audio_i16.tobytes())

        if not HAS_FFMPEG:
            self.error.emit("ffmpeg not found on PATH")
            return None
        
        cmd = self._ffmpeg_cmd(w, h, fps, cfg, opening_data, out, temp_audio_path)
        log(f"[EXPORT] {opening_data['name']}: "
            f"{total_frames} frames @ {fps} fps", "EXPORT")

        # ══════════════════════════════════════════════════════════════
        # 1: Drain stderr in a background thread to prevent deadlock
        # ══════════════════════════════════════════════════════════════
        proc = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,         
            stderr=subprocess.PIPE,            
        )

        stderr_chunks: list[bytes] = []
        stderr_exc: list[Exception] = []

        def _drain_stderr():
            """Read stderr in a separate thread to prevent pipe deadlock."""
            try:
                while True:
                    chunk = proc.stderr.read(8192)
                    if not chunk:
                        break
                    stderr_chunks.append(chunk)
            except Exception as e:
                stderr_exc.append(e)

        stderr_thread = threading.Thread(target=_drain_stderr, daemon=True)
        stderr_thread.start()

        # ── Pre-render static frames → BGR24 bytes ──
        name = opening_data["name"]
        eco  = opening_data.get("eco", "")
        n_mv = len(uci_moves)

        title_bgr = None
        if cfg.title_enabled:
            img = render_export_title_card(
                name, eco, n_mv, width=w, height=h, bg_color=bg_color)
            title_bgr = _qimage_to_bgr_bytes(img)

        end_bgr = None
        if cfg.end_title_enabled:
            img = render_export_end_screen(
                name, eco, n_mv, width=w, height=h, bg_color=bg_color)
            end_bgr = _qimage_to_bgr_bytes(img)

        start_img = render_composite_frame(
            board_states[0], notations, 0,
            width=w, height=h, sq_size=sq_size,
            theme=theme, flipped=flipped,
            bg_color=bg_color, arrow_style=arrow_sty, is_board_only=is_board_only)
        start_bgr = _qimage_to_bgr_bytes(start_img)

        hold_cache: dict[int, bytes] = {}

        # ── Write loop with batched buffer ──
        _FLUSH_THRESHOLD = 32 * 1024 * 1024  # 32 MB

        buf       = bytearray()
        rendered  = 0
        last_pct  = -1

        def _flush():
            nonlocal buf
            if buf:
                try:
                    proc.stdin.write(buf)
                except BrokenPipeError:
                    # stderr thread will have the real error message
                    raise RuntimeError("ffmpeg pipe broken")
                buf = bytearray()

        def _queue(bgr: bytes):
            nonlocal rendered, last_pct
            buf.extend(bgr)
            rendered += 1
            if len(buf) >= _FLUSH_THRESHOLD:
                _flush()
            pct = rendered * 50 // total_frames
            if pct != last_pct:
                self.progress.emit(rendered, total_frames)
                last_pct = pct

        # ── Execute plan ──
        try:
            for item in plan:
                if self._cancel:
                    _flush()
                    self._safe_close(proc)
                    stderr_thread.join(timeout=2)
                    return None

                kind  = item[0]
                count = item[1]

                if kind == 'title':
                    bgr = title_bgr
                    for _ in range(count):
                        _queue(bgr)

                elif kind == 'end':
                    bgr = end_bgr
                    for _ in range(count):
                        _queue(bgr)

                elif kind == 'anim':
                    _, _, mi, anim_base = item
                    b = board_states[mi]
                    for af in range(count):
                        state = dict(anim_base)
                        state['progress'] = ease_vals[af]
                        img = render_composite_frame(
                            b, notations, mi,
                            anim_state=state,
                            width=w, height=h, sq_size=sq_size,
                            theme=theme, flipped=flipped,
                            bg_color=bg_color, arrow_style=arrow_sty, is_board_only=is_board_only)
                        _queue(_qimage_to_bgr_bytes(img))

                elif kind == 'hold':
                    _, _, bidx, last_mv = item
                    if bidx not in hold_cache:
                        b = board_states[bidx]
                        chk = self._check_sqs(b)
                        img = render_composite_frame(
                            b, notations, bidx - 1,
                            last_move=last_mv, check_squares=chk,
                            width=w, height=h, sq_size=sq_size,
                            theme=theme, flipped=flipped,
                            bg_color=bg_color, arrow_style=arrow_sty, is_board_only=is_board_only)
                        hold_cache[bidx] = _qimage_to_bgr_bytes(img)
                    bgr = hold_cache[bidx]
                    for _ in range(count):
                        _queue(bgr)

            _flush()  # final drain

        except RuntimeError as e:
            self.error.emit(str(e))
            return None

        log(f"[EXPORT] {rendered} frames piped — waiting for ffmpeg…","EXPORT")

        # ══════════════════════════════════════════════════════════════
        # 2: Close stdin, then wait for ffmpeg + stderr thread
        # ══════════════════════════════════════════════════════════════
        try:
            proc.stdin.close()
        except BrokenPipeError as e:
            self.error.emit(str(e))
            return None

        # proc.wait() now returns promptly because stderr is being drained
        rc = proc.wait()

        # Ensure stderr thread finishes
        stderr_thread.join(timeout=5)

        # Collect full stderr for error reporting
        stderr_text = b"".join(stderr_chunks).decode("utf-8", errors="replace")

        if rc != 0:
            self.error.emit(
                f"ffmpeg exited code {rc}:\n{stderr_text[-800:]}")
            return None

        # ── Verify output ──
        if not os.path.exists(out):
            self.error.emit(f"Output file not found: {out}")
            return None

        file_size = os.path.getsize(out)
        if file_size < 1000:
            self.error.emit(
                f"Output file is suspiciously small ({file_size} bytes): {out}")
            return None

        log(f"[EXPORT] ✓ {out} ({file_size:,} bytes)", "EXPORT")

        # ── Cleanup temporary audio file ──
        try:
            if os.path.exists(temp_audio_path):
                os.remove(temp_audio_path)
        except Exception as e:
            self.error.emit(str(e))
        return out

    # ──────────────────────────────────────────────────────────────────────
    #  Pre-computation helpers
    # ──────────────────────────────────────────────────────────────────────

    @staticmethod
    def _generate_notations(uci_moves):
        """Generate SAN notations from UCI move list."""
        board = chess.Board()
        notations = []
        for uci in uci_moves:
            try:
                m = chess.Move.from_uci(uci)
                notations.append(board.san(m))
                board.push(m)
            except Exception:
                break
        return notations

    @staticmethod
    def _precompute_boards(uci_moves, fen=None):
        if fen: states = [chess.Board(fen)]
        else: states = [chess.Board()]
        for uci in uci_moves:
            b = states[-1].copy()
            try: b.push(chess.Move.from_uci(uci))
            except Exception: break
            states.append(b)
        return states

    @staticmethod
    def _precompute_move_meta(board_states, uci_moves):
        metas = []
        for mi, uci in enumerate(uci_moves):
            m = chess.Move.from_uci(uci); b_before = board_states[mi]
            b_after = board_states[mi + 1] if mi + 1 < len(board_states) else None
            bfr = 7 - chess.square_rank(m.from_square); bfc = chess.square_file(m.from_square)
            btr = 7 - chess.square_rank(m.to_square); btc = chess.square_file(m.to_square)
            piece_obj = b_before.piece_at(m.from_square)
            cap = b_before.piece_at(m.to_square); is_ep = b_before.is_en_passant(m)
            if is_ep:
                ep_sq = chess.square(chess.square_file(m.to_square), chess.square_rank(m.from_square))
                cap = b_before.piece_at(ep_sq)
            cap_sym = cap.symbol() if cap else '.'
            is_castle = b_before.is_castling(m); is_promo = m.promotion is not None
            is_check = b_after.is_check() if b_after else False; is_mate = b_after.is_checkmate() if b_after else False
            metas.append({
                'from': (bfr, bfc), 'to': (btr, btc), 'piece_obj': piece_obj, 'captured': cap_sym,
                'last_move': ((bfr, bfc), (btr, btc)), 'castle': is_castle, 'promo': is_promo, 'check': is_check, 'checkmate': is_mate,
            })
        return metas


    @staticmethod
    def _get_sound_samples(sound_name, sr=44100):
        def make_wood_hit(freq, duration, volume, noise_vol=0.3, decay_factor=25.0):
            """Generates a percussive 'thud' simulating a piece hitting a board."""
            n = int(sr * duration)
            if n <= 0: return np.zeros(1, dtype=np.float64)
            t = np.arange(n, dtype=np.float64) / sr
            
            # Deterministic noise for consistent acoustic transient
            rng = np.random.RandomState(42)
            noise = rng.randn(n)
            
            # Pitched element with slight inharmonicity for "wood" feel
            pitch = np.sin(2.0 * np.pi * freq * t) + 0.5 * np.sin(2.0 * np.pi * freq * 2.01 * t)
            
            # Combine tone and noise
            out = pitch + (noise_vol * noise)
            
            # Fast exponential decay - percussive sounds die out quickly
            env = np.exp(-decay_factor * t)
            
            # Tiny attack to avoid speaker click
            attack_n = int(sr * 0.003)
            if attack_n > 1:
                env[:attack_n] *= np.linspace(0.0, 1.0, attack_n)
                
            return volume * out * env

        def make_tone(freq, duration, volume, harmonics=2, decay_factor=8.0, vibrato=0.0):
            """Generates a clean, bell-like or synthetic tone."""
            n = int(sr * duration)
            if n <= 0: return np.zeros(1, dtype=np.float64)
            t = np.arange(n, dtype=np.float64) / sr
            
            # Optional vibrato for tension (used in 'check')
            mod = 1.0 + vibrato * np.sin(2.0 * np.pi * 5.0 * t)
            phase = 2.0 * np.pi * freq * t * mod
            
            out = np.sin(phase)
            for h in range(2, harmonics + 1):
                out += (1.0 / (h**1.5)) * np.sin(phase * h) # Scale harmonics by 1/h^1.5 for warmth
                
            # Bell-like exponential decay
            env = np.exp(-decay_factor * t)
            
            attack_n = int(sr * 0.005)
            if attack_n > 1:
                env[:attack_n] *= np.linspace(0.0, 1.0, attack_n)
                
            return volume * out * env

        def make_chord(freqs, duration, volume, decay_factor=3.0):
            """Generates a rich, wide chord."""
            n = int(sr * duration)
            if n <= 0: return np.zeros(1, dtype=np.float64)
            t = np.arange(n, dtype=np.float64) / sr
            out = np.zeros(n, dtype=np.float64)
            
            for f in freqs:
                # Add slight chorus/detune for richness
                out += np.sin(2.0 * np.pi * f * t)
                out += 0.5 * np.sin(2.0 * np.pi * (f * 1.002) * t) # Slight detune
                
            out /= len(freqs)
            
            # Smooth swell and decay
            env = np.exp(-decay_factor * t)
            attack_n = int(sr * 0.01)
            if attack_n > 1:
                env[:attack_n] *= np.linspace(0.0, 1.0, attack_n)
                
            return volume * out * env

        # --- SOUND DEFINITIONS ---
        
        if sound_name == 'move':
            # Short, high woody click
            return make_wood_hit(800, 0.06, 0.45, noise_vol=0.4, decay_factor=35.0)
            
        elif sound_name == 'capture':
            # Heavier, lower thud with more noise
            return make_wood_hit(350, 0.10, 0.6, noise_vol=0.6, decay_factor=20.0)
            
        elif sound_name == 'check':
            # Alarming ping with slight vibrato (tension)
            return make_tone(880, 0.25, 0.4, harmonics=3, decay_factor=5.0, vibrato=0.02)
            
        elif sound_name == 'checkmate':
            # Triumphant C Major 7 spread chord
            return make_chord([523.25, 659.25, 783.99, 1046.50], 0.8, 0.5, decay_factor=2.0)
            
        elif sound_name == 'castle':
            # King slide (higher, lighter) -> Rook impact (lower, heavier)
            return np.concatenate([
                make_wood_hit(700, 0.05, 0.4, noise_vol=0.3, decay_factor=40.0),
                np.zeros(max(1, int(sr * 0.06)), dtype=np.float64),
                make_wood_hit(400, 0.06, 0.5, noise_vol=0.5, decay_factor=30.0)
            ])
            
        elif sound_name == 'error':
            # Dull, low thud (no ring)
            return make_wood_hit(200, 0.12, 0.5, noise_vol=0.2, decay_factor=30.0)
            
        elif sound_name == 'promote':
            # Ascending arpeggio (C5 -> E5 -> G5 -> C6)
            return np.concatenate([
                make_tone(523.25, 0.08, 0.45, harmonics=2, decay_factor=10.0),
                make_tone(659.25, 0.08, 0.45, harmonics=2, decay_factor=10.0),
                make_tone(783.99, 0.08, 0.45, harmonics=2, decay_factor=10.0),
                make_tone(1046.50, 0.20, 0.55, harmonics=3, decay_factor=4.0)
            ])
            
        elif sound_name == 'start':
            # Uplifting rising 5th (C4 -> G4)
            return np.concatenate([
                make_tone(261.63, 0.12, 0.5, harmonics=2, decay_factor=6.0),
                np.zeros(max(1, int(sr * 0.04)), dtype=np.float64),
                make_tone(392.00, 0.20, 0.5, harmonics=2, decay_factor=4.0)
            ])
            
        elif sound_name == 'tick':
            # Ultra-short, high-pitched clock click
            return make_wood_hit(2500, 0.02, 0.25, noise_vol=0.7, decay_factor=50.0)
            
        elif sound_name == 'end':
            # Resolving falling 5th (G4 -> C4)
            return np.concatenate([
                make_tone(392.00, 0.15, 0.5, harmonics=2, decay_factor=5.0),
                np.zeros(max(1, int(sr * 0.05)), dtype=np.float64),
                make_tone(261.63, 0.30, 0.5, harmonics=2, decay_factor=3.0)
            ])
            
        return np.zeros(int(sr * 0.1), dtype=np.float64)

    @staticmethod
    def _check_sqs(board):
        if board.is_check():
            k = board.king(board.turn); return [(7 - chess.square_rank(k), chess.square_file(k))]
        return []

    @staticmethod
    def _build_frame_plan(cfg, fps, uci_moves, move_metas, n_anim, n_hold):
        """Return a compact list of (kind, count, *data) tuples."""
        plan = []

        # 1 Start Title
        if cfg.title_enabled:
            plan.append(('title', int(cfg.title_duration * fps)))

        plan.append(('start_hold', n_hold))

        # 2 Animated Modes
        for mi in range(len(uci_moves)):
            meta = move_metas[mi]
            plan.append(('anim', n_anim, mi, {
                'from':      meta['from'],
                'to':        meta['to'],
                'piece_obj': meta['piece_obj'],
                'captured':  meta['captured'],
            }))
            plan.append(('hold', n_hold, mi + 1, meta['last_move']))

        # 3 End Title
        if cfg.end_title_enabled:
            plan.append(('end', int(cfg.end_title_duration * fps)))

        return plan

    @staticmethod
    def _ffmpeg_cmd(w, h, fps, cfg, opening_data, output_path, audio_path=None):
        cmd = ["ffmpeg", "-y", "-f", "rawvideo", "-vcodec", "rawvideo", "-s", f"{w}x{h}", "-pix_fmt", "bgr24", "-r", str(fps), "-i", "-"]
        if audio_path: cmd.extend(["-i", audio_path])
        cmd.extend(["-c:v", "libx264", "-profile:v", "high", "-level", "4.1", "-pix_fmt", "yuv420p", "-crf", str(cfg.ffmpeg_crf), "-preset", cfg.ffmpeg_preset, "-bf", "2", "-g", str(fps * 2), "-keyint_min", str(fps), "-sc_threshold", "0", "-movflags", "+faststart", "-metadata", f"title={opening_data.get('name', 'Chess Opening')}"])
        if audio_path: cmd.extend(["-c:a", "aac", "-b:a", "192k", "-shortest"])
        else: cmd.append("-an")
        cmd.append(output_path); return cmd

    @staticmethod
    def _safe_close(proc):
        try: proc.stdin.close()
        except Exception: pass
        proc.terminate()

# ═══════════════════════════════════════════════════════════════════════════════
#  ENTRY POINT
# ═══════════════════════════════════════════════════════════════════════════════

def main():
    app = QApplication(sys.argv)
    app.setStyle("Fusion")

    # Dark palette
    palette = QPalette()
    palette.setColor(QPalette.Window, QColor(18, 18, 30))
    palette.setColor(QPalette.WindowText, QColor(220, 220, 230))
    palette.setColor(QPalette.Base, QColor(30, 30, 42))
    palette.setColor(QPalette.AlternateBase, QColor(34, 34, 58))
    palette.setColor(QPalette.ToolTipBase, QColor(30, 30, 46))
    palette.setColor(QPalette.ToolTipText, QColor(220, 220, 230))
    palette.setColor(QPalette.Text, QColor(220, 220, 230))
    palette.setColor(QPalette.Button, QColor(42, 42, 58))
    palette.setColor(QPalette.ButtonText, QColor(220, 220, 230))
    palette.setColor(QPalette.Highlight, QColor(42, 130, 218))
    palette.setColor(QPalette.HighlightedText, QColor(255, 255, 255))
    app.setPalette(palette)

    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()