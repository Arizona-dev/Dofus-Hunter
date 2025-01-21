import re
import json
import cv2
import pytesseract
import numpy as np
import os
import matplotlib.pyplot as plt
from scipy.signal import find_peaks
from PIL import Image, ImageEnhance, ImageFilter, ImageDraw, ImageFont

pytesseract.pytesseract.tesseract_cmd = r"C:\Program Files\Tesseract-OCR\tesseract.exe"

# Regex to fix bracket misreads:
fix_brackets_pattern = re.compile(r"(\[-?\d{1,2},-?\d{1,2})1")

# Regex patterns for parsing data
steps_pattern = re.compile(r"^\s*ÉTAPE\s*:\s*(\d+)\s*/\s*(\d+)\s*$", re.IGNORECASE)
startPos_pattern = re.compile(r"^Départ\s+(\[[^\]]+\])$", re.IGNORECASE)
tries_pattern = re.compile(r"^(\d+)\s+essais?\s+restants?", re.IGNORECASE)
unwanted_pattern = re.compile(
    r"(EN COURS|ENCOURS|ENCcouRs|EN \(COURS|VALIDER|™|VALIDÉ|[0-9]+)", re.IGNORECASE
)
coordinate_pattern = re.compile(r"(-?\d+)\s*,\s*(-?\d+)")


def sanitize_hint_text(text):
    """
    Sanitize hint text by removing unwanted characters and normalizing whitespace.
    """
    # Remove specific special characters that shouldn't be in hints
    chars_to_remove = '«»"`™=;&'
    for char in chars_to_remove:
        text = text.replace(char, "")

    # Replace multiple spaces with a single space
    text = " ".join(text.split())
    return text.strip()


def split_merged_lines(line):
    """
    Split a merged line into separate logical segments.
    Returns a list of lines.
    """
    # First, clean up any special characters or OCR artifacts
    line = re.sub(r"[€™Ÿÿ<>]", "", line)

    # Split at any occurrence of "essais restants" with optional prefix
    line = re.sub(
        r"\s*(?:in\s+)?(?:\d+\s+)?essais?\s+restants?.*$",
        "\n",
        line,
        flags=re.IGNORECASE,
    )

    # Known breaking points that should be on separate lines
    break_points = [
        (r"(ÉTAPE\s*:\s*\d+/\d+)(.+)", r"\1\n\2"),  # Split after ÉTAPE section
        (r"(\[-?\d+,\s*-?\d+\])\s*([A-ZÀ-Ú])", r"\1\n\2"),  # Split after coordinates
        (r"(\))\s+([A-ZÀ-Ú])", r"\1\n\2"),  # Split after closing parenthesis
        (r"([a-zà-ú])\s+(EN\s*COURS)", r"\1\n\2"),  # Split before EN COURS
        (r"(EN\s*COURS)\s+([A-ZÀ-Ú])", r"\1\n\2"),  # Split after EN COURS
    ]

    result = line
    for pattern, replacement in break_points:
        result = re.sub(pattern, replacement, result, flags=re.IGNORECASE)

    # Split into lines and clean each line
    lines = []
    for line in result.split("\n"):
        line = line.strip()
        if line:
            # Remove single characters that are likely OCR artifacts
            if not re.match(r"^[a-zà-ú0-9+]$", line, re.IGNORECASE):
                # Remove any standalone "in"
                line = re.sub(r"(?:^|\s)in(?:\s|$)", " ", line).strip()
                # Remove special characters from the beginning of the line
                # line = re.sub(r'^[^a-zA-ZÀ-ÿ0-9\[\(\s]+', '', line).strip()
                if line:  # Only append non-empty lines
                    lines.append(line)

    print(f"DEBUG - Split line '{line}' into: {lines}")

    return lines


