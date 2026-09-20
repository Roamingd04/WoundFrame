#!/usr/bin/env python3
"""
WoundFrame
========================

A reproducible workflow for standardizing longitudinal wound photographs
to a common physical scale and generating publication-ready image panels.

Workflow for each image:
1. Select two points on an in-frame metric reference separated by a known distance.
2. Select the wound center.
3. Calculate pixels/mm from the reference.
4. Rotate the image so the calibration segment is horizontal.
5. Resample to a common pixels/mm value.
6. Crop a fixed physical field of view centered on the wound.
7. Optionally add a scale bar.
8. Assemble subjects x timepoints into a panel.

The program preserves calibration coordinates, settings, input hashes, processing
metadata, software versions, duplicate reports, and unparsed filenames.

This script does not alter the original input files.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import platform
import re
import shutil
import sys
import traceback
import zipfile
from dataclasses import asdict, dataclass
from pathlib import Path

import cv2
import matplotlib
import numpy as np

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402


__version__ = "1.0.0"

BASE_DIR = Path(__file__).resolve().parent
DEFAULT_OUTPUT_ROOT = BASE_DIR / "wound_panel_output"
DEFAULT_CACHE_ROOT = BASE_DIR / "_wound_panel_cache"
DEFAULT_ERROR_LOG = BASE_DIR / "error_log.txt"

SUPPORTED_EXTENSIONS = {
    ".jpg", ".jpeg", ".png", ".tif", ".tiff", ".bmp", ".webp"
}


@dataclass(frozen=True)
class Config:
    calibration_mm: float = 20.0
    target_pixels_per_mm: float = 50.0
    crop_width_mm: float = 20.0
    crop_height_mm: float = 20.0
    scale_bar_mm: float = 5.0
    add_scale_bar: bool = True
    fullscreen: bool = True
    cell_width_in: float = 2.75
    cell_height_in: float = 2.75
    wspace: float = 0.25
    hspace: float = 0.40
    panel_title: str = "Standardized macroscopic wound evolution"


def positive_float(value: str) -> float:
    value = str(value).replace(",", ".")
    try:
        number = float(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"Invalid numeric value: {value}") from exc
    if number <= 0:
        raise argparse.ArgumentTypeError("Value must be greater than zero.")
    return number


def nonnegative_float(value: str) -> float:
    value = str(value).replace(",", ".")
    try:
        number = float(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"Invalid numeric value: {value}") from exc
    if number < 0:
        raise argparse.ArgumentTypeError("Value must be zero or greater.")
    return number


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Standardize longitudinal wound photographs to a common physical "
            "scale and generate a subject-by-timepoint panel."
        )
    )
    parser.add_argument(
        "--input",
        type=Path,
        help="Input folder or ZIP. If omitted, a file/folder picker is used.",
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        default=DEFAULT_OUTPUT_ROOT,
        help="Root directory for generated datasets and runs.",
    )
    parser.add_argument(
        "--calibration-mm",
        type=positive_float,
        default=Config.calibration_mm,
        help="Known physical distance between the two ruler clicks in mm.",
    )
    parser.add_argument(
        "--target-ppmm",
        type=positive_float,
        default=Config.target_pixels_per_mm,
        help="Target output resolution in pixels/mm.",
    )
    parser.add_argument(
        "--crop-width-mm",
        type=positive_float,
        default=Config.crop_width_mm,
        help="Physical crop width in mm.",
    )
    parser.add_argument(
        "--crop-height-mm",
        type=positive_float,
        default=Config.crop_height_mm,
        help="Physical crop height in mm.",
    )
    parser.add_argument(
        "--scale-bar-mm",
        type=positive_float,
        default=Config.scale_bar_mm,
        help="Scale bar length in mm.",
    )
    parser.add_argument(
        "--scale-bar",
        choices=["yes", "no"],
        default="yes",
        help="Add a scale bar to standardized crops.",
    )
    parser.add_argument(
        "--fullscreen",
        choices=["yes", "no"],
        default="yes",
        help="Use fullscreen calibration windows.",
    )
    parser.add_argument(
        "--cell-width-in",
        type=positive_float,
        default=Config.cell_width_in,
        help="Approximate width allocated to each panel cell in inches.",
    )
    parser.add_argument(
        "--cell-height-in",
        type=positive_float,
        default=Config.cell_height_in,
        help="Approximate height allocated to each panel cell in inches.",
    )
    parser.add_argument(
        "--wspace",
        type=nonnegative_float,
        default=Config.wspace,
        help="Horizontal Matplotlib spacing between panel cells.",
    )
    parser.add_argument(
        "--hspace",
        type=nonnegative_float,
        default=Config.hspace,
        help="Vertical Matplotlib spacing between panel cells.",
    )
    parser.add_argument(
        "--title",
        default=Config.panel_title,
        help="Title written above the generated panel.",
    )
    parser.add_argument(
        "--recalibrate",
        action="store_true",
        help="Discard saved click coordinates for this dataset and recalibrate.",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )
    return parser.parse_args()


def config_from_args(args: argparse.Namespace) -> Config:
    return Config(
        calibration_mm=args.calibration_mm,
        target_pixels_per_mm=args.target_ppmm,
        crop_width_mm=args.crop_width_mm,
        crop_height_mm=args.crop_height_mm,
        scale_bar_mm=args.scale_bar_mm,
        add_scale_bar=args.scale_bar == "yes",
        fullscreen=args.fullscreen == "yes",
        cell_width_in=args.cell_width_in,
        cell_height_in=args.cell_height_in,
        wspace=args.wspace,
        hspace=args.hspace,
        panel_title=args.title,
    )


def natural_key(value: object) -> list[object]:
    return [
        int(piece) if piece.isdigit() else piece.lower()
        for piece in re.split(r"(\d+)", str(value))
    ]


def safe_name(value: str, fallback: str = "dataset") -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", value).strip("._-")
    return cleaned or fallback


def is_under(path: Path, parent: Path) -> bool:
    try:
        path.resolve().relative_to(parent.resolve())
        return True
    except (OSError, ValueError):
        return False


def sha256_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(chunk_size)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def read_image(path: Path) -> np.ndarray:
    """Unicode-safe OpenCV image reader for Windows and other platforms."""
    data = np.fromfile(str(path), dtype=np.uint8)
    image = cv2.imdecode(data, cv2.IMREAD_COLOR)
    if image is None:
        raise RuntimeError(f"Could not read image: {path}")
    return image


def write_image(path: Path, image: np.ndarray) -> None:
    """Unicode-safe OpenCV image writer."""
    suffix = path.suffix.lower() or ".png"
    ok, encoded = cv2.imencode(suffix, image)
    if not ok:
        raise RuntimeError(f"Could not encode image for: {path}")
    encoded.tofile(str(path))


def find_images(
    root: Path,
    output_root: Path | None = None,
    cache_root: Path | None = None,
) -> list[Path]:
    images: list[Path] = []
    root = root.resolve()

    for path in root.rglob("*"):
        if not path.is_file() or path.suffix.lower() not in SUPPORTED_EXTENSIONS:
            continue
        if output_root is not None and is_under(path, output_root):
            continue
        if (
            cache_root is not None
            and not is_under(root, cache_root)
            and is_under(path, cache_root)
        ):
            continue
        images.append(path)

    return sorted(images, key=natural_key)


def safe_extract_zip(zip_path: Path, destination: Path) -> None:
    destination_resolved = destination.resolve()
    with zipfile.ZipFile(zip_path, "r") as archive:
        for member in archive.infolist():
            target = (destination / member.filename).resolve()
            if not is_under(target, destination_resolved) and target != destination_resolved:
                raise RuntimeError(
                    f"Unsafe path found inside ZIP archive: {member.filename}"
                )
        archive.extractall(destination)


def extract_zip(
    zip_path: Path,
    cache_root: Path,
    output_root: Path,
) -> Path:
    identity = f"{zip_path.resolve()}|{zip_path.stat().st_size}|{zip_path.stat().st_mtime_ns}"
    key = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:12]
    destination = cache_root / f"{safe_name(zip_path.stem)}_{key}"
    destination.mkdir(parents=True, exist_ok=True)

    if not any(destination.iterdir()):
        safe_extract_zip(zip_path, destination)

    images = find_images(
        destination,
        output_root=output_root,
        cache_root=cache_root,
    )
    if not images:
        found_extensions = sorted(
            {
                p.suffix.lower()
                for p in destination.rglob("*")
                if p.is_file()
            }
        )
        ext_text = ", ".join(found_extensions) if found_extensions else "none"
        raise RuntimeError(
            "The ZIP archive was extracted, but no supported image files were found. "
            f"Extensions found: {ext_text}"
        )

    print(f"ZIP selected      : {zip_path}")
    print(f"Extraction folder : {destination}")
    print(f"Images discovered : {len(images)}")
    return destination


def _tk_root():
    try:
        import tkinter as tk
    except ImportError as exc:
        raise RuntimeError(
            "Tkinter is not available. Run the script with --input PATH instead."
        ) from exc

    root = tk.Tk()
    root.withdraw()
    try:
        root.attributes("-topmost", True)
    except Exception:
        pass
    return root


def show_info(title: str, message: str) -> None:
    try:
        from tkinter import messagebox
        root = _tk_root()
        messagebox.showinfo(title, message, parent=root)
        root.destroy()
    except Exception:
        print(f"\n{title}\n{message}\n")


def show_error(title: str, message: str) -> None:
    try:
        from tkinter import messagebox
        root = _tk_root()
        messagebox.showerror(title, message, parent=root)
        root.destroy()
    except Exception:
        print(f"\n{title}: {message}\n", file=sys.stderr)


def choose_input(
    supplied_input: Path | None,
    cache_root: Path,
    output_root: Path,
) -> Path:
    if supplied_input is not None:
        selected = supplied_input.expanduser().resolve()
        if not selected.exists():
            raise FileNotFoundError(f"Input path does not exist: {selected}")
        if selected.is_file():
            if selected.suffix.lower() != ".zip":
                raise RuntimeError("--input must be a folder or ZIP archive.")
            return extract_zip(selected, cache_root, output_root)
        return selected

    local_zips = sorted(BASE_DIR.glob("*.zip"), key=natural_key)
    if len(local_zips) == 1:
        return extract_zip(local_zips[0], cache_root, output_root)

    try:
        from tkinter import filedialog
        root = _tk_root()
        selected_zip = filedialog.askopenfilename(
            parent=root,
            title="Select a ZIP archive. Cancel to select an image folder.",
            filetypes=[("ZIP archives", "*.zip"), ("All files", "*.*")],
        )
        root.destroy()

        if selected_zip:
            return extract_zip(Path(selected_zip), cache_root, output_root)

        root = _tk_root()
        selected_folder = filedialog.askdirectory(
            parent=root,
            title="Select the folder containing the wound photographs",
        )
        root.destroy()
    except Exception as exc:
        raise RuntimeError(
            "No input was provided and the graphical file picker could not be opened. "
            "Run with --input PATH."
        ) from exc

    if not selected_folder:
        raise FileNotFoundError("No input folder or ZIP archive was selected.")

    return Path(selected_folder).resolve()


DAY_PATTERNS = (
    r"(?<![a-z0-9])z[\s_-]*(\d+)(?!\d)",
    r"(?<![a-z0-9])day[\s_-]*(\d+)(?!\d)",
    r"(?<![a-z0-9])d[\s_-]*(\d+)(?!\d)",
)


def relative_parent_names(path: Path, input_root: Path) -> list[str]:
    try:
        relative = path.relative_to(input_root)
    except ValueError:
        return []
    return [parent.name for parent in relative.parents if parent.name not in ("", ".")]


def extract_day_token(path: Path, input_root: Path) -> str | None:
    candidates = [path.stem, *relative_parent_names(path, input_root)]

    for candidate in candidates:
        for pattern in DAY_PATTERNS:
            match = re.search(pattern, candidate.lower(), flags=re.IGNORECASE)
            if match:
                return f"z{int(match.group(1))}"
    return None


def parse_subject_day(path: Path, input_root: Path) -> tuple[str | None, str | None]:
    day = extract_day_token(path, input_root)
    if day is None:
        return None, None

    day_number = day[1:]
    subject = path.stem.lower().strip()

    subject = re.sub(
        rf"(?i)(?<![a-z0-9])(?:z|day|d)[\s_-]*{re.escape(day_number)}(?!\d)",
        "",
        subject,
    )
    subject = re.sub(r"[\s_-]+", "-", subject).strip("-")

    if not subject:
        for parent_name in relative_parent_names(path, input_root):
            candidate = parent_name.lower().strip()
            if not candidate:
                continue
            fake_path = input_root / candidate / "placeholder.jpg"
            if extract_day_token(fake_path, input_root) is not None:
                continue
            subject = re.sub(r"[\s_-]+", "-", candidate).strip("-")
            if subject:
                break

    if not subject:
        subject = path.stem.lower().strip()

    return subject, day


def timepoint_number(day: str) -> int:
    match = re.search(r"\d+", day)
    if not match:
        raise ValueError(f"Invalid canonical timepoint: {day}")
    return int(match.group())


def image_key(path: Path, input_root: Path) -> str:
    try:
        return path.relative_to(input_root).as_posix()
    except ValueError:
        return str(path.resolve())


def build_manifest(
    images: list[Path],
    input_root: Path,
) -> tuple[list[dict[str, object]], list[tuple[Path, str, str]], list[Path], str]:
    rows: list[dict[str, object]] = []
    parsed: list[tuple[Path, str, str]] = []
    unparsed: list[Path] = []

    dataset_hasher = hashlib.sha256()

    for path in images:
        relative = image_key(path, input_root)
        file_hash = sha256_file(path)
        subject, day = parse_subject_day(path, input_root)

        row = {
            "relative_path": relative,
            "size_bytes": path.stat().st_size,
            "sha256": file_hash,
            "subject": subject or "",
            "timepoint": day or "",
            "parsed": bool(subject and day),
        }
        rows.append(row)

        dataset_hasher.update(relative.encode("utf-8"))
        dataset_hasher.update(b"\0")
        dataset_hasher.update(file_hash.encode("ascii"))
        dataset_hasher.update(b"\n")

        if subject and day:
            parsed.append((path, subject, day))
        else:
            unparsed.append(path)

    parsed.sort(
        key=lambda item: (
            natural_key(item[1]),
            timepoint_number(item[2]),
            natural_key(item[0].name),
        )
    )

    return rows, parsed, unparsed, dataset_hasher.hexdigest()[:12]


def write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    if not rows:
        return
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def load_calibration(path: Path) -> dict[str, dict[str, float]]:
    if not path.exists():
        return {}

    result: dict[str, dict[str, float]] = {}
    with path.open("r", newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            result[row["image"]] = {
                key: float(row[key])
                for key in ("x1", "y1", "x2", "y2", "cx", "cy")
            }
    return result


def save_calibration(
    path: Path,
    calibration: dict[str, dict[str, float]],
) -> None:
    rows = []
    for key in sorted(calibration, key=natural_key):
        rows.append({"image": key, **calibration[key]})
    write_csv(path, rows)


def get_screen_size() -> tuple[int, int]:
    try:
        root = _tk_root()
        width = int(root.winfo_screenwidth())
        height = int(root.winfo_screenheight())
        root.destroy()
        return max(800, width), max(600, height)
    except Exception:
        return 1920, 1080


def prepare_display(
    image: np.ndarray,
    fullscreen: bool,
) -> tuple[np.ndarray, float, int, int, int, int]:
    height, width = image.shape[:2]

    if fullscreen:
        screen_width, screen_height = get_screen_size()
    else:
        screen_width, screen_height = 1400, 850

    scale = min(screen_width / width, screen_height / height)
    shown_width = int(round(width * scale))
    shown_height = int(round(height * scale))

    resized = cv2.resize(
        image,
        (shown_width, shown_height),
        interpolation=cv2.INTER_AREA if scale < 1 else cv2.INTER_CUBIC,
    )

    canvas = np.full(
        (screen_height, screen_width, 3),
        fill_value=25,
        dtype=np.uint8,
    )
    x0 = (screen_width - shown_width) // 2
    y0 = (screen_height - shown_height) // 2
    canvas[y0:y0 + shown_height, x0:x0 + shown_width] = resized

    return canvas, scale, x0, y0, shown_width, shown_height


def collect_three_clicks(
    path: Path,
    config: Config,
    number: int,
    total: int,
) -> dict[str, float] | None:
    image = read_image(path)
    shown, scale, x0, y0, shown_width, shown_height = prepare_display(
        image,
        config.fullscreen,
    )
    base = shown.copy()
    points: list[tuple[int, int]] = []
    window = f"[{number}/{total}] Calibration - {path.name}"

    def redraw() -> None:
        canvas = base.copy()
        instructions = (
            f"{number}/{total} | {path.name}",
            "1) Click calibration point A on the ruler",
            f"2) Click point B exactly {config.calibration_mm:g} mm from A",
            "3) Click the wound center",
            "ENTER = accept    R = reset    ESC = skip",
        )

        y = 30
        for line in instructions:
            cv2.putText(
                canvas, line, (22, y),
                cv2.FONT_HERSHEY_SIMPLEX, 0.68,
                (255, 255, 255), 4, cv2.LINE_AA,
            )
            cv2.putText(
                canvas, line, (22, y),
                cv2.FONT_HERSHEY_SIMPLEX, 0.68,
                (0, 0, 0), 1, cv2.LINE_AA,
            )
            y += 29

        colors = ((0, 220, 255), (0, 220, 255), (0, 255, 0))
        labels = ("A", "B", "W")

        for index, (x, py) in enumerate(points):
            cv2.circle(canvas, (x, py), 8, colors[index], -1, cv2.LINE_AA)
            cv2.circle(canvas, (x, py), 12, (0, 0, 0), 2, cv2.LINE_AA)
            cv2.putText(
                canvas, labels[index], (x + 14, py - 10),
                cv2.FONT_HERSHEY_SIMPLEX, 0.8,
                colors[index], 3, cv2.LINE_AA,
            )

        if len(points) >= 2:
            cv2.line(
                canvas, points[0], points[1],
                (0, 220, 255), 2, cv2.LINE_AA,
            )

        cv2.imshow(window, canvas)

    def on_mouse(event, x, y, flags, param) -> None:
        del flags, param
        if event != cv2.EVENT_LBUTTONDOWN or len(points) >= 3:
            return
        if x0 <= x < x0 + shown_width and y0 <= y < y0 + shown_height:
            points.append((x, y))
            redraw()

    try:
        cv2.namedWindow(window, cv2.WINDOW_NORMAL)
        if config.fullscreen:
            cv2.setWindowProperty(
                window,
                cv2.WND_PROP_FULLSCREEN,
                cv2.WINDOW_FULLSCREEN,
            )
        else:
            cv2.resizeWindow(window, shown.shape[1], shown.shape[0])
        cv2.setMouseCallback(window, on_mouse)
        redraw()
    except cv2.error as exc:
        raise RuntimeError(
            "OpenCV could not open the calibration window. "
            "Install 'opencv-python', not 'opencv-python-headless'."
        ) from exc

    while True:
        key = cv2.waitKeyEx(30)

        if key in (ord("r"), ord("R")):
            points.clear()
            redraw()
        elif key in (13, 10) and len(points) == 3:
            break
        elif key == 27:
            cv2.destroyWindow(window)
            return None

        try:
            if cv2.getWindowProperty(window, cv2.WND_PROP_VISIBLE) < 1:
                return None
        except cv2.error:
            return None

    cv2.destroyWindow(window)

    original_points = [
        ((x - x0) / scale, (y - y0) / scale)
        for x, y in points
    ]
    (x1, y1), (x2, y2), (cx, cy) = original_points

    return {
        "x1": x1,
        "y1": y1,
        "x2": x2,
        "y2": y2,
        "cx": cx,
        "cy": cy,
    }


def affine_point(matrix: np.ndarray, point: tuple[float, float]) -> tuple[float, float]:
    x, y = point
    value = matrix @ np.array([x, y, 1.0], dtype=float)
    return float(value[0]), float(value[1])


def rotate_to_ruler_horizontal(
    image: np.ndarray,
    p1: tuple[float, float],
    p2: tuple[float, float],
    center: tuple[float, float],
) -> tuple[np.ndarray, tuple[float, float], float]:
    dx = p2[0] - p1[0]
    dy = p2[1] - p1[1]
    angle_deg = math.degrees(math.atan2(dy, dx))

    height, width = image.shape[:2]
    image_center = (width / 2.0, height / 2.0)

    matrix = cv2.getRotationMatrix2D(image_center, angle_deg, 1.0)

    cosine = abs(matrix[0, 0])
    sine = abs(matrix[0, 1])
    new_width = int(math.ceil(height * sine + width * cosine))
    new_height = int(math.ceil(height * cosine + width * sine))

    matrix[0, 2] += new_width / 2.0 - image_center[0]
    matrix[1, 2] += new_height / 2.0 - image_center[1]

    rotated = cv2.warpAffine(
        image,
        matrix,
        (new_width, new_height),
        flags=cv2.INTER_LINEAR,
        borderMode=cv2.BORDER_CONSTANT,
        borderValue=(255, 255, 255),
    )

    return rotated, affine_point(matrix, center), angle_deg


def crop_with_padding(
    image: np.ndarray,
    cx: float,
    cy: float,
    width: int,
    height: int,
) -> np.ndarray:
    x1 = int(round(cx - width / 2))
    y1 = int(round(cy - height / 2))
    x2 = x1 + width
    y2 = y1 + height

    image_height, image_width = image.shape[:2]

    left = max(0, -x1)
    top = max(0, -y1)
    right = max(0, x2 - image_width)
    bottom = max(0, y2 - image_height)

    if any((left, top, right, bottom)):
        image = cv2.copyMakeBorder(
            image,
            top, bottom, left, right,
            cv2.BORDER_CONSTANT,
            value=(255, 255, 255),
        )
        x1 += left
        x2 += left
        y1 += top
        y2 += top

    return image[y1:y2, x1:x2].copy()


def add_scale_bar(image: np.ndarray, config: Config) -> np.ndarray:
    if not config.add_scale_bar:
        return image

    output = image.copy()
    height, width = output.shape[:2]

    bar_px = int(round(config.scale_bar_mm * config.target_pixels_per_mm))
    margin = int(round(0.60 * config.target_pixels_per_mm))
    thickness = max(5, int(round(0.10 * config.target_pixels_per_mm)))

    x2 = width - margin
    x1 = x2 - bar_px
    y2 = height - margin
    y1 = y2 - thickness
    pad = 8

    cv2.rectangle(
        output,
        (x1 - pad, y1 - pad),
        (x2 + pad, y2 + pad),
        (255, 255, 255),
        -1,
    )
    cv2.rectangle(
        output,
        (x1, y1),
        (x2, y2),
        (0, 0, 0),
        -1,
    )
    return output


def process_image(
    path: Path,
    calibration: dict[str, float],
    config: Config,
) -> tuple[np.ndarray, dict[str, float]]:
    image = read_image(path)

    p1 = (calibration["x1"], calibration["y1"])
    p2 = (calibration["x2"], calibration["y2"])
    center = (calibration["cx"], calibration["cy"])

    distance_px = math.hypot(p2[0] - p1[0], p2[1] - p1[1])
    pixels_per_mm = distance_px / config.calibration_mm

    if not math.isfinite(pixels_per_mm) or pixels_per_mm <= 0:
        raise RuntimeError(f"Invalid calibration for image: {path.name}")

    rotated, rotated_center, angle_deg = rotate_to_ruler_horizontal(
        image,
        p1,
        p2,
        center,
    )

    resize_factor = config.target_pixels_per_mm / pixels_per_mm
    resized = cv2.resize(
        rotated,
        None,
        fx=resize_factor,
        fy=resize_factor,
        interpolation=cv2.INTER_CUBIC if resize_factor > 1 else cv2.INTER_AREA,
    )

    crop_width_px = int(round(config.crop_width_mm * config.target_pixels_per_mm))
    crop_height_px = int(round(config.crop_height_mm * config.target_pixels_per_mm))

    cx = rotated_center[0] * resize_factor
    cy = rotated_center[1] * resize_factor

    crop = crop_with_padding(
        resized,
        cx,
        cy,
        crop_width_px,
        crop_height_px,
    )
    crop = add_scale_bar(crop, config)

    metadata = {
        "calibration_segment_px": distance_px,
        "original_pixels_per_mm": pixels_per_mm,
        "rotation_degrees": angle_deg,
        "resize_factor": resize_factor,
    }
    return crop, metadata


def config_hash(config: Config) -> str:
    payload = json.dumps(asdict(config), sort_keys=True, ensure_ascii=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:10]


def save_environment_versions(path: Path) -> None:
    lines = [
        f"WoundFrame: {__version__}",
        f"Python: {sys.version.split()[0]}",
        f"Platform: {platform.platform()}",
        f"numpy: {np.__version__}",
        f"opencv-python (cv2): {cv2.__version__}",
        f"matplotlib: {matplotlib.__version__}",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def build_panel(
    run_dir: Path,
    processed: dict[tuple[str, str], Path],
    config: Config,
) -> None:
    if not processed:
        return

    subjects = sorted(
        {subject for subject, _ in processed},
        key=natural_key,
    )
    days = sorted(
        {day for _, day in processed},
        key=timepoint_number,
    )

    nrows = len(subjects)
    ncols = len(days)
    max_label_length = max(len(subject) for subject in subjects)

    label_margin_in = min(4.0, max(1.8, 0.10 * max_label_length + 1.0))
    figure_width = label_margin_in + config.cell_width_in * ncols
    figure_height = 1.0 + config.cell_height_in * nrows

    figure, axes = plt.subplots(
        nrows,
        ncols,
        figsize=(figure_width, figure_height),
        squeeze=False,
    )

    for row_index, subject in enumerate(subjects):
        for col_index, day in enumerate(days):
            axis = axes[row_index, col_index]
            image_path = processed.get((subject, day))

            if image_path and image_path.exists():
                bgr = read_image(image_path)
                rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
                axis.imshow(rgb)
            else:
                axis.text(
                    0.5,
                    0.5,
                    "missing",
                    ha="center",
                    va="center",
                    color="0.55",
                    fontsize=9,
                    transform=axis.transAxes,
                )

            axis.set_xticks([])
            axis.set_yticks([])
            for spine in axis.spines.values():
                spine.set_visible(False)

            if row_index == 0:
                axis.set_title(
                    day.upper(),
                    fontsize=12,
                    fontweight="bold",
                    pad=12,
                )

            if col_index == 0:
                pretty_subject = (
                    subject.replace("_", " ").replace("-", " ").title()
                )
                axis.text(
                    -0.10,
                    0.5,
                    pretty_subject,
                    transform=axis.transAxes,
                    ha="right",
                    va="center",
                    fontsize=10,
                    clip_on=False,
                )

    figure.suptitle(
        config.panel_title,
        fontsize=15,
        fontweight="bold",
        y=0.985,
    )

    left_fraction = min(0.34, label_margin_in / figure_width)
    figure.subplots_adjust(
        left=left_fraction,
        right=0.985,
        top=0.94,
        bottom=0.04,
        wspace=config.wspace,
        hspace=config.hspace,
    )

    figure.savefig(
        run_dir / "wound_panel_all_subjects.png",
        dpi=300,
        facecolor="white",
        bbox_inches="tight",
        pad_inches=0.15,
    )
    figure.savefig(
        run_dir / "wound_panel_all_subjects.pdf",
        facecolor="white",
        bbox_inches="tight",
        pad_inches=0.15,
    )
    plt.close(figure)


def print_settings(config: Config) -> None:
    print("\n========== SETTINGS ==========")
    print(f"Calibration distance : {config.calibration_mm:g} mm")
    print(
        f"Crop                 : "
        f"{config.crop_width_mm:g} x {config.crop_height_mm:g} mm"
    )
    print(
        f"Scale bar            : {config.scale_bar_mm:g} mm "
        f"({'ON' if config.add_scale_bar else 'OFF'})"
    )
    print(f"Target resolution    : {config.target_pixels_per_mm:g} px/mm")
    print(f"Fullscreen           : {'YES' if config.fullscreen else 'NO'}")
    print(
        f"Panel cell size      : "
        f"{config.cell_width_in:g} x {config.cell_height_in:g} in"
    )
    print(f"Panel spacing        : W={config.wspace:g}, H={config.hspace:g}")
    print("==============================\n")


def run(args: argparse.Namespace, config: Config) -> Path:
    output_root = args.output_root.expanduser().resolve()
    cache_root = DEFAULT_CACHE_ROOT.resolve()
    output_root.mkdir(parents=True, exist_ok=True)
    cache_root.mkdir(parents=True, exist_ok=True)

    input_root = choose_input(args.input, cache_root, output_root).resolve()

    all_images = find_images(
        input_root,
        output_root=output_root,
        cache_root=cache_root,
    )
    if not all_images:
        raise RuntimeError("No supported image files were found.")

    manifest_rows, parsed, unparsed, dataset_hash = build_manifest(
        all_images,
        input_root,
    )
    if not parsed:
        raise RuntimeError(
            "Images were found, but no timepoints could be detected. "
            "Include a token such as Z0, Z2, Z5, Day4, or D6 in each filename "
            "or in its parent folder."
        )

    dataset_dir = (
        output_root
        / f"{safe_name(input_root.name)}_{dataset_hash}"
    )
    dataset_dir.mkdir(parents=True, exist_ok=True)

    manifest_path = dataset_dir / "input_manifest.csv"
    write_csv(manifest_path, manifest_rows)

    if unparsed:
        (dataset_dir / "unparsed_images.txt").write_text(
            "\n".join(image_key(p, input_root) for p in unparsed) + "\n",
            encoding="utf-8",
        )
    else:
        unparsed_path = dataset_dir / "unparsed_images.txt"
        if unparsed_path.exists():
            unparsed_path.unlink()

    calibration_path = dataset_dir / "calibration.csv"
    if args.recalibrate and calibration_path.exists():
        calibration_path.unlink()

    calibration = load_calibration(calibration_path)

    subjects = sorted({subject for _, subject, _ in parsed}, key=natural_key)
    days = sorted({day for _, _, day in parsed}, key=timepoint_number)

    print("========== AUTO-DETECTION ==========")
    print(f"Input root      : {input_root}")
    print(f"Valid images    : {len(parsed)}")
    print(f"Subjects        : {len(subjects)}")
    print(f"Timepoints      : {', '.join(day.upper() for day in days)}")
    print(f"Unparsed images : {len(unparsed)}")
    print(f"Dataset ID      : {dataset_hash}")
    print("====================================\n")

    show_info(
        "WoundFrame",
        (
            f"Valid images: {len(parsed)}\n"
            f"Subjects: {len(subjects)}\n"
            f"Timepoints: {', '.join(day.upper() for day in days)}\n\n"
            "For each new image:\n"
            "1. click ruler point A\n"
            f"2. click ruler point B exactly {config.calibration_mm:g} mm away\n"
            "3. click the wound center\n\n"
            "ENTER = accept | R = reset | ESC = skip"
        ),
    )

    for index, (path, _subject, _day) in enumerate(parsed, start=1):
        key = image_key(path, input_root)
        if key in calibration:
            continue

        clicks = collect_three_clicks(
            path,
            config,
            number=index,
            total=len(parsed),
        )
        if clicks is None:
            continue

        calibration[key] = clicks
        save_calibration(calibration_path, calibration)

    run_id = config_hash(config)
    run_dir = dataset_dir / "runs" / f"run_{run_id}"
    if run_dir.exists():
        shutil.rmtree(run_dir)
    crops_dir = run_dir / "standardized_crops"
    crops_dir.mkdir(parents=True, exist_ok=True)

    (run_dir / "settings.json").write_text(
        json.dumps(
            {
                "software_version": __version__,
                "dataset_id": dataset_hash,
                "config": asdict(config),
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )

    processed: dict[tuple[str, str], Path] = {}
    metadata_rows: list[dict[str, object]] = []
    duplicate_rows: list[dict[str, object]] = []

    duplicate_counter: dict[tuple[str, str], int] = {}

    for path, subject, day in parsed:
        key = image_key(path, input_root)
        if key not in calibration:
            continue

        crop, metadata = process_image(path, calibration[key], config)

        pair = (subject, day)
        occurrence = duplicate_counter.get(pair, 0) + 1
        duplicate_counter[pair] = occurrence

        filename = (
            f"{safe_name(subject)}_{day}_standardized.png"
            if occurrence == 1
            else f"{safe_name(subject)}_{day}_standardized_{occurrence}.png"
        )
        output_path = crops_dir / filename
        write_image(output_path, crop)

        if occurrence == 1:
            processed[pair] = output_path
        else:
            duplicate_rows.append(
                {
                    "subject": subject,
                    "timepoint": day,
                    "input_image": key,
                    "saved_crop": output_path.name,
                    "panel_policy": "first image retained in main panel",
                }
            )

        metadata_rows.append(
            {
                "input_image": key,
                "subject": subject,
                "timepoint": day,
                "output_crop": output_path.name,
                "calibration_mm": config.calibration_mm,
                "target_pixels_per_mm": config.target_pixels_per_mm,
                "crop_width_mm": config.crop_width_mm,
                "crop_height_mm": config.crop_height_mm,
                "scale_bar_mm": (
                    config.scale_bar_mm if config.add_scale_bar else 0
                ),
                **metadata,
            }
        )

    write_csv(run_dir / "processing_metadata.csv", metadata_rows)
    if duplicate_rows:
        write_csv(run_dir / "duplicates.csv", duplicate_rows)

    save_environment_versions(run_dir / "environment_versions.txt")
    build_panel(run_dir, processed, config)

    print(f"Output run       : {run_dir}")
    show_info(
        "Processing complete",
        f"Results were written to:\n{run_dir}",
    )
    return run_dir


def main() -> int:
    try:
        args = parse_args()
        config = config_from_args(args)
        print_settings(config)
        run(args, config)
        return 0
    except KeyboardInterrupt:
        print("\nCancelled by user.", file=sys.stderr)
        return 130
    except Exception as exc:
        details = traceback.format_exc()
        DEFAULT_ERROR_LOG.write_text(details, encoding="utf-8")
        show_error(
            "WoundFrame error",
            (
                f"{exc}\n\n"
                f"Full traceback saved to:\n{DEFAULT_ERROR_LOG}"
            ),
        )
        print(details, file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
