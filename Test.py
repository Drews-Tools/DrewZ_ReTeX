# main.py
import sys
import os
import io
import hashlib
import logging
import webbrowser
import requests
import json
import subprocess
import time
import shutil
import threading
import random
from rarfile import RarFile, BadRarFile
from PIL import Image, ImageChops, ImageQt, ImageDraw, ImageFont, ImageEnhance

from PySide6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QComboBox,
    QLabel, QMessageBox, QFileDialog, QScrollArea, QDialog, QListWidget,
    QListWidgetItem, QSizePolicy, QFrame, QLineEdit, QGraphicsView,
    QGraphicsScene, QGraphicsTextItem, QColorDialog, QSpinBox, QDialogButtonBox,
    QGraphicsPixmapItem, QProgressBar, QGroupBox, QCheckBox,
    QSlider, QInputDialog, QGraphicsItem
)
from PySide6.QtGui import (
    Qt, QPalette, QColor, QFont, QFontDatabase, QPainter, QImage, QPen,
    QFontMetrics, QIcon, QPixmap
)
from PySide6.QtCore import QSize, Qt, QPointF, QRectF, Signal, Slot, QThread

# Import the LoginPanel
from scripts.login_panel import LoginPanel

from scripts.essentials import ( 
    PreviewGraphicsView, OptionsDialog, LoadingDialog, FontSelectionDialog,
    ApplyTextureThread, PreviewDialog, ConvertToPAAThread,
    DuplicateDialog, ResizableIconItem, ResizableTextItem,  BlendingHelper
)

from scripts.instructions import InstructionsDialog
###############################################################################
# We are using EXACT 1:1 pixel sizes (no DPI adjust). We'll add extra logs.
###############################################################################
os.environ['PATH'] = os.path.dirname(__file__) + os.pathsep + os.environ['PATH']
base_path = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
icon_path = os.path.join(base_path, "resources/images/app_icon.ico")

# Removed log_file and FileHandler to disable file logging
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler()
    ]
)
# ---------------------------------------------------------------------------
# Helper function to convert a PIL Image to a QPixmap
# ---------------------------------------------------------------------------
def pil2pixmap(pil_image):
    """
    Converts a PIL Image to QPixmap.
    """
    if pil_image.mode != "RGBA":
        pil_image = pil_image.convert("RGBA")
    # Convert the image data to bytes
    data = pil_image.tobytes("raw", "RGBA")
    bytes_per_line = pil_image.size[0] * 4  # 4 bytes per pixel for RGBA
    qimage = QImage(data, pil_image.size[0], pil_image.size[1], bytes_per_line, QImage.Format_RGBA8888)
    return QPixmap.fromImage(qimage)

# ---------------------------------------------------------------------------
# UpdateThread: Manages the "Updater" download and RAR extraction in background
# ---------------------------------------------------------------------------
class UpdateThread(QThread):
    progress = Signal(str, int)
    finished = Signal()
    error = Signal(str)

    def __init__(self, download_url, archive_name, parent=None):
        super().__init__(parent)
        self.download_url = download_url
        self.archive_name = archive_name
        self.root_dir = getattr(sys, '_MEIPASS', os.path.dirname(os.path.abspath(sys.argv[0])))
        logging.info(f"UpdateThread init, root_dir={self.root_dir}")
        self.rar_path = os.path.join(self.root_dir, self.archive_name)
        self.extract_dir = os.path.join(self.root_dir, "Update")
        self.main_app_name = "Updater.exe"
        logging.info(f"rar_path={self.rar_path}")
        logging.info(f"extract_dir={self.extract_dir}")

    def extract_rar(self, rar_path, extract_to):
        logging.info(f"Extracting RAR: {rar_path} => {extract_to}")
        try:
            os.makedirs(extract_to, exist_ok=True)
            unrar_exe = os.path.join(self.root_dir, 'UnRAR.exe')
            logging.info(f"unrar_exe path: {unrar_exe}")
            if not os.path.exists(unrar_exe):
                source_unrar = os.path.join(self.root_dir, "resources", "tools", "UnRAR.exe")
                logging.info(f"source_unrar path: {source_unrar}")
                if os.path.exists(source_unrar):
                    shutil.copy(source_unrar, unrar_exe)
                    logging.info(f"Copied UnRAR.exe to root directory at {unrar_exe}.")
                else:
                    error_msg = f"UnRAR.exe not found in resources at {source_unrar}"
                    logging.error(error_msg)
                    raise FileNotFoundError(error_msg)

            RarFile.UNRAR_TOOL = unrar_exe
            logging.info(f"Set RarFile.UNRAR_TOOL to {RarFile.UNRAR_TOOL}.")

            with RarFile(rar_path) as rf:
                file_list = rf.namelist()
                logging.info(f"Files in RAR archive: {file_list}")
                if "Updater.exe" not in file_list and "Updater\\Updater.exe" not in file_list:
                    error_msg = "Updater.exe not found in the RAR archive."
                    logging.error(error_msg)
                    raise FileNotFoundError(error_msg)

                logging.info(f"Extracting files to: {extract_to}")
                rf.extractall(path=extract_to)
                logging.info(f"Extracted update archive successfully.")

        except BadRarFile:
            error_msg = "Failed to extract the .rar file. It may be corrupted."
            logging.error(error_msg)
            self.error.emit(error_msg)
            return
        except FileNotFoundError as fnf_error:
            logging.error(fnf_error)
            self.error.emit(str(fnf_error))
            return
        except Exception as e:
            error_msg = f"An error occurred during extraction: {e}"
            logging.error(error_msg)
            self.error.emit(error_msg)
            return

    def list_rar_contents(self, rar_path):
        logging.info(f"Listing contents of RAR file: {rar_path}")
        try:
            with RarFile(rar_path) as rf:
                contents = rf.namelist()
                logging.info(f"RAR contents: {contents}")
                return contents
        except Exception as e:
            logging.error(f"Failed to list RAR contents: {e}")
            self.error.emit(f"Failed to list RAR contents: {e}")
            return []

    def launch_updater_detached(self, updater_path):
        try:
            if sys.platform == "win32":
                batch_content = f'start "" "{updater_path}"'
                batch_path = os.path.join(self.root_dir, "launch_updater.bat")
                with open(batch_path, 'w') as batch_file:
                    batch_file.write(batch_content)
                logging.info(f"Batch file created at: {batch_path}")

                subprocess.Popen(['cmd', '/c', batch_path], shell=True)
                logging.info("Updater launched successfully via batch file.")
                self.progress.emit("Updater launched successfully.", 95)

                def delete_batch():
                    try:
                        time.sleep(1)
                        os.remove(batch_path)
                        logging.info(f"Batch file deleted: {batch_path}")
                    except Exception as e:
                        logging.warning(f"Could not delete batch file: {e}")

                delete_thread = threading.Thread(target=delete_batch, daemon=True)
                delete_thread.start()
            else:
                subprocess.Popen(
                    [updater_path],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    stdin=subprocess.DEVNULL,
                    preexec_fn=os.setpgrp
                )
                logging.info("Updater launched successfully as a detached process.")
                self.progress.emit("Updater launched successfully.", 95)
        except Exception as e:
            error_msg = f"Failed to launch Updater.exe as a detached process: {e}"
            logging.error(error_msg)
            self.error.emit(error_msg)

    def run(self):
        logging.info("UpdateThread started.")
        try:
            self.progress.emit("Starting update...", 0)
            logging.info("Starting update process...")

            self.progress.emit("Downloading update...", 10)
            logging.info("Downloading update...")
            with requests.get(self.download_url, stream=True, timeout=60) as r:
                logging.info(f"HTTP GET Request sent to {self.download_url}")
                r.raise_for_status()
                total_length = r.headers.get('content-length')
                logging.info(f"Content-Length: {total_length}")
                if total_length is None:
                    logging.info("No content-length header; downloading without progress tracking.")
                    with open(self.rar_path, 'wb') as f:
                        shutil.copyfileobj(r.raw, f)
                        logging.info(f"Downloaded file saved to {self.rar_path}")
                else:
                    total_length = int(total_length)
                    downloaded = 0
                    chunk_size = 8192
                    logging.info(f"Total size to download: {total_length} bytes")
                    with open(self.rar_path, 'wb') as f:
                        for chunk in r.iter_content(chunk_size=chunk_size):
                            if chunk:
                                f.write(chunk)
                                downloaded += len(chunk)
                                progress_percent = 10 + int((downloaded / total_length) * 40)
                                logging.info(f"Downloaded {downloaded} of {total_length} bytes ({progress_percent}%)")
                                self.progress.emit("Downloading update...", min(progress_percent, 50))

            self.progress.emit("Download completed.", 50)
            logging.info("Download completed.")

            self.progress.emit("Extracting update...", 60)
            logging.info("Extracting update...")
            self.extract_rar(self.rar_path, self.extract_dir)
            self.progress.emit("Extraction completed.", 70)
            logging.info("Extraction completed.")

            logging.info(f"Listing files in {self.extract_dir}:")
            for root, dirs, files in os.walk(self.extract_dir):
                level = root.replace(self.extract_dir, '').count(os.sep)
                indent = ' ' * 4 * (level)
                logging.info(f"{indent}{os.path.basename(root)}/")
                subindent = ' ' * 4 * (level + 1)
                for f in files:
                    logging.info(f"{subindent}{f}")

            self.progress.emit("Moving Updater.exe to root directory...", 80)
            updater_extracted_path = os.path.join(self.extract_dir, "Updater.exe")
            updater_target_path = os.path.join(self.root_dir, "Updater.exe")
            logging.info(f"updater_extracted_path: {updater_extracted_path}")
            logging.info(f"updater_target_path: {updater_target_path}")

            if not os.path.exists(updater_extracted_path):
                logging.info(f"Updater.exe not found at {updater_extracted_path}. Searching subdirectories...")
                found = False
                for root, dirs, files in os.walk(self.extract_dir):
                    if "Updater.exe" in files:
                        updater_extracted_path = os.path.join(root, "Updater.exe")
                        found = True
                        logging.info(f"Found Updater.exe at {updater_extracted_path}")
                        break
                if not found:
                    error_msg = f"Updater.exe not found in the extracted files: {self.extract_dir}"
                    logging.error(error_msg)
                    raise FileNotFoundError(error_msg)

            shutil.move(updater_extracted_path, updater_target_path)
            logging.info(f"Moved Updater.exe to root directory at {updater_target_path}.")
            self.progress.emit("Updater.exe moved successfully.", 85)
            logging.info("Updater.exe moved successfully.")

            self.progress.emit("Launching Updater.exe...", 90)
            logging.info("Launching Updater.exe...")
            self.launch_updater_detached(updater_target_path)

            self.progress.emit("Update process completed.", 100)
            logging.info("Update process completed.")
            self.finished.emit()

        except Exception as e:
            error_msg = f"UpdateThread encountered an error: {e}"
            logging.error(error_msg)
            self.error.emit(str(e))
            return

# ---------------------------------------------------------------------------
# TexturingApp
# ---------------------------------------------------------------------------