def parse_ocr_output(lines):
    """Extract Étape, Départ, Zone (the next line after Départ), Hints, and Remaining Tries."""

    # Preprocess lines to handle merged content
    processed_lines = []
    for line in lines:
        processed_lines.extend(split_merged_lines(line))

    data = {
        "start_pos_zone": None,
        "start_pos_x": None,
        "start_pos_y": None,
        "step": None,
        "total_steps": None,
        "remaining_tries": None,
        "hints": [],
        "last_hint_pos_x": None,
        "last_hint_pos_y": None,
    }

    expect_startPosZone = False
    collecting_hints = False
    current_hint = None

    for line in processed_lines:
        line = line.strip()
        if not line:
            continue

        print(f"Processing line: {line}")

        match = re.search(r"Départ\s+(\[[^\]]+\])", line)
        if match:
            line = f"Départ {match.group(1)}"

        # 1) Étape
        m_steps = steps_pattern.search(line)
        if m_steps:
            data["step"] = int(m_steps.group(1))  # Extract x
            data["total_steps"] = int(m_steps.group(2))  # Extract y
            continue

        # Remove any numeric prefix that might interfere with parsing
        line = re.sub(r"^\d+\s+", "", line)

        # 2) Départ
        if "Départ" in line:
            # Remove leading digit before "Départ"
            line = re.sub(r"^\d+\s*Départ", "Départ", line)

        m_startPos = startPos_pattern.search(line)
        if m_startPos:
            coords = m_startPos.group(1).strip("[]")  # Remove square brackets
            try:
                x, y = map(int, coords.split(","))
                data["start_pos_x"] = x
                data["start_pos_y"] = y
            except ValueError:
                data["start_pos_x"] = None
                data["start_pos_y"] = None
            expect_startPosZone = True
            continue

        # 3) Text under Départ (startPosZone)
        if expect_startPosZone:
            if "start_pos_zone" not in data or data["start_pos_zone"] is None:
                data["start_pos_zone"] = ""

            # Only add text up to the closing parenthesis
            parenthesis_match = re.search(r"([^)]*\))", line)
            if parenthesis_match:
                data["start_pos_zone"] += f" {parenthesis_match.group(1).strip()}"
                expect_startPosZone = False
                collecting_hints = True
            else:
                data["start_pos_zone"] += f" {line.strip()}"
            continue

        # 4) Remaining Tries
        m_tries = tries_pattern.search(line)
        if m_tries:
            data["remaining_tries"] = int(m_tries.group(1))
            if current_hint:
                sanitized_hint = sanitize_hint_text(current_hint)
                if sanitized_hint:
                    data["hints"].append({"hintText": sanitized_hint})
                current_hint = None
            collecting_hints = False
            continue

        # 5) Hints
        if collecting_hints:
            print(f"DEBUG: Processing potential hint line: {line}")

            # Remove unwanted patterns but keep the rest
            sanitized_line = unwanted_pattern.sub("", line).strip()

            print(f"DEBUG: Sanitized line: {sanitized_line}")

            # Remove specific unwanted single characters
            if re.match(r"^[&9B?]$", sanitized_line):
                print(f"DEBUG: Skipping single character line: {sanitized_line}")
                continue

            if sanitized_line:
                whitelist = ["Ankama", "Dofus"]  # Dofus is whitelisted
                blacklist = []
                blacklist_alone = [
                    "Q",
                    "ff",
                    "S",
                    "'",
                    "À",
                    "?",
                    "Dofus",
                ]

                # First remove standalone blacklisted words from the line, but protect whitelisted words
                cleaned_line = sanitized_line
                words = cleaned_line.split()
                cleaned_words = [
                    word
                    for word in words
                    if not (
                        word in blacklist_alone
                        and not any(white_word in word for white_word in whitelist)
                    )
                ]
                cleaned_line = " ".join(cleaned_words)

                # Then remove blacklisted words from the line, except whitelisted ones
                for word in blacklist:
                    if not any(white_word in word for white_word in whitelist):
                        cleaned_line = cleaned_line.replace(word, "")

                # Split line based on capitalized words
                def is_split_word(word, index):
                    return (
                        index > 0
                        and word[0].isupper()  # Capitalized word
                        and word not in whitelist  # Not whitelisted
                    )

                words = cleaned_line.split()
                segments = []
                segment = []

                for i, word in enumerate(words):
                    if is_split_word(word, i):
                        segments.append(" ".join(segment))
                        segment = [word]  # Start new segment
                    else:
                        segment.append(word)
                # Add the last segment
                if segment:
                    segments.append(" ".join(segment))

                sanitized_segments = [
                    sanitize_hint_text(segment) for segment in segments
                ]
                for segment in sanitized_segments:
                    # Sanitize the segment
                    cleaned_line = sanitize_hint_text(segment)
                    print(f"DEBUG: Cleaned segment: {cleaned_line}")

                    # If we have a cleaned line, always try to append it first
                    if cleaned_line:
                        if current_hint:
                            current_hint += f" {cleaned_line}"
                            print(f"DEBUG: Appending to current hint: {current_hint}")
                        else:
                            current_hint = cleaned_line
                            print(f"DEBUG: Started first hint: {current_hint}")

                        # Now check for splits after appending
                        words = current_hint.split()
                        split_points = []
                        for i, word in enumerate(words):
                            if (
                                i > 0
                                and word[0].isupper()
                                and not any(
                                    white_word in word for white_word in whitelist
                                )
                                and word not in blacklist_alone
                            ):
                                # Found a split point, save current hint and start new one
                                first_part = " ".join(words[:i])
                                second_part = " ".join(words[i:])

                                # Save the first part
                                sanitized_hint = sanitize_hint_text(first_part)
                                if sanitized_hint:
                                    data["hints"].append({"hintText": sanitized_hint})
                                print(f"DEBUG: Saved split hint: {sanitized_hint}")

                                # Start new hint with remaining part
                                current_hint = second_part
                                print(
                                    f"DEBUG: Started new hint from split: {current_hint}"
                                )
                                break  # Exit after first split

    # Handle last hint if exists
    if current_hint:
        sanitized_hint = sanitize_hint_text(current_hint)
        if sanitized_hint:
            data["hints"].append({"hintText": sanitized_hint})

        print(f"DEBUG: Saved final hint: {sanitized_hint}")

    return data


