# WoundFrame

**WoundFrame** is an open-source Python workflow for scale-normalizing longitudinal wound photographs and assembling reproducible subject-by-timepoint image panels.


**Author:** Ștefan-Rareș Maxim  
**License:** BSD 3-Clause  
**Version:** 1.0.0

## How to cite

If you use WoundFrame in research, figures, analyses, presentations, software, or publications, please cite the software.

GitHub will automatically expose citation metadata from the included `CITATION.cff` file through its **Cite this repository** interface.

Suggested citation before a DOI is assigned:

> Maxim, Ștefan-Rareș. (2026). *WoundFrame: Reproducible scale-normalized wound image panels* (Version 1.0.0) [Computer software].

If a DOI is later assigned through Zenodo, prefer the DOI-based citation.


The tool was designed for preclinical wound-healing image series, but the workflow is generic: if each photograph contains an in-frame metric reference and the wound can be identified manually, the images can be standardized to the same physical field of view.

## What the tool does

For each photograph, the user makes **three clicks**:

1. calibration point **A** on an in-frame ruler or metric reference;
2. calibration point **B** at a known physical distance from A;
3. the **wound center**.

The script then:

- calculates the image-specific pixels/mm ratio;
- rotates the image using the calibration segment as the horizontal reference;
- rescales all images to a common pixels/mm value;
- extracts the same physical crop size around each wound;
- optionally adds a scale bar;
- detects timepoints automatically from filenames or parent folders;
- assembles a subject × timepoint panel;
- records the calibration coordinates, processing settings, software versions and SHA-256 hashes of the source images.

**Original image files are never modified.**

---

## Repository structure

```text
WoundFrame/
├── woundframe.py
├── run_windows.bat
├── requirements.txt
├── requirements-lock.txt
├── .gitignore
├── README.md
├── docs/
│   ├── IMAGE_PREPARATION.md
│   ├── USAGE.md
│   ├── OUTPUTS_AND_REPRODUCIBILITY.md
│   └── METHODS_TEXT.md
├── examples/
│   ├── README.md
│   └── example_file_names.txt
└── tests/
    └── test_filename_parsing.py
```

---

## Requirements

- Python **3.10+**
- Windows, macOS or Linux
- A graphical desktop session for the manual three-click calibration
- Python packages:
  - NumPy
  - OpenCV (`opencv-python`, **not** `opencv-python-headless`)
  - Matplotlib

Install the dependencies:

```bash
python -m pip install -r requirements.txt
```

For the exact versions used during preparation/testing of this release:

```bash
python -m pip install -r requirements-lock.txt
```

---

## Quick start on Windows

1. Download or clone this repository.
2. Install Python 3.10 or newer.
3. Open a terminal in the repository folder and run:

```bat
py -m pip install -r requirements.txt
```

4. Double-click:

```text
run_windows.bat
```

5. At:

```text
Use all defaults? [Y/n]:
```

press **Enter** to start immediately with the default parameters.

6. Select the ZIP archive or folder containing the photographs.
7. For every image that has not already been calibrated:
   - click ruler point A;
   - click ruler point B at the distance specified in the launcher;
   - click the wound center;
   - press **Enter** to accept.

Keyboard controls during calibration:

| Key | Action |
|---|---|
| `Enter` | accept the three selected points |
| `R` | clear the points and start that image again |
| `Esc` | skip the current image |

---

## Image naming

The photographs do **not** need to be organized into day folders. They can all be mixed in one directory.

Recommended naming:

```text
rat01-Z0.jpg
rat01-Z2.jpg
rat01-Z5.jpg

rat02-Z0.jpg
rat02-Z2.jpg
rat02-Z5.jpg
```

The script automatically detects:

```text
Z0
Z2
Z5
Z10
Day4
day_4
D6
```

and normalizes these to:

```text
z0
z2
z5
z10
z4
z6
```

The remaining filename is treated as the subject identifier.

Examples:

| Filename | Subject | Timepoint |
|---|---|---|
| `rat01-Z0.jpg` | `rat01` | `Z0` |
| `CAP1-Z5.JPG` | `cap1` | `Z5` |
| `animal_03_day4.png` | `animal-03` | `Z4` |
| `capd-t1a-z2.jpg` | `capd-t1a` | `Z2` |

Timepoints may also be stored as parent folders:

```text
images/
├── Z0/
│   ├── rat01.jpg
│   └── rat02.jpg
├── Z2/
│   ├── rat01.jpg
│   └── rat02.jpg
└── Z5/
    ├── rat01.jpg
    └── rat02.jpg
```

See [`docs/IMAGE_PREPARATION.md`](docs/IMAGE_PREPARATION.md) for acquisition recommendations.

---

## Default processing parameters

| Parameter | Default |
|---|---:|
| Calibration segment | 20 mm |
| Crop width | 20 mm |
| Crop height | 20 mm |
| Target resolution | 50 px/mm |
| Scale bar | 5 mm |
| Fullscreen calibration | yes |
| Panel cell width | 2.75 in |
| Panel cell height | 2.75 in |
| Horizontal panel spacing | 0.25 |
| Vertical panel spacing | 0.40 |