class TexturingApp(QWidget):
    CURRENT_VERSION = "1.0.0"

    def __init__(self):
        super().__init__()
        self.root_dir = getattr(sys, '_MEIPASS', os.path.dirname(os.path.abspath(__file__)))
        self.setWindowTitle("DayZReSkin")
        icon_path = os.path.join(self.root_dir, "resources", "images", "app_icon.ico")
        self.setWindowIcon(QIcon(icon_path))
        self.resize(2200, 1200)
        self.showMaximized()

        # Define themes and current theme
        self.themes = {
            "dark": "dark",
            "light": "light"
        }
        self.current_theme = "dark"  # Default theme

        # Template & textures
        self.template_path = ""
        self.output_folder = ""
        self.texture_folder = ""
        self.texture_files = []
        self.template_image = None
        self.blended_image = None  # Added to store the blended image
        self.texture_previews = {}
        self.current_texture_file = None  # To track the selected texture

        # Font settings
        self.selected_font_path = ""
        self.loaded_font_id = -1
        self.selected_font_family = "Arial"
        self.selected_font_size = 24

        # Current text color
        self.current_text_color = QColor(255, 255, 255)

        # Option settings for additional processing
        self.opt_generate_scripts_options = ""
        self.opt_pack_into_pbo_options = ""

        # Additional user fields for "Generate Scripts"
        self.opt_dependent_mod = ""       # (Optional)
        self.opt_mod_name = ""           # (Required for naming, etc.)
        self.opt_parent_classname = ""   # e.g., "TShirt_Base"
        self.opt_hidden_selections = ""  # comma-separated

        # Additional user fields for "Pack into .PBO" signing
        # 'none', 'use_existing', 'create_new'
        self.opt_pbo_signing_choice = "none"
        self.opt_existing_biprivatekey = ""
        self.opt_existing_bikey = ""
        self.opt_new_key_name = ""

        # Auto-detect the DayZ Tools directory
        self.dayz_tools_dir = ""
        self.auto_detect_dayz_tools()

        # Define blending mode mapping (Updated to align with essentials.py)
        self.blending_mode_map = {
            "Normal": "normal",
            "Multiply": "multiply",
            "Screen": "screen",     # <--- add this
            "Overlay Light": "overlay_light",
            "Overlay Half": "overlay_half",
            "Overlay Heavy": "overlay_heavy",
            "Overlay Full": "overlay_full",
            "Soft Light": "soft_light",
            "Hard Light": "hard_light",
            "Difference": "difference"
        }

        # Flag to prevent multiple texture applications
        self.is_applying_texture = False

        self.init_ui()
        logging.info("UI initialized.")

    def auto_detect_dayz_tools(self):
        default_paths = [
            r"E:\Steam\steamapps\common\DayZ Tools",
            r"G:\Steam\steamapps\common\DayZ Tools",
            r"F:\Steam\steamapps\common\DayZ Tools",
            r"D:\Steam\steamapps\common\DayZ Tools",
            r"K:\Steam\steamapps\common\DayZ Tools",
            r"A:\Steam\steamapps\common\DayZ Tools",
            r"C:\Program Files\Steam\steamapps\common\DayZ Tools",
            r"C:\Program Files (86)\Steam\steamapps\common\DayZ Tools",
            r"C:\Games\Steam\steamapps\common\DayZ Tools",
            r"E:\Games\Steam\steamapps\common\DayZ Tools",
            r"D:\Games\Steam\steamapps\common\DayZ Tools"
        ]
        for path in default_paths:
            if os.path.exists(path):
                self.dayz_tools_dir = path
                logging.info(f"Auto-detected DayZ Tools directory: {path}")
                break
        if not self.dayz_tools_dir:
            self.dayz_tools_dir = QFileDialog.getExistingDirectory(self, "Select DayZ Tools Directory", "")
            if not self.dayz_tools_dir:
                QMessageBox.warning(self, "Warning", "DayZ Tools directory was not selected. Some features may not work correctly.")
                logging.warning("DayZ Tools directory was not selected by the user.")
            else:
                logging.info(f"User selected DayZ Tools directory: {self.dayz_tools_dir}")

    def init_ui(self):
        self.apply_dark_theme()
        main_layout = QVBoxLayout()
        main_layout.setContentsMargins(10, 10, 10, 10)
        self.setLayout(main_layout)

        # Header
        header_frame = QFrame()
        header_frame.setFrameShape(QFrame.Box)
        header_frame.setLineWidth(2)
        header_layout = QHBoxLayout()
        header_layout.setAlignment(Qt.AlignCenter)
        header_frame.setLayout(header_layout)

        header_label = QLabel()
        header_label.setText("""
            <span style="color: #007acc; font-size: 24pt; font-weight: bold;">
                <span style="color: #ba1111;">Day</span><span style="color: #ba1111;">Z</span><span style="color: #9dff00;">Re</span><span style="color: #ff4081;">S</span><span style="color: #40c4ff;">k</span><span style="color: #ffeb3b;">i</span><span style="color: #8bc34a;">n</span>
            </span>
        """)
        header_label.setAlignment(Qt.AlignCenter)
        header_layout.addWidget(header_label)
        main_layout.addWidget(header_frame)

        # Main scroll area
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setStyleSheet("background-color: #2c2c2c;")
        main_layout.addWidget(scroll_area)

        content_widget = QWidget()
        scroll_area.setWidget(content_widget)
        content_layout = QVBoxLayout()
        content_widget.setLayout(content_layout)

        # Top layout with Buttons
        top_layout = QHBoxLayout()
        self.template_button = QPushButton("Select Template")
        self.template_button.clicked.connect(self.load_template)
        self.style_button(self.template_button)
        top_layout.addWidget(self.template_button)

        self.texture_button = QPushButton("Select Texture Folder")
        self.texture_button.clicked.connect(self.load_textures)
        self.style_button(self.texture_button)
        top_layout.addWidget(self.texture_button)

        self.scan_duplicates_button = QPushButton("Scan for Duplicates")
        self.scan_duplicates_button.clicked.connect(self.scan_for_duplicates)
        self.scan_duplicates_button.setVisible(False)
        self.style_button(self.scan_duplicates_button)
        top_layout.addWidget(self.scan_duplicates_button)

        self.output_button = QPushButton("Select Output Folder")
        self.output_button.clicked.connect(self.select_output_folder)
        self.style_button(self.output_button)
        top_layout.addWidget(self.output_button)

        self.logout_button = QPushButton("Logout")
        self.logout_button.clicked.connect(self.logout_action)
        self.style_button(self.logout_button)
        top_layout.addWidget(self.logout_button)

        # Instructions Button
        self.instructions_button = QPushButton("Instructions")
        self.instructions_button.clicked.connect(self.open_instructions)
        self.style_button(self.instructions_button, highlight=True)
        top_layout.addWidget(self.instructions_button)

        # Discord Button
        self.discord_button = QPushButton("Join Discord")
        self.discord_button.clicked.connect(self.open_discord_link)
        self.style_button(self.discord_button, highlight=True)
        top_layout.addWidget(self.discord_button)

        top_layout.addStretch()
        content_layout.addLayout(top_layout)

        # Options Checkboxes
        options_layout = QHBoxLayout()
        self.chk_convert_to_paa = QCheckBox("Convert to .PAA")
        self.chk_generate_scripts = QCheckBox("Generate Scripts")
        self.chk_pack_into_pbo = QCheckBox("Pack into .PBO")
        options_layout.addWidget(self.chk_convert_to_paa)
        options_layout.addWidget(self.chk_generate_scripts)
        options_layout.addWidget(self.chk_pack_into_pbo)
        options_layout.addStretch()
        self.options_button = QPushButton("Options")
        self.options_button.clicked.connect(self.open_options_dialog)
        self.style_button(self.options_button, highlight=True)
        options_layout.addWidget(self.options_button)
        content_layout.addLayout(options_layout)

        # Connect checkboxes to update their states
        self.chk_convert_to_paa.stateChanged.connect(self.update_checkbox_states)
        self.chk_generate_scripts.stateChanged.connect(self.update_checkbox_states)
        self.update_checkbox_states()

        # Blending mode
        blending_layout = QHBoxLayout()
        blending_label = QLabel("Blending Mode:")
        blending_label.setStyleSheet("color: white;")
        self.blending_mode = QComboBox()
        self.blending_mode.addItems([
            "Normal",
            "Multiply",
            "Screen",
            "Overlay Light",
            "Overlay Half",
            "Overlay Heavy",
            "Overlay Full",
            "Soft Light",
            "Hard Light",
            "Difference"
        ])
        blending_layout.addWidget(blending_label)
        blending_layout.addWidget(self.blending_mode)
        blending_layout.addStretch()
        content_layout.addLayout(blending_layout)

        # Controls Layout
        controls_layout = QVBoxLayout()
        main_layout.addLayout(controls_layout)

        # Connect blending mode change to preview generation
        self.blending_mode.currentIndexChanged.connect(self.generate_preview)

        # Central layout
        central_layout = QHBoxLayout()
        content_layout.addLayout(central_layout)

        # Left Layout (Template and Textures)
        left_layout = QVBoxLayout()
        central_layout.addLayout(left_layout, 3)

        # Template Preview Group
        template_group = QGroupBox("Template Preview")
        template_group.setStyleSheet("QGroupBox { color: white; }")
        template_group_layout = QVBoxLayout()
        template_group.setLayout(template_group_layout)

        template_label_title = QLabel("Template Preview")
        template_label_title.setAlignment(Qt.AlignCenter)
        template_label_title.setStyleSheet("color: white; font-weight: bold;")
        template_group_layout.addWidget(template_label_title)

        self.template_label = QLabel()
        self.template_label.setAlignment(Qt.AlignCenter)
        self.template_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.template_label.setFrameStyle(QFrame.Box | QFrame.Plain)
        self.template_label.setStyleSheet("border: 2px solid gray; background-color: #1e1e1e;")
        self.template_label.setFixedHeight(500)
        template_group_layout.addWidget(self.template_label)
        left_layout.addWidget(template_group)

        # Texture Previews Group
        textures_group = QGroupBox("Texture Previews")
        textures_group.setStyleSheet("QGroupBox { color: white; }")
        textures_group_layout = QVBoxLayout()
        textures_group.setLayout(textures_group_layout)

        textures_label_title = QLabel("Texture Previews")
        textures_label_title.setAlignment(Qt.AlignCenter)
        textures_label_title.setStyleSheet("color: white; font-weight: bold;")
        textures_group_layout.addWidget(textures_label_title)

        scroll_area_textures = QScrollArea()
        scroll_area_textures.setWidgetResizable(True)
        scroll_area_textures.setStyleSheet("background-color: #2c2c2c; border: 1px solid gray;")
        scroll_area_textures.setFixedHeight(500)
        self.thumbnail_container = QWidget()
        self.thumbnail_layout = QHBoxLayout(self.thumbnail_container)
        self.thumbnail_layout.setAlignment(Qt.AlignLeft)
        self.thumbnail_layout.setSpacing(10)
        scroll_area_textures.setWidget(self.thumbnail_container)
        textures_group_layout.addWidget(scroll_area_textures)

        left_layout.addWidget(textures_group)
        left_layout.addStretch()

        # Right Layout (Output Images)
        right_layout = QVBoxLayout()
        central_layout.addLayout(right_layout, 2)

        output_list_label = QLabel("Output Images")
        output_list_label.setAlignment(Qt.AlignCenter)
        output_list_label.setStyleSheet("color: white; font-weight: bold;")
        right_layout.addWidget(output_list_label)

        self.output_list = QListWidget()
        self.output_list.setStyleSheet("""
            QListWidget {
                background-color: #3c3c3c;
                border: 1px solid gray;
                color: white;
            }
            QListWidget::item:selected {
                background-color: #555555;
            }
        """)
        self.output_list.setIconSize(QSize(100, 100))
        self.output_list.setFixedHeight(500)
        self.output_list.itemClicked.connect(self.display_selected_output)
        right_layout.addWidget(self.output_list)

        output_preview_label = QLabel("Selected Output Preview")
        output_preview_label.setAlignment(Qt.AlignCenter)
        output_preview_label.setStyleSheet("color: white; font-weight: bold;")
        right_layout.addWidget(output_preview_label)

        self.scene = QGraphicsScene()
        self.output_preview_view = PreviewGraphicsView(self.scene)
        self.output_preview_view.setFixedHeight(500)
        self.output_preview_view.setStyleSheet("background-color: #1e1e1e;")
        right_layout.addWidget(self.output_preview_view)

        self.scene.selectionChanged.connect(self.on_selection_changed)
        right_layout.addStretch()

        # Apply Texture Frame
        texture_apply_frame = QFrame()
        texture_apply_frame.setFrameShape(QFrame.Box)
        texture_apply_frame.setLineWidth(2)
        texture_apply_layout = QHBoxLayout()
        texture_apply_layout.setContentsMargins(10, 10, 10, 10)
        texture_apply_frame.setLayout(texture_apply_layout)

        rename_label = QLabel("Base Name:")
        rename_label.setStyleSheet("color: white;")
        self.rename_input = QLineEdit()
        self.rename_input.setPlaceholderText("Enter base name for output images")
        self.rename_input.setStyleSheet("""
            QLineEdit {
                background-color: #3c3c3c;
                color: white;
                border: 1px solid gray;
                padding: 5px;
                border-radius: 5px;
            }
        """)
        texture_apply_layout.addWidget(rename_label)
        texture_apply_layout.addWidget(self.rename_input)

        # Renamed Apply Button
        self.apply_button = QPushButton("Blend to Template")  # Renamed here
        self.apply_button.clicked.connect(self.apply_texture)
        self.style_button(self.apply_button, highlight=True)
        texture_apply_layout.addWidget(self.apply_button)
        texture_apply_layout.addStretch()
        content_layout.addWidget(texture_apply_frame)

        # Convert to .PAA button
        self.convert_to_paa_button = QPushButton("Convert to .PAA")
        self.convert_to_paa_button.clicked.connect(self.convert_to_paa)
        self.style_button(self.convert_to_paa_button, highlight=True)  # Highlight style for visibility
        self.convert_to_paa_button.setVisible(False)  # Initially hidden
        content_layout.addWidget(self.convert_to_paa_button)

        # Connect the checkbox to toggle the button visibility
        self.convert_to_paa_button.hide()  # Hide initially

        # Text Section Grouped into QGroupBox
        self.text_group = QGroupBox("Text Options")
        self.text_group.setStyleSheet("QGroupBox { color: white; }")
        text_group_layout = QHBoxLayout()
        self.text_group.setLayout(text_group_layout)

        self.text_input = QLineEdit()
        self.text_input.setPlaceholderText("Enter text to add")
        self.text_input.setStyleSheet("""
            QLineEdit {
                background-color: #3c3c3c;
                color: white;
                border: 1px solid gray;
                padding: 5px;
                border-radius: 5px;
            }
        """)
        text_group_layout.addWidget(self.text_input)

        self.text_color_button = QPushButton("Color")
        self.text_color_button.clicked.connect(self.select_text_color)
        self.style_button(self.text_color_button)
        text_group_layout.addWidget(self.text_color_button)

        self.add_text_button = QPushButton("Add Text")
        self.add_text_button.clicked.connect(self.add_text_to_preview)
        self.style_button(self.add_text_button)
        text_group_layout.addWidget(self.add_text_button)

        text_group_layout.addStretch()
        self.text_group.hide()  # Hide initially
        content_layout.addWidget(self.text_group)

        # Font Section Grouped into QGroupBox
        self.font_group = QGroupBox("Font Options")
        self.font_group.setStyleSheet("QGroupBox { color: white; }")
        font_group_layout = QHBoxLayout()
        self.font_group.setLayout(font_group_layout)

        self.select_font_button = QPushButton("Select Font")
        self.select_font_button.clicked.connect(self.select_font)
        self.style_button(self.select_font_button)
        font_group_layout.addWidget(self.select_font_button)

        self.selected_font_label = QLabel(f"Font: {self.selected_font_family}")
        self.selected_font_label.setStyleSheet("color: white;")
        font_group_layout.addWidget(self.selected_font_label)

        font_size_label = QLabel("Size:")
        font_size_label.setStyleSheet("color: white;")
        self.font_size_spinbox = QSpinBox()
        self.font_size_spinbox.setRange(6, 300)
        self.font_size_spinbox.setValue(self.selected_font_size)
        self.font_size_spinbox.setStyleSheet("""
            QSpinBox {
                background-color: #3c3c3c;
                color: white;
                border: 1px solid gray;
                padding: 2px;
                border-radius: 2px;
            }
        """)
        self.font_size_spinbox.valueChanged.connect(self.update_font_size)
        font_group_layout.addWidget(font_size_label)
        font_group_layout.addWidget(self.font_size_spinbox)

        self.update_text_image_button = QPushButton("Update Selected Item")
        self.update_text_image_button.clicked.connect(self.update_selected_item)
        self.update_text_image_button.setEnabled(False)
        self.style_button(self.update_text_image_button)
        font_group_layout.addWidget(self.update_text_image_button)

        self.update_font_button = QPushButton("Update Selected Font")
        self.update_font_button.clicked.connect(self.update_selected_font)
        self.update_font_button.setEnabled(False)
        self.style_button(self.update_font_button)
        font_group_layout.addWidget(self.update_font_button)

        self.update_font_size_spinbox = QSpinBox()
        self.update_font_size_spinbox.setRange(6, 300)
        self.update_font_size_spinbox.setValue(self.selected_font_size)
        self.update_font_size_spinbox.setStyleSheet("""
            QSpinBox {
                background-color: #3c3c3c;
                color: white;
                border: 1px solid gray;
                padding: 2px;
                border-radius: 2px;
            }
        """)
        self.update_font_size_spinbox.valueChanged.connect(self.update_selected_font_size)
        self.update_font_size_spinbox.setEnabled(False)
        font_group_layout.addWidget(QLabel("Selected Font Size:"))
        font_group_layout.addWidget(self.update_font_size_spinbox)

        font_group_layout.addStretch()
        self.font_group.hide()  # Hide initially
        content_layout.addWidget(self.font_group)

        # --------------------------------------------------------------------
        # NEW: Image/Icon Options Section
        # --------------------------------------------------------------------
        self.icon_group = QGroupBox("Image/Icon Options")
        self.icon_group.setStyleSheet("QGroupBox { color: white; }")
        icon_layout = QHBoxLayout()
        self.icon_group.setLayout(icon_layout)

        self.add_icon_button = QPushButton("Add Image/Icon")
        self.add_icon_button.clicked.connect(self.add_icon)
        self.style_button(self.add_icon_button, highlight=True)
        icon_layout.addWidget(self.add_icon_button)

        self.clear_icon_button = QPushButton("Clear Selected Image/Icon")
        self.clear_icon_button.clicked.connect(self.clear_selected_icon)
        self.style_button(self.clear_icon_button)
        icon_layout.addWidget(self.clear_icon_button)

        icon_layout.addStretch()
        self.icon_group.hide()  # Hide initially until blending is done
        content_layout.addWidget(self.icon_group)
        # --------------------------------------------------------------------

        # Add the "Apply to Current Texture" and "Apply to All Textures" buttons below Image/Icon Options
        apply_texture_layout = QHBoxLayout()
        self.apply_to_current_texture_button = QPushButton("Apply to Current Texture")
        self.apply_to_current_texture_button.clicked.connect(self.apply_to_current_texture)
        self.style_button(self.apply_to_current_texture_button, highlight=True)
        self.apply_to_current_texture_button.setFixedWidth(200)  # Set wider width as desired
        self.apply_to_current_texture_button.setVisible(False)    # Hide initially
        apply_texture_layout.addWidget(self.apply_to_current_texture_button)

        self.apply_to_all_textures_button = QPushButton("Apply to All Textures")
        self.apply_to_all_textures_button.clicked.connect(self.apply_to_all_textures)
        self.style_button(self.apply_to_all_textures_button, highlight=True)
        self.apply_to_all_textures_button.setFixedWidth(200)  # Set wider width as desired
        self.apply_to_all_textures_button.setVisible(False)     # Hide initially
        apply_texture_layout.addWidget(self.apply_to_all_textures_button)

        apply_texture_layout.addStretch()
        content_layout.addLayout(apply_texture_layout)

        # --------------------------------------------------------------------
        # NEW: Bottom Frame with "Drew's Tools" and Version
        # --------------------------------------------------------------------
        bottom_frame = QFrame()
        bottom_frame.setFrameShape(QFrame.Box)
        bottom_frame.setLineWidth(2)
        bottom_layout = QHBoxLayout()
        bottom_layout.setContentsMargins(10, 10, 10, 10)
        bottom_frame.setLayout(bottom_layout)

        # "Drew's Tools" Label
        drews_tools_label = QLabel("Drew's Tools")
        drews_tools_label.setStyleSheet("color: white; font-weight: bold; font-size: 14pt;")
        drews_tools_label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)

        # Version Label
        self.version_label = QLabel("Version: ")
        self.version_label.setStyleSheet("color: white; font-size: 14pt;")
        self.version_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)

        bottom_layout.addWidget(drews_tools_label, alignment=Qt.AlignLeft)
        bottom_layout.addStretch()
        bottom_layout.addWidget(self.version_label, alignment=Qt.AlignRight)

        content_layout.addWidget(bottom_frame)
        # --------------------------------------------------------------------
        self.check_version()

        # Brightness and Contrast Controls
        brightness_label = QLabel("Brightness:")
        brightness_label.setStyleSheet("color: white;")
        self.brightness_slider = QSlider(Qt.Horizontal)
        self.brightness_slider.setRange(0, 200)  # 100 is the default (no change)
        self.brightness_slider.setValue(100)
        self.brightness_slider.setToolTip("Adjust Brightness")
        self.brightness_slider.valueChanged.connect(self.update_preview)

        self.brightness_value_label = QLabel("100%")
        self.brightness_value_label.setStyleSheet("color: white;")
        self.brightness_value_label.setFixedWidth(50)

        contrast_label = QLabel("Contrast:")
        contrast_label.setStyleSheet("color: white;")
        self.contrast_slider = QSlider(Qt.Horizontal)
        self.contrast_slider.setRange(0, 200)  # 100 is the default (no change)
        self.contrast_slider.setValue(100)
        self.contrast_slider.setToolTip("Adjust Contrast")
        self.contrast_slider.valueChanged.connect(self.update_preview)

        self.contrast_value_label = QLabel("100%")
        self.contrast_value_label.setStyleSheet("color: white;")
        self.contrast_value_label.setFixedWidth(50)

        # Apply Adjustments Button
        self.apply_adjustments_button = QPushButton("Apply Brightness/Contrast to All")
        self.apply_adjustments_button.setStyleSheet("""
            QPushButton {
                background-color: #5cb85c;
                color: white;
                border: none;
                padding: 10px;
                border-radius: 5px;
            }
            QPushButton:hover {
                background-color: #4cae4c;
            }
        """)
        self.apply_adjustments_button.clicked.connect(self.apply_brightness_contrast_to_all)
        self.apply_adjustments_button.setEnabled(False)  # Disabled until textures are applied

        # Reset Brightness Button
        self.reset_brightness_button = QPushButton("Reset Brightness")
        self.reset_brightness_button.clicked.connect(lambda: self.brightness_slider.setValue(100))
        self.style_button(self.reset_brightness_button)

        # Reset Contrast Button
        self.reset_contrast_button = QPushButton("Reset Contrast")
        self.reset_contrast_button.clicked.connect(lambda: self.contrast_slider.setValue(100))
        self.style_button(self.reset_contrast_button)

        # Layout for Brightness and Contrast
        brightness_layout = QHBoxLayout()
        brightness_layout.addWidget(brightness_label)
        brightness_layout.addWidget(self.brightness_slider)
        brightness_layout.addWidget(self.brightness_value_label)

        contrast_layout = QHBoxLayout()
        contrast_layout.addWidget(contrast_label)
        contrast_layout.addWidget(self.contrast_slider)
        contrast_layout.addWidget(self.contrast_value_label)

        # Add to the main layout
        controls_layout.addWidget(self.reset_brightness_button)
        controls_layout.addWidget(self.reset_contrast_button)
        controls_layout.addLayout(brightness_layout)
        controls_layout.addLayout(contrast_layout)
        controls_layout.addWidget(self.apply_adjustments_button)

        # Initially hide grouped widgets
        self.text_group.hide()
        self.font_group.hide()
        self.convert_to_paa_button.hide()

    # ---------------------------
    # New Apply Texture Methods
    # ---------------------------
    # Define the function to toggle visibility
    def toggle_paa_button_visibility(self, state):
        self.convert_to_paa_butto

    def apply_to_current_texture(self):
        """
        Applies both text and image/icon to the current texture
        without showing separate warnings if only one is missing.
        """
        logging.info("Applying to current texture: Combining text and image/icon applications.")

        # Get all items in the scene
        items = self.scene.items()
        text_items = [i for i in items if isinstance(i, ResizableTextItem)]
        icon_items = [i for i in items if isinstance(i, ResizableIconItem)]

        # If absolutely no text AND no icons are in the scene, show ONE warning
        if not text_items and not icon_items:
            QMessageBox.warning(
                self,
                "Warning",
                "No text or image/icon items found.\n\n"
                "Please add some text or an image/icon first!"
            )
            return

        # If we have text items, apply them (suppress sub-warnings)
        if text_items:
            self.apply_only_text_to_current(show_warnings=False)

        # If we have icon items, apply them (suppress sub-warnings)
        if icon_items:
            self.apply_icon_to_current_preview(show_warnings=False)

        # Finally, show one "Done" message
        QMessageBox.information(
            self,
            "Done",
            "Applied text and/or icons/images to the current texture."
        )
        logging.info("apply_to_current_texture: Completed text + icon on current texture.")


    def apply_to_all_textures(self):
        logging.info("Applying to all textures: Combining text and image/icon applications.")

        # Figure out if we have text and/or icon items
        items = self.scene.items()
        text_items = [i for i in items if isinstance(i, ResizableTextItem)]
        icon_items = [i for i in items if isinstance(i, ResizableIconItem)]

        # If we truly have nothing, show one single warning
        if not text_items and not icon_items:
            QMessageBox.warning(
                self,
                "Warning",
                "No text or image/icon items found in the scene.\n\n"
                "Please add some text or images/icons first!"
            )
            return

        # If text is present, apply to all
        if text_items:
            self.apply_only_text_to_all(show_warnings=False)

        # If icons are present, apply to all
        if icon_items:
            self.apply_icon_to_all_previews(show_warnings=False)

        # At the end, pop up one success
        QMessageBox.information(
            self,
            "Done",
            "Applied text and/or icons/images to all textures.\n"
            f"Files saved to:\n{self.output_folder}"
        )
        logging.info("apply_to_all_textures: Completed text + icon on all textures.")


    def add_icon(self):
        logging.debug("add_icon: Opening file dialog for image/icon selection.")
        file_path, _ = QFileDialog.getOpenFileName(self, "Select Image/Icon", "", "Image Files (*.png *.jpg *.jpeg *.ico)")
        if not file_path:
            logging.info("add_icon: Image/Icon selection canceled.")
            return

        logging.debug(f"add_icon: Selected file path: {file_path}")
        pixmap = QPixmap(file_path)
        if pixmap.isNull():
            QMessageBox.warning(self, "Error", "Could not load the selected image/icon.")
            logging.error("add_icon: Selected image/icon is invalid or could not be loaded.")
            return

        logging.debug(f"add_icon: Loaded pixmap size: {pixmap.size()}")
        center_position = self.scene.sceneRect().center()
        self.add_resizable_icon(pixmap, center_position)
        logging.info(f"add_icon: Image/Icon added to scene from file: {file_path}")

    def clear_selected_icon(self):
        logging.debug("clear_selected_icon: Clearing selected image/icon items from the scene.")
        selected_items = self.scene.selectedItems()
        if not selected_items:
            logging.debug("clear_selected_icon: No items selected in scene.")
        removed = False
        for item in selected_items:
            logging.debug(f"clear_selected_icon: Examining selected item: {item}")
            if isinstance(item, ResizableIconItem):
                self.scene.removeItem(item)
                removed = True
                logging.info("clear_selected_icon: Cleared an image/icon item from scene.")
            elif isinstance(item, ResizableTextItem):
                self.scene.removeItem(item)
                removed = True
                logging.info("clear_selected_icon: Cleared a text item from scene.")
        if not removed:
            QMessageBox.information(self, "Info", "No image/icon or text item selected to clear.")
            logging.info("clear_selected_icon: No items selected for removal.")

    def apply_icon_to_current_preview(self, show_warnings=True):
        """
        Applies the currently selected icon (or text item) to self.blended_image,
        masking/clipping it to the base's transparent areas so there's no overspill.
        MODIFIED so that if no items are selected, it will apply ALL icons/text in the scene.
        """
        logging.debug("apply_icon_to_current_preview: Attempting to apply selected icon/text to current preview.")

        selected_items = self.scene.selectedItems()

        # NEW: If no items are selected, gather *all* ResizableIconItem/ResizableTextItem objects
        if not selected_items:
            logging.debug("apply_icon_to_current_preview: No selected items. Gathering all icons/text in the scene.")
            selected_items = [
                i for i in self.scene.items()
                if isinstance(i, ResizableIconItem) or isinstance(i, ResizableTextItem)
            ]
            if not selected_items:
                if show_warnings:
                    QMessageBox.warning(
                        self,
                        "Warning",
                        "No image/icon or text items found in the scene to apply."
                    )
                logging.warning("apply_icon_to_current_preview: No icon/text items found at all.")
                return

        # We will loop over *all* relevant items (selected or entire scene)
        # so we do NOT 'break' after the first found
        applied_any = False
        for icon_item in selected_items:
            if not (isinstance(icon_item, ResizableIconItem) or isinstance(icon_item, ResizableTextItem)):
                continue  # skip anything that's not an icon/text
            applied_any = True

            if self.blended_image is None:
                if show_warnings:
                    QMessageBox.warning(self, "Warning", "No base preview image available.")
                logging.warning("apply_icon_to_current_preview: No base preview image available.")
                return

            # Retrieve the transformed pixmap (scaled & rotated)
            logging.debug("apply_icon_to_current_preview: Retrieving transformed pixmap from item.")
            if isinstance(icon_item, ResizableIconItem):
                icon_pixmap = icon_item.get_transformed_pixmap()
            elif isinstance(icon_item, ResizableTextItem):
                icon_pixmap = icon_item.get_transformed_pixmap()
            else:
                icon_pixmap = QPixmap()

            if icon_pixmap.isNull():
                if show_warnings:
                    QMessageBox.warning(self, "Error", "Failed to retrieve the transformed icon/text pixmap.")
                logging.error("apply_icon_to_current_preview: Transformed icon/text pixmap is null.")
                continue  # skip this item

            logging.debug(f"apply_icon_to_current_preview: Transformed pixmap size: {icon_pixmap.size()}")

            # Convert QPixmap -> QImage (RGBA8888)
            icon_qimage = icon_pixmap.toImage().convertToFormat(QImage.Format_RGBA8888)
            logging.debug("apply_icon_to_current_preview: Converted QPixmap to QImage with RGBA8888 format.")

            # Convert memoryview to bytes
            buf = icon_qimage.bits()
            data = bytes(buf[:icon_qimage.sizeInBytes()])
            logging.debug(f"apply_icon_to_current_preview: Buffer length: {len(data)} bytes.")

            try:
                # Create a PIL RGBA image from these bytes
                icon_pil = Image.frombytes("RGBA", (icon_qimage.width(), icon_qimage.height()), data)
                logging.debug("apply_icon_to_current_preview: Successfully converted QImage to PIL RGBA image.")
            except Exception as e:
                logging.error(f"apply_icon_to_current_preview: Error converting QImage to PIL image: {e}")
                if show_warnings:
                    QMessageBox.warning(self, "Error", f"Error converting image: {e}")
                continue

            # Get the item’s top-left position in scene coordinates
            pos = icon_item.sceneBoundingRect().topLeft()
            x = int(pos.x())
            y = int(pos.y())
            logging.debug(f"apply_icon_to_current_preview: Icon/Text top-left in scene: ({x}, {y})")

            # Make a copy of the base (blended image)
            base = self.blended_image.copy()
            base_width, base_height = base.size

            # Create an RGBA overlay the same size
            overlay = Image.new("RGBA", (base_width, base_height), (0, 0, 0, 0))

            # Clamp x, y to ensure we don't paste out of bounds
            x = max(0, min(x, base_width - icon_pil.width))
            y = max(0, min(y, base_height - icon_pil.height))
            logging.debug(f"apply_icon_to_current_preview: Clamped paste position: ({x}, {y})")

            # Composite approach to prevent black box & clip to base alpha
            overlay.paste(icon_pil, (x, y), icon_pil)
            logging.debug("apply_icon_to_current_preview: Pasted icon onto overlay with alpha.")

            composited = Image.alpha_composite(base, overlay)

            # Multiply final alpha by the base alpha
            base_alpha = base.getchannel("A")
            final_alpha = composited.getchannel("A")
            clipped_alpha = ImageChops.multiply(base_alpha, final_alpha)
            composited.putalpha(clipped_alpha)
            logging.debug("apply_icon_to_current_preview: Multiplied final alpha by base alpha for clipping.")

            # Show the result in the QGraphicsView and update self.blended_image
            self.show_image_in_graphics_view(composited)
            self.blended_image = composited

            # Save the updated image each time (the last item is final)
            output_path = os.path.join(self.output_folder, "updated_preview.png")
            composited.save(output_path, format='PNG')
            logging.info(f"apply_icon_to_current_preview: Updated preview saved to {output_path}.")

        if not applied_any:
            # Means the loop never applied anything
            logging.warning("apply_icon_to_current_preview: No valid icon/text items to apply.")
            if show_warnings:
                QMessageBox.warning(
                    self,
                    "Warning",
                    "No valid icon/text items were applied."
                )

    def apply_icon_to_all_previews(self, show_warnings=True):
        """
        Applies the selected icon/image to ALL output images,
        clipping to base transparency & avoiding black boxes on rotation.
        MODIFIED so that if no item is selected, it applies *all* icons/text in the scene.
        """
        logging.debug("apply_icon_to_all_previews: Attempting to apply selected icon to all preview images.")

        selected_items = self.scene.selectedItems()

        # NEW: If no items are selected, gather all icons/text
        if not selected_items:
            logging.debug("apply_icon_to_all_previews: No selection, gathering all icons/text in the scene.")
            selected_items = [
                i for i in self.scene.items()
                if isinstance(i, ResizableIconItem) or isinstance(i, ResizableTextItem)
            ]
            if not selected_items:
                if show_warnings:
                    QMessageBox.warning(self, "Warning", "No image/icon or text items found in the scene.")
                logging.warning("apply_icon_to_all_previews: No items in the scene.")
                return

        # We'll apply each selected (or all) item in turn
        # NOTE: Original code only looked for the first ResizableIconItem, then 'break'.
        # We are not removing that logic, but we'll handle them in a loop.
        # We'll gather them in a list to apply multiple if found.
        icon_items = []
        for item in selected_items:
            logging.debug(f"apply_icon_to_all_previews: Checking item: {item}")
            if isinstance(item, ResizableIconItem):
                icon_items.append(item)
                logging.debug("apply_icon_to_all_previews: Found a ResizableIconItem.")
            elif isinstance(item, ResizableTextItem):
                icon_items.append(item)
                logging.debug("apply_icon_to_all_previews: Found a ResizableTextItem.")

        if not icon_items:
            if show_warnings:
                QMessageBox.warning(self, "Warning", "No image/icon item selected (or found) to apply.")
            logging.warning("apply_icon_to_all_previews: No icon/text items to apply.")
            return

        if not self.output_folder:
            if show_warnings:
                QMessageBox.warning(self, "Warning", "No output folder selected.")
            logging.warning("apply_icon_to_all_previews: No output folder selected.")
            return

        # Gather images in the output folder
        supported_formats = ('.png', '.jpg', '.jpeg', '.bmp', '.gif')
        image_files = [f for f in os.listdir(self.output_folder) if f.lower().endswith(supported_formats)]
        logging.debug(f"apply_icon_to_all_previews: Found {len(image_files)} image(s) in output folder.")

        if not image_files:
            if show_warnings:
                QMessageBox.warning(self, "Warning", "No images found in the output folder.")
            logging.warning("apply_icon_to_all_previews: No image files in output folder.")
            return

        # For each icon or text item, we'll apply it to all images
        for icon_item in icon_items:
            logging.debug("apply_icon_to_all_previews: Retrieving transformed pixmap from item.")
            icon_pixmap = icon_item.get_transformed_pixmap()
            if icon_pixmap.isNull():
                QMessageBox.warning(self, "Error", "Failed to retrieve a transformed icon/text pixmap.")
                logging.error("apply_icon_to_all_previews: Transformed pixmap is null.")
                continue

            icon_qimage = icon_pixmap.toImage().convertToFormat(QImage.Format_RGBA8888)
            buf = icon_qimage.bits()
            data = bytes(buf[:icon_qimage.sizeInBytes()])
            logging.debug(f"apply_icon_to_all_previews: Buffer length: {len(data)} bytes.")

            try:
                icon_pil = Image.frombytes("RGBA", (icon_qimage.width(), icon_qimage.height()), data)
                logging.debug("apply_icon_to_all_previews: Successfully converted QImage to PIL RGBA image.")
            except Exception as e:
                logging.error(f"apply_icon_to_all_previews: Error converting QImage to PIL image: {e}")
                if show_warnings:
                    QMessageBox.warning(self, "Error", f"Error converting icon image: {e}")
                continue

            # Get top-left from scene
            pos = icon_item.sceneBoundingRect().topLeft()
            x = int(pos.x())
            y = int(pos.y())
            logging.debug(f"apply_icon_to_all_previews: Item top-left: ({x}, {y})")

            # Apply to each image in output_folder
            for img_file in image_files:
                img_path = os.path.join(self.output_folder, img_file)
                logging.debug(f"apply_icon_to_all_previews: Processing image file: {img_file}")
                try:
                    base_img = Image.open(img_path).convert('RGBA')
                    logging.debug(f"Opened {img_file} and converted to RGBA.")

                    # Ensure base matches template size
                    if base_img.size != self.template_image.size:
                        if hasattr(Image, 'Resampling'):
                            base_img = base_img.resize(self.template_image.size, resample=Image.Resampling.LANCZOS)
                        else:
                            base_img = base_img.resize(self.template_image.size, Image.LANCZOS)
                        logging.info(f"Resized {img_file} to match template size {self.template_image.size}.")

                    base_width, base_height = base_img.size

                    # Clamp
                    clamped_x = max(0, min(x, base_width - icon_pil.width))
                    clamped_y = max(0, min(y, base_height - icon_pil.height))

                    overlay = Image.new("RGBA", base_img.size, (0, 0, 0, 0))
                    overlay.paste(icon_pil, (clamped_x, clamped_y), icon_pil)
                    composited = Image.alpha_composite(base_img, overlay)

                    # Multiply alpha
                    base_alpha = base_img.getchannel("A")
                    final_alpha = composited.getchannel("A")
                    clipped_alpha = ImageChops.multiply(base_alpha, final_alpha)
                    composited.putalpha(clipped_alpha)

                    composited.save(img_path, format='PNG')
                    logging.info(f"apply_icon_to_all_previews: Applied item to {img_file}.")

                except Exception as e:
                    logging.error(f"apply_icon_to_all_previews: Error applying item to {img_file}: {e}")
                    if show_warnings:
                        QMessageBox.warning(self, "Error", f"Error applying icon/text to {img_file}:\n{e}")

        # Reload output images, done
        self.load_output_images()
        logging.info("apply_icon_to_all_previews: Completed applying icon/text to all previews.")

        if show_warnings:
            QMessageBox.information(
                self,
                "Done",
                "Icons/text have been applied to all output images."
            )

    def add_resizable_icon(self, pixmap, center_position):
        item = ResizableIconItem(pixmap)

        # Set transform origin to the center of the pixmap
        item.setTransformOriginPoint(item.boundingRect().center())
        logging.debug("add_resizable_icon: Transform origin set to center.")

        # Calculate the top-left position based on the center position
        top_left_x = center_position.x() - pixmap.width() / 2
        top_left_y = center_position.y() - pixmap.height() / 2
        item.setPos(top_left_x, top_left_y)

        self.scene.addItem(item)
        logging.info(f"add_resizable_icon: Added ResizableIconItem at center position: {center_position}")

    def select_text_color(self):
        color = QColorDialog.getColor(initial=self.current_text_color, parent=self, title="Select Text Color")
        if color.isValid():
            self.current_text_color = color
            logging.info(f"Text color changed to: {self.current_text_color.name()}")
        else:
            logging.info("Text color selection canceled.")

    def update_preview(self):
        if not self.blended_image:
            return

        brightness = self.brightness_slider.value()
        contrast = self.contrast_slider.value()

        self.brightness_value_label.setText(f"{brightness}%")
        self.contrast_value_label.setText(f"{contrast}%")

        enhanced_image = self.blended_image.copy()
        enhancer_brightness = ImageEnhance.Brightness(enhanced_image)
        enhanced_image = enhancer_brightness.enhance(brightness / 100.0)

        enhancer_contrast = ImageEnhance.Contrast(enhanced_image)
        enhanced_image = enhancer_contrast.enhance(contrast / 100.0)

        self.show_image_in_graphics_view(enhanced_image)
        logging.info("Preview updated with brightness and contrast adjustments.")

    def update_checkbox_states(self):
        if self.chk_convert_to_paa.isChecked():
            self.chk_generate_scripts.setEnabled(True)
        else:
            self.chk_generate_scripts.setChecked(False)
            self.chk_generate_scripts.setEnabled(False)

        if self.chk_convert_to_paa.isChecked() and self.chk_generate_scripts.isChecked():
            self.chk_pack_into_pbo.setEnabled(True)
        else:
            self.chk_pack_into_pbo.setChecked(False)
            self.chk_pack_into_pbo.setEnabled(False)

    def generate_preview(self):
        """
        Generates a preview by blending the template image with the selected texture.
        Ensures that the blended image aligns correctly with the QGraphicsScene
        and matches the template's size.
        """
        # Check if the template image is loaded
        if not self.template_image:
            logging.warning("Cannot generate preview: Template not loaded.")
            QMessageBox.warning(self, "Warning", "Please select a template image first.")
            return

        # Check if the texture folder and files are loaded
        if not self.texture_folder or not self.texture_files:
            logging.warning("Cannot generate preview: No textures loaded.")
            QMessageBox.warning(self, "Warning", "Please select a texture folder with images.")
            return

        # Check if a texture is selected
        if not self.current_texture_file:
            logging.warning("Cannot generate preview: No texture selected.")
            QMessageBox.warning(self, "Warning", "Please select a texture to preview.")
            return

        # Construct the full path to the selected texture
        selected_texture_path = os.path.join(self.texture_folder, self.current_texture_file)
        logging.debug(f"Selected texture path for preview: {selected_texture_path}")

        # Attempt to open and convert the texture image to RGBA
        try:
            texture_image = Image.open(selected_texture_path).convert('RGBA')
            logging.info(f"Loaded texture for preview: {self.current_texture_file}")

            # Resize the texture to match the template size if necessary
            if texture_image.size != self.template_image.size:
                if hasattr(Image, 'Resampling'):
                    texture_image = texture_image.resize(self.template_image.size, resample=Image.Resampling.LANCZOS)
                else:
                    # Fallback for older Pillow
                    texture_image = texture_image.resize(self.template_image.size, Image.LANCZOS)
                logging.info(f"Resized texture image to match template size: {self.template_image.size}")
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Could not load texture for preview.\n{e}")
            logging.error(f"Could not load texture for preview: {e}")
            return

        # Blend the template and texture images using BlendingHelper
        try:
            blending_mode = self.blending_mode.currentText()
            blended_image = BlendingHelper.blend_images(self.template_image, texture_image, blending_mode)

            # Ensure the blended image size matches the template
            if blended_image.size != self.template_image.size:
                if hasattr(Image, 'Resampling'):
                    blended_image = blended_image.resize(self.template_image.size, resample=Image.Resampling.LANCZOS)
                else:
                    blended_image = blended_image.resize(self.template_image.size, Image.LANCZOS)
                logging.warning("Blended image size did not match template. Resized to match.")

            self.blended_image = blended_image.copy()
            logging.info(f"Blended image size: {self.blended_image.size}")
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to blend images.\n{e}")
            logging.error(f"Failed to blend images: {e}")
            return

        # Update the QGraphicsScene with the blended image
        try:
            self.scene.clear()  # Clear existing items in the scene
            logging.info("Cleared graphics scene for new blended image.")

            # Convert the blended PIL Image to QPixmap
            pixmap = pil2pixmap(self.blended_image)

            # Create a QGraphicsPixmapItem and add it to the scene
            pixmap_item = QGraphicsPixmapItem(pixmap)
            self.scene.addItem(pixmap_item)

            # Set the scene's dimensions to match the blended image
            self.scene.setSceneRect(0, 0, pixmap.width(), pixmap.height())
            logging.info(f"Scene updated to match blended image size: {pixmap.width()}x{pixmap.height()}")

            # Optionally, fit the view to the scene
            self.output_preview_view.fitInView(self.scene.sceneRect(), Qt.KeepAspectRatio)
            logging.debug("Output preview view fitted to scene.")
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to update preview scene.\n{e}")
            logging.error(f"Failed to update preview scene: {e}")
            return

        # Update brightness and contrast settings
        self.update_preview()


    def open_instructions(self):
        dialog = InstructionsDialog(self)   # pass `self` as parent if desired
        dialog.exec()

    def open_options_dialog(self):
        dialog = OptionsDialog(
            self,
            generate_checked=self.chk_generate_scripts.isChecked(),
            pack_checked=self.chk_pack_into_pbo.isChecked(),
            generate_options=self.opt_generate_scripts_options,
            pack_options=self.opt_pack_into_pbo_options,
            dependent_mod=self.opt_dependent_mod,
            mod_name=self.opt_mod_name,
            parent_classname=self.opt_parent_classname,
            hidden_selections=self.opt_hidden_selections,
            pbo_signing_option=self.opt_pbo_signing_choice,
            existing_biprivatekey_path=self.opt_existing_biprivatekey,
            existing_bikey_path=self.opt_existing_bikey,
            new_key_name=self.opt_new_key_name,
            root_dir=self.root_dir
        )
        if dialog.exec() == QDialog.Accepted:
            self.opt_generate_scripts_options = dialog.generate_options
            self.opt_pack_into_pbo_options = dialog.pack_options

            self.opt_dependent_mod = dialog.dependent_mod
            self.opt_mod_name = dialog.mod_name
            self.opt_parent_classname = dialog.parent_classname
            self.opt_hidden_selections = dialog.hidden_selections

            self.opt_pbo_signing_choice = dialog.pbo_signing_option
            self.opt_existing_biprivatekey = dialog.existing_biprivatekey_path
            self.opt_existing_bikey = dialog.existing_bikey_path
            self.opt_new_key_name = dialog.new_key_name

            logging.info("Options updated from OptionsDialog.")
            logging.info(f"Dependent Mod: {self.opt_dependent_mod}")
            logging.info(f"Mod Name: {self.opt_mod_name}")
            logging.info(f"Parent ClassName: {self.opt_parent_classname}")
            logging.info(f"HiddenSelections: {self.opt_hidden_selections}")
            logging.info(f"PBO Signing Choice: {self.opt_pbo_signing_choice}")
            logging.info(f"Existing biprivatekey: {self.opt_existing_biprivatekey}")
            logging.info(f"Existing bikey: {self.opt_existing_bikey}")
            logging.info(f"New key name: {self.opt_new_key_name}")
        else:
            logging.info("Options dialog canceled.")

    def open_discord_link(self):
        discord_url = "https://discord.gg/gXnkS5WHak"
        webbrowser.open(discord_url)

    def logout_action(self):
        reply = QMessageBox.question(
            self,
            "Logout",
            "Are you sure you want to logout?",
            QMessageBox.Yes | QMessageBox.No
        )
        if reply == QMessageBox.Yes:
            QApplication.quit()

    @Slot(str, str)
    def prompt_update(self, download_url, archive_name):
        reply = QMessageBox.question(
            self,
            "Update Available",
            "DayZReSkin has a new version available! Would you like to update now?",
            QMessageBox.Yes | QMessageBox.No
        )
        if reply == QMessageBox.Yes:
            self.perform_update(download_url, archive_name)

    def perform_update(self, download_url, archive_name):
        logging.info(f"Starting update: {download_url}, Archive: {archive_name}")
        self.update_thread = UpdateThread(download_url, archive_name)
        self.update_thread.progress.connect(self.update_loading_dialog)
        self.update_thread.finished.connect(self.on_update_finished)
        self.update_thread.error.connect(self.on_update_error)
        self.update_thread.start()

        theme = self.themes.get(self.current_theme, "dark")
        self.loading_dlg = LoadingDialog(self, theme)
        self.loading_dlg.show()
        logging.info("Loading dialog shown.")

    def check_version(self):
        try:
            token = "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"  # Note: Tokens should be securely managed
            headers = {"Authorization": f"Bearer {token}"}
            url = "https://raw.githubusercontent.com/Drews-Tools/DayZReSkinDB/main/version_contol.json"
            response = requests.get(url, headers=headers)
            response.raise_for_status()
            data = json.loads(response.text)
            latest_version = data["version"]
            if latest_version == self.CURRENT_VERSION:
                self.update_version_label(self.CURRENT_VERSION, "Up-to-date")
            else:
                self.update_version_label(self.CURRENT_VERSION, "Out-dated")
                download_url = "https://github.com/Drews-Tools/Updater_MMM/releases/download/DayZ/Updater.rar"
                archive_name = "Updater.rar"
                self.prompt_update(download_url, archive_name)
        except requests.exceptions.RequestException as e:
            logging.error(f"Version check error: {e}")
            self.update_version_label(self.CURRENT_VERSION, "Offline")
        except json.JSONDecodeError as e:
            logging.error(f"JSON parse error: {e}")
            self.update_version_label(self.CURRENT_VERSION, "Offline")
        except Exception as e:
            logging.error(f"Unknown version check error: {e}")
            self.update_version_label(self.CURRENT_VERSION, "Offline")

    def update_version_label(self, current_version, version_status):
        self.version_label.setText(f"Version: {current_version} {version_status}")

    @Slot(str, int)
    def update_loading_dialog(self, message, progress):
        if hasattr(self, 'loading_dlg') and self.loading_dlg.isVisible():
            self.loading_dlg.progress_label.setText(message)
            self.loading_dlg.progress_bar.setValue(progress)
            self.loading_dlg.percent_label.setText(f"{progress}%")

    @Slot()
    def on_update_finished(self):
        if hasattr(self, 'loading_dlg') and self.loading_dlg.isVisible():
            self.loading_dlg.close()
        QMessageBox.information(
            self,
            "Update",
            "Updater launched. The application will now close."
        )
        logging.info("Updater launched and application will quit.")
        QApplication.quit()

    @Slot(str)
    def on_update_error(self, error_message):
        if hasattr(self, 'loading_dlg') and self.loading_dlg.isVisible():
            self.loading_dlg.close()
        QMessageBox.critical(self, "Update Error", f"An error occurred:\n{error_message}")

    def closeEvent(self, event):
        if hasattr(self, 'update_thread') and self.update_thread.isRunning():
            self.update_thread.terminate()
            self.update_thread.wait(timeout=5)
            logging.info("Update thread terminated on close.")
        event.accept()

    def apply_dark_theme(self):
        dark_palette = QPalette()
        dark_palette.setColor(QPalette.Window, QColor(53, 53, 53))
        dark_palette.setColor(QPalette.WindowText, Qt.white)
        dark_palette.setColor(QPalette.Base, QColor(25, 25, 25))
        dark_palette.setColor(QPalette.AlternateBase, QColor(53, 53, 53))
        dark_palette.setColor(QPalette.ToolTipBase, Qt.white)
        dark_palette.setColor(QPalette.ToolTipText, Qt.white)
        dark_palette.setColor(QPalette.Text, Qt.white)
        dark_palette.setColor(QPalette.Button, QColor(53, 53, 53))
        dark_palette.setColor(QPalette.ButtonText, Qt.white)
        dark_palette.setColor(QPalette.BrightText, Qt.red)
        dark_palette.setColor(QPalette.Highlight, QColor(142, 45, 197).lighter())
        dark_palette.setColor(QPalette.HighlightedText, Qt.black)
        self.setPalette(dark_palette)

        self.setStyleSheet("""
            QWidget {
                background-color: #2c2c2c;
                color: white;
                font-family: Arial, sans-serif;
                font-size: 14px;
            }
            QPushButton {
                background-color: #444444;
                border: 1px solid #555555;
                padding: 5px;
                border-radius: 5px;
            }
            QPushButton:hover {
                background-color: #555555;
            }
            QComboBox {
                background-color: #444444;
                border: 1px solid #555555;
                padding: 5px;
                border-radius: 5px;
                color: white;
            }
            QLabel {
                color: white;
            }
            QListWidget {
                selection-background-color: #555555;
            }
            QGraphicsView {
                background-color: #1e1e1e;
            }
            QLineEdit {
                background-color: #3c3c3c;
                color: white;
                border: 1px solid gray;
                padding: 5px;
                border-radius: 5px;
            }
        """)

    def style_button(self, button, highlight=False):
        if highlight:
            button.setStyleSheet("""
                QPushButton {
                    background-color: #007acc;
                    border: 1px solid #005f99;
                    padding: 10px;
                    border-radius: 5px;
                    color: white;
                    font-weight: bold;
                }
                QPushButton:hover {
                    background-color: #005f99;
                }
            """)
        else:
            button.setStyleSheet("""
                QPushButton {
                    background-color: #444444;
                    border: 1px solid #555555;
                    padding: 5px;
                    border-radius: 5px;
                }
                QPushButton:hover {
                    background-color: #555555;
                }
            """)

    def load_template(self):
        file_name, _ = QFileDialog.getOpenFileName(
            self, "Select Template", "", "Image Files (*.png *.jpg *.jpeg)"
        )
        if file_name:
            self.template_path = file_name
            try:
                self.template_image = Image.open(self.template_path).convert('RGBA')
                if self.template_image is None:
                    raise ValueError("Template image is None.")
                logging.info(f"Template loaded: {self.template_path}")
            except Exception as e:
                QMessageBox.warning(self, "Error", f"Could not open template.\n{e}")
                logging.error(f"Could not open template: {e}")
                return

            self.show_image_in_label(self.template_image, self.template_label, (400, 400))
            self.update_scene_with_template()

            if self.texture_files:
                if not self.current_texture_file:
                    self.current_texture_file = self.texture_files[0]
                self.generate_preview()
        else:
            logging.info("Template selection canceled.")

    def update_scene_with_template(self):
        if not self.template_image:
            return
        self.scene.clear()
        logging.info("Cleared graphics scene for new template.")
        pixmap = pil2pixmap(self.template_image)
        pixmap_item = QGraphicsPixmapItem(pixmap)
        self.scene.addItem(pixmap_item)
        self.scene.setSceneRect(0, 0, pixmap.width(), pixmap.height())
        logging.info(f"Scene updated to {pixmap.width()}x{pixmap.height()}")

    def set_tooltip_style(self, is_dark_theme=True):
        if is_dark_theme:
            tooltip_style = """
                QToolTip {
                    color: white;
                    background-color: #2c2c2c;
                    border: 1px solid #555555;
                    padding: 5px;
                    border-radius: 3px;
                    font-size: 12px;
                }
            """
        else:
            tooltip_style = """
                QToolTip {
                    color: black;
                    background-color: #f0f0f0;
                    border: 1px solid #cccccc;
                    padding: 5px;
                    border-radius: 3px;
                    font-size: 12px;
                }
            """
        QApplication.instance().setStyleSheet(tooltip_style)

    def load_textures(self):
        folder = QFileDialog.getExistingDirectory(self, "Select Texture Folder", "")
        if folder:
            self.texture_folder = folder
            self.scan_duplicates_button.setVisible(True)
            logging.info(f"Texture folder selected: {self.texture_folder}")
        else:
            QMessageBox.warning(self, "Warning", "No folder selected.")
            logging.warning("Texture folder selection canceled.")
            return

        # Clear existing thumbnails
        for i in reversed(range(self.thumbnail_layout.count())):
            widget_item = self.thumbnail_layout.itemAt(i)
            if widget_item and widget_item.widget():
                widget_item.widget().deleteLater()

        self.texture_files = [
            f for f in os.listdir(self.texture_folder)
            if f.lower().endswith(('.png', '.jpg', '.jpeg'))
        ]
        if not self.texture_files:
            QMessageBox.warning(self, "Warning", "No textures found in the selected folder.")
            logging.warning("No textures found in folder.")
            return

        self.texture_previews.clear()
        for tex_file in self.texture_files:
            full_path = os.path.join(self.texture_folder, tex_file)
            try:
                im = Image.open(full_path).convert('RGBA')
                if hasattr(Image, 'Resampling'):
                    im.thumbnail((100, 100), Image.Resampling.LANCZOS)
                else:
                    im.thumbnail((100, 100), Image.LANCZOS)
                pixmap = pil2pixmap(im)
                logging.info(f"Texture loaded + thumbnail: {tex_file}")
            except Exception as e:
                pixmap = QPixmap(100, 100)
                pixmap.fill(Qt.gray)
                logging.error(f"Error loading {tex_file}: {e}")

            self.texture_previews[tex_file] = pixmap
            btn = QPushButton()
            btn.setIcon(pixmap)
            btn.setIconSize(QSize(100, 100))
            btn.setFixedSize(110, 110)
            btn.setToolTip(tex_file)
            btn.setStyleSheet("""
                QPushButton {
                    border: 1px solid gray;
                    border-radius: 5px;
                }
                QPushButton:hover {
                    border: 2px solid #007acc;
                }
            """)
            btn.clicked.connect(lambda checked, f=tex_file: self.select_texture_preview(f))
            self.thumbnail_layout.addWidget(btn)

        if self.texture_files:
            self.current_texture_file = self.texture_files[0]
            self.generate_preview()

    def select_texture_preview(self, tex_file):
        if tex_file not in self.texture_files:
            logging.warning(f"Texture '{tex_file}' is not in the texture files list.")
            return
        self.current_texture_file = tex_file
        logging.info(f"Texture selected for preview: {tex_file}")
        self.generate_preview()

    def scan_for_duplicates(self):
        if not self.texture_folder or not self.texture_files:
            QMessageBox.warning(self, "Warning", "Please select a texture folder first.")
            logging.warning("Duplicate scan failed: No folder.")
            return

        hash_dict = {}
        duplicates = []
        for tex_file in self.texture_files:
            full_path = os.path.join(self.texture_folder, tex_file)
            try:
                with Image.open(full_path) as img:
                    img_converted = img.convert('RGBA')
                    img_bytes = img_converted.tobytes()
                    img_hash = hashlib.sha256(img_bytes).hexdigest()
            except Exception as e:
                logging.error(f"Error scanning {tex_file}: {e}")
                continue
            if img_hash in hash_dict:
                duplicates.append(tex_file)
            else:
                hash_dict[img_hash] = tex_file

        if duplicates:
            duplicate_dialog = DuplicateDialog(duplicates, self)
            result = duplicate_dialog.exec()

            if result == QDialog.Accepted:
                selected_duplicates = []
                for index in range(duplicate_dialog.duplicate_list.count()):
                    item = duplicate_dialog.duplicate_list.item(index)
                    if item.checkState() == Qt.Checked:
                        selected_duplicates.append(item.text())

                if not selected_duplicates:
                    QMessageBox.information(self, "No Selection", "No duplicates selected for removal.")
                    logging.info("No duplicates selected for removal.")
                    return

                for dup in selected_duplicates:
                    if dup in self.texture_files:
                        self.texture_files.remove(dup)
                    if dup in self.texture_previews:
                        del self.texture_previews[dup]
                    for i in range(self.thumbnail_layout.count()):
                        widget_item = self.thumbnail_layout.itemAt(i)
                        if widget_item and widget_item.widget():
                            btn = widget_item.widget()
                            if btn.toolTip() == dup:
                                self.thumbnail_layout.removeWidget(btn)
                                btn.deleteLater()
                                logging.info(f"Removed duplicate: {dup}")
                                break
                QMessageBox.information(self, "Duplicates Removed", f"{len(selected_duplicates)} duplicate(s) removed.")
                logging.info(f"Removed {len(selected_duplicates)} duplicates.")
                if self.texture_files:
                    if self.current_texture_file not in self.texture_files:
                        self.current_texture_file = self.texture_files[0]
                    self.generate_preview()
            else:
                QMessageBox.information(self, "Operation Cancelled", "No files were removed.")
                logging.info("Duplicate removal operation canceled by the user.")
        else:
            QMessageBox.information(self, "No Duplicates", "No duplicates found.")
            logging.info("No duplicates detected.")

    def select_output_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Select Output Folder", "")
        if folder:
            self.output_folder = folder
            logging.info(f"Output folder: {self.output_folder}")
        else:
            QMessageBox.warning(self, "Warning", "No output folder selected.")
            logging.warning("No output folder selected.")

    def select_font(self):
        if not self.root_dir:
            QMessageBox.warning(self, "Warning", "Root directory not set.")
            logging.warning("Font selection failed: Root directory not set.")
            return

        # Build the exact 'resources/fonts' path from self.root_dir
        fonts_dir = os.path.join(self.root_dir, "resources", "fonts")
        if not os.path.isdir(fonts_dir):
            QMessageBox.warning(
                self,
                "Warning",
                f"Fonts directory not found: {fonts_dir}"
            )
            logging.warning(f"Font selection failed: '{fonts_dir}' does not exist.")
            return

        dialog = FontSelectionDialog(fonts_dir, self)
        if dialog.exec() == QDialog.Accepted:
            self.selected_font_path = dialog.selected_font_path
            if self.selected_font_path:
                font_db = QFontDatabase()
                loaded_font_id = font_db.addApplicationFont(self.selected_font_path)
                if loaded_font_id != -1:
                    loaded_families = font_db.applicationFontFamilies(loaded_font_id)
                    if loaded_families:
                        self.selected_font_family = loaded_families[0]
                        self.selected_font_label.setText(f"Font: {self.selected_font_family}")
                        logging.info(f"Font selected and applied: {self.selected_font_family}")
                    else:
                        QMessageBox.warning(self, "Error", "Failed to retrieve font family.")
                        logging.error("Failed to retrieve font family after selection.")
                else:
                    QMessageBox.warning(self, "Error", "Failed to load the selected font.")
                    logging.error("Failed to load the selected font.")
        else:
            logging.info("Font selection dialog canceled.")

    def update_font_size(self, value):
        self.selected_font_size = value
        logging.info(f"Font size default => {self.selected_font_size}")

    def apply_texture(self):
        # DEBUG ADDED
        call_id = random.randint(10000, 99999)
        logging.info(f"apply_texture() CALLED. CALL_ID={call_id}")

        # ---------------------------------------------------------
        # UPDATED CODE: PROMPT ONLY IF we detect subdirs that match
        #  self.opt_mod_name OR '@self.opt_mod_name'. If none, skip prompt.
        # ---------------------------------------------------------
        if os.path.exists(self.output_folder):
            mod_dir_name = self.opt_mod_name.strip() or ""
            possible_dirs = [mod_dir_name, f"@{mod_dir_name}"]

            # Gather actual subdirectories in output_folder
            subdirs = [
                item
                for item in os.listdir(self.output_folder)
                if os.path.isdir(os.path.join(self.output_folder, item))
            ]

            # Check overlap with possible_dirs
            dirs_to_remove = [sd for sd in subdirs if sd in possible_dirs]

            if dirs_to_remove:
                # If we have at least one matching subdirectory, prompt
                reply = QMessageBox.question(
                    self,
                    "Overwrite Folder?",
                    f"The selected output folder ({self.output_folder}) contains these directories:\n"
                    f"{dirs_to_remove}\n\n"
                    "Do you want to overwrite (remove) them?\n\n"
                    "NOTE: This will ONLY remove those matching directories.\n"
                    "It will NOT remove any .png files.",
                    QMessageBox.Yes | QMessageBox.No
                )
                if reply == QMessageBox.No:
                    return
                else:
                    # Remove only those subdirectories
                    for d in dirs_to_remove:
                        dir_path = os.path.join(self.output_folder, d)
                        try:
                            shutil.rmtree(dir_path)
                            logging.info(f"Removed directory: {dir_path}")
                        except Exception as e:
                            logging.error(f"Error removing directory {dir_path}: {e}")
        # ---------------------------------------------------------
        # END OF UPDATED CODE
        # ---------------------------------------------------------

        if self.is_applying_texture:
            logging.warning(f"[CALL_ID={call_id}] Attempted to start texture application while another is in progress.")
            QMessageBox.warning(self, "Warning", "Texture application is already in progress.")
            return

        if not self.template_image:
            logging.warning(f"[CALL_ID={call_id}] No template selected.")
            QMessageBox.warning(self, "Warning", "Select a template first.")
            return

        if not self.texture_folder or not self.texture_files:
            logging.warning(f"[CALL_ID={call_id}] No textures found to apply.")
            QMessageBox.warning(self, "Warning", "No textures to apply.")
            return

        if not self.output_folder:
            logging.warning(f"[CALL_ID={call_id}] No output folder selected.")
            QMessageBox.warning(self, "Warning", "No output folder selected.")
            return

        base_name = self.rename_input.text().strip()
        if not base_name:
            logging.warning(f"[CALL_ID={call_id}] No base name entered.")
            QMessageBox.warning(self, "Warning", "Enter a base name.")
            return

        # Disable the apply button to prevent multiple clicks
        self.apply_button.setEnabled(False)
        self.is_applying_texture = True

        brightness = self.brightness_slider.value()
        contrast = self.contrast_slider.value()
        selected_blending_mode = self.blending_mode_map.get(self.blending_mode.currentText(), "normal")
        logging.info(f"[CALL_ID={call_id}] Starting texture application with mode={selected_blending_mode}, brightness={brightness}, contrast={contrast}")

        # Create a new thread instance
        self.apply_texture_thread = ApplyTextureThread(
            template_image=self.template_image,
            texture_files=self.texture_files,
            texture_folder=self.texture_folder,
            output_folder=self.output_folder,
            base_name=base_name,
            blending_mode=selected_blending_mode,
            brightness=brightness,
            contrast=contrast,
            dayz_tools_dir=self.dayz_tools_dir
        )

        try:
            self.apply_texture_thread.finished.disconnect(self.on_apply_texture_finished)
        except (TypeError, RuntimeError):
            pass
        try:
            self.apply_texture_thread.error.disconnect(self.on_apply_texture_error)
        except (TypeError, RuntimeError):
            pass

        # DEBUG ADDED: Log the thread object
        logging.debug(f"[CALL_ID={call_id}] apply_texture_thread object: {self.apply_texture_thread}")

        # Connect signals to slots
        self.apply_texture_thread.progress.connect(self.show_progress)
        # DEBUG ADDED: Use a lambda to pass the call_id to the finished slot
        self.apply_texture_thread.apply_finished.connect(lambda: self.on_apply_texture_finished(call_id))
        self.apply_texture_thread.error.connect(self.on_apply_texture_error)
        
        self.apply_texture_thread.start()
        logging.info(f"[CALL_ID={call_id}] apply_texture_thread started. (isRunning={self.apply_texture_thread.isRunning()})")

        # Show loading dialog
        theme = self.themes.get(self.current_theme, "dark")
        self.loading_dlg = LoadingDialog(self, theme)
        self.loading_dlg.show()
        logging.info(f"[CALL_ID={call_id}] Loading dialog shown.")

    @Slot(str, int)
    def show_progress(self, message, progress):
        if hasattr(self, 'loading_dlg') and self.loading_dlg.isVisible():
            self.loading_dlg.progress_label.setText(message)
            self.loading_dlg.progress_bar.setValue(progress)
            self.loading_dlg.percent_label.setText(f"{progress}%")

    @Slot()
    def on_apply_texture_finished(self, call_id=None):
        # DEBUG ADDED
        logging.info(f"on_apply_texture_finished() triggered. CALL_ID={call_id}")
        
        if hasattr(self, 'loading_dlg') and self.loading_dlg.isVisible():
            self.loading_dlg.close()

        # DEBUG ADDED
        logging.info(f"[CALL_ID={call_id}] About to show the final 'Done' QMessageBox for apply_texture.")

        QMessageBox.information(
            self,
            "Done",
            f"Blended images saved to:\n{self.output_folder}"
        )

        logging.info(f"[CALL_ID={call_id}] Texture application completed successfully.")
        self.apply_button.setEnabled(True)
        self.apply_adjustments_button.setEnabled(True)
        self.text_group.show()
        self.font_group.show()
        self.icon_group.show()
        self.convert_to_paa_button.show()
        self.apply_to_current_texture_button.setVisible(True)
        self.apply_to_all_textures_button.setVisible(True)
        logging.info(f"[CALL_ID={call_id}] Apply Texture buttons now visible.")

        self.load_output_images()
        self.is_applying_texture = False

    @Slot(str)
    def on_apply_texture_error(self, error_message):
        # (We could also pass call_id, but it's optional here.)
        logging.error(f"on_apply_texture_error() invoked. error_message={error_message}")
        if hasattr(self, 'loading_dlg') and self.loading_dlg.isVisible():
            self.loading_dlg.close()
        QMessageBox.critical(self, "Error", f"An error occurred during texture application:\n{error_message}")
        self.apply_button.setEnabled(True)
        self.is_applying_texture = False

    def show_large_preview(self, tex_file):
        pixmap = self.texture_previews.get(tex_file)
        if pixmap is None:
            logging.warning(f"No preview available for texture: {tex_file}")
            return
        dialog = PreviewDialog(pixmap, self)
        dialog.exec()
        logging.info(f"Displayed large preview for texture: {tex_file}")

    def display_selected_output(self, item):
        out_name = item.text()
        out_path = os.path.join(self.output_folder, out_name)
        logging.info(f"Displaying selected output: {out_name}")

        try:
            image = Image.open(out_path).convert('RGBA')
            self.show_image_in_graphics_view(image)
            logging.info(f"Output image loaded: {out_path}")
        except Exception as e:
            QMessageBox.warning(self, "Error", f"Could not open output image.\n{e}")
            logging.error(f"Error loading output image: {e}")

    def show_image_in_graphics_view(self, pil_image):
        self.scene.clear()
        logging.info("show_image_in_graphics_view: Cleared graphics scene.")

        pixmap = pil2pixmap(pil_image)
        pixmap_item = QGraphicsPixmapItem(pixmap)
        self.scene.addItem(pixmap_item)
        self.scene.setSceneRect(0, 0, pixmap.width(), pixmap.height())
        logging.info(f"show_image_in_graphics_view: Added pixmap to graphics scene with size {pixmap.width()}x{pixmap.height()}.")

        # Optionally, fit the view to the scene
        self.output_preview_view.fitInView(self.scene.sceneRect(), Qt.KeepAspectRatio)
        logging.debug("show_image_in_graphics_view: Output preview view fitted to scene.")

    def add_text_to_preview(self):
        """
        Adds a text item to the scene at the current font size (self.selected_font_size),
        then logs relevant bounding information for debugging.
        """
        text = self.text_input.text().strip()
        if not text:
            QMessageBox.warning(self, "Warning", "Please enter some text.")
            logging.warning("Add text failed: No text entered.")
            return

        # Build the QFont using current settings
        qfont = QFont()
        qfont.setFamily(self.selected_font_family)
        qfont.setPixelSize(self.selected_font_size)

        # Create a new ResizableTextItem
        text_item = ResizableTextItem(text)
        # Ensure text color is fully opaque
        self.current_text_color.setAlpha(255)
        text_item.setDefaultTextColor(self.current_text_color)
        text_item.setFontAndUpdateOrigin(qfont)  # Set font and update origin
        text_item.setFlags(QGraphicsTextItem.ItemIsMovable | QGraphicsTextItem.ItemIsSelectable)

        # Calculate the position to center the text item in the scene
        scene_rect = self.scene.sceneRect()
        text_bounding_rect = text_item.boundingRect()

        center_x = (scene_rect.width() - text_bounding_rect.width()) / 2
        center_y = (scene_rect.height() - text_bounding_rect.height()) / 2
        text_item.setPos(center_x, center_y)

        # Add to the scene
        self.scene.addItem(text_item)
        self.text_input.clear()

        # Extra logs for debugging the preview text sizes
        bounding_rect = text_item.boundingRect()
        logging.info(
            f"--- TEXT DEBUG (Preview) ---\n"
            f"Text => '{text}'\n"
            f"Font => {qfont.family()} (pixelSize={qfont.pixelSize()})\n"
            f"QGraphicsTextItem boundingRect => {bounding_rect.width():.2f}x{bounding_rect.height():.2f} px\n"
            f"SceneRect => {scene_rect.width():.2f}x{scene_rect.height():.2f}\n"
            f"Placed at => ({center_x:.2f}, {center_y:.2f}) in scene\n"
            f"Transform Origin => {text_item.transformOriginPoint()}\n"
            f"---------------------------------"
        )

        # Now finalize transform origin
        text_item.setTransformOriginPoint(text_item.boundingRect().center())
        logging.debug("add_text_to_preview: Transform origin set to center.")

    def apply_only_text_to_current(self, show_warnings=True):
        """
        Applies the text items in the scene to the currently selected output image,
        while clipping them against any transparent parts of that image.
        MODIFIED so if no text is *selected*, it applies *all text* in the scene (we do not remove your existing code).
        """
        selected_item = self.output_list.currentItem()
        if not selected_item:
            if show_warnings:
                QMessageBox.warning(self, "Warning", "No output image selected for text.")
            logging.warning("Apply only text failed: No output image selected.")
            return

        # Gather text items *from selection first*
        # (keeping your existing approach, but if none are selected, gather all text in the scene)
        items = self.scene.selectedItems()
        text_items = [i for i in items if isinstance(i, QGraphicsTextItem)]

        if not text_items:
            # If no selected text items, gather *all* text items in the scene
            logging.debug("apply_only_text_to_current: No selected text, gathering all text in scene.")
            all_text = [i for i in self.scene.items() if isinstance(i, QGraphicsTextItem)]
            if not all_text:
                if show_warnings:
                    QMessageBox.warning(self, "Warning", "No text items found in the scene.")
                logging.warning("No text items to apply.")
                return
            text_items = all_text

        out_name = selected_item.text()
        out_path = os.path.join(self.output_folder, out_name)
        logging.info(f"Applying ONLY text to: {out_name}")

        success = self.apply_text_to_image(out_path, text_items, self.scene.sceneRect())
        if success and show_warnings:
            QMessageBox.information(
                self,
                "Done",
                f"Only text applied to:\n{out_path}"
            )
            logging.info(f"Successfully applied only text to {out_path}.")

    def apply_only_text_to_all(self, show_warnings=True):
        """
        Applies text items in the scene to ALL output images,
        clipping them to base transparency so no overspill.
        MODIFIED so if no text is *selected*, it uses all text in the scene.
        """
        if self.output_list.count() == 0:
            if show_warnings:
                QMessageBox.warning(self, "Warning", "No output images to apply text to.")
            logging.warning("Apply only text to all failed: No output images.")
            return

        # Gather selected text first
        items = self.scene.selectedItems()
        text_items = [i for i in items if isinstance(i, QGraphicsTextItem)]

        if not text_items:
            # If none selected, gather all text in scene
            logging.debug("apply_only_text_to_all: No selected text, gathering all text.")
            all_text = [i for i in self.scene.items() if isinstance(i, QGraphicsTextItem)]
            if not all_text:
                if show_warnings:
                    QMessageBox.warning(self, "Warning", "No text items found in the scene.")
                logging.warning("No text items to apply.")
                return
            text_items = all_text

        scene_rect = self.scene.sceneRect()

        for i in range(self.output_list.count()):
            out_name = self.output_list.item(i).text()
            out_path = os.path.join(self.output_folder, out_name)
            logging.info(f"Applying ONLY text to: {out_name}")

            success = self.apply_text_to_image(
                out_path,
                text_items,
                scene_rect,
                debug_prefix="(ALL)"
            )
            if not success:
                logging.error(f"Failed to apply only text to {out_name}.")

        if show_warnings:
            QMessageBox.information(
                self,
                "Done",
                f"Only text applied to all output images in:\n{self.output_folder}"
            )
        logging.info("Successfully applied only text to all output images.")

    def apply_text_to_image(self, output_path, text_items, scene_rect, debug_prefix=""):
        """
        Helper to draw text items onto an existing PNG, then clip them to base alpha
        so no text spills over transparent areas. Ensures descenders (y, g, p, q) 
        are fully visible by adding extra space below the baseline.
        """
        try:
            # 1) Load base image as RGBA
            image = Image.open(output_path).convert('RGBA')
            base_width, base_height = image.size

            # 2) Create a blank RGBA overlay to draw text
            overlay = Image.new('RGBA', (base_width, base_height), (0, 0, 0, 0))

            # 3) We’ll draw each text item onto the overlay (with rotation),
            #    then alpha-composite overlay onto the base, and multiply alpha to clip.
            #    We do NOT scale the text size by sceneRect (1:1 pixel sizing).
            scale_factor = min(
                base_width / scene_rect.width() if scene_rect.width() else 1,
                base_height / scene_rect.height() if scene_rect.height() else 1
            )
            logging.info(
                f"apply_text_to_image({debug_prefix}): OUTPUT={os.path.basename(output_path)}\n"
                f"Base image size => {base_width}x{base_height} px\n"
                f"SceneRect => {scene_rect.width():.2f}x{scene_rect.height():.2f}\n"
                f"Calculated scale_factor => {scale_factor:.4f}\n"
                f"(No scaling of text font size; only (x,y) positions are scaled.)"
            )

            for text_item in text_items:
                text = text_item.toPlainText()
                if not text:
                    continue

                qfont = text_item.font()
                rotation = text_item.rotation()

                # We'll scale the x,y position if needed
                x = text_item.pos().x() * scale_factor
                y = text_item.pos().y() * scale_factor

                # The actual font size we got from QGraphicsTextItem
                actual_font_size = qfont.pixelSize()
                if actual_font_size <= 0:
                    actual_font_size = self.selected_font_size  # fallback

                # Attempt to load the same TTF font for PIL
                from PIL import ImageFont, ImageDraw
                temp_draw = ImageDraw.Draw(overlay)  # just for measuring
                try:
                    if self.selected_font_path:
                        pil_font = ImageFont.truetype(self.selected_font_path, actual_font_size)
                    else:
                        pil_font = ImageFont.load_default()
                except Exception as e:
                    logging.error(f"Could not load selected font: {e}. Using default font.")
                    pil_font = ImageFont.load_default()

                # Measure text bounding box normally
                bbox = temp_draw.textbbox((0, 0), text, font=pil_font)
                text_w = bbox[2] - bbox[0]
                text_h = bbox[3] - bbox[1]

                # Get the font metrics to accommodate descenders
                ascent, descent = pil_font.getmetrics()
                # Sometimes textbbox omits tails, so let's ensure we add enough padding:
                # The total needed height is at least ascent+descent
                needed_h = max(text_h, ascent + descent + 2)  # +2 to ensure no cut-off

                # Create a small RGBA for the text with extra space for descenders
                text_layer = Image.new('RGBA', (text_w, needed_h), (0, 0, 0, 0))
                text_draw = ImageDraw.Draw(text_layer)

                # Fully opaque text color
                text_color = (
                    self.current_text_color.red(),
                    self.current_text_color.green(),
                    self.current_text_color.blue(),
                    255
                )

                # Draw text at top-left (0, 0). Because we gave enough vertical space,
                # descenders won't get clipped anymore.
                text_draw.text((0, 0), text, font=pil_font, fill=text_color)

                # Rotate by -rotation
                rotated_text = text_layer.rotate(-rotation, expand=True)
                rotated_w, rotated_h = rotated_text.size

                # Compute final paste coords (clamp to avoid out-of-bounds)
                paste_x = int(max(0, min(x, base_width - rotated_w)))
                paste_y = int(max(0, min(y, base_height - rotated_h)))

                # Paste rotated text onto overlay using alpha
                overlay.paste(rotated_text, (paste_x, paste_y), rotated_text)

                # More logs for debugging text size & bounding
                logging.info(
                    f"--- TEXT DEBUG {debug_prefix} ---\n"
                    f"Text => '{text}'\n"
                    f"QFont => {qfont.family()} (pixelSize={qfont.pixelSize()})\n"
                    f"PIL font => size={actual_font_size}, metrics=(ascent={ascent}, descent={descent})\n"
                    f"Measured text bbox => w={text_w}, h={text_h}, needed_h={needed_h}\n"
                    f"Rotated => {rotated_w}x{rotated_h} px\n"
                    f"Scene pos => ({text_item.pos().x():.2f}, {text_item.pos().y():.2f}) => scaled => ({x:.2f}, {y:.2f})\n"
                    f"Paste => ({paste_x}, {paste_y}) in base\n"
                    f"Rotation => {rotation} deg\n"
                    f"----------------------------------------"
                )

            # 4) Alpha-composite overlay onto base
            composited = Image.alpha_composite(image, overlay)

            # 5) Multiply final alpha by base alpha (clip to base’s opaque region)
            base_a = image.getchannel("A")
            final_a = composited.getchannel("A")
            clipped_a = ImageChops.multiply(base_a, final_a)
            composited.putalpha(clipped_a)

            # 6) Save
            composited.save(output_path, 'PNG')
            logging.info(
                f"apply_text_to_image({debug_prefix}): "
                f"Saved final composited image to '{output_path}' (size={composited.size}).\n"
            )
            return True

        except Exception as e:
            logging.error(f"Error applying text to image {output_path}: {e}")
            return False

    def update_selected_item(self):
        selected_items = self.scene.selectedItems()
        if not selected_items:
            QMessageBox.warning(self, "Warning", "No item selected to update.")
            logging.warning("Update selected item failed: No item selected.")
            return

        selected_item = selected_items[0]
        logging.info(f"Updating selected item: {selected_item}")

        if isinstance(selected_item, ResizableTextItem):
            new_text, ok = QInputDialog.getText(
                self, "Update Text", "Enter new text:", QLineEdit.Normal, ""
            )
            if ok and new_text.strip():
                selected_item.setPlainText(new_text.strip())
                selected_item.updateTransformOrigin()  # Update transform origin after text change
                logging.info(f"Text updated to: '{new_text.strip()}'")
            else:
                QMessageBox.warning(self, "Warning", "No text entered.")
                logging.warning("Update selected item failed: No text entered.")
        elif isinstance(selected_item, ResizableIconItem):
            # Implement any specific update logic for icons if needed
            QMessageBox.information(self, "Info", "Selected item is an image/icon. No text to update.")
            logging.info("Update selected item: Selected item is an image/icon.")
        else:
            QMessageBox.warning(self, "Warning", "Selected item is not a text or image/icon item.")
            logging.warning("Update selected item failed: Selected item is neither text nor image/icon.")

    def update_selected_font(self):
        selected_items = self.scene.selectedItems()
        if not selected_items:
            QMessageBox.warning(self, "Warning", "No item selected to update font.")
            logging.warning("Update font failed: No item selected.")
            return

        selected_item = selected_items[0]
        if not isinstance(selected_item, QGraphicsTextItem):
            QMessageBox.warning(self, "Warning", "Selected item is not a text item.")
            logging.warning("Update font failed: Selected item is not a text item.")
            return

        fonts_directory = os.path.join(self.root_dir, "resources", "fonts")
        if not os.path.isdir(fonts_directory):
            QMessageBox.information(self, "Info", "No fonts folder found; using default Arial.")
            logging.info("No fonts folder found; using default Arial.")
            return

        dialog = FontSelectionDialog(fonts_directory, self)
        if dialog.exec() == QDialog.Accepted:
            new_font_path = dialog.selected_font_path
            if new_font_path:
                font_db = QFontDatabase()
                loaded_font_id = font_db.addApplicationFont(new_font_path)
                if loaded_font_id == -1:
                    QMessageBox.warning(self, "Error", "Failed to load the selected font.")
                    logging.error("Failed to load the selected font.")
                    return
                loaded_families = font_db.applicationFontFamilies(loaded_font_id)
                font_family = loaded_families[0] if loaded_families else "Arial"

                current_font = selected_item.font()
                current_font.setFamily(font_family)
                selected_item.setFont(current_font)
                logging.info(f"Updated selected text item to font '{font_family}'.")
                QMessageBox.information(self, "Success", f"Font updated to {font_family}.")
        else:
            logging.info("Font update canceled.")

    def update_selected_font_size(self, value):
        self.selected_font_size = value
        logging.info(f"Selected font size changed to: {value} (for newly added text.)")

        selected_items = self.scene.selectedItems()
        if not selected_items:
            return
        selected_item = selected_items[0]
        if isinstance(selected_item, QGraphicsTextItem):
            font = selected_item.font()
            font.setPixelSize(value)
            selected_item.setFont(font)
            logging.info(f"Updated selected text item font size to: {value}")

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            pos = self.output_preview_view.mapFromGlobal(self.mapToGlobal(event.pos()))
            scene_pos = self.output_preview_view.mapToScene(pos)
            items = self.scene.items(scene_pos)
            if not items:
                self.scene.clearSelection()
                logging.info("Clicked on empty space in preview. Cleared selection.")
        super().mousePressEvent(event)

    def load_output_images(self):
        self.output_list.clear()
        if not self.output_folder:
            logging.warning("Output folder not set. Cannot load output images.")
            return

        supported_formats = ('.png', '.jpg', '.jpeg', '.bmp', '.gif')
        image_files = [f for f in os.listdir(self.output_folder) if f.lower().endswith(supported_formats)]
        if not image_files:
            QMessageBox.information(self, "No Images Found", "No image files were found in the output folder.")
            logging.info("No image files found in the output folder.")
            return

        for img_file in image_files:
            img_path = os.path.join(self.output_folder, img_file)
            pixmap = QPixmap(img_path)
            if pixmap.isNull():
                logging.warning(f"Cannot load image: {img_path}")
                continue

            icon = QIcon(pixmap.scaled(100, 100, Qt.KeepAspectRatio, Qt.SmoothTransformation))
            item = QListWidgetItem(icon, img_file)
            self.output_list.addItem(item)

        logging.info(f"Loaded {len(image_files)} images into output_list.")
        
    def convert_to_paa(self):
        if not self.dayz_tools_dir:
            QMessageBox.warning(self, "Warning", "DayZ Tools directory not set.")
            return

        # ---------------------------------------------------------
        # UPDATED CODE: PROMPT ONLY IF we detect subdirs that match
        #  self.opt_mod_name OR '@self.opt_mod_name'. If none, skip prompt.
        # ---------------------------------------------------------
        if os.path.exists(self.output_folder):
            mod_dir_name = self.opt_mod_name.strip() or ""
            possible_dirs = [mod_dir_name, f"@{mod_dir_name}"]

            # Gather actual subdirectories in output_folder
            subdirs = [
                item
                for item in os.listdir(self.output_folder)
                if os.path.isdir(os.path.join(self.output_folder, item))
            ]

            # Check overlap with possible_dirs
            dirs_to_remove = [sd for sd in subdirs if sd in possible_dirs]

            if dirs_to_remove:
                # If we have at least one matching subdirectory, prompt
                reply = QMessageBox.question(
                    self,
                    "Overwrite Folder?",
                    f"The selected output folder ({self.output_folder}) contains these directories:\n"
                    f"{dirs_to_remove}\n\n"
                    "Do you want to overwrite (remove) them?\n\n"
                    "NOTE: This will ONLY remove those matching directories.\n"
                    "It will NOT remove any .png files.",
                    QMessageBox.Yes | QMessageBox.No
                )
                if reply == QMessageBox.No:
                    return
                else:
                    # Remove only those subdirectories
                    for d in dirs_to_remove:
                        dir_path = os.path.join(self.output_folder, d)
                        try:
                            shutil.rmtree(dir_path)
                            logging.info(f"Removed directory: {dir_path}")
                        except Exception as e:
                            logging.error(f"Error removing directory {dir_path}: {e}")
        # ---------------------------------------------------------
        # END OF UPDATED CODE
        # ---------------------------------------------------------

        # 1) Get the base_name from the same QLineEdit you used in apply_texture()
        base_name = self.rename_input.text().strip()
        if not base_name:
            QMessageBox.warning(self, "Warning", "Enter a base name first for .PAA conversion.")
            return

        # 2) Proceed with normal checks
        image_to_paa_exe = os.path.join(self.dayz_tools_dir, "Bin", "ImageToPAA", "ImageToPAA.exe")
        if not os.path.exists(image_to_paa_exe):
            QMessageBox.critical(self, "Error", f"ImageToPAA.exe not found at:\n{image_to_paa_exe}")
            return

        if not self.output_folder:
            QMessageBox.warning(self, "Warning", "No output folder selected.")
            return

        png_files = [f for f in os.listdir(self.output_folder) if f.lower().endswith('.png')]
        if not png_files:
            QMessageBox.warning(self, "Warning", "No .PNG files found in the output folder.")
            return

        # Disable the button to prevent duplicate execution
        self.convert_to_paa_button.setEnabled(False)

        # 3) Now base_name is defined, you can pass it into script_options
        script_options = {
            'base_name': base_name,
            'dependent_mod': self.opt_dependent_mod,
            'mod_name': self.opt_mod_name,
            'parent_classname': self.opt_parent_classname,
            'hidden_selections': self.opt_hidden_selections
        }

        # 4) Create and start the thread
        self.convert_to_paa_thread = ConvertToPAAThread(
            dayz_tools_dir=self.dayz_tools_dir,
            output_folder=self.output_folder,
            mod_name=self.opt_mod_name,
            generate_scripts=self.chk_generate_scripts.isChecked(),
            pack_into_pbo=self.chk_pack_into_pbo.isChecked(),
            pbo_options={
                'pbo_signing_option': self.opt_pbo_signing_choice,
                'existing_biprivatekey_path': self.opt_existing_biprivatekey,
                'existing_bikey_path': self.opt_existing_bikey,
                'new_key_name': self.opt_new_key_name
            },
            paa_files=png_files,
            script_options=script_options
        )

        # Connect thread signals to the UI
        self.convert_to_paa_thread.progress.connect(self.show_progress)
        self.convert_to_paa_thread.finished_paa.connect(self.on_convert_to_paa_finished)
        self.convert_to_paa_thread.error.connect(self.on_convert_to_paa_error)

        self.convert_to_paa_thread.start()

        logging.info("ConvertToPAAThread started.")

        # Show a loading dialog
        theme = self.themes.get(self.current_theme, "dark")
        self.loading_dlg = LoadingDialog(self, theme)
        self.loading_dlg.progress_bar.setValue(0)
        self.loading_dlg.progress_label.setText("Converting to .PAA...")
        self.loading_dlg.show()

        logging.info("Loading dialog shown for .PAA conversion.")

    @Slot(str, int)
    def update_progress(self, message, percentage):
        # Update your loading dialog or progress bar here
        if hasattr(self, 'loading_dlg') and self.loading_dlg.isVisible():
            self.loading_dlg.update_progress(message, percentage)

    @Slot(str)
    def on_convert_to_paa_finished(self, message):
        if hasattr(self, 'loading_dlg') and self.loading_dlg.isVisible():
            self.loading_dlg.close()
        QMessageBox.information(
            self,
            "Conversion Complete",
            message
        )
        logging.info(message)
        self.convert_to_paa_button.setEnabled(True)

    @Slot(str)
    def on_convert_to_paa_error(self, error_message):
        """
        Slot to handle errors emitted by ConvertToPAAThread.
        Delegates error handling to the existing handle_error method.
        """
        self.handle_error(error_message)

    # ---------------------------------------------------------------------------
    # NEW: Apply Brightness and Contrast Adjustments to all output images
    # ---------------------------------------------------------------------------
    def apply_brightness_contrast_to_all(self):
        if not self.output_folder:
            QMessageBox.warning(self, "Warning", "No output folder selected.")
            logging.warning("Apply brightness/contrast failed: No output folder selected.")
            return

        brightness = self.brightness_slider.value()
        contrast = self.contrast_slider.value()
        supported_formats = ('.png', '.jpg', '.jpeg', '.bmp', '.gif')
        image_files = [f for f in os.listdir(self.output_folder) if f.lower().endswith(supported_formats)]
        if not image_files:
            QMessageBox.warning(self, "Warning", "No images found in the output folder.")
            logging.warning("Apply brightness/contrast failed: No images found.")
            return

        for img_file in image_files:
            img_path = os.path.join(self.output_folder, img_file)
            try:
                image = Image.open(img_path).convert('RGBA')
                # Split into RGB and Alpha
                rgb, alpha = image.split()[:3], image.split()[3]
                rgb_image = Image.merge("RGB", rgb)

                enhancer_brightness = ImageEnhance.Brightness(rgb_image)
                rgb_image = enhancer_brightness.enhance(brightness / 100.0)

                enhancer_contrast = ImageEnhance.Contrast(rgb_image)
                rgb_image = enhancer_contrast.enhance(contrast / 100.0)

                # Merge back with original alpha
                final_image = Image.merge("RGBA", (*rgb_image.split(), alpha))

                final_image.save(img_path, format='PNG')
                logging.info(f"Applied brightness/contrast to {img_file}.")
            except Exception as e:
                logging.error(f"Error applying brightness/contrast to {img_file}: {e}")
                QMessageBox.warning(self, "Error", f"Error applying adjustments to {img_file}:\n{e}")
        self.load_output_images()
        QMessageBox.information(self, "Done", "Brightness and Contrast adjustments applied to all images.")

    def on_selection_changed(self):
        selected_items = self.scene.selectedItems()
        if selected_items:
            self.update_text_image_button.setEnabled(True)
            if isinstance(selected_items[0], ResizableTextItem):
                self.update_font_button.setEnabled(True)
                self.update_font_size_spinbox.setEnabled(True)
                logging.info("Selected item is text. Font update controls enabled.")
            elif isinstance(selected_items[0], ResizableIconItem):
                self.update_font_button.setEnabled(False)
                self.update_font_size_spinbox.setEnabled(False)
                logging.info("Selected item is an image/icon. Font update controls disabled.")
            else:
                self.update_font_button.setEnabled(False)
                self.update_font_size_spinbox.setEnabled(False)
                logging.info("Selected item is neither text nor image/icon. Font update controls disabled.")
        else:
            self.update_text_image_button.setEnabled(False)
            self.update_font_button.setEnabled(False)
            self.update_font_size_spinbox.setEnabled(False)
            logging.info("No item selected. Update buttons disabled.")

    def show_image_in_label(self, pil_image, label, max_size):
        if pil_image.mode != 'RGBA':
            pil_image = pil_image.convert('RGBA')
        pixmap = pil2pixmap(pil_image)
        scaled = pixmap.scaled(
            max_size[0], max_size[1],
            Qt.KeepAspectRatio,
            Qt.SmoothTransformation
        )
        label.setPixmap(scaled)
        logging.info(f"Displayed template in label with scaled size: {scaled.size()}")

# ---------------------------------------------------------------------------
# Main Application Logic
# ---------------------------------------------------------------------------
def main():
    import sys
    app = QApplication(sys.argv)

    app.setStyleSheet("""
        QToolTip {
            color: white;
            background-color: #2c2c2c;
            border: 1px solid #555555;
            padding: 5px;
            border-radius: 3px;
            font-size: 12px;
        }
    """)

    logging.basicConfig(
        filename='texturing_app.log',
        level=logging.DEBUG,
        format='%(asctime)s - %(levelname)s - %(message)s'
    )
    logging.info("Application started.")

    login_dialog = LoginPanel()  # Ensure LoginPanel is correctly implemented
    if login_dialog.exec() == QDialog.Accepted:
        window = TexturingApp()
        window.show()
        sys.exit(app.exec())
    else:
        sys.exit(0)

if __name__ == "__main__":
    main()