def read_hunt_from_screenshot(screenshot, retries=3):
    """
    Process a screenshot to extract hunt information including player direction.

    Args:
        screenshot: PIL Image object containing the hunt screenshot
        retries (int): Number of retry attempts if processing fails

    Returns:
        str: JSON string containing parsed hunt data or error message
    """
    for attempt in range(retries):
        try:
            # Preprocess and get four separate images
            header_img, zone_img, hint_img, footer_img = preprocess_image(screenshot)

            directions = read_direction_arrows(screenshot)

            # Configure pytesseract
            custom_config = r"--oem 1 --psm 3 -l fra"  # French language

            # Process header section
            header_data = pytesseract.image_to_data(
                header_img, config=custom_config, output_type=pytesseract.Output.DICT
            )

            # Process zone section
            zone_data = pytesseract.image_to_data(
                zone_img, config=custom_config, output_type=pytesseract.Output.DICT
            )

            # Process hints section
            hints_data = pytesseract.image_to_data(
                hint_img, config=custom_config, output_type=pytesseract.Output.DICT
            )

            # Process footer section
            footer_data = pytesseract.image_to_data(
                footer_img, config=custom_config, output_type=pytesseract.Output.DICT
            )

            # Debug - print all recognized text blocks for each section
            sections = {
                "Header": header_data,
                "Zone": zone_data,
                "Hints": hints_data,
                "Footer": footer_data,
            }

            lines_by_section = {}
            for section_name, ocr_data in sections.items():
                current_line = []
                current_line_num = -1
                lines = []

                print(f"\nDebug - {section_name} section OCR blocks:")
                for i in range(len(ocr_data["text"])):
                    if (
                        int(ocr_data["conf"][i]) > 0
                    ):  # Filter out low confidence results
                        text = ocr_data["text"][i].strip()
                        line_num = ocr_data["line_num"][i]
                        conf = ocr_data["conf"][i]

                        print(
                            f"Debug - OCR block: text='{text}', confidence={conf}, line={line_num}"
                        )

                        if text:  # Only process non-empty text
                            if line_num != current_line_num:
                                if current_line:
                                    lines.append(" ".join(current_line))
                                current_line = [text]
                                current_line_num = line_num
                            else:
                                current_line.append(text)

                # Add the last line if it exists
                if current_line:
                    lines.append(" ".join(current_line))

                lines_by_section[section_name.lower()] = lines
                print(f"Debug - Extracted {section_name} lines: {lines}")

            # Combine all lines in the correct order
            all_lines = (
                lines_by_section["header"]
                + lines_by_section["zone"]
                + lines_by_section["hints"]
                + lines_by_section["footer"]
            )

            # Parse combined OCR output
            hunt_data = parse_ocr_output(all_lines)

            # Debug logging for direction assignment
            print(f"Debug - hunt_data has hints?: {'hints' in hunt_data}")
            print(f"Debug - hints not empty?: {bool(hunt_data.get('hints'))}")
            print(f"Debug - directions type: {type(directions)}")
            print(f"Debug - directions content: {directions}")

            # Parse directions if it's a string
            if isinstance(directions, str):
                try:
                    directions = json.loads(directions)
                    print(f"Debug - parsed directions: {directions}")
                except json.JSONDecodeError as e:
                    print(f"Debug - failed to parse directions: {e}")

            # Add directions to hints in order
            if (
                "hints" in hunt_data
                and hunt_data["hints"]
                and isinstance(directions, list)
            ):
                print(f"Debug - Number of hints: {len(hunt_data['hints'])}")
                print(f"Debug - Number of directions: {len(directions)}")

                for idx, hint in enumerate(hunt_data["hints"]):
                    print(f"Debug - Processing hint {idx}")
                    if idx < len(directions):
                        hint["hintDirection"] = directions[idx]
                        print(
                            f"Debug - Assigned direction {directions[idx]} to hint {idx}"
                        )
                    else:
                        print(f"Debug - No direction available for hint {idx}")

            # Log the last hint
            if "hints" in hunt_data and hunt_data["hints"]:
                print(
                    f"Last hint: {json.dumps(hunt_data['hints'][-1], indent=2, ensure_ascii=False)}"
                )

            return json.dumps(hunt_data, indent=2, ensure_ascii=False)

        except Exception as e:
            if attempt < retries - 1:
                print(f"Attempt {attempt + 1} failed with error: {e}")
                print("Retrying...")
                continue

            error_response = {
                "error": "Failed to process screenshot",
                "details": str(e),
            }
            return json.dumps(error_response, ensure_ascii=False)