The calibration distance is **not** the crop size. It is simply the known real-world distance between the two ruler points selected by the user.

For example, if `calibration-mm = 20`, the two clicks may be:

```text
0 cm -> 2 cm
1 cm -> 3 cm
2 cm -> 4 cm
```

A longer accurately identifiable calibration segment generally reduces the relative error caused by a few pixels of clicking uncertainty.

---

## Command-line usage

The Windows launcher is optional. The script can be run directly:

```bash
python woundframe.py
```

Or with an explicit input folder:

```bash
python woundframe.py --input "C:\data\wound_photos"
```

Or a ZIP archive:

```bash
python woundframe.py --input "C:\data\wound_photos.zip"
```

Example with custom parameters:

```bash
python woundframe.py \
  --input wound_photos \
  --calibration-mm 20 \
  --crop-width-mm 25 \
  --crop-height-mm 25 \
  --scale-bar-mm 5 \
  --target-ppmm 50 \
  --fullscreen yes \
  --wspace 0.30 \
  --hspace 0.45
```

Show all options:

```bash
python woundframe.py --help
```

---

## Reusing calibration

Click coordinates are stored in:

```text
wound_panel_output/<dataset_id>/calibration.csv
```

If the same dataset is run again, already calibrated images are skipped automatically.

This means you can change:

- crop size;
- scale-bar length;
- target pixels/mm;
- panel spacing;
- panel cell dimensions;

without clicking all images again.

To deliberately discard the saved clicks and recalibrate:

```bash
python woundframe.py --input wound_photos --recalibrate
```

The Windows launcher exposes the same choice under:

```text
Reuse saved calibration? yes/no [yes]:
```

---

## Reproducibility model

Each discovered source image receives a SHA-256 hash. A dataset ID is generated from the relative image paths and hashes.

Each processing configuration receives a separate run ID.

The resulting structure is:

```text
wound_panel_output/
└── dataset_<hash>/
    ├── input_manifest.csv
    ├── calibration.csv
    ├── unparsed_images.txt        # only when needed
    └── runs/
        └── run_<settings_hash>/
            ├── settings.json
            ├── environment_versions.txt
            ├── processing_metadata.csv
            ├── duplicates.csv     # only when needed
            ├── wound_panel_all_subjects.png
            ├── wound_panel_all_subjects.pdf
            └── standardized_crops/
                └── ...
```

This separates:

- **source identity**;
- **manual calibration**;
- **processing configuration**;
- **generated output**.

See [`docs/OUTPUTS_AND_REPRODUCIBILITY.md`](docs/OUTPUTS_AND_REPRODUCIBILITY.md).

---

## Scientific-use considerations

The workflow standardizes scale and field of view, but it cannot repair poor acquisition geometry.

For quantitative or publication use:

- place the metric reference in approximately the **same plane as the wound**;
- keep the camera sensor as parallel to the wound surface as practical;
- minimize perspective distortion;
- use consistent lighting, exposure, focus and white balance;
- do not selectively edit individual images;
- retain the original photographs unchanged;
- document any global image adjustments if they are made outside this tool.

If the ruler is substantially above or below the wound plane, pixels/mm measured from the ruler may not accurately represent pixels/mm at the wound surface.

---

## Duplicate and unparsed files

If two images resolve to the same subject and timepoint, both crops are preserved but the first image in deterministic filename order is used in the main panel. Duplicates are reported in:

```text
duplicates.csv
```

Images for which no timepoint can be detected are listed in:

```text
unparsed_images.txt
```

They are not included in the panel.

---

## Testing

Basic filename/timepoint parsing tests are included:

```bash
python -m unittest discover -s tests -v
```

---

## Citation / methods

A concise methods paragraph that can be adapted for a manuscript is provided in:

[`docs/METHODS_TEXT.md`](docs/METHODS_TEXT.md)

Before publishing the repository, consider adding:

- the authors/contributors;
- institutional affiliation if appropriate;
- a software license;
- a DOI/Zenodo archive for the release used in the manuscript.

---

## Limitations

- Calibration is manual.
- Wound-center placement is manual.
- Perspective correction is not performed.
- The program assumes a single linear metric calibration is representative of the wound plane.
- The tool standardizes image presentation; it does not automatically segment or measure wound area.
- Very inconsistent acquisition angles or severe perspective distortion should be corrected at the acquisition stage, not computationally hidden.

---

## Version

`1.0.0`

## License

WoundFrame is distributed under the **BSD 3-Clause License**.

You may use, modify, and redistribute the software, including in other open-source or commercial projects, provided that the BSD license conditions are followed.

For academic and scientific use, please also cite WoundFrame using the repository's `CITATION.cff` metadata.

Copyright © 2026 Ștefan-Rareș Maxim.
