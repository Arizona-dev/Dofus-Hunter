import asyncio
import re
import json
import winocr
from PIL import Image, ImageEnhance

# Regex to fix bracket misreads:
fix_brackets_pattern = re.compile(r"(\[-?\d{1,2},-?\d{1,2})1")

# Regex patterns for parsing data
steps_pattern = re.compile(r"^\s*ÉTAPE\s*:\s*(\d+)\s*/\s*(\d+)\s*$", re.IGNORECASE)
startPos_pattern = re.compile(r"^Départ\s+(\[[^\]]+\])$", re.IGNORECASE)
tries_pattern = re.compile(r"(\d+)\s+essais?\s+restants?", re.IGNORECASE)
coordinate_pattern = re.compile(r"-?\d{1,3},\s*-?\d{1,3}")


def parse_ocr_output(lines):
    """Extract Étape, Départ, Zone (the next line after Départ), Hints, and Remaining Tries."""
    data = {
        "startPos": None,
        "startPosDescription": None,
        "step": None,
        "totalSteps": None,
        "hints": [],
        "remainingTries": None,
    }

    expect_startPosDescription = False
    collecting_hints = False

    for line in lines:
        line = line.strip()
        if not line:
            continue
        print(
            f"Processing line: '{line}'"
        )  # Debugging: Print each line being processed

        match = re.search(r"Départ\s+(\[[^\]]+\])", line)
        if match:
            line = f"Départ {match.group(1)}"  # Return sanitized line

        # 1) Étape
        m_steps = steps_pattern.search(line)
        if m_steps:
            data["step"] = int(m_steps.group(1))  # Extract x
            data["totalSteps"] = int(m_steps.group(2))  # Extract y
            print(f"Found Étape: {data['step']}/{data['totalSteps']}")
            continue

        # 2) Départ
        m_startPos = startPos_pattern.search(line)
        if m_startPos:
            coords = m_startPos.group(1).strip("[]")  # Remove square brackets
            try:
                x, y = map(
                    int, coords.split(",")
                )  # Split on comma and convert to integers
                print(f"Extracted coordinates: x={x}, y={y}")
                data["startPos"] = [x, y]  # Store as a list
            except ValueError:
                print(f"Invalid coordinate format: {coords}")
                data["startPos"] = None  # Set to None if parsing fails
            expect_startPosDescription = True
            collecting_hints = False
            continue

        # 3) Text under Départ (startPosDescription)
        if expect_startPosDescription:
            data["startPosDescription"] = line
            print(f"Found startPosDescription: {data['startPosDescription']}")
            expect_startPosDescription = False
            collecting_hints = True
            continue

        # 4) Remaining Tries
        m_tries = tries_pattern.search(line)
        if m_tries:
            data["remainingTries"] = int(m_tries.group(1))
            print(f"Found Remaining Tries: {data['remainingTries']}")
            collecting_hints = False
            continue

        # 5) Hints
        if collecting_hints:
            data["hints"].append({"hintText": line})
            print(f"Found hint: {line}")

    return data


async def read_coordinates_from_image(screenshot, retries=3):
    for attempt in range(retries):
        try:
            # Preprocess the image
            preprocessed_image = preprocess_image(screenshot)

            # Pass the preprocessed image to winocr
            result = await winocr.recognize_pil(preprocessed_image, "fr")

            print("Player position text (OCR output):")
            for line_obj in result.lines:
                print(line_obj.text)  # Debugging: Print each OCR line

                # Extract coordinates using the regex
                match = coordinate_pattern.search(line_obj.text.strip())
                if match:
                    # Parse the coordinates into x and y
                    x, y = map(int, match.group(0).split(","))
                    print(f"Found coordinates: x={x}, y={y}")
                    return json.dumps({"playerPos": [x, y]}, ensure_ascii=False)

            print("No coordinates found in the image.")
        except Exception as e:
            print(f"Attempt {attempt + 1} failed with error: {e}")

        print("Retrying...")

    print("Failed to retrieve player position after retries.")
    return json.dumps({"playerPos": None}, ensure_ascii=False)


async def read_hunt_from_screenshot(screenshot, retries=3):
    """Processes an image and extracts hunt information. Handles player position if required."""
    for attempt in range(retries):
        try:
            # Preprocess the provided screenshot
            preprocessed_image = preprocess_image(screenshot)
            result = await winocr.recognize_pil(preprocessed_image, "fr")

            # Fix misread brackets in the entire recognized text
            corrected_full_text = fix_brackets_pattern.sub(r"\1]", result.text)
            print("Full text (corrected):")
            print(corrected_full_text)

            print("\nLines (corrected):")
            corrected_lines = []
            for line_obj in result.lines:
                # Fix brackets per line
                line_corrected = fix_brackets_pattern.sub(r"\1]", line_obj.text)
                line_corrected = line_corrected.strip()
                if line_corrected:
                    corrected_lines.append(line_corrected)
                    print(line_corrected)

            # Parse the corrected lines into structured data
            parsed_data = parse_ocr_output(corrected_lines)

            # Output as JSON
            print("\nParsed JSON:")
            json_result = json.dumps(parsed_data, indent=2, ensure_ascii=False)
            print(json_result)

            return json_result  # Successfully processed
        except Exception as e:
            print(f"Attempt {attempt + 1} failed with error: {e}")

        print("Retrying...")

    print("Failed to process the screenshot after retries.")
    return json.dumps({"error": "Failed to process screenshot"}, ensure_ascii=False)


def preprocess_image(screenshot):
    """Preprocess the image to improve OCR accuracy."""
    image = screenshot.convert("RGB")

    # Upscale the image
    width, height = image.size
    upscale_factor = 3
    image = image.resize(
        (width * upscale_factor, height * upscale_factor), Image.Resampling.LANCZOS
    )

    # Convert to grayscale
    image = image.convert("L")

    # Increase contrast
    enhancer = ImageEnhance.Contrast(image)
    image = enhancer.enhance(2)

    return image