# Player Coordinates
###############################################


def preprocess_image(
    image: Image.Image,
    debug: bool = True,
    left_margin_percent: float = 0.025,
    right_margin_percent: float = 0.38,
    crop_width_percent: float = 0.1,
) -> tuple[Image.Image, Image.Image, Image.Image]:
    """
    Split the game image into three parts: header (ETAPE), hints section, and footer (essais).
    Also crops the left side of the hints section.

    Args:
        image: Input PIL Image
        debug: Whether to save debug images
        left_margin_percent: Percentage of image width to remove from left for hints
        crop_width_percent: Additional percentage of width to remove from left for hints

    Returns:
        Tuple of (header_image, hints_image, footer_image)
    """
    if debug:
        debug_dir = "debug_ocr"
        os.makedirs(debug_dir, exist_ok=True)
        image.save(os.path.join(debug_dir, "1_original.png"))

    # Ensure we have the correct image format and convert to array
    if image.mode != "RGB":
        image = image.convert("RGB")
    img_array = np.array(image)
    height, width = img_array.shape[:2]

    # Convert to grayscale without using cv2.cvtColor
    gray = np.array(image.convert("L"))

    if debug:
        Image.fromarray(gray).save(os.path.join(debug_dir, "2a_grayscale.png"))

    # Calculate row-wise mean intensity
    row_means = np.mean(gray, axis=1)

    # Smooth the intensity profile
    window_size = 3
    row_means_smooth = np.convolve(
        row_means, np.ones(window_size) / window_size, mode="same"
    )

    # Find peaks (white lines)
    peaks, properties = find_peaks(
        row_means_smooth,
        distance=10,  # Minimum distance between peaks
        prominence=5,  # Minimum prominence
        width=1,
    )  # Expected width of peaks

    # Filter peaks by height range (40-50)
    peak_heights = row_means_smooth[peaks]
    valid_peaks = peaks[np.where((peak_heights >= 40) & (peak_heights <= 50))[0]]

    if debug:
        plt.figure(figsize=(15, 10))
        plt.subplot(211)
        plt.plot(row_means_smooth, label="Smoothed Intensity")
        plt.axhline(y=40, color="r", linestyle="--", label="Min Height (40)")
        plt.axhline(y=50, color="g", linestyle="--", label="Max Height (50)")
        plt.plot(peaks, row_means_smooth[peaks], "rx", label="All Peaks")
        plt.plot(
            valid_peaks, row_means_smooth[valid_peaks], "go", label="Line Peaks (40-50)"
        )
        plt.title("Row-wise Mean Intensity")
        plt.legend()

        # Create a copy for visualization
        debug_img = img_array.copy()
        for y in valid_peaks:
            cv2.line(debug_img, (0, y), (width, y), (0, 255, 0), 2)
        Image.fromarray(debug_img).save(
            os.path.join(debug_dir, "2b_detected_splits.png")
        )

        plt.subplot(212)
        plt.plot(np.gradient(row_means_smooth), label="Gradient")
        plt.title("Intensity Gradient")
        plt.legend()
        plt.savefig(os.path.join(debug_dir, "2c_intensity_analysis.png"))
        plt.close()

    if len(valid_peaks) < 2:
        raise ValueError(
            f"Could not detect enough horizontal lines (found {len(valid_peaks)})"
        )

    # Sort peaks by position
    valid_peaks = sorted(valid_peaks)

    # Get the splits
    header_split = valid_peaks[1]
    zone_split = valid_peaks[2]

    # For footer, look for the last significant intensity change
    lower_third_start = height * 2 // 3
    lower_means = row_means_smooth[lower_third_start:]
    lower_gradient = np.gradient(lower_means)
    significant_changes = np.where(np.abs(lower_gradient) > np.std(lower_gradient) * 2)[
        0
    ]

    if len(significant_changes) > 0:
        footer_split = lower_third_start + significant_changes[0]
    else:
        footer_split = valid_peaks[-1]

    # Add minimal padding
    padding = 10
    header_split += padding
    zone_split += padding
    footer_split += padding

    # Create the section
    header_img = Image.fromarray(img_array[:header_split])
    zone_img = Image.fromarray(img_array[header_split:zone_split])
    hints_img = Image.fromarray(img_array[zone_split:footer_split])
    footer_img = Image.fromarray(img_array[footer_split:])

    if debug:
        header_img.save(os.path.join(debug_dir, "3_header.png"))
        zone_img.save(os.path.join(debug_dir, "4_zone.png"))
        hints_img.save(os.path.join(debug_dir, "5_hints.png"))
        footer_img.save(os.path.join(debug_dir, "6_footer.png"))

    # Crop the left and right side of the hints section
    hints_array = np.array(hints_img)
    hints_width = hints_array.shape[1]
    left_margin = int(hints_width * left_margin_percent)
    right_end = int(hints_width * (1 - right_margin_percent))
    crop_width = int(hints_width * crop_width_percent)
    hints_array = hints_array[:, (left_margin + crop_width) : right_end]

    # Convert back to PIL Image ensuring proper format
    if len(hints_array.shape) == 3:
        hints_img = Image.fromarray(hints_array, "RGB")
    else:
        hints_img = Image.fromarray(hints_array, "L")

    if debug:
        hints_img.save(os.path.join(debug_dir, "4_hints_cropped.png"))

        with open(os.path.join(debug_dir, "debug_info.txt"), "w") as f:
            f.write(f"Original image size: {width}x{height}\n")
            f.write(f"Header split at y={header_split}\n")
            f.write(f"Zone split at y={zone_split}\n")
            f.write(f"Footer split at y={footer_split}\n")
            f.write(f"Number of total peaks: {len(peaks)}\n")
            f.write(f"Number of valid peaks (40-50): {len(valid_peaks)}\n")
            f.write(f"Left margin cropped: {left_margin + crop_width} pixels\n")
            f.write(f"Right end: {right_end} pixels\n")

    return (
        header_img,
        zone_img,
        hints_img,
        footer_img,
    )


def preprocess_image_pos(image, debug: bool = True):
    """
    Preprocess image for position OCR with debug output for each step.
    """
    if debug:
        debug_dir = "debug_ocr_pos"
        os.makedirs(debug_dir, exist_ok=True)
        image.save(os.path.join(debug_dir, "1_original.png"))

    # Convert to RGB if needed
    if image.mode != "RGB":
        image = image.convert("RGB")
        if debug:
            image.save(os.path.join(debug_dir, "2_rgb.png"))
            with open(os.path.join(debug_dir, "debug_info.txt"), "w") as f:
                f.write(f"Original mode: {image.mode}\n")
                f.write(f"Original size: {image.size}\n")

    # Resize for better OCR
    target_height = 800  # Reduced from 1400
    aspect_ratio = image.width / image.height
    target_width = int(target_height * aspect_ratio)
    image = image.resize((target_width, target_height), Image.Resampling.LANCZOS)

    if debug:
        image.save(os.path.join(debug_dir, "3_resized.png"))
        with open(os.path.join(debug_dir, "debug_info.txt"), "a") as f:
            f.write(f"\nAfter resize:\n")
            f.write(f"Target height: {target_height}\n")
            f.write(f"Aspect ratio: {aspect_ratio:.3f}\n")
            f.write(f"New size: {image.size}\n")

    # Convert to grayscale
    image = image.convert("L")
    if debug:
        image.save(os.path.join(debug_dir, "4_grayscale.png"))

    # Invert image (for white text on black background)
    image = Image.eval(image, lambda x: 255 - x)
    if debug:
        image.save(os.path.join(debug_dir, "5_inverted.png"))

    # Add padding
    padding = int(target_height * 0.15)
    new_size = (target_width + 2 * padding, target_height + 2 * padding)
    padded_image = Image.new("L", new_size, 255)
    padded_image.paste(image, (padding, padding))
    image = padded_image

    if debug:
        image.save(os.path.join(debug_dir, "6_padded.png"))
        with open(os.path.join(debug_dir, "debug_info.txt"), "a") as f:
            f.write(f"\nPadding:\n")
            f.write(f"Padding size: {padding} pixels\n")
            f.write(f"Padded size: {new_size}\n")

    # Enhance contrast and sharpen
    enhancer = ImageEnhance.Contrast(image)
    image = enhancer.enhance(2.0)
    if debug:
        image.save(os.path.join(debug_dir, "7_contrast.png"))

    image = image.filter(ImageFilter.SHARPEN)
    if debug:
        image.save(os.path.join(debug_dir, "8_sharpened.png"))

    # Threshold
    image = image.point(lambda x: 0 if x < 160 else 255)
    if debug:
        image.save(os.path.join(debug_dir, "9_threshold.png"))
        with open(os.path.join(debug_dir, "debug_info.txt"), "a") as f:
            f.write(f"\nThreshold:\n")
            f.write(f"Threshold value: 160\n")

    # Convert back to RGB
    final_image = image.convert("RGB")
    if debug:
        final_image.save(os.path.join(debug_dir, "10_final.png"))
        with open(os.path.join(debug_dir, "debug_info.txt"), "a") as f:
            f.write(f"\nFinal:\n")
            f.write(f"Final size: {final_image.size}\n")
            f.write(f"Final mode: {final_image.mode}\n")

    return final_image


def process_coordinates_image(screenshot):
    """Extract coordinates from screenshot using OCR"""
    try:
        # Process image
        img = Image.fromarray(screenshot)
        preprocessed_img = preprocess_image_pos(img)

        # Extract text with OCR
        config = r"--oem 3 --psm 7 -c tessedit_char_whitelist=0123456789,-"
        text = pytesseract.image_to_string(preprocessed_img, config=config).strip()
        print(text)
        # Extract coordinates
        coordinates = []
        for match in re.finditer(r"(-?\d+)\s*,\s*(-?\d+)", text):
            x, y = match.groups()
            try:
                coordinates.append({"x": int(x), "y": int(y)})
            except ValueError:
                continue

        return {"success": bool(coordinates), "coordinates": coordinates}

    except Exception as e:
        return {"success": False, "error": str(e), "coordinates": []}


# if __name__ == "__main__":
#     result3 = process_coordinates_image("pos7.png")
#     print(json.dumps(result3, indent=2))


# DETECT DIRECTION
###########################################################


def determine_orientation(template):
    h, w = template.shape
    aspect_ratio = w / h

    # Use aspect ratio to determine orientation
    if aspect_ratio > 1:  # Wider than tall
        return "horizontal"
    else:  # Taller than wide
        return "vertical"


def calculate_perpendicular_masses(template, orientation):
    h, w = template.shape

    if orientation == "horizontal":
        left_mass = np.sum(template[:, : w // 2])
        right_mass = np.sum(template[:, w // 2 :])
        return left_mass, right_mass
    else:  # Vertical
        top_mass = np.sum(template[: h // 2, :])
        bottom_mass = np.sum(template[h // 2 :, :])
        return top_mass, bottom_mass


def determine_arrow_direction_weight(template):
    # Step 1: Determine orientation (horizontal or vertical)
    orientation = determine_orientation(template)

    # Step 2: Calculate perpendicular masses
    if orientation == "horizontal":
        left_mass, right_mass = calculate_perpendicular_masses(template, orientation)
        if left_mass > right_mass:
            return 4
        else:
            return 0
    else:  # Vertical
        top_mass, bottom_mass = calculate_perpendicular_masses(template, orientation)
        if top_mass > bottom_mass:
            return 6
        else:
            return 2


def determine_arrow_direction_combined(template):
    # Use weight-based determination
    weight_direction = determine_arrow_direction_weight(template)

    # Optionally, combine with other methods for robustness (like diagonal or scoring methods)
    return weight_direction


def extract_arrow_templates(binary_image):
    contours, _ = cv2.findContours(
        binary_image, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
    )
    templates = []

    for contour in contours:
        x, y, w, h = cv2.boundingRect(contour)
        if w > 10 and h > 10:  # Minimum size threshold
            template = binary_image[y : y + h, x : x + w]
            templates.append((template, x, y, w, h))

    return sorted(templates, key=lambda x: x[2])  # Sort by y-coordinate


def save_debug_image(template, direction, i):
    h, w = template.shape
    scale = 3  # Scale factor for resizing debug image

    # Resize the template for better visibility
    debug_image = cv2.resize(
        template, (w * scale, h * scale), interpolation=cv2.INTER_NEAREST
    )
    debug_image = cv2.cvtColor(debug_image, cv2.COLOR_GRAY2BGR)

    if direction in ["up", "down"]:
        # Draw horizontal cut for "up" and "down" (perpendicular to arrow's orientation)
        cv2.line(
            debug_image,
            (0, (h // 2) * scale),
            (w * scale, (h // 2) * scale),
            (0, 255, 0),
            2,
        )
    else:  # "left" or "right"
        # Draw vertical cut for "left" and "right" (perpendicular to arrow's orientation)
        cv2.line(
            debug_image,
            ((w // 2) * scale, 0),
            ((w // 2) * scale, h * scale),
            (0, 255, 0),
            2,
        )

    cv2.putText(
        debug_image,
        f"{direction}",
        (10, 30),
        cv2.FONT_HERSHEY_SIMPLEX,
        1.0,  # Increased font size
        (0, 0, 255),
        2,
    )
    cv2.imwrite(f"debug_template_{i}.png", debug_image)


def read_direction_arrows(pil_image):
    try:
        input_image = cv2.cvtColor(np.array(pil_image), cv2.COLOR_RGB2BGR)

        # Ensure the input image is not empty
        if input_image is None or input_image.size == 0:
            raise ValueError("Invalid input: 'image' is empty or corrupted.")

        # Convert to grayscale and binarize
        gray = cv2.cvtColor(input_image, cv2.COLOR_BGR2GRAY)
        _, binary = cv2.threshold(gray, 240, 255, cv2.THRESH_BINARY)

        # Define search region
        left_margin = int(input_image.shape[1] * 0.03)
        search_width = int(input_image.shape[1] * 0.1)
        search_region = binary[:, left_margin : left_margin + search_width]

        # Extract templates
        templates = extract_arrow_templates(search_region)

        arrows = []
        debug_img = input_image.copy()

        for i, (template, x, y, w, h) in enumerate(templates):
            print(f"\nAnalyzing template {i}:")

            direction = determine_arrow_direction_combined(template)
            arrows.append(direction)

            # Save individual debug image with cut line
            save_debug_image(template, direction, i)

            actual_x = left_margin + x
            cv2.rectangle(
                debug_img, (actual_x, y), (actual_x + w, y + h), (0, 255, 0), 2
            )
            cv2.putText(
                debug_img,
                f"{direction}",
                (actual_x, y - 10),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.5,
                (255, 0, 0),
                1,
            )

        # Save the debug image with all detected arrows
        cv2.imwrite("debug_arrows.png", debug_img)
        print(f"\nFinal arrows: {arrows}")

        return arrows

    except Exception as e:
        print(f"Error: {str(e)}")
        return json.dumps({"error": f"Arrow detection failed: {str(e)}"})
